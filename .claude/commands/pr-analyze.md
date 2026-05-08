---
description: Analyze a press release archive and produce a strategic playbook (credibility ladder, drumbeat patterns, stakeholder orchestration, foundation plays + recommendations).
argument-hint: <archive-dir> [--ceo-names "Name1" "Name2"] [--client-stage seed|seriesA|seriesB|preIPO] [--client-industry medtech|biotech|saas]
---

Invoke the **press-release-analyzer** skill workflow for the archive specified in $ARGUMENTS.

## Argument parsing

Expected: `<archive-dir>` `[flags]`. Examples:
- `/pr-analyze ./acme-medtech/`
- `/pr-analyze ~/research/bsx/ --ceo-names "Kevin Lobo"`
- `/pr-analyze ./globex/ --client-stage seriesA --client-industry medtech`

The archive directory should contain `releases/`, `manifest.json`, and `INDEX.md` (the output of `/pr-archive`).

If `$ARGUMENTS` is empty, ask the user which archive to analyze and offer to list candidates by scanning common locations (`./`, `~/research/`, current directory subfolders containing `releases/`).

## Skill location

Locate the skill scripts (try in order):
1. `$PRESS_RELEASE_SKILL_DIR` environment variable
2. `~/.claude/skills/press-release-archiver/`
3. Current working directory if `analyzer/stats.py` exists there

## Workflow

### Stage 1 — deterministic stats

Run all three Python scripts:
```bash
python3 <skill>/analyzer/stats.py <archive> [--ceo-names ...]
python3 <skill>/analyzer/ladder.py <archive>
python3 <skill>/analyzer/sample.py <archive>
```

These write to `<archive>/analysis/`:
- `stats.json` + `patterns.md`
- `ladder.json` + `ladder.md`
- `sample.md`

Show the user the high-level stats from `stats.py`'s stdout (release count, median gap, cluster count, CEO quote rate).

### Stage 2 — synthesis (you do this)

Read in order:
1. `<archive>/analysis/patterns.md` — deterministic stats
2. `<archive>/analysis/ladder.md` — candidate ladder rungs
3. `<archive>/analysis/sample.md` — strategically-sampled releases

Then write four focused analytical files into `<archive>/analysis/`:
- `credibility-ladder.md` — curated proof-point sequence with pacing analysis
- `drumbeat-map.md` — cadence pattern analysis with strategic clusters/silences
- `validator-sequence.md` — stakeholder orchestration over time
- `foundation-plays.md` — Years 1–3 emulatable plays

Plus a combined `playbook.md` that stitches all four together with an executive TL;DR (3 bullets), top 3 plays, and a "Caveats" section at the end.

Style guide for each file:
- **Quote actual headlines and dates** from the archive — don't generalize
- **Surface specific deltas** (e.g., "median 24-day gap" vs the playbook's expected pattern)
- **End each section with applicable plays** the user can run
- 800–1,500 words per file; the combined playbook 2,500–4,000 words

If `--client-stage` and/or `--client-industry` flags were provided, tailor the recommendations sections accordingly:
- **seed/seriesA** → emphasize Foundation Plays (HQ, key hire, awards, named investors)
- **seriesB** → emphasize Drumbeat (campaigns) + Validator Sequence
- **preIPO** → emphasize Hospital/Customer-Validation + Crisis-Recovery Pair
- **medtech** → use clinical-ladder language; **biotech** → trial-readout language; **saas** → enterprise-customer + ARR language

### Stage 3 — report

After writing all five files, tell the user:
- All five file paths
- 3 most surprising findings from the analysis (max 60 words each)
- Any data-quality caveats (small sample size, parser noise, missing CEO names, mature-company earnings dominance, etc.)
- Suggest the next step: `/pr-present <archive>/analysis/playbook.md` to generate a presentation
