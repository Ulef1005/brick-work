# #131 wish price card: captures for approval

Captures of the wish detail page at 390 px (phone), light and dark, taken with `scripts/capture_screens.cjs` from a local instance on the
invented `tests.app4` fixture world. Named `<frame>-<view>-<device>-<width>-<theme>.png` as in `design/approval/`; the nearest frame
is `1d` (set detail, price card), which has no wish variant (a design gap reported on the PR).

The wish is set 1000-2 with a max price of €40 and no max with box; the set has a €35 used quote and a €55 quote with box.

| File | What |
|---|---|
| `1d-wish-price-card-phone-390-{light,dark}.png` | The price card alone (the other modules hidden for the capture): With box, Your max price, Max with box |
| `1d-wish-phone-390-{light,dark}.png` | The whole wish page as it renders |

## After the approved design (frames 131a to 131d)

The wish page was changed to follow the approved frames in `docs/design-proposals/131`. These captures are from that build, with the same fixture wish:

| File | What |
|---|---|
| `131a-wish-cards-phone-390-{light,dark}.png` | The Wanted card (Your max price, Max with box: Not set) and the price card footer (With box, Your max price, Max with box, one row each) |
| `131b-edit-sheet-phone-390-{light,dark}.png` | The Edit sheet with Max price with box, both currency fields labelled Currency, and the line on an empty max with box |
