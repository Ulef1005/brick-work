# Brick Work: brand section

Sub-brand of Toni's World. Direction **D, "Courses, in progress"**. Assets in `assets/brick-work/`.

## Mark
Three courses of a running-bond wall in hand-stitched line, each brick with abstract raised studs. The bottom two courses are laid. In the top course one brick is set and the next is only outlined, dashed, with a stitched cross. The wall is still going up. Paper-coloured line on an accent tile, same 96-unit tile (rx 24) as the pillow mark.

Not a LEGO reference: no 2 × 4 brick, no stud-count fidelity, no red/yellow, no figure.

## Secondary accent (identity surfaces only)
| Token | Light | Dark |
|---|---|---|
| `--bw-accent` (ground under the mark) | oklch(0.50 0.10 215) | oklch(0.76 0.10 215) |
| `--bw-accent-soft` | oklch(0.89 0.045 215) | oklch(0.35 0.065 215) |
| `--bw-on-accent` (mark and text on the ground) | #FAFAF8 | #1A1816 |

Hue 215 sits 30° from `--tw-info` (245) and far from clay, danger, warning and success. Allowed on: logo, app icon, splash, lockup, and the mark beside the app name in the top bar. Never on controls, data or charts. Clay stays the interaction colour.
Check on a rendered build: on-accent text contrast (AA) in both themes.

## Files
- `mark.svg`, `mark-dark.svg`: tile marks. `mark-line.svg`: line mark, `currentColor`.
- `app-icon.svg` (1024, square, no rounding; iOS rounds it) and `icons/icon-{120,152,167,180,192,512,1024}.png`.
- Splash PNGs removed (they matched no device); regenerate per device from the mark when needed.
- `lockup-horizontal[-dark].svg`, `lockup-stacked[-dark].svg`. Text is live `<text>` in Patrick Hand; load the font or outline before shipping standalone.
- `manifest.webmanifest`: name and short name "Brick Work".
- `brick-work.css`: accent tokens, light and `.tw-dark`.

## Rules
- Wordmark: Patrick Hand, brand surfaces only. Product top bar uses Inter 600 beside the 24 px mark.
- No gradients, shadows, emoji, mascot, second interaction colour.
- At 16 px the studs blur into the brick edge; the course rhythm and the cross still read. Don't redraw a simpler favicon unless it fails on device.
