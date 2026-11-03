# Brick Work API v1: contract

**Retired (M.11d, issue #113).** On the 4.0 line every v1 path answers `410 Gone` and names v2, except `GET /health`; the API is [api-v2.md](api-v2.md). This file stays as the reference for what v2 inherits. The modules it names as backing (`core.api_reads`, `core.api_writes`, `core.api_jobs`, `core.api_orders`, `core.api_pages`, `api/operations.py`, `api/reads.py`, `api/writes.py`, `api/sync.py`) are gone.

**Status:** decisions accepted 2026-10-15; M0 foundations, M1 transport, M2 GET operations, M3 collection writes, M4 checker and manual-price writes, M5 jobs, sources, the encrypted key store and uploads, M6 orders and the full Undo dispatcher, and M7 MCP implemented in 4.11b–4.11i. M8 cutover and M9 standalone smoke shipped in 4.11j. The machine-readable twin is [openapi-v1.yaml](openapi-v1.yaml).

**How to read this file.** Every claim about existing code names the file it came from (`brickwork/core/...`, `brickwork/web/...`; paths below drop the `brickwork/` prefix). **NEW** records an endpoint or helper introduced by the v1 plan; the implemented operation table and OpenAPI `x-milestone` markers show what is now implemented. "Backing" is the function an endpoint wraps. This contract records accepted behaviour; milestone entries distinguish implemented foundations from planned endpoints.

---

## 0. Standalone implementation

The sole API blueprint is `brickwork/api/`, mounted at `/api/v1`, and it reads and writes only `brickwork.db` through `core/connect.py`. The replaced web API, legacy screens, stores and external refresh integration were removed in 4.11j. Earlier ids do not carry over: copy ids are the UUIDs in `copies.id`.

The browser, CLI and MCP use the same core functions listed below. Browser routes have no legacy prefix; [the cutover table](cutover-4.11j.md) records every changed path and its backing function. There are no redirects. The one retained legacy reader is `core/importer/`, exposed as **Import from BrickTracker** through Tools & Admin and `brickwork import-bricktracker` (rewritten on Rebrickable numbers in M.8j; the old migrate command is gone). The input is read-only.

Lists use the shared filter/paging service. API writes capture core receipts in one transaction and one event with `via=api` and the calling token name in `actor`. Schema 3.3, scoped tokens, encrypted keys, archive semantics and price preferences are implemented. The historical 3.2 initialization and upgrade mapping remain for existing databases and migration proofs.

---

## 1. Principles

| # | Rule |
|---|---|
| P1 | **Versioned path** `/api/v1`. Breaking changes ship as `/api/v2`; v1 keeps working through the deprecation window (section 9). |
| P2 | **JSON only** (`application/json`; errors `application/problem+json`). Exceptions, all explicit in the tables: file downloads (PDF, images, XML, SQLite snapshot) and multipart uploads (instruction PDFs, own photos and identification images). |
| P3 | **Own token** `BW_API_TOKEN` plus scoped tokens: `read`, `write`, `admin` (section 2.9). No private-client names, tokens, hosts or routes in the app. |
| P4 | **Stable ids.** Catalogue items are addressed by BrickLink-canonical `(item_type, item_no)` (`/items/{type}/{no}`), as in `items` PK. Owned things have surrogate ids: copies, stock lines, lots, storages, places, flags are UUID text (`copies.id` etc.); wishes, instruction files, orders, jobs, events, images are integers. |
| P5 | **Every write is one transaction and one `events` row** with `via='api'`, `actor` equal to the token name, and is undoable through the same Undo as the web (`POST /events/{id}/undo`). Every write response carries `event_id` and `undo_url`. Operations that cannot be undone say so in their table row. |
| P6 | **Idempotent writes** through the client's `Idempotency-Key`, stored in `events` like the checker's `operation` id (section 2.7). Required on creates and quantity moves. |
| P7 | **Archive, do not delete.** `DELETE` on copies, stock, wishes, lots, storages, places and flags archives (`archived_at`) and `POST .../restore` reverses it. Places and flags retain all references; Undo clears the archive mark. |
| P8 | **Errors are problem+json** (RFC 9457) with a stable `code` (Appendix A). Messages are for humans; clients switch on `code`. |
| P9 | **Pagination and filters use the web lists' vocabulary** (section 2.5), cursor based, default 50, maximum 200. |
| P10 | **Optimistic concurrency** with `ETag` / `If-Match` on single-record updates of copies, stock, wishes. |
| P11 | **No secrets ever leave the API.** Key status contains only `configured`, `origin` (`env`/`stored`) and `saved_at`; key values and fragments never leave the app. Error text is passed through `sources.base.redact`, as the CLI and web already do. Source budgets are shown, key values never. |
| P12 | **Thin transport.** Handlers parse, authorise, call one service function, serialise. No SQL in handlers; the service functions are the ones named in the tables. |

---

## 2. Conventions

### 2.1 Identity and addressing

| Thing | Address | Notes |
|---|---|---|
| Item | `{type}/{no}` | `type` is one of `S M P I O G B C ?` (`items.item_type` CHECK). `no` matches `[A-Za-z0-9-]{1,32}` (`add.lookup`). `?` is a supported placeholder type. |
| Colour | `color_id` integer | BrickLink colour id; 0 and 117 exist (schema-notes). A part needs a colour (`wishlist` CHECK, `add.validate_edits`); all other types have none. |
| Copy | `copies.id` UUID | One physical set. `POST /copies` with `quantity: 3` creates 3 copies (as `add.confirm`). |
| Stock line | `loose_stock.id` UUID | Identical lines merge (`stock.add_loose`, `stock.merge_edited`); `PATCH` may return `merged_ids`. |
| Wish | `wishlist.id` integer | Key is `(type, no, colour)` among live rows (`wishlist_live_key`). |
| Part line of a copy | `copy_parts.id` integer | Unique across copies; figure components carry `parent_minifig`. |

### 2.2 Value formats

| Value | Format |
|---|---|
| Money | Decimal **string** (`"12.50"`), never a float; `purchase_price`, `current_value`, `max_price`, observation `price/min/max` (schema: TEXT; `collection.save` normalises with `Decimal`). Always with a currency code, `^[A-Z]{3,8}$`. |
| Time | ISO-8601 UTC with offset (`now().isoformat()` in `sources/base.py`). Dates the user types (`purchase_date`) are stored as given; the API accepts ISO-8601 date or date-time. |
| Condition (copies) | `N` new, `U` used. Stock adds `D` damaged (`collection.save` allowed sets). Wishes use `new`, `used`, `any`. The API serialises `new`, `used`, `damaged`; stored codes stay unchanged. |
| Completeness | `sealed`, `complete`, `incomplete` (stored as `S`, `C`, `I`); `completeness_source` `manual` or `derived`. |
| Guide / slot | `guide` in `sold, stock, retail, manual, valuation`; `slot` free text (`boxed`, `estimate` are used by `collection.detail`). Old slots `new, used, bricklink_new, bricklink_used, boxed` (`web/store.py` SLOTS) map to condition plus guide (section 5). |

### 2.3 Envelopes

* Single read: `{"data": {...}}` with `ETag` header on copies, stock, wishes.
* List: `{"data": [...], "page": {"next_cursor": "...|null", "limit": 50, "total": 123|null}}`. `total` is given only when cheap (`archived` filter off, no text search).
* Write: `{"data": {...}, "event_id": 412, "undo_url": "/api/v1/events/412/undo", "idempotent_replay": false}`.
* Action returning a receipt: `{"data": {"event_id": 412, "message": "..."}, "event_id": 412, ...}` (the web already returns `event_id` and `message` from `bw_collection_write`).
* Queued work: `202 Accepted`, the write envelope with the `Job` as `data` (state `queued`, `running` or `waiting_for_budget`), `undo_url: null` (import work is never reversed), header `Location: /api/v1/jobs/{id}`. Retry and resume also start the embedded drainer unless `BW_EMBEDDED_WORKER=0`.

### 2.4 Resource states

Archived rows are hidden from lists; `archived=true|include|only` shows them. Archived instruction-file content returns 404. A `GET` of an archived record returns it with `archived_at` set (the web hides them with `archived_at IS NULL`; the API does not 404 so Undo links keep working). Writes to an archived record fail with `409 archived`.

### 2.5 Pagination, filters, sort

* `cursor` (opaque, from `page.next_cursor`), `limit` 1 to 200, default 50. The web default of 15 per page (wiki Open Questions, "paging question") is a UI setting, not an API one.
* Sort `sort=<key>&direction=asc|desc`, stable tie-break on `number` then id, exactly as `filterRows` (`compare(a,b,'number')`). Keys: `number, name, year, quantity, missing, damaged, used_price, colour`; `missing` sorts by missing plus damaged, descending, as the web.
* Filters (same names and meaning as `filterRows` / `data-bc-filter`): `q` (substring over name, number, colour, category, theme, year), `type`, `condition`, `status` (`sealed complete incomplete unknown`), `storage` (id or `null`), `place` (id or `null`), `flag` (id; the web filters by flag name, the API by id), `lot` (id or `null`), `problem` (`missing|damaged`), `duplicates` (`true|false`), `theme`, `category`, `year`, `colour`, `inventory` (`parts|figures|instructions`). Additions NEW: `item_no`, `archived`, `under_max`, `since`.
* Unknown filter names are `400 unknown_filter`, not ignored.
* NEW: one function `filter_rows(rows, query, filters, sort, direction)` shared by the web payload and the API replaces the JS-only logic's server side. Implemented in `core/listing.py`; `core/list_records.payload` and the API use it, with shared JSON fixtures checked against the browser function. Collection rows use the compact web field vocabulary; future read projections adapt into that vocabulary. Pagination uses a value cursor (sort value, number, id), so inserts before the current page do not repeat or skip existing rows. Cursors are bound to sort, direction and filter signature.

### 2.6 ETag and If-Match

`ETag` is a hash of the record's canonical JSON (copies: the `snapshot` row plus flag ids). `PATCH`/`PUT`/`DELETE` on `/copies/{id}`, `/stock/{id}`, `/wishes/{id}` accept `If-Match`; a mismatch is `412 precondition_failed` and nothing is written. Without `If-Match` the write proceeds (Undo's own guard, "Item changed · undo the later save first" in `collection.undo`, still protects history). NEW: `collection.save` gets an optional `expect` argument checked after `BEGIN IMMEDIATE`, so the check and the write are one transaction.

### 2.7 Idempotency

`Idempotency-Key: <1 to 80 characters of [A-Za-z0-9-]>` (same charset rule as the checker's `operation`).

* **Required** on: `POST /copies`, `/stock`, `/wishes`, `/found`, `/stock/booklets`, `/copies/{id}/take`, `/stock/{id}/give`, `/wishes/{id}/to-owned`, `/orders/documents`, `/orders/{id}/allocate`, `/orders/{id}/allocations/retry`, `/prices/observations`, `/items/{type}/{no}/prices`, `/events/{id}/undo`, `/storages/{id}/contents`, `/copies/{id}/parts/bulk`, `/lots`. A missing key is `428 idempotency_key_required`. Optional elsewhere.
* **M3 receipt** (no new table): exactly one `events` row per request, `entity='bw_api'`, `field='op:<key>'` (or `receipt` without a key). Its `new_value` holds `{method, path, body_sha256, status, response, event_id, token_name, receipts}`. `receipts` embeds the existing core receipt shapes; intermediate audit details are collected without inserting extra rows. This merges the domain and idempotency receipts so the one-event rule holds, including composed operations. The dispatcher passes each embedded receipt to its existing core Undo owner in reverse order. Undo events carry `undone_event_id` and cannot themselves be undone. Public operation values remain redacted.
* **Replay:** same key, same method, path and body hash returns the stored response with `idempotent_replay: true` and the original status. Same key with another body is `409 idempotency_conflict`. A key is honoured for 30 days from the receipt's `at`; after that the same key starts a new operation. The receipt rows stay, because `events` is append-only (triggers `events_no_update`, `events_no_delete`).
* Keys are scoped per token name. M3 uses this single replay mechanism; `add.confirm` receives a private batch identity inside the embedded receipt, rather than persisting a second web replay receipt. Checker operation handling follows in its milestone.

### 2.8 Errors

Media type `application/problem+json`:

```json
{"type":"urn:brickwork:error:validation_failed","title":"Validation failed","status":422,
 "code":"validation_failed","detail":"Enter a price of zero or more",
 "errors":[{"field":"purchase_price","code":"invalid_money","message":"..."}],
 "instance":"/api/v1/copies/3f2a..."}
```

Optional members: `retry_after` (seconds), `job_id`, `source`. Codes and statuses are in Appendix A. A global handler maps: unknown `/api/v1/*` path to `404 not_found` (`api` unknown-route handler), `ValueError` to `422`/`409` by exception class, `SourceError` to `502 source_error` with the redacted public text, `WaitingForBudget` to `202` job or `429` (section 8.3), `sqlite3.Error` to `503 db_unavailable`.

HTTP exceptions preserve their status: 401 maps to `unauthorized`, 403 to `forbidden`, 404 to `not_found`, 405 to `method_not_allowed` with an `Allow` header, 409 to `conflict`, 413 to `payload_too_large`, and 415 to `unsupported_media_type`. Other 4xx exceptions use `bad_request`; 5xx exceptions use `internal_error` with no private detail.

### 2.9 Authentication, scopes, tokens

* Header `Authorization: Bearer <token>`. `X-Web-Token` is not accepted. Transport security (TLS in front of the app, or loopback) is the deployment's job; the API does not add a setting for it.
* **Scopes** (cumulative): `read` < `write` < `admin`. `read`: every `GET` except those marked admin. `write`: collection, stock, wishes, locations, orders, price, job writes. `admin`: settings update, source enable or disable, catalogue import and colour sync, database check and export, token management.
* **Bootstrap token:** `BW_API_TOKEN` (environment) is a single token with scope `admin`, compared with `hmac.compare_digest` as today. If it is unset **and** no stored token exists, the API answers `503 api_disabled` (today: `503 web api disabled`). `/health` stays open.
* **Scoped tokens (NEW, DDL-2 `api_tokens`):** columns `id, name, hash (sha256), scopes, created_at, expires_at, last_used_at, revoked_at`. Token names are unique, trimmed, 1–80 characters; `bootstrap` is reserved. Expiry must be a future timestamp with an explicit timezone. Created by `POST /tokens` (admin) or `brickwork token create --name web --scope read,write [--expires 90d]`, the secret is shown once and only its hash is stored. The environment bootstrap cannot be revoked through the API. A stored token is revoked by `DELETE /tokens/{id}` or `brickwork token revoke`. `last_used_at` is updated at most once a minute. This authentication bookkeeping is not a user mutation and does not emit events. The environment identity is named `bootstrap`.
* **Rotation without downtime:** create the new token, switch the client, check `last_used_at` of the old one, revoke it. Any number of tokens may be valid at once. To rotate `BW_API_TOKEN` itself, set the new value and restart; for a rolling change, create a stored `admin` token first.
* **Read-only instance:** `BW_READ_ONLY` (exists: `config`/`web/views.py` `bw_collection_editable`) makes every non-`GET` return `403 read_only_instance`, whatever the scope.
* **Audit identity:** `events.actor` holds the token name for API writes. It is NULL for web, CLI and import writes; `events.via` distinguishes `app`, `cli`, `api`, `import`, `migration`.

---

## 3. Resource catalogue

### 3.1 Summary

| # | Resource | Base path | Operations | Writes wrap | Ops (NEW) |
|---|---|---|---|---|---|
| 1 | Meta | `/health /version /me` | get | none | 4 (3) |
| 2 | Catalogue | `/catalogue, /colors` | list, get | read-only | 5 (2) |
| 3 | Items | `/items` | list, get, inventory, used-in, colours, images, import (action) | import queues the pipeline | 7 (5) |
| 4 | Images | `/images/{id}/content` | download | read-only | 1 (0) |
| 5 | Copies | `/copies` | list, get, create, update, archive, restore, flags, pin, completeness, checked, check session, gaps, matches, take (action) | collection.save, add.confirm, planning.save, checker.write, workbench.take_for_gap | 16 (6) |
| 6 | Copy parts | `/copies/{id}/parts, /figures` | list, update (mark missing or found), bulk apply | NEW SQL in checker.write style | 5 (5) |
| 7 | Loose stock | `/stock, /found` | list, get, create, update, archive, restore, flags, parts of a figure, give, booklets, found | stock.add_loose, collection.save, workbench.transfer/booklets/found | 13 (5) |
| 8 | Minifigures | `/minifigures` | list, get | read-only (figures themselves are stock lines or copy figures) | 2 (1) |
| 9 | Matching | `/unresolved, /id-matches, /gaps, /matches` | list, resolve | admin.resolve | 5 (1) |
| 10 | Instructions | `/instruction-files` | list, get, attach (PDF), rename, download | admin.instruction_upload/rename | 5 (2) |
| 11 | Prices | `/prices, /items/{type}/{no}/prices` | list, current, history, record, batch record, refresh (queue), stale | admin.queue_refresh; observation insert is NEW | 8 (3) |
| 12 | Wishlist | `/wishes` | list, get, create, update, archive, restore, flags, to-owned (action) | collection.save, add.confirm | 8 (4) |
| 13 | Storages | `/storages` | list, get, create, rename, archive, move contents (action) | ledger.* | 6 (0) |
| 14 | Lots | `/lots` | list, get, create, update, archive | collection.new_lot/save | 5 (1) |
| 15 | Places | `/places` | list, create, rename, archive | admin.value_write | 4 (0) |
| 16 | Flags | `/flags` | list, create, rename, archive | admin.value_write | 4 (0) |
| 17 | Planning | `/planning/ranking, /export/missing.xml` | get, export | read-only | 2 (0) |
| 18 | Orders | `/orders` | list, get, import document, match line, hold, phase, received, allocate, reconcile, short XML | orders.* | 10 (0) |
| 19 | Events | `/events` | list, get, undo (action) | NEW dispatcher | 3 (3) |
| 20 | Jobs | `/jobs` | list, get, retry, resume, drain, queue identities, queue pictures | Pipeline.*, admin.queue_* | 7 (1) |
| 21 | Sources | `/sources, /catalogue/import, /colors/sync` | list, enable or disable, import catalogue, sync colours | admin_ops.tools_write | 6 (2) |
| 22 | Settings | `/settings` | get, update (whitelist) | admin.save_settings, admin_ops.settings_set | 2 (1) |
| 23 | Admin | `/statistics, /database, /identifications` | statistics, check, export, identification history | admin.* | 8 (4) |
| 24 | Tokens | `/tokens` | list, create, revoke | NEW | 3 (3) |
| | **Total** | | | | **139 (52)** |

"Ops (NEW)" is operations in the group, with the number that need new code in brackets. Of the 52 NEW operations, 41 have no existing function at all (backing starts with **NEW**) and 11 wrap an existing read or write but add a new part (server-side filter and paging, or an extra field set), which the Backing column names.

### 3.2 Operations

Scope `none` means no token. Every path is relative to `/api/v1`. Write rows are one transaction plus one `events` row; the receipt kind and Undo function per write group are in section 4.

#### Meta

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /health` | Liveness, app, schema and API version. No token. | none | core.api_reads.health (core database only) |
| `GET /version` | Build, API and schema versions, enabled features. | read | **NEW** (reads schema_meta, __version__) |
| `GET /openapi.yaml` | This contract as OpenAPI 3.1 YAML. No token. | none | **NEW** (serves docs/brickwork/openapi-v1.yaml) |
| `GET /me` | The calling token: name, scopes, expiry. | read | **NEW** |

#### Catalogue

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /catalogue/items` | Search the local BrickLink catalogue file by type and text. | read | brickwork/add.py search; paging NEW (**NEW** parts as noted) |
| `GET /catalogue/items/{type}/{no}` | One catalogue entry. | read | brickwork/add.py lookup |
| `GET /catalogue/status` | Catalogue file state (loaded, item counts, imported_at). | read | web/admin_ops.py catalogue_status |
| `GET /colors` | All colours. | read | brickwork/add.py colors |
| `GET /colors/{color_id}` | One colour. | read | **NEW** (SELECT on colors) |

#### Items

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /items` | Items known to the store, with text search over name, number and properties. | read | **NEW** (items + search_index FTS) |
| `GET /items/{type}/{no}` | Item detail: properties, counts, owned and wished summary. | read | brickwork/collection.py detail (trimmed) |
| `GET /items/{type}/{no}/inventory` | Parts and figures the item is made of (inventory lines). | read | **NEW** read (inventory_lines; shape from collection.detail consists) |
| `GET /items/{type}/{no}/used-in` | Owned copies that contain this part or figure. | read | brickwork/collection.py detail (used_in) |
| `GET /items/{type}/{no}/colors` | Colours this part is known in. | read | **NEW** (replaces web/store.py part_colors) |
| `GET /items/{type}/{no}/images` | Local pictures of the item. | read | **NEW** read (item_images) |
| `POST /items/{type}/{no}/import` | Create the item identity and queue the six import steps. | write | core.api_jobs.queue_item / core.add.lookup / core.pipeline.Pipeline.queue_steps |

#### Images

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /images/{id}/content` | Image bytes from the local picture store. | read | web/views.py bw_image |

#### Copies

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /copies` | Owned set copies. | read | brickwork/collection.py listing + instances; server-side filter and paging NEW (**NEW** parts as noted) |
| `POST /copies` | Add owned copies of a set (quantity N makes N copies) and queue its import. | write | brickwork/add.py confirm (where=owned); storage and purchase fields NEW (**NEW** parts as noted) |
| `GET /copies/{id}` | One copy. | read | brickwork/collection.py detail(copy_id) |
| `PATCH /copies/{id}` | Edit condition, completeness, storage, purchase and estimate fields, note. | write | brickwork/collection.py save(entity=copy) |
| `DELETE /copies/{id}` | Archive the copy (the UI calls this deleting a set). | write | brickwork/collection.py save(archive=True) |
| `POST /copies/{id}/restore` | Clear the archive mark. | write | **NEW** (no function; receipt in collection.py style) |
| `PUT /copies/{id}/flags` | Replace the copy flags. | write | brickwork/collection.py save(flags=[...]) |
| `PUT /copies/{id}/pin` | Pin or unpin a copy. | write | brickwork/planning.py save(action=pin) |
| `GET /copies/{id}/completeness` | Stored and derived completeness, checked flag, missing and damaged counts. | read | brickwork/completeness.py derived_state + checker.py header; composition NEW (**NEW** parts as noted) |
| `PUT /copies/{id}/checked` | Set or clear the "Set is checked" flag and recompute derived completeness. | write | **NEW** (extracted from checker.py write, action finish) |
| `GET /copies/{id}/check` | Part-check session state for this copy. | read | brickwork/checker.py view |
| `POST /copies/{id}/check` | Apply one part-check action (start, answer, found_one, skip, select, back, next, spares, finish, undo). | write | brickwork/checker.py write (Idempotency-Key = its operation id) |
| `GET /copies/{id}/gaps` | Missing, damaged and absent items of the copy. | read | brickwork/workbench.py gaps (filtered) |
| `GET /copies/{id}/matches` | Loose stock that would fill the copy gaps. | read | brickwork/workbench.py matches (filtered) |
| `POST /copies/{id}/take` | Take N of one missing part (with colour) or whole minifigure (no colour) from loose stock into the copy. | write | brickwork/workbench.py take_for_gap |

| `POST /copies/{id}/photos` | Upload an own photo (multipart, 15 MB). | write | brickwork/collection.py photo |

#### Copy parts

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /copies/{id}/parts` | Part lines of the copy (required, spare, figure components). | read | **NEW** read (copy_parts; shape from collection.detail consists) |
| `PATCH /copies/{id}/parts/{part_id}` | Set missing, damaged, checked for one line (mark missing or found). | write | **NEW** (SQL of checker.py write answer; recompute via workbench.py recompute) |
| `POST /copies/{id}/parts/bulk` | Apply missing counts to many lines by item and colour (mode set or add, optional dry run). | write | **NEW** (replaces web/store.py apply_missing_parts) |
| `GET /copies/{id}/figures` | Whole figures of the copy. | read | **NEW** read (copy_minifigs; shape from collection.detail) |
| `PATCH /copies/{id}/figures/{type}/{no}` | Set the missing count of one whole figure. | write | **NEW** (SQL of checker.py write, figure token) |

#### Loose stock

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /stock` | Loose stock lines (parts, minifigures, booklets, anything). | read | brickwork/collection.py listing + instances; server-side filter and paging NEW (**NEW** parts as noted) |
| `POST /stock` | Add loose stock; identical lines merge. | write | brickwork/stock.py add_loose via add.py confirm (where=loose) |
| `GET /stock/{id}` | One stock line. | read | brickwork/collection.py detail(stock_id) |
| `PATCH /stock/{id}` | Edit a stock line (may merge into an existing line; response lists merged ids). | write | brickwork/collection.py save(entity=stock) + merge_result |
| `DELETE /stock/{id}` | Archive the line. | write | brickwork/collection.py save(archive=True) |
| `POST /stock/{id}/restore` | Clear the archive mark. | write | **NEW** |
| `PUT /stock/{id}/flags` | Replace the line flags. | write | brickwork/collection.py save(flags=[...]) |
| `GET /stock/{id}/parts` | Parts of a loose minifigure. | read | **NEW** read (loose_minifig_parts) |
| `PATCH /stock/{id}/parts` | Set missing and damaged on parts of a loose minifigure. | write | **NEW** |
| `POST /stock/{id}/give` | Give N from this line to a copy gap or a loose-figure part gap. | write | brickwork/workbench.py transfer |
| `POST /stock/booklets` | Add loose booklets from lines "set number, quantity". | write | brickwork/workbench.py booklets |
| `POST /found` | Record found parts into copies, a loose line, or a list. | write | brickwork/workbench.py found |

| `POST /stock/{id}/photos` | Upload an own photo (multipart, 15 MB). | write | brickwork/collection.py photo |

#### Minifigures

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /minifigures` | Figures by identity: owned in sets, loose, missing. | read | brickwork/collection.py listing(kind=M); paging NEW (**NEW** parts as noted) |
| `GET /minifigures/{no}` | One figure: sets, loose lines, missing, matches, prices. | read | brickwork/collection.py detail(kind=M) |

#### Matching

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /unresolved` | Identities needing a manual decision, with candidates. | read | brickwork/admin.py unresolved |
| `POST /unresolved/resolve` | Choose a candidate (or none) for one unresolved identity. | write | brickwork/admin.py resolve |
| `GET /id-matches` | Source identifier to BrickLink identity matches. | read | **NEW** read (id_match) |
| `GET /gaps` | Missing items over all copies and loose figures. | read | brickwork/workbench.py gaps |
| `GET /matches` | Suggestions: loose stock that fills a gap. | read | brickwork/workbench.py matches |

#### Instructions

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /instruction-files` | Booklet files and booklet identities with coverage. | read | web/admin_ops.py tools_read(instructions); paging NEW (**NEW** parts as noted) |
| `GET /instruction-files/{id}` | One file record. | read | **NEW** (SELECT) |
| `POST /instruction-files` | Attach a PDF (multipart, up to 20 MB) to an item. | write | brickwork/admin.py instruction_upload |
| `PATCH /instruction-files/{id}` | Rename the label. | write | brickwork/admin.py instruction_rename |
| `GET /instruction-files/{id}/content` | Download the PDF. | read | web/views.py bw_instruction_download |

#### Prices

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /prices` | Current price per item, colour, condition and guide. | read | **NEW** read (price_current joined to price_observations) |
| `GET /items/{type}/{no}/prices` | Current prices and recorded observations of one item. | read | brickwork/collection.py prices + decorate_prices |
| `GET /items/{type}/{no}/prices/history` | Observation history of one item. | read | brickwork/collection_prices.py history |
| `POST /items/{type}/{no}/prices` | Record one manual or valuation observation. | write | **NEW** (insert into price_observations/price_current + event; replaces web/store.py record_fetched_price) |
| `POST /prices/observations` | Record up to 500 observations in one transaction. | write | **NEW** (replaces PUT /part-prices) |
| `POST /items/{type}/{no}/prices/refresh` | Queue a market price refresh for one item. | write | core.api_jobs.queue_item / core.pipeline.Pipeline.queue_steps |
| `GET /prices/stale` | Items whose price is older than the freshness rule. | read | brickwork/admin.py stale_prices |
| `POST /prices/refresh` | Queue refresh jobs for every stale item. | write | web/admin_ops.py tools_write(refresh) = admin.queue_refresh(stale_prices) |

#### Wishlist

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /wishes` | Wishlist rows; under_max filters to rows priced under the wish maximum. | read | brickwork/collection.py listing(wishes=True) + planning.py wishes/max_comparison; filter and paging NEW (**NEW** parts as noted) |
| `POST /wishes` | Add a wish (same colour and item adds to the live row on decision=another). | write | brickwork/add.py confirm (where=wishlist); max price fields NEW at creation (**NEW** parts as noted) |
| `GET /wishes/{id}` | One wish. | read | brickwork/collection.py detail(wish_id) |
| `PATCH /wishes/{id}` | Edit quantity, colour, condition, max price and currency, note. | write | brickwork/collection.py save(entity=wish) |
| `DELETE /wishes/{id}` | Archive the wish. | write | brickwork/collection.py save(archive=True) |
| `POST /wishes/{id}/restore` | Restore an archived wish. | write | **NEW** |
| `PUT /wishes/{id}/flags` | Replace the wish flags. | write | brickwork/collection.py save(flags=[...]) |
| `POST /wishes/{id}/to-owned` | Turn a wish into owned copies and archive the wish, one transaction. | write | **NEW** (composition of add.py confirm owned + collection.py save archive; replaces web/store.py wanted_to_owned) |

#### Storages

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /storages` | Active storages with counts, plus the virtual "Not stored". | read | brickwork/ledger.py storages |
| `POST /storages` | Create a storage. | write | brickwork/ledger.py storage_save (id None) |
| `GET /storages/{id}` | Storage with its contents. | read | brickwork/ledger.py storage_detail |
| `PATCH /storages/{id}` | Rename. | write | brickwork/ledger.py storage_save |
| `DELETE /storages/{id}` | Archive; refuses non-empty unless move_to_unstored=true. | write | brickwork/ledger.py storage_archive |
| `POST /storages/{id}/contents` | Move copies, stock and lots into this storage (id "unstored" for none). A lot carries its parts that sit in the lot's own storage, in the same receipt. | write | brickwork/ledger.py move |

#### Lots

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /lots` | Part lots. | read | **NEW** read (lots + stock counts) |
| `POST /lots` | Create a lot from existing stock lines. | write | brickwork/collection.py new_lot |
| `GET /lots/{id}` | Lot with its stock. | read | brickwork/collection.py lot_detail |
| `PATCH /lots/{id}` | Edit name, note, storage, purchase fields. | write | brickwork/collection.py save(entity=lot) |
| `DELETE /lots/{id}` | Archive the lot. | write | brickwork/collection.py save(entity=lot, archive=True) |

#### Places

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /places` | Purchase locations with counts and totals per currency. | read | brickwork/collection.py purchase_places |
| `POST /places` | Create a purchase location. | write | brickwork/admin.py value_write(add) |
| `PATCH /places/{id}` | Rename. | write | brickwork/admin.py value_write(rename) |
| `DELETE /places/{id}` | Archive, retaining references. Undo restores the place. | write | brickwork/admin.py value_write(delete) |

#### Flags

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /flags` | Flags of kind owner, status and tag. | read | brickwork/admin.py value_rows (three groups merged) |
| `POST /flags` | Create a flag. | write | brickwork/admin.py value_write(add) |
| `PATCH /flags/{id}` | Rename. | write | brickwork/admin.py value_write(rename) |
| `DELETE /flags/{id}` | Archive, retaining flag links. Undo restores the flag. | write | brickwork/admin.py value_write(delete) |

#### Planning

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /planning/ranking` | Owned copies ranked by cost to complete, with the repair settings used. | read | brickwork/planning.py ranking |
| `GET /export/missing.xml` | BrickLink wanted-list XML of missing items for chosen copies. | read | core.api_reads.missing / core.planning.export |
| `GET /export/missing.json` | The same missing-item aggregation and eligibility as XML, returned as JSON. | read | core.api_reads.missing / core.planning.export |

#### Orders

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /orders` | Orders with line and receipt state. | read | brickwork/orders.py listing |
| `GET /orders/{id}` | Order with documents and lines. | read | brickwork/orders.py detail |
| `POST /orders/documents` | Import an order document: pasted email, BrickLink XML, or fetch by order number with the user key. | write | brickwork/orders.py import_document |
| `PATCH /orders/{id}/lines/{line_id}` | Match a line to a catalogue identity. | write | brickwork/orders.py match |
| `PUT /orders/{id}/lines/{line_id}/hold` | Hold or release a line. | write | brickwork/orders.py hold |
| `POST /orders/{id}/documents/{doc_id}/phase` | Move a document: review, reopen or save. | write | brickwork/orders.py phase |
| `POST /orders/{id}/received` | Record received counts per line. | write | brickwork/orders.py received |
| `POST /orders/{id}/allocate` | Allocate received lines to copies or stock. | write | brickwork/orders.py allocate |
| `GET /orders/{id}/allocation-review` | Saved lines, available received quantities and current copy-gap destinations, paginated. | read | core.orders.allocation_review |
| `GET /orders/{id}/allocations` | Allocation history, paginated. | read | core.orders.allocation_history |
| `GET /orders/{id}/history` | Ledger receipts from web and API operations, with Undo state, paginated. | read | core.ledger.history |
| `POST /orders/{id}/allocations/retry` | Retry reviewed `chosen` allocations against current counts and gaps. Requires an Idempotency-Key. | write | core.orders.retry_allocations → orders.allocate |
| `POST /orders/{id}/reconcile` | Reconcile the order. | write | brickwork/orders.py reconcile |
| `GET /orders/{id}/short.xml` | BrickLink XML of the still-missing lines. | read | brickwork/orders.py short_xml |

#### Events

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /events` | Audit events, newest first. | read | **NEW** read (events; values redacted) |
| `GET /events/{id}` | One event with old and new values. | read | **NEW** |
| `POST /events/{id}/undo` | Undo a receipt event. One endpoint for all receipt kinds. | write | **NEW** dispatcher over collection.py undo, workbench.py undo, ledger.py undo, add.py undo, planning.py undo, part_inventory.py undo |

#### Jobs

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /jobs` | Import and refresh jobs with steps. | read | brickwork/admin.py jobs / pipeline.py Pipeline.list_jobs |
| `GET /jobs/{id}` | One job. | read | brickwork/pipeline.py status |
| `POST /jobs/{id}/retry` | Retry failed steps (all, or one step). | write | brickwork/pipeline.py Pipeline.queue_retry |
| `POST /jobs/{id}/resume` | Resume an interrupted or budget-waiting job; a failed job needs retry. | write | core/api_jobs.py resume (worker start through the embedded drainer) |
| `POST /jobs/drain` | Run one drain of due jobs in the request worker. | write | brickwork/pipeline.py worker (CLI: brickwork worker) |
| `POST /jobs/instruction-identities` | Queue identity refresh for booklets without a file. | write | brickwork/admin.py queue_missing_booklets |
| `POST /jobs/pictures` | Queue a picture refresh for a scope. | write | brickwork/pictures.py queue |

#### Sources

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /sources` | Sources with key state (configured yes or no), budget, usage today, last success and error. | read | web/admin_ops.py sources_status + tools_read(catalogues) |
| `PATCH /sources/{source}` | Enable or disable a source. | admin | web/admin_ops.py tools_write(source) |
| `POST /catalogue/import` | Rebuild the catalogue file from the configured BrickLink XML directory. | admin | web/admin_ops.py catalogue_import_bricklink; no path parameter |
| `POST /colors/sync` | Pull colours from BrickLink with the user key. | admin | brickwork/sources/bricklink.py sync_colors |

| `PUT /sources/{source}/key` | Store an encrypted source key (replaces a stored one). Write-only. | admin | core/keys.py save using core/secrets.py |
| `DELETE /sources/{source}/key` | Archive stored key; Undo restores it. | admin | core/keys.py archive |
| `POST /sources/{source}/key/test` | One budgeted call with the key in use; the result carries no key material. | admin | core/keys.py check |

#### Settings

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /settings` | Allowed settings and freshness rules. | read | brickwork/admin.py settings + web/admin_ops.py settings_show (v3 settings only) (**NEW** parts as noted) |
| `PATCH /settings` | Update allowed settings (whitelist). | admin | brickwork/admin.py save_settings, web/admin_ops.py settings_set, planning.py save(settings) |

#### Admin

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /statistics` | Counts by completeness, theme, storage, place. | read | brickwork/admin.py statistics |
| `GET /database/check` | Integrity, foreign-key check and row counts. | admin | brickwork/admin.py check |
| `GET /database/export` | SQLite snapshot download. Stored source keys, even encrypted, are removed from the copy; refuses (409) if known plaintext credentials would remain. | admin | web/admin_ops.py tools_export |
| `GET /identifications` | Photo identification history; archived rows hidden. | read | brickwork/admin.py history |

| `POST /identifications` | Upload an image for Brickognize identification (image, up to 8 MB). | write | core/identify.py store with sources/brickognize.py |
| `GET /identifications/{id}` | Identification result. | read | **NEW** service over identifications |
| `GET /identifications/{id}/thumb` | Thumbnail bytes. | read | **NEW** service over local thumbnail |
| `DELETE /identifications/{id}` | Archive identification; Undo restores it. | write | core/identify.py archive |

#### Tokens

| Operation | What it does | Scope | Backing today |
|---|---|---|---|
| `GET /tokens` | Tokens including revoked rows; cursor, limit and direction. Never the secret or hash. | admin | `core.tokens.listing` |
| `POST /tokens` | Create a token. The secret is shown once in this response. | admin | `core.tokens.create` |
| `DELETE /tokens/{id}` | Revoke a token; a second revocation is `409 conflict`. | admin | `core.tokens.revoke` |


---

The implemented M1 to M7 operation table is checked by `scripts/check_api_contract.py` in `scripts/check.sh`; refresh it with `--write` after changing the YAML.

<!-- api-m1:start -->
| Implemented operation | Backing |
|---|---|
| `GET /api/v1/wishlists` | `core.wishlists` |
| `POST /api/v1/wishlists` | `core.wishlists` |
| `PATCH /api/v1/wishlists/{id}` | `core.wishlists` |
| `DELETE /api/v1/wishlists/{id}` | `core.wishlists` |
| `POST /api/v1/wishlists/{id}/restore` | `core.wishlists` |
| `POST /api/v1/wishlists/{id}/transfer` | `core.wishlists` |
| `GET /api/v1/wishlists/{id}/export.xml` | `core.wishlists` |
| `GET /api/v1/wishlists/{id}/export.csv` | `core.wishlists` |
| `GET /api/v1/health` | `core.meta.health` |
| `GET /api/v1/version` | `core.meta.version` |
| `GET /api/v1/openapi.yaml` | `api.get_openapi_yaml` |
| `GET /api/v1/me` | `core.tokens.authenticate` |
| `GET /api/v1/catalogue/items` | `core.api_reads.catalogue` |
| `GET /api/v1/catalogue/items/{type}/{no}` | `core.add.lookup` |
| `GET /api/v1/catalogue/status` | `core.api_reads.catalogue_status` |
| `GET /api/v1/colors` | `core.add.colors` |
| `GET /api/v1/colors/{color_id}` | `core.api_reads.record` |
| `GET /api/v1/items` | `core.api_reads.items / core.collection.properties / core.add.decorate_many` |
| `GET /api/v1/items/{type}/{no}` | `core.api_reads.item / core.collection.detail` |
| `GET /api/v1/items/{type}/{no}/inventory` | `core.api_reads.inventory` |
| `GET /api/v1/items/{type}/{no}/used-in` | `core.api_reads.used_in` |
| `GET /api/v1/items/{type}/{no}/colors` | `core.api_reads.item_colors` |
| `GET /api/v1/items/{type}/{no}/images` | `core.api_reads.images` |
| `POST /api/v1/items/{type}/{no}/import` | `core.api_jobs.queue_item / core.add.lookup / core.pipeline.Pipeline.queue_steps` |
| `GET /api/v1/images/{id}/content` | `core.api_reads.content` |
| `GET /api/v1/copies` | `core.api_reads.entities(entity=copy)` |
| `POST /api/v1/copies` | `core.add.lookup / core.add.validate_edits / core.add.confirm / core.collection.save` |
| `GET /api/v1/copies/{id}` | `core.api_reads.entity(entity=copy)` |
| `PATCH /api/v1/copies/{id}` | `core.collection.save` |
| `DELETE /api/v1/copies/{id}` | `core.collection.save` |
| `POST /api/v1/copies/{id}/restore` | `core.collection.restore` |
| `PUT /api/v1/copies/{id}/flags` | `core.collection.save` |
| `PUT /api/v1/copies/{id}/pin` | `core.planning.save` |
| `GET /api/v1/copies/{id}/completeness` | `core.api_reads.completeness_read / core.completeness.derived_state / core.checker.checked` |
| `PUT /api/v1/copies/{id}/checked` | `core.checker.write / core.completeness.derived_state` |
| `GET /api/v1/copies/{id}/check` | `core.checker.view` |
| `POST /api/v1/copies/{id}/check` | `core.checker.write (Idempotency-Key = its operation id)` |
| `GET /api/v1/copies/{id}/gaps` | `core.workbench.gaps` |
| `GET /api/v1/copies/{id}/matches` | `core.workbench.matches` |
| `POST /api/v1/copies/{id}/take` | `core.workbench.take_for_gap` |
| `GET /api/v1/copies/{id}/parts` | `core.api_reads.child_rows` |
| `PATCH /api/v1/copies/{id}/parts/{part_id}` | `core.checker.write / core.checker.mark_row` |
| `POST /api/v1/copies/{id}/parts/bulk` | `core.checker.write / core.checker.mark_row` |
| `GET /api/v1/copies/{id}/figures` | `core.api_reads.child_rows` |
| `PATCH /api/v1/copies/{id}/figures/{type}/{no}` | `core.checker.write / core.checker.mark_row` |
| `GET /api/v1/stock` | `core.api_reads.entities(entity=stock)` |
| `POST /api/v1/stock` | `core.add.lookup / core.add.validate_edits / core.add.confirm / core.collection.save` |
| `GET /api/v1/stock/{id}` | `core.api_reads.entity(entity=stock)` |
| `PATCH /api/v1/stock/{id}` | `core.collection.save / core.collection.merge_result` |
| `DELETE /api/v1/stock/{id}` | `core.collection.save / core.collection.merge_result` |
| `POST /api/v1/stock/{id}/restore` | `core.collection.restore` |
| `PUT /api/v1/stock/{id}/flags` | `core.collection.save / core.collection.merge_result` |
| `GET /api/v1/stock/{id}/parts` | `core.api_reads.child_rows` |
| `PATCH /api/v1/stock/{id}/parts` | `core.checker.write / core.checker.mark_row` |
| `POST /api/v1/stock/{id}/give` | `core.workbench.transfer` |
| `POST /api/v1/stock/booklets` | `core.workbench.booklets` |
| `POST /api/v1/found` | `core.workbench.found` |
| `GET /api/v1/minifigures` | `core.collection.listing(kind=M)` |
| `GET /api/v1/minifigures/{no}` | `core.api_reads.item / core.collection.detail` |
| `GET /api/v1/unresolved` | `core.admin.unresolved` |
| `POST /api/v1/unresolved/resolve` | `core.admin.resolve` |
| `GET /api/v1/id-matches` | `core.api_reads.resource_rows` |
| `GET /api/v1/gaps` | `core.workbench.gaps` |
| `GET /api/v1/matches` | `core.workbench.matches` |
| `GET /api/v1/instruction-files` | `core.api_reads.resource_rows / core.api_reads.instruction_coverage` |
| `POST /api/v1/instruction-files` | `core.admin.instruction_upload` |
| `GET /api/v1/instruction-files/{id}` | `core.api_reads.record` |
| `PATCH /api/v1/instruction-files/{id}` | `core.admin.instruction_rename` |
| `DELETE /api/v1/instruction-files/{id}` | `core.admin.instruction_archive` |
| `GET /api/v1/instruction-files/{id}/content` | `core.api_reads.content` |
| `GET /api/v1/prices` | `core.api_pages.page / core.collection.decorate_prices` |
| `GET /api/v1/items/{type}/{no}/prices` | `core.api_reads.current_prices / core.api_reads.price_history` |
| `POST /api/v1/items/{type}/{no}/prices` | `core.manual_prices.record / core.sources.base.observation` |
| `GET /api/v1/items/{type}/{no}/prices/history` | `core.api_pages.page` |
| `POST /api/v1/prices/observations` | `core.manual_prices.record / core.sources.base.observation` |
| `POST /api/v1/items/{type}/{no}/prices/refresh` | `core.api_jobs.queue_item / core.pipeline.Pipeline.queue_steps` |
| `GET /api/v1/prices/stale` | `core.admin.stale_prices` |
| `POST /api/v1/prices/refresh` | `core.admin.queue_refresh(core.admin.stale_prices)` |
| `GET /api/v1/wishes` | `core.api_reads.entities(entity=wish)` |
| `POST /api/v1/wishes` | `core.add.lookup / core.add.validate_edits / core.add.confirm / core.collection.save` |
| `GET /api/v1/wishes/{id}` | `core.api_reads.entity(entity=wish)` |
| `PATCH /api/v1/wishes/{id}` | `core.collection.save` |
| `DELETE /api/v1/wishes/{id}` | `core.collection.save` |
| `POST /api/v1/wishes/{id}/restore` | `core.collection.restore` |
| `PUT /api/v1/wishes/{id}/flags` | `core.collection.save` |
| `POST /api/v1/wishes/{id}/to-owned` | `core.add.confirm / core.collection.save` |
| `GET /api/v1/storages` | `core.api_reads.storages / core.ledger.storages` |
| `POST /api/v1/storages` | `core.ledger.storage_save` |
| `GET /api/v1/storages/{id}` | `core.api_reads.storage / core.ledger.storage_detail` |
| `PATCH /api/v1/storages/{id}` | `core.ledger.storage_save` |
| `DELETE /api/v1/storages/{id}` | `core.ledger.storage_archive` |
| `POST /api/v1/storages/{id}/contents` | `core.ledger.move` |
| `GET /api/v1/lots` | `core.api_reads.lots` |
| `POST /api/v1/lots` | `core.collection.new_lot` |
| `GET /api/v1/lots/{id}` | `core.collection.lot_detail / core.api_reads.record` |
| `PATCH /api/v1/lots/{id}` | `core.collection.save` |
| `DELETE /api/v1/lots/{id}` | `core.collection.save` |
| `GET /api/v1/places` | `core.api_reads.places / core.collection.purchase_places` |
| `POST /api/v1/places` | `core.admin.value_write` |
| `PATCH /api/v1/places/{id}` | `core.admin.value_write` |
| `DELETE /api/v1/places/{id}` | `core.admin.value_write` |
| `GET /api/v1/flags` | `core.api_reads.resource_rows` |
| `POST /api/v1/flags` | `core.admin.value_write` |
| `PATCH /api/v1/flags/{id}` | `core.admin.value_write` |
| `DELETE /api/v1/flags/{id}` | `core.admin.value_write` |
| `GET /api/v1/planning/ranking` | `core.planning.ranking` |
| `GET /api/v1/export/missing.csv` | `core.list_exports` |
| `GET /api/v1/export/picker.csv` | `core.list_exports` |
| `GET /api/v1/export/wishlist.csv` | `core.list_exports` |
| `GET /api/v1/export/missing.json` | `core.api_reads.missing / core.planning.export` |
| `GET /api/v1/export/missing.xml` | `core.api_reads.missing / core.planning.export` |
| `GET /api/v1/orders` | `core.orders.listing` |
| `GET /api/v1/orders/export.csv` | `core.order_exports` |
| `GET /api/v1/orders/{id}` | `core.orders.detail` |
| `POST /api/v1/orders/documents` | `core.orders.import_document` |
| `PATCH /api/v1/orders/{id}/lines/{line_id}` | `core.orders.match` |
| `PUT /api/v1/orders/{id}/lines/{line_id}/hold` | `core.orders.hold` |
| `POST /api/v1/orders/{id}/documents/{doc_id}/phase` | `core.orders.phase` |
| `POST /api/v1/orders/{id}/received` | `core.orders.received` |
| `POST /api/v1/orders/{id}/allocate` | `core.orders.allocate` |
| `POST /api/v1/orders/{id}/reconcile` | `core.orders.reconcile` |
| `GET /api/v1/orders/{id}/short.xml` | `core.orders.short_xml` |
| `POST /api/v1/orders/{id}/allocations/retry` | `core.orders.retry_allocations` |
| `GET /api/v1/orders/{id}/allocation-review` | `core.orders.allocation_review` |
| `GET /api/v1/orders/{id}/allocations` | `core.orders.allocation_history` |
| `GET /api/v1/orders/{id}/history` | `core.ledger.history` |
| `GET /api/v1/events` | `core.api_pages.page / core.api_reads.undone_sql` |
| `GET /api/v1/events/{id}` | `core.api_reads.events` |
| `POST /api/v1/events/{id}/undo` | `core.api_writes.undo_event / core.tokens.undo` |
| `GET /api/v1/jobs` | `core.api_pages.page` |
| `GET /api/v1/jobs/{id}` | `core.api_reads.one / core.api_reads.rows` |
| `POST /api/v1/jobs/{id}/retry` | `core.api_jobs.retry / core.pipeline.Pipeline.queue_retry` |
| `POST /api/v1/jobs/{id}/resume` | `core.api_jobs.resume` |
| `POST /api/v1/jobs/drain` | `core.api_jobs.drain / core.pipeline.Pipeline.drain` |
| `POST /api/v1/jobs/instruction-identities` | `core.api_jobs.booklets / core.admin.queue_missing_booklets` |
| `POST /api/v1/jobs/pictures` | `core.api_jobs.queue_pictures / core.pictures.queue` |
| `GET /api/v1/sources` | `core.api_reads.sources` |
| `PATCH /api/v1/sources/{source}` | `core.source_ops.toggle` |
| `POST /api/v1/catalogue/import` | `core.source_ops.catalogue_import / core.sources.bricklink_catalogue.load` |
| `POST /api/v1/colors/sync` | `core.source_ops.sync_colours / core.sources.bricklink.BrickLink.sync_colors` |
| `GET /api/v1/sync/{source}` | `core.sync.status` |
| `GET /api/v1/sync/{source}/lists` | `core.sync.lists` |
| `PUT /api/v1/sync/{source}/link` | `core.sync.link` |
| `POST /api/v1/sync/{source}/pull/plan` | `core.sync.plan_pull` |
| `POST /api/v1/sync/{source}/pull/apply` | `core.sync.apply_pull` |
| `POST /api/v1/sync/{source}/send/plan` | `core.sync.plan_send` |
| `POST /api/v1/sync/{source}/send/apply` | `core.sync.apply_send` |
| `PUT /api/v1/sources/{source}/user` | `core.sync.paste / core.keys.save` |
| `DELETE /api/v1/sources/{source}/user` | `core.sync.remove / core.keys.archive` |
| `POST /api/v1/sources/{source}/user/connect` | `core.sync.connect` |
| `POST /api/v1/sources/{source}/user/test` | `core.sync.test` |
| `PUT /api/v1/sources/{source}/key` | `core.keys.save / core.secrets.encrypt` |
| `DELETE /api/v1/sources/{source}/key` | `core.keys.archive` |
| `POST /api/v1/sources/{source}/key/test` | `core.keys.check` |
| `GET /api/v1/exchange-rates` | `core.currency.listing` |
| `PUT /api/v1/exchange-rates/{code}` | `core.currency.set_rate` |
| `POST /api/v1/exchange-rates/ecb` | `core.currency.fetch_ecb` |
| `GET /api/v1/settings` | `core.admin.settings` |
| `PATCH /api/v1/settings` | `core.admin.patch_settings` |
| `GET /api/v1/statistics` | `core.admin.statistics` |
| `GET /api/v1/database/check` | `core.admin.check` |
| `GET /api/v1/database/export` | `core.api_reads.database_export` |
| `POST /api/v1/imports/bricktracker` | `core.importer.bricktracker.plan` |
| `POST /api/v1/imports/{id}/apply` | `core.importer.bricktracker.apply` |
| `POST /api/v1/identifications` | `core.identify.store / core.sources.brickognize.Brickognize.predict` |
| `GET /api/v1/identifications` | `core.api_reads.resource_rows` |
| `GET /api/v1/tokens` | `core.tokens.listing` |
| `POST /api/v1/tokens` | `core.tokens.create` |
| `DELETE /api/v1/tokens/{id}` | `core.tokens.revoke` |
| `POST /api/v1/copies/{id}/photos` | `core.collection.photo` |
| `POST /api/v1/stock/{id}/photos` | `core.collection.photo` |
| `DELETE /api/v1/identifications/{id}` | `core.identify.archive` |
| `GET /api/v1/identifications/{id}` | `core.api_reads.record` |
| `GET /api/v1/identifications/{id}/thumb` | `core.api_reads.content` |
| `POST /api/v1/storages/{id}/restore` | `core.collection.restore` |
| `POST /api/v1/lots/{id}/restore` | `core.collection.restore` |
| `POST /api/v1/places/{id}/restore` | `core.collection.restore` |
| `POST /api/v1/flags/{id}/restore` | `core.collection.restore` |
| `POST /api/v1/instruction-files/{id}/restore` | `core.collection.restore` |
<!-- api-m1:end -->

M2 implements every remaining GET in §3.2, including admin database reads and identification history/result/thumbnail reads. The generated table above names the actual backing functions. New projections live in `core/api_reads.py`; copies and stock reuse `collection.instances(include_archived=True)` and lots reuse `collection.lot_detail(include_archived=True)`, keeping web defaults live-only; no read handler queries SQL or opens a legacy store. Catalogue reads use the existing read-only `bricklink-catalog.db` index beside `brickwork.db` (the same exception as `add.lookup`); all collection, settings and operational data comes from `brickwork.db`. Reads never queue jobs or contact a source.

M2 response details and corrections to the draft:

* Every list uses `filter_rows` and value-cursor paging. Resource selectors (`source`, `kind`, `state`, `failed`, `spare`, `parent`, `owned`, etc.) are supported alongside §2.5. `colour` selects a BrickLink colour id; the adapter keeps the colour name for text search and sorting. `entity` matches an event entity prefix. Events and jobs default to descending numeric id (newest first). `since` uses the record update/create time, or event `at`. Unknown names and invalid filter/sort choices return `400 unknown_filter`; invalid cursors/limits return `400 bad_request`.
* Copy, stock and wish lists contain individual rows, including archived rows when requested; their single reads also return archived records. ETags hash the stored row and sorted flag ids, so display metadata and quote changes do not change them. Public flags are ids. Stored unrecorded conditions/completeness remain nullable, and the placeholder item type is `?` (the draft accidentally listed an empty string). Conditions and completeness are words, including the stored/derived completeness response; checked values are booleans.
* Item detail wraps the trimmed existing `collection.detail` projection with `item`, `properties`, counts, copies, stock, wishes, prices, inventory and matches. Price history returns recorded observations, including voided/error observations; current prices retain the existing core selection. Under max uses `planning.display_prices` and `planning.max_comparison`: only matching recorded currencies are comparable, and equality is under the maximum. `under_max=false` selects comparable over-maximum wishes.
* Planning ranking returns a list envelope with the settings once at top level; its default `sort=ranking` preserves the core group, pin, ratio and gain order through `planning.ranking_sort_key`, with a value cursor. Other lists default to `number`. Fresh stores use the same price-setting defaults as the settings screen. Both exports accept repeated `copy_id` parameters, or comma-separated `ids` (1–2000 unique copy ids), and reuse `planning.export`; JSON uses word conditions, XML preserves BrickLink's `N`/`U` format. Exporting unresolved identities fails with `422 validation_failed`.
* Instruction-file rows expose `item_no` and `content_url`; the list additionally reports booklet `coverage: {total, covered}`. Booklet identities without a PDF remain queryable under `/items?type=I`. Local image and PDF downloads enforce the same containment rules as the web. Identification thumbnails use the new-store root's `data/identifications/{id}.jpg`; legacy thumbnails are never read.
* Source key state contains only `configured`, `origin` and `saved_at`, with environment precedence over a stored key. Stored state is reported without decrypting or exposing it; key wiring and writes shipped in M5 (4.11g). Source errors and event values are redacted. Credential-change event payloads and internal idempotency receipts are suppressed. Admin database export is a read-only consistent snapshot; stored credential rows (live, archived and previous) are removed from the copy, and known plaintext credential material still refuses with `409 conflict`; it emits no mutation event.
* Unresolved-identity and stale-price projections use bulk reads in their existing core functions, preserving the web's selection rules. Per-list SQL trace tests compare a small fixture with several hundred relevant rows. All GET contracts, browser/Python/HTTP filter-sort parity, cursor stability during inserts, archives, ETags, source-key precedence and disclosure checks run offline.

M1 introduced the token branch of `POST /events/{id}/undo`. M3 adds collection, add, workbench, ledger and planning receipt dispatch. The endpoint requires write scope, an `Idempotency-Key` and no request body; token, source key and source toggle receipt Undo (also when bundled in an API event) additionally requires admin scope, as making those changes does. M4 adds manual-price receipts (`bw_manual_prices`); direct part, figure, loose-part and completeness marking reuse the guarded workbench receipt. Remaining receipt families follow in M5–M6. Undoing token creation revokes it, preserving the row and unique name; undoing revocation restores its former revocation state. Audit receipts contain public metadata only, never hashes or secrets. Undo itself has `undo_url: null`. Token Undo stores its key, response and target in its one audit row (`bw_token`, `undo:<key>`), scoped to actor with the same 30-day replay window; it does not add a second receipt row. Token create/revoke do not accept idempotency keys: retrying a create conflicts on name and never reveals the secret again.

## 4. Writes: audit, Undo, receipts

M3 returns the `event_id` of one API operation event containing the core receipt shapes below. The API keeps the functions and adds one front door; standalone core receipts from the web or earlier milestones remain supported. Every API write records `via='api'` and `actor` equal to its token name in the same transaction; web, CLI and import actors are NULL.

| Write group | Receipt (`events.entity`, field) | Undo function today | In API |
|---|---|---|---|
| M3 API operations | `bw_api`, `op:<key>` or `receipt`; embeds the core receipt shapes below | `core.api_writes.undo_event` dispatches to their existing owners | shared indexed `undone_event_id` lookup |
| Token create/revoke | `bw_token`, `create`/`revoke` | `core.tokens.undo` (admin required) | `POST /events/{id}/undo` |
| Copy, stock, wish, lot edits, archive, flags, new lot, photo | `bw_collection`, `save`/`archive`/`photo`/`caption` | `collection.undo` | `POST /events/{id}/undo` |
| Add (copies, stock, wishes) | `bw_add`, `receipt` (with `batch`) | `add.undo(batch)` | same; the dispatcher reads `batch` from the receipt |
| Transfer, take, found, booklets | `bw_workbench`, `receipt` | `workbench.undo` | same |
| Storage, move, orders, allocations | `bw_ledger`, `receipt` | `ledger.undo` | same |
| Pin, repair settings | `bw_planning`, `pin`/`settings` | `planning.undo` | same |
| Part to Inventory | `part_inventory:<batch>`, `receipt` | `part_inventory.undo` | same (Part to Inventory itself is not in v1, section 9) |
| Part check answers | `checker:<id>` (or `checker:<id>:fig:<type>:<no>`), field `checker:<operation>` | `checker.write` action `undo_event`, sharing the web Undo snapshot guard | `POST /events/{id}/undo`; later answers or edits block Undo |
| Prices recorded by API | `bw_manual_prices`, `receipt` (embedded in `bw_api`) | `manual_prices.undo`: set `error='undone'` and recompute `price_current` | same |
| Places and flags edits/archive | `bw_collection`, `save`/`archive` | `collection.undo` | same |
| Repair settings | `bw_planning`, `settings` | `planning.undo` | same |
| Source toggle | `source:<source>`, `enabled` | `source_ops.undo_toggle` | same; catalogue import jobs follow rule 5 below |
| Source keys | `source_key:<source>`, `save`/`archive` | `keys.undo` (admin required) | same; guarded encrypted state stays outside events |
| Identification upload/archive | `identification:<id>`, `create`/`archive` | `identify.undo` | same; Undo archives an upload or restores an archive |

Rules:

1. `POST /events/{id}/undo` looks up `events.entity` and calls the matching function. Unknown entity or a field that is not a receipt is `409 not_undoable`. Already undone returns `200` with `already_undone: true` (all existing functions return silently when an `undo` event exists).
2. A blocked Undo (later change to the same rows) is `409 undo_blocked` with the existing message ("Item changed · undo the later save first").
3. `GET /events` includes `undoable` and `undone`, computed with the same lookups the web history uses (`ledger.history`).
4. Undo itself writes one API operation event with `undone_event_id` (or a standalone core `field='undo'` row outside the API), and is not undoable.
5. Import jobs, source observations, budget spend and stored pictures are never reversed (pipeline.md, "Undo does not reverse import jobs").

---

## 5. Mapping from the retired API

The legacy blueprint and its prefixed routes were removed in 4.11j. Only the independent `brickwork/api/` blueprint at `/api/v1` remains. The historical operation mapping below records replacement semantics, not aliases or redirects. Status: **kept** = same job, new shape; **renamed**; **replaced** = different resource model; **dropped**.

| Today | Status | New | Notes |
|---|---|---|---|
| `GET /health` | kept | `GET /health` | No token; drops `web_db`; adds schema version. |
| `GET /sets/<set_num>` | replaced | `GET /items/{type}/{no}` (+ `GET /copies?item_no=`, `GET /wishes?item_no=`, `GET /items/{type}/{no}/prices`) | One combined payload split into resources. |
| `GET /wanted` | renamed | `GET /wishes` | |
| `GET /owned` | renamed | `GET /copies` | Grouping by set is a client concern. |
| `PUT /prices/<set>/<slot>` | replaced | `POST /items/{type}/{no}/prices` | Slot becomes condition plus guide. Slots `new, used` to `manual` N, U; `bricklink_new, bricklink_used` to `sold`/`stock` N, U (source `bricklink`, written by the pipeline, not by clients); `boxed` to `valuation` with `slot=boxed`. |
| `POST /prices/<set>/refresh` | renamed | `POST /items/{type}/{no}/prices/refresh` | Now a queued job (202); old call blocked up to 25 s (`fetch.refresh`). |
| `GET /prices/<set>/history` | renamed | `GET /items/{type}/{no}/prices/history` | |
| `PUT /wanted/<set_num>` | replaced | `PATCH /wishes/{id}` | Key is the wish id. Adds `max_price_currency`. |
| `GET /catalog/search` | renamed | `GET /catalogue/items` | BrickLink catalogue file, not Rebrickable's. |
| (catch-all 404) | kept | any unknown path | problem+json `not_found`. |
| `POST /owned` | renamed | `POST /copies` | `quantity`, `Idempotency-Key`. |
| `POST /wanted` | renamed | `POST /wishes` | |
| `PATCH /owned/<id>` | renamed | `PATCH /copies/{id}` | Field names are the `copies` columns (`box`, `instructions` become flags, Appendix B). |
| `DELETE /owned/<id>` | changed | `DELETE /copies/{id}` | Archive, not delete; restore added. |
| `DELETE /wanted/<set>` | changed | `DELETE /wishes/{id}` | Archive. |
| `POST /wanted/<set>/to-owned` | renamed | `POST /wishes/{id}/to-owned` | |
| `GET /parts/resolve?bricklink=` | replaced | `GET /id-matches?source=&kind=&source_id=` and `GET /items/{type}/{no}` (type P) | Reads `id_match`, no Rebrickable call. |
| `GET /missing?part=` | replaced | `GET /gaps?item_type=P&item_no=` | |
| `POST /owned/<id>/missing-parts` | replaced | `POST /copies/{id}/parts/bulk` | `mode` set or add, `dry_run` kept. |
| `POST /missing/found` | replaced | `POST /found` | `destination: set` with `assignments`. |
| `GET /parts/<part>/colors` | renamed | `GET /items/{type}/{no}/colors` | |
| `GET /storages` | kept | `GET /storages` | |
| `POST /loose-parts` | replaced | `POST /stock` with `item_type: P` | |
| `POST /identifications`, `GET /identifications[/<id>[/thumb]]`, `DELETE /identifications/<id>` | kept | Same paths, plus history `GET /identifications` | Brickognize upload, result, thumbnail and archive are included in v1. |
| `GET /owned/<id>/minifigs` | renamed | `GET /copies/{id}/figures` | |
| `PUT /owned/<id>/minifigs/<fig>` | replaced | `PATCH /copies/{id}/figures/{type}/{no}` | |
| `PUT /minifigs/<fig>/bricklink`, `POST /minifigs/resolve-bricklink`, `GET`/`PUT /minifigs/resolve-bricklink/<id>` | replaced | `POST /unresolved/resolve`, `GET /id-matches` | One manual-decision path (`admin.resolve`). |
| `GET /minifigs/pending` | replaced | `GET /unresolved?kind=minifig` | |
| `GET /sets/<n>/minifigs/match-input`, `POST .../match` | dropped | `POST /items/{type}/{no}/import` (matching is a pipeline step) | |
| `GET /export/missing-items` | replaced | `GET /gaps?copy_id=` | |
| `GET /export/missing-items.xml` | renamed | `GET /export/missing.xml?copy_id=` | |
| `POST /loose-minifigs`, `GET /loose-minifigs` | replaced | `POST /stock`, `GET /stock?type=M` | |
| `PATCH /loose-minifigs/<id>` | replaced | `PATCH /stock/{id}`, `PATCH /stock/{id}/parts` | |
| `GET /minifigs/prices` | replaced | `GET /prices?item_type=M&item_no=` | |
| `PUT /minifigs/prices/<id>/<slot>` | replaced | `POST /items/{type}/{no}/prices` | |
| `GET`/`PATCH /settings` | kept | `GET`/`PATCH /settings` | Whitelist (section 6, Settings). |
| `GET /bricklink/colors` | renamed | `GET /colors` | |
| `PUT /bricklink/colors` | dropped | `POST /colors/sync` | The app pulls colours with the user's key; no client pushes them. |
| `GET /bricklink/catalog` | renamed | `GET /catalogue/status` | |
| `POST /bricklink/order-lines/resolve` | dropped | `POST /orders/documents` | Pasted lines are an order document (`email`/`xml`). |
| `PUT /part-prices` | replaced | `POST /prices/observations` | |
| `GET /part-prices` | replaced | `GET /prices` | |
| `GET /part-prices/due` | renamed | `GET /prices/stale` | |
| `GET /images/bl/P/<colour>/<item>.png`, `.../M/<item>.png` | dropped | `GET /images/{id}/content`, `GET /items/{type}/{no}/images` | Pictures are local files; remote URLs are provenance only (pipeline.md). |
| `GET /complete-sets` | renamed | `GET /planning/ranking` | |
| `PATCH /owned/<id>/pin` | renamed | `PUT /copies/{id}/pin` | |
| `PUT /orders/<bl_order_id>` | dropped | `POST /orders/documents` (`source: api`, `number`) | The app now fetches the order itself with the user's key. |
| `GET /orders/<bl_order_id>` | replaced | `GET /orders?bricklink_order_id=` | |
| unversioned `/api/settings`, `/api/bricklink/*`, `/api/part-prices*`, `/api/images/*`, `/api/orders/*` | dropped | none | Only `/api/v1` exists. |

**Client needs** (derived from the legacy routes): details of a set with prices and copies; wishlist and owned lists; set price record, refresh and history; wish limit edit; catalogue search; add owned or wanted; edit, archive owned; wish to owned; part resolution, missing parts per copy, apply missing, found; part colours; storages; loose parts and loose figures (add, list, patch); copy figures and figure missing; unresolved figures and manual match; missing-items export; figure and part prices (write and read, stale list); settings; BrickLink colours and catalogue status; completion ranking and pin; orders (push and read). In the new API these are all covered by the endpoints in the right column; identification uploads are included in v1; pushed orders are replaced by document import.

---

## 6. Behaviour notes per group (what to wrap, what to build)

| Group | Notes |
|---|---|
| Copies | Create = `add.confirm(where=owned)`: inserts items row if absent, N copies with completeness `I` and source `derived` unless given, queues the six-step import in the same transaction, writes the `bw_add` receipt. Storage and purchase fields on create are NEW (applied by `collection.save` inside the same transaction; one receipt). Edit = `collection.save`, which validates conditions, ids, `Decimal` prices, dates and recomputes derived completeness (`completeness.derived_state`). |
| Part and figure marking | The only existing single-line writes are inside `checker.write` (session-bound) and `workbench.reduce_gap` (reduces only). `PATCH .../parts/{part_id}` is NEW: sets absolute `missing`, `damaged`, `checked` with the checker's bounds (0 to quantity), recomputes derived completeness via `workbench.recompute`, writes a `bw_workbench` style receipt. Whole-figure missing affects component parts exactly as `workbench.reduce_gap`/`part_gap` define. |
| Loose stock | `stock.add_loose` merges identical lines (not for type `M`: each figure is its own line, `stock.py`); `PATCH` can merge, response lists `merged_ids` (`collection.merge_result`). Booklets are type `I` stock created by `workbench.booklets` (limits: 200 lines, quantity 1 to 99). |
| Take and give | `take_for_gap(copy_id, 'P', no, color, qty)` or `take_for_gap(copy_id, 'M', no, None, qty)`: all or nothing, Matcher order, one receipt. `transfer(source_id, copy_id, target, target_id, amount)`: target `part, figure, stock-part, instructions, box`. Both raise on changed counts ("review matches again"); API code `409 stale_match`. |
| Prices | Reads use `collection.prices`/`decorate_prices` and `collection_prices.choose` (priority from `settings.source_priority`). Manual and valuation observations are NEW: insert `price_observations` (`source='manual'`), update `price_current`, audit. Source-fetched prices (BrickLink, Brickset) are written only by the pipeline. Refresh = `Pipeline.queue_steps(..., ('market_price',))`; skips items with a live import job (`admin.queue_refresh`). |
| Wishlist | `collection.save(entity=wish)` already takes `max_price` plus `max_price_currency` (rules: max without currency keeps the wish's currency, else the configured one; currency without max is rejected; clearing the max clears the currency). `under_max` uses `planning.max_comparison`. Create with a max price is NEW (create then save, one receipt). |
| Storages and locations | `ledger.storage_save/move/storage_archive`; archive refuses a non-empty storage unless `move_to_unstored=true`; the virtual "Not stored" is `unstored` in `POST /storages/{id}/contents`. Lots are created only from existing stock (`collection.new_lot`). |
| Orders | `orders.import_document(db, source, text, choice, number, label)`; `source=api` calls BrickLink with the user's key (`orders.api_data`), the other two parse pasted email or XML (max 1 MiB). Everything else is `orders.*` unchanged. |
| Jobs | `Pipeline`: six steps `identity, inventory, matching, pictures, metadata, market_price`; states `queued, running, waiting_for_budget, failed, done`. The API never blocks on network work; it queues and returns `202`. A worker must run: embedded drainer (`web/views.py` `bw_start_worker`) or `brickwork worker`; `POST /jobs/drain` runs one batch (Q6). |
| Settings (whitelist) | `retail_country` (DE US UK CA), `bricklink_region`, `bricklink_currency`, `incomplete_discount_pct`, `source_priority`, `import_order:<TYPE>`, freshness days, repair values. Anything else is `422 unsupported_setting` (`admin_ops.settings_set` already does this). Keys and tokens are never settings. |

---

## 7. MCP server

A thin adapter: **no logic of its own**. Each tool validates its arguments against the OpenAPI operation and forwards one API call; single-read results are the API's `data`; lists retain the `data`/`page` envelope so cursors remain available, and writes retain the complete receipt envelope (`event_id`, `undo_url`, `idempotent_replay`). API errors are the API's problem document with MCP `isError: true`.

### 7.1 Transport and process

| Mode | How | Use |
|---|---|---|
| stdio | `brickwork mcp` | Local agent clients. |
| HTTP | `brickwork mcp --transport http`: Streamable HTTP at `/mcp`, same Flask app behind an ASGI host, same token | Remote clients. |

Both use the same tool table. Package: `brickwork/core/mcp/` (NEW), using the official `mcp>=1.30,<2` Python SDK, OpenAPI metadata and an API client. `x-mcp-tool` on operations and `x-mcp.resources` declare the shared surface. The HTTP command mounts the SDK ASGI endpoint alongside the Flask WSGI application; a plain WSGI deployment does not serve `/mcp`. The API endpoints remain at `/api/v1`.

### 7.2 Auth and gating

* Same bearer token. The MCP forwards the caller's token (HTTP mode) or reads `BW_API_TOKEN`/`--token-file` (stdio). It adds no privilege.
* **Read tools** are always listed. **Write tools** are listed only when the token has `write` **and** the server runs with `--allow-write` (or `BW_MCP_WRITE=1`). **Admin operations** (settings update, source toggle, catalogue import, database export, tokens) are never exposed as tools; use the API or CLI.
* Every write tool sends an `Idempotency-Key`: an optional `idempotency_key` argument is reused verbatim, otherwise a UUID is generated. Clients retrying a call must retain that argument to replay the same operation. Write results include `event_id` and `undo_url`. Destructive confirmation is the client's job; the MCP's `archive_*` tools are archive, never hard delete.

### 7.3 In-process or HTTP

Default: HTTP to the API (loopback for stdio mode), so scopes, idempotency, ETag, rate handling and audit are identical to any other client. Option `--in-process`: the MCP builds the Flask app once and calls it through the WSGI test client (same routes, same auth middleware, no socket). It does **not** call service functions directly, because that would bypass the layers above and duplicate them. Cost: one extra serialisation; benefit: one code path.

Arguments are generated from the OpenAPI path/query parameters and JSON body schemas. Query filters are individual arguments (not a nested `filters` object). `update_copy`, `update_stock`, and `update_wish` put their JSON body in `fields`; other tools take body fields directly. OpenAPI names win over the shorthand Input column below (`color_id`, `item_type`, `target_id`, etc.). Optional `if_match` forwards `If-Match` where supported. Unknown arguments fail validation. Write visibility and direct calls recheck `/me`, so revocation and scope changes take effect immediately; the API still enforces read-only mode and operation authorization.

Examples:

```sh
brickwork mcp --in-process --token-file data/mcp-token
brickwork mcp --api-url http://127.0.0.1:5000/api/v1 --allow-write
brickwork mcp --transport http --host 127.0.0.1 --port 5000 --allow-write
```

The HTTP transport always forwards the request's bearer token and never falls back to the bootstrap token or `--token-file`. stdio reads `BW_API_TOKEN` unless `--token-file` is supplied. `BW_MCP_WRITE=1` also enables the server-side write flag. HTTP defaults to loopback; remote deployments provide TLS at their proxy. stdio protocol output uses stdout exclusively; SDK diagnostics use stderr.

### 7.4 Tools: read (31)

| Tool | Input | Calls |
|---|---|---|
| `search_catalogue` | type, q | `GET /catalogue/items` |
| `get_item` | type, no | `GET /items/{type}/{no}` |
| `list_copies` | filters, cursor, limit | `GET /copies` |
| `get_copy` | id | `GET /copies/{id}` |
| `get_copy_completeness` | id | `GET /copies/{id}/completeness` |
| `list_copy_parts` | id, problem, spare | `GET /copies/{id}/parts` |
| `list_copy_figures` | id | `GET /copies/{id}/figures` |
| `list_gaps` | item_type, item_no, color_id, copy_id | `GET /gaps` |
| `list_matches` | item_type, item_no, color_id, copy_id | `GET /matches` |
| `list_stock` | filters, cursor, limit | `GET /stock` |
| `list_minifigures` | filters, cursor, limit | `GET /minifigures` |
| `get_wishlists` | archived | `GET /wishlists` |
| `export_wishlist_xml` | id, summary | `GET /wishlists/{id}/export.xml` |
| `export_wishlist_csv` | id, kind, summary | `GET /wishlists/{id}/export.csv` |
| `list_wishes` | filters incl. under_max | `GET /wishes` |
| `list_storages` | none | `GET /storages` |
| `list_lots` | none | `GET /lots` |
| `list_places` | none | `GET /places` |
| `list_flags` | kind | `GET /flags` |
| `get_prices` | type, no, color_id | `GET /items/{type}/{no}/prices` |
| `list_stale_prices` | none | `GET /prices/stale` |
| `list_instruction_files` | item_type, item_no, has_file | `GET /instruction-files` |
| `list_orders` | bricklink_order_id | `GET /orders` |
| `get_order` | id | `GET /orders/{id}` |
| `list_events` | entity, since, undoable | `GET /events` |
| `list_jobs` | state | `GET /jobs` |
| `get_sources` | none | `GET /sources` |
| `get_settings` | none | `GET /settings` |
| `get_statistics` | none | `GET /statistics` |
| `get_planning_ranking` | none | `GET /planning/ranking` |
| `get_sync_status` | source | `GET /sync/{source}` |

### 7.5 Tools: write (30, gated)

| Tool | Input | Calls |
|---|---|---|
| `add_copies` | item_no, quantity, condition, completeness | `POST /copies` |
| `update_copy` | id, fields | `PATCH /copies/{id}` |
| `archive_copy` | id | `DELETE /copies/{id}` |
| `set_part_missing` | id, part_id, missing, damaged | `PATCH /copies/{id}/parts/{part_id}` |
| `set_figure_missing` | id, type, no, missing | `PATCH /copies/{id}/figures/{type}/{no}` |
| `set_copy_checked` | id, checked | `PUT /copies/{id}/checked` |
| `add_stock` | item_type, item_no, color_id, quantity, condition | `POST /stock` |
| `update_stock` | id, fields | `PATCH /stock/{id}` |
| `add_wish` | item_type, item_no, color_id, quantity, max_price | `POST /wishes` |
| `post_wishlists` | name, note, sort, bricklink_id | `POST /wishlists` |
| `patch_wishlists_id` | id, name, note, sort, bricklink_id | `PATCH /wishlists/{id}` |
| `delete_wishlists_id` | id | `DELETE /wishlists/{id}` |
| `post_wishlists_id_restore` | id | `POST /wishlists/{id}/restore` |
| `post_wishlists_id_transfer` | id, ids, copy | `POST /wishlists/{id}/transfer` |
| `update_wish` | id, fields | `PATCH /wishes/{id}` |
| `archive_wish` | id | `DELETE /wishes/{id}` |
| `wish_to_owned` | id | `POST /wishes/{id}/to-owned` |
| `take_for_gap` | copy id, part and colour or minifigure, quantity | `POST /copies/{id}/take` |
| `give_from_stock` | stock id, copy id, target, quantity | `POST /stock/{id}/give` |
| `create_storage` | name | `POST /storages` |
| `move_to_storage` | storage id, selections | `POST /storages/{id}/contents` |
| `record_price` | type, no, condition, guide, price, currency | `POST /items/{type}/{no}/prices` |
| `refresh_price` | type, no | `POST /items/{type}/{no}/prices/refresh` |
| `import_item` | type, no | `POST /items/{type}/{no}/import` |
| `retry_job` | id, step | `POST /jobs/{id}/retry` |
| `undo_event` | id | `POST /events/{id}/undo` |
| `import_order` | source, text or number | `POST /orders/documents` |
| `plan_sync_pull` | source | `POST /sync/{source}/pull/plan` |
| `apply_sync_pull` | source, plan_id, ticked | `POST /sync/{source}/pull/apply` |
| `plan_sync_send` | source | `POST /sync/{source}/send/plan` |

### 7.6 Resources (read-only, 8)

| URI | Reads |
|---|---|
| `brickwork://summary` | `GET /statistics` |
| `brickwork://copies/{id}` | `GET /copies/{id}` |
| `brickwork://items/{type}/{no}` | `GET /items/{type}/{no}` |
| `brickwork://wishlist` | `GET /wishes` |
| `brickwork://storages` | `GET /storages` |
| `brickwork://sources` | `GET /sources` |
| `brickwork://events/recent` | `GET /events` |
| `brickwork://openapi` | `the published openapi-v1.yaml` |

Each tool description repeats the API summary and lists the filter names; tool names are `snake_case`, stable, and versioned with the API (a tool is removed only with a deprecation notice, section 9).

---

## 8. Standalone operation

### 8.1 Fresh install, no keys, no network

`brickwork setup` creates `data/brickwork.db` from `schema.sql` (new files only; `connect.py`). Behaviour with nothing configured (exercised by the smoke test, section 12):

| Endpoint family | Without keys | Code |
|---|---|---|
| `/health`, `/version`, `/me`, `/settings`, `/sources`, `/statistics`, collection reads and local edits on existing items, `/events`, `/jobs`, storages, lots, places, flags | works | none |
| `GET /catalogue/items`, `POST /copies`, `/stock`, `/wishes` for an item not yet known | needs the BrickLink catalogue file (`bricklink-catalog.db`) | `424 catalogue_not_loaded` |
| `POST /orders/documents` with `source=api`, `POST /colors/sync`, source key tests | needs BrickLink consumer key, secret, token value and secret | `424 source_not_configured`, `source: bricklink` |
| Queued price refresh (`POST /prices/refresh`, item refresh) | queues without credentials; executing the source step requires the source key | job step fails with `source_not_configured` |
| Pipeline `matching`, `pictures` (parts) | needs Rebrickable key | job step fails with `source_not_configured` (`rebrickable`); other steps continue (pipeline.md: a failed step does not stop the job) |
| Pipeline `metadata` for sets | needs Brickset key (optional) | step ends `failed` with `source_not_configured` (`brickset`) |
| Manual prices (`POST /items/{type}/{no}/prices`), part checks, transfers, orders from email or XML | works | none |
| Disabled source (`PATCH /sources/{source}`) | | `424 source_disabled` |

The standalone smoke test exercises fresh setup, catalogue-required and key-required operations with socket connections and DNS blocked. Queue operations need no key; source execution reports typed failures before any credentialed request. Public picture downloads remain source calls and are not run by this offline smoke.

### 8.2 Key store

Source keys are entered in the app and stored encrypted with Fernet in `source_keys(source PRIMARY KEY, ciphertext, saved_at, archived_at)`. `BW_SECRET_KEY` supplies the Fernet encryption key. Without it, key entry is disabled with a clear error; environment source keys continue to work. A wrong encryption key fails without exposing any key material.

Environment values win over stored values: BrickLink uses `BW_BRICKLINK_CONSUMER_KEY`, `BW_BRICKLINK_CONSUMER_SECRET`, `BW_BRICKLINK_TOKEN_VALUE`, `BW_BRICKLINK_TOKEN_SECRET`; Rebrickable uses `BW_REBRICKABLE_API_KEY`; Brickset uses `BW_BRICKSET_API_KEY`. Brickognize needs no key. The source payload may hold that source's credential bundle encrypted as one value.

`PUT /sources/{source}/key` requires admin scope and accepts a write-only key payload; `DELETE /sources/{source}/key` archives the stored key and is undoable. `GET /sources` reports only `key: {configured: true|false, origin: env|stored|null, saved_at: timestamp|null}`. No endpoint, page, log or error returns a key or any fragment. Read status is implemented in M2; wiring, writes and the Catalogues & keys page are M5 (below).

### 8.3 Budgets and throttling

Per source daily budgets (UTC day), reserved before each call in a separate transaction: `BW_BRICKLINK_DAILY_BUDGET` (default 4,400), `BW_REBRICKABLE_DAILY_BUDGET` (1,000), Brickset 100 charged calls per day, `BW_BRICKOGNIZE_DAILY_BUDGET` (100); at least 1 s spacing between attempts (sources.md, pipeline.md). Surfacing:

* Queued work (refresh, import, retry): `202` job; when the budget is spent the job is `waiting_for_budget` with `retry_at` (next UTC midnight or the remote's wait). No error.
* Synchronous source calls (`POST /orders/documents` with `source=api`, `POST /colors/sync`, `POST /catalogue/import`): `429 budget_exhausted` with `Retry-After` and `retry_after` seconds, plus `job_id` when `WaitingForBudget` holds a resumable request (`sources/base.py`). Remote throttle (`RemoteBudgetExceeded.retry_seconds`) is `429 source_throttled` with that wait.
* `GET /sources` shows `budget`, `used_today`, `last_success`, `last_error`. There is no per-token API rate limit in v1.
* The BrickLink default of 4,400 provides a safety margin for other tools using the same key.

### 8.4 Outbound calls

Only these hosts are called (constants in the clients): `api.bricklink.com` (store API), `img.bricklink.com` and `www.bricklink.com` (pictures), `rebrickable.com` with `cdn.rebrickable.com`/`images.rebrickable.com` (API and pictures), `brickset.com` (API v3), `api.brickognize.com` (`sources/bricklink.py`, `rebrickable.py`, `brickset.py`, `brickognize.py`, `sources/images.py` `HOSTS`). Redirects are disabled and untrusted image hosts are rejected (`sources/images.py`, sources.md). The API adds no outbound call: no webhook, no callback URL, no URL fetch by parameter (`POST /catalogue/import` takes no path or URL; it reads the configured directory). The BrickLink catalogue download stays a manual step by the user (launch kit: nothing of BrickLink's ships).

---

## 9. Compatibility, versioning, deprecation

* **Additive within v1:** new endpoints, new optional request fields, new response members, new enum values for output only. Clients must ignore unknown response members.
* **Breaking (needs v2):** removing or renaming a path, member or enum value; changing a type, a default, a required field, a status code or an error `code`; tightening validation that accepted input before.
* **OpenAPI file** is the contract: `openapi-v1.yaml` is versioned with the code, `info.version` follows `MAJOR.MINOR.PATCH` (`1.0.0-draft` now). Contract tests run against it (section 12).
* **Deprecation:** mark the operation `deprecated: true`, send `Deprecation: true` and `Sunset: <date>` headers, name the replacement in the changelog. Minimum window 6 months and one minor release; MCP tools follow the same notice.
* **Stability tiers:** all documented paths are stable. Fields named `x-*` and anything under `/api/v1/_*` are not.
* **Event vocabulary** (`events.entity`, `field`) is **not** part of the contract; `GET /events` shows it for audit, clients use `undoable`, `undone` and the Undo endpoint.

### What the API does NOT do

* No key values or fragments in responses, pages, logs or errors (8.2).
* Uploads in v1: instruction PDFs (20 MB, `admin.instruction_upload`), own photos (15 MB, `collection.photo`) and Brickognize identification images.
* No bulk SQL, raw table access, or export of tables other than the SQLite snapshot (`admin` scope).
* Deletes archive and are undoable, including places and flags.
* No arbitrary outbound requests, webhooks or server-sent events in v1 (progress is polling `GET /jobs/{id}`; the Socket.IO channel in pipeline.md stays a web-UI detail).
* No user accounts or per-user data separation: tokens identify clients of one collection.
* No price alerts (out of scope, wiki Open Questions).
* No Part to Inventory, Brickset-only refresh in v1 (CLI and web keep them).

---

## 10. Decisions (2026-10-15)

1. Stored scoped tokens (`read`, `write`, `admin`) plus an environment bootstrap `BW_API_TOKEN` that cannot be revoked through the API.
2. Schema 3.3 replaces `pre-3.3 API origin` with `api` in `events.via` and maps existing rows.
3. In-app source keys are encrypted with Fernet using `BW_SECRET_KEY`; environment keys win. Missing encryption secret disables entry, with a clear error. Only configured state, origin and saved time are reported; writes require admin.
4. `DELETE /copies/{id}` archives; `POST /copies/{id}/restore` restores.
5. Instruction PDFs, own photos (15 MB) and Brickognize identification upload/result/thumbnail/archive are in v1.
6. Embedded job drainer by default; `brickwork worker` is documented for headless installations. `POST /jobs/drain` remains available.
7. No per-token rate limit in v1.
8. API enums use words; stored codes do not change.
9. Purchase locations and flags gain `archived_at`; deletes archive and Undo restores them.
10. Price settings move into v3 `settings`; readers use that store.
11. `events.actor` is the API token name, NULL for web, CLI and imports.
12. Undo of an API manual price marks `error='undone'` and recomputes `price_current`.
13. The resource catalogue includes the client-required identification operations; no private client configuration belongs in the app.
14. `BW_BRICKLINK_DAILY_BUDGET` stays 4,400, a safety margin for other tools sharing a key.
15. The package rename was completed in 4.11a: `brickwork/core` and `brickwork/web`.

---

## 11. Schema and code changes this contract needs

| ID | Change | Why |
|---|---|---|
| DDL-1 | Schema 3.3: rebuild `events` with `CHECK(via IN ('app','cli','api','import','migration'))`: create the new table, copy rows mapping `pre-3.3 API origin` to `api` (the append-only triggers cannot be bypassed, so drop them, copy, recreate all append-only triggers, including `events_no_replace`); add nullable `actor TEXT`. `schema_meta` CHECK to `3.3`. One atomic idempotent step in `upgrade_api.py`, called by `upgrade.py` and `connect()`. The 3.2 initialization DDL is retained for earlier migration proofs; new connections immediately upgrade to 3.3. | `via='api'` (F5). |
| DDL-2 | Table `api_tokens(id TEXT PK, name TEXT UNIQUE NOT NULL, hash TEXT NOT NULL, scopes TEXT NOT NULL, created_at, expires_at, last_used_at, revoked_at)`. | Scoped tokens (2.9). |
| DDL-3 | `archived_at` on `purchase_locations` and `flags`. | Archive everywhere. |
| DDL-4 | `source_keys(source TEXT PRIMARY KEY, ciphertext TEXT NOT NULL, saved_at TEXT NOT NULL, archived_at TEXT)` and Fernet helpers. | Encrypted source keys (decision 3); wiring in 4.11g. |
| CODE-1 | `admin.audit()` and `sources.base.audit_origin` accept `api`; `audit()` accepts origin and actor instead of the literal `'app'`. | F5. |
| CODE-2 | Typed exceptions with stable codes and one HTTP status table; handler follows in 4.11c (Appendix A). | F3. |
| CODE-3 | `filter_rows` and cursor paging shared by web and API. | F6. |
| CODE-4 | `collection.save(..., expect=...)` for If-Match. | 2.6. |
| CODE-5 | Receipt dispatcher for `POST /events/{id}/undo`. | F4. |
| CODE-6 | Blueprint `brickwork/api/` (handlers, serialisers, auth), the `brickwork token` and `brickwork mcp` CLI commands, the `mcp/` adapter. | Build. |
| CODE-7 | M8 removes the retired blueprint, old token setting, external refresh call and live legacy-store readers. The `bw_api` event entity remains the current operation receipt format. | Standalone cutover. |

---

## 12. Build order and tests

Milestones are independent PRs, each leaves the app working. Contract tests are generated from `openapi-v1.yaml` (every operation: request validates against its schema, a fixture response validates against its response schema, every documented status code is reachable).

| M | Scope | Tests |
|---|---|---|
| 4.11b (M0) | Schema 3.3, DDL-1–4, CODE-1, CODE-2; archive and Undo; encrypted key helpers; price settings moved | Migration test on an existing 3.2 file (idempotent, events preserved, CHECK enforced); `audit_origin('api')`; error mapping table test. |
| 4.11c (M1) | Blueprint skeleton: auth (env + stored tokens, scopes, read-only), problem+json, envelopes, pagination and filters (`filter_rows`), `/health /version /me /tokens`, OpenAPI served at `GET /openapi.yaml` | **Auth tests:** no token (401), bad, revoked, expired, wrong scope (403), `X-Web-Token` rejected, `api_disabled` (503), constant-time compare used, `BW_READ_ONLY` (403 on writes), token secret never in any response or log. **Contract test harness** generated from YAML operations marked `x-milestone: M1` (fails if a marked operation has no handler or an implemented v1 route has no marked operation). PyYAML and jsonschema are development dependencies. Future operations remain unmarked until implemented. |
| 4.11d (M2) | Reads: catalogue, items, copies, parts, figures, stock, minifigures, wishes, locations, prices, instructions, orders, events, jobs, sources, settings, statistics | Contract tests for every `GET`; filter and sort parity test: the same query through `filter_rows` and through the JS fixture data gives the same order (shared JSON fixtures); cursor stability while rows are inserted. |
| 4.11e (M3) | Writes on existing functions: copies, stock, wishes, locations, flags, pin, storages, lots, instruction files, take, give, found, booklets | For each write: one `events` row with `via='api'`, one transaction (failure leaves nothing), Undo through `POST /events/{id}/undo` restores the exact rows, archive and restore, `If-Match` (412) and idempotency (replay, conflict, required key). |
| 4.11f (M4) | NEW writes: part and figure marking, bulk apply, completeness checked, wish to owned, manual prices and batch, restore, loose-figure parts | Same checks plus derived-completeness recomputation parity with `checker.write` on shared fixtures. |
| 4.11g (M5) | Jobs and sources: queue, retry, resume, drain, budgets as 202 or 429, encrypted key wiring; `GET /sources` with configured, origin and saved_at only | Mocked transports only (no network); budget exhaustion gives `waiting_for_budget` and `Retry-After`; **no-secret test:** set fake keys in the environment, call every endpoint, assert none of the values appears in any body, header or log line. |
| 4.11h (M6) | Orders endpoints; events Undo dispatcher complete for all receipt kinds | Undo matrix over every receipt entity in section 4; blocked-Undo returns `undo_blocked`. |
| 4.11i (M7) | MCP: stdio and HTTP, read tools, then gated write tools | Tool list equals the table in section 7 (generated check against the OpenAPI operations); write tools absent without the flag or scope; each tool round-trips through an in-process client; no logic test: tools contain no import from `collection`/`add`/`workbench`. |
| 4.11j (M8) | Standalone cutover, root browser paths, one read-only legacy importer. | Minimal naming allowlist and retired-route checks. |
| 4.11j (M9) | **Standalone smoke test** (also runs in M1 onwards as a growing test): start the app with an empty data directory, no environment keys, no `BW_API_TOKEN` set except a generated one, **network blocked** (socket patched to fail): setup, create a storage, load a tiny synthetic catalogue file, add a copy, mark a part missing, record a manual price, undo it, list events; assert the family table of section 8.1 (`catalogue_not_loaded`, `source_not_configured`, no outbound connection attempted). | |

Definition of done per milestone: contract tests green, no endpoint without a test of its error codes, the tables in this file regenerated from the YAML (a script diff in CI).

---

## Appendix A: error codes

| `code` | HTTP | When | Existing trigger |
|---|---|---|---|
| `bad_request` | 400 | malformed JSON, wrong content type | `web/api.py` `body()` |
| `unknown_filter` | 400 | filter or sort name not in the vocabulary | NEW |
| `unauthorized` | 401 | no, bad, expired or revoked token | `authenticate` |
| `forbidden` | 403 | scope too low | NEW |
| `read_only_instance` | 403 | `BW_READ_ONLY` set and a write was attempted | `bw_collection_editable` |
| `not_found` | 404 | no such path or record | `unknown_route`, `abort(404)` |
| `method_not_allowed` | 405 | unsupported HTTP method; `Allow` lists supported methods | routing / `abort(405)` |
| `archived` | 409 | write to an archived record | `collection.save` "Instance is unavailable" |
| `conflict` | 409 | state changed, duplicate ("Already owned or wished") | `add.validate_edits` |
| `stale_match` | 409 | stock or gap counts changed | `workbench.transfer`/`take_for_gap` |
| `undo_blocked` | 409 | later change to the same rows | `collection.undo`, `workbench.undo`, `ledger.undo` |
| `not_undoable` | 409 | event is not a receipt | NEW |
| `idempotency_conflict` | 409 | key reused with another body | NEW |
| `precondition_failed` | 412 | `If-Match` mismatch | NEW |
| `payload_too_large` | 413 | document over 1 MiB, PDF over 20 MB, photo over 15 MB | `orders.import_document`, `admin.instruction_upload` |
| `unsupported_media_type` | 415 | not JSON or multipart where required | NEW |
| `validation_failed` | 422 | field errors | `collection.save` and others (`ValueError`) |
| `unsupported_setting` | 422 | key not in the whitelist | `admin_ops.settings_set` |
| `idempotency_key_required` | 428 | required key missing | NEW |
| `source_not_configured` | 424 | key missing for the source | NEW typed error |
| `source_disabled` | 424 | source disabled in Catalogues & keys | `sources.enabled` |
| `catalogue_not_loaded` | 424 | no BrickLink catalogue file | `add.search` "Load the BrickLink catalogue" |
| `budget_exhausted` | 429 | daily budget spent, synchronous call | `WaitingForBudget` |
| `source_throttled` | 429 | remote asked to wait | `RemoteBudgetExceeded` |
| `too_many_attempts` | 429 | too many failed token checks from this client; `Retry-After` and `retry_after` give the wait | `core/throttle.py` |
| `source_error` | 502 | upstream failure, redacted text | `SourceError` |
| `not_set_up` | 503 | database file missing ("Run 'brickwork setup'") | `admin.database`, `admin_ops.require_setup` |
| `api_disabled` | 503 | no token configured | `authenticate` (today 503) |
| `db_unavailable` | 503 | SQLite error | NEW mapping |
| `internal_error` | 500 | anything else, no detail leaked | NEW |

## Appendix B: copy and stock field sets

`PATCH /copies/{id}` accepts exactly the fields `collection.save` allows for `copy`: `condition, storage_id, purchase_location_id, purchase_date, purchase_price, purchase_currency, note, completeness, completeness_source, current_value, current_value_currency`. Stock: the common set plus `lot_id`. Wish: `quantity, color_id, condition, max_price, max_price_currency, note`. Lot: `name, note, storage_id, purchase_location_id, purchase_date, purchase_price, purchase_currency`. Flags are replaced as a set through `PUT .../flags` (one receipt, as `save` with `flags`). `box` and `instructions` of the old Web copy are the status flags "Box present" and "Instructions present" (`workbench.flag`), set through `PUT /copies/{id}/flags`.

## M2 response field alignment (4.11d follow-up)

The API serializer selects public fields independently of browser projections.
Contract tests close every M1/M2 response object with `additionalProperties: false`,
including referenced and nested objects; explicitly declared free maps stay open.

| Public response | API mapping and contract additions |
|---|---|
| Items | Browser `image` becomes `image_id`. `Item` adds `owned` (integer) and `properties` (free map). |
| Item detail | `counts.owned` counts live copies plus live loose quantity; `counts.wished` is the same boolean wish check as `add.decorate` for the uncoloured item identity. Both fields are required. Adds `inventory` (catalogue inventory lines) and `matches` (identity matches). `prices` is an array of `PriceCurrent`. |
| Catalogue item | Adds `category`; `owned` is an integer count, replacing its boolean schema. |
| Copies, stock, wishes, minifigures | Adds `image_id`, mapped from the browser picture selection. |
| Wishes | `max_state` maps to `under_max`: true for under/equal, false for over, null when incomparable or missing. The selected quote's amount becomes `current_price`. `max_margin` is a difference, so it does not supply `current_price` and is omitted. |
| Prices | Flat current-price rows become `PriceCurrent {observation, age_days, stale}`. `observation_id` becomes the nested observation's `id`; `age_days` is elapsed whole days or null. Item-price `observations` becomes `records`. |
| Stale prices | Adds `source_table` (`copies`, `loose_stock`, `wishlist`). The cursor identity includes item type, number, colour, condition and source table. |
| Sources | `used_today` uses the same durable budget counter as enforcement and the web, including repeated attempts of one job. |
| Instruction files | Adds `coverage.total` and `coverage.covered` to the list envelope. |
| Lots | Adds `quantity`; detail follows `{lot, rows}`. |
| Settings | Browser `priority` becomes `source_priority`; `repair_*` settings are grouped under `repair` with the prefix removed. |
| Ranking | Replaces the unconstrained row with `RankingRow`: copy fields plus `group`, `items`, nullable `rank`, `reasons`, `missing_count`, `missing_figures`, `missing_parts`, `original_gap`, `stock_used`, `unresolved_items`, `display_ratio_width`, `complete_quote`, `listing`, `value_when_complete`, `valuation_basis`, `breakdown`, `repair_cost`, `gross_gain`, `net_gain`, `ratio`, `ratio_width`, `ratio_overflow`. Ranking `settings` follows `Settings`. |
| Identification detail | Replaces the empty response schema with `OneIdentification {data: Identification}`. |

Browser decoration fields that are absent from the public contract do not appear
in API responses. Web templates retain their existing projections and names.


## M3 implementation alignment (4.11e)

* Events and jobs page in SQL on integer `id`; default order is descending. Current prices page in SQL on the stable current-row `rowid`, ascending by default. Price-history lists page on observation `id`, descending by default. All filters become SQL predicates and cursors bind to resource, direction and filters. These history pages report `total: null`. Item-price summaries load only that item's current prices and its latest 200 observations; the history endpoint supplies the rest.
* The event page and Undo dispatcher share indexed undone predicates. The 3.3 additive upgrade installs idempotent event lookup indexes, including the JSON `undone_event_id` index, and adds `instruction_files.archived_at`; existing 3.3 stores upgrade too. No earlier migration mapping changes.
* Core transactions now compose through savepoints. Pipeline initialization no longer implicitly commits the caller. File rollback callbacks remove newly installed PDFs if the outer API transaction fails; an existing content-addressed PDF is retained.
* `POST /copies`, `/stock`, `/wishes` and `/wishes/{id}/to-owned` return `{ids: [...]}` because one request can create several records. Creates resolve their catalogue identities with `add.lookup`. Stock additions pass condition, storage and lot into `stock.add_loose` through `add.confirm` before merging; existing quantity is never relocated by a create. A stock create adds quantity without a duplicate-decision prompt. Wishes retain decimal max prices and their currency. To-owned accepts part or all of the wished quantity and archives the wish only when fully moved.
* Archive responses for copies, stock, wishes, storages and lots carry the archived record. Place, flag and instruction archive responses carry `{id, archived: true}`. Every archived M3 resource has an explicit restore action. API instruction attachments and label edits request guarded collection receipts from the shared core helpers; the web retains its existing attachment and label audit shapes.
* `collection.save(expect=...)` checks If-Match after taking the write lock. Only the documented PATCH and DELETE operations on copies, stock, and wishes accept `If-Match`; other writes reject it with `400 bad_request`. Read tokens cannot write; write tokens can Undo collection receipts, while credential Undo still requires admin.
* M3 embeds collection, add, workbench, ledger and planning receipts. Creation Undo archives new records, preserving catalogue and queued-import provenance, as the existing core rules do. Existing records are restored exactly; later edits block Undo. Orders and source jobs remain in their later milestones.
* `scripts/generate_api_writes.py` generates the transport's request metadata from the YAML; its consistency test prevents drift. The OpenAPI route and closed-response contract harness includes M3.

## M4 implementation alignment (4.11f)

* Part, figure, bulk, loose-figure-part and "Set is checked" writes call `checker.write` with a stateless action; the counts are bounded by the same `checker.mark_row` the browser session uses, recomputing completeness with `completeness.derived_state` inside the same transaction. Missing parts of a figure count on the figure (`parts_lines`, `parts_missing` on `GET /copies/{id}/figures`), never on the set. Direct marking leaves browser session progress alone.
* `POST /copies/{id}/parts/bulk` matches lines by part number and colour among top-level, non-spare lines; `mode` is `set` (default) or `add`. Lines that are absent or ambiguous come back in `skipped`. With `dry_run: true` the request runs inside a savepoint that is rolled back: nothing is stored, `event_id` and `undo_url` are `null`, and no key is stored.
* Manual prices (`POST /items/{type}/{no}/prices`, `POST /prices/observations`, at most 500 per batch) go through `manual_prices.record` and `sources.base.observation` with source `manual`. One batch is one receipt. Undo voids each observation (`error='undone'`), keeps the history, and recomputes `price_current` from the latest non-void observation with the same full key (decision 12).
* Restore for copies, stock, wishes, storages, lots, places, flags and instruction files and wish-to-owned shipped in M3 and are unchanged.
* `PUT /copies/{id}/checked` with `checked: false` when no "Set is checked" flag exists creates nothing. It returns 200 with the current completeness and one API event whose receipt has no changes, so its Undo does nothing. Price items require `item_type` as one of S, M, P, I, O, G, B, C; a missing or unknown type is 422 `validation_failed` before any catalogue lookup.


## M5 implementation alignment (4.11g)

* **Key store.** `core/keys.py` is the one service for the API and the Catalogues & keys page. A key bundle (JSON of the source's environment variable names to values) is encrypted with Fernet (`BW_SECRET_KEY`) into `source_keys.ciphertext`; the plaintext never reaches a response, page, log line, error text, event row or export. Resolution is **per source: the complete set of environment variables wins; otherwise the live stored bundle is decrypted for the request; otherwise `source_not_configured`**. A partly set environment is ignored. Every source client resolves its credentials through `Source.credential_values()`, and `redact()` also masks stored values this process has decrypted. A stored key that cannot be decrypted (wrong or missing secret) fails closed as `source_not_configured` with fixed text. Values are checked for 8 to 256 printable characters without spaces; the error text never repeats them.
* **Writes.** `PUT /sources/{source}/key` takes `{key}` (Rebrickable, Brickset) or `{consumer_key, consumer_secret, token_value, token_secret}` (BrickLink). Without `BW_SECRET_KEY` it answers `424 source_not_configured` ("Key entry is disabled"). `DELETE` archives the row (the source stops using it). Both are one transaction and one event; Undo restores the exact previous state (`source_key_previous` holds one level of the replaced ciphertext, so no ciphertext is ever in an event; Undo is blocked when the key changed since). Network-bound operations (`detached`) claim their `Idempotency-Key` in the first transaction: a concurrent duplicate is `409 idempotency_conflict` while the first runs, and a failed action releases the claim. Replay of a `PUT` compares a keyed fingerprint (HMAC with `BW_SECRET_KEY`), never a plain hash of the body. `POST /sources/{source}/key/test` makes one budgeted call (BrickLink `/colors/1`, Rebrickable `/colors/0/`, Brickset `checkKey`) and returns `{source, ok, checked_at}`; failures are the usual redacted source errors. Brickognize and the catalogue need no key: `422`.
* **Page.** Catalogues & keys shows the key origin (environment or stored) and `saved_at` per source, a write-only password form per keyed source (BrickLink has four fields; nothing is ever put in a `value` attribute), Remove and Test buttons, and a clear message when `BW_SECRET_KEY` is missing. The forms post to the same page with the same CSRF token as the other Manage forms and call the same core functions. A fresh install lists every source client so keys can be entered before first use.
* **Export.** `GET /database/export` (and the Manage download) no longer refuses when keys are stored: the in-memory copy has `source_keys` and `source_key_previous` emptied (secure delete plus VACUUM) and key events blanked. A copy that would still contain a known plaintext credential is refused with `409`.
* **Typed errors.** `source_not_configured` and `source_disabled` come from every source client before any request is built or charged; `catalogue_not_loaded` from the local identity step. A failed pipeline step stores its stable `error_code` (`JobStep.error_code`). `problem+json` carries `source`, `retry_after` and `job_id` where they apply.
* **Budgets.** Queued work never errors: the job becomes `waiting_for_budget` with `retry_at`. Synchronous calls (`POST /colors/sync`, `POST /sources/{source}/key/test`, `POST /identifications`) answer `429 budget_exhausted` (own daily budget) or `429 source_throttled` (the provider asked to wait), with `Retry-After`, `retry_after` and the `job_id` that holds the call.
* **Jobs.** `retry`, `resume`, `instruction-identities` and `pictures` queue inside the request transaction and answer `202` (the instruction-identities list answers `202` with `{jobs, skipped}`); `retry` with no failed step and `resume` of a finished job are `409`. Running happens outside the transaction: the embedded drainer (one per app, started by `core/drainer.start` from the API and the web app alike; `BW_EMBEDDED_WORKER=0` disables it everywhere for headless installs that run `brickwork worker`) or `POST /jobs/drain`, which runs due jobs in the request and records one receipt-less event. A repeated identical picture refresh returns the active job. Retry, resume, drain and queueing are never undoable.
* **Sources.** `PATCH /sources/{source}` (admin) registers the client if needed, flips `enabled` in one event and is undoable. `POST /catalogue/import` rebuilds the catalogue index from the XML files in `bricklink-catalog-src/` beside the resolved database file (one resolver, `bricklink_catalogue.source_directory`, shared with the Manage action; no path or URL parameter; `422` when the folder is empty); `POST /colors/sync` pulls colours with one budgeted call. Both are admin scope and not undoable.
* **Uploads.** Photos for copies and stock (`POST /copies/{id}/photos`, `POST /stock/{id}/photos`): multipart `file` (an `image/*` part, at most 15 MB, decodable, at most 30 megapixels) and optional `caption`; wrong type `415`, too large `413`, unreadable `422`; one `bw_collection` photo receipt, Undo through the existing `collection.undo`; a failed request removes the new file. Identification (`POST /identifications`): multipart `file` only, `image/*`, at most 8 MB; the image is re-encoded as a JPEG of at most 1600 px (metadata dropped), sent to Brickognize through its budgeted client, and only a clean 256 px thumbnail is kept (`data/identifications/{id}.jpg`) with the candidates (`item_type`, `item_no`, `score`, catalogue `name` or null). `DELETE /identifications/{id}` archives (`archived_at`, schema addition) and Undo restores; Undo of an upload archives it. Archived records and thumbnails are hidden: `GET /identifications/{id}` is `404` unless `?archived=true`; `DELETE` still finds its own row. `missing_count` is `0` for API-created records.


## M6 implementation alignment (4.11h)

* Order import, matching, holding, document phases, received counts, allocation and reconcile wrap `orders.*`, with savepoints inside the API operation transaction. Each request records one operation event with embedded ledger receipts. Duplicate-document imports record an empty ledger receipt and return the existing ids; their Undo is a no-op. Import Undo retains orders, lines and catalogue provenance and marks the document `undone`, following `ledger.undo`.
* Email and XML are JSON `text` documents (maximum 1 MiB; larger text is `413 payload_too_large`). BrickLink pull uses `source: api` and `number` with the source client's encrypted/environment key resolution and budget. It claims the replay key before fetching; the fetched data is imported together with the API receipt in the final transaction. A failed final audit rolls back the entire import. Source call jobs and budget charges remain as provenance and are not undone.
* Allocation review (`GET /orders/{id}/allocation-review`), allocation records (`GET /orders/{id}/allocations`) and ledger history (`GET /orders/{id}/history`) are cursor-paginated and load with a constant query count. History includes embedded API ledger receipts and their parent event ids for `POST /events/{id}/undo`.
* `POST /orders/{id}/allocate` confirms `chosen` allocations atomically, using current received quantities and gap guards. v3 has no partially applied reservations to drain: `POST /orders/{id}/allocations/retry` accepts the same reviewed `chosen` shape and calls the same allocator. Replay of a successful confirm uses its original key; retrying revised choices uses a new key. Both quantity actions require Idempotency-Key. Undo is through the ledger operation event and reverses the whole confirm.
* `OrderReceived.counts` and `OrderPhase.pairs` are maps of numeric line ids to integer counts/ids; `OrderAllocate.chosen` is a bounded array of typed allocation choices. Unknown or invalid fields are rejected before a write. Missing order, line or document ids return `404 not_found`.
* The dispatcher covers collection, add, workbench, ledger, planning, manual-price, token, source-key, source-toggle, identification, part-inventory and checker receipts. `part_inventory.undo` composes through a savepoint; checker event Undo shares the web snapshot guard and restoration, including figure sessions. Unsupported fields, Undo receipts and bundles containing unsupported receipt kinds are never advertised as undoable. Later changes return `409 undo_blocked`; already undone is a successful no-op. One registry supplies the embedded receipt predicate to capture, dispatch and event-list SQL. No schema change.

## M7 implementation alignment (4.11i)

The MCP adapter exposes the 30 read tools, 27 gated write tools and eight resources from section 7. Both SDK transports use the same OpenAPI-derived schemas and the API auth path. There is no schema migration. Two queue routes required by the tool table were missing: `POST /items/{type}/{no}/import` and `POST /items/{type}/{no}/prices/refresh` now wrap `core.api_jobs.queue_item`, `add.lookup` and `Pipeline.queue_steps`. Both resolve identity from the BrickLink catalogue, queue without network, return 202 with one API event and `undo_url: null`, support idempotent replay, and start the embedded worker. A price refresh accepts an empty object and queues the whole item's shared `market_price` step; the draft's unused variant arguments were removed rather than silently ignored. Source credentials are needed when the worker executes the step.

## M8 / M9 implementation alignment (4.11j)

The v3 UI is the sole browser surface. The old API blueprints, shared-token setting, external price-refresh integration, upstream socket handlers and both legacy stores are removed. Browser paths drop their prefix with no redirects; the full [old-to-new path table](cutover-4.11j.md) includes methods and backing functions. The sole legacy reader is the `core.importer` module, shared by CLI and Tools & Admin, with a neutral optional `--extras` input. This milestone adds no API operations and no schema migration. Historical 3.2 literals remain only where the existing upgrade and proof require them.

`scripts/check.sh` explicitly runs `tests/test_standalone_smoke.py`, then the full suite. The smoke uses the complete app and CLI setup with socket and DNS calls blocked, generated bootstrap auth, a tiny XML catalogue and synthetic inventory, local writes, price Undo and typed missing-key errors. Price refresh queues without credentials; running a price-only job reports `source_not_configured` without a network attempt.

## Named wishlists

Wishlist rows now carry `list_id` (default `default`). `GET /wishes?list={id}` scopes rows to a list. `GET/POST /wishlists`, `PATCH/DELETE /wishlists/{id}`, and `POST /wishlists/{id}/restore` manage list receipts; archive includes its live wishes. `POST /wishlists/{id}/transfer` takes `ids` and optional `copy` (`false` moves, `true` copies) with the path id as the target. Collisions reject the whole transfer. All writes retain the normal Idempotency-Key and event Undo semantics.

`GET /wishlists/{id}/export.xml` downloads BrickLink wanted list XML. `GET /wishlists/{id}/export.csv?kind=sets|parts` downloads Rebrickable CSV through stored identity mappings. `id=all` includes every active list. `summary=true` returns `data: {content, summary, filename, mimetype}`; the summary includes exported count, omitted rows and notes such as currency-incompatible limits. Direct download responses expose the three counts through `X-Wishlist-Exported`, `X-Wishlist-Omitted`, `X-Wishlist-Notes`. See [formats, schema and CLI examples](wishlists.md) for exact headers, mapping policy and documentation verification limits.
