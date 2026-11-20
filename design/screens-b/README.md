# Screens, direction B′ Drawer Tag

The approved frames of commission U, built by `../sources/b/b_frames.py` (`build`, `check`), and of commission N (below). One folder per screen, `<theme>-<width>.html` and `.png` (device scale 2). Light and dark: Ulf approved light, one phone and one desktop view per screen, and then, at his request, every frame in dark (the dark round, #512). The dark frames are the light ones with the dark token values, the on-dark lockup and, for catalogue pictures, a light grey tile with the picture multiplied. The other widths are built from them (App Design Standard, review scope).

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
| `17-sync-hub/` | N1-01 Workbench · Sync, the hub (#518) | N round 1 |
| `18-rebrickable/` | N1-02 Rebrickable, the page at rest (#519) | N round 1 |
| `19-rebrickable-connect/` | N1-03 Rebrickable step 1, Connect, with the step bar | N round 1 |
| `20-rebrickable-choose-what/` | N1-04 Rebrickable step 2, Choose what, with the Lost Parts rule moved from Settings | N round 1 |
| `21-rebrickable-pick-sets/` | N1-05 Rebrickable step 3, Pick sets | N round 1 |
| `22-rebrickable-preview/` | N1-06 Rebrickable step 4, Preview, with the three-way conflict choice | N round 1 |
| `23-rebrickable-run/` | N1-07 Rebrickable step 5, Run | N round 1 |
| `24-rebrickable-result/` | N1-08 Rebrickable step 6, Result | N round 1 |
| `25-brickset/` | N2-01 Brickset, the page at rest | N round 2 |
| `26-brickset-choose-what/` | N2-02 Brickset, choose what | N round 2 |
| `27-bricklink/` | N2-03 BrickLink, the page at rest | N round 2 |
| `28-bricklink-connect/` | N2-04 BrickLink, connect (IP-bound token) | N round 2 |
| `29-bricklink-choose-what/` | N2-05 BrickLink, choose what | N round 2 |
| `30-bricklink-wanted-file/` | N2-06 BrickLink, wanted list by file | N round 2 |
| `31-brickowl/` | N2-07 Brick Owl, the page at rest | N round 2 |
| `32-brickowl-choose-what/` | N2-08 Brick Owl, choose what | N round 2 |
| `33-brickowl-run/` | N2-09 Brick Owl, run with a daily budget | N round 2 |
| `34-import-export/` | N2-10 Import & export | N round 2 |
| `35-own-export/` | N2-11 The complete export | N round 2 |
| `36-re-import-preview/` | N2-12 Re-import, preview | N round 2 |
| `37-rebrickable-pick-lists/` | N2-13 Step 3, Pick sets, by list | N round 2 |
| `38-sets-list-filter/` | N2-14 Sets, with a list filter | N round 2 |
| `39-set-detail-lists/` | N2-15 Set detail, with the list tags | N round 2 |
| `40-rebrickable-preview-lists/` | N2-16 Rebrickable, preview of list tags | N round 2 |
| `41-bricklink-pick-lots/` | N2-17 BrickLink, pick orders and lots | N round 2 |
| `42-bricklink-preview/` | N2-18 BrickLink, preview | N round 2 |
| `43-sync-errors/` | N2-19 When a run stops | N round 2 |

Commission N (Sync and files, #517) adds `17` to `24` (round 1), built by `../sources/n/n_frames.py` (`build`, `check`, `narrow`), which imports `b_frames.py`, and `25` to `43` (round 2: Brickset, BrickLink, Brick Owl, Import & export, the complete export and the list tags of #531), built by `../sources/n/n2_frames.py` (same commands, default folder `screens-b`); its review artifact is https://claude.ai/artifact/1sWRRsfiYxkEgHXxKxrsUn. Round 1 also changed approved frames: Sync is the last Workbench entry in `06`, `07`, `09`, `10`, `11`, `13`, `14` and `16` (C-01), Tools & Admin drops Collection sync (C-02, `01`) and Settings points to Sync (C-03, `02`). Its new components NC-01 to NC-06 (step bar, radio row, select field, filter chip, three-way choice, info box) are drawn inside the frames; `BUILD-NOTES.md` describes them.

These frames replace the v1.3 frames in `../screens/` screen by screen as each is approved; `../screens/` and its manifest stay the record of what is built today until the app is rebuilt (milestone U). Set pictures are empty white tiles with their alt text, because this public repo carries no catalogue pictures; the review showed the real pictures (https://claude.ai/artifact/FX8PAj3J9cgVkY42oPGc8a, version 3).
