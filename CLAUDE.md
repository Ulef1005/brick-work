# Brick Work

## Design reference
The app must follow the design in `design/`. Before building or changing a screen, and when asked to check compliance, follow `DESIGN-CHECK.md`:
- find the screen in `design/frames.json`,
- compare against its PNGs in `design/frames/` (light and dark, 1440 / 1024 / 390),
- take exact values from `design/sections/<Group>/<id>.html` or the section in its `design/BW *.dc.html` page,
- use tokens from `design/tokens-v2.css`, never new colours.

Do not edit files in `design/`; they are exported from the design project. Report design gaps instead.
