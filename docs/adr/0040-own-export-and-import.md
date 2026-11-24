# 0040. Brick Work's own export and import

- **Status:** proposed (accepted when the pull request for #524 merges)
- **Date:** 2026-11-23
- **Decided by:** the shape in #524 (a versioned file with a manifest, a choice of what to include, a preview, a choice per conflict, one Undo; catalogue data and secrets out) is Ulf's, 2026-11-19. The cut to a first version and everything below the Decision heading are the build's proposal, open for review in the pull request. A design review (Fable 5.2, 2026-11-23) found that the first draft of this ADR could not be written back to the store; the Decision answers each finding.

## Context

**Export database** gives the whole SQLite file: complete, but unreadable without tools, and it carries the catalogue, caches and secrets. #470 gives the owned rows as a spreadsheet that cannot be read back. A person who moves to another install, shares a collection or wants a readable archive has no way to do it.

The store has two kinds of ids. `copy`, `stock`, `lot`, `storage`, `place`, `flag`, `wishlist` and `wish` have text uuids. Everything else a first draft wanted to include (orders and their lines, allocations, part lines, figure lines, stock transfers, part checks) has integer ids that other rows and JSON columns refer to (`part_check.session_json` by `copy_part.id`, `stock_transfer` by an event). Items and colours have install-specific integer ids and are not always named by a provider key: unidentified items have none, and local items and colours (ids from 1e9) exist only here.

## Options considered

1. **One zip of JSON Lines**, a file per table, with a manifest. Readable, streamable, versioned.
2. **A zip of CSV files.** Readable in a spreadsheet, but typed and nested fields flatten badly.
3. **A SQLite file with the user tables only.** Simple to restore, unreadable, tied to one schema.

Recommendation: option 1; the CSV files of #470 are the readable form and may be added inside later.

## Decision

**Version 1 is add-only and small.** The file carries what the store can rebuild through its own writers: storage and places (parents first), flags, lots, **copies**, **loose stock**, wishlists and wishes. Orders, allocations, part checks, stock transfers, prices and photos are left out of version 1 and each follows as its own section with its own id mapping; the manifest names the sections present, so the format grows without a new version.

- **File:** `brickwork-export-<date>.zip` with `manifest.json` and `data/<table>.jsonl`; readable CSV copies may follow as `csv/` and are never read back. Manifest: `format` (`brickwork-export`), `format_version` (1), `schema`, `created_at`, `sections`, `counts`. An import refuses a newer `format_version` and reads every older one.
- **Naming items and colours:** every reference carries `provider`, `namespace`, `key`, `kind` and the name, as `store4.identity` reads them. An item with no key or a local item or colour is written in full (name, kind, number text) and is **unresolved** on import unless this install has a local item of the same name and kind that the person confirms. Nothing is guessed.
- **Copies are rebuilt, not copied.** The import calls the store's own `create_copy_in` (version 1 gives the copy this install's own preselected part list, since the file names the source of the list, not its version), then applies the file's marks (checked, missing, damaged, spare, per line key: figure, item, colour) to the lines it made. Marks on a line this install's list lacks are counted as unmatched and not applied. So `inventory_source`, version, digest, `fetched_inventory_id` and `pending_job_id` are never written from the file, and the table CHECKs hold. Each copy is one transaction step under the import's one receipt. The apply answer counts the lines that did not match.
- **Ids and conflicts.** Uuids are kept when free. A row whose id exists here with the same content is **already here** (nothing written). A row whose id exists with different content is a **difference**, reported and left alone: version 1 never overwrites. **Add as new** gives the row a new uuid and re-keys its children. A different id that hits a unique key (`stock_merge_key`, `wish_live_key`, storage `short_id`, the seeded `default` wishlist, flags by name) is matched to the existing row, and the preview says so.
- **A copy carries `checked_by`** (the word for who checked it, such as `rebrickable`): the store reads a copy as checked from the flag, the line marks or this column (ADR 0038), so the file keeps all three.
- **Left out of every file:** catalogue and projected item data, fetched inventories, pictures, `source_key`, `api_token`, settings that name a secret, jobs, sync receipts, events, `wishlist.bricklink_id`, `storage.short_id` labels' print state and other install-specific or personal fields.
- **Undo.** The import writes through the row log under one `import` plan receipt with the origin `brickwork_export` (schema 4.8, #595). Undo takes back exactly the rows that run made, and refuses by name when one of them changed after the import, as the other imports do.
- **Order of writes:** storage and places (parents first), flags, lots, wishlists, copies with their lines, stock, wishes, then the flag links. A row whose parent is unresolved is unresolved too.
- **Surfaces:** `GET /export/brickwork.zip?sections=…` (read); `POST /imports/brickwork/plan` and `/apply` (write, as the sync routes); `brickwork export-all` and `brickwork import-file`; `brickwork import-file --apply`. Applying is admin work, so there is no MCP tool (admin work is never a tool). The page belongs to #523.

## Consequences

- Needs no schema change beyond 4.8. This lands after #595.
- A file is not a backup: events, the catalogue build, orders and secrets are not in it. The how-to says so and points at **Export database**.
- Because copies go through `create_copy_in`, an import of a large collection is as slow as adding the copies one by one; the plan shows the count first.
- A later section for orders needs an integer-id mapping table in the plan; that is its own decision.

## Open for review

1. Whether lots, stock and wishes are enough for the first version, or copies alone.
2. Whether a difference should be reported only (the proposal), or also offer **Take the file's** for a plain field of a copy or stock row once Undo keeps before-images.
