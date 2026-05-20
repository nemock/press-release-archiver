---
name: press-release-analyzer
description: Reverse-engineer the PR strategy of a public company from a structured press-release archive (the output of press-release-archiver). Produces a strategic playbook with credibility-ladder analysis, drumbeat patterns, stakeholder orchestration, and foundation-phase plays — designed for early-stage companies (seed → Series A → pre-IPO) who want to learn from how mature companies built their narrative. Supports single-company analysis OR comparative analysis with stage alignment (e.g., "what was Globex Corp doing in its first 5 years post-IPO, vs. Acme Medtech in its first 5?"). Token-conscious: deterministic Python computes stats, then YOU (Claude, in this conversation) synthesize the strategic narrative directly.
---

# Press Release Analyzer

Three deterministic Python scripts produce structured inputs (`stats.json`, `ladder.json`, `sample.md`, etc.). YOU then read those artifacts and write the strategic synthesis directly as markdown. No external API calls — all the LLM work happens in the conversation, charged against the user's Claude subscription.

## When invoked

Ask the user for, or infer:

1. **Archive directory** — the output of `press-release-archiver`, e.g. `acme-medtech/`
2. **Mode** — single-company OR comparative (the user will say "compare X and Y" or just give one company)
3. **CEO/founder names** — improves stakeholder-quote attribution. Optional but worth asking about.
4. **Optional filter** — for multi-product-line companies (Abbott, Stryker, Boston Scientific, Johnson & Johnson, etc.) where the archive mixes unrelated business units, ask whether the user wants to narrow the analysis to a specific product line or therapeutic area. If yes, get 3–8 keywords (e.g. `"DBS,deep brain stimulation,Infinity DBS"`). The filter applies word-boundary regex matching across headline + summary + body. Filtered output lands in `<archive>/analysis-<slug>/` so the same archive can drive multiple parallel playbooks (`analysis-dbs/`, `analysis-diabetes-care/`, etc.).
5. **For comparative**: anchor dates for each company. Default = first release in archive. Override with **the IPO/SPAC/Series-A date** if you want stage alignment.

## Stage 1 — Run the deterministic pipeline

For a **single-company** analysis:

```bash
python3 stats.py <archive-dir> --ceo-names "Name1" "Name2"
python3 ladder.py <archive-dir>
python3 sample.py <archive-dir>
```

This writes:
- `<archive>/analysis/stats.json` — full structured stats
- `<archive>/analysis/patterns.md` — human-readable cadence/topic/headline summary
- `<archive>/analysis/ladder.json` + `<archive>/analysis/ladder.md` — candidate credibility-ladder rungs
- `<archive>/analysis/sample.md` — strategic-sample bundle of ~30-80 releases

**With an optional product-line filter** (multi-line conglomerates):

```bash
python3 stats.py <archive-dir> --ceo-names "..." --filter "DBS,deep brain stimulation,Infinity DBS"
python3 ladder.py <archive-dir> --filter "DBS,deep brain stimulation,Infinity DBS"
python3 sample.py <archive-dir> --filter "DBS,deep brain stimulation,Infinity DBS"
```

The filter must be passed **identically** to all three scripts. Output lands in `<archive>/analysis-<slug>/` (the slug is the slugified first keyword, here `dbs`). Override with `--analysis-name <name>` to control the subdirectory name explicitly.

`patterns.md` and `stats.json` both record the active filter and the match rate (e.g. "73 of 487 releases matched"). The synthesis output you write later should explicitly note that the analysis is narrowed to a product line — frame insights as "the company's *DBS communications strategy*" rather than "the company's PR strategy."

For a **comparative** analysis, also run `compare.py`:

```bash
python3 compare.py <archive-a> <archive-b> \
    --anchor-a <yyyy-mm-dd> --anchor-b <yyyy-mm-dd> \
    --out <archive-a>-vs-<archive-b>/
```

With a filter (compares only product-line-relevant releases from each):

```bash
python3 compare.py <archive-a> <archive-b> \
    --anchor-a <yyyy-mm-dd> --anchor-b <yyyy-mm-dd> \
    --filter "DBS,deep brain stimulation" \
    --out <archive-a>-vs-<archive-b>-dbs/
```

This writes:
- `<out>/comparison.json` + `<out>/comparison.md` — stage-aligned cross-company comparison
- (When filtered) `<out>/comparison.json` also records the match rate for each company. If either company has zero matches the script exits with a clear error.

**Important: pick anchor dates that align by company stage, not calendar year.** For each company, choose the date it became a public-storytelling entity (typically the IPO date, SPAC merger close, or first material wire release). Aligning these makes the comparison strategically meaningful — what was each company doing at equivalent maturity, regardless of calendar year.

## Stage 2 — Read the artifacts

Read in this order:
1. `patterns.md` — get the deterministic stats fixed in your head (cadence, topic mix, etc.)
2. `ladder.md` — see the candidate rungs in chronological order
3. `sample.md` — read the actual release content for ~30-80 strategically-selected releases
4. (For comparative) `comparison.md` — see the side-by-side year-by-year deltas

The user is on a Claude monthly subscription, so the cost is your context window, not API tokens. The whole bundle for one company is typically ~15–25K tokens; for a two-company comparison, ~30–50K. Easily fits.

## Stage 3 — Write the strategic synthesis

Produce **five files** in the analysis directory (or the comparison output dir for comparative mode), each as a focused, standalone deliverable. Then concatenate them into a combined `playbook.md`. Use the Write tool.

### File 1 — `credibility-ladder.md`

The chronological proof-point sequence. Curate the candidate rungs from `ladder.md`: keep what's strategically meaningful (capital events, regulatory milestones, clinical demonstrations, flagship partnerships); drop the noise (routine appointments unless transformative, building-opening fluff, conference scheduling). For each kept rung:
- Date + headline
- Why it matters strategically (1 sentence)
- Days since previous rung (already computed)
- What the rung enabled / what it set up

End with a **Lessons section** answering: how were proof-points sequenced? What pattern in spacing? What rung-types dominated each phase? What's the *minimum viable ladder* an early-stage company could borrow from this?

### File 2 — `drumbeat-map.md`

Cadence patterns and what they reveal. From `patterns.md`'s clusters, silences, and per-year counts:
- Identify the 3–5 most strategically meaningful clusters (drumbeat campaigns) and what they were building toward
- Identify the most meaningful silences (60+ day gaps) — what was being prepared during the quiet?
- Note overall cadence rhythm — steady (Globex Corp-style) or campaign-driven (Acme Medtech-style)?
- For each cluster, list the headlines + your inference of the strategic intent

End with **applicable plays** for an early-stage client.

### File 3 — `validator-sequence.md`

Stakeholder orchestration. From the stakeholder data in `stats.json` and the sample releases:
- When did internal voices give way to clinical voices and institutional voices?
- What was the company's first third-party-validated release? What did that signal?
- How was the CEO quote rate used? Always a CEO quote, or selectively?
- What kinds of validators were brought in at what stages?

End with **the validator-recruitment playbook**: at what milestone do you bring in surgeons / customers / hospitals / board members / investors? What's the right order?

### File 4 — `foundation-plays.md`

Specifically scoped to **Years 1–3** of the archive (Foundation→Build phase). For each year:
- What categories of releases did the company prioritize?
- What were the 5–8 dominant play types? (e.g., "headquarters opening," "key hire," "advisory board reveal," "first customer," "TIME's Best Inventions appearance")
- For each play, give a generic template an early-stage client could adapt

This is the highest-value deliverable for the user's stated client base (seed → pre-IPO).

### File 5 — `playbook.md` (combined)

Stitch all four files together with a brief executive summary at the top:
- 3-bullet TL;DR
- "Top 3 plays this archive teaches"
- Then sections for each of the four analyses above
- Final "Caveats and limitations" section

For **comparative mode**, also produce a sixth file:

### File 6 — `comparative-playbook.md` (only for `--compare`)

Read `comparison.md` and write a head-to-head comparison along these dimensions:
- Cadence rhythm (campaign-driven vs steady-state)
- Credibility-ladder pacing (how fast each company climbed)
- Stakeholder strategy (CEO-centric vs distributed voices)
- Topic mix shift over equivalent stages
- Three to five **inflection-point plays** that one company did and the other didn't (or did differently)

End with a **stage-matched recommendations** section: which playbook best fits the user's seed/Series-A/pre-IPO clients, and why.

## Style guide for synthesis

- **Be specific.** Quote actual headlines and dates from the archive. Don't say "they used a lot of partnerships" — say "they signed 4 hospital-system agreements in 18 months (Partner A Sept 2023, Partner B Aug 2024, Partner C May 2025, [next] X)."
- **Surface contrasts.** When stats reveal a delta (e.g., one company has a much higher CEO quote rate than the other, or one has zero clusters while the other has many), call it out. The deltas are the strategy.
- **Make it actionable.** End each file's analysis section with at least one "play" a client could literally execute next quarter.
- **Don't moralize.** Note when crisis communications happened (delistings, departures) and analyze the language they used; don't praise or critique.
- **Token discipline.** You don't need to load full bodies of every release. The sample bundle was specifically curated to give you what you need.

## Reporting back

After writing the files, report to the user:
- Which files were written and their paths
- 2–3 most surprising findings from the analysis (the kind of thing they'd want to highlight to a client)
- Any caveats (small-sample issues, classification noise, missing data)
- For comparative mode: the most strategically actionable contrast between the two companies

## Failure modes to watch for

- **Too few releases** — under ~15 releases, statistical patterns are unreliable; surface this caveat.
- **Mature company with mostly earnings releases** — Globex Corp's archive is dominated by quarterly reporting; the *interesting* releases are the rare non-earnings events (FDA updates, share repurchases, settlements). Lean into those.
- **Anchor mismatch** — for comparative, if the two anchor dates aren't actually equivalent in company stage, surface this and recommend a different anchor.
- **CEO names not provided** — without them, CEO quote rate is undercounted. Ask the user for known CEO/founder names if they didn't provide.
