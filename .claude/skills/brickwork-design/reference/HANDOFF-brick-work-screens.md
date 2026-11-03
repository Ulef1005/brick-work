# Handoff: Brick Work screens

Frames: `Brick Work Screens 1.dc.html` (one canvas, sections 1a to 6a, light and dark through the Theme tweak). Index: `INDEX-brick-work-screens.md`. Coverage: `COVERAGE-brick-work.md`. Brand and patterns: `skills/brick-work-brand/`.

## Part colours: use Rebrickable colors.csv

The frames draw colours as approximations. In the build, take every part colour from Rebrickable's `colors.csv` (download from rebrickable.com/downloads):

| Column | Use |
|---|---|
| `id` | the Rebrickable colour id, the key to join on inventory rows |
| `name` | the name shown inside the swatch |
| `rgb` | six hex digits without `#`; the swatch fill |
| `is_trans` | `t` for transparent colours: draw the swatch with a 50 % checker-free tint and keep the name in dark ink |
| `num_parts`, `num_sets`, `y1`, `y2` | not needed |

Rules:
1. Store the file in the instance (it changes rarely) and refresh it with the catalog sync.
2. Fill = `#` + `rgb`. Ink = dark `#1A1816` when the colour's relative luminance is above 0.45, else paper `#FAFAF8`.
3. Unknown colour id: show the name "Unknown colour", a neutral `--tw-surface-2` fill and the raw id in mono. Never guess.
4. BrickLink colour names differ from Rebrickable's; match by Rebrickable id and show the Rebrickable name.
5. Order everywhere: colour first, part number second.

## Not framed yet

See the "Not framed" and "Partly" tables in `COVERAGE-brick-work.md`. The largest gaps are the item lists (Minifigures, Parts, Instructions, Boxes), wishlist detail, order detail and document review, admin pages, and system pages.


## Check Set Parts · "Missing so far" list
This is a **history view**, not a "last 3" list: it shows every part marked missing in the current check, newest first, and keeps growing (scrolls inside the panel). Each row has a "Found n" action to undo a miss. The "3 parts" in the label is the live count of the history.
