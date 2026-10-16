# Design check

How to check the built app against the Brick Work design reference. Written for Claude Code and for quick manual checks.

## Where things are

| What | Path |
|---|---|
| Browse all frames (size and theme switches) | `design/index.html` → `BW Navigator.dc.html`, also on GitHub Pages |
| Manifest of every section and frame | `design/frames.json` |
| PNG of every frame, light and dark | `design/frames/<section>-<frame>-<width>-<theme>.png` |
| Static HTML of v1.3 sections (exact inline values) | `design/sections/<Group>/<id>.html` |
| Source pages (all sections) | `design/BW Guide|Collection|Workbench|Planning|Manage.dc.html` |
| Tokens | `design/tokens-v2.css` |
| Sample data | `design/test-data/` |
| Handoff, build spec, coverage | `docs/` |

Deep link to any section: `BW Navigator.dc.html#/<Group>/<Sub-area>/<id>?w=1440&t=dark`, or simply `#/12f`. The manifest gives each section's `view` link.

## Checking a screen (Claude)

1. Find the screen in `frames.json` by `group` and `sub` (they match the app's rail), or by `title`.
2. Open the PNGs for the widths you are checking (1440 first, then 1024, 390). Compare against a screenshot of the running app at the same width and theme.
3. For exact values, read `static_html` when present (v1.3 sections). Otherwise read the section in its source page (`source`, find `<section id="<id>"`); styles are inline, values in px and `var(--tw-*)` tokens.
4. Report differences as a list: section id, frame label, what differs, expected value, actual value. Cosmetic gaps under 2 px are not worth reporting.

## Rules that apply everywhere

- Colours only from `tokens-v2.css`. Clay (`--tw-accent`) is the only interaction colour: buttons, links, selected states. Status uses the status tokens, never clay.
- Inter for UI, Geist Mono for identifiers, counts, money and dates.
- Hairlines are 0.5 px. Radii 6 / 10 / 16 / pill. No shadows except sheets, menus and the scrim. No gradients, no emoji.
- Targets at least 44 px (56 px for primary checker actions). Tab bar labels 11 px.
- Set, figure and part images: never cropped, `object-fit: contain` on a white tile; sets 4:3.
- Money unspaced, symbol first: `€8.53`. Never mix currencies in one comparison.
- No minus, hyphen or dash before a number in visible text: "4 missing", "needs 6 · 4 left". Hyphens inside identifiers stay (6081-1). A lone dash for an empty value stays.
- Copy: English, sentence case, short, bare counts, mid-dots, no exclamation marks, never the word "LEGO".
- Every list: search, filter, sort, removable chips and a result count; 15 per page with the shared pager.
- Light and dark both supported; dark uses the same tokens under `.tw-dark`.

## Images

Third-party catalogue images are not in the repo (see `.gitignore`). Frames fall back to the placeholders in `design/assets/data/placeholders/`. The PNG exports were made with the images in place.
