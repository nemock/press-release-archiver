# press-release-analyzer

> Reverse-engineer the PR strategy of a public company from a structured press-release archive. Sibling skill to [`press-release-archiver`](../archiver/).

Input: a press-release corpus produced by `press-release-archiver` (a `releases/` directory of frontmatter-tagged markdown files plus a `manifest.json`).

Output: a strategic playbook that distills the company's communication strategy into emulatable plays — designed for early-stage companies (seed → Series A → pre-IPO) who want to learn from the PR programs of mature, well-funded competitors and adjacent-market peers.

```
your-archive/
└── analysis/                       # NEW (produced by this skill)
    ├── stats.json                  # deterministic stats
    ├── patterns.md                 # cadence, topic mix, headline patterns
    ├── ladder.json                 # candidate credibility-ladder rungs
    ├── ladder.md                   # rungs with archetype classification
    ├── sample.md                   # ~30-80 strategically-sampled releases
    ├── credibility-ladder.md       # SYNTHESIZED: curated proof-point sequence
    ├── drumbeat-map.md             # SYNTHESIZED: cadence-pattern analysis
    ├── validator-sequence.md       # SYNTHESIZED: stakeholder orchestration
    ├── foundation-plays.md         # SYNTHESIZED: Years 1-3 emulatable plays
    └── playbook.md                 # SYNTHESIZED: combined master document
```

For comparative analysis (`compare.py`), an additional `<a>-vs-<b>/` directory holds:
- `comparison.json` + `comparison.md` (deterministic stage-aligned stats)
- `comparative-playbook.md` (synthesized cross-company analysis)

---

## Why this exists

The product of a press-release archive is a corpus of decisions — each release is the result of someone (probably an expensive PR firm) making strategic calls about timing, framing, and stakeholder voice. Mature growth-stage and post-IPO companies have spent millions of dollars learning what to say when. That knowledge is encoded in the archive. This skill extracts it.

For an early-stage founder or growth marketer who wants to build a comparable PR program from scratch — but doesn't have a $30K/month PR retainer — this skill produces an actionable playbook by reverse-engineering what a peer that DID have that retainer learned.

## Architecture

Three deterministic Python scripts produce structured inputs that fit comfortably into one Claude conversation context:

| Script | Output | Tokens |
|---|---|---|
| `stats.py` | `stats.json` + `patterns.md` | ~3-5K |
| `ladder.py` | `ladder.json` + `ladder.md` | ~3-5K |
| `sample.py` | `sample.md` (smart-sampled releases) | ~12-20K |
| `compare.py` | `comparison.json` + `comparison.md` | ~5-10K |

Then **Claude (in this conversation, on your monthly subscription)** reads those artifacts and writes the strategic synthesis directly. No external API calls. No per-release token burn. The full Acme Medtech analysis fits in ~25K context tokens; a Acme Medtech-vs-Globex Corp comparison in ~50K.

Why keep the synthesis in-conversation rather than scripted? Because the strategic-pattern recognition is what an LLM does well; the deterministic stats are what Python does well. The split is intentional.

---

## Usage (single-company)

```bash
# Stage 1: deterministic pipeline
python3 stats.py acme-medtech/ --ceo-names "Jane Smith" "John Doe"
python3 ladder.py acme-medtech/
python3 sample.py acme-medtech/

# Stage 2: invoke Claude with the SKILL.md workflow
# (in Claude Code or Claude Desktop, ask: "analyze the Acme Medtech archive
#  using the press-release-analyzer skill")
```

Claude reads the artifacts and writes the five output files (`credibility-ladder.md`, `drumbeat-map.md`, `validator-sequence.md`, `foundation-plays.md`, `playbook.md`) directly into `acme-medtech/analysis/`.

## Usage (comparative — the "killer feature")

The comparative mode aligns two companies by **company-relative time** (months since IPO/anchor), not calendar year. A mature company's early-public-years window — taken from a decade or two ago — becomes directly comparable to an early-stage company's recent post-IPO window because both cover roughly equivalent stages of public-company maturity.

```bash
# Run stats + ladder on both
python3 stats.py acme-medtech/ --ceo-names "Jane Smith"
python3 stats.py globex-corp/ --ceo-names "Pat Lee" "Sam Park"
python3 ladder.py acme-medtech/
python3 ladder.py globex-corp/

# Stage-aligned comparison
python3 compare.py acme-medtech/ globex-corp/ \
    --anchor-a <yyyy-mm-dd> \
    --anchor-b <yyyy-mm-dd> \
    --out acme-vs-globex/

# Then invoke Claude with: "compare these two archives"
# Claude writes comparative-playbook.md
```

Anchor selection is the meaningful choice. Pick the date each company became a public storytelling entity — typically the IPO date, SPAC merger close, or first archived release. Pick anchors that align by company *stage*, not calendar year. That's where the strategic insight lives: what was each company doing at *equivalent maturity*, regardless of which calendar year that maturity fell in.

---

## What you actually get out

A playbook that answers questions like:

- **Credibility ladder** — what proof-point sequence built market confidence? How did they pace it? A typical build-stage medtech company shows a multi-year, multi-rung ladder where each rung represents the next-most-believable claim (e.g., capital event → product demo → clinical validation → regulatory milestone). The ladder structure itself is a copyable template.
- **Drumbeat patterns** — when did they cluster releases (campaigns) and when did they go quiet? Build-stage companies typically cluster 3–4× their normal rate around inflection moments; mature companies often run a steady cadence with few or zero clusters. Two completely different strategies for two different stages.
- **Validator sequence** — when did internal voices give way to clinical → institutional voices? Well-orchestrated programs introduce third-party voices only *after* there's something material for them to validate — a "credibility on demand" approach.
- **Foundation plays** — what did they release in Years 1-3? The playbook surfaces the 5-8 dominant play types — typically: headquarters opening, key hire, advisory board reveal, first customer, conference debut, award capture, demonstration day, regulatory milestone announcement.
- **Comparative deltas** — what did Mature Co. do at Stage X that Early Co. didn't, and vice versa? This is where most of the actionable strategy lives.

---

## Limitations & caveats

- **Tag inference noise.** The archiver's tag inference is keyword-based and over-broad. The analyzer mostly filters this out, but expect some classification fuzziness. Claude curates in the synthesis pass.
- **CEO quote detection misses ~20-30% of quotes.** The regex pattern doesn't catch every attribution variant ("according to," "X commented," etc.). The CEO quote rate is therefore a *floor estimate*. Pass `--ceo-names` to improve detection.
- **Mature-company corpora are dominated by routine reporting.** Globex Corp's archive is ~80% quarterly earnings reports — those get filtered from the credibility-ladder rungs but still affect cadence stats. Lean into the rare non-earnings events.
- **Anchor selection matters.** Comparative analysis is only as meaningful as the anchor dates. If two companies' anchors don't represent equivalent stages, the comparison is misleading. The skill surfaces this caveat in the output.
- **Pre-IPO archives are sparse.** Companies under-communicate before going public; the Foundation-phase analysis is therefore best for the immediate post-IPO years.
- **No semantic ML/embeddings yet.** Pattern detection is deterministic + LLM-curation. A Pass 4 with per-release LLM enrichment (richer than keyword tags) would unlock additional analyses (tone, narrative-arc-position) but would burn tokens. Not implemented in this version.

---

## License

MIT. See [../LICENSE](../LICENSE).
