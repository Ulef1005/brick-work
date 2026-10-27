# Design audit: screens for approval

Captures from the test instance of the app, for approval on the tracking issues. Each file is named `<frame>-<view>-<device>-<width>-<theme>.png`, the same pattern as `design/frames/`. Long pages are clipped to their first 3,000 px.

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
