---
name: press-release-archiver
description: Compile every press release ever issued by a public company into a structured local markdown archive (per-release files + a top-level INDEX.md). Use when the user wants to "archive press releases for [Company]", "study [Company]'s PR strategy", "build a corpus of [Company]'s announcements", or wants offline-resilient access to a competitor's wire history. Works best on US-listed companies (SEC EDGAR is the most reliable source); pre-IPO archives are sparser. Requires curl + python3. Optional Chrome Connector (Claude Desktop) for releases that aren't in EDGAR or Wayback Machine.
---

# Press Release Archiver

Three Python scripts in this directory: `discover.py`, `fetch.py`, `build_index.py`. They form a pipeline. Tag taxonomies live in `tag_presets.json`.

## When invoked

Ask the user for, or infer:

1. **Company name** (required) — e.g. `"Acme Medtech"`
2. **Stock ticker** (optional but strongly recommended) — improves CIK precision
3. **Industry** for tag preset (default `generic`; alternatives: `medtech`, `biotech`, `saas`)
4. **Output directory** (default `./<company-slug>/`)
5. **Mode** — full archive (default) or `--update` for an incremental refresh of an existing archive

Confirm the plan with the user before running discovery on companies with very common names.

---

## Stage 1A — EDGAR enumeration

```bash
python3 discover.py "<company>" --ticker <TICKER> --out <dir>/manifest.json
```

This auto-populates the manifest with every press release the company filed as an 8-K EX-99.1 exhibit. Show the user the count + year breakdown before proceeding.

## Stage 1B — Wire enumeration (you run the searches)

The script can't search Business Wire / GlobeNewswire / PR Newswire on its own — it would get blocked. Instead, **you (Claude) run the searches** and merge the results.

```bash
python3 discover.py "<company>" --ticker <TICKER> --out <dir>/manifest.json --emit-queries
```

This prints a list of search queries — one per (wire × year). Run each via your `WebSearch` tool (Claude Code) or `mcp__plugin_marketing_*` search tools (Claude Desktop), parse the results into this JSON shape:

```json
[
  {"date": "2024-08-07", "headline": "...", "url": "https://www.businesswire.com/news/...", "wire": "businesswire"},
  ...
]
```

Then merge:

```bash
python3 discover.py --manifest-merge wire_results.json --out <dir>/manifest.json
# or pipe via stdin:
echo '[{...}]' | python3 discover.py --manifest-merge - --out <dir>/manifest.json
```

**Heuristics for parsing search results:**
- Extract date from the URL when possible (Business Wire URLs encode date as `YYYYMMDD` early in the path)
- Skip aggregator/syndicate URLs (Yahoo Finance, BioSpace, etc.) — prefer the original wire
- If a search hit's date is within ±1 day of an existing EDGAR row, it gets merged into that row (adds the wire URL); otherwise it becomes a new wire-only entry

After merge, show the user the updated count.

---

## Stage 2 — Tiered fetch

```bash
python3 fetch.py <dir>/manifest.json --out <dir>/releases/ --tags <preset>
```

Per-entry tier order:
1. **EDGAR EX-99.1** if accession exists (no rate-limit, no JS)
2. **Wayback Machine** snapshot of the wire URL (4-second delay between requests)
3. **Pending Chrome assist** — emitted to `<dir>/pending_chrome.json`

**File-exists skip:** entries already on disk are skipped. Use `--force` to re-fetch.

### Stage 2B — Chrome Connector assist (Claude Desktop only)

If `pending_chrome.json` is non-empty AND you have `mcp__Claude_in_Chrome__*` tools available, work through it:

For each pending entry:
1. `mcp__Claude_in_Chrome__navigate` to the wire URL
2. `mcp__Claude_in_Chrome__get_page_text` to capture rendered text
3. Pipe the result through `fetch.py --inject`:
   ```bash
   python3 fetch.py --inject <slug> --manifest <dir>/manifest.json --out <dir>/releases/ --tags <preset> <<< "$html"
   ```

If Chrome Connector isn't available, surface the pending list to the user — the archive is incomplete but functional.

---

## Stage 3 — Index

```bash
python3 build_index.py --releases <dir>/releases/ --manifest <dir>/manifest.json --out <dir>/INDEX.md
```

Produces a navigable `INDEX.md`: chronological listing, per-year stats, per-tag groupings.

---

## Incremental update (later runs)

When the user wants to refresh an existing archive without re-fetching everything:

```bash
# Find only releases newer than what's on disk
python3 discover.py "<company>" --ticker <TICKER> --update <dir>/releases/ --out <dir>/delta_manifest.json

# Wire merge for the delta (same workflow as Stage 1B above)
python3 discover.py --manifest-merge new_wire_results.json --out <dir>/delta_manifest.json

# Fetch only the new ones
python3 fetch.py <dir>/delta_manifest.json --out <dir>/releases/ --tags <preset>

# Rebuild the index
python3 build_index.py --releases <dir>/releases/ --manifest <dir>/manifest.json --out <dir>/INDEX.md
```

The `--update` flag finds the most recent date in the existing releases dir and only enumerates entries dated after it.

---

## Reporting back to the user

After all stages, tell them:
- Total releases captured / total enumerated
- Year coverage (first → last)
- Source breakdown (EDGAR / Wayback / Chrome / skipped-already-on-disk)
- Any pending entries that need attention
- Path to `INDEX.md`

## Failure modes worth surfacing

- **EDGAR 8-K with no EX-99.1 exhibit** — usually a regulatory filing (item 5.02 governance, 5.03 bylaws) without a press release. Skip silently.
- **Wayback returns no snapshot** — page either was never archived or was archived after a paywall. Falls through to Tier 3.
- **Wire mismatch post-listing-change** — companies sometimes switch wires (Business Wire → GlobeNewswire after delisting). The wire-search step in Stage 1B should catch this; if it misses, manually add the URL to wire_results.json.
- **Pre-IPO releases** — most pre-IPO companies don't issue formal wire releases. Don't promise comprehensive pre-IPO coverage; default `--pre-ipo skip` reflects this.
- **Tag preset not matched to industry** — if the user is studying a SaaS company with the `medtech` preset, tags will be sparse. Always confirm the preset choice (or pick `generic`).
