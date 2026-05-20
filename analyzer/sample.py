#!/usr/bin/env python3
"""
sample.py — Smart sampling for the press-release-analyzer skill.

Selects a strategically representative subset of releases from an archive
and writes them out as a single markdown bundle the LLM can read in one
context window. The bundle is the input to Pass 3 (Claude's strategic
synthesis).

Sampling strategy (token-conscious by default):
  1. All milestone-tagged releases (regulatory, capital-markets,
     product-milestone, partnership, corporate, award)
  2. All crisis-flavored governance releases (delisting, departure,
     transition, retirement, change in board)
  3. First and last release of each year (anchor points)
  4. First appearance of each tag (when each kind of release first happened)
  5. Cluster anchors (first release of each cluster from stats.json)

Result: typically 30-50 unique releases for an 8-year archive (Acme Medtech),
50-80 for a 23-year archive (Globex Corp). Each entry includes headline,
date, tags, summary, and the first ~500 chars of body — compact but
semantically rich.

Use --deep for full bodies (much more tokens; only use when synthesizing
a deeper dive).

Usage:
  python3 sample.py <archive-dir> --stats <archive>/analysis/stats.json \\
                                  --out <archive>/analysis/sample.md
"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

# Reuse stats.py's release parser
import importlib.util
import os
SCRIPT_DIR = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("stats_mod", SCRIPT_DIR / "stats.py")
stats_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stats_mod)
parse_release = stats_mod.parse_release
filter_releases = stats_mod.filter_releases
parse_filter_arg = stats_mod.parse_filter_arg
add_filter_args = stats_mod.add_filter_args
resolve_analysis_out_dir = stats_mod.resolve_analysis_out_dir


# Tags that indicate a strategically meaningful release
MILESTONE_TAGS = {
    "regulatory", "capital-markets", "product-milestone",
    "partnership", "corporate", "award", "product-launch",
    "trial", "data-readout", "ip",
}

CRISIS_KEYWORDS = re.compile(
    r"\b(delisting|delist|notice from|departure|retirement|"
    r"transition|reduction in|going concern|cash burn|"
    r"resign|resignation|step down|terminat)\b",
    re.I,
)


def select_samples(releases, stats=None, max_samples=80):
    """Return a list of (release, reason) tuples — releases the synthesis
    pass should read in full or near-full."""
    selected = {}  # filename -> (release, reasons)

    def add(r, reason):
        if r["filename"] not in selected:
            selected[r["filename"]] = (r, [reason])
        else:
            selected[r["filename"]][1].append(reason)

    # 1. Milestone-tagged
    for r in releases:
        if any(t in MILESTONE_TAGS for t in r["tags"]):
            add(r, "milestone")

    # 2. Crisis-flavored governance
    for r in releases:
        if "governance" in r["tags"] or "leadership" in r["tags"]:
            text = (r["headline"] + " " + r["summary"]).lower()
            if CRISIS_KEYWORDS.search(text):
                add(r, "crisis")

    # 3. First and last release of each year
    by_year = {}
    for r in releases:
        y = r["date"][:4]
        if y not in by_year:
            by_year[y] = [r, r]
        else:
            if r["date"] < by_year[y][0]["date"]:
                by_year[y][0] = r
            if r["date"] > by_year[y][1]["date"]:
                by_year[y][1] = r
    for y, (first, last) in by_year.items():
        add(first, f"first of {y}")
        add(last, f"last of {y}")

    # 4. First appearance of each tag (using stats.json if available)
    if stats and "topics" in stats:
        first_app = stats["topics"].get("first_appearance", {})
        wanted_dates = {v["date"] for v in first_app.values()}
        for r in releases:
            if r["date"] in wanted_dates:
                add(r, "first-of-tag")

    # 5. Cluster anchors
    if stats and "cadence" in stats:
        for cl in stats["cadence"].get("clusters", []):
            for r in releases:
                if r["date"] == cl["start"]:
                    add(r, f"cluster-anchor ({cl['count']} releases over {cl['start']}–{cl['end']})")
                    break

    # Sort chronologically; trim to max_samples by importance
    out = sorted(selected.values(), key=lambda x: x[0]["date"])
    if len(out) > max_samples:
        # Score: more reasons = more important. Plus crisis/milestone get a bump.
        def score(item):
            r, reasons = item
            s = len(reasons)
            for reason in reasons:
                if reason in ("milestone", "crisis"):
                    s += 2
                if reason.startswith("cluster"):
                    s += 1
            return s
        out = sorted(out, key=score, reverse=True)[:max_samples]
        out.sort(key=lambda x: x[0]["date"])

    return out


def render_bundle(samples, company_name, deep=False):
    """Render sampled releases as a single markdown document the LLM can read."""
    L = []
    L.append(f"# {company_name} — Strategic Sample Bundle")
    L.append("")
    L.append(f"**{len(samples)} releases sampled** for strategic-synthesis pass. "
             f"Each entry below was selected for one or more reasons (e.g., "
             f"\"milestone\", \"crisis\", \"first-of-tag\", \"cluster-anchor\", "
             f"\"first/last of YEAR\"). Use this as the qualitative input alongside "
             f"`patterns.md` (the deterministic stats).")
    L.append("")
    L.append("---")
    L.append("")
    for r, reasons in samples:
        L.append(f"## {r['date']} — {r['headline']}")
        L.append("")
        L.append(f"**Selected because:** {', '.join(reasons)}  ")
        if r["tags"]:
            tag_str = " ".join(f"`{t}`" for t in r["tags"])
            L.append(f"**Tags:** {tag_str}  ")
        if r["edgar_accession"] and r["edgar_accession"] != "null":
            L.append(f"**EDGAR:** {r['edgar_accession']}  ")
        if r["source_url"]:
            L.append(f"**Source:** {r['source_url']}")
        L.append("")
        if r["summary"]:
            L.append("### Summary")
            L.append("")
            L.append(r["summary"])
            L.append("")
        if r["body"]:
            L.append("### Body excerpt")
            L.append("")
            if deep:
                L.append(r["body"])
            else:
                excerpt = r["body"][:600].rstrip()
                if len(r["body"]) > 600:
                    excerpt += "…"
                L.append(excerpt)
            L.append("")
        L.append("---")
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="Sample strategic releases for LLM synthesis pass.")
    ap.add_argument("archive_dir")
    ap.add_argument("--stats", default=None,
                    help="Path to stats.json (default: <archive>/analysis/stats.json)")
    ap.add_argument("--out", default=None,
                    help="Output bundle path (default: <archive>/analysis/sample.md)")
    ap.add_argument("--deep", action="store_true",
                    help="Include FULL body text (not just excerpt). "
                         "Significantly more tokens — use only for deep-dive runs.")
    ap.add_argument("--max-samples", type=int, default=80)
    add_filter_args(ap)
    args = ap.parse_args()

    archive_dir = Path(args.archive_dir)
    # Output dir respects --filter / --analysis-name; stats.json lives in the same dir.
    out_dir = resolve_analysis_out_dir(archive_dir, args)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else (out_dir / "sample.md")
    stats_path = Path(args.stats) if args.stats else (out_dir / "stats.json")
    stats = json.loads(stats_path.read_text()) if stats_path.exists() else None

    all_releases = []
    for p in sorted((archive_dir / "releases").glob("*.md")):
        r = parse_release(p)
        if r:
            all_releases.append(r)
    all_releases.sort(key=lambda x: x["date"])

    filter_keywords = parse_filter_arg(args.filter_str)
    releases = filter_releases(all_releases, filter_keywords)
    if filter_keywords and not releases:
        raise SystemExit(
            f"Filter matched 0 releases. Keywords tried: {filter_keywords}.")

    company_name = stats.get("company") if stats else archive_dir.name

    samples = select_samples(releases, stats=stats, max_samples=args.max_samples)
    out_path.write_text(render_bundle(samples, company_name, deep=args.deep))

    print(f"Wrote {out_path}")
    if filter_keywords:
        print(f"  Filter active: {len(releases)} of {len(all_releases)} releases matched ({filter_keywords})")
    print(f"  Sampled {len(samples)}/{len(releases)} releases")
    if args.deep:
        print(f"  --deep mode: full bodies included (heavy on tokens)")


if __name__ == "__main__":
    main()
