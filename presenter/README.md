# press-release-presenter

> Turn a strategic PR-analysis playbook into a recording-ready HTML slide deck — with the closing slides as concrete recommendations the client can act on next quarter. Sibling skill to [`press-release-archiver`](../archiver/) and [`press-release-analyzer`](../analyzer/).

Input: a `playbook.md` (single-company analysis) or `comparative-playbook.md` (two-company comparison) produced by `press-release-analyzer`.

Output: a single self-contained HTML file. Open in a browser, press `F` for fullscreen, navigate with ← / → arrow keys, screen-record while you narrate.

```
your-archive/analysis/
├── playbook.md            # input (from analyzer skill)
└── presentation.html      # output (this skill)
```

For a comparative deck:

```
company-a-vs-company-b/
├── comparative-playbook.md   # input
└── presentation.html         # output
```

---

## Why this exists

A strategic playbook produced by the analyzer is a thorough document — typically 2,500–4,000 words across multiple analytical sections. That's the right format for an analyst to study but the wrong format to present to a client.

A presentation forces compression. Each slide gets one idea. Each chapter gets a sidebar entry. The client absorbs the strategy as a sequence of memorable moments rather than a wall of text. And critically — the deck **ends with recommendations**, not analysis. The client walks away with concrete plays to run next quarter.

This skill is also designed for **screen-recording**. Dark theme with high contrast, large readable fonts, minimal text per slide, smooth slide transitions. You can record yourself walking through the deck and post it as a Loom-style explainer for your client, or use it live on a Zoom call.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  ANALYZER  produces  →  playbook.md  /  comparative-playbook.md │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PRESENTER                                                       │
│                                                                  │
│  1. Claude reads the playbook                                    │
│  2. Claude plans the deck (chapters, slides, recommendations)    │
│  3. Claude writes a SLIDES JS array of slide objects             │
│  4. Substitutes the array into template.html                     │
│  5. Writes presentation.html                                     │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
                       presentation.html
                       (open in browser, ← → to navigate)
```

The template (`template.html`) is the single piece of styled, scripted infrastructure. It defines the dark theme, all slide layouts (big-number, comparison, timeline, list, recommendation, chart, callout, etc.), keyboard navigation, chapter sidebar, and slide counter. Claude doesn't write CSS or JS for each deck — only the slide data array.

---

## Available slide layouts

| Layout | Purpose | Example use |
|---|---|---|
| `section` | Chapter divider | Introduce each major chapter |
| `big-number` | One striking stat, full-screen | "5 strategic clusters", "64% CEO quote rate" |
| `comparison` | Side-by-side A vs B | Cadence rhythms, quote rates |
| `quote` | Punchy one-line insight | The most teachable lesson from the playbook |
| `timeline` | Horizontal markers | The credibility ladder |
| `list` | Bulleted or numbered | The 8 foundation plays |
| `recommendation` | Numbered, action-oriented | The closing chapter — "PLAY 01: cluster 3 releases…" |
| `chart` | Horizontal bar chart | Releases per year, archetype mix |
| `callout` | Big phrase with inline highlights | "Cluster <highlight>5×</highlight> the normal rate" |
| `closing` | Final gradient signature | "Your move." |

See [SKILL.md](./SKILL.md) for the full schema of each layout.

---

## Usage

```bash
# Step 1: produce a playbook with the analyzer skill
# (see analyzer/README.md)

# Step 2: invoke the presenter skill in Claude Code or Claude Desktop:
# "Make a presentation from the analysis at <path-to-playbook>.
#  My client is a Series A medtech company."

# The skill reads the playbook, plans the deck, writes presentation.html.

# Step 3: open the result
open <path>/presentation.html
```

In the browser:
- **Arrow keys** ← / → to navigate
- **Space / PageDown** also navigate forward
- **F** for fullscreen (best for recording)
- **Home / End** to jump to first / last slide
- Click any chapter in the left sidebar to jump to it

---

## Style decisions baked into the template

- **Dark navy background, light text, mint accent** — high contrast, gentle on eyes during long viewing
- **Inter / JetBrains Mono** typography — system fallbacks; works without external fonts
- **Numbers rendered at 240px** — readable on a phone screen recorded from a 4K camera
- **No external dependencies** — the entire deck is one HTML file you can email, host anywhere, or open offline
- **No animations beyond a 0.4s fade between slides** — recording-friendly; no distracting transitions
- **Sidebar is always visible** — gives viewers structure; signals "this is a structured analysis, not a stream of consciousness"

If you want to customize the theme or layouts, edit `template.html` directly. Changes apply to all subsequently-generated decks.

---

## Tips for screen recording

1. Open the deck, press `F` for fullscreen
2. Use a recording tool (QuickTime, Loom, OBS) at 1920×1080 or 4K
3. Speak naturally over each slide — they're designed for narration, not for self-reading
4. Keep ~20–40 seconds per slide; that puts a 25-slide deck at ~10–15 minutes recorded
5. End on the closing slide, then stop recording with the slide still visible (gives editing room)

---

## License

MIT. See [../LICENSE](../LICENSE).
