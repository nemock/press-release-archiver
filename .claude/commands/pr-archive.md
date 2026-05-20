---
description: Build a structured local archive of every press release a company has ever issued — public (SEC EDGAR + Wayback) or private (newsroom + wires).
argument-hint: "<Company Name>" [TICKER | URL] [--out path] [--tags preset] [--no-wire-search]
---

Invoke the **press-release-archiver** skill workflow for the company specified in $ARGUMENTS.

## Argument parsing

Expected: `"<Company Name>"` `[TICKER | URL]` `[flags]`. The second argument is auto-detected — a bare 1-5 uppercase token (optional `.X` share class) is a ticker; anything with a scheme or domain shape is a URL. Examples:
- `/pr-archive "Stryker" SYK` (public, by ticker)
- `/pr-archive "Vicarious Surgical" https://vicarioussurgical.com` (auto-detected URL)
- `/pr-archive "Acme Robotics" acme.example` (bare domain — also auto-detected)
- `/pr-archive "Boston Scientific" BSX --tags medtech --out ~/research/bsx/`

If `$ARGUMENTS` is empty or unclear, ask the user for company name and either a ticker (public) or a URL (private / pre-IPO).

Even when a URL is provided, the discover step still probes SEC EDGAR by name — if a confident match comes back, the company is treated as public and the EDGAR pipeline runs. Otherwise it falls into private-company mode (wires + newsroom only).

**Defaults:** `--tags medtech`, `--out ./<company-slug>/`, wire-search enabled.

## Skill location

Locate the skill scripts. Try in order, use the first that exists:
1. `$PRESS_RELEASE_SKILL_DIR` environment variable
2. `~/.claude/skills/press-release-archiver/`
3. The current working directory if `archiver/discover.py` exists there

If none exist, tell the user to install the skill (clone the repo to `~/.claude/skills/press-release-archiver/`).

## Workflow

1. **EDGAR discovery (always attempted):**
   ```bash
   # Pass the disambiguator as-is — discover.py auto-detects ticker vs URL.
   python3 <skill>/archiver/discover.py "<COMPANY>" <TICKER_OR_URL> --out <OUT>/manifest.json
   ```
   Inspect `manifest.json` — the `is_public` flag tells you whether EDGAR resolved a CIK.
   - **Public path** (EDGAR resolved): show the user the EDGAR release count + per-year breakdown. If <10 releases were found, flag this — the company may be too small, too new, or non-US-listed.
   - **Private path** (no CIK): tell the user the archive will be wires + newsroom only. Coverage will likely be sparser and there will be no canonical SEC accession trail.

2. **Wire + newsroom search** (skip if `--no-wire-search`):
   ```bash
   python3 <skill>/archiver/discover.py "<COMPANY>" <TICKER_OR_URL> --emit-queries
   ```
   Take the emitted search queries. Run each via your `WebSearch` tool. Parse results into JSON of shape `[{date, headline, url, wire}]` — one entry per real wire / newsroom press release found. Skip aggregator URLs (Yahoo Finance, BioSpace, Manila Times, etc.) — prefer the original wire (businesswire.com / globenewswire.com / prnewswire.com) or the company's own newsroom domain. Date often appears in the URL slug; extract from there when possible. For private companies the newsroom queries (`site:<domain>`) are usually the highest-yield source.

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

- Company not found in SEC EDGAR → automatically falls back to private-company mode if a URL was provided; if only a name was given, ask the user for either a ticker or a URL
- EDGAR returned but very sparse → recent IPO; archive may not need full pipeline
- Fuzzy EDGAR match auto-rejected (no ticker to confirm) → tell the user; if they want to treat it as public, re-run with `--ticker <SYM>` explicitly
- Wayback rate-limited (HTTP 429) → suggest re-run with longer `--wayback-delay`
- Many wire URLs failed → suggest manually adding to wire_results.json before re-merge
