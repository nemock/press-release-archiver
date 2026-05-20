#!/usr/bin/env python3
"""
Stage 3 of the press-release-archiver skill — generates INDEX.md.

Reads every per-release markdown file produced by fetch.py and writes
a navigable top-level index: chronological listing, per-year stats,
per-tag groupings.

Usage:
  python3 build_index.py --releases <company-dir>/releases/ --out <company-dir>/INDEX.md
  python3 build_index.py --releases acme-medtech/releases/ --manifest acme-medtech/manifest.json
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

def load_tag_labels(presets_file=None):
    """Load human-readable tag labels from tag_presets.json `_labels` block.
    Falls back to a small built-in set so build_index works without the file."""
    presets_path = presets_file or (Path(__file__).resolve().parent / "tag_presets.json")
    if Path(presets_path).exists():
        data = json.loads(Path(presets_path).read_text())
        if "_labels" in data:
            return data["_labels"]
    return {
        "financial-results": "Financial Results",
        "leadership": "Leadership",
        "partnership": "Partnerships",
        "product-milestone": "Product Milestones",
        "regulatory": "Regulatory",
        "capital-markets": "Capital Markets",
        "corporate": "Corporate Actions",
    }

TAG_LABELS = load_tag_labels()
TAG_ORDER = list(TAG_LABELS.keys())


def parse_release(path):
    text = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        return None
    fm_block, body = m.group(1), m.group(2)
    fm = {}
    for line in fm_block.split("\n"):
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        v = v.strip()
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1].replace('\\"', '"')
        if v.startswith("[") and v.endswith("]"):
            v = [x.strip() for x in v[1:-1].split(",") if x.strip()]
        fm[k.strip()] = v
    summary_m = re.search(r"## Summary\n+(.+?)(?:\n##|\Z)", body, re.S)
    return {
        "path": path,
        "filename": path.name,
        "date": fm.get("date", ""),
        "headline": fm.get("headline", "") or "",
        "source_url": fm.get("source_url", ""),
        "edgar_accession": fm.get("edgar_accession", ""),
        "tags": fm.get("tags", []) if isinstance(fm.get("tags"), list) else [],
        "summary": summary_m.group(1).strip() if summary_m else "",
    }


def fmt_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %-d, %Y")
    except Exception:
        return date_str


def build(releases_dir, out_path, manifest_path=None):
    releases = []
    for p in sorted(Path(releases_dir).glob("*.md")):
        r = parse_release(p)
        if r:
            releases.append(r)
    releases.sort(key=lambda r: r["date"])

    company = "Company"
    cik = ticker = url = ""
    is_public = None
    if manifest_path and Path(manifest_path).exists():
        m = json.loads(Path(manifest_path).read_text())
        company = m.get("company_name", company)
        cik = m.get("cik", "") or ""
        ticker = m.get("ticker", "") or ""
        url = m.get("url", "") or ""
        is_public = m.get("is_public")

    tag_counts = Counter()
    year_counts = Counter()
    for r in releases:
        for t in r["tags"]:
            tag_counts[t] += 1
        if r["date"]:
            year_counts[r["date"][:4]] += 1

    L = []
    L.append(f"# {company} — Press Release Archive")
    L.append("")
    if ticker or cik or url or is_public is False:
        bits = []
        if ticker:
            bits.append(f"**Ticker:** {ticker}")
        if cik:
            bits.append(f"**SEC CIK:** {cik}")
        if url:
            bits.append(f"**Website:** <{url}>")
        if is_public is False:
            bits.append("**Status:** Private / pre-IPO")
        L.append(" &nbsp;·&nbsp; ".join(bits))
        L.append("")
    L.append(f"**Releases archived:** {len(releases)} ")
    if releases:
        L.append(f"**Coverage:** {releases[0]['date']} → {releases[-1]['date']}")
    L.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d')}")
    L.append("")
    L.append("---")
    L.append("")

    # Stats
    L.append("## At a glance")
    L.append("")
    L.append("### Releases per year\n\n| Year | Count |\n|---|---|")
    for y in sorted(year_counts):
        L.append(f"| {y} | {year_counts[y]} |")
    L.append("")
    L.append("### Releases per topic\n\n| Topic | Count |\n|---|---|")
    for tag in TAG_ORDER:
        if tag in tag_counts:
            L.append(f"| {TAG_LABELS[tag]} | {tag_counts[tag]} |")
    L.append("")
    L.append("---")
    L.append("")

    # Chronological
    L.append("## Chronological listing\n")
    by_year = defaultdict(list)
    for r in releases:
        by_year[r["date"][:4]].append(r)
    for year in sorted(by_year):
        L.append(f"### {year}\n")
        for r in by_year[year]:
            chips = " ".join(f"`{t}`" for t in r["tags"])
            L.append(f"#### [{r['headline']}](releases/{r['filename']})\n")
            L.append(f"**{fmt_date(r['date'])}** &nbsp;·&nbsp; {chips}\n")
            L.append(r["summary"] + "\n")
            details = []
            if r["source_url"]:
                details.append(f"[Source]({r['source_url']})")
            if r["edgar_accession"] and r["edgar_accession"] != "null":
                details.append(f"EDGAR: `{r['edgar_accession']}`")
            if details:
                L.append("&nbsp;&nbsp;&nbsp;&nbsp;<sub>"
                         + " &nbsp;·&nbsp; ".join(details) + "</sub>\n")

    # Tag groupings
    L.append("---\n\n## Topic index\n")
    by_tag = defaultdict(list)
    for r in releases:
        for t in r["tags"]:
            by_tag[t].append(r)
    for tag in TAG_ORDER:
        if tag not in by_tag:
            continue
        L.append(f"### {TAG_LABELS[tag]} ({len(by_tag[tag])})\n")
        for r in sorted(by_tag[tag], key=lambda x: x["date"]):
            L.append(f"- **{r['date']}** — [{r['headline']}](releases/{r['filename']})")
        L.append("")

    Path(out_path).write_text("\n".join(L))
    print(f"Wrote {out_path}: {len(releases)} releases, "
          f"{Path(out_path).stat().st_size:,} bytes")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--releases", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--manifest", default=None)
    args = ap.parse_args()
    out = args.out or str(Path(args.releases).parent / "INDEX.md")
    build(args.releases, out, args.manifest)


if __name__ == "__main__":
    main()
