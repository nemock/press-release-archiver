#!/usr/bin/env python3
"""
compare.py — Cross-company comparative analysis with stage alignment.

The killer feature for early-stage clients: aligns two companies by their
*company-relative time* (months since IPO/funding event), not calendar
year. This makes Globex Corp's 2003-era patterns directly comparable
to Acme Medtech's 2022-era patterns even though they're 19 years apart
on the calendar.

For each company, we determine an anchor date (default: first release in
the archive, but can be overridden with --anchor-a / --anchor-b). All
releases are then re-indexed by months-since-anchor.

Output:
  - <out>/comparison.json    structured cross-company stats
  - <out>/comparison.md      human-readable summary (Claude reads this)

Usage:
  python3 compare.py <archive-a> <archive-b> --out <out-dir>
  python3 compare.py acme-medtech/ globex-corp/ \\
                     --anchor-a <yyyy-mm-dd> --anchor-b <yyyy-mm-dd> \\
                     --out acme-vs-globex/
"""

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import importlib.util
SCRIPT_DIR = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("stats_mod", SCRIPT_DIR / "stats.py")
stats_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stats_mod)
parse_release = stats_mod.parse_release
collect_company_meta = stats_mod.collect_company_meta


def months_between(d1, d2):
    """Approximate calendar months between two dates."""
    a = datetime.strptime(d1, "%Y-%m-%d")
    b = datetime.strptime(d2, "%Y-%m-%d")
    return (b.year - a.year) * 12 + (b.month - a.month)


def stage_relative_releases(releases, anchor_date):
    """Annotate each release with months-since-anchor."""
    out = []
    for r in releases:
        try:
            m = months_between(anchor_date, r["date"])
        except ValueError:
            continue
        if m < 0:
            continue  # pre-anchor releases dropped
        out.append({**r, "month_since_anchor": m})
    return sorted(out, key=lambda x: x["month_since_anchor"])


def aligned_window_stats(releases_a, releases_b, max_months=None):
    """Compute side-by-side stats for the overlapping company-relative window.
    Returns dict keyed by 12-month buckets (Year 1, Year 2, ...) with counts
    and tag mixes for each company."""
    # If no max specified, use the smaller of the two
    last_a = releases_a[-1]["month_since_anchor"] if releases_a else 0
    last_b = releases_b[-1]["month_since_anchor"] if releases_b else 0
    if max_months is None:
        max_months = min(last_a, last_b)

    by_year_a = defaultdict(list)
    by_year_b = defaultdict(list)
    for r in releases_a:
        if r["month_since_anchor"] <= max_months:
            by_year_a[r["month_since_anchor"] // 12 + 1].append(r)
    for r in releases_b:
        if r["month_since_anchor"] <= max_months:
            by_year_b[r["month_since_anchor"] // 12 + 1].append(r)

    out = {}
    for y in sorted(set(list(by_year_a.keys()) + list(by_year_b.keys()))):
        a = by_year_a.get(y, [])
        b = by_year_b.get(y, [])
        out[f"year_{y}"] = {
            "count_a": len(a),
            "count_b": len(b),
            "tags_a": dict(Counter(t for r in a for t in r["tags"]).most_common(8)),
            "tags_b": dict(Counter(t for r in b for t in r["tags"]).most_common(8)),
            "headlines_a": [{"date": r["date"], "headline": r["headline"]} for r in a[:5]],
            "headlines_b": [{"date": r["date"], "headline": r["headline"]} for r in b[:5]],
        }
    return out, max_months


def diff_stats(stats_a, stats_b):
    """Headline differences in the deterministic stats."""
    return {
        "release_count": {
            "a": stats_a["release_count"],
            "b": stats_b["release_count"],
            "delta": stats_a["release_count"] - stats_b["release_count"],
        },
        "median_gap_days": {
            "a": stats_a["cadence"]["median_gap_days"],
            "b": stats_b["cadence"]["median_gap_days"],
        },
        "ceo_quote_rate": {
            "a": stats_a["stakeholders"]["ceo_quote_rate"],
            "b": stats_b["stakeholders"]["ceo_quote_rate"],
        },
        "avg_headline_words": {
            "a": stats_a["headlines"]["avg_word_count"],
            "b": stats_b["headlines"]["avg_word_count"],
        },
        "headline_starts_with_company_pct": {
            "a": stats_a["headlines"]["starts_with_company_pct"],
            "b": stats_b["headlines"]["starts_with_company_pct"],
        },
        "headline_all_caps_pct": {
            "a": stats_a["headlines"]["all_caps_pct"],
            "b": stats_b["headlines"]["all_caps_pct"],
        },
    }


def render_comparison_md(name_a, name_b, anchor_a, anchor_b,
                         aligned, max_months, diff, archetype_a, archetype_b):
    L = []
    L.append(f"# {name_a} vs. {name_b} — Comparative Analysis")
    L.append("")
    L.append(f"**Stage-aligned comparison** anchored on each company's "
             f"first material release in the archive.")
    L.append("")
    L.append(f"- {name_a} anchor: **{anchor_a}**")
    L.append(f"- {name_b} anchor: **{anchor_b}**")
    L.append(f"- Aligned window: **first {max_months} months** of each company's archived history")
    L.append("")
    L.append("---")
    L.append("")

    # Headline deltas
    L.append("## Top-line deltas")
    L.append("")
    L.append("| Metric | " + name_a + " | " + name_b + " |")
    L.append("|---|---|---|")
    L.append(f"| Releases in archive | {diff['release_count']['a']} | {diff['release_count']['b']} |")
    L.append(f"| Median gap between releases | {diff['median_gap_days']['a']}d | {diff['median_gap_days']['b']}d |")
    L.append(f"| CEO quote rate | {diff['ceo_quote_rate']['a']:.0%} | {diff['ceo_quote_rate']['b']:.0%} |")
    L.append(f"| Avg headline length | {diff['avg_headline_words']['a']:.1f} words | {diff['avg_headline_words']['b']:.1f} words |")
    L.append(f"| Headlines starting with company name | {diff['headline_starts_with_company_pct']['a']:.0%} | {diff['headline_starts_with_company_pct']['b']:.0%} |")
    L.append(f"| All-caps headlines | {diff['headline_all_caps_pct']['a']:.0%} | {diff['headline_all_caps_pct']['b']:.0%} |")
    L.append("")

    # Ladder archetype mix
    L.append("## Credibility-ladder archetype mix")
    L.append("")
    L.append("Within the aligned window, what kinds of rungs did each company climb?")
    L.append("")
    archetypes = sorted(set(list(archetype_a.keys()) + list(archetype_b.keys())))
    L.append(f"| Archetype | {name_a} | {name_b} |")
    L.append("|---|---|---|")
    for arch in archetypes:
        L.append(f"| `{arch}` | {archetype_a.get(arch, 0)} | {archetype_b.get(arch, 0)} |")
    L.append("")

    # Year-by-year (stage-aligned)
    L.append("---")
    L.append("")
    L.append("## Stage-aligned year-by-year")
    L.append("")
    L.append("Reading this table: 'Year 1' = months 0–11 since the company's "
             "anchor date. So Acme Medtech Year 1 (post-SPAC, 2021–2022) sits "
             "in the same column as Globex Corp Year 1 (post-2003 Computer "
             "Motion merger, 2003–2004).")
    L.append("")
    for ystr, data in aligned.items():
        y = int(ystr.replace("year_", ""))
        L.append(f"### Year {y}")
        L.append("")
        L.append(f"- {name_a}: **{data['count_a']} releases**")
        if data["tags_a"]:
            L.append(f"  - tags: " + ", ".join(f"`{t}`={n}" for t, n in data["tags_a"].items()))
        L.append(f"- {name_b}: **{data['count_b']} releases**")
        if data["tags_b"]:
            L.append(f"  - tags: " + ", ".join(f"`{t}`={n}" for t, n in data["tags_b"].items()))
        L.append("")
        if data["headlines_a"]:
            L.append(f"  Sample {name_a} headlines:")
            for h in data["headlines_a"]:
                L.append(f"    - {h['date']}: {h['headline']}")
        if data["headlines_b"]:
            L.append(f"  Sample {name_b} headlines:")
            for h in data["headlines_b"]:
                L.append(f"    - {h['date']}: {h['headline']}")
        L.append("")
    return "\n".join(L)


def load_archive(archive_dir, anchor_override=None):
    archive_dir = Path(archive_dir)
    company_name, ticker, _ = collect_company_meta(archive_dir)
    releases = []
    for p in sorted((archive_dir / "releases").glob("*.md")):
        r = parse_release(p)
        if r:
            releases.append(r)
    releases.sort(key=lambda x: x["date"])
    anchor = anchor_override or releases[0]["date"]
    return company_name, ticker, releases, anchor


def load_stats(archive_dir):
    p = Path(archive_dir) / "analysis" / "stats.json"
    return json.loads(p.read_text()) if p.exists() else None


def load_ladder(archive_dir):
    p = Path(archive_dir) / "analysis" / "ladder.json"
    return json.loads(p.read_text()) if p.exists() else None


def main():
    ap = argparse.ArgumentParser(description="Cross-company comparative analysis with stage alignment.")
    ap.add_argument("archive_a")
    ap.add_argument("archive_b")
    ap.add_argument("--anchor-a", default=None,
                    help="Anchor date for archive A (default: first release date). "
                         "Override to align on IPO, funding event, etc.")
    ap.add_argument("--anchor-b", default=None,
                    help="Anchor date for archive B")
    ap.add_argument("--out", required=True,
                    help="Output directory for comparison.json + comparison.md")
    ap.add_argument("--max-months", type=int, default=None,
                    help="Cap the comparison window (in months since anchor). "
                         "Default: use the smaller archive's full window.")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    name_a, ticker_a, rel_a, anchor_a = load_archive(args.archive_a, args.anchor_a)
    name_b, ticker_b, rel_b, anchor_b = load_archive(args.archive_b, args.anchor_b)

    stats_a = load_stats(args.archive_a) or {}
    stats_b = load_stats(args.archive_b) or {}
    ladder_a = load_ladder(args.archive_a) or {}
    ladder_b = load_ladder(args.archive_b) or {}

    aligned_a = stage_relative_releases(rel_a, anchor_a)
    aligned_b = stage_relative_releases(rel_b, anchor_b)
    aligned, max_months = aligned_window_stats(aligned_a, aligned_b, args.max_months)

    if stats_a and stats_b:
        diff = diff_stats(stats_a, stats_b)
    else:
        diff = {"_warning": "Both archives need stats.json (run stats.py first) for top-line deltas."}

    # Archetype mix from ladders, restricted to aligned window
    def archetype_mix(ladder, anchor, max_m):
        out = Counter()
        for rung in ladder.get("rungs", []):
            try:
                m = months_between(anchor, rung["date"])
            except ValueError:
                continue
            if 0 <= m <= max_m:
                out[rung["archetype"]] += 1
        return dict(out.most_common())

    arch_a = archetype_mix(ladder_a, anchor_a, max_months)
    arch_b = archetype_mix(ladder_b, anchor_b, max_months)

    comp = {
        "company_a": {"name": name_a, "ticker": ticker_a, "anchor": anchor_a,
                      "archive_release_count": len(rel_a)},
        "company_b": {"name": name_b, "ticker": ticker_b, "anchor": anchor_b,
                      "archive_release_count": len(rel_b)},
        "max_months_compared": max_months,
        "aligned_by_year": aligned,
        "headline_deltas": diff,
        "archetype_mix_a": arch_a,
        "archetype_mix_b": arch_b,
    }
    (out_dir / "comparison.json").write_text(json.dumps(comp, indent=2, default=str))
    (out_dir / "comparison.md").write_text(
        render_comparison_md(name_a, name_b, anchor_a, anchor_b,
                             aligned, max_months, diff, arch_a, arch_b))

    print(f"Wrote {out_dir / 'comparison.json'}")
    print(f"Wrote {out_dir / 'comparison.md'}")
    print(f"  {name_a} (anchor {anchor_a}, {len(rel_a)} releases)")
    print(f"  {name_b} (anchor {anchor_b}, {len(rel_b)} releases)")
    print(f"  Stage-aligned window: {max_months} months")


if __name__ == "__main__":
    main()
