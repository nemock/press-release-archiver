---
description: Incrementally refresh an existing press release archive with releases issued since the last run.
argument-hint: <Company Name> [--tags preset] [--no-wire-search]
---

Refresh an existing press release archive with new releases issued since the last run. Uses the archiver's `--update` mode which only enumerates entries newer than the most recent file already on disk.

## Argument parsing

Expected: `<Company Name>` `[flags]`. Examples:
- `/pr-update Stryker`
- `/pr-update "Boston Scientific" --no-wire-search`

The first argument is a **company name**. Resolve it to an archive directory in the current working directory using this sequence:

1. **If it's clearly a path** (starts with `./`, `/`, `~/`, or contains `/`) — treat as an explicit path.

2. **Slugify the name** (lowercase, replace spaces with hyphens, strip non-alphanumeric except hyphens):
   - `Stryker` → `stryker`
   - `Boston Scientific` → `boston-scientific`

3. **Try the slugified path:** `./<slug>/` if it exists with `releases/` + `manifest.json`.

4. **Fallback — scan for matching `company_name` in manifests:** look at every subdirectory of cwd containing `manifest.json`. Match `company_name` (case-insensitive) against the input. Use the first match.

If `$ARGUMENTS` is empty, ask the user which archive to update.

## When the archive doesn't exist

If resolution fails:

1. Tell the user the archive for `<Company>` doesn't exist in the current directory.
2. **List existing archives** in the cwd (subdirs with `releases/` + `manifest.json`).
3. Suggest: this is the wrong command — they probably want `/pr-archive "<Company>" [TICKER]` to **build** the archive for the first time. `/pr-update` is for refreshing an existing one.
4. Offer to run `/pr-archive` for them now, with a brief explanation of the difference: archive builds the full corpus from scratch; update only fetches releases issued since the existing archive's most recent date.

## Skill location

Locate scripts via `$PRESS_RELEASE_SKILL_DIR`, then `~/.claude/skills/press-release-archiver/`, then current directory.

## Workflow

1. **Read company info from existing manifest:**
   ```bash
   cat <archive>/manifest.json
   ```
   Extract `company_name` and `ticker` from the existing manifest. These are needed for the discovery query.

2. **Incremental discovery:**
   ```bash
   python3 <skill>/archiver/discover.py "<COMPANY>" --ticker <TICKER> \
       --update <archive>/releases/ \
       --out <archive>/delta_manifest.json
   ```
   The `--update` flag finds the most recent date in the existing releases directory and only enumerates entries dated after it.

   **If 0 new entries are found, tell the user the archive is already up-to-date and exit gracefully.** Show the most recent release on disk for context.

3. **Wire search for the delta** (skip if `--no-wire-search`):
   Same pattern as `/pr-archive`, but only for the delta period:
   ```bash
   python3 <skill>/archiver/discover.py "<COMPANY>" --ticker <TICKER> \
       --update <archive>/releases/ --emit-queries
   ```
   Run any new queries via `WebSearch`. Most updates will be for the trailing 1–2 quarters, so this is much smaller than the initial archive's wire-search step.

   Merge any results:
   ```bash
   python3 <skill>/archiver/discover.py --manifest-merge wire_results.json \
       --out <archive>/delta_manifest.json
   ```

4. **Fetch new releases:**
   ```bash
   python3 <skill>/archiver/fetch.py <archive>/delta_manifest.json \
       --out <archive>/releases/ --tags <TAGS>
   ```
   File-exists skip is automatic — the archiver won't re-fetch entries already on disk.

5. **Rebuild the master manifest** by merging delta into it:
   ```bash
   python3 -c "
   import json
   m = json.load(open('<archive>/manifest.json'))
   d = json.load(open('<archive>/delta_manifest.json'))
   existing_keys = {(e['date'], e.get('edgar_accession')) for e in m['entries']}
   m['entries'].extend(e for e in d['entries']
                       if (e['date'], e.get('edgar_accession')) not in existing_keys)
   m['entries'].sort(key=lambda x: x['date'])
   json.dump(m, open('<archive>/manifest.json', 'w'), indent=2)
   "
   ```

6. **Rebuild INDEX.md:**
   ```bash
   python3 <skill>/archiver/build_index.py --releases <archive>/releases/ \
       --manifest <archive>/manifest.json --out <archive>/INDEX.md
   ```

7. **Report:** how many new releases were captured, the date range of the delta, and whether any pending Chrome assist is needed.

## Suggest re-running analysis

If new releases were added, suggest re-running `/pr-analyze <Company>` to refresh the strategic analysis with the new data. Note: this overwrites the previous analysis files.
