---
description: Cross-company comparative analysis with stage alignment — produces a comparative playbook showing what one company did at equivalent maturity that the other didn't.
argument-hint: <Company A> <Company B> [--anchor-a YYYY-MM-DD] [--anchor-b YYYY-MM-DD] [--out path] [--client-stage X] [--client-industry Y]
---

Invoke the **press-release-analyzer** skill in **comparative mode** for the two companies in $ARGUMENTS.

## Argument parsing

Expected: `<Company A>` `<Company B>` `[flags]`. Examples:
- `/pr-compare Stryker "Boston Scientific"`
- `/pr-compare Acme Globex --anchor-a 2021-09-15 --anchor-b 2003-07-15`
- `/pr-compare ./startup ./mature-co --client-stage seriesA --client-industry medtech`

The first two arguments are **company names** (or paths). Resolve each independently using the same logic as `/pr-analyze`:

1. **If it's clearly a path** (starts with `./`, `/`, `~/`, or contains `/`) — use as-is.
2. **Slugify the name** (lowercase, hyphenate, strip non-alphanumeric).
3. **Try `./<slug>/`** with `releases/` + `manifest.json`.
4. **Fallback — scan subdirectories** of cwd for a `manifest.json` whose `company_name` matches.

If anchor dates are not provided, default to each archive's first release date. **Stage-aligned anchors are the meaningful choice** — pick the date each company became a public-storytelling entity (typically the IPO date, SPAC merger close, or first material wire release). If anchors aren't obvious, ask the user.

If `$ARGUMENTS` has fewer than 2 company names, ask the user.

**Default --out:** `./<slug-a>-vs-<slug-b>/`

## When an archive doesn't exist

If either company can't be resolved:

1. Tell the user clearly which one is missing.
2. **List existing archives** in the cwd (subdirs with `releases/` + `manifest.json`).
3. Suggest: `/pr-archive "<Missing Company>" [TICKER]` to build the missing archive.
4. **Offer to build it inline.** Ask: "Would you like me to run `/pr-archive` for `<Missing Company>` now, then continue with the comparison?" If yes, perform the full archive workflow first. If no, exit gracefully.

If BOTH archives are missing, suggest building both: `/pr-archive "A" TICKA && /pr-archive "B" TICKB && /pr-compare A B`.

## Skill location

Locate the skill scripts via `$PRESS_RELEASE_SKILL_DIR`, then `~/.claude/skills/press-release-archiver/`, then current directory.

## Workflow

### Stage 1 — ensure single-company stats exist for both archives

For each archive, check if `<archive>/analysis/stats.json` and `ladder.json` exist. If missing, run them first:
```bash
python3 <skill>/analyzer/stats.py <archive> [--ceo-names ...]
python3 <skill>/analyzer/ladder.py <archive>
python3 <skill>/analyzer/sample.py <archive>
```

If user didn't provide `--ceo-names` for either, ask — improves CEO-quote detection accuracy meaningfully.

### Stage 2 — comparative pipeline

```bash
python3 <skill>/analyzer/compare.py <archive-a> <archive-b> \
    --anchor-a <date-a> --anchor-b <date-b> \
    --out <comparison-dir>
```

This writes `comparison.json` + `comparison.md` to the comparison dir.

### Stage 3 — comparative synthesis

Read in order:
1. `<comparison-dir>/comparison.md` — primary source
2. Both archives' `patterns.md` and `ladder.md`
3. Both archives' `playbook.md` if they exist (use as style reference, don't duplicate content)
4. Both archives' `sample.md` (skim, focus on releases inside the aligned window)

Write `<comparison-dir>/comparative-playbook.md` with sections:
- **TL;DR** — 3 bullets, the most surprising deltas
- **The two playbooks at a glance** — side-by-side metrics table
- **Dimension 1: Cadence rhythm** (campaign vs. steady-state)
- **Dimension 2: Credibility-ladder pacing**
- **Dimension 3: Stakeholder strategy**
- **Dimension 4: Topic-mix shift over equivalent stages**
- **Five inflection-point plays one company ran that the other didn't**
- **Stage-matched recommendations** — for each client profile (seed/seriesA/seriesB/preIPO), name 2–3 specific plays from one or the other archive they should adopt
- **Caveats** — anchor mismatch, detector bias, sample size, industry calibration

Style guide:
- **Quote actual headlines and dates** from each archive
- **Lean into the deltas** — they ARE the strategy
- **Length:** 2,500–3,500 words

If `--client-stage` and `--client-industry` were provided, weight the recommendations toward that profile.

### Stage 4 — report

Tell the user:
- Path to `comparative-playbook.md`
- 3 most surprising findings (max 60 words each)
- Stage-matched recommendation for the user's typical client profile
- Caveats (especially anchor mismatch — if one archive starts well after the other's equivalent stage, surface this)
- Suggest the next step: `/pr-present <comparison-dir>/comparative-playbook.md` to generate a presentation
