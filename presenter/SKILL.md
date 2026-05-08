---
name: press-release-presenter
description: Turn a strategic PR-analysis playbook (the output of press-release-analyzer) into a recording-optimized HTML slide presentation, ending with concrete recommendations for the client's own PR strategy. Single self-contained HTML file with keyboard navigation, dark theme, big numbers, comparison layouts, timelines, and chapter sidebar. The closing chapter is always client-facing recommendations the user can hand to a seed → Series A → pre-IPO company. Sibling skill to press-release-archiver and press-release-analyzer.
---

# Press Release Presenter

Reads a `playbook.md` (single-company analysis) or `comparative-playbook.md` (two-company analysis) and produces a single self-contained HTML deck the user can open in a browser, present from full-screen, and screen-record. The deck has minimal text per slide, big visual numbers, and ends with 4–6 client-facing recommendations.

## When invoked

Ask the user for, or infer:

1. **Source playbook path** — typically one of:
   - `<archive>/analysis/playbook.md` (single-company)
   - `<comparison-dir>/comparative-playbook.md` (two-company)
2. **Output path** — defaults to `<same-dir>/presentation.html`
3. **Client context (optional but recommended)** — what stage is the client they want to present this to (seed / Series A / Series B / pre-IPO)? What industry? Knowing this lets you tailor the closing recommendation slides.

If the user says "make a presentation from the analysis" without specifying which, default to:
- The combined `playbook.md` if it exists in a single-company `<x>/analysis/` dir
- The `comparative-playbook.md` if a comparison dir is present

## What this skill produces

A single HTML file the user opens in a browser. Keyboard nav (←/→), chapter sidebar, slide counter (e.g., "5/24"), fullscreen on `F` key. Dark theme, light text, designed for screen recording.

## How to build the deck

The template at `template.html` defines all slide layouts and rendering logic. Your job is to substitute a single placeholder, `{{SLIDES_JSON}}`, with a JavaScript array of slide objects. **Do NOT change the template's CSS or JS** — only the slide data array and the `<title>` (the `{{DECK_TITLE}}` placeholder).

### Step-by-step

1. **Read the template:**
   ```bash
   cat presenter/template.html
   ```
2. **Read the source playbook** (the analyzer output).
3. **Plan the deck.** Use the scratchpad in your head to map the playbook to slides:
   - Skip the playbook's TL;DR (it's a summary, the deck IS the summary)
   - Each major chapter of the playbook becomes a chapter in the sidebar
   - Within each chapter, pull out the 2–5 most striking facts as individual slides
   - Lean into NUMBERS as standalone slides (e.g., "5 strategic clusters" gets its own big-number slide)
   - Use comparison layouts when the playbook surfaces an A vs B contrast
   - Use timeline layout for the credibility ladder
   - End with 4–6 recommendation slides — these are the most important slides in the deck
4. **Write the slide array** as a JavaScript array of objects. See "Available layouts" below.
5. **Write the output file:** copy the template, substitute `{{DECK_TITLE}}` and `{{SLIDES_JSON}}`, save to the output path.

### Available slide layouts

Each slide is an object with `chapter` (string, used in sidebar grouping) and `layout` (string), plus layout-specific fields:

```js
// Section divider — use to introduce each major chapter
{ chapter: "Cadence", layout: "section",
  eyebrow: "Chapter 01", title: "How they paced the drumbeat",
  subtitle: "Releases over 5 years, clustered around inflection points" }

// Big number — use liberally; each striking stat gets its own slide
{ chapter: "Cadence", layout: "big-number",
  number: "24", caption: "days median between releases",
  footnote: "Mature companies in the same industry: 80+" }

// Comparison — A vs B side by side
{ chapter: "Stakeholder strategy", layout: "comparison",
  heading: "Who speaks for the company",
  leftTitle: "Build-stage co.", leftValue: "64%", leftDesc: "of releases quote the CEO",
  rightTitle: "Mature co.", rightValue: "12%", rightDesc: "of releases quote the CEO",
  warm: "right" }  // optional: 'left' or 'right' colors that side warm orange

// Quote — for landing a punchy insight
{ chapter: "Validator sequence", layout: "quote",
  body: "They waited until they had something material for that voice to validate.",
  attribution: "On the first surgeon-quoted release, year 4 post-funding" }

// Timeline — perfect for the credibility ladder; markers spaced evenly
{ chapter: "Credibility ladder", layout: "timeline",
  heading: "Five years, six rungs",
  markers: [
    { date: "Year 0", desc: "Capital event" },
    { date: "Year 1", desc: "Public company posture" },
    { date: "Year 2", desc: "First product demo" },
    { date: "Year 3", desc: "Clinical validation" },
    { date: "Year 4", desc: "Hospital partnerships" },
    { date: "Year 5", desc: "Bridge to first-in-human" },
  ] }

// List — bulleted (default) or numbered (ordered: true)
{ chapter: "Foundation plays", layout: "list", ordered: true,
  heading: "8 plays a build-stage company can borrow",
  items: [
    { title: "Investor Roster Anchor", desc: "Heavy validator stack in one release" },
    { title: "Headquarters / Real Estate", desc: "Operational maturity signal" },
    // ... etc.
  ] }

// Recommendation — for the closing chapter; numbered tag at top, big title, body
{ chapter: "Recommendations", layout: "recommendation",
  number: "PLAY 01",
  title: "Cluster three releases in 14 days around your next milestone",
  body: "Build anticipation at <strong>T-14</strong>, refresh team narrative at <strong>T-7</strong>, deliver at <strong>T-0</strong>. Then go quiet for 60–90 days." }

// Chart — simple horizontal bars
{ chapter: "Cadence", layout: "chart",
  heading: "Strategic clusters by year",
  subtitle: "3+ releases within 14 days",
  bars: [
    { label: "Year 1", value: 1 },
    { label: "Year 2", value: 3, warm: true },
    { label: "Year 3", value: 0 },
    { label: "Year 4", value: 1 },
  ] }

// Callout — large impactful phrase, optionally with inline highlights
// Use <span class="highlight">text</span> for accent color
// Use <span class="strong-warm">text</span> for warm accent
{ chapter: "Cadence", layout: "callout",
  text: "Vicarious clusters <span class=\"highlight\">5×</span> their normal rate around inflection moments.",
  sub: "Then goes quiet for 60–90 days." }

// Closing — final slide; gradient text
{ chapter: "Recommendations", layout: "closing",
  signature: "Your move.",
  nextStep: "Pick one play. Run it next quarter. Measure cluster intensity, silence discipline, and validator timing." }
```

### Style rules

- **Skip the playbook's intro/TL;DR.** Start with the substance.
- **One idea per slide.** If a slide has two ideas, split it.
- **Numbers > sentences.** When you have a number, use the `big-number` layout. The slide caption can be a short phrase; don't write paragraphs.
- **6–10 chapters max.** More than that overwhelms the sidebar. Group related sections.
- **20–30 slides total.** Less than 20 feels thin; more than 30 fatigues a recording.
- **Closing chapter must be "Recommendations"** with 4–6 recommendation slides plus one closing slide. These are the value the client takes away.
- **Recommendations are concrete plays.** Not "improve your PR" — "run a 3-release cluster around your next funding announcement, T-14/T-7/T-0."

### Tailoring recommendations to the client

If the user told you the client's stage and industry:

- **Seed / Series A:** Recommend Foundation Plays (Investor Roster Anchor, Strategic Hire, HQ release, Award Capture). Emphasize affordability and credibility-building from zero.
- **Series B / Series C:** Recommend the Drumbeat plays (clusters around milestones, strategic silences) and start the Validator Sequence (introduce first clinical/customer voice with proof).
- **Pre-IPO:** Recommend the Hospital/Customer-Validation Sequence and the Crisis-Recovery Pair discipline. They're entering the public-storytelling era.
- **Industry:** if medtech/biotech, lean clinical-ladder examples. If SaaS, swap "first surgeon quote" for "first enterprise customer logo" and "FDA submission" for "SOC 2 / GA launch."

### Substitution mechanics

The template has two placeholders to substitute:

1. `{{DECK_TITLE}}` in the `<title>` tag — set to a generic but informative title like "Press Release Strategy — Comparative Playbook" or "PR Playbook for early-stage medtech." **Do not include any specific company names.**
2. `{{SLIDES_JSON}}` in the `<script>` block — replace with the full JS array literal.

Use the Write tool to produce the output HTML file. After writing, report:
- Path to the file
- Number of slides
- Number of chapters
- The closing recommendations (one-line each) — these are the deliverable

## Reporting back

After writing the file, tell the user:
- File path and how to open it (double-click, or `open <path>` on macOS)
- Keyboard shortcuts: ← → to navigate, F for fullscreen, Home/End for first/last slide
- The 4–6 recommendation slide titles (the takeaways)
- Any caveats from the source playbook that surfaced

## Failure modes

- **Source playbook missing or empty** — surface this; don't fabricate slides.
- **Comparative playbook with one company barely covered** — flag the imbalance; the deck will tilt toward the well-covered company.
- **Heavy distress / crisis chapter** — be careful with framing. The deck should be analytical, not sensational.
- **Industry mismatch** — if the playbook is medtech but the client is fintech, the recommendations need translation. Ask the user to confirm the client industry before generating.
