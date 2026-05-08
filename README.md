# press-release skills (archiver + analyzer + presenter)

Three sibling Claude skills that together turn any publicly-traded company's press releases into a client-ready strategic playbook and recording-optimized slide deck:

| Skill | What it does | When to use |
|---|---|---|
| **[`archiver/`](./archiver/)** | Compiles every press release a company has ever issued into a structured local markdown archive (one file per release + `INDEX.md`). Three-tier fetcher: SEC EDGAR → Wayback Machine → Chrome Connector. | When you want offline-resilient access to a competitor's full PR history. |
| **[`analyzer/`](./analyzer/)** | Reverse-engineers the PR strategy from an archive — credibility ladder, drumbeat patterns, stakeholder orchestration, foundation-phase plays. Supports stage-aligned cross-company comparison. | When you want to extract emulatable plays from a mature company's PR program for an early-stage client. |
| **[`presenter/`](./presenter/)** | Turns a strategic playbook into a recording-ready HTML slide deck, ending with concrete recommendations the client can run next quarter. Single self-contained HTML file, dark theme, keyboard navigation, chapter sidebar. | When you want to deliver the strategy to a client in a presentable format — Loom-style explainer, Zoom call, or live walkthrough. |

Designed for marketing/strategy work with **early-stage companies** (seed → Series A → pre-IPO) who want to learn from how mature growth-stage companies built their narrative arcs.

---

## Quick start (slash commands)

For Claude Code users, the repo includes 5 slash commands that wrap each pipeline:

| Command | What it does |
|---|---|
| `/pr-archive "<Company>" [TICKER]` | Build the full press-release archive (EDGAR + Wayback + optional Chrome) |
| `/pr-analyze "<Company>"` | Compute stats + write the strategic playbook (5 markdown files) |
| `/pr-compare "<Company A>" "<Company B>"` | Stage-aligned comparative analysis between two companies |
| `/pr-update "<Company>"` | Incrementally refresh an existing archive with new releases |
| `/pr-present <playbook-path>` | Generate a recording-ready HTML slide deck from a playbook |

The analyze, compare, and update commands accept a company **name** (or path). The name is slugified (`Boston Scientific` → `boston-scientific`) and matched against archive directories in your current working directory. If the archive doesn't exist, the command tells you and offers to run `/pr-archive` for you.

### Install

```bash
git clone https://github.com/nemock/press-release-archiver.git ~/.claude/skills/press-release-archiver
cd ~/.claude/skills/press-release-archiver
bash install.sh
echo 'export PRESS_RELEASE_SKILL_DIR="$HOME/.claude/skills/press-release-archiver"' >> ~/.zshrc
```

That copies the commands to `~/.claude/commands/` (so they're available in any Claude Code session, not just inside the cloned repo) and points the `$PRESS_RELEASE_SKILL_DIR` env var at the skill's Python scripts.

### End-to-end example

```
/pr-archive "Stryker" SYK
/pr-analyze Stryker --client-stage seriesA --client-industry medtech
/pr-present ./stryker/analysis/playbook.md --open
```

Or for a comparative analysis:

```
/pr-archive "Stryker" SYK
/pr-archive "Boston Scientific" BSX
/pr-compare Stryker "Boston Scientific" --client-stage seriesA
/pr-present ./stryker-vs-boston-scientific/comparative-playbook.md --open
```

### Without slash commands (raw pipeline)

If you'd rather invoke the Python scripts directly:

```bash
# 1. Build an archive
python3 archiver/discover.py "Acme Medtech" --ticker ACME --out ../acme/manifest.json
python3 archiver/fetch.py ../acme/manifest.json --out ../acme/releases/ --tags medtech
python3 archiver/build_index.py --releases ../acme/releases/ --manifest ../acme/manifest.json \
    --out ../acme/INDEX.md

# 2. Run deterministic analysis
python3 analyzer/stats.py ../acme/ --ceo-names "Jane Smith" "John Doe"
python3 analyzer/ladder.py ../acme/
python3 analyzer/sample.py ../acme/

# 3. Then ask Claude in conversation: "synthesize the analysis into a playbook"
#    (the LLM-driven synthesis happens in the chat; no external API calls)

# 4. For comparative analysis:
python3 analyzer/compare.py acme/ globex/ \
    --anchor-a <yyyy-mm-dd> --anchor-b <yyyy-mm-dd> \
    --out acme-vs-globex/

# 5. To generate the HTML presentation, ask Claude: "make a presentation
#    from the playbook at <path>" — Claude reads the template and writes
#    presentation.html.
```

The `compare.py` script aligns companies by **company-relative time** (months since IPO/anchor) rather than calendar year — so a mature company's archive from a decade or two ago maps directly onto an early-stage company's recent post-IPO window because both cover roughly equivalent stages of public-company maturity.

---

## What you actually get out

For one company, an analysis package looks like:

```
acme-medtech/
├── INDEX.md                       # navigable archive index
├── manifest.json                  # discovery output
├── releases/                      # one .md per press release (verbatim body)
└── analysis/
    ├── stats.json                 # deterministic stats
    ├── patterns.md                # human-readable cadence/topic patterns
    ├── ladder.json                # candidate credibility-ladder rungs
    ├── ladder.md                  # rungs by archetype
    ├── sample.md                  # ~30-80 strategically-sampled releases
    │
    ├── credibility-ladder.md      # SYNTHESIZED: curated proof-point sequence
    ├── drumbeat-map.md            # SYNTHESIZED: cadence-pattern analysis
    ├── validator-sequence.md      # SYNTHESIZED: stakeholder orchestration
    ├── foundation-plays.md        # SYNTHESIZED: Years 1-3 emulatable plays
    └── playbook.md                # SYNTHESIZED: combined master document
```

For comparative mode, an additional `acme-vs-globex/` directory holds the cross-company comparison.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  ARCHIVER  (deterministic Python)                               │
│                                                                 │
│  discover.py  →  fetch.py  →  build_index.py                    │
│       ↓             ↓              ↓                            │
│  manifest.json  releases/*.md   INDEX.md                        │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  ANALYZER  (Python stats + Claude synthesis)                    │
│                                                                 │
│  stats.py    ladder.py    sample.py    compare.py               │
│      ↓           ↓            ↓             ↓                   │
│  patterns.md  ladder.md   sample.md   comparison.md             │
│                              │                                  │
│                              ▼                                  │
│      Claude reads artifacts in conversation                     │
│                              │                                  │
│                              ▼                                  │
│  credibility-ladder.md, drumbeat-map.md, validator-sequence.md, │
│  foundation-plays.md, playbook.md, comparative-playbook.md      │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PRESENTER  (Claude composes; HTML template renders)            │
│                                                                  │
│  template.html  +  Claude-authored SLIDES JSON array            │
│        ↓                                                         │
│  presentation.html — single self-contained file, dark theme,    │
│  keyboard nav, chapter sidebar, recording-optimized              │
└─────────────────────────────────────────────────────────────────┘
```

Two design principles:

1. **Python handles the deterministic work** (HTTP fetches, HTML parsing, statistical aggregation, structured sampling). The LLM handles the judgment work (curating which releases really represent strategic milestones, identifying narrative themes, drafting human-readable plays).
2. **No external API dependency for the analyzer**. Synthesis runs in the user's Claude conversation, charged against the monthly subscription. No API key required, no per-token billing surprises.

---

## When the comparative mode is most useful

The contrast between a mid-stage build company (~5–10 years public, dozens of releases) and a mature scale company (~20+ years public, hundreds of releases) is itself the lesson. A campaign-driven build company will typically show a short median release gap and 3–8 strategic clusters; a steady-state mature company shows a much longer median gap and few or zero clusters. Two stages, two playbooks. The skill helps you identify which to borrow from for the company you're advising.

---

## License

MIT. See [LICENSE](LICENSE).
