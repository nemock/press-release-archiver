#!/usr/bin/env python3
"""
Stage 1 of the press-release-archiver skill.

Discovers every press release for a given company by combining:
  - SEC EDGAR (dense walk via data.sec.gov submissions) — public companies
  - Business Wire / GlobeNewswire / PR Newswire searches via WebSearch
  - The company's own newsroom (when a URL is provided)

Outputs a manifest.json the fetch.py stage consumes.

CHANGELOG
  - 2026-05-21  EDGAR enumeration switched from efts.sec.gov full-text search
                to a dense walk of data.sec.gov/submissions (every 8-K, not
                just those matching a phrase query). Added --start-year /
                --end-year / --edgar-delay / --max-filings / --edgar-sample.
                Old FTS sampler is still reachable for spot-checks via
                --edgar-sample.
  - (See git log for earlier history.)

The second positional argument is auto-detected:
  - Looks like a ticker (1-5 uppercase letters, optional .X share class) → public-company mode
  - Looks like a URL or bare domain → URL-anchored mode; still probes EDGAR by name
    to detect if the company happens to be public

Usage:
  # Public company by ticker (auto-detected)
  python3 discover.py "Stryker" SYK --out stryker_manifest.json

  # Private / pre-IPO company by URL (auto-detected)
  python3 discover.py "Vicarious Surgical" https://vicarioussurgical.com --out manifest.json

  # Narrow EDGAR walk to a date range
  python3 discover.py "Abbott" ABT --start-year 2015 --end-year 2024 --out abbott.json

  # Use the old sparse FTS sampler instead of the dense walker
  python3 discover.py "Abbott" ABT --edgar-sample --out abbott_quick.json

  # Explicit flags (still supported)
  python3 discover.py "Acme Medtech" --ticker ACME --out manifest.json
  python3 discover.py "Acme Medtech" --url https://acme.example --out manifest.json

EDGAR compliance: set SEC_USER_AGENT in your environment to a string the SEC
can identify (e.g. "your-project/1.0 you@example.com"). Defaults to a generic
identifier if unset.

Note: this is a SKETCH. The wire/newsroom search step is stubbed —
it should be wired to whatever search transport the skill environment
provides (WebSearch tool, SerpAPI, etc.). The EDGAR path is fully implemented.
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

# Dense EDGAR enumeration helper (lives in the same archiver/ package).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import edgar_dense  # noqa: E402

USER_AGENT_SEC = "Press Release Archiver Skill your-email@example.com"


# ---------------------------------------------------------------------------
# Input disambiguation
# ---------------------------------------------------------------------------

TICKER_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")


def detect_disambiguator(value):
    """Classify a bare disambiguator argument as 'ticker' or 'url'.

    Tickers: 1-5 uppercase letters, optional .X share-class suffix (BRK.A).
    Anything else with a scheme or domain-shaped substring is treated as a URL.
    Returns (kind, normalized_value). For URLs, a missing https:// scheme is added.
    Returns (None, None) when the value matches neither shape.
    """
    if not value:
        return (None, None)
    v = value.strip()
    if TICKER_RE.match(v):
        return ("ticker", v)
    # URL: has scheme, or has at least one dot with a 2+ char TLD-ish tail
    if "://" in v or re.search(r"\w+\.[A-Za-z]{2,}", v):
        if "://" not in v:
            v = "https://" + v.lstrip("/")
        return ("url", v)
    return (None, None)


def extract_domain(url):
    """Return the bare hostname (no scheme, no www., no path) for a URL."""
    if not url:
        return None
    u = url if "://" in url else "https://" + url
    netloc = urllib.parse.urlparse(u).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc or None


# ---------------------------------------------------------------------------
# CIK lookup
# ---------------------------------------------------------------------------

def find_cik(company_name, ticker=None):
    """Resolve a company name (and optional ticker) to a 10-digit CIK.

    Strategy:
      1. If ticker provided, use the SEC's company_tickers.json (~40k row index).
         A ticker hit is high-confidence.
      2. Otherwise, search EDGAR's company browse endpoint by name. Name-only
         hits are flagged lower-confidence — caller may want to confirm before
         treating as public.

    Returns (cik, resolved_name, confidence) where confidence is one of:
      'exact'      — ticker matched, or name match with the search term as a
                     substring of the resolved title (high confidence)
      'fuzzy'      — name search returned rows but none contained the search
                     term as a substring (low confidence; first row returned)
      'none'       — no rows returned at all
    """
    if ticker:
        url = "https://www.sec.gov/files/company_tickers.json"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT_SEC})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        T = ticker.upper()
        for row in data.values():
            if row["ticker"].upper() == T:
                cik = str(row["cik_str"]).zfill(10)
                return cik, row["title"], "exact"
        # Fall through to name search if ticker not found

    # Name-based search
    name_q = urllib.parse.quote_plus(company_name)
    url = (f"https://www.sec.gov/cgi-bin/browse-edgar?"
           f"action=getcompany&company={name_q}&type=8-K&dateb=&owner=include"
           f"&count=10&action=getcompany")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT_SEC})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None, None, "none"

    matches = re.findall(r'CIK=(\d{10})[^>]*>([^<]+)</a>', html)
    if not matches:
        return None, None, "none"
    target = company_name.lower()
    for cik, name in matches:
        if target in name.lower():
            return cik, name, "exact"
    return matches[0][0], matches[0][1], "fuzzy"


# ---------------------------------------------------------------------------
# EDGAR enumeration
# ---------------------------------------------------------------------------

# Exhibit description / file_type tokens that indicate the EX-99.x is NOT
# a press release. These exhibits get attached to 8-Ks for various reasons
# (governance, side letters, slide decks) and should be filtered out.
NON_PR_EXHIBIT_TOKENS = {
    "PRESENTATION", "SLIDE", "DECK",
    "CHARTER", "BYLAWS", "BY-LAWS",
    "CONSENT", "INDEMNIFICATION", "OPINION", "WAIVER",
    "AGREEMENT", "AMENDMENT", "STOCK PURCHASE",
    "PLAN OF MERGER", "VOTING AGREEMENT",
}


def is_press_release_exhibit(file_type, file_description):
    """Heuristic: does this EDGAR exhibit row look like a press release?

    Modern 8-K filings often label the exhibit just "EX-99.1" or "Exhibit 99.1"
    with no descriptive phrase, so we can't rely on the word "press release"
    appearing in the description. Instead: accept anything whose file_type
    starts with EX-99.1, then reject if the type/description contains a
    known non-PR keyword (governance docs, slide decks, side letters).
    """
    if not file_type.upper().startswith("EX-99.1"):
        return False
    combined = (file_type + " " + (file_description or "")).upper()
    if any(tok in combined for tok in NON_PR_EXHIBIT_TOKENS):
        return False
    return True


def enumerate_edgar_press_releases_fts(cik):
    """SAMPLER PATH — kept for spot-checks via --edgar-sample.

    Returns list of (filing_date, accession, file_description) tuples for
    8-K filings whose body text contains the literal phrase "press release",
    filtered to those with an EX-99.1 exhibit.

    Uses EDGAR's full-text search backend (efts.sec.gov). The endpoint
    requires a non-empty `q=` parameter; we use `q="press release"`. Pages
    results in batches of 100.

    Known limitations that motivated the dense walker (enumerate_edgar_dense):
      - 8-Ks whose body doesn't contain "press release" are missed.
      - The FTS result set is capped (~10K hits across all queries) and very
        high-volume filers get truncated. For Abbott (CIK 0000001800) this
        returned only ~7 entries vs. thousands of actual 8-Ks on file.

    Prefer enumerate_edgar_dense() for any production run.
    """
    cik_padded = cik  # already 10 digits
    rows = []
    seen = set()
    from_offset = 0
    while True:
        url = (f"https://efts.sec.gov/LATEST/search-index?"
               f"q=%22press+release%22&forms=8-K"
               f"&ciks={cik_padded}&from={from_offset}")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT_SEC})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 500 and from_offset > 0:
                # EDGAR occasionally 500s on later pages; the data we have so
                # far is still useful. Stop pagination.
                break
            raise

        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            break
        for hit in hits:
            src = hit["_source"]
            adsh = src.get("adsh", "")
            desc = (src.get("file_description") or "")
            ftype = src.get("file_type", "")
            date = src.get("file_date", "")
            if adsh in seen:
                continue
            if is_press_release_exhibit(ftype, desc):
                seen.add(adsh)
                rows.append((date, adsh, desc))

        from_offset += len(hits)
        if from_offset >= data["hits"]["total"]["value"]:
            break

    rows.sort()
    return rows


def enumerate_edgar_press_releases(cik, *, mode="dense", start_year=None,
                                    end_year=None, delay_ms=120,
                                    max_filings=5000):
    """Top-level EDGAR enumeration. Routes to either the dense walker
    (default; covers every 8-K) or the legacy FTS sampler (--edgar-sample).

    Both return list of (date, accession, description) tuples sorted ascending.
    """
    if mode == "sample":
        return enumerate_edgar_press_releases_fts(cik)
    return edgar_dense.enumerate_dense(
        cik,
        start_year=start_year,
        end_year=end_year,
        delay_ms=delay_ms,
        max_filings=max_filings,
    )


# ---------------------------------------------------------------------------
# Wire enumeration (Business Wire, GlobeNewswire, PR Newswire)
# ---------------------------------------------------------------------------

def enumerate_wire_releases(company_name, years, url=None):
    """Search the major wires (and the company's own newsroom) for press releases.

    SKETCH: this is a stub. In a real skill, wire it to whatever search
    transport is available (Claude's WebSearch tool, SerpAPI, etc.).
    The function should return a list of dicts:
      {"date": "YYYY-MM-DD", "headline": "...", "url": "...", "wire": "businesswire|globenewswire|prnewswire|newsroom"}
    """
    sites = ["businesswire.com", "globenewswire.com", "prnewswire.com"]
    print("  [wire-search] Stubbed. In a real skill, search:", file=sys.stderr)
    for site in sites:
        for year in years:
            print(f"    site:{site} \"{company_name}\" {year}", file=sys.stderr)
    domain = extract_domain(url) if url else None
    if domain:
        print(f"    site:{domain} \"press release\" OR news", file=sys.stderr)
    return []


# ---------------------------------------------------------------------------
# Manifest assembly
# ---------------------------------------------------------------------------

def slug_from_headline(headline, fallback):
    """Generate a URL-safe slug from a headline (max 60 chars)."""
    if not headline:
        return fallback
    s = re.sub(r"[^\w\s-]", "", headline.lower())
    s = re.sub(r"\s+", "-", s).strip("-")
    if len(s) > 60:
        s = s[:60].rsplit("-", 1)[0]
    return s or fallback


def merge_sources(edgar_rows, wire_rows, company_name):
    """Merge EDGAR + wire enumerations into a deduplicated manifest.

    Dedup key: same date (±1 day) AND a strong substring overlap on the
    headline. EDGAR entries with no headline get whatever the wire match
    found; wire entries get the EDGAR accession when present.
    """
    entries = {}

    # Pass 1: count entries per actual_date so we know which need a -<n> suffix.
    # Dense mode can produce many 8-Ks on the same day; the slug becomes the
    # output filename downstream, so collisions would silently overwrite.
    date_counts = {}
    resolved_dates = []
    for date, accession, desc in edgar_rows:
        actual_date = date
        m = re.search(r"DATED\s+(\w+)\s+(\d+),?\s+(\d{4})", desc, re.I)
        if m:
            try:
                d = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}",
                                      "%B %d %Y")
                actual_date = d.strftime("%Y-%m-%d")
            except ValueError:
                pass
        date_counts[actual_date] = date_counts.get(actual_date, 0) + 1
        resolved_dates.append(actual_date)

    # Pass 2: seed entries with disambiguated slugs.
    per_date_seq = {}
    for (date, accession, desc), actual_date in zip(edgar_rows, resolved_dates):
        per_date_seq[actual_date] = per_date_seq.get(actual_date, 0) + 1
        seq = per_date_seq[actual_date]
        slug = (f"press-release-{actual_date}"
                if date_counts[actual_date] == 1
                else f"press-release-{actual_date}-{seq}")
        entries[actual_date + "|" + accession] = {
            "date": actual_date,
            "headline": None,        # filled by fetch.py from EX-99.1 body
            "wire_url": None,
            "edgar_accession": accession,
            "slug": slug,
            "source_priority": ["edgar"],
        }

    # Layer in wire entries
    for w in wire_rows:
        wdate = w["date"]
        # Look for a same-day EDGAR row to merge
        merged = False
        for k, e in entries.items():
            if abs((datetime.strptime(e["date"], "%Y-%m-%d")
                    - datetime.strptime(wdate, "%Y-%m-%d")).days) <= 1:
                e["wire_url"] = w["url"]
                e["headline"] = w["headline"]
                e["slug"] = slug_from_headline(w["headline"], e["slug"])
                e["source_priority"] = ["edgar", "wayback"]
                merged = True
                break
        if not merged:
            slug = slug_from_headline(w["headline"], f"press-release-{wdate}")
            entries[wdate + "|wire-" + slug] = {
                "date": wdate,
                "headline": w["headline"],
                "wire_url": w["url"],
                "edgar_accession": None,
                "slug": slug,
                "source_priority": ["wayback", "chrome"],
            }

    return sorted(entries.values(), key=lambda x: x["date"])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def existing_dates_in_releases(releases_dir):
    """Scan a releases directory and return the set of YYYY-MM-DD dates
    that already have a captured release file. Used by --update mode to
    skip everything that's already been fetched."""
    dates = set()
    for p in Path(releases_dir).glob("*.md"):
        m = re.match(r"(\d{4}-\d{2}-\d{2})-", p.name)
        if m:
            dates.add(m.group(1))
    return dates


def emit_search_queries(company_name, years, url=None):
    """Emit a copy-pasteable list of search queries Claude should run.
    Returns the list as a Python list (also printed for human visibility).

    When a URL is provided, adds newsroom-targeted queries against the
    company's own domain. For private-company mode (no years known yet),
    falls back to a multi-year window ending at the current year.
    """
    queries = []
    if not years:
        this_year = datetime.now().year
        years = [str(y) for y in range(this_year - 5, this_year + 1)]
    for site in ("businesswire.com", "globenewswire.com", "prnewswire.com"):
        for year in years:
            queries.append(f'site:{site} "{company_name}" {year}')
    domain = extract_domain(url) if url else None
    if domain:
        # Capture the company's own newsroom regardless of year.
        queries.append(f'site:{domain} "press release"')
        queries.append(f'site:{domain} news')
        # Bias wire results toward releases that actually link back to the
        # company's domain — useful for disambiguating common company names.
        for year in years:
            queries.append(f'"{company_name}" "{domain}" "press release" {year}')
    return queries


def merge_wire_into_manifest(manifest, wire_rows):
    """Merge wire results (provided by Claude after running searches) into
    an existing manifest's entries list. Uses ±1 day date matching to glue
    a wire URL to an existing EDGAR row; otherwise adds a wire-only entry.
    """
    entries = manifest["entries"]
    by_key = {f"{e['date']}|{e.get('edgar_accession') or ''}": e for e in entries}

    for w in wire_rows:
        wdate = w["date"]
        merged = False
        for e in entries:
            try:
                d_e = datetime.strptime(e["date"], "%Y-%m-%d")
                d_w = datetime.strptime(wdate, "%Y-%m-%d")
                if abs((d_e - d_w).days) <= 1 and not e.get("wire_url"):
                    e["wire_url"] = w["url"]
                    if not e.get("headline"):
                        e["headline"] = w["headline"]
                    if w.get("headline") and e["slug"].startswith("press-release-"):
                        e["slug"] = slug_from_headline(w["headline"], e["slug"])
                    e["source_priority"] = ["edgar", "wayback"]
                    merged = True
                    break
            except ValueError:
                continue
        if not merged:
            slug = slug_from_headline(w.get("headline", ""), f"press-release-{wdate}")
            entries.append({
                "date": wdate,
                "headline": w.get("headline"),
                "wire_url": w["url"],
                "edgar_accession": None,
                "slug": slug,
                "source_priority": ["wayback", "chrome"],
            })

    entries.sort(key=lambda x: x["date"])
    manifest["entries"] = entries
    return manifest


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Discover press releases for a company (public or private).",
        epilog="Three modes: full discovery (default), --manifest-merge to add "
               "wire results to an existing manifest, --update for incremental.")
    ap.add_argument("company_name", nargs="?")
    ap.add_argument("disambiguator", nargs="?",
                    help="Auto-detected: a ticker (e.g. SYK) or a URL "
                         "(e.g. https://vicarioussurgical.com). Use --ticker "
                         "or --url to be explicit.")
    ap.add_argument("--ticker", default=None,
                    help="Explicit ticker symbol; takes precedence over auto-detected positional.")
    ap.add_argument("--url", default=None,
                    help="Explicit company URL; takes precedence over auto-detected positional.")
    ap.add_argument("--out", default="manifest.json")
    ap.add_argument("--pre-ipo", choices=["skip", "include"], default="skip")

    ap.add_argument("--update", metavar="RELEASES_DIR",
                    help="Incremental mode: only enumerate releases dated AFTER "
                         "the most recent file in RELEASES_DIR. Outputs a "
                         "delta-only manifest.")
    ap.add_argument("--manifest-merge", metavar="WIRE_JSON",
                    help="Merge wire results (path to JSON, or '-' for stdin) "
                         "into an existing manifest. JSON shape: list of "
                         "{date, headline, url, wire}. Requires --out to point "
                         "at the existing manifest.")
    ap.add_argument("--emit-queries", action="store_true",
                    help="Print the wire-search queries Claude should run, "
                         "then exit. Use after a fresh discover run when "
                         "preparing to gather wire URLs.")

    # EDGAR walker options
    edgar = ap.add_argument_group(
        "EDGAR enumeration",
        "Controls the SEC EDGAR 8-K walk. The dense walker is the default "
        "and covers every 8-K filing on file for the CIK; the older FTS "
        "sampler is reachable via --edgar-sample for quick spot-checks.")
    edgar.add_argument("--start-year", type=int, default=None,
                       help="Earliest filing year to include (inclusive). "
                            "Default: no lower bound (typically 1994+).")
    edgar.add_argument("--end-year", type=int, default=None,
                       help="Latest filing year to include (inclusive). "
                            "Default: current year.")
    edgar.add_argument("--edgar-sample", action="store_true",
                       help="Use the legacy efts.sec.gov full-text-search "
                            "sampler instead of the dense submissions walker. "
                            "Fast but incomplete for high-volume filers.")
    edgar.add_argument("--edgar-delay", type=int, default=120,
                       help="Politeness delay (ms) between SEC requests "
                            "(default 120; SEC cap is ~10 req/sec).")
    edgar.add_argument("--max-filings", type=int, default=5000,
                       help="Safety cap on 8-Ks examined in dense mode "
                            "(default 5000; warns if hit).")
    args = ap.parse_args()

    # ----- Mode: --manifest-merge (wire URLs piped in by Claude) -----
    if args.manifest_merge:
        if not Path(args.out).exists():
            print(f"ERROR: --manifest-merge needs an existing --out manifest "
                  f"to merge into; '{args.out}' not found", file=sys.stderr)
            sys.exit(1)
        if args.manifest_merge == "-":
            wire_rows = json.load(sys.stdin)
        else:
            wire_rows = json.loads(Path(args.manifest_merge).read_text())
        manifest = json.loads(Path(args.out).read_text())
        before = len(manifest["entries"])
        manifest = merge_wire_into_manifest(manifest, wire_rows)
        Path(args.out).write_text(json.dumps(manifest, indent=2))
        added = len(manifest["entries"]) - before
        print(f"Merged {len(wire_rows)} wire rows into {args.out}.")
        print(f"  Net new entries: {added}; updated existing: {len(wire_rows) - added}")
        return

    # ----- Modes that require company_name -----
    if not args.company_name:
        ap.error("company_name is required (unless using --manifest-merge)")

    # Auto-detect the positional disambiguator if --ticker / --url not given.
    ticker = args.ticker
    url = args.url
    if args.disambiguator and not (ticker or url):
        kind, value = detect_disambiguator(args.disambiguator)
        if kind == "ticker":
            ticker = value
        elif kind == "url":
            url = value
        else:
            print(f"ERROR: could not classify '{args.disambiguator}' as ticker or URL. "
                  f"Use --ticker or --url to be explicit.", file=sys.stderr)
            sys.exit(1)

    # Always try EDGAR — a URL-anchored company may still turn out to be public.
    print(f"Resolving CIK for {args.company_name}"
          f"{f' ({ticker})' if ticker else ''}...")
    cik, resolved_name, confidence = find_cik(args.company_name, ticker)
    if cik and confidence == "exact":
        print(f"  CIK {cik} = {resolved_name}")
        is_public = True
    elif cik and confidence == "fuzzy":
        # Name-only match with no substring agreement — likely the wrong company.
        # Be conservative: treat as private unless an explicit ticker was given.
        if ticker:
            print(f"  CIK {cik} = {resolved_name} (fuzzy match accepted: ticker was explicit)")
            is_public = True
        else:
            print(f"  Fuzzy EDGAR match found ({resolved_name}, CIK {cik}) "
                  f"but rejected — no ticker to confirm. Treating as private.")
            cik = None
            is_public = False
    else:
        if ticker:
            print(f"ERROR: ticker '{ticker}' did not resolve to an SEC CIK.",
                  file=sys.stderr)
            sys.exit(1)
        print(f"  No EDGAR match — treating as private / pre-IPO.")
        is_public = False

    edgar_rows = []
    if is_public and cik:
        mode = "sample" if args.edgar_sample else "dense"
        if mode == "sample":
            print(f"Enumerating EDGAR 8-K press releases for CIK {cik} "
                  f"(sampler mode — incomplete on high-volume filers)...")
        else:
            print(f"Enumerating EDGAR 8-K press releases for CIK {cik} "
                  f"(dense walk, years {args.start_year or 'any'}–{args.end_year or 'now'})...")
        edgar_rows = enumerate_edgar_press_releases(
            cik,
            mode=mode,
            start_year=args.start_year,
            end_year=args.end_year,
            delay_ms=args.edgar_delay,
            max_filings=args.max_filings,
        )
        print(f"  Found {len(edgar_rows)} press releases on EDGAR")

    # ----- Mode: --update (incremental, narrow to net-new) -----
    if args.update:
        existing = existing_dates_in_releases(args.update)
        if existing:
            cutoff = max(existing)
            print(f"  Existing archive max date: {cutoff} "
                  f"({len(existing)} releases on disk)")
            edgar_rows = [r for r in edgar_rows if r[0] > cutoff]
            if is_public:
                print(f"  After cutoff filter: {len(edgar_rows)} new EDGAR entries")
        else:
            print(f"  No existing releases found in {args.update}; full enumeration.")

    years = sorted({r[0][:4] for r in edgar_rows})
    if args.pre_ipo == "include" and years and not args.update:
        first = int(years[0])
        years = [str(y) for y in range(first - 5, int(years[-1]) + 1)]

    if args.emit_queries:
        print()
        print("Wire-search queries to run (one per line):")
        for q in emit_search_queries(args.company_name, years, url=url):
            print(f"  {q}")
        print()
        print("Format wire results as JSON list of {date, headline, url, wire},")
        print(f"then merge: python3 discover.py --manifest-merge results.json --out {args.out}")
        sys.exit(0)

    print(f"Searching wires for {args.company_name} (stub — emit queries with --emit-queries)...")
    wire_rows = enumerate_wire_releases(args.company_name, years, url=url)
    print(f"  Found {len(wire_rows)} wire releases")

    manifest = {
        "company_name": resolved_name or args.company_name,
        "ticker": ticker,
        "cik": cik,
        "url": url,
        "is_public": is_public,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "update" if args.update else "full",
        "entries": merge_sources(edgar_rows, wire_rows, args.company_name),
    }

    Path(args.out).write_text(json.dumps(manifest, indent=2))
    print(f"\nManifest written: {args.out}")
    print(f"  {len(manifest['entries'])} entries")
    by_year = {}
    for e in manifest["entries"]:
        by_year[e["date"][:4]] = by_year.get(e["date"][:4], 0) + 1
    print("  Year breakdown:", ", ".join(f"{y}: {c}" for y, c in sorted(by_year.items())))
    if not args.update:
        print()
        if is_public:
            print("Next: run wire searches to capture non-EDGAR releases. Use:")
        else:
            print("Next: run wire + newsroom searches (no EDGAR available for private mode):")
        disambig = ""
        if ticker:
            disambig = f"--ticker {ticker} "
        elif url:
            disambig = f"--url {url} "
        print(f"  python3 discover.py {repr(args.company_name)} {disambig}--emit-queries")


if __name__ == "__main__":
    main()
