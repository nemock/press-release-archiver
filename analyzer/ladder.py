#!/usr/bin/env python3
"""
ladder.py — Credibility Ladder extractor for the press-release-analyzer skill.

A company's "credibility ladder" is the chronological sequence of proof-point
releases that build investor + market confidence over time. Each rung is a
material milestone (a regulatory clearance, a capital event, a major product
demonstration, a flagship partnership). The pacing between rungs reveals the
strategic rhythm.

This script deterministically extracts CANDIDATE rungs from a tagged archive.
The final curation — deciding which candidates are *true* rungs vs. routine
events — happens in the LLM synthesis pass (Claude reading ladder.json +
sample.md together).

Output:
  - <out>/ladder.json    structured candidate rungs with classification
  - <out>/ladder.md      human-readable timeline (used as Claude context)

Usage:
  python3 ladder.py <archive-dir>
  python3 ladder.py acme-medtech/ --out acme-medtech/analysis/
"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

import importlib.util
SCRIPT_DIR = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("stats_mod", SCRIPT_DIR / "stats.py")
stats_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stats_mod)
parse_release = stats_mod.parse_release
collect_company_meta = stats_mod.collect_company_meta
filter_releases = stats_mod.filter_releases
parse_filter_arg = stats_mod.parse_filter_arg
add_filter_args = stats_mod.add_filter_args
resolve_analysis_out_dir = stats_mod.resolve_analysis_out_dir


# Releases that count as candidate rungs (any of these tags qualifies)
RUNG_TAGS = {
    "regulatory", "capital-markets", "product-milestone",
    "partnership", "corporate", "award",
    "clinical", "trial", "data-readout", "product-launch",
}

# Anti-tags — releases that are noise even if they have a rung tag
EXCLUDE_PHRASES = (
    "to report", "earnings call", "to participate",
    "to present at", "scheduling",
)

# Routine quarterly earnings releases are not "ladder rungs" — they're
# baseline reporting. Detect and exclude them.
QUARTERLY_EARNINGS_RE = re.compile(
    r"\b(first|second|third|fourth|q[1-4])\s+quarter\b"
    r".{0,60}\b(earnings|financial results|results)\b"
    r"|\b(reports|announces)\s+\w+\s+quarter\b",
    re.I,
)
ANNUAL_RESULTS_RE = re.compile(
    r"\b(full[\s-]?year|annual)\b.{0,40}\b(financial results|results|earnings)\b",
    re.I,
)


def is_routine_reporting(release):
    """Quarterly earnings + annual results without additional newsworthy hooks
    are routine reporting, not credibility-ladder rungs."""
    h = release["headline"]
    if QUARTERLY_EARNINGS_RE.search(h) or ANNUAL_RESULTS_RE.search(h):
        # Keep it if the headline ALSO mentions a SPECIFIC secondary milestone.
        # Note: not just "announces" or "reports" — those appear in every
        # earnings release. Look for concrete event types after a conjunction.
        notable_secondary = re.search(
            r"\b(?:and\s+)?(?:announces|reports)\s+"
            r"(?!\w+\s+quarter\b)(?!preliminary\b)(?!fourth\b)(?!third\b)(?!second\b)(?!first\b)"
            r"\w+",
            h, re.I)
        # Stronger signals — actual milestone words, irrespective of context
        strong_signal = re.search(
            r"\b(approves|completes|achieves|launches|"
            r"first[- ]in[- ]human|fda|510\(k\)|ce mark|"
            r"clinical plan|regulatory intent|raises\s+\$|"
            r"partnership|reverse stock split|"
            r"share repurchase|delisting|listing notice|nasdaq listing)\b",
            h, re.I)
        if not strong_signal and not notable_secondary:
            return True
    return False

# Heuristic classification of rung type by headline keywords.
# This is the narrative archetype of the rung — a client building
# their own ladder will want to know "did we do a regulatory rung
# or a clinical rung last quarter?"
RUNG_ARCHETYPES = [
    ("capital_event", [
        "raises", "raise", "announces pricing", "public offering", "ipo",
        "spac", "merger", "business combination", "private placement",
        "series a", "series b", "series c", "series d", "series e",
        "funding", "investment", "stock split", "share repurchase",
        "delisting", "listing notice", "nasdaq listing",
    ]),
    ("regulatory_event", [
        "fda", "510(k)", "510k", "ce mark", "approval",
        "clearance", "ind", "nda", "bla", "breakthrough",
        "submission", "regulatory",
    ]),
    ("clinical_event", [
        "first-in-human", "first patient", "first surgery",
        "first procedure", "in-vivo", "in vivo", "porcine",
        "cadaveric", "clinical use", "clinical plan",
    ]),
    ("product_event", [
        "design freeze", "version 1", "v1.0", "beta", "demo",
        "demonstration", "system", "named to time",
        "launch", "platform", "release",
    ]),
    ("partnership_event", [
        "partnership with", "collaboration with", "agreement with",
        "hospital system", "joins forces", "named",
    ]),
    ("governance_event", [
        "appointed", "appointment", "ceo", "cfo", "coo",
        "chairman", "board of directors", "transition",
        "election of new directors", "founder",
    ]),
    ("recognition_event", [
        "best inventions", "best places to work", "award",
        "recognized", "named",
    ]),
]


def classify_rung(release):
    """Return the most likely archetype based on headline keywords. Falls
    back to the first matching tag's category if no keyword hits."""
    text = (release["headline"] + " " + release["summary"]).lower()
    for archetype, keywords in RUNG_ARCHETYPES:
        if any(k in text for k in keywords):
            return archetype
    # Fallback by tag
    if "regulatory" in release["tags"]:
        return "regulatory_event"
    if "capital-markets" in release["tags"]:
        return "capital_event"
    if "product-milestone" in release["tags"]:
        return "product_event"
    if "partnership" in release["tags"]:
        return "partnership_event"
    return "other"


def is_rung_candidate(release):
    """A release is a candidate rung if it has any rung tag AND its headline
    doesn't match any of the noise phrases (e.g., 'to report', 'to present at',
    routine quarterly earnings)."""
    if not any(t in RUNG_TAGS for t in release["tags"]):
        return False
    headline = release["headline"].lower()
    if any(p in headline for p in EXCLUDE_PHRASES):
        return False
    if is_routine_reporting(release):
        return False
    return True


def extract_ladder(releases):
    rungs = []
    for r in releases:
        if not is_rung_candidate(r):
            continue
        rungs.append({
            "date": r["date"],
            "headline": r["headline"],
            "tags": r["tags"],
            "archetype": classify_rung(r),
            "summary": r["summary"][:300],
            "filename": r["filename"],
        })
    rungs.sort(key=lambda x: x["date"])

    # Compute days between consecutive rungs
    for i in range(1, len(rungs)):
        try:
            prev = datetime.strptime(rungs[i - 1]["date"], "%Y-%m-%d")
            curr = datetime.strptime(rungs[i]["date"], "%Y-%m-%d")
            rungs[i]["days_since_prev_rung"] = (curr - prev).days
        except ValueError:
            rungs[i]["days_since_prev_rung"] = None

    return rungs


def archetype_distribution(rungs):
    from collections import Counter
    return dict(Counter(r["archetype"] for r in rungs).most_common())


def render_ladder_md(rungs, company_name):
    L = []
    L.append(f"# {company_name} — Credibility Ladder (candidate rungs)")
    L.append("")
    L.append(f"**{len(rungs)} candidate rungs** identified across the archive. "
             f"Each rung is a material proof-point release. The LLM synthesis "
             f"step will curate this list to surface the *true* ladder — "
             f"sequenced milestones that built investor and market confidence — "
             f"and identify the strategic logic behind their spacing.")
    L.append("")
    L.append("**Archetype distribution** (deterministic categorization):")
    L.append("")
    for arch, n in archetype_distribution(rungs).items():
        L.append(f"- `{arch}`: {n}")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## Chronological rungs")
    L.append("")
    L.append("| # | Date | Days since prev | Archetype | Headline |")
    L.append("|---|---|---|---|---|")
    for i, r in enumerate(rungs, 1):
        gap = r.get("days_since_prev_rung")
        gap_str = f"{gap}" if gap is not None else "—"
        L.append(f"| {i} | {r['date']} | {gap_str} | `{r['archetype']}` | {r['headline']} |")
    L.append("")

    # Cluster ladder rungs by archetype for narrative reading
    L.append("---")
    L.append("")
    L.append("## Rungs grouped by archetype")
    L.append("")
    by_arch = {}
    for r in rungs:
        by_arch.setdefault(r["archetype"], []).append(r)
    for arch in sorted(by_arch):
        L.append(f"### {arch}  ({len(by_arch[arch])})")
        L.append("")
        for r in by_arch[arch]:
            L.append(f"- **{r['date']}** — {r['headline']}")
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="Extract candidate credibility ladder rungs.")
    ap.add_argument("archive_dir")
    ap.add_argument("--out", default=None)
    add_filter_args(ap)
    args = ap.parse_args()

    archive_dir = Path(args.archive_dir)
    out_dir = resolve_analysis_out_dir(archive_dir, args)
    out_dir.mkdir(parents=True, exist_ok=True)

    company_name, ticker, _ = collect_company_meta(archive_dir)

    all_releases = []
    for p in sorted((archive_dir / "releases").glob("*.md")):
        r = parse_release(p)
        if r:
            all_releases.append(r)
    if not all_releases:
        raise SystemExit(f"No release files in {archive_dir / 'releases'}")
    all_releases.sort(key=lambda x: x["date"])

    filter_keywords = parse_filter_arg(args.filter_str)
    releases = filter_releases(all_releases, filter_keywords)
    if filter_keywords and not releases:
        raise SystemExit(
            f"Filter matched 0 releases. Keywords tried: {filter_keywords}.")

    rungs = extract_ladder(releases)

    ladder_payload = {"company": company_name, "rungs": rungs}
    if filter_keywords:
        ladder_payload["filter"] = {
            "keywords": filter_keywords,
            "matched": len(releases),
            "total_in_archive": len(all_releases),
        }

    (out_dir / "ladder.json").write_text(json.dumps(ladder_payload, indent=2))
    (out_dir / "ladder.md").write_text(render_ladder_md(rungs, company_name))

    print(f"Wrote {out_dir / 'ladder.json'}")
    print(f"Wrote {out_dir / 'ladder.md'}")
    if filter_keywords:
        print(f"  Filter active: {len(releases)} of {len(all_releases)} releases matched ({filter_keywords})")
    print(f"  {len(rungs)} candidate rungs identified")
    print(f"  Archetype distribution: {archetype_distribution(rungs)}")


if __name__ == "__main__":
    main()
