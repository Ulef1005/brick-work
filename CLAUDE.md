# Brick Work

## Design reference
The app must follow the design in `design/`. Before building or changing a screen, and when asked to check compliance, follow `design/DESIGN-CHECK.md`:
- find the screen in `design/sources/frames.json`,
- compare against its PNGs in `design/screens/` (light and dark, 1440 / 1024 / 390),
- take exact values from the HTML in its screen folder (`design/screens/NN-<screen>/`) or the section in its `design/sources/BW *.dc.html` page,
- use tokens from `design/tokens/`, never new colours.

`design/sources/` is the design project's export; `design/` is organised per P2 by scripts; never hand-edit `sources/` or generated files. Report design gaps instead.
