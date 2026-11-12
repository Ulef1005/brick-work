# Design check

How to check the built app against the Brick Work design reference. Written for Claude Code and for quick manual checks.

## Where things are

| What | Path |
|---|---|
| Browse all frames (size and theme switches) | `design/sources/index.html` → `BW Navigator.dc.html`, also on GitHub Pages |
| Manifest of every section and frame (the design project's export) | `design/sources/frames.json` |
| Generated manifest: screens, states, sizes, light and dark, with the file names | `design/screens/manifest.json` |
| PNG of every frame, light and dark | `design/screens/NN-<screen>/NN-<Screen>[-<state>]-<width>-<theme>.png` |
| Static HTML of v1.3 sections (exact inline values) | `design/screens/NN-<screen>/NN-<Screen>.html` |
| Source pages (all sections) | `design/sources/BW Guide|Collection|Workbench|Planning|Manage.dc.html` |
| Tokens | `design/tokens/` (`tokens.css`, `brickwork-tokens.css`); the export's own copy is `design/sources/tokens-v2.css` |
| Sample data | `design/sources/test-data/` |
| Logo, app icon, UI icons | `design/logo/`, `design/app-icon/`, `design/components/icons/` |
| How each screen state is reached in the built app; built and approved flags | `design/screens/states.json` |
| Baseline captures of the built app, per screen state (candidates until approved) | `design/screens/approval/baselines/<NN-Screen>/<NN-Screen>[-<state>]-<width>-<theme>.png` |
| Older build captures sent for approval on issues (history) | `design/screens/approval/<issue>/` |
| Handoff, build spec, coverage | `docs/` |

The folders are organised by scripts (`scripts/design_screens.py`, `scripts/brand_assets.py`, `scripts/tokens_base.py`); `design/sources/` is the design project's export and is never hand-edited.

Deep link to any section: `BW Navigator.dc.html#/<Group>/<Sub-area>/<id>?w=1440&t=dark`, or simply `#/12f`. The manifest gives each section's `view` link.

## Checking a screen (Claude)

1. Find the screen in `design/sources/frames.json` (or `design/screens/manifest.json`) by `group` and `sub` (they match the app's rail), or by `title`. Its folder is `design/screens/NN-<screen>/`.
2. Open the PNGs for the widths you are checking (1440 first, then 1024, 390). Compare against a screenshot of the running app at the same width and theme.
3. For exact values, read the HTML in the screen folder when present (`static_html` in frames.json; v1.3 sections). Otherwise read the section in its source page (`source`, find `<section id="<id>"`); styles are inline, values in px and `var(--tw-*)` tokens.
4. Report differences as a list: section id, frame label, what differs, expected value, actual value. Cosmetic gaps under 2 px are not worth reporting.

## The screenshot gate

The gate compares the **built app** with **approved baseline captures** of the built app, per screen state; it never compares with the design frames, which stay the design record (ADR 0022).

- `design/screens/states.json` lists each screen section of the manifest with how to reach it in the built app (a path in the invented demo dataset, clock fixed) and two flags: `built` (the app has this screen) and `approved` (the maintainer approved its baseline captures). Only the maintainer sets `approved`, after reviewing the candidates. A screen that is not built, or whose state is not reached yet, says why.
- `python scripts/screen_gate.py capture [NN-Screen ...]` (run from the app's venv) renders every built, not yet approved state at 1440 / 1024 / 390, light and dark, into `design/screens/approval/baselines/` as candidates (review images; committed baselines come from the CI workflow, see below). It uses the pinned Chrome for Testing (`scripts/chrome.py`), the bundled fonts, no animation and a fixed clock.
- `tests/test_screen_gate.py` (in `scripts/check.sh` and CI) renders every state with `approved: true` and compares it with its baseline: a pixel is different when a channel is off by more than 3/255, and a capture fails when more than 0.05 % of its pixels differ or its size changes. On failure it writes the diff image to `build/screen-diffs/`. With no approved state it runs, reports "0 approved states, N candidates pending approval" and passes.
- The gate and the `capture` command render on up to four Chrome processes at once (`BW_GATE_WORKERS=1` for one): a capture does not depend on the session it is rendered in, because the browser starts every capture empty (no cache, stored data or web storage), loads every declared font face and lays the page out again once the fonts are in (#267, ADR 0024). `python scripts/screen_gate.py agree` renders every approved state on one process and on four and compares the two (the `gate-agree` workflow runs it on Linux). `scripts/check.sh` runs the gate as its own step after the parallel tests; `BW_GATE_KEEP=<folder>` keeps the actual captures.
- The `check.sh` summary prints: approved states checked, how many differ, candidates pending, states not built.
- A baseline is rendered on one platform; pixels from another operating system's Chrome differ in text anti-aliasing. The gate compares **in CI, on Linux**; a local macOS `compare` is expected to differ slightly and is not authoritative.
- Committed baselines are rendered on the platform the gate runs on. Review images for the maintainer may be rendered anywhere (a candidate on a Mac is fine to look at). **At approval** the session runs the `baselines` workflow (`.github/workflows/baselines.yml`, `workflow_dispatch`, input `screens`: the approved screens' names or NN prefixes) on GitHub, downloads its `baselines` artifact, and commits those PNGs together with the `APPROVALS.md` line and `approved: true` in `states.json`, in one commit. `capture` skips an approved state, so for a screen that is already approved and changes on purpose, first commit `approved: false` for its states and push, then run the workflow. Until a state is approved it has no baseline file; once approved it has all six (`scripts/design_screens.py check` enforces both).
- A state names its `world`: `demo` (the approved baselines' dataset, never extended), `showcase` (the exported demo's invented collection: orders, a flea-market lot, sets with two copies, staged checks) or `extras` (the showcase plus `brickwork/demo/gate_extras.py`: an instruction, boxes, a dollar wish). Data a new state needs goes into `showcase` or `extras`, never into `demo`, because that would move approved baselines. A state may carry a `script` (JavaScript run before the capture: open a sheet, tick a box) and a `max` height (a bottom sheet is a fixed bar: `max: 900` captures one viewport with it open) and `sheet_below` (a width in px: below it the capture is one real viewport, 844 px on a phone, for a sheet that is a fixed panel rather than a `dialog[open]`, such as the filter panel). A page that another built state already shows is recorded as `built: false` with a `reason` and `covered_by` naming that state; a screen the app does not have says so in its `reason`.
- When the gate fails in CI, the `screen-diffs` artifact of the run holds the diff images.
- An intended visual change updates the candidates (`approved` back to false), and the maintainer approves them again.

## Rules that apply everywhere

- Colours only from `design/tokens/` (served as `tokens-v2.css`). Clay (`--tw-accent`) is the only interaction colour: buttons, links, selected states. Status uses the status tokens, never clay.
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

Third-party catalogue images are not in the repo (see `.gitignore`). Frames fall back to the placeholders in `design/sources/assets/data/placeholders/`. The PNG exports were made with the images in place.
