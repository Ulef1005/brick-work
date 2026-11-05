# Brick Work: build spec

Short rules for building the frames. Devices in order of use: **MacBook 1440 × 900 and 1280 × 800 (hero)**, **iPad mini 5 at 768 × 1024 and 1024 × 768**, **iPhone 16 at 393 × 852 (rare)**. Tokens: `assets/tokens-v2.css`.

## 1. Interaction states

Every interactive component has these six, drawn with tokens only.

| State | Rule |
|---|---|
| Default | As in the frames. |
| Hover (pointer only) | `opacity: 0.7` on text or icon buttons; filled clay buttons keep their fill. No hover on touch. |
| Pressed | Ground fades to `--tw-accent-soft`, text to `--tw-accent-text`, 120 ms. Primary clay button: ground to `--tw-viz-5`. |
| Focus-visible | 2 px `--tw-accent` outline, 2 px offset (set in `tokens-v2.css`). Never removed. |
| Disabled | `--tw-surface-2` ground, `--tw-text-muted` text, label says what is missing ("Choose a colour"). |
| Loading | Label stays, a 14 px ring spinner is added; the control is not clickable. |
| Error | One plain sentence, one action, the code in mono under it, `--tw-danger` for the code only. |

Components: stepper (− / count / +), Found / Missing answer, filter chips, segmented control, choice chip (colour), toggle, bottom sheet, side panel.

## 2. Motion

`--tw-ease` for everything; 120 ms for state changes, 240 ms for sheets and pushes. No bounce, no shared-element transitions.

- **Sheets:** rise from the bottom (phone, iPad portrait) or slide in from the right (desktop, iPad landscape); the scrim fades in with it.
- **Checker answer:** the row or part saves at once; the progress strip segment grows over 240 ms; a toast "Saved" with **Undo** stays 5 s.
- **Undo:** restores the previous answer, the strip shrinks back, toast "Undone".
- **Route change:** push from the right; Back reverses.
- **Reduced motion:** every transition becomes an instant change or a 0 ms opacity swap; the strip and toasts still update. No decorative motion exists.

## 3. Feedback on save

- Saved: inline check next to the changed value for 1.5 s, plus the toast.
- Saving slowly (over 400 ms): the value shows a small ring.
- Offline or failed: the value stays as typed with a warning-soft pill "Not saved · waiting for network" and a Retry action; nothing is lost; the checker keeps a local queue and sends in order.
- Undo is always the first action on a reversible save; destructive actions ask first.

## 4. Keyboard and pointer (MacBook)

- **Jump:** ⌘K. Esc closes sheets, panels and menus; focus returns to the opener.
- **Checker:** `F` found all, `M` missing, `1`–`9` set the count, `S` skip for later, `Z` or ⌘Z undo, `←` back, `→` or Enter next. Shown as small keys in the footer of the part screen.
- **Part Runner:** the same keys; `Enter` opens the find selector, `1`/`2`/`3` choose add to set, loose parts, pick list only.
- **Part Spotter:** `Space` takes the picture, `Enter` confirms the label when a colour is chosen, `1`–`9` choose a candidate.
- **Lists:** `/` focuses search, `F` opens Filters, arrow keys move between rows, Enter opens.
- **Tab order:** top bar, rail, page title, toolbar, list, sticky actions. Sheets trap focus.
- **Drag and drop:** photo files onto Add and Part Spotter; the drop zone shows a clay dashed outline while a file is over it.

## 5. Accessibility

Targets: 44 px minimum, 56 px for steppers and the main answer. Support 200 % zoom (rows grow, nothing clips; long names wrap to two lines then truncate with a tooltip). Contrast numbers below use `--tw-*` token pairs actually used in the frames (WCAG ratio).

| Pair | Light | Dark | Result |
|---|---|---|---|
| text on bg | 16.9 | 15.0 | pass |
| text on surface | 15.4 | 13.7 | pass |
| text-2 on bg | 9.7 | 10.0 | pass |
| **text-muted on bg** | **3.5** | 4.8 | light fails AA for small text |
| **text-muted on surface** | **3.2** | 4.4 | light fails; dark just under |
| **text-muted on surface-2** | **3.0** | 4.0 | fails both |
| accent-text on bg | 5.2 | 9.8 | pass |
| **accent-text on accent-soft** | **4.4** | 7.2 | light just under AA |
| ink on accent (primary button) | 5.3 | 8.3 | pass |
| text on status pills (success, warning, info, danger soft) | 14.7–15.0 | 11.2–11.5 | pass |
| mark paper on brand accent | 5.4 | 8.5 | pass |
| ink or paper on colour swatches | 5.2–17.7 | same | pass |

**Action on the failures** (proposal, for the owner to approve): use `--tw-text-2` for any text smaller than 18 px that carries information (ids, counts, ages); keep `--tw-text-muted` for non-essential hints only. If the muted look is wanted, darken it for small text to `#6B665D` (about 5.4 on bg, 4.6 on surface-2) as `--bw-text-small`. Darken light `--tw-accent-text` on `--tw-accent-soft` selected chips to about `oklch(0.50 0.17 42)`; verify once built.

Labels for assistive tech: steppers ("Missing count, 4, increase / decrease"), colour swatches ("Tan, selected"), chips ("Filter: Incomplete, on"), progress strip ("40 found, 2 missing, 1 skipped, 70 to go"), image slots (alt = part name and colour; decorative placeholders hidden).

## 6. Standalone mode and safe areas

- **Tokens:** `--tw-safe-top`, `--tw-safe-bottom` (and `env(safe-area-inset-left/right)` in landscape). Fixed bars pad with them; content scrolls under translucent-free bars (no blur).
- **iPad mini 5** (no notch, home indicator on the bottom edge, status bar 24 pt): top bar 56 px sits under the status bar; sticky action areas and the tab or side bar add `--tw-safe-bottom` (about 20 px). Landscape: left rail and right edge add `safe-area-inset-left/right` (0 on this model, keep the rule).
- **iPhone 16** (Dynamic Island, status bar 54 pt): top bar adds `--tw-safe-top`; bottom bar adds 34 px home-indicator pad.
- **Status bar style:** `default` (dark text on the page colour) with `theme-color` set for both schemes. `black-translucent` would draw content under the bar and force every top bar to carry the inset; not needed here.
- **Mac browser window:** no insets; the app fills the viewport, minimum width 1024, below that the rail collapses to icons.

## 7. Images

- **Ratios:** set hero 4:3 contain; missing-part cards 96 px square; compact rows and Matching 56 px square; checker, picker and scanner pictures square, `object-fit: contain`, never cropped; minifigure 1:1; instruction 3:4; box 4:3.
- **Ground:** parts and boxes are photographed on white. Place them on a white tile (`#FFFFFF`) with 0.5 px `--tw-divider-strong` and radius 10 in both themes, so the white background reads as a deliberate tile, not a hole in the page.
- **States:** loading = `--tw-surface-2` tile with the part number in mono and no shimmer; failed = same tile with "Image did not load" and a Retry text action; none available = same tile with the number and "No image".
- **Lightbox:** tap or click opens the full-size picture on the scrim; pinch or `+` / `−` zooms, arrow keys move between pictures of the same list, Esc or tap outside closes, caption shows name and colour.

## 8. Part colours: Rebrickable colour id to hex

From Rebrickable `colors.csv` (id, name, rgb). **Verify each row against the downloaded file before shipping; these values were entered from memory and the file is the authority.** Ink rule: relative luminance above 0.45 gets `#1A1816`, otherwise `#FAFAF8`.

| id | name | hex | ink |
|---|---|---|---|
| 0 | Black | #05131D | paper |
| 15 | White | #FFFFFF | dark |
| 19 | Tan | #E4CD9E | dark |
| 71 | Light Bluish Gray | #A0A5A9 | dark |
| 72 | Dark Bluish Gray | #6C6E68 | paper |
| 120 | Dark Brown | #352100 | paper |
| 4 | Red | #C91A09 | paper |

The frames still draw approximations (Tan `oklch(0.82 0.05 85)`, Light Bluish Gray `oklch(0.72 0.01 85)`); the build replaces them with this table.

## 9. Shell by device

- **Desktop (1440 and 1280):** rail with all four groups and counts, Jump in the top bar, Add as a clay action in the top bar, theme switcher at the foot of the rail.
- **iPad mini landscape (1024 × 768):** collapsed icon rail (64 px), same top bar. Labels appear on long-press and in the page title.
- **iPad mini portrait (768 × 1024):** top bar plus a **bottom bar of the four groups** like the phone; the group's items sit in a segmented row under the top bar and the Workbench group opens a six-item grid sheet on a second tap of the active tab. Reason: a rail would cost 64 px of 768; the thumb sits on the bottom edge at the table.
- **Phone:** unchanged from the v1 frames.
