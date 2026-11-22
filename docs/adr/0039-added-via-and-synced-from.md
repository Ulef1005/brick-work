# 0039. Where a row came from: `added_via` and `synced_from`

- **Status:** proposed (accepted when the pull request for #551 merges)
- **Date:** 2026-11-22
- **Decided by:** Ulf, issue #551 ("File it in N, parent of #531 (Recommended)", 2026-11-20; "Source detail (Recommended)" for the list names). The storage shape below is the build's proposal, open for review in the pull request.

## Context

Milestone N brings rows in from four sites and several file formats. A person needs to see how a copy, a loose-stock row or a wish arrived, filter by it, and undo exactly what one sync run did. Until 4.7 a copy records only where its *part list* came from (`inventory_source`); nothing records how the row itself arrived, and stock rows and wishes have no source at all. The approved frames (N2-20, N2-21) show two separate facts: **Added via**, one value that never changes, and **Last synced from**, the site, its lists and the date of the last match. A set added by hand can be matched by a later sync, and a set can sit in two Rebrickable lists.

## Options considered

1. **A column per row plus a child table** — `added_via` on `copy`, `stock` and `wish`; `synced_from` with one row per row, site and list. Reads are one join; a set in two lists is two rows.
2. **Columns only** (`added_via`, `last_synced_site`, `last_synced_at`) — cheaper, but one site and one list per row, against the frames and #531.
3. **Derived from the event log** — no new storage, but every list read would scan events, and rows older than the log have no answer.

For the allowed values: a `CHECK(... IN (...))` on the column, or a lookup table `origin` that the column references. SQLite cannot change a CHECK without rebuilding the table, so each new file format (BrickEconomy CSV, #474) would cost a table rebuild of `copy`; a lookup table takes one `INSERT` in a later step.

Recommendation: option 1, with the lookup table.

## Decision

- Schema 4.7 → 4.8, additive (`brickwork/store4/added_via.sql`).
- `origin(id, kind)`: `hand`; the sites `rebrickable`, `brickset`, `bricklink`, `brickowl`; the files `bricklink_xml`, `rebrickable_csv`, `brickset_csv`, `brickowl_xml`, `brickwork_export`; and the one import from another app (its value names that app, as the importer module does).
- `copy.added_via`, `stock.added_via`, `wish.added_via` reference it. NULL is a row older than 4.8 and reads **Before this release**. A trigger refuses any change, so the value is fixed from creation. A kind move (set ↔ box and the like) carries the value to the new row.
- Every route writes `origins.current()`: `hand` (the app, the API, MCP and the CLI), or the origin a sync run, file import or the import from another app opens with `origins.adding(...)` around its writes. A test fails when a new `INSERT` of one of these rows leaves the column out.
- `synced_from(copy_id | stock_id | wish_id, site, list_key, list_name, synced_at)`: exactly one row reference, one row per site and list (`list_key` '' for the site's collection as a whole). A pull touches every live copy, set-like stock row and wish of the linked list whose item the site holds, made by this pull or not; its receipt keeps a compact entry per touched row and its Undo takes them back, leaving a row a later run touched again.
- API v2 serves both read only as `source` on `Copy`, `Stock` and `Wish` (`RowSource`); MCP reads the same bodies.

## Consequences

- An older version cannot open a 4.8 file, as with every schema step; the way back is the backup. Every existing row stays NULL.
- The UI (the Added via chip, the Last synced from line, the Source filter on Sets and the stock lists) is built with the page rebuilds of milestone N, on this data.
- #531 fills `list_key` and `list_name` from the Rebrickable set lists, and renames them with `origins.rename_list`.
- A sync that matches thousands of rows writes as many `synced_from` updates and receipt entries (about 60 bytes each).
- Reversible: drop the three columns, the triggers, `synced_from` and `origin`, and nothing else reads them.

## Links

Issue #551, #531, #489 ([ADR 0038](0038-checked-by.md) for the pattern of an additive step), [Sync with Rebrickable](../how-to/sync-collection.md).
