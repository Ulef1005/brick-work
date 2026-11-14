# Handoff: Brick Work (screens, flows, brand)

## Overview
Brick Work is a single-user Lego collection workbench, a sub-brand inside Toni's World. It tracks owned sets (the rail counts in the frames come from a real collection of a few hundred items. The bundled sample data is smaller: 19 copies of 18 sets and 6 wishes, only for filling frames), wishlist, loose minifigures and parts, orders, storage and prices, and has workbench tools: **Part Spotter** (photo to part ID), **Set Inspector**, **Part Runner** and **Matchmaker**. Devices, in order of importance: **2020 MacBook (1440 × 900, 1280 × 800) is the main device**; iPad mini 5 sometimes (768 × 1024, 1024 × 768); iPhone 16 very rarely. English UI, no login.

## About the design files
Everything in `design_files/` is a **design reference built in HTML**: prototypes showing the intended look and behaviour, not production code. Recreate them in the target codebase's own stack and patterns (React, Vue, SwiftUI, etc.). If no stack exists, pick the most suitable one for a responsive PWA. Do not ship the HTML.

## Fidelity
**High fidelity.** Final colours, type, spacing and copy. Recreate pixel-accurately using the codebase's libraries. Part colours in the frames are approximations; use Rebrickable `colors.csv` in the build (see Data).

## Open the files
- `design_files/reference/BW Guide.dc.html` (general guidance: principles, colour, tokens, navigation, data-type language) and `BW Collection`, `BW Workbench`, `BW Planning`, `BW Manage`: one page per nav group. Each workflow is a row of all sizes: phone, MacBook 1440, iPad mini portrait and landscape (pan sideways). A Theme tweak switches light and dark. Each file needs `support.js`, `tokens-v2.css` and `assets/data/` beside it (laid out). PNG exports of every frame, light and dark, are in `design_files/frames/` (`<section>-<frame>-<width>-<theme>.png`); device coverage is in `reference/FRAMES-by-device.md`.
- `Brick Work Clickdummy.dc.html`: clickable flows (Sets, Set detail, Set Inspector, Part Runner, Part Spotter).
- `design_files/SKILL.md`: kit guide and page map. `reference/BUILD-SPEC.md`: motion, states, accessibility. `reference/COVERAGE-brick-work.md`: frames against capabilities (13 capabilities are partly framed, small variants of existing patterns).
- `design_files/test-data/`: sample JSON (sets, orders, wishlist, checker scenarios, part-to-inventory, colours, empty states, edge cases) plus README. Images are in `reference/assets/data/`.

## Navigation
Four groups:
- **Collection:** Sets (home `/`), Minifigures, Parts, Instructions, Boxes.
- **Workbench:** Part Spotter, Set Inspector, Part Runner, Matchmaker, Orders, Storage.
- **Planning:** Wishlist, Prices, Complete sets.
- **Manage:** Add, Tools & Admin (+ Statistics, system pages, theme switcher).

Phone (rare): top bar (mark + "Brick Work", Add, Jump search), a horizontally scrolling row of the active group's items under it, bottom tab bar (83 px incl. 34 px safe area) with the four groups. Desktop: 232 px left rail with group headings and counts, 56 px top bar with "Jump to a set, copy, figure or part" (⌘K); rail collapses to icons at 1024. Theme switcher: three icon segments (auto, sun, moon), no text.

## Screens (frame ids = section ids in the canvas)
Layout rule everywhere: phone 390 wide, 20 px side padding; desktop content padded 32 px.

**Collection**
- *1c Sets / 8a lists:* grid (4:3 cover, id in mono, name, theme · year, price with age mark, status pill) and list (56 px thumb rows, min 80 px). Search, Filters (sheet on phone, docked panel on desktop), Sort, removable chips, result count. Select mode, read-only and problem states in 8a.
- *1d Set detail:* hero, status, progress strip, Prices card, parts and minifigures, copies ("Set 1"), copy chooser/delete (7b).
- *2a Minifigure, 2b Part, 2c Instruction/box, 2d Part lot:* detail pages with the shared **Prices card** and a "Used in sets" list. 2b rows that complete a set show a success chip **"Completes set"** after the need count, in place of "· n left".
- *8c:* add into a lot, progress, instruction sheets, order details.

**Workbench**
- *3a Matchmaker, 3c Part Runner (Choose sets, Rank, Pick, Found it):* picker grid shows a count badge per found part; sheet has a stepper per copy.
- *3b/3e Set Inspector:* Start/Resume, Part (stepper `−` · "Found 4" primary · `+`, Missing, Back, Skip for later, Undo), Count, Figure, Spares, Finish.
  - **Missing so far** (desktop right panel) is a **history view**: every miss of the current check, newest first, growing, scrollable; a part found in full leaves the list (Ulf, 14.11.). Header "MISSING SO FAR · n PARTS · −total". Each row: part image, name, colour dot + number · colour name, "−1 of 2", **Found 1** button; footer hint "Found one in the pile? Tap Found 1 and the count drops."
  - **Missing pass** (phone, replaces the old "already answered" screen): final pass over answered parts. Progress strip "104 of 113 found / 9 missing", list of the same rows, button "Done · 9 still missing", links Back / Undo last. Use case: a pile of parts, add the missing items to a set.
  - Desktop checker: answer buttons sit directly under part name and number (no gap).
- *3f Part Spotter:* see flow below.
- *5a Orders, 7d detail/review/history/resume, 5d Storage.*

**Planning:** 4a Wishlist, 4b Prices, 4c Complete sets (pins, settings, export), 7c.
**Manage:** 4d Add, 5b Tools & Admin (+7e pages), 5c Statistics, 7f system pages, 8b place/storage/admin forms and theme picker.

## Part Spotter flow
1. **Capture.** Controls above the tabs: **Camera** row (e.g. "Rear camera · wide", dropdown; opens a list of available cameras) and **Recognition** switch **Local model | Brickognize** (default Local model, hint "Runs on this device · works offline"). Toggle "Add inventory to Brick Work". Viewfinder 4:3 with dashed guide and "Piece n" tag; primary "Take picture"; links "Add a saved photo", "Review n queued". Queue limit 6.
2. **Detect.** The chosen engine returns ranked candidates with confidence.
3. **Review (one piece).** Top: **reference part large** (2fr, white tile, name, number · colour · "0.91 match") beside **your photo** (1fr), both square. Below: **Other possibilities** list (48 px thumb, name, number · colour, score). Tapping an alternative swaps the reference. Colour: choice chips 56 px, filled with the colour, name inside, 3 px clay outline + tick when selected; **Confirm is disabled until a colour is chosen**. Unidentified pieces can be skipped or retaken.
4. **Verified queue.** Confirmed pieces go to the queue (Queue tab shows mixed statuses).
5. **Results / batch confirmation sheet.** Title "Add 3 pieces to inventory?", subtitle "1 uncertain piece is left out." Rows with image, "Piece n", name, colour chip, "+qty". **Add to:** segmented **Loose parts | Assign to a lot**; lot picker row ("Lot · Pile A · Oct 2024 · 128 parts"); link **New lot**; primary **"Add 3 to Pile A"**; Cancel. Success banner "Receipts saved. Batch added." Done returns to Workbench.
6. Errors/empties: queue full, storage full (export session), no camera, unreadable photo, nothing identified (frame "3f Scanner errors and empties").

## Data-type language (use on every screen; frame 1a)
- **Identity:** picture left/top, number mono above name, theme · year muted. Not coloured.
- **Status pills:** dot + word on soft ground, ink text. Complete = success, Incomplete = warning, Sealed = info, unknown = dashed outline. A missing minifigure makes a copy Incomplete even when checked.
- **Counts:** mono tabular, right-aligned, deficits with minus ("needs 6 · −4").
- **Money:** mono, currency first, age mark ("€8.53 8 Oct"); stale says "stale"; listings labelled "listings"; none = "no sales". Never mix currencies.
- **Actions:** clay only; 44 px min, 56 px for steppers and main phone action; one primary per screen; destructive confirm is the only danger-tinted button.
- **Colour:** swatch filled with the colour, name inside; ink `#1A1816` on light colours, `#FAFAF8` on dark; inline chip 22 px radius 6; never a bare dot (except the small dot beside a number in dense lists), never a colour without its name; **colour first, part number second**.
- **Prices card (same everywhere):** card `--tw-surface`, radius 16, padding 20, gap 20. Per row: label (Used/New), value + unit (avg/listings), **range bar** (8 px band min to max, 3 px ink tick at average, "min €x" / "max €y" under it), sub-line "5 sold · 6 months · 8 Oct · fresh". Sets only: "With box" and "Set estimate".
- **Progress strip:** found `--tw-viz-4`, missing `--tw-warning`, skipped outline, to go `--tw-viz-n1`; 8 px, gap 2, mono legend.
- **Images:** set rows set covers; part rows part images on white tile (`object-fit: contain`); minifigure rows minifigure images. Never cross categories. Missing image: `placeholders/missing-*.jpg` tile.

## Interactions and behaviour
- Hover (pointer): opacity .7. Pressed: row background to `--tw-accent-soft`, 120 ms ease; no scale. Sheets slide 240 ms, easing `cubic-bezier(.2,.6,.2,1)`. No bounces, shimmer or blur.
- Counter on button: `−` · primary carrying the count · `+`.
- Take/Give: one transfer path from loose stock, capped at min(needs, have).
- Every list: search, Filters, Sort, chips, result count.
- Thumb zone: main phone answer in the bottom third; sticky bars never overlap the tab bar.
- Details: see `BUILD-SPEC.md` (motion, states, accessibility). Min contrast 4.5:1 for text (3:1 headline scale); use `--tw-text-muted`, not `--tw-text-faint`, for text.

## State and data
- Entities: Set (id `7286-1`, copies with `copy_label`), Copy (status, checked, missing parts), Part (number, name, colour id), Colour (Rebrickable id), Minifigure, Lot, Order, Wishlist item, Price observation (condition, avg/min/max, count, window, observed date).
- Set Inspector state: per part `{needed, found, missing, skipped}` + history array of misses; derived progress strip; "Missing pass" reads the history and decrements on Found 1.
- Part Spotter state: settings `{camera, engine: 'local'|'brickognize', addInventory}`, queue (max 6) of pieces `{photo, candidates[{part, colour, confidence}], chosen, colour, status}`, batch `{destination: 'loose'|'lot', lotId}`.
- Part colours: Rebrickable `colors.csv` (`id`, `name`, `rgb` hex without `#`, `is_trans`). Fill `#rgb`; ink dark if luminance > 0.45 else paper. Unknown id: "Unknown colour", neutral fill, raw id in mono. Match by Rebrickable id.
- Recognition engines: local on-device model or Brickognize API; both return the same candidate shape.
- Sync: catalog sync refreshes colours and prices.

## Design tokens
Source: `design_files/assets/tokens-v2.css` (Toni's World v2; load first).
- **Light:** bg `#FAFAF8`, surface `#F2EFE9`, surface-2 `#ECE8DF`, divider `#E7E2D7`, divider-strong `#D8D1C3`, text `#1A1816`, text-2 `#45413B`, muted `#8A847A`, faint `#B5AFA3`; accent `oklch(0.66 0.17 45)`, accent-soft `oklch(0.93 0.04 55)`, accent-text `oklch(0.54 0.17 42)`; success `oklch(0.55 0.08 150)`, warning `oklch(0.64 0.10 80)`, info `oklch(0.54 0.06 245)`, danger `oklch(0.62 0.18 25)` (each with `-soft`); scrim `rgba(20,15,5,.30)`.
- **Dark:** bg `#1A1816`, surface `#232020`, surface-2 `#2C2826`, divider `#2F2B27`, divider-strong `#403A34`, text `#F1ECE3`, text-2 `#C8C2B6`, muted `#8C857A`; accent `oklch(0.78 0.16 55)`, accent-soft `oklch(0.32 0.07 45)`, accent-text `oklch(0.84 0.15 58)`; scrim `rgba(0,0,0,.45)`. In sheets set `--tw-surface: var(--tw-surface-2)` so chips stay visible.
- **Type:** Inter (primary), Geist Mono (numbers, ids). Display 34/40, H1 28/34, H2 22/28, H3 18/24, body 17/27, small 14/20, label 11/14 uppercase +0.10em. Headlines tracking −0.2 to −0.4. Weights 400 body, 500 controls, 600 headings.
- **Spacing:** 4 · 8 · 12 · 16 · 20 · 24 · 32 · 40 · 56. **Radii:** 6 chips, 10 buttons/inputs, 16 sheets/cards, pill 999 for tags only. **Borders:** 0.5 px hairlines. **Shadows:** none. No gradients, no emoji.
- **Brand accent (identity surfaces only):** `--bw-accent` `oklch(0.50 0.10 215)` light / `oklch(0.76 0.10 215)` dark; soft `oklch(0.89 0.045 215)` / `oklch(0.35 0.065 215)`. Used only for logo, app icon, splash, lockup and the 24 px mark in the top bar; never on controls or data.

## Assets
- `assets/brand/`: mark (`mark.svg`, dark, line), app icon, icons 152 to 1024, splash for iPad mini (1536×2048, 2048×1536) and iPhone 16 (1179×2556) light/dark, lockups (PNG or SVG; the SVG text needs Patrick Hand, shipped in `assets/fonts/`), manifest, `brick-work.css`.
- `assets/icons-ui/`: 33 UI icons, 24 px grid, 1.6 px stroke, round caps. New: Boxes, Part Runner, Matchmaker, sun, moon, auto.
- Sample images (`reference/assets/data/`): from the supplied test data, for design only. Real imagery is still needed for the five image-slot categories.
- Wordmark font Patrick Hand (brand surfaces only): `assets/fonts/PatrickHand-Regular.woff2` (Latin subset, from Google Fonts) and `OFL-PatrickHand.txt`. Serve it from `/fonts/`, as `head-block.html` expects.
- No LEGO trademarks: never the word "LEGO", its logo or a minifigure likeness in the brand; UI says "set", "part", "minifigure".

## Voice
Warm, short, sentence case, bare counts, mid-dots, no exclamation marks. Names: "Tools & Admin", "Part Spotter", "Wishlist", "Set 1".

## Open items
Rebrickable `colors.csv` (sample `colors.json` is enough for frames; see Guide G2); real imagery; wiring of the Missing pass and lot assignment in the click-dummy.

## Files
```
design_files/
  SKILL.md                         kit guide and page map
  assets/                          tokens-v2.css, brand/, icons-ui/
  reference/
    BW Guide|Collection|Workbench|Planning|Manage.dc.html
        Brick Work Clickdummy.dc.html
    support.js, assets/data/       runtime + sample images
    BUILD-SPEC.md, COVERAGE-brick-work.md, INDEX-brick-work-screens.md,
    HANDOFF-*.md, README-brick-work.md
  test-data/                       JSON + README + images
```
