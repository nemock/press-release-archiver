---
description: Analyze a press release archive and produce a strategic playbook (credibility ladder, drumbeat patterns, stakeholder orchestration, foundation plays + recommendations).
argument-hint: <Company Name> [--ceo-names "Name1" "Name2"] [--client-stage seed|seriesA|seriesB|preIPO] [--client-industry medtech|biotech|saas]
---

Invoke the **press-release-analyzer** skill workflow for the company in $ARGUMENTS.

## Argument parsing

Expected: `<Company Name>` `[flags]`. Examples:
- `/pr-analyze Stryker`
- `/pr-analyze "Boston Scientific" --ceo-names "Mike Mahoney"`
- `/pr-analyze Acme --client-stage seriesA --client-industry medtech`

The first argument is a **company name**. Resolve it to an archive directory in the current working directory using this sequence:

1. **If it's clearly a path** (starts with `./`, `/`, `~/`, or contains `/`) — treat as an explicit path. Skip resolution.

2. **Slugify the name** (lowercase, replace spaces with hyphens, strip non-alphanumeric except hyphens):
   - `Stryker` → `stryker`
   - `Boston Scientific` → `boston-scientific`
   - `Acme Medtech, Inc.` → `acme-medtech-inc`

3. **Try the slugified path:** check if `./<slug>/` exists AND contains both `releases/` and `manifest.json`. If yes, that's the archive.

4. **Fallback — scan for matching `company_name` in manifests:** for every subdirectory of cwd that contains `manifest.json`, parse the JSON and check whether `company_name` (case-insensitive) contains the input string. Use the first match. Tell the user which directory you matched.

If `$ARGUMENTS` is empty, ask the user which company to analyze.

## When the archive doesn't exist

If resolution fails (no slugified directory, no manifest match), **don't proceed silently.** Instead:

1. Tell the user clearly: the archive for `<Company>` doesn't appear to exist in the current directory (`<cwd>`).
2. **List existing archives** in the cwd: scan for subdirectories containing `releases/` and `manifest.json`. Show their directory names and (if available from the manifest) the company names. Format as a short table.
3. Suggest the next step:
   ```
   /pr-archive "<Company>" [TICKER]
   ```
4. **Offer to run it inline.** Ask: "Would you like me to run `/pr-archive` for `<Company>` now? It takes 2–5 minutes." If the user agrees, perform the full archive workflow (same as the `/pr-archive` command) — ask for the ticker if needed, run discover/wire-search/fetch/index, then continue into the analysis. If the user declines, exit gracefully.

## Skill location

Locate the skill scripts (try in order):
1. `$PRESS_RELEASE_SKILL_DIR` env var
2. `~/.claude/skills/press-release-archiver/`
3. Current working directory if `analyzer/stats.py` exists there

## Workflow

### Stage 1 — deterministic stats

Run all three Python scripts (substitute `<archive>` with the resolved archive directory):
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
- All five file paths (relative to cwd)
- 3 most surprising findings from the analysis (max 60 words each)
- Any data-quality caveats (small sample size, parser noise, missing CEO names, mature-company earnings dominance, etc.)
- Suggest the next step: `/pr-present <archive>/analysis/playbook.md` to generate a recording-ready presentation
