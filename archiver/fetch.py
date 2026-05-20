#!/usr/bin/env python3
"""
Stage 2 of the press-release-archiver skill — the tiered fetcher.

For each manifest entry, tries (in order):
  Tier 1 — SEC EDGAR EX-99.1 exhibit (curl + User-Agent)
  Tier 2 — Wayback Machine snapshot of the wire URL (urllib + browser UA)
  Tier 3 — Live wire URL via Chrome Connector (orchestrated by Claude;
           HTML is piped in via stdin using --inject mode)

Usage:
  # Standard run (writes whatever it can; emits pending_chrome.json for the rest)
  python3 fetch.py manifest.json --out releases/

  # Inject mode: Claude has fetched HTML via Chrome MCP and is piping it in
  echo "<html>..." | python3 fetch.py --inject <slug> --manifest manifest.json --out releases/

This sketch lifts the parsing/cleaning code from the project's original
fetch_releases.py — that code is battle-tested against ~60 real releases.
For a real skill, factor it into lib/parse.py.
"""

import argparse
import html as html_mod
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

USER_AGENT_SEC = "Press Release Archiver Skill your-email@example.com"
USER_AGENT_BROWSER = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# HTTP transport
# ---------------------------------------------------------------------------

def fetch(url, user_agent, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        try:
            return resp.geturl(), data.decode("utf-8")
        except UnicodeDecodeError:
            return resp.geturl(), data.decode("latin-1", errors="replace")


# ---------------------------------------------------------------------------
# Tier 1 — EDGAR
# ---------------------------------------------------------------------------

def edgar_index_url(accession, cik):
    nodash = accession.replace("-", "")
    cik_int = str(int(cik))
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{nodash}/{accession}-index.htm"


def find_ex991_in_index(index_html):
    rows = re.split(r"<tr[^>]*>", index_html, flags=re.I)
    for row in rows:
        if "EX-99.1" in row.upper():
            m = re.search(r'href="(/Archives/[^"]+\.htm)"', row)
            if m:
                return "https://www.sec.gov" + m.group(1)
    return None


def fetch_tier1_edgar(accession, cik):
    """Returns (source_url, body_html) or (None, None) on failure."""
    idx_url = edgar_index_url(accession, cik)
    try:
        _, idx_html = fetch(idx_url, USER_AGENT_SEC)
    except Exception:
        return None, None
    ex_url = find_ex991_in_index(idx_html)
    if not ex_url:
        return None, None
    try:
        _, body_html = fetch(ex_url, USER_AGENT_SEC)
        return ex_url, body_html
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# Tier 2 — Wayback Machine
# ---------------------------------------------------------------------------

def fetch_tier2_wayback(wire_url, year_hint=None):
    """Returns (source_url, body_html) or (None, None) on failure."""
    if not wire_url:
        return None, None
    when = year_hint or "2024"
    wb = f"https://web.archive.org/web/{when}/{wire_url}"
    try:
        final_url, body = fetch(wb, USER_AGENT_BROWSER, timeout=45)
        return final_url, body
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# HTML → text  (lifted from project's fetch_releases.py)
# ---------------------------------------------------------------------------

class TextExtractor(HTMLParser):
    BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5",
                  "h6", "section", "article", "blockquote", "td"}
    SKIP_TAGS = {"script", "style", "noscript", "head", "nav", "footer",
                 "form", "button", "svg", "iframe"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_depth = 0
        self.in_wayback_toolbar = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs_d = dict(attrs)
        if tag == "div" and attrs_d.get("id") in ("wm-ipp-base", "wm-ipp"):
            self.skip_depth += 1
            self.in_wayback_toolbar = True
            return
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
            return
        if tag in self.BLOCK_TAGS and self.skip_depth == 0:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.SKIP_TAGS or self.in_wayback_toolbar:
            if self.skip_depth > 0:
                self.skip_depth -= 1
            if self.skip_depth == 0:
                self.in_wayback_toolbar = False
            return
        if tag in self.BLOCK_TAGS and self.skip_depth == 0:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip_depth == 0:
            self.parts.append(data)

    def handle_entityref(self, name):
        if self.skip_depth == 0:
            try:
                self.parts.append(html_mod.unescape(f"&{name};"))
            except Exception:
                pass

    def handle_charref(self, name):
        if self.skip_depth == 0:
            try:
                self.parts.append(html_mod.unescape(f"&#{name};"))
            except Exception:
                pass

    def text(self):
        raw = "".join(self.parts)
        lines = [re.sub(r"[ \t\xa0]+", " ", line).strip() for line in raw.split("\n")]
        out, prev_blank = [], False
        for line in lines:
            if not line:
                if not prev_blank:
                    out.append("")
                prev_blank = True
            else:
                out.append(line)
                prev_blank = False
        return "\n".join(out).strip()


def html_to_text(body_html):
    p = TextExtractor()
    p.feed(body_html)
    return p.text()


# ---------------------------------------------------------------------------
# Cleaners + headline extraction
# (Lifted directly from the working project script — already tested on 64 releases.)
# ---------------------------------------------------------------------------

DATELINE_RE = re.compile(r"\bBUSINESS\s*WIRE\b|\bGLOBE\s*NEWSWIRE\b|/PRNewswire/", re.I)


def looks_like_dateline_start(line):
    """Conservative dateline detector. Triggers on:
      - Explicit wire markers (BUSINESS WIRE, GLOBE NEWSWIRE, /PRNewswire/)
      - CITY, STATE patterns that ALSO contain a 4-digit year (real datelines
        always have a date; without the year requirement we'd match person
        names like 'Keith R. Leonard, Jr.' or company names like
        'Globex Corp, Inc.').
    """
    if DATELINE_RE.search(line):
        return True
    if (re.match(r"^[A-Z][A-Za-z .]+,\s*[A-Z][a-zA-Z.]+", line)
            and re.search(r"\b(19|20)\d{2}\b", line)):
        return True
    return False


def clean_edgar_body(text):
    text = re.sub(r"^\s*EX-99\.\d+\s+\d+\s+\S+\.htm\s+[^\n]*\n", "", text)
    text = re.sub(r"^\s*Exhibit\s+99\.\d+\s*\n", "", text, flags=re.I)
    return text.strip()


def clean_wire_body(text):
    """Generic wire/Wayback/syndicate cleaner. Strips toolbars, navigation,
    and trailing junk."""
    m = re.search(r"(BUSINESS WIRE|GLOBE NEWSWIRE|/PRNewswire/|PR Newswire)",
                  text, flags=re.I)
    if m:
        idx = m.start()
        prefix = text[:idx]
        lines = prefix.split("\n")
        keep_from = 0
        for i in range(len(lines) - 1, max(-1, len(lines) - 30), -1):
            L = lines[i].strip()
            low = L.lower()
            if (len(L) > 20
                    and not low.startswith(("home", "search", "menu", "share",
                                             "save", "press", "wayback",
                                             "web archive", "news provided by",
                                             "modal title", "subscribe",
                                             "twitter", "linkedin", "facebook"))
                    and "wayback" not in low
                    and "log in" not in low
                    and "sign up" not in low):
                keep_from = i
                break
        text = "\n".join(lines[keep_from:]) + text[idx:]

    cut_markers = [
        r"\bView source version on (?:businesswire|globenewswire)\.com",
        r"\bMultimedia Files:",
        r"\bSAVED PAGES\b",
        r"\bWAYBACK MACHINE\b",
        r"\bSOURCE\s+\w",
        r"\bRelated Links\b",
        r"\bModal title\b",
        r"\bSearch\s*\n+\s*Log In\b",
        r"\bShare this article\b",
        r"\bGet daily news updates",
        r"\bRecommended\s*\n",
        r"\bMore from BioSpace\b",
    ]
    for marker in cut_markers:
        text = re.split(marker, text, maxsplit=1, flags=re.I)[0]

    text = dedupe_trailing_block(text, "Contacts")
    text = dedupe_trailing_block(text, "Investor Contact")
    return text.strip()


def dedupe_trailing_block(text, marker):
    pat = re.compile(rf"(^|\n)\s*{re.escape(marker)}\s*(\n|$)", re.I)
    matches = list(pat.finditer(text))
    if len(matches) < 2:
        return text
    a_start, b_start = matches[-2].start(), matches[-1].start()
    block_a, block_b = text[a_start:b_start].strip(), text[b_start:].strip()
    if abs(len(block_a) - len(block_b)) < 200 and len(block_b) > 30:
        return text[:b_start].rstrip()
    return text


def strip_leading_headline_dup(body, headline):
    def norm(s):
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s)).strip().lower()
    nh = norm(headline)
    if not nh:
        return body
    lines = body.split("\n")
    found = -1
    accumulator = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        accumulator.append(line.strip())
        candidate = norm(" ".join(accumulator))
        if candidate == nh or (len(candidate) > 10
                                and candidate.startswith(nh[:max(20, len(nh))])):
            found = i
            break
        if len(accumulator) >= 4:
            break
    if found >= 0:
        j = found + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        return "\n".join(lines[j:]).strip()
    return body


PREAMBLE_PREFIXES = (
    "press release",
    "exhibit",
    "contact:", "contact ",
    "contacts:", "contacts ",
    "source:",
    "for immediate release",
    "for further information",
    "investor relations",
    "media contact",
    "investor contact",
    "monday ", "tuesday ", "wednesday ", "thursday ",
    "friday ", "saturday ", "sunday ",  # day-of-week timestamp lines
)
# US (123) 456-7890 / 123-456-7890 / and +1-123-456-7890 international forms
PHONE_RE = re.compile(r"^\+?\d?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\s*$")


def is_preamble_line(L):
    """Lines that appear before the actual press-release headline in some
    wire / EDGAR formats: bare 'Press Release' label, contact info,
    source attribution, day-of-week timestamps, standalone phone numbers."""
    low = L.lower()
    if any(low.startswith(p) for p in PREAMBLE_PREFIXES):
        return True
    if PHONE_RE.match(L):
        return True
    return False


def is_all_caps(s):
    """Heuristic: text is mostly all caps (allows digits, punctuation, spaces)."""
    letters = [c for c in s if c.isalpha()]
    if len(letters) < 3:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters) > 0.85


_NAME_FUNCTION_WORDS = {"in", "of", "and", "to", "for", "from", "with", "by",
                        "on", "at", "the", "a", "an", "or", "as", "is", "are",
                        "was", "were", "be"}

def looks_like_contact_name(L):
    """Detect lines that look like a person's name in a contact block:
    short (2-4 words), Title Case (NOT all caps — that signals a headline),
    every word capitalized, NO lowercase function/connector words like
    'in', 'of', 'and', 'to' (those signal a real headline).
    """
    words = L.split()
    if not 1 <= len(words) <= 4:
        return False
    if len(L) > 40:
        return False
    if is_all_caps(L):
        # All-caps short lines are usually headlines (especially in modern
        # earnings releases that split headlines across blank lines).
        return False
    for w in words:
        clean = w.rstrip(",.;")
        if not clean:
            return False
        if not clean[0].isupper():
            # Lowercase first letter signals a function word ('in', 'of',
            # 'and', etc.) — meaning this isn't a name, it's a headline.
            return False
    return True


def extract_headline_and_body(text, hint=None):
    """Walk text, accumulating a multi-line headline until the dateline.
    See project's fetch_releases.py for the full battle-tested implementation —
    this is the same logic, condensed for the sketch.

    The preamble skipper is state-aware: once we've encountered a preamble
    keyword (Contacts:, FOR IMMEDIATE RELEASE, etc.) we stay in "skip mode"
    until we hit something that clearly looks like a headline (a long line,
    or an ALL CAPS line). This handles wire formats where the contact block
    contains person names + phone numbers separated by blank lines, none of
    which match a single static prefix.
    """
    raw = text.split("\n")
    i = 0
    in_contact_block = False
    while i < len(raw):
        L = raw[i].strip()
        if not L:
            i += 1
            continue
        if (L.startswith("EX-99")
                or len(L) < 6
                or is_preamble_line(L)):
            if any(L.lower().startswith(p) for p in
                   ("contact:", "contacts:", "contact ", "contacts ")):
                in_contact_block = True
            i += 1
            continue
        # In contact block: skip lines that look like person names — short,
        # 2-4 words, all words start with a capital letter, NO lowercase
        # function/connector words (in, of, and, to, for, from, with, etc.)
        # Headlines like "da Vinci Approved in Japan" contain "in" so they
        # correctly fall through.
        if in_contact_block and looks_like_contact_name(L):
            i += 1
            continue
        # Non-preamble line — stop skipping.
        break
    if i >= len(raw):
        return (hint or "Untitled", "")

    parts = []
    while i < len(raw) and len(parts) < 6:
        L = raw[i].strip()
        if not L:
            j = i + 1
            seen = []
            while j < len(raw) and len(seen) < 8:
                if raw[j].strip():
                    seen.append(j)
                j += 1
            dl = None
            for idx in seen:
                if looks_like_dateline_start(raw[idx].strip()):
                    dl = idx
                    break
            if dl is not None:
                # Decide whether the chunk between current blank and dateline
                # is (a) a continuation of the headline (glue it in) or
                # (b) a subhead / unrelated block (drop it).
                #
                # Heuristics for "this is continuation":
                #   - Headline so far ends in a "weak" word (preposition/conjunction)
                #   - All collected parts AND the next block are ALL CAPS
                #     (modern earnings releases split multi-line headlines
                #     across blank lines)
                weak = {"with", "and", "of", "by", "for", "to", "as",
                        "in", "on", "from", "the", "a", "an"}
                last_word = (parts[-1].split()[-1].lower().strip(",.;:")
                             if parts else "")
                next_block = []
                k = i + 1
                while k < dl:
                    L2 = raw[k].strip()
                    if L2:
                        next_block.append(L2)
                    k += 1

                glue = False
                if last_word in weak:
                    glue = True
                elif (parts and next_block
                      and all(is_all_caps(p) for p in parts)
                      and all(is_all_caps(n) for n in next_block)):
                    glue = True
                if glue:
                    parts.extend(next_block)
                i = dl
                break
            while i < len(raw) and not raw[i].strip():
                i += 1
            break
        if looks_like_dateline_start(L):
            break
        parts.append(L)
        i += 1

    headline = re.sub(r"\s+", " ", " ".join(parts)).strip() or hint or "Untitled"
    body_text = "\n".join(raw[i:]).strip()
    return headline, body_text


# ---------------------------------------------------------------------------
# Tags + summary
# ---------------------------------------------------------------------------

TAG_KEYWORDS = []  # populated by load_tags() at startup


def load_tags(preset_or_path, presets_file=None):
    """Load a tag taxonomy by preset name (looked up in tag_presets.json) or
    by direct path to a JSON file with shape `{tag-id: [keyword, ...]}`.
    """
    global TAG_KEYWORDS
    presets_path = presets_file or (Path(__file__).resolve().parent / "tag_presets.json")
    if Path(preset_or_path).exists():
        data = json.loads(Path(preset_or_path).read_text())
        # Custom file may either be a flat keyword map or a presets file.
        block = data if not any(k.startswith("_") for k in data) else data.get("generic", {})
    else:
        if not Path(presets_path).exists():
            raise SystemExit(f"tag preset '{preset_or_path}' requested but "
                             f"presets file not found at {presets_path}")
        all_presets = json.loads(Path(presets_path).read_text())
        if preset_or_path not in all_presets:
            available = [k for k in all_presets if not k.startswith("_")]
            raise SystemExit(f"unknown tag preset '{preset_or_path}'. "
                             f"Available: {', '.join(available)}")
        block = all_presets[preset_or_path]
    TAG_KEYWORDS = [(tag, [kw.lower() for kw in kws])
                    for tag, kws in block.items()]


def infer_tags(headline, body):
    text = (headline + " " + body[:2000]).lower()
    tags = [tag for tag, kws in TAG_KEYWORDS if any(k in text for k in kws)]
    return tags[:4] if tags else ["corporate"]


def generate_summary(headline, body):
    paras = re.split(r"\n\s*\n", body.strip())
    lead = next((p for p in paras
                 if "BUSINESS WIRE" in p or "GLOBE NEWSWIRE" in p
                 or "/PRNewswire/" in p), None)
    if lead is None:
        lead = next((p for p in paras if len(p.strip()) > 100), None)
    if lead is None:
        return headline
    lead = re.sub(r"\s+", " ", lead.replace("\n", " ")).strip()
    lead = re.sub(
        r"^.*?\b(?:BUSINESS|GLOBE)\s*(?:WIRE|NEWSWIRE)\)\s*[-–—]*\s*"
        r"(?:[A-Z][a-z]+\.?\s+\d+,\s*\d{4}\s*[-–—]+\s*)?",
        "", lead, flags=re.I)
    lead = re.sub(r"^.*?/PRNewswire/\s*--?\s*", "", lead, flags=re.I)
    sentences = re.split(r"(?<=[.!?])\s+", lead.strip())
    return " ".join(sentences[:2]).strip()[:500] or headline


# ---------------------------------------------------------------------------
# Markdown writer
# ---------------------------------------------------------------------------

def yaml_quote(s):
    if ":" in s or s.startswith(("-", "?", "&", "*", "!", "|", ">", "%", "@", "`")):
        return '"' + s.replace('"', '\\"') + '"'
    return s


def write_markdown(out_dir, date_str, headline, source_url, source_label,
                   edgar_accession, body, slug):
    tags = infer_tags(headline, body)
    summary = generate_summary(headline, body)
    long_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %-d, %Y")
    edgar_line = edgar_accession or "—"

    content = "\n".join([
        "---",
        f"date: {date_str}",
        f"headline: {yaml_quote(headline)}",
        f"source_url: {source_url}",
        f"edgar_accession: {edgar_accession or 'null'}",
        f"tags: [{', '.join(tags)}]",
        "---",
        "",
        f"# {headline}",
        "",
        f"**Date:** {long_date}  ",
        f"**Source:** [{source_label}]({source_url})  ",
        f"**EDGAR 8-K:** {edgar_line}",
        "",
        "## Summary",
        "",
        summary,
        "",
        "## Full Press Release",
        "",
        body.strip(),
        "",
    ])
    out_path = Path(out_dir) / f"{date_str}-{slug}.md"
    out_path.write_text(content)
    return out_path


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def output_path_for(entry, out_dir):
    return Path(out_dir) / f"{entry['date']}-{entry['slug']}.md"


def process(entry, cik, out_dir, wayback_delay=4.0, force=False):
    """Try tiers in order. Returns (status, used_tier, message).
    If the output file already exists and force=False, returns ('SKIP', 0, ...).
    """
    accession = entry.get("edgar_accession")
    wire_url = entry.get("wire_url")
    headline_hint = entry.get("headline")
    slug = entry["slug"]
    date_str = entry["date"]

    if not force and output_path_for(entry, out_dir).exists():
        return ("SKIP", 0, "already on disk")

    body = None
    source_url = None
    source_label = None

    # Tier 1 — EDGAR (requires both an accession and a CIK)
    if accession and cik:
        ex_url, html = fetch_tier1_edgar(accession, cik)
        if html:
            body = clean_edgar_body(html_to_text(html))
            source_url = wire_url or ex_url
            source_label = ("Business Wire (body text from SEC EDGAR EX-99.1)"
                            if wire_url else "SEC EDGAR (EX-99.1)")
            tier = 1

    # Tier 2 — Wayback
    if body is None and wire_url:
        time.sleep(wayback_delay)
        wb_url, html = fetch_tier2_wayback(wire_url, year_hint=date_str[:4])
        if html:
            body = clean_wire_body(html_to_text(html))
            source_url = wire_url
            wire_name = ("Business Wire" if "businesswire" in wire_url
                         else "GlobeNewswire" if "globenewswire" in wire_url
                         else "PR Newswire" if "prnewswire" in wire_url
                         else "Wire")
            source_label = f"{wire_name} (via Wayback Machine)"
            tier = 2

    # Tier 3 falls through to caller (Chrome assist via --inject)
    if body is None:
        return ("PENDING_CHROME", None, "needs Chrome Connector")

    headline, body = extract_headline_and_body(body, hint=headline_hint)
    if headline_hint:
        headline = headline_hint
    body = strip_leading_headline_dup(body, headline)

    write_markdown(out_dir, date_str, headline, source_url, source_label,
                   accession, body, slug)
    return ("OK", tier, str(slug))


def inject_mode(slug, manifest_path, out_dir, html_text):
    """Process HTML piped via stdin (Tier 3 — Claude has done the Chrome fetch)."""
    manifest = json.loads(Path(manifest_path).read_text())
    entry = next((e for e in manifest["entries"] if e["slug"] == slug), None)
    if not entry:
        print(f"ERROR: slug '{slug}' not found in manifest", file=sys.stderr)
        sys.exit(1)
    body = clean_wire_body(html_to_text(html_text))
    headline, body = extract_headline_and_body(body, hint=entry.get("headline"))
    if entry.get("headline"):
        headline = entry["headline"]
    body = strip_leading_headline_dup(body, headline)

    wire_url = entry.get("wire_url") or "(injected via Chrome)"
    wire_name = ("Business Wire" if "businesswire" in (wire_url or "")
                 else "GlobeNewswire" if "globenewswire" in (wire_url or "")
                 else "Wire")
    source_label = f"{wire_name} (live, via Chrome Connector)"

    out = write_markdown(out_dir, entry["date"], headline, wire_url,
                         source_label, entry.get("edgar_accession"),
                         body, slug)
    print(f"Wrote {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", nargs="?", help="manifest.json from discover.py")
    ap.add_argument("--out", default="releases/", help="output directory")
    ap.add_argument("--inject", help="slug to inject (reads HTML from stdin)")
    ap.add_argument("--manifest", dest="manifest_arg",
                    help="(with --inject) path to manifest.json")
    ap.add_argument("--wayback-delay", type=float, default=4.0,
                    help="seconds between Wayback requests (rate limit)")
    ap.add_argument("--tags", default="generic",
                    help="tag preset name (medtech|biotech|saas|generic) or "
                         "path to a custom JSON keyword map")
    ap.add_argument("--force", action="store_true",
                    help="re-fetch entries that already have a .md on disk")
    args = ap.parse_args()

    load_tags(args.tags)
    Path(args.out).mkdir(parents=True, exist_ok=True)

    if args.inject:
        manifest_path = args.manifest_arg or args.manifest
        if not manifest_path:
            print("ERROR: --inject requires --manifest", file=sys.stderr)
            sys.exit(1)
        html_text = sys.stdin.read()
        inject_mode(args.inject, manifest_path, args.out, html_text)
        return

    if not args.manifest:
        print("ERROR: manifest.json path required", file=sys.stderr)
        sys.exit(1)

    manifest = json.loads(Path(args.manifest).read_text())
    cik = manifest.get("cik")
    entries = manifest["entries"]

    company_label = manifest.get("company_name", "(unknown)")
    if cik:
        scope_label = f"CIK {cik}"
    elif manifest.get("url"):
        scope_label = f"private / {manifest['url']}"
    else:
        scope_label = company_label
    print(f"Processing {len(entries)} entries for {scope_label} "
          f"(tags={args.tags}, force={args.force})...")
    pending = []
    counts = {1: 0, 2: 0, "skip": 0, "fail": 0}
    for i, entry in enumerate(entries, 1):
        status, tier, msg = process(entry, cik, args.out, args.wayback_delay,
                                    force=args.force)
        marker = {"OK": "OK", "SKIP": "SKIP", "PENDING_CHROME": "PENDING"}.get(status, status)
        print(f"  [{i:>3}/{len(entries)}] {entry['date']}  "
              f"T{tier if tier else '?'}  {marker:7s} {entry['slug']}")
        if status == "OK":
            counts[tier] += 1
        elif status == "SKIP":
            counts["skip"] += 1
        else:
            pending.append(entry)
            counts["fail"] += 1

    print()
    print(f"Tier 1 (EDGAR):    {counts[1]}")
    print(f"Tier 2 (Wayback):  {counts[2]}")
    print(f"Skipped (exists):  {counts['skip']}")
    print(f"Pending (Chrome):  {counts['fail']}")

    if pending:
        pending_path = Path(args.out).parent / "pending_chrome.json"
        pending_path.write_text(json.dumps(pending, indent=2))
        print(f"\nPending entries written to {pending_path}")
        print("Use --inject mode (with HTML piped from Chrome MCP) to capture them.")


if __name__ == "__main__":
    main()
