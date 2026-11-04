# Captures of the built app

Two kinds of captures of the running app, both made from invented data (never anything under `data/`).

## `baselines/`: the screenshot gate's captures (D3, #160)

`baselines/<NN-Screen>/<NN-Screen>[-<state>]-<width>-<theme>.png`, one folder per screen section of `design/screens/manifest.json`, at 1440 / 1024 / 390, light and dark. `NN-Screen` is the manifest's folder name; `<state>` names a further state of a section (`50-Tools-and-admin-pages-settings-1440-dark.png`).

- **Candidates until approved.** `scripts/screen_gate.py capture` writes them. A state is approved only when the maintainer sets `approved: true` for it in `design/screens/states.json`, after reviewing its captures (through a review artifact). Until then they are candidates and the gate only counts them.
- **What the gate does.** `tests/test_screen_gate.py` renders every approved state again and compares it with its baseline; see `design/DESIGN-CHECK.md` § The screenshot gate. A baseline is a capture of the built app, never of the design frames.
- **How they are made.** From the app's venv, at the repo root: `python scripts/screen_gate.py capture [NN-Screen ...]`. It starts the real app on the demo dataset (clock fixed at 2026-10-12T08:00:00Z), renders with the pinned Chrome for Testing (`scripts/chrome.py`), bundled fonts, no animation, and clips pages longer than 1600 CSS px. States it cannot reach are listed with their reason in `states.json` (`built: false`).
- **Replacing a baseline.** Set the state's `approved` to false, run `capture`, and have the maintainer approve again.

## The older folders: captures sent for approval on issues

Captures from the test instance, sent for approval on the tracking issues before D3. Each file is named `<frame>-<view>-<device>-<width>-<theme>.png` (the widths are 390, 768 and 1440, so they are not the gate's baselines). Long pages are clipped to their first 3,000 px. The `build_frames.py` scripts in some folders re-create them from the repo root; they use a system Chrome at the path they name.

| Folder | Issue | What changed |
|---|---|---|
| [23-orders](23-orders/) | #23 (R1) | Orders hub rebuilt to 12b: three import cards and the "Already imported" table, no breadcrumb, no native dropdowns |
| [16-edit-panel](16-edit-panel/) | #16 (option A) | Matching removed from set detail; Instances and Own photos in the Edit panel; Take on a whole missing minifigure card (set 3178-1, figure cty0163) |
| [24-planning-manage](24-planning-manage/) | #24 (P1 to P5) | Wishlist price filter and verdict pills (12k); Export names the count; Add shows no list on an empty search; Prices age on one line |
| [18-21-collection-lists](18-21-collection-lists/) | #18, #21 | Sets cards (theme · year, status and price on one line, tags), pager 15 per page (12h), data headlines, filter chips, Parts as a table with By lot (7a), Select and Group in the filters (12i) |
| [24-12l-catalogues-keys](24-12l-catalogues-keys/) | #24 | Catalogues & keys rebuilt to 12l: sources table, keys column with Test and save, Replace, Remove and Undo |
| [24-12m-api-tokens](24-12m-api-tokens/) | #24 N1 | New API tokens page (12m): list, create with the token shown once, revoke with Undo |
| [23-r2-storage](23-r2-storage/) | #23 R2 | Storage rebuilt to 12c: table and contents, Select and move, purchase locations. Type, parent and note wait for decision #46 |
| [23-r3-part-to-inventory](23-r3-part-to-inventory/) | #23 R3 | Part to Inventory rebuilt to 3f: camera row, recognition switch, viewfinder, review, queue, batch sheet |
| [24-p6-tools-admin](24-p6-tools-admin/) | #24 P6 | Old breadcrumb gone everywhere; Tools & Admin hub as grouped rows (5b); subpage headers (7e, 11d); database check on a button; 404 page (7f) |
| [24-4b-prices](24-4b-prices/) | #24 (speed) | Prices rebuilt for speed: light page, 15 rows per page with the Collection pager, Details load on open; thumbnails |
| [112-m10-b](112-m10-b/) | #112 (M.10 batch B) | Identity: Links card per provider with status, colour scope and preferred (m10b1); choosing the preferred link for all colours or one (m10b2); merge with search, preview and plain-words refusals, then Undo (m10b3); a merged item with Unmerge and its refusal (m10b4); Unresolved items rebuilt to the list pattern with what the copies use (m10b5); the unidentified item (m10b6) |
| [112-m10-a](112-m10-a/) | #112 (M.10 batch A) | Part lists: copy page Part list control, Switch sheet with what changes and marks that do not carry over, pending BrickLink list, list changed since built, retired lines, figure part sources; Add review Part list picker, picture warning, unknown number and unidentified (prototype on branch m10/frames-a, frames m10a1 to m10a8b; m10a2b is the Switch sheet at a taller viewport, so the whole sheet is visible) |
| [112-m10-c](112-m10-c/) | #112 (M.10 batch C) | Catalogue lifecycle in Tools & Admin: Catalogue build with Re-download and Rebuild, running and finished states, not reconciled yet; BrickLink item lists; Mappings and coverage; Settings part-list switch and picture source order; migration report view |
