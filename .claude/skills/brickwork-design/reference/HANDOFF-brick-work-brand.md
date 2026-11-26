# Handoff: Brick Work brand (direction D)

> **Superseded for the logo and app icon** by `design/BRAND.md` sections 1 and 2 (the violet Bond mark with the cut-out X, commission U, approved 2026-11-18 and 2026-11-19). This file is kept as the record of the retired cross-stitch brand; its files are in `design/logo/retired/` and `design/app-icon/retired/`.

Answers `2026-10-brick-work-brand-handoff`. The owner chose **D, Courses in progress**; A, B and C were dropped. Screens brief (Phase 2b) builds on this.

## Decided
- Mark: three-course running-bond wall, stitched line, abstract studs, top course unfinished (one brick set, one outlined with a stitched cross).
- Accent: hue 215. Light ground `oklch(0.50 0.10 215)`, dark `oklch(0.76 0.10 215)`. Soft: `oklch(0.89 0.045 215)` / `oklch(0.35 0.065 215)`. On-accent: `#FAFAF8` / `#1A1816`.
- Wordmark: Patrick Hand, horizontal and stacked.

## Delivered (`assets/brick-work/`, mirrored in `skills/brick-work-brand/assets/`)
- Mark: light, dark, line. Lockups: horizontal and stacked, light and dark.
- App icon SVG (1024) plus PNGs at 120, 152, 167, 180, 192, 512, 1024.
- Splash 1170 × 2532, light and dark.
- `manifest.webmanifest`, `brick-work.css`.
- `README-brick-work.md` for the kit.
- `skills/brick-work-brand/SKILL.md`: Claude skill so later sessions apply the brand correctly.
- `Brick Work Specimen.dc.html`: A to D, light and dark, with favicon, home-screen, lockup and top-bar use (removed from `design/components/` with `BW Panel.dc.html` on 2026-11-26, Ulf: "Delete both (Recommended)"; git history keeps them).

## For Phase 2b
- Top bar: 24 px mark + "Brick Work" in Inter 600, clay controls on the right. The mark is the only teal on screen.
- Splash and icons are final; wire `apple-touch-icon` (180), the manifest and `apple-touch-startup-image`.
- Empty states may reuse the dashed outline plus stitched cross; keep it monochrome, no teal.

## Open
- Contrast not measured numerically: confirm AA for any text on `--bw-accent` in a rendered build.
- Lockup SVGs use live Patrick Hand text; outline them if shipped without the font.
- 16 px favicon: studs blur into the edge; confirm on device.
