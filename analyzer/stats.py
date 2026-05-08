#!/usr/bin/env python3
"""
stats.py — Pass 1 of the press-release-analyzer skill.

Reads a press-release archive (the output of press-release-archiver) and
produces deterministic statistics: cadence, topic mix, headline patterns,
body length trends, and stakeholder/quote heuristics.

The output is consumed by the LLM synthesis step (Claude reading these
artifacts in conversation), so it's structured for easy reasoning rather
than for charts. Two artifacts are written:
  - <out>/stats.json    machine-readable, full structured stats
  - <out>/patterns.md   human-readable summary, used as Claude's context

Usage:
  python3 stats.py <archive-dir>
  python3 stats.py acme-medtech/ --out acme-medtech/analysis/
"""

import argparse
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path


# ---------------------------------------------------------------------------
# Frontmatter parser (mirrors build_index.py)
# ---------------------------------------------------------------------------

def parse_release(path):
    """Return a dict of frontmatter + body, or None if file is malformed."""
    text = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        return None
    fm_block, rest = m.group(1), m.group(2)
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

    summary_m = re.search(r"## Summary\n+(.+?)(?:\n##|\Z)", rest, re.S)
    body_m = re.search(r"## Full Press Release\n+(.+)$", rest, re.S)
    return {
        "path": str(path),
        "filename": path.name,
        "date": fm.get("date", ""),
        "headline": fm.get("headline", "") or "",
        "source_url": fm.get("source_url", ""),
        "edgar_accession": fm.get("edgar_accession", ""),
        "tags": fm.get("tags", []) if isinstance(fm.get("tags"), list) else [],
        "summary": (summary_m.group(1).strip() if summary_m else ""),
        "body": (body_m.group(1).strip() if body_m else ""),
    }


# ---------------------------------------------------------------------------
# Core analyses
# ---------------------------------------------------------------------------

def cadence_stats(releases):
    """Release timing patterns: yearly/quarterly/monthly counts, gaps,
    silences (gaps > 60 days), and clusters (3+ releases within 14 days)."""
    by_year = Counter()
    by_quarter = Counter()
    by_month = Counter()
    by_dow = Counter()
    dates = []
    for r in releases:
        try:
            d = datetime.strptime(r["date"], "%Y-%m-%d")
        except ValueError:
            continue
        dates.append((d, r))
        by_year[d.strftime("%Y")] += 1
        by_quarter[f"{d.year}-Q{(d.month - 1) // 3 + 1}"] += 1
        by_month[d.strftime("%Y-%m")] += 1
        by_dow[d.strftime("%A")] += 1

    dates.sort(key=lambda x: x[0])
    gaps = []
    silences = []
    for i in range(1, len(dates)):
        gap = (dates[i][0] - dates[i - 1][0]).days
        gaps.append(gap)
        if gap > 60:
            silences.append({
                "start": dates[i - 1][0].strftime("%Y-%m-%d"),
                "end": dates[i][0].strftime("%Y-%m-%d"),
                "days": gap,
                "before_headline": dates[i - 1][1]["headline"][:100],
                "after_headline": dates[i][1]["headline"][:100],
            })

    # Cluster detection: 3+ releases within a 14-day rolling window
    clusters = []
    i = 0
    while i < len(dates):
        j = i
        while (j + 1 < len(dates)
               and (dates[j + 1][0] - dates[i][0]).days <= 14):
            j += 1
        if j - i >= 2:  # 3 or more (i, i+1, i+2 minimum)
            cluster = {
                "start": dates[i][0].strftime("%Y-%m-%d"),
                "end": dates[j][0].strftime("%Y-%m-%d"),
                "count": j - i + 1,
                "headlines": [d[1]["headline"][:80] for d in dates[i:j + 1]],
            }
            clusters.append(cluster)
            i = j + 1
        else:
            i += 1

    return {
        "by_year": dict(sorted(by_year.items())),
        "by_quarter": dict(sorted(by_quarter.items())),
        "by_month": dict(sorted(by_month.items())),
        "by_dow": dict(by_dow),
        "median_gap_days": int(statistics.median(gaps)) if gaps else None,
        "p10_gap_days": (sorted(gaps)[len(gaps) // 10] if gaps else None),
        "p90_gap_days": (sorted(gaps)[(len(gaps) * 9) // 10] if gaps else None),
        "max_gap_days": max(gaps) if gaps else None,
        "silences": silences,
        "clusters": clusters,
    }


def topic_stats(releases):
    """Tag distribution overall + per year, plus first/last appearance per tag."""
    overall = Counter()
    by_year = defaultdict(Counter)
    first_appearance = {}
    last_appearance = {}
    for r in releases:
        year = r["date"][:4]
        for t in r["tags"]:
            overall[t] += 1
            by_year[year][t] += 1
            if t not in first_appearance or r["date"] < first_appearance[t]["date"]:
                first_appearance[t] = {"date": r["date"], "headline": r["headline"]}
            if t not in last_appearance or r["date"] > last_appearance[t]["date"]:
                last_appearance[t] = {"date": r["date"], "headline": r["headline"]}
    return {
        "overall": dict(overall.most_common()),
        "by_year": {y: dict(c.most_common()) for y, c in sorted(by_year.items())},
        "first_appearance": first_appearance,
        "last_appearance": last_appearance,
    }


# Stop words for headline n-gram analysis
HEADLINE_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "with",
    "and", "or", "as", "by", "is", "are", "was", "were", "be", "been",
    "its", "their", "this", "that", "these", "those",
}


def headline_stats(releases, company_name=""):
    """Headline length distribution, common starting verbs, common phrases."""
    word_counts = []
    starts_with_company = 0
    starts_with_verb = Counter()
    bigrams = Counter()
    trigrams = Counter()
    all_caps = 0

    company_first_word = company_name.split()[0].lower() if company_name else None

    for r in releases:
        h = r["headline"]
        if not h:
            continue
        words = h.split()
        word_counts.append(len(words))
        if h.upper() == h and len(h) > 3:
            all_caps += 1
        if (company_first_word
                and words and words[0].lower() == company_first_word):
            starts_with_company += 1
            # First "verb" is typically the second/third word ("Acme Medtech Announces ...")
            for w in words[1:4]:
                wl = w.lower().strip(",.;:")
                if wl and wl not in HEADLINE_STOPWORDS and wl != company_first_word:
                    starts_with_verb[wl] += 1
                    break
        # Bigrams + trigrams over headline (lowercase, alphanumeric)
        clean = [w.lower().strip(",.;:!?\"'()") for w in words]
        clean = [w for w in clean if w and w.isalpha() and w not in HEADLINE_STOPWORDS]
        for i in range(len(clean) - 1):
            bigrams[(clean[i], clean[i + 1])] += 1
        for i in range(len(clean) - 2):
            trigrams[(clean[i], clean[i + 1], clean[i + 2])] += 1

    return {
        "count": len(word_counts),
        "avg_word_count": (sum(word_counts) / len(word_counts) if word_counts else 0),
        "median_word_count": (statistics.median(word_counts) if word_counts else 0),
        "max_word_count": max(word_counts) if word_counts else 0,
        "min_word_count": min(word_counts) if word_counts else 0,
        "starts_with_company_count": starts_with_company,
        "starts_with_company_pct": (starts_with_company / len(word_counts)
                                    if word_counts else 0),
        "all_caps_count": all_caps,
        "all_caps_pct": all_caps / len(word_counts) if word_counts else 0,
        "common_starting_verbs": [{"verb": v, "count": c}
                                   for v, c in starts_with_verb.most_common(15)],
        "common_bigrams": [{"phrase": " ".join(p), "count": c}
                           for p, c in bigrams.most_common(20)],
        "common_trigrams": [{"phrase": " ".join(p), "count": c}
                            for p, c in trigrams.most_common(15)],
    }


def body_stats(releases):
    """Body length trends + quote density."""
    word_counts_by_year = defaultdict(list)
    quote_counts = []
    quote_counts_by_year = defaultdict(list)
    for r in releases:
        if not r["body"]:
            continue
        wc = len(r["body"].split())
        word_counts_by_year[r["date"][:4]].append(wc)
        # Naive quote count: count of `"..."` patterns >= 30 chars
        quotes = re.findall(r'"([^"\n]{30,500})"', r["body"])
        # Also accommodate curly quotes used by wire services
        quotes += re.findall(r'“([^”\n]{30,500})”', r["body"])
        quote_counts.append(len(quotes))
        quote_counts_by_year[r["date"][:4]].append(len(quotes))
    return {
        "word_count_avg_by_year": {y: round(sum(v) / len(v))
                                    for y, v in sorted(word_counts_by_year.items())},
        "word_count_median_overall": (statistics.median(
            [w for v in word_counts_by_year.values() for w in v]
        ) if word_counts_by_year else 0),
        "quote_count_avg": (sum(quote_counts) / len(quote_counts)
                             if quote_counts else 0),
        "quote_count_avg_by_year": {y: round(sum(v) / len(v), 2)
                                     for y, v in sorted(quote_counts_by_year.items())},
    }


def stakeholder_stats(releases, ceo_names=None):
    """Detect quoted speakers and classify (CEO / clinician / institutional / other).
    Also surface the FIRST third-party quote — a key strategic moment."""
    ceo_names = ceo_names or []
    # Extract "<...>," said NAME, TITLE pattern + similar
    speaker_pattern = re.compile(
        r'[\"“”]\s*[,.\s]*\s*said\s+'
        r'(?:Dr\.?\s+)?([A-Z][a-zA-Z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-zA-Z]+)'
        r'(?:,\s*([^.]+?))?(?=[.\n])',
        re.M,
    )
    by_year = defaultdict(Counter)
    first_third_party_release = None
    speaker_categories = {
        "ceo": 0,
        "internal": 0,  # other officers
        "clinical": 0,  # surgeons, doctors
        "institutional": 0,  # hospital execs, partner orgs
    }
    ceo_quote_count = 0
    releases_with_any_quote = 0
    for r in releases:
        if not r["body"]:
            continue
        speakers = speaker_pattern.findall(r["body"])
        if speakers:
            releases_with_any_quote += 1
        year = r["date"][:4]
        seen_third_party = False
        for name, title in speakers:
            tl = (title or "").lower()
            cat = "internal"
            is_ceo = any(c.lower() in name.lower() for c in ceo_names)
            if is_ceo or "ceo" in tl or "chief executive" in tl:
                cat = "ceo"
                ceo_quote_count += 1
            elif "dr." in name.lower() or "md" in tl or "surgeon" in tl:
                cat = "clinical"
                seen_third_party = True
            elif ("hospital" in tl or "health" in tl
                  or "president of" in tl or "chair" in tl
                  or "venture" in tl or "founder" in tl
                  and "co-founder" not in tl):
                cat = "institutional"
                seen_third_party = True
            speaker_categories[cat] += 1
            by_year[year][cat] += 1
        if seen_third_party and first_third_party_release is None:
            first_third_party_release = {
                "date": r["date"],
                "headline": r["headline"],
                "speakers": [{"name": n, "title": t.strip() if t else ""}
                             for n, t in speakers
                             if any(k in (t or "").lower() for k in
                                    ("md", "surgeon", "hospital", "health",
                                     "president of", "chair"))],
            }
    return {
        "releases_with_quote": releases_with_any_quote,
        "speaker_categories": speaker_categories,
        "ceo_quote_count": ceo_quote_count,
        "ceo_quote_rate": (ceo_quote_count / len(releases) if releases else 0),
        "by_year": {y: dict(c) for y, c in sorted(by_year.items())},
        "first_third_party_release": first_third_party_release,
    }


# ---------------------------------------------------------------------------
# Patterns.md generator — human-readable summary the LLM consumes
# ---------------------------------------------------------------------------

def render_patterns_md(stats, company_name):
    L = []
    L.append(f"# {company_name} — Press Release Pattern Analysis")
    L.append("")
    L.append(f"**Releases analyzed:** {stats['release_count']}  ")
    L.append(f"**Coverage:** {stats['date_range']['first']} → {stats['date_range']['last']}  ")
    if stats.get("ticker"):
        L.append(f"**Ticker:** {stats['ticker']}")
    L.append("")
    L.append("---")
    L.append("")

    # CADENCE
    c = stats["cadence"]
    L.append("## Cadence")
    L.append("")
    L.append(f"- Median gap between releases: **{c['median_gap_days']} days**")
    L.append(f"- p10 / p90 gap: {c['p10_gap_days']} / {c['p90_gap_days']} days")
    L.append(f"- Largest gap (silence): **{c['max_gap_days']} days**")
    L.append("")
    L.append("**Releases per year:**")
    L.append("")
    L.append("| Year | Count |")
    L.append("|---|---|")
    for y, n in c["by_year"].items():
        L.append(f"| {y} | {n} |")
    L.append("")
    if c["clusters"]:
        L.append(f"**Strategic clusters** ({len(c['clusters'])} found — 3+ releases within 14 days):")
        L.append("")
        for cl in c["clusters"][:8]:
            L.append(f"- **{cl['start']} → {cl['end']}** ({cl['count']} releases)")
            for h in cl["headlines"][:5]:
                L.append(f"  - {h}")
        L.append("")
    if c["silences"]:
        L.append(f"**Strategic silences** ({len(c['silences'])} found — gaps > 60 days):")
        L.append("")
        for s in c["silences"][:10]:
            L.append(f"- **{s['start']} → {s['end']}** ({s['days']} days)")
            L.append(f"  - Before: {s['before_headline']}")
            L.append(f"  - After: {s['after_headline']}")
        L.append("")

    # TOPIC MIX
    t = stats["topics"]
    L.append("## Topic mix")
    L.append("")
    L.append("| Tag | Total | First appeared |")
    L.append("|---|---|---|")
    for tag, n in t["overall"].items():
        first = t["first_appearance"].get(tag, {}).get("date", "—")
        L.append(f"| `{tag}` | {n} | {first} |")
    L.append("")
    L.append("**Topic mix evolution** (count per year):")
    L.append("")
    if t["by_year"]:
        all_tags = sorted(t["overall"].keys())
        header = "| Year | " + " | ".join(f"`{tag}`" for tag in all_tags) + " |"
        sep = "|---|" + "---|" * len(all_tags)
        L.append(header)
        L.append(sep)
        for year, counts in t["by_year"].items():
            row = "| " + year + " | " + " | ".join(str(counts.get(tag, 0)) for tag in all_tags) + " |"
            L.append(row)
        L.append("")

    # HEADLINES
    h = stats["headlines"]
    L.append("## Headline patterns")
    L.append("")
    L.append(f"- Average word count: **{h['avg_word_count']:.1f}** "
             f"(median {h['median_word_count']}, range {h['min_word_count']}–{h['max_word_count']})")
    L.append(f"- Releases starting with company name: **{h['starts_with_company_pct']:.0%}** "
             f"({h['starts_with_company_count']}/{h['count']})")
    L.append(f"- All-caps headlines: {h['all_caps_pct']:.0%} ({h['all_caps_count']}/{h['count']})")
    if h["common_starting_verbs"]:
        L.append("")
        L.append("**Most common headline verbs** (after company name):")
        L.append("")
        for v in h["common_starting_verbs"][:10]:
            L.append(f"- {v['verb']}: {v['count']}")
    if h["common_trigrams"]:
        L.append("")
        L.append("**Most common headline 3-grams:**")
        L.append("")
        for t in h["common_trigrams"][:10]:
            L.append(f"- *{t['phrase']}* ({t['count']})")
    L.append("")

    # BODY TRENDS
    b = stats["bodies"]
    L.append("## Body & quote patterns")
    L.append("")
    L.append(f"- Median body word count: **{int(b['word_count_median_overall'])}**")
    L.append(f"- Average quotes per release: **{b['quote_count_avg']:.1f}**")
    L.append("")
    L.append("**Body length & quote density by year:**")
    L.append("")
    L.append("| Year | Avg word count | Avg quotes |")
    L.append("|---|---|---|")
    years = sorted(set(list(b["word_count_avg_by_year"].keys())
                       + list(b["quote_count_avg_by_year"].keys())))
    for y in years:
        wc = b["word_count_avg_by_year"].get(y, "—")
        qc = b["quote_count_avg_by_year"].get(y, "—")
        L.append(f"| {y} | {wc} | {qc} |")
    L.append("")

    # STAKEHOLDERS
    s = stats["stakeholders"]
    L.append("## Stakeholder orchestration")
    L.append("")
    L.append(f"- Releases with at least one quote: **{s['releases_with_quote']}/{stats['release_count']}**")
    L.append(f"- CEO quote rate: **{s['ceo_quote_rate']:.0%}**")
    L.append("")
    L.append("**Speakers across the corpus by category:**")
    L.append("")
    for cat, n in s["speaker_categories"].items():
        L.append(f"- {cat}: {n}")
    L.append("")
    if s.get("first_third_party_release"):
        ft = s["first_third_party_release"]
        L.append(f"**First third-party (clinical/institutional) quote:** "
                 f"{ft['date']} — *{ft['headline']}*")
        for sp in ft.get("speakers", [])[:3]:
            L.append(f"  - {sp['name']} ({sp['title']})")
        L.append("")

    return "\n".join(L)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def collect_company_meta(archive_dir, manifest_path=None):
    """Try to pull company name + ticker from manifest.json (modern), then
    INDEX.md header (legacy archives), then fall back to directory name.
    Returns (company_name, ticker, manifest_dict_or_None).
    """
    archive_dir = Path(archive_dir)
    if manifest_path is None:
        manifest_path = archive_dir / "manifest.json"
    if Path(manifest_path).exists():
        m = json.loads(Path(manifest_path).read_text())
        return m.get("company_name", archive_dir.name), m.get("ticker", ""), m

    # Fall back to INDEX.md header parsing
    index_path = archive_dir / "INDEX.md"
    if index_path.exists():
        text = index_path.read_text()
        name_m = re.search(r"^# (.+?)(?:\s*[—-]\s*Press Release Archive)?$", text, re.M)
        ticker_m = re.search(r"\*\*Ticker:?\*?\*?:?\s*(?:NYSE:?\s*|Nasdaq:?\s*)?(\w{2,6})", text, re.I)
        name = name_m.group(1).strip() if name_m else archive_dir.name
        ticker = ticker_m.group(1).strip() if ticker_m else ""
        return name, ticker, None

    return archive_dir.name, "", None


def main():
    ap = argparse.ArgumentParser(description="Compute deterministic statistics from a press-release archive.")
    ap.add_argument("archive_dir", help="path to the company archive (contains releases/, manifest.json, INDEX.md)")
    ap.add_argument("--out", default=None, help="output directory (default: <archive>/analysis/)")
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--company-name", default=None,
                    help="Override company name (default: from manifest/INDEX/dir)")
    ap.add_argument("--ticker", default=None,
                    help="Override ticker symbol")
    ap.add_argument("--ceo-names", nargs="*", default=[],
                    help="CEO/founder names to detect in quote attributions "
                         "(e.g. --ceo-names \"Jane Smith\" \"John Doe\")")
    args = ap.parse_args()

    archive_dir = Path(args.archive_dir)
    out_dir = Path(args.out or archive_dir / "analysis")
    out_dir.mkdir(parents=True, exist_ok=True)

    company_name, ticker, manifest = collect_company_meta(archive_dir, args.manifest)
    if args.company_name:
        company_name = args.company_name
    if args.ticker:
        ticker = args.ticker

    releases = []
    for p in sorted((archive_dir / "releases").glob("*.md")):
        r = parse_release(p)
        if r:
            releases.append(r)
    if not releases:
        raise SystemExit(f"No release files found in {archive_dir / 'releases'}")
    releases.sort(key=lambda x: x["date"])

    stats = {
        "company": company_name,
        "ticker": ticker,
        "release_count": len(releases),
        "date_range": {"first": releases[0]["date"], "last": releases[-1]["date"]},
        "cadence": cadence_stats(releases),
        "topics": topic_stats(releases),
        "headlines": headline_stats(releases, company_name),
        "bodies": body_stats(releases),
        "stakeholders": stakeholder_stats(releases, ceo_names=args.ceo_names),
    }

    (out_dir / "stats.json").write_text(json.dumps(stats, indent=2, default=str))
    (out_dir / "patterns.md").write_text(render_patterns_md(stats, company_name))

    print(f"Wrote {out_dir / 'stats.json'}")
    print(f"Wrote {out_dir / 'patterns.md'}")
    print()
    print(f"  {len(releases)} releases analyzed")
    print(f"  Coverage: {stats['date_range']['first']} → {stats['date_range']['last']}")
    print(f"  Median gap: {stats['cadence']['median_gap_days']} days")
    print(f"  Clusters detected: {len(stats['cadence']['clusters'])}")
    print(f"  Silences detected: {len(stats['cadence']['silences'])}")
    print(f"  CEO quote rate: {stats['stakeholders']['ceo_quote_rate']:.0%}")


if __name__ == "__main__":
    main()
