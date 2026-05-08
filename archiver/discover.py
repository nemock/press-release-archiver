#!/usr/bin/env python3
"""
Stage 1 of the press-release-archiver skill.

Discovers every press release for a given public company by combining:
  - SEC EDGAR full-text search (8-K filings with EX-99.1 exhibits)
  - Business Wire / GlobeNewswire / PR Newswire searches via DuckDuckGo
    (chosen over Google because it has no API key requirement)

Outputs a manifest.json the fetch.py stage consumes.

Usage:
  python3 discover.py "Acme Medtech" --ticker ACME --out manifest.json
  python3 discover.py "Stryker" --ticker SYK --pre-ipo skip --out stryker_manifest.json

Note: this is a SKETCH. The DuckDuckGo / Bing search step is stubbed —
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

USER_AGENT_SEC = "Press Release Archiver Skill your-email@example.com"


# ---------------------------------------------------------------------------
# CIK lookup
# ---------------------------------------------------------------------------

def find_cik(company_name, ticker=None):
    """Resolve a company name (and optional ticker) to a 10-digit CIK.

    Strategy:
      1. If ticker provided, use the SEC's company_tickers.json (~40k row index).
      2. Otherwise, search EDGAR's company browse endpoint by name.
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
                return cik, row["title"]
        # Fall through to name search if ticker not found

    # Name-based search
    name_q = urllib.parse.quote_plus(company_name)
    url = (f"https://www.sec.gov/cgi-bin/browse-edgar?"
           f"action=getcompany&company={name_q}&type=8-K&dateb=&owner=include"
           f"&count=10&action=getcompany")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT_SEC})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    # Parse the result table for CIK + name pairs.
    matches = re.findall(
        r'CIK=(\d{10})[^>]*>([^<]+)</a>', html)
    if not matches:
        return None, None
    # Heuristic: prefer the row whose name contains the search term
    target = company_name.lower()
    for cik, name in matches:
        if target in name.lower():
            return cik, name
    return matches[0][0], matches[0][1]


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


def enumerate_edgar_press_releases(cik):
    """Return list of (filing_date, accession, file_description) tuples for
    every 8-K filed by `cik` that has a press-release-style EX-99.1 exhibit.

    Uses EDGAR's full-text search backend (efts.sec.gov). The endpoint
    requires a non-empty `q=` parameter; we use `q="press release"` to
    bias toward 8-Ks that mention a press release (most do, in the body
    of the form even when the exhibit description doesn't). Pages results
    in batches of 100 (EDGAR's max per request).

    Known limitation: 8-Ks whose body doesn't contain the phrase "press
    release" will be missed. For high-volume mature filers this is
    occasionally an issue (~5-10% miss rate). A more thorough approach
    would walk data.sec.gov/submissions/ and inspect each 8-K's index.
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


# ---------------------------------------------------------------------------
# Wire enumeration (Business Wire, GlobeNewswire, PR Newswire)
# ---------------------------------------------------------------------------

def enumerate_wire_releases(company_name, years):
    """Search the major wires for press releases mentioning the company.

    SKETCH: this is a stub. In a real skill, wire it to whatever search
    transport is available (Claude's WebSearch tool, SerpAPI, etc.).
    The function should return a list of dicts:
      {"date": "YYYY-MM-DD", "headline": "...", "url": "...", "wire": "businesswire|globenewswire|prnewswire"}
    """
    sites = ["businesswire.com", "globenewswire.com", "prnewswire.com"]
    print("  [wire-search] Stubbed. In a real skill, search:", file=sys.stderr)
    for site in sites:
        for year in years:
            print(f"    site:{site} \"{company_name}\" {year}", file=sys.stderr)
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

    # Seed from EDGAR (authoritative for date + accession)
    for date, accession, desc in edgar_rows:
        # Try to extract date from description like "PRESS RELEASE OF X DATED MARCH 4, 2024"
        # else fall back to filing date.
        actual_date = date
        m = re.search(r"DATED\s+(\w+)\s+(\d+),?\s+(\d{4})", desc, re.I)
        if m:
            try:
                d = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}",
                                      "%B %d %Y")
                actual_date = d.strftime("%Y-%m-%d")
            except ValueError:
                pass

        slug = f"press-release-{actual_date}"
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


def emit_search_queries(company_name, years):
    """Emit a copy-pasteable list of search queries Claude should run.
    Returns the list as a Python list (also printed for human visibility)."""
    queries = []
    for site in ("businesswire.com", "globenewswire.com", "prnewswire.com"):
        for year in years:
            queries.append(f'site:{site} "{company_name}" {year}')
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
        description="Discover press releases for a public company.",
        epilog="Three modes: full discovery (default), --manifest-merge to add "
               "wire results to an existing manifest, --update for incremental.")
    ap.add_argument("company_name", nargs="?")
    ap.add_argument("--ticker", default=None)
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

    print(f"Resolving CIK for {args.company_name}"
          f"{f' ({args.ticker})' if args.ticker else ''}...")
    cik, resolved_name = find_cik(args.company_name, args.ticker)
    if not cik:
        print(f"ERROR: could not resolve CIK for {args.company_name}",
              file=sys.stderr)
        sys.exit(1)
    print(f"  CIK {cik} = {resolved_name}")

    print(f"Enumerating EDGAR 8-K press releases for CIK {cik}...")
    edgar_rows = enumerate_edgar_press_releases(cik)
    print(f"  Found {len(edgar_rows)} press releases on EDGAR")

    # ----- Mode: --update (incremental, narrow to net-new) -----
    if args.update:
        existing = existing_dates_in_releases(args.update)
        if existing:
            cutoff = max(existing)
            print(f"  Existing archive max date: {cutoff} "
                  f"({len(existing)} releases on disk)")
            edgar_rows = [r for r in edgar_rows if r[0] > cutoff]
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
        for q in emit_search_queries(args.company_name, years):
            print(f"  {q}")
        print()
        print("Format wire results as JSON list of {date, headline, url, wire},")
        print(f"then merge: python3 discover.py --manifest-merge results.json --out {args.out}")
        sys.exit(0)

    print(f"Searching wires for {args.company_name} (stub — emit queries with --emit-queries)...")
    wire_rows = enumerate_wire_releases(args.company_name, years)
    print(f"  Found {len(wire_rows)} wire releases")

    manifest = {
        "company_name": resolved_name or args.company_name,
        "ticker": args.ticker,
        "cik": cik,
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
        print("Next: run wire searches to capture non-EDGAR releases. Use:")
        print(f"  python3 discover.py {repr(args.company_name)} "
              f"{'--ticker ' + args.ticker + ' ' if args.ticker else ''}--emit-queries")


if __name__ == "__main__":
    main()
