#!/usr/bin/env python3
"""
edgar_dense.py — Dense EDGAR 8-K enumeration helper.

Walks SEC EDGAR's structured submissions endpoint for a given CIK and returns
EVERY 8-K filing across the company's full filing history (not a sampled
subset). For each 8-K, the filing's own index.json is inspected to detect a
press-release exhibit (Exhibit 99.1 / 99.2 / 99 with a .htm/.txt filename).

Why this exists: the original enumerator hit efts.sec.gov's full-text search
backend with q="press release". That backend has a hard result cap and won't
return matches for filings whose body text doesn't contain the literal phrase
"press release", which makes it useless for high-volume mature filers (e.g.
Abbott, J&J, P&G). The dense walker uses the deterministic submissions index
instead, so every 8-K on file is considered.

SEC compliance:
  - User-Agent header (from SEC_USER_AGENT env or a sensible default)
  - Default 120 ms between requests (~8 req/sec, well under the 10 req/sec cap)
  - Exponential backoff on HTTP 429/503 (3 attempts: 1s, 2s, 4s)
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from html.parser import HTMLParser


SEC_USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "press-release-archiver/1.0 (https://github.com/nemock/press-release-archiver) "
    "contact: your-email@example.com",
)


# ---------------------------------------------------------------------------
# HTTP transport with throttle + retry
# ---------------------------------------------------------------------------

class EdgarClient:
    """Tiny rate-limited / retrying HTTP client for SEC endpoints. The SEC
    fair-access policy caps unauthenticated callers at ~10 req/sec and asks for
    a descriptive User-Agent header; we honor both."""

    def __init__(self, delay_ms=120, max_attempts=3):
        self.delay = delay_ms / 1000.0
        self.max_attempts = max_attempts
        self._last_call = 0.0
        self._req_count = 0

    def _throttle(self):
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_call = time.monotonic()

    def get_json(self, url, timeout=30):
        return json.loads(self._get_bytes(url, timeout))

    def get_text(self, url, timeout=30):
        return self._get_bytes(url, timeout).decode("utf-8", errors="replace")

    def _get_bytes(self, url, timeout):
        last_err = None
        for attempt in range(self.max_attempts):
            self._throttle()
            self._req_count += 1
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": SEC_USER_AGENT,
                                  "Accept-Encoding": "identity"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code in (429, 503):
                    # Backoff: 1s, 2s, 4s
                    wait = 2 ** attempt
                    time.sleep(wait)
                    continue
                raise
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = e
                time.sleep(2 ** attempt)
                continue
        raise last_err

    @property
    def request_count(self):
        return self._req_count


# ---------------------------------------------------------------------------
# Submissions index walk
# ---------------------------------------------------------------------------

def _iter_filings_for_cik(client, cik_padded):
    """Yield filing rows (each a dict with at least accessionNumber, form,
    filingDate, primaryDocument, primaryDocDescription) across the entire
    history of a CIK.

    data.sec.gov/submissions/CIK{padded10}.json gives the most recent
    1000 filings inline. Older filings live in shard files referenced via
    `filings.files[]`. We walk both."""
    root = client.get_json(
        f"https://data.sec.gov/submissions/CIK{cik_padded}.json")
    yield from _iter_recent_block(root.get("filings", {}).get("recent", {}))
    for shard in root.get("filings", {}).get("files", []):
        shard_url = f"https://data.sec.gov/submissions/{shard['name']}"
        shard_data = client.get_json(shard_url)
        # Shard structure mirrors the `recent` block at the top level
        yield from _iter_recent_block(shard_data)


def _iter_recent_block(block):
    """The submissions endpoint stores filings as parallel arrays. Zip them
    back into per-filing dicts. Tolerant of missing fields in older shards."""
    n = len(block.get("accessionNumber", []))
    keys = ("accessionNumber", "form", "filingDate", "reportDate",
            "primaryDocument", "primaryDocDescription", "items")
    for i in range(n):
        row = {}
        for k in keys:
            arr = block.get(k, [])
            row[k] = arr[i] if i < len(arr) else None
        yield row


# ---------------------------------------------------------------------------
# Per-filing exhibit discovery
# ---------------------------------------------------------------------------

# Match documents whose "type" indicates a press release attached to an 8-K.
# EX-99.1 and EX-99.2 are the common ones. Some filings use plain "EX-99".
PR_EXHIBIT_TYPE_RE = re.compile(r"^EX-99(\.\d+)?$", re.I)

# Filenames that look like press releases vs. supporting documents (XBRL,
# auditor consents, etc.). We accept .htm/.html/.txt and reject obvious noise.
PR_FILENAME_RE = re.compile(r"\.(htm|html|txt)$", re.I)
NOISE_FILENAME_RE = re.compile(
    r"(xbrl|metalinks|filing[-_]?summary|graphic|chart|exhibit99\.sch)",
    re.I)


class _FilingIndexParser(HTMLParser):
    """Parses the EDGAR filing-index HTML page and yields (type, name) tuples
    for each document row in the Document Format Files / Data Files tables.

    The index.json endpoint returns generic icon types (text.gif, image2.gif)
    instead of true SEC document types, so we have to read the human-readable
    HTML page where the Type column is correct."""

    def __init__(self):
        super().__init__()
        self.rows = []      # list of dicts with "type" and "name"
        self._in_table = False
        self._in_tr = False
        self._in_td = False
        self._row_cells = []
        self._cell_text = []
        self._cell_href = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs_d = dict(attrs)
        if tag == "table":
            self._in_table = True
        elif tag == "tr" and self._in_table:
            self._in_tr = True
            self._row_cells = []
        elif tag == "td" and self._in_tr:
            self._in_td = True
            self._cell_text = []
            self._cell_href = None
        elif tag == "a" and self._in_td:
            self._cell_href = attrs_d.get("href")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "td" and self._in_td:
            text = "".join(self._cell_text).strip()
            self._row_cells.append({"text": text, "href": self._cell_href})
            self._in_td = False
        elif tag == "tr" and self._in_tr:
            # Document Format Files table is the one we want. Columns vary
            # slightly across years but the row consistently has at least:
            #   Seq | Description | Document (with href) | Type | Size
            # We match by looking for a cell whose text looks like a doc type
            # and another whose href looks like a filing artifact.
            doc_type = None
            doc_name = None
            for c in self._row_cells:
                if c["text"] and EX_TYPE_TEXT_RE.match(c["text"]):
                    doc_type = c["text"]
                if c["href"] and (c["href"].lower().endswith(".htm") or
                                  c["href"].lower().endswith(".html") or
                                  c["href"].lower().endswith(".txt")):
                    # Strip any iXBRL viewer wrapper (/ix?doc=…)
                    href = c["href"]
                    if "/ix?doc=" in href:
                        href = href.split("/ix?doc=", 1)[1]
                    doc_name = href.rsplit("/", 1)[-1]
            if doc_type and doc_name:
                self._row_cells_dump(doc_type, doc_name)
            self._in_tr = False
        elif tag == "table":
            self._in_table = False

    def handle_data(self, data):
        if self._in_td:
            self._cell_text.append(data)

    def _row_cells_dump(self, doc_type, doc_name):
        self.rows.append({"type": doc_type, "name": doc_name})


# Match the Type cell text. Common values: "EX-99.1", "EX-99.2", "EX-99",
# "EX-99.1 CHARTER", etc. We accept the EX-99[.N] prefix and screen out
# obvious non-PR sub-types in find_press_release_exhibits below.
EX_TYPE_TEXT_RE = re.compile(r"^EX-99(\.\d+)?\b", re.I)

# Sub-type tokens that disqualify even an EX-99.x exhibit from being a PR
# (governance docs, slide decks, side letters, etc.).
NON_PR_TYPE_TOKENS = (
    "PRESENTATION", "SLIDE", "DECK", "CHARTER", "BYLAWS", "BY-LAWS",
    "CONSENT", "INDEMNIFICATION", "OPINION", "WAIVER", "AGREEMENT",
    "AMENDMENT", "STOCK PURCHASE", "VOTING AGREEMENT", "PLAN OF MERGER",
)


def find_press_release_exhibits(client, cik_int, accession):
    """Fetch the filing's human-readable index page (`-index.htm`) and return
    a list of dicts describing each press-release-style exhibit found.
    Returns [] if the index can't be loaded or no PR exhibits exist.

    The index.json endpoint returns useless icon types ("text.gif") instead of
    document types — that's why we parse the HTML index page, which has the
    correct Type column in its Document Format Files table.
    """
    acc_nodash = accession.replace("-", "")
    url = (f"https://www.sec.gov/Archives/edgar/data/"
           f"{cik_int}/{acc_nodash}/{accession}-index.htm")
    try:
        html = client.get_text(url)
    except urllib.error.HTTPError:
        return []

    parser = _FilingIndexParser()
    try:
        parser.feed(html)
    except Exception:
        return []

    out = []
    for r in parser.rows:
        item_type = r["type"].upper()
        item_name = r["name"]
        # Must be an EX-99 prefix
        if not EX_TYPE_TEXT_RE.match(item_type):
            continue
        # Must be a readable document (filename), not a noise artifact
        if not PR_FILENAME_RE.search(item_name):
            continue
        if NOISE_FILENAME_RE.search(item_name):
            continue
        # Reject EX-99.x sub-types that are clearly not press releases
        if any(tok in item_type for tok in NON_PR_TYPE_TOKENS):
            continue
        out.append({"type": r["type"], "name": item_name})
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def enumerate_dense(cik, start_year=None, end_year=None,
                    delay_ms=120, max_filings=5000, progress_every=100,
                    log=print):
    """Walk every 8-K filing under CIK and return (date, accession, description)
    tuples for those with a press-release exhibit.

    Args:
        cik: 10-digit zero-padded CIK string (e.g. "0000001800")
        start_year: lower bound (inclusive). None = no lower bound.
        end_year: upper bound (inclusive). None = current year.
        delay_ms: politeness delay between SEC requests
        max_filings: safety cap (warns + truncates if hit)
        progress_every: log a progress line every N 8-Ks examined
        log: callable for progress messages (default: print)

    Returns:
        List of (filing_date, accession_with_dashes, description) tuples,
        sorted ascending by date. Description is "EX-99.x ({filename})" — used
        as a hint by downstream merge logic; the real headline comes from the
        press release body during the fetch stage.
    """
    if not cik:
        return []
    cik_padded = cik.zfill(10)
    cik_int = str(int(cik_padded))
    end_year = end_year or datetime.now().year

    client = EdgarClient(delay_ms=delay_ms)
    log(f"  enumerating EDGAR 8-Ks for CIK {cik_padded} "
        f"(years {start_year or 'any'}–{end_year}, "
        f"delay {delay_ms} ms)…")

    rows = []
    examined = 0
    eight_k_seen = 0
    capped = False
    for filing in _iter_filings_for_cik(client, cik_padded):
        if filing.get("form") not in ("8-K", "8-K/A"):
            continue
        date = filing.get("filingDate") or ""
        if not date:
            continue
        year = int(date[:4])
        if start_year and year < start_year:
            continue
        if year > end_year:
            continue

        eight_k_seen += 1
        accession = filing.get("accessionNumber")
        if not accession:
            continue

        if eight_k_seen > max_filings:
            log(f"  WARN: hit --max-filings cap ({max_filings}); "
                f"truncating. Re-run with a higher --max-filings to capture more.")
            capped = True
            break

        exhibits = find_press_release_exhibits(client, cik_int, accession)
        if not exhibits:
            continue

        # Use the first matching exhibit's name as the descriptor. Multiple
        # press releases on a single 8-K is rare but possible (we still emit
        # one manifest entry per 8-K; the downstream fetcher walks all
        # exhibits when it actually pulls the body).
        primary = exhibits[0]
        desc = f"{primary['type']} ({primary['name']})"
        rows.append((date, accession, desc))

        examined += 1
        if examined % progress_every == 0:
            log(f"  enumerating EDGAR 8-Ks for CIK {cik_padded}: "
                f"{examined} press releases (out of {eight_k_seen} 8-Ks seen)")

    rows.sort()
    log(f"  done: {len(rows)} press releases across {eight_k_seen} 8-Ks "
        f"({client.request_count} SEC requests)"
        + (" — CAP HIT" if capped else ""))
    return rows
