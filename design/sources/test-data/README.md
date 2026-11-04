# Brick Work – test data and images (for Claude Design)

Use this instead of inventing content. Every screen in the brief can be filled from here, in every state the brief asks for. Paths in the JSON are relative to this folder.

**Real vs invented.** Set, part, colour and minifigure names, numbers, years, themes, inventories and images are **real** (Rebrickable catalogue snapshot of 2026-10-03). The *collection* (which copies exist, where they are stored, what was paid, what is checked or missing), the orders, prices, tray photos and admin state are **invented**, seeded and consistent with each other. Do not treat any price as real.

**Images** are catalogue images from the Rebrickable CDN, resized (sets 640 px, parts 200 px, minifigures 400 px). They belong to their owners and are for design mock-ups only. The four tray photos in `images/photos/` are **synthetic**: catalogue part photos composited onto a tray. They are not real camera photos, so real ones will be noisier, darker and less tidy.

## Files

| File | What it holds | Feeds screens |
|---|---|---|
| `sets.json` | 19 owned copies of 18 sets (one set twice), with status, owners, tags, storage, purchase, grid progress, image | Home, Sets grid/list, set detail header, storage, statistics |
| `inventories/<set>-copy-a.json` | Full parts + minifigure-parts lists for 7 copies (see table below) | Set detail, Parts tab, Minifigures tab, Checker, Problems |
| `inventories/_index.json` | One summary line per inventory | Sets grid progress |
| `checker-scenarios.json` | Exact values for each checker state: start, part, count, skipped, figure, spares, finish with problems, finish clean, resume, 1,400-row stress | Check Set Parts (all states) |
| `part-to-inventory.json` | One capture session: 13 pieces with candidates, colour options, confidence, "missing in your set X", the no-match case, queue states, added actions, export formats | Part to Inventory (all 7 steps) |
| `wishlist.json` | 6 wishes with max price, condition, four price slots, 12 months of history, one fetch error, one empty price slot | Wishlist, price history chart |
| `orders.json` | 5 BrickLink orders (ordered, partly arrived, arrived), pasted confirmation text, line-level match state (matched / ambiguous with candidates / unmatched), received counts | Orders |
| `statistics.json` | Totals, by theme, year, storage, spend by year, top colours, completeness buckets | Statistics |
| `colors.json`, `images/colors-sheet.png` | 43 colours with RGB and transparency (all colours used, plus the 8 commonest transparent ones) | Colour swatches everywhere |
| `metadata.json` | Owners, storages, purchase locations, statuses (with "show on grid"), tags | Filters, Manage, forms |
| `tools-admin.json` | Config, database size and tables, migrations (one pending), integrity findings, image cache, retired sets, instructions, exports, fetch log, bulk refresh queue | Tools & administration |
| `edge-cases.json` | Very long names, umlauts and CJK, 0-part set, price 0, 842-piece rows, transparent and near-duplicate colours, 66-minifigure set, 10,001-part set | Truncation, wrapping, number widths |
| `empty-states.json` | 15 empty/zero-data situations with the trigger and the next action | Empty states |

## The seven full inventories (the checker walks these)

| Copy | Rows | Pieces | State | Use it for |
|---|---|---|---|---|
| `7286-1-copy-a` Prisoner Transport | 93 | 173 | nothing checked | Checker **start**; sealed set |
| `1592-1-copy-a` Town Square – Castle Scene | 145 | 484 | 37 % of rows checked, 5 missing, a few half-counted rows, 8 minifigures | Checker **part / count / skipped / figure / resume**; Part to Inventory target |
| `6085-1-copy-a` Black Monarch's Castle | 150 | 661 | 100 % checked, 0 missing | **Finish clean**; "complete" status |
| `40567-1-copy-a` Forest Hideout | 86 | 258 | all checked, 6 missing, 2 damaged | **Finish with problems**; Problems page; export missing |
| `30637-1-copy-a` Animal Tray and Bag Tag | 27 | 94 | nothing checked, 0 minifigures | Tiny set, no Figure step |
| `21325-1-copy-a` Medieval Blacksmith | 455 | 2,164 | 100 % checked | Dense list, long tables |
| `75192-1-copy-a` Millennium Falcon | 706 | 7,534 | nothing checked | Stress test: progress strip with 700 rows, scrolling |

Rows have: `part`, `name`, `category`, `color {id,name,rgb,transparent}`, `quantity`, `spare`, `element`, `print`, `checked`, `missing`, `damaged`, `image` (local) and `image_url` (remote). Minifigure parts live under `minifigure_parts[<fig number>]`. `image` is `null` where the catalogue has none (4 real cases); design the missing-image state with `images/_placeholders/`.

## Image folders

`images/sets/` 24 set covers · `images/parts/` 544 part-in-colour images (named `<part>__<colourId>.jpg`) · `images/minifigs/` 30 · `images/photos/` 4 synthetic trays · `images/colors-sheet.png` · `images/_placeholders/` neutral missing-image tiles (replace with your own states).
Full part images exist for the five small hero sets; for the two large ones only the 48 most numerous rows have an image, so a long list also shows the missing-image state realistically.

## Tray photos

| File | Situation |
|---|---|
| `tray-01-sorted.jpg` | 12 parts spaced out; 4 of them are missing in set 1592-1 (the happy path) |
| `tray-02-pile.jpg` | 36 overlapping parts, queue and bulk-review stress |
| `tray-03-dim-light.jpg` | Dark, soft focus; should prompt "retake?" |
| `tray-04-single-part.jpg` | One part, close up; the single-piece review step |

## Rules of the data

- Dates are ISO `YYYY-MM-DD`; prices are EUR with two decimals; today in the data is **2026-10-12**.
- Every `*_pct` and summary figure is derived from the rows, so numbers agree across screens (for example 5 missing in 1592-1 shows on the grid, the set page and Problems).
- Names that look like typos (`Colour`/`Color`, `Gray`) are the catalogue's own. Keep them.
- Not covered here: Apple icons, splash images, brand marks (those are your deliverable), real camera photos, and real prices.

## Added in v1.3 (synthetic)

| File | Feeds |
|---|---|
| `storages.json` | 12c Storage, purchase locations |
| `sources-and-keys.json` | 12l Catalogues & keys, 12j first run |
| `api-tokens.json` | 12m API tokens |
| `collection-sync.json` | 12n Collection sync |
| `barcodes.json` | 12o Scan a set barcode (fake EAN codes) |
| `wish-max-currency.json` | 12k Max price with a currency |
| `minifigure-detail.json` | 12f Minifigure detail, 12g Minifigures in a set |

`empty-states.json` gained firstRun, empty storage, no storages and no tokens.
