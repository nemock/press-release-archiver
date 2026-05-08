# press-release skills (archiver + analyzer + presenter)

Three sibling Claude skills that together turn any publicly-traded company's press releases into a client-ready strategic playbook and recording-optimized slide deck:

| Skill | What it does | When to use |
|---|---|---|
| **[`archiver/`](./archiver/)** | Compiles every press release a company has ever issued into a structured local markdown archive (one file per release + `INDEX.md`). Three-tier fetcher: SEC EDGAR → Wayback Machine → Chrome Connector. | When you want offline-resilient access to a competitor's full PR history. |
| **[`analyzer/`](./analyzer/)** | Reverse-engineers the PR strategy from an archive — credibility ladder, drumbeat patterns, stakeholder orchestration, foundation-phase plays. Supports stage-aligned cross-company comparison. | When you want to extract emulatable plays from a mature company's PR program for an early-stage client. |
| **[`presenter/`](./presenter/)** | Turns a strategic playbook into a recording-ready HTML slide deck, ending with concrete recommendations the client can run next quarter. Single self-contained HTML file, dark theme, keyboard navigation, chapter sidebar. | When you want to deliver the strategy to a client in a presentable format — Loom-style explainer, Zoom call, or live walkthrough. |

Designed for marketing/strategy work with **early-stage companies** (seed → Series A → pre-IPO) who want to learn from how mature growth-stage companies built their narrative arcs.

---

## Quick start

```bash
git clone https://github.com/nemock/press-release-archiver.git
cd press-release-archiver

# 1. Build an archive of any public company
cd archiver
python3 discover.py "Acme Medtech" --ticker ACME --out ../acme/manifest.json
python3 fetch.py ../acme/manifest.json --out ../acme/releases/ --tags medtech
python3 build_index.py --releases ../acme/releases/ --manifest ../acme/manifest.json \
    --out ../acme/INDEX.md

# 2. Run deterministic analysis
cd ../analyzer
python3 stats.py ../acme/ --ceo-names "Jane Smith" "John Doe"
python3 ladder.py ../acme/
python3 sample.py ../acme/

# 3. Open the project in Claude Code or Claude Desktop and ask Claude
#    to use the press-release-analyzer skill to synthesize the playbook.
#    (The synthesis is done by Claude reading the artifacts produced by
#    Stage 2 — no API key required, runs on your monthly Claude subscription.)
```

For comparative analysis (the "killer feature"):

```bash
# After running discover/fetch/build_index/stats/ladder for both companies:
python3 analyzer/compare.py acme/ globex/ \
    --anchor-a <yyyy-mm-dd> \
    --anchor-b <yyyy-mm-dd> \
    --out acme-vs-globex/
# Then ask Claude: "produce the comparative playbook for these two companies"
```

The `compare.py` script aligns companies by **company-relative time** (months since IPO/anchor) rather than calendar year — so a mature company's archive from a decade or two ago maps directly onto an early-stage company's recent post-IPO window because both cover roughly equivalent stages of public-company maturity.

To finish — turn the playbook into a recording-ready slide deck:

```bash
# Ask Claude: "make a presentation from the analysis at <path-to-playbook>.
# My client is a Series A medtech."
# (The presenter skill reads the playbook and writes presentation.html)
open <path>/presentation.html
```

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
