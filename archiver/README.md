# press-release-archiver

> Compile every press release a public company has ever issued into a structured, offline-resilient local markdown archive — one file per release plus a navigable `INDEX.md`. Built as a Claude Code / Claude Desktop skill, but the scripts also stand alone.

```
your-company-archive/
├── INDEX.md                            # navigable master index
├── manifest.json                       # discovered release metadata
└── releases/
    ├── 2018-04-05-series-a-funding.md
    ├── 2020-06-12-major-corporate-action.md
    ├── 2024-08-07-hospital-partnership.md
    └── ...                             # ~60+ files for an established public company
```

Each release file has YAML frontmatter (date, headline, source URL, EDGAR accession, tags) followed by the headline as H1, a 2–3 sentence summary, and the full verbatim body — paragraph breaks preserved, contact info kept, wire chrome stripped.

---

## Why this exists

PR strategy work — competitive intelligence, messaging benchmarks, narrative pattern-mining — needs a clean local corpus to actually be analyzable. The web doesn't give you one:

- **SEC EDGAR** has every material press release as an 8-K EX-99.1 exhibit, but the HTML is wrapped in regulatory chrome and the search UI assumes you know exactly what you want.
- **Business Wire / GlobeNewswire / PR Newswire** carry the published canonical version, but **Business Wire blocks all automated access** (Cloudflare-style JS challenge — even browser-User-Agent `curl` gets a flat 403). They also occasionally retire URLs.
- **Company IR pages** are usually JS-rendered and depend on a CDN that can disappear or get redesigned.
- **News aggregators** (BioSpace, Yahoo Finance, etc.) carry syndicate copies but break the canonical-link expectation.

Existing tools either scrape one source poorly or require expensive press-release database subscriptions. This skill crosses the three free, durable sources and writes the result to disk so it survives company website redesigns, paywalls, and link rot.

## How it works — three-tier architecture

For each candidate release, the fetcher tries sources in order:

| Tier | Source | When it works | Notes |
|---|---|---|---|
| 1 | **SEC EDGAR EX-99.1 exhibit** | Material releases since IPO | Authoritative; no rate-limit; works in any environment with `curl` |
| 2 | **Wayback Machine** snapshot of wire URL | Anything ever indexed by IA (most things) | 4-second polite delay between requests; very reliable for 2015+ |
| 3 | **Live wire URL via Chrome Connector** | Newest releases not yet in Wayback, or non-material releases the company never filed as 8-K | Requires Claude Desktop with `mcp__Claude_in_Chrome__*` tools available |

Discovery similarly combines authoritative sources:
- **EDGAR full-text search** (efts.sec.gov) for every 8-K with an EX-99.1 exhibit on a given CIK
- **Web search** (you, Claude, run the queries — script can't, since wires would block it) for non-material releases that aren't filed with the SEC

Architectural separation is intentional: **Python scripts handle deterministic work** (HTTP, parsing, cleaning, writing); **the LLM handles judgment** (does this company exist, did discovery miss anything, do these search results actually correspond to my company).

---

## Installation

### As a Claude skill

Copy this directory into your skills root:

```bash
# Claude Desktop
cp -r press-release-archiver ~/Library/Application\ Support/Claude/skills/

# Claude Code
cp -r press-release-archiver ~/.claude/skills/
```

Then ask Claude something like *"archive every press release from Stryker into a local markdown corpus"* and it'll discover the skill via `SKILL.md`.

### As standalone scripts

Just clone the repo and run the three Python scripts manually — they only need `python3` (3.8+) and `curl`. No third-party dependencies.

```bash
git clone https://github.com/nemock/press-release-archiver.git
cd press-release-archiver/archiver
python3 discover.py "Acme Medtech" --ticker ACME --out manifest.json
python3 fetch.py manifest.json --out releases/ --tags medtech
python3 build_index.py --releases releases/ --manifest manifest.json --out INDEX.md
```

---

## Usage

### Stage 1A — EDGAR enumeration

```bash
python3 discover.py "Acme Medtech" --ticker ACME --out acme/manifest.json
```

Walks SEC EDGAR's full-text search, finds every 8-K with an EX-99.1 press release exhibit for that CIK. Ticker is optional but strongly recommended (avoids ambiguity for common company names). For Acme Medtech: ~43 releases auto-discovered in under 5 seconds.

### Stage 1B — Wire enumeration (you do the searches)

The script can't search the wires itself — they block automated access. Instead, it emits the queries for you (or for Claude) to run:

```bash
python3 discover.py "Acme Medtech" --ticker ACME --emit-queries
# Outputs:
#   site:businesswire.com "Acme Medtech" 2020
#   site:businesswire.com "Acme Medtech" 2021
#   ...etc, 21 queries (3 wires × 7 years)
```

Run them with whatever search transport you have (Google search box, `WebSearch` tool in Claude Code, MCP search in Claude Desktop, SerpAPI), normalize results into this JSON shape:

```json
[
  {"date": "2024-08-07",
   "headline": "Acme Medtech Announces New Hospital System Partnership with Regional Hospital A",
   "url": "https://www.businesswire.com/news/home/20240807415785/en/...",
   "wire": "businesswire"},
  {"date": "2026-04-30",
   "headline": "Acme Medtech Reports First Quarter 2026 Financial Results",
   "url": "https://www.globenewswire.com/news-release/2026/04/30/...",
   "wire": "globenewswire"}
]
```

Then merge:

```bash
python3 discover.py --manifest-merge wire_results.json --out acme/manifest.json
# or pipe via stdin
python3 discover.py --manifest-merge - --out acme/manifest.json < wire_results.json
```

The merger glues a wire URL onto an existing EDGAR row when their dates match within ±1 day; otherwise it's added as a wire-only entry.

### Stage 2 — Tiered fetch

```bash
python3 fetch.py acme/manifest.json --out acme/releases/ --tags medtech
```

Per-entry: tries EDGAR (Tier 1), then Wayback Machine (Tier 2). Files already on disk are skipped (use `--force` to re-fetch). Anything tier 1 + 2 can't capture is emitted to `pending_chrome.json` for the optional Chrome assist phase.

Flags:
- `--out <dir>` — output directory (auto-created)
- `--tags <preset|path>` — tag taxonomy. Built-in presets: `generic`, `medtech`, `biotech`, `saas`. Or provide your own JSON file
- `--force` — re-fetch entries that already have a file on disk
- `--wayback-delay <seconds>` — politeness delay between Wayback requests (default 4s; lower at your own risk of 429s)

### Stage 2B — Chrome Connector assist (Claude Desktop only)

If `pending_chrome.json` exists and you have `mcp__Claude_in_Chrome__*` tools:

For each pending entry, navigate, capture text, pipe back through `--inject` mode:

```bash
python3 fetch.py --inject <slug> --manifest manifest.json --out releases/ <<< "$html"
```

Same parsers / cleaners / tag inference apply uniformly regardless of where the HTML came from.

### Stage 3 — Index

```bash
python3 build_index.py --releases acme/releases/ --manifest acme/manifest.json --out acme/INDEX.md
```

Generates the navigable index: company header, year stats, topic counts, full chronological listing with summaries, plus a topic-grouped second view.

### Incremental update (for re-runs)

```bash
# Discover only what's new since the existing archive's max date
python3 discover.py "Acme Medtech" --ticker ACME \
    --update acme/releases/ --out acme/delta.json

# (Optional) merge new wire results
python3 discover.py --manifest-merge new_wire_results.json --out acme/delta.json

# Fetch the delta — file-exists skip prevents redundant work
python3 fetch.py acme/delta.json --out acme/releases/ --tags medtech

# Rebuild the index
python3 build_index.py --releases acme/releases/ --manifest acme/manifest.json --out acme/INDEX.md
```

---

## Tag presets

The fetcher heuristically tags releases by case-insensitive substring match against the headline + first 2 KB of body. Tags drive the "topic index" section of `INDEX.md` and frontmatter for downstream filtering.

Built-in presets in [tag_presets.json](tag_presets.json):

| Preset | Tuned for | Distinct tags |
|---|---|---|
| `generic` | Any industry — broad keyword sets | 14 |
| `medtech` | Surgical robotics, devices, diagnostics | 12 |
| `biotech` | Drug development, clinical trials | 11 |
| `saas` | B2B software, ARR-driven companies | 13 |

To add a custom preset, drop a new top-level block into `tag_presets.json` (or pass `--tags /path/to/your.json` to fetch.py with shape `{"tag-id": ["keyword", ...]}`). New tag IDs render in `INDEX.md` once you also add their human label to the `_labels` block.

---

## What an output archive looks like

For a mature public company with 5–25 years of history, a typical run produces roughly 50–150 press releases captured (mostly EDGAR EX-99.1 with a sprinkle of Business Wire / PR Newswire / GlobeNewswire releases via Wayback Machine), totaling a few megabytes of structured markdown. The topic index surfaces communication patterns at a glance: how many financial-results releases vs. partnership announcements vs. awards.

Each release file follows a consistent template:

```markdown
---
date: YYYY-MM-DD
headline: <Exact published headline>
source_url: <wire URL>
edgar_accession: <8-K accession or null>
tags: [<inferred topic tags>]
---

# <Exact published headline>

**Date:** <full date>
**Source:** [<wire name>](<url>)
**EDGAR 8-K:** <accession or —>

## Summary

<2–3 sentence TL;DR drawn from the lead paragraph>

## Full Press Release

<full verbatim body — paragraph breaks preserved, contact info kept,
 wire chrome stripped>
```

---

## Limitations & gotchas

- **US-listed companies only** for EDGAR coverage. Foreign issuers without ADR listings won't have CIKs and will fall through to wire-only enumeration.
- **Pre-IPO archives are sparse.** Most pre-IPO companies don't issue formal wire releases — early funding announcements live in VC databases (Crunchbase, Tracxn) instead. Default `--pre-ipo skip` reflects this.
- **Tag inference is heuristic.** Tags fire on keyword matches, not semantic understanding. A press release about "Q1 2024 conference presentation announcing partnership" might fire `financial-results`, `conference`, `partnership` even if it's primarily one of those. Treat tags as a starting filter, not ground truth.
- **EDGAR rate limits.** SEC requires a User-Agent identifying your project; the script provides one. SEC also limits unauthenticated requests to ~10/sec — a 0.2-second sleep between calls keeps us well under.
- **Wayback Machine rate limits.** Aggressive runs trigger 429s. Default 4-second delay is a sweet spot; reducing it below 2 seconds will fail.
- **Business Wire is hard-blocked.** Cloudflare's JS challenge defeats both `curl` and Python's urllib. Wayback is the workaround for archived pages; live wire fetch requires Chrome Connector.
- **Wire mismatch post-listing-change.** Companies sometimes switch wires (e.g., Business Wire → GlobeNewswire after a delisting). The wire-search step in Stage 1B catches this; manual additions handle the residual.
- **Investor presentations are intentionally skipped.** Slide decks attached to 8-Ks (description contains "PRESENTATION") are not press releases. The discovery filter excludes them.

---

## Architectural notes for extending

- **Adding a new wire source.** The fetcher's tier 2 (Wayback) is wire-agnostic — it just feeds `<original-url>` into a Wayback request and uses the same HTML cleaner. To support a new wire, the discovery step needs a corresponding `site:` query and the parser/cleaner may need a new dateline regex (`DATELINE_RE` in `fetch.py`).
- **Adding a new source tier.** The `process()` function in `fetch.py` is where the tier ladder lives. New tiers slot in between existing ones. Each tier returns `(source_url, body_html)` or `(None, None)` and the orchestrator falls through.
- **Per-release LLM enrichment.** The summary generator is currently a deterministic "first sentence after dateline" extractor. Swapping it for an LLM call (Claude API / Anthropic SDK) would give cleaner TL;DRs at the cost of API tokens. Hook point: `generate_summary()` in `fetch.py`.
- **Multi-company analysis.** `build_index.py` is single-company. For comparative analysis (e.g., "show me partnership announcement frequency for Acme Medtech vs Globex Corp vs Stryker"), a meta-index script would aggregate per-company `manifest.json` files into a cross-company time series. Not implemented yet — straightforward to add.

---

## License

MIT. See [LICENSE](LICENSE).
