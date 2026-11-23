# Screens, direction B′ Drawer Tag

The approved frames of commission U, built by `../sources/b/b_frames.py` (`build`, `check`). One folder per screen, `<theme>-<width>.html` and `.png` (device scale 2). Light and dark: Ulf approved light, one phone and one desktop view per screen, and then, at his request, every frame in dark (the dark round, #512). The dark frames are the light ones with the dark token values, the on-dark lockup and, for catalogue pictures, a light grey tile with the picture multiplied. The other widths are built from them (App Design Standard, review scope).

| Folder | Item | Approved |
|---|---|---|
| `00-components/` | R2-04 components: buttons, focus, tabs, label tape, status, the two Xs, progress per copy, cells, field | round 2 |
| `01-tools-and-admin/` | R2-05 Tools & Admin, with R2-01 the four-tab shell and R2-02 the lockup in the app bar | round 2 |
| `02-settings/` | R2-06 Settings | round 2 |
| `03-find-instructions/` | R2-07 Find instructions (#465) | round 2 |
| `04-sets/` | R3-01 Sets: label tape per storage, the bar per copy (#489), the storage index (#490), Drawers and Ledger | round 3 |
| `05-sets-without-storage/` | R3-01 Sets when no storage is set: no tape, no storage index | round 3 |
| `06-set-inspector/` | R3-02 Set Inspector | round 3 |
| `07-part-runner/` | R3-03 Part Runner | round 3 |
| `08-sets-empty/` | R3-04 Sets, empty | round 3 |
| `09-matchmaker/` | R4-01 Matchmaker: coverage bars, completable first | round 4 |
| `10-build-scout/` | R4-02 Build Scout: coverage bars, list with detail panel | round 4 |
| `11-storage/` | R4-03 Storage: short code first, detail under its label tape | round 4 |
| `12-set-detail/` | R6-02 Set detail: copy bar under the hero, Sell this copy and Value first | round 6 |
| `13-part-spotter/` | R6-05 Part Spotter: panels side by side, colour swatches | round 6 |
| `14-lot-sorter/` | R6-03 Lot Sorter: Set detection, ink score bar, Make a copy sheet | round 6 |
| `15-order-missing-parts/` | R6-01 Order missing parts: missing bars, order list, source choice | round 6 |
| `16-orders/` | R6-04 Orders: Count what arrived, status by shape | round 6 |
| `44-source-chip/` | N2-20 Set detail with the source of a copy: Added via, Last synced from, Checked on Rebrickable (#551, #489); early landing for U, the rest of N round 2 is on `design/sync-n` | N round 2 |
| `48-sets-pulled-copy/` | N2-24 Sets with the label of a pulled copy, "Checked on Rebrickable" (#489); early landing for U | N round 2 |
| `49-storage-select-mode/` | N2-25 Storage, Select mode: a checkbox beside each copy's bar, "2 copies picked" with Move to another storage (#500) | N round 2 |
| `50-404-missing-piece/`, `50-404-drawer/`, `50-404-everywhere/` | System pages: three funny 404 pages (A, B, C) the app rotates, light and dark, 1440 and 390 (#503, Ulf 23.11.) | #503 |
| `51-500-drawer-stuck/` | The 500 page in the drawer tone ("This drawer is stuck") | #503 |
| `52-order-allocation-line/` | Review allocation, an item line on the phone: "6 available · 0 allocated" on its own line below the name and colour | #503 |
| `53-offline/` | The offline page in the drawer tone: "Your drawers are out of reach" with a Try again button (#503) | #503 |

These frames replace the v1.3 frames in `../screens/` screen by screen as each is approved; `../screens/` and its manifest stay the record of what is built today until the app is rebuilt (milestone U). Set pictures are empty white tiles with their alt text, because this public repo carries no catalogue pictures; the review showed the real pictures (https://claude.ai/artifact/FX8PAj3J9cgVkY42oPGc8a, version 3).
