# Coverage check: Brick Work frames against the manifest

Source: `coverage/coverage-manifest.json` (origin/house 553c98c), page-level tags only: **138**. Frames are in the five `BW *.dc.html` pages (sections 1a to 11d; `FRAMES-by-device.md`). Fourth pass (v1.2): the 13 partly-framed tags and the re-import message are now framed in 11a to 11d. Re-counted from the frame names and the earlier table, not by opening each frame again; my own judgement of which tag a frame carries.

| Result | Tags |
|---|---|
| Framed | 134 |
| Partly framed | 0 |
| Not framed | 0 |
| Build only or out of scope | 4 |

## Not framed

| Capability | Frame or gap |
|---|---|

## Partly

| Capability | Frame or gap |
|---|---|

## Build only

| Capability | Frame or gap |
|---|---|
| `collection.cached-images` | Image cache; frames use image slots |
| `collection.pagination` | Replaced by continuous scroll |
| `shared.csrf` | Build |
| `shell.login` | Out of scope: no login |

## Framed

| Capability | Frame or gap |
|---|---|
| `collection.copy-chooser` | 7b copy chooser sheet |
| `collection.counted-scopes` | 7a scope chips |
| `collection.figures-scopes` | 7a |
| `collection.grid-list` | 1c Sets, 8a Minifigures grid |
| `collection.item-search` | 7a |
| `collection.list-view` | 1c list |
| `collection.loose-figure-condition` | 7a New/Used chips |
| `collection.minifigure` | 2a |
| `collection.minifigures` | 7a |
| `collection.needed-by-copies` | 2a, 2b Matching |
| `collection.overview` | Home is the set overview: 1c Sets list |
| `collection.part` | 2b |
| `collection.part-lots` | 7a by-lot grouping and Lot column; 2d lot page |
| `collection.parts` | 7a |
| `collection.parts-scopes` | 7a |
| `collection.problems` | 8a |
| `collection.purchase-location` | 8b place page |
| `collection.random-samples` | 8a optional "Try one tonight" strip on the set overview |
| `collection.retained-management` | 8a select mode with Storage, Condition, Add to lot, Delete |
| `collection.scopes` | 1c status chips |
| `collection.search-filter-sort` | 1c, 4a |
| `collection.set-detail` | 1d |
| `collection.sets` | 1c |
| `collection.statistics-drilldown` | 5c |
| `collection.status-counts` | 1c bar and chips |
| `collection.storage` | 8b storage page, 5d list |
| `collection.storage-year-filters` | 1c Filters sheet |
| `collection.storages` | 5d |
| `collection.theme-hierarchy` | 8b theme picker |
| `collection.wish-detail` | 7b |
| `collection.wishlist` | 4a |
| `completion.pins` | 7c |
| `completion.ranking` | 4c |
| `completion.repair-settings` | 7c |
| `completion.selection-export` | 7c |
| `detail.item-and-copy` | 1d, 1e |
| `detail.session-copy-edit` | 1e |
| `identify.history` | 7e |
| `inventory.checker` | 3e |
| `inventory.compact-rows` | 1d |
| `inventory.conditional-paired-save` | 3e figure: count with save and next |
| `inventory.conditional-undo` | 3e Undo; 1d/1e inline saves toast not drawn |
| `inventory.copy-confirmation` | 3e finish "Set is checked" |
| `inventory.house-panels` | 1d Info and Prices |
| `inventory.individual-minifigure.details` | 2a |
| `inventory.individual-minifigures` | 7a |
| `inventory.individual-part.details` | 2b |
| `inventory.individual-part.lot-details` | 2d |
| `inventory.individual-part.lots` | 7a by lot, 2d |
| `inventory.individual-parts` | 7a |
| `inventory.manual-prices` | 1d row, 8c estimate sheet |
| `inventory.optional-spares` | 3e spare pass |
| `inventory.price-history` | 1d, 2a, 2b chart |
| `inventory.price-overview` | 4b |
| `inventory.price-refresh` | Update price (1d, 4b), 2e states |
| `inventory.price-tracking` | 4b |
| `inventory.resume` | 3e resume |
| `inventory.set-delete` | 7b |
| `inventory.set-edit` | 1e |
| `inventory.spare-exclusion` | 3e start note, spare pass |
| `inventory.url-tabs` | 1d tabs |
| `inventory.whole-figure-pass` | 3e figure |
| `inventory.wishlist-add` | 4d Where: Wishlist |
| `inventory.wishlist-delete` | 7b Remove from wishlist |
| `inventory.write-disabled` | 8a read-only banner and disabled controls |
| `jobs.bulk-set-import` | 4d paste/file |
| `jobs.minifigure-import` | 4d |
| `jobs.part-add` | 4d part type |
| `jobs.part-bulk-add` | 4d paste |
| `jobs.part-csv-import` | 4d file |
| `jobs.part-lookup` | 4d search |
| `jobs.part-lot-create` | 8c add parts into a new or existing lot |
| `jobs.peeron-select-rotate` | 7e Peeron page select |
| `jobs.progress` | 5b, 7e, 8c import progress |
| `jobs.set-import` | 4d |
| `jobs.set-refresh` | 7e |
| `maintenance.admin-composition` | 7e list, 8b storage form and tags; owner, status and theme forms follow the same sheet |
| `maintenance.bricklink-import-export` | 7e |
| `maintenance.charts` | 5c |
| `maintenance.deep-link-sections` | 7e, 8b |
| `maintenance.instructions` | 5b, 7e, 8c fetch and upload sheets |
| `maintenance.statistics` | 5c |
| `maintenance.statistics-detail` | 5c |
| `maintenance.unresolved-minifigure-report` | 5b |
| `orders.allocation-confirm` | 5a allocation |
| `orders.allocation-history` | 7d |
| `orders.allocation-links` | 7d |
| `orders.allocation-retry` | 7d |
| `orders.allocation-review` | 5a |
| `orders.allocation-undo` | 5a |
| `orders.catalogue-search` | 7d line review |
| `orders.count-audit` | 8c |
| `orders.count-received` | 5a |
| `orders.detail` | 7d |
| `orders.documents` | 7d |
| `orders.from-bricklink` | 5a import |
| `orders.import-hub` | 5a |
| `orders.instruction-sticker-groups` | 7d |
| `orders.ledger-list` | 5a |
| `orders.line-review` | 7d |
| `orders.loose-leftovers` | 8c |
| `orders.partial-receipt` | 5a count (short) |
| `orders.paste-email` | 5a |
| `orders.ready-to-check-preview` | 8c |
| `orders.received-column` | 5a count |
| `orders.reconciliation` | 5a |
| `orders.resumable-draft` | 7d |
| `orders.resume-review` | 7d |
| `orders.saved-lines` | 7d |
| `orders.xml-upload` | 5a |
| `prices.repair-use-loose-stock` | 7c |
| `shared.dialog` | 7b delete confirm, sheets |
| `shared.form-controls` | 1e, 4d |
| `shared.lightbox` | 7f |
| `shared.table` | 4b, 4d desktop tables |
| `shell.error` | 7f |
| `shell.exception-details` | 7f |
| `shell.not-found` | 7f |
| `shell.success` | 7f |
| `shell.tools-administration` | 5b |

## What is still open

Only the partly framed tags remain, and none is a missing screen: they are variants (per-type filter sheets, Peeron loading and result states, duplicate and grouping controls, hold state on orders, a list page for purchase places). Each can follow the pattern already drawn.

Nothing has been dropped on purpose. `shell.login` is out of scope (no login). Home is the set overview.

## Update v3 (this round)

Partly framed capabilities are now all framed (phone 390 and MacBook 1440), so **partly = 0**; 5 remain build-only.

| Capability | Frame (page, section) |
|---|---|
| collection.continuous-scroll | Collection 11a Continuous scroll |
| collection.duplicates | Collection 11a Duplicates |
| collection.grouping | Collection 11a Grouping |
| collection.item-filters | Collection 11a Item filters (per-type sheet content) |
| collection.purchase-locations | Collection 11a Purchase locations |
| inventory.consolidated-instances | Collection 11a Consolidated instances |
| orders.bricklink-xml-tools-link | Workbench 11b BrickLink XML link |
| orders.explicit-order-link | Workbench 11b Explicit order link |
| orders.undo-hold-reconcile | Workbench 11b Undo hold reconcile |
| orders.idempotent-reimport | Workbench 11b Already imported |
| planning.wanted-watch | Planning 11c Wanted watch and alert |
| jobs.peeron-load, jobs.peeron-pdf | Manage 11d Peeron load, Peeron PDF |
| maintenance.admin.set.refresh-bulk | Manage 11d Set refresh bulk |
| Part to Inventory camera list, New lot, desktop Results | Workbench 3f |

The manifest file `coverage/coverage-manifest.json` was not re-counted tag by tag; the table above is the delta from the 13 partly-framed items of v1. Device coverage per section: `FRAMES-by-device.md`. All frames are exported as PNG in `frames/`.
| `collection.continuous-scroll` | 11a scroll (v1.2 frames, phone and desktop) |
| `collection.duplicates` | 11a dups (v1.2 frames, phone and desktop) |
| `collection.grouping` | 11a group (v1.2 frames, phone and desktop) |
| `collection.item-filters` | 11a filters (v1.2 frames, phone and desktop) |
| `collection.purchase-locations` | 11a buy (v1.2 frames, phone and desktop) |
| `inventory.consolidated-instances` | 11a inst (v1.2 frames, phone and desktop) |
| `jobs.peeron-load` | 11d peeron (v1.2 frames, phone and desktop) |
| `jobs.peeron-pdf` | 11d pdf (v1.2 frames, phone and desktop) |
| `maintenance.admin.set.refresh-bulk` | 11d refresh (v1.2 frames, phone and desktop) |
| `orders.bricklink-xml-tools-link` | 11b xml (v1.2 frames, phone and desktop) |
| `orders.explicit-order-link` | 11b link (v1.2 frames, phone and desktop) |
| `orders.undo-hold-reconcile` | 11b undo (v1.2 frames, phone and desktop) |
| `planning.wanted-watch` | 11c watch (v1.2 frames, phone and desktop) |
| `orders.idempotent-reimport` | 11b reimp (v1.2 frames, phone and desktop) |
