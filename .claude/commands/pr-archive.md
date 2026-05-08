---
description: Build a structured local archive of every press release a public company has ever issued (SEC EDGAR + Wayback Machine + optional Chrome Connector).
argument-hint: "<Company Name>" [TICKER] [--out path] [--tags preset] [--no-wire-search]
---

Invoke the **press-release-archiver** skill workflow for the company specified in $ARGUMENTS.

## Argument parsing

Expected: `"<Company Name>"` `[TICKER]` `[flags]`. Examples:
- `/pr-archive "Stryker" SYK`
- `/pr-archive "Boston Scientific" BSX --tags medtech --out ~/research/bsx/`
- `/pr-archive "Salesforce" CRM --tags saas --no-wire-search`

If `$ARGUMENTS` is empty or unclear, ask the user for company name and ticker.

**Defaults:** `--tags medtech`, `--out ./<company-slug>/`, wire-search enabled.

## Skill location

Locate the skill scripts. Try in order, use the first that exists:
1. `$PRESS_RELEASE_SKILL_DIR` environment variable
2. `~/.claude/skills/press-release-archiver/`
3. The current working directory if `archiver/discover.py` exists there

If none exist, tell the user to install the skill (clone the repo to `~/.claude/skills/press-release-archiver/`).

## Workflow

1. **EDGAR discovery:**
   ```bash
   python3 <skill>/archiver/discover.py "<COMPANY>" --ticker <TICKER> --out <OUT>/manifest.json
   ```
   Show the user the EDGAR release count + per-year breakdown. If <10 releases were found, flag this — the company may be too small, too new, or non-US-listed.

2. **Wire search** (skip if `--no-wire-search`):
   ```bash
   python3 <skill>/archiver/discover.py "<COMPANY>" --ticker <TICKER> --emit-queries
   ```
   Take the emitted search queries. Run each via your `WebSearch` tool. Parse results into JSON of shape `[{date, headline, url, wire}]` — one entry per real wire press release found. Skip aggregator URLs (Yahoo Finance, BioSpace, Manila Times, etc.) — prefer the original wire (businesswire.com / globenewswire.com / prnewswire.com). Date often appears in the URL slug; extract from there when possible.

   Then merge:
   ```bash
   python3 <skill>/archiver/discover.py --manifest-merge wire_results.json --out <OUT>/manifest.json
   ```

3. **Fetch all releases:**
   ```bash
   python3 <skill>/archiver/fetch.py <OUT>/manifest.json --out <OUT>/releases/ --tags <TAGS>
   ```
   This runs Tier 1 (EDGAR) + Tier 2 (Wayback). Takes 1–5 minutes for typical archives. If `pending_chrome.json` is non-empty after, surface to the user — those are releases that need Tier 3 Chrome Connector assist.

4. **Build index:**
   ```bash
   python3 <skill>/archiver/build_index.py --releases <OUT>/releases/ --manifest <OUT>/manifest.json --out <OUT>/INDEX.md
   ```

5. **Report.** Tell the user:
   - Path to the archive directory
   - Total releases captured
   - Year coverage (first → last date)
   - Source breakdown (EDGAR / Wayback / pending Chrome)
   - 2–3 most surprising findings if you noticed any (long silences, distress clusters, leadership volatility)
   - Any caveats (e.g., Intuitive-style mature companies whose archive starts post-IPO)

## Failure modes to surface

- Company not found in SEC EDGAR → suggest they're not US-listed; archive will be wire-only
- EDGAR returned but very sparse → recent IPO; archive may not need full pipeline
- Wayback rate-limited (HTTP 429) → suggest re-run with longer `--wayback-delay`
- Many wire URLs failed → suggest manually adding to wire_results.json before re-merge
