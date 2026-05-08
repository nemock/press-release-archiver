---
description: Generate a recording-ready HTML slide presentation from an analyzer playbook, ending with concrete recommendations for the client's PR strategy.
argument-hint: <Company Name> | <Company A> <Company B> | <playbook-path>  [--client-stage X] [--client-industry Y] [--out path] [--open]
---

Invoke the **press-release-presenter** skill workflow for the playbook in $ARGUMENTS.

## Argument parsing

Three accepted shapes (auto-detect):

- **One company name** → resolve to `./<slug>/analysis/playbook.md`
- **Two company names** → resolve to `./<slug-a>-vs-<slug-b>/comparative-playbook.md`
- **A path** (starts with `./`, `/`, `~/`, or contains `/` and ends in `.md`) → use as-is

Examples:
- `/pr-present Stryker --client-stage seriesA`
- `/pr-present Stryker "Boston Scientific" --client-industry medtech --open`
- `/pr-present ./acme/analysis/playbook.md --open`

For company names, slugify lowercased + hyphenated (`Boston Scientific` → `boston-scientific`, `Acme Medtech, Inc.` → `acme-medtech-inc`).

If the resolved path doesn't exist, also try the manifest-scan fallback: walk subdirectories of cwd looking for one whose `manifest.json` has a `company_name` matching the input. If found, use that directory's `analysis/playbook.md` (or for two names, find both matching directories and look for an `<a-slug>-vs-<b-slug>/` comparison directory).

If `$ARGUMENTS` is empty, ask the user which playbook to present and offer to scan common locations (`./*/analysis/playbook.md`, `./*-vs-*/comparative-playbook.md`).

**Default --out:** same directory as the playbook, named `presentation.html`.

**The `--open` flag** opens the file in the user's default browser via `open <path>` (macOS) or `xdg-open <path>` (Linux). Default: don't open.

## When the playbook doesn't exist

If you can resolve the archive directory(ies) but the corresponding playbook is missing:

1. Tell the user: the archive(s) exist but no playbook has been written yet.
2. Suggest the prerequisite:
   - For a single-company presentation: `/pr-analyze <Company>`
   - For a comparative presentation: `/pr-compare <Company A> <Company B>`
3. **Offer to run the prerequisite inline.** If user agrees, perform the analyze/compare workflow first, then continue into the presentation generation.

If the archive directory itself is missing, follow the `/pr-analyze` failure-mode pattern: list existing archives, suggest `/pr-archive`, offer to run it inline.

## Skill location

Locate the skill via `$PRESS_RELEASE_SKILL_DIR`, then `~/.claude/skills/press-release-archiver/`, then current directory. The template lives at `<skill>/presenter/template.html`.

## Workflow

1. **Read the source playbook.** Skip the playbook's TL;DR section — the deck IS the summary.

2. **Read the template:**
   ```bash
   cat <skill>/presenter/template.html
   ```

3. **Read the layout schemas:** `<skill>/presenter/SKILL.md` documents the available layouts and their fields. Use that as your reference.

4. **Plan the deck.** Map the playbook to slides:
   - Each major chapter of the playbook becomes a chapter in the sidebar (6–8 chapters total)
   - 18–25 slides total
   - Lean into NUMBERS as standalone `big-number` slides
   - Use `comparison` layout when the playbook surfaces an A vs B contrast (comparative playbooks especially)
   - Use `timeline` for the credibility ladder
   - Use `list` for the foundation plays (8 plays as a numbered list is the go-to)
   - Use `chart` for archetype/topic-mix distributions
   - Use `quote` for memorable insights
   - **End with a "Recommendations" chapter — 4–6 `recommendation`-layout slides plus one `closing` slide.**

5. **Tailor the recommendations.** If `--client-stage` or `--client-industry` flags were provided:
   - **seed**: Foundation plays (Investor Roster, Strategic Hire, Strategic Silence, HQ release, Award Capture)
   - **seriesA**: Campaign drumbeat (cluster discipline, T-14/T-7/T-0)
   - **seriesB**: Validator Sequence (introduce clinical/customer voice with proof points)
   - **preIPO**: Hospital-validation sequence + Crisis-Recovery Pair discipline
   - **medtech/biotech**: clinical/regulatory ladder language
   - **saas**: enterprise-customer / GA-launch / SOC-2 language (translate clinical concepts)

6. **Write the slide data.** Compose a Python script that:
   - Defines `slides` as a list of dicts (one per slide), each with `chapter`, `layout`, and layout-specific fields
   - Loads the template with `Path("<skill>/presenter/template.html").read_text()`
   - Substitutes `{{DECK_TITLE}}` with a generic-but-informative title (do NOT include specific company names; use stage descriptors like "Build-Stage PR Playbook")
   - Substitutes `{{SLIDES_JSON}}` with `json.dumps(slides, indent=2, ensure_ascii=False)`
   - Writes the output HTML file

   Run the script via `python3 << EOF ... EOF` heredoc.

7. **If `--open` flag was provided**, run `open <path>` (macOS) or detect platform.

8. **Report:**
   - Path to `presentation.html`
   - Number of slides + chapter list
   - The 4–6 recommendation slide titles (the takeaways the client walks away with)
   - Reminder of keyboard shortcuts: ← → navigate, F fullscreen, Home/End, click sidebar to jump

## Style guide

- **Skip the TL;DR.** Don't copy the playbook's opening summary — the deck is the summary.
- **One idea per slide.** If a slide has two ideas, split it.
- **Numbers > sentences.** Use `big-number` whenever you have a striking stat.
- **6–10 chapters max.** More overwhelms the sidebar.
- **20–30 slides total.** Less feels thin; more fatigues a recording.
- **Closing chapter must be "Recommendations"** with concrete, executable plays — not just summary.
- **Generic deck title.** No specific company names in `{{DECK_TITLE}}` (privacy and reusability).
