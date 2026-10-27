# Brick Work API v2: contract

**Status:** the contract of the whole v2 surface, written for M.11a (issue #113, 2026-10-27). The transport, the meta endpoints and item addressing are implemented in M.11a; every other operation answers `501 not_implemented` until its piece (M.11b to M.11d) lands. The machine-readable twin is [openapi-v2.yaml](openapi-v2.yaml); the data model behind it is [data-model-design.md](../data-model-4.0/data-model-design.md) (sections 3.1, 3.2, 3.5, 3.6, 3.8 and 7).

**How to read this file.** v2 is v1 with the 4.0 identity, not a redesign ([api-v1.md](api-v1.md) is the v1 contract and stays as the reference for what v2 inherits). Section 1 says what changed and what did not. Section 2 holds the conventions, section 3 the resource catalogue with every v1 operation mapped to its v2 operation (or dropped, with the reason), section 4 the pieces and the 501 list. Each operation carries the piece that implements it: **M.11a** the contract, transport, meta and item addressing; **M.11b** the reads; **M.11c** the writes; **M.11d** orders, jobs, sources, keys, sync, imports, identifications, tokens and admin; **M.11e** the MCP regenerated from this file and the parity test (no operations of its own).

---

## 1. What changed from v1, and what did not

v1 answers `410 Gone` on the 4.0 line (its `/health` excepted) because it cannot represent local or unidentified items; the 410 text names `/api/v2` and this file.

**Unchanged** (a client changes only how it names items): envelopes (`data`, `page`, write receipts), cursor pagination and the filter vocabulary, `ETag` / `If-Match`, `Idempotency-Key`, problem+json errors with stable codes, bearer tokens with the `read` < `write` < `admin` scopes, `BW_API_TOKEN`, the throttle on failed token checks, read-only instances, archive instead of delete, one event per write with `via=api` and `actor` = token name, and Undo through `POST /events/{id}/undo`. The code behind them is shared with v1 (`brickwork/api/transport.py`).

**Changed:**

| Topic | v1 | v2 |
|---|---|---|
| Item address | `/items/{type}/{no}`, BrickLink type letter and number | `/items/{id}` (Brick Work id, per install) and number paths: `/sets/by-number/{no}`, `/parts/by-number/{no}`, `/minifigures/by-number/{no}`, `GET /lookup?provider=&kind=&key=` |
| Item in a body | `item_type`, `item_no` | `item: {id, kind, name, unidentified, bricklink: [{type, no, color_id, preferred}], rebrickable: {key} or null}` |
| Colour in a body | `color_id` (BrickLink) | `color: {id, name, rgb, bricklink_id, rebrickable_id}` |
| Item in a request | `item_type`, `item_no`, `color_id` | `item: {id}` or `item: {provider, kind, key}` and `color` in the same provider space; `422 unidentified` when the number resolves to nothing |
| The `?` type | placeholder type for unidentified items | gone: `unidentified: true` |
| Unresolved matches | `/unresolved`, `/id-matches` | links: `/links?status=to_check`, `/items/{id}/links`, `/items/{id}/provider-status`, merge and unmerge |
| Merged ids | none | `307` to the survivor on GET, `409 merged` on writes |
| Codes mapped to words | some stored as letters | words stored and served (Q8); the v1 mappings are dropped |
| Wish ids | integers | uuids (Q6) |
| Copy body | no part-list state | adds `inventory: {source, version, ordinal, of, pending, changed_since_build}` |
| Settings | v1 whitelist | adds `prefer_bricklink_inventory` and the picture order inside `source_priority` |
| Catalogue status | loaded, counts | builds (dump, mapping version, local mapping manifest, BrickLink list), coverage per link status, last reconcile |
| MCP | tools take BrickLink type and number | regenerated from this file; tools take numbers and a provider, never a Brick Work id; tool names stay where the operation exists |

**Ids are per install** (data model 3.1). A Brick Work id from one install means nothing in another, and a restore from a different archive can renumber. Clients store provider numbers and use ids only within a session.

---

## 2. Conventions

### 2.1 Identity and addressing

| Thing | Address | Notes |
|---|---|---|
| Item | `/items/{id}`, integer | Catalogue ids are running numbers from the catalogue build (up to six digits today); local items (BrickLink-born, API-born, unidentified) start at 1,000,000,000. An item the collection has not projected yet is still addressable: the read falls back to the attached catalogue. |
| Item by number | `/sets/by-number/{no}`, `/parts/by-number/{no}`, `/minifigures/by-number/{no}`, `GET /lookup?provider=&kind=&key=` | Same item body as `/items/{id}`, answered with `200`, not a redirect, so a client needs one round trip. |
| Colour | `color` query parameter or body member | In the provider's space (below). `GET /colors/{id}` takes a Brick Work colour id. |
| Copy, stock line, lot, storage, place, flag | uuid text | As v1. |
| Wish | uuid text | Was an integer. |
| Wishlist | text id (`default` for the first) | As v1. |
| Event, job, order, order line, instruction file | integer | As v1. |

**Number paths and `/lookup`** (decisions 2 to 4 of #113):

* `provider` is `bricklink` (the default) or `rebrickable`. BrickLink is the default because every current client, order e-mail and the House API speak BrickLink numbers. A set number is the same at both providers, so a set is looked up at both and the answers merge.
* `kind` is `set`, `part`, `minifigure`, `instructions`, `box`, `gear`, `book` or `catalog`; the three number paths fix it. Rebrickable has numbers only for sets, parts and minifigures; another kind with `provider=rebrickable` is `422`.
* A BrickLink number resolves through the item's links (every confirmed link: `manual`, `matched`, `inferred`) and through a BrickLink-born local item's own number. A Rebrickable number resolves through the born key.
* **Colour-scoped links.** With `color`, the colour is read in the provider's space (`bricklink`: a BrickLink colour id, `rebrickable`: a Rebrickable colour id) and the lookup is the inverse of the resolution function (data model 3.2): a link scoped to that colour applies, an unscoped link applies only when the item has none scoped to the colour (the leg rule), and a `manual` link decides alone. The answer then carries `data.color`, the resolved Brick Work colour, so a client can map provider colours. Without `color`, a link of any scope matches.
* One match is `200` with the item body. Several is `409 ambiguous` with `candidates` (item bodies) and the problem fields; none is `404`. A merged item found by number is followed to its survivor silently.
* Unknown query names are `400 unknown_filter`. A colour that names no colour, or a bad `kind` or `provider`, is `422 validation_failed`.

**Colours in a request** are in the provider's space (decision 4): a BrickLink colour id with `provider=bricklink`, a Rebrickable colour id with `provider=rebrickable`, and a Brick Work colour id with `provider=brickwork`. The `brickwork` space is for paths that already name the item by id (`/items/{id}/...`); on a number path it is `422`, since a Brick Work id is not a number.

**Item and colour bodies** (data model 7):

```json
{"id": 15011, "kind": "set", "name": "...", "unidentified": false,
 "bricklink": [{"type": "S", "no": "6081-1", "color_id": null, "preferred": true}],
 "rebrickable": {"key": "6081-1"}}
```

`bricklink` lists the confirmed BrickLink links, preferred first; a colour-scoped link names its BrickLink colour in `color_id`, an unscoped one has `null`. A BrickLink-born local item with no link of its own lists its born number. `rebrickable` is the born key or `null`. `unidentified` is true for a local item that is not born at Rebrickable (data model 3.8): no born key, or a BrickLink-only number. Every field of a row that names an item (`item`, `child`, `parent_minifig`, `part`, `figure`) carries this body, and every colour (`color`) the colour body `{id, name, rgb, bricklink_id, rebrickable_id}`.

**Merged ids** (decision 5, amended 2026-10-27):

* `GET` of a merged id (any `/items/{id}...` path) answers **`307 Temporary Redirect`** with `Location` to the same path under the survivor (the query string is kept), `Cache-Control: no-store` and a problem body (`code: moved`, `survivor`).
* **This deviates from data model 3.6 and 7, which say `301`.** A merge can be undone exactly (unmerge restores every moved row), and a cached permanent `301` would keep sending the unmerged id to the old survivor. `307` also keeps the method, though only `GET` redirects.
* A write that names a merged id is `409 merged` with `survivor`; nothing is written, since a client that silently writes to a moved id would surprise. `POST /items/{id}/unmerge` is the one write that names a merged id on purpose.

### 2.2 Value formats

As v1: money is a decimal **string** with a currency code `^[A-Z]{3,8}$`; time is ISO-8601 UTC with offset; dates the user types are stored as given. Stored words are served as stored (Q8): conditions `new`, `used` (stock adds `damaged`; wishes `new`, `used`, `any`), completeness `sealed`, `complete`, `incomplete` with `completeness_source` `manual` or `derived`, kinds as above. The v1 code-to-word mappings are gone because nothing is stored as a letter any more.

### 2.3 Envelopes

* Single read: `{"data": {...}}` with `ETag` on copies, stock and wishes.
* List: `{"data": [...], "page": {"next_cursor": "...|null", "limit": 50, "total": 123|null}}`.
* Write: `{"data": {...}, "event_id": 412, "undo_url": "/api/v2/events/412/undo", "idempotent_replay": false}`.
* Queued work: `202 Accepted`, the write envelope with the `Job` as `data`, header `Location: /api/v2/jobs/{id}`.
* Every response of the API carries `Cache-Control: no-store`.

### 2.4 Resource states

As v1: archived rows are hidden from lists (`archived=true|include|only`), a `GET` of an archived record returns it with `archived_at`, writes to one fail with `409 archived`.

### 2.5 Pagination, filters, sort

As v1: opaque `cursor`, `limit` 1 to 200 (default 50), `sort` and `direction` with a stable tie-break, unknown filter names are `400 unknown_filter`. The filters that named an item by BrickLink type and number change: `item_type` becomes `kind`, `item_no` becomes `number` with `provider`, and `color_id` / `colour` become `color` (in the `provider` space, default `bricklink`; `provider=brickwork` takes a Brick Work colour id). `type` on `GET /items` is `kind`.

### 2.6 ETag and If-Match

As v1: copies, stock and wishes carry an `ETag`; `PATCH`, `PUT` and `DELETE` accept `If-Match`; a mismatch is `412 precondition_failed` and nothing is written. `POST /copies/{id}/inventory` accepts `If-Match` as well, since a switch rewrites the copy's lines.

### 2.7 Idempotency

As v1: `Idempotency-Key: <1 to 80 characters of [A-Za-z0-9-]>`, stored in the one event row of the request; same key and body replays the stored response (`idempotent_replay: true`), another body is `409 idempotency_conflict`, a key is honoured for 30 days. **Required** on: creates (`POST /copies`, `/stock`, `/wishes`, `/found`, `/stock/booklets`, `/lots`), quantity moves (`/copies/{id}/take`, `/stock/{id}/give`, `/wishes/{id}/to-owned`, `/storages/{id}/contents`, `/copies/{id}/parts/bulk`), orders (`/orders/documents`, `/orders/{id}/allocate`, `/orders/{id}/allocations/retry`), prices (`/prices/observations`, `/items/{id}/prices`), `/events/{id}/undo`, and the v2 identity writes (`PUT /items/{id}/links`, `POST /items/{id}/merge`, `POST /items/{id}/unmerge`, `POST /copies/{id}/inventory`). A missing key is `428 idempotency_key_required`. Optional elsewhere.

### 2.8 Errors

Media type `application/problem+json`, as v1:

```json
{"type":"urn:brickwork:error:ambiguous","title":"Ambiguous","status":409,"code":"ambiguous",
 "detail":"bricklink part 3001 names 2 items; address one by id",
 "candidates":[{"id":44280,"kind":"part","name":"...","unidentified":false,"bricklink":[],"rebrickable":{"key":"3001"}}],
 "instance":"/api/v2/parts/by-number/3001"}
```

Optional members: `retry_after`, `job_id`, `source`, and in v2 `candidates` (with `ambiguous`), `survivor` (with `merged` and `moved`), `piece` and `error` (with `not_implemented`). Codes and statuses are in Appendix A; `x-error-status` in the OpenAPI file lists the same table. A path under `/api/v2` that does not exist is `404 not_found` and a wrong method `405 method_not_allowed` with `Allow`, both problem+json.

### 2.9 Authentication, scopes, tokens

As v1: `Authorization: Bearer <token>`; `read` < `write` < `admin`; `BW_API_TOKEN` is a bootstrap admin token named `bootstrap`; stored tokens are hashed, scoped and may expire; with neither, `503 api_disabled`. `/health` and `/openapi.yaml` need no token. `BW_READ_ONLY` makes every non-`GET` `403 read_only_instance` whatever the scope. Failed token checks back off per client (`429 too_many_attempts`, `Retry-After`); forwarded addresses count only with `BW_TRUSTED_PROXIES`. **The scope of every v2 operation is the one its `security` entry in `openapi-v2.yaml` names**; the blueprint reads it from there, so the contract is the single place that says who may call what. Request bodies are refused unread over their cap (JSON 4 MB, uploads per route) with `413 payload_too_large`.

---

## 3. Resource catalogue

### 3.1 Summary

189 operations in all (M.11a 9, M.11b 57, M.11c 65, M.11d 58 by piece); v1 had 179 operations.

| Group | Operations | Pieces |
|---|---|---|
| Meta | 4 | M.11a 4 |
| Catalogue | 5 | M.11b 5 |
| Items | 8 | M.11a 1, M.11b 6, M.11d 1 |
| Identity | 10 | M.11a 4, M.11b 3, M.11c 3 |
| Images | 1 | M.11b 1 |
| Copies | 18 | M.11b 6, M.11c 12 |
| Copy parts | 5 | M.11b 2, M.11c 3 |
| Loose stock | 13 | M.11b 3, M.11c 10 |
| Minifigures | 2 | M.11b 2 |
| Instructions | 7 | M.11b 3, M.11c 4 |
| Prices | 8 | M.11b 4, M.11c 2, M.11d 2 |
| Wishlist | 16 | M.11b 5, M.11c 11 |
| Storages | 7 | M.11b 2, M.11c 5 |
| Lots | 6 | M.11b 2, M.11c 4 |
| Places | 5 | M.11b 1, M.11c 4 |
| Flags | 5 | M.11b 1, M.11c 4 |
| Planning | 6 | M.11b 6 |
| Orders | 15 | M.11d 15 |
| Events | 3 | M.11b 2, M.11c 1 |
| Jobs | 7 | M.11d 7 |
| Sources | 7 | M.11d 7 |
| Settings | 5 | M.11c 2, M.11d 3 |
| Admin | 10 | M.11b 1, M.11d 9 |
| Matching | 2 | M.11b 2 |
| Tokens | 3 | M.11d 3 |

### 3.2 Operations

Scope `none` means no token. Every path is relative to `/api/v2`. The **v1** column names the v1 operation the row replaces when its path changed, says `same` when the path is unchanged and **NEW** when v1 had no such operation. Write rows are one transaction plus one event; the receipt kinds and Undo dispatch per write group are v1's ([api-v1.md](api-v1.md) section 4) and move to this file with M.11c.

#### Meta

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `GET /health` | Liveness, app, schema and API version. No token. | none | M.11a | same |
| `GET /me` | The calling token: name, scopes, expiry. | read | M.11a | same |
| `GET /openapi.yaml` | This contract as OpenAPI 3.1 YAML. No token. | none | M.11a | same |
| `GET /version` | Build, API and schema versions, enabled features. | read | M.11a | same |

#### Catalogue

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `GET /catalogue/items` | Search the local BrickLink catalogue file by type and text. | read | M.11b | same |
| `GET /catalogue/items/{id}` | One catalogue entry. | read | M.11b | `GET /catalogue/items/{type}/{no}` |
| `GET /catalogue/status` | Catalogue file state (loaded, item counts, imported_at). | read | M.11b | same |
| `GET /colors` | All colours. | read | M.11b | same |
| `GET /colors/{color_id}` | One colour. | read | M.11b | same |

#### Items

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `GET /items` | Items known to the store, with text search over name, number and properties. | read | M.11b | same |
| `GET /items/{id}` | Item detail: properties, counts, owned and wished summary. | read | M.11a | `GET /items/{type}/{no}` |
| `GET /items/{id}/colors` | Colours this part is known in. | read | M.11b | `GET /items/{type}/{no}/colors` |
| `GET /items/{id}/detail` | Item detail: properties, counts, owned and wished summary, prices, matches (what v1's GET /items/{type}/{no} returned). | read | M.11b | **NEW** |
| `GET /items/{id}/images` | Local pictures of the item. | read | M.11b | `GET /items/{type}/{no}/images` |
| `POST /items/{id}/import` | Create the item identity and queue the six import steps. | write | M.11d | `POST /items/{type}/{no}/import` |
| `GET /items/{id}/inventory` | Parts and figures the item is made of (inventory lines). | read | M.11b | `GET /items/{type}/{no}/inventory` |
| `GET /items/{id}/used-in` | Owned copies that contain this part or figure. | read | M.11b | `GET /items/{type}/{no}/used-in` |

#### Identity

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `GET /items/{id}/links` | The item's provider links with status, method, origin, preferred and colour scope (design 3.2), to-check candidates included. | read | M.11b | **NEW** |
| `PUT /items/{id}/links` | Set one manual link of the item, or make one preferred for its colour scope (design 3.2). Idempotent per (provider, type, number, colour). | write | M.11c | **NEW** |
| `POST /items/{id}/merge` | Merge this local item into a survivor (design 3.6): every reference moves, the id answers 307 to the survivor afterwards. Refused for a live catalogue item. | write | M.11c | **NEW** |
| `GET /items/{id}/provider-status` | What is known about the item at a provider when there is no key: looked and nothing found, to check without candidate, kind differs (design 3.2). | read | M.11b | **NEW** |
| `POST /items/{id}/unmerge` | Undo a merge by its receipt (design 3.6): the merged id answers for itself again. Refused if a moved row changed since. | write | M.11c | **NEW** |
| `GET /links` | Links and provider statuses across items, by status: status=to_check is the list that replaces v1's /unresolved. | read | M.11b | **NEW** |
| `GET /lookup` | Find the item for any provider number: provider, kind and key (and a colour in the provider space). Same body and errors as the by-number paths. | read | M.11a | **NEW** |
| `GET /minifigures/by-number/{no}` | Find the item for a minifigure number; the same item body as /items/{id} (decision 2). Default provider bricklink; provider=rebrickable for Rebrickable numbers. Several items answer 409 ambiguous with the candidates, none 404. | read | M.11a | **NEW** |
| `GET /parts/by-number/{no}` | Find the item for a part number; the same item body as /items/{id} (decision 2). Default provider bricklink; provider=rebrickable for Rebrickable numbers. Several items answer 409 ambiguous with the candidates, none 404. | read | M.11a | **NEW** |
| `GET /sets/by-number/{no}` | Find the item for a set number; the same item body as /items/{id} (decision 2). A set number is the same at both providers. Several items answer 409 ambiguous with the candidates, none 404. | read | M.11a | **NEW** |

#### Images

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `GET /images/{id}/content` | Image bytes from the local picture store. | read | M.11b | same |

#### Copies

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `GET /copies` | Owned set copies. | read | M.11b | same |
| `POST /copies` | Add owned copies of a set (quantity N makes N copies) and queue its import. | write | M.11c | same |
| `DELETE /copies/{id}` | Archive the copy (the UI calls this deleting a set). | write | M.11c | same |
| `GET /copies/{id}` | One copy. | read | M.11b | same |
| `PATCH /copies/{id}` | Edit condition, completeness, storage, purchase and estimate fields, note. | write | M.11c | same |
| `GET /copies/{id}/check` | Part-check session state for this copy. | read | M.11b | same |
| `POST /copies/{id}/check` | Apply one part-check action (start, answer, found_one, skip, select, back, next, spares, finish, undo). | write | M.11c | same |
| `PUT /copies/{id}/checked` | Set or clear the "Set is checked" flag and recompute derived completeness. | write | M.11c | same |
| `GET /copies/{id}/completeness` | Stored and derived completeness, checked flag, missing and damaged counts. | read | M.11b | same |
| `PUT /copies/{id}/flags` | Replace the copy flags. | write | M.11c | same |
| `GET /copies/{id}/gaps` | Missing, damaged and absent items of the copy. | read | M.11b | same |
| `POST /copies/{id}/inventory` | Switch the copy's part list in place (design 4.4): to Rebrickable (a version) or BrickLink. A BrickLink switch is pending until its fetch job lands. | write | M.11c | **NEW** |
| `DELETE /copies/{id}/inventory/pending` | Cancel a pending BrickLink switch (design 4.4): the copy keeps its current list. | write | M.11c | **NEW** |
| `GET /copies/{id}/matches` | Loose stock that would fill the copy gaps. | read | M.11b | same |
| `POST /copies/{id}/photos` | Upload an own photo (multipart, 15 MB). | write | M.11c | same |
| `PUT /copies/{id}/pin` | Pin or unpin a copy. | write | M.11c | same |
| `POST /copies/{id}/restore` | Clear the archive mark. | write | M.11c | same |
| `POST /copies/{id}/take` | Take N of one missing part (with colour) or whole minifigure (no colour) from loose stock into the copy. | write | M.11c | same |

#### Copy parts

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `GET /copies/{id}/figures` | Whole figures of the copy. | read | M.11b | same |
| `PATCH /copies/{id}/figures/{item_id}` | Set the missing count of one whole figure. | write | M.11c | `PATCH /copies/{id}/figures/{type}/{no}` |
| `GET /copies/{id}/parts` | Part lines of the copy (required, spare, figure components). | read | M.11b | same |
| `POST /copies/{id}/parts/bulk` | Apply missing counts to many lines by item and colour (mode set or add, optional dry run). | write | M.11c | same |
| `PATCH /copies/{id}/parts/{part_id}` | Set missing, damaged, checked for one line (mark missing or found). | write | M.11c | same |

#### Loose stock

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `POST /found` | Record found parts into copies, a loose line, or a list. | write | M.11c | same |
| `GET /stock` | Loose stock lines (parts, minifigures, booklets, anything). | read | M.11b | same |
| `POST /stock` | Add loose stock; identical lines merge. | write | M.11c | same |
| `POST /stock/booklets` | Add loose booklets from lines "set number, quantity". | write | M.11c | same |
| `DELETE /stock/{id}` | Archive the line. | write | M.11c | same |
| `GET /stock/{id}` | One stock line. | read | M.11b | same |
| `PATCH /stock/{id}` | Edit a stock line (may merge into an existing line; response lists merged ids). | write | M.11c | same |
| `PUT /stock/{id}/flags` | Replace the line flags. | write | M.11c | same |
| `POST /stock/{id}/give` | Give N from this line to a copy gap or a loose-figure part gap. | write | M.11c | same |
| `GET /stock/{id}/parts` | Parts of a loose minifigure. | read | M.11b | same |
| `PATCH /stock/{id}/parts` | Set missing and damaged on parts of a loose minifigure. | write | M.11c | same |
| `POST /stock/{id}/photos` | Upload an own photo (multipart, 15 MB). | write | M.11c | same |
| `POST /stock/{id}/restore` | Clear the archive mark. | write | M.11c | same |

#### Minifigures

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `GET /minifigures` | Figures by identity: owned in sets, loose, missing. | read | M.11b | same |
| `GET /minifigures/{id}` | One figure: sets, loose lines, missing, matches, prices. | read | M.11b | `GET /minifigures/{no}` |

#### Instructions

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `GET /instruction-files` | Booklet files and booklet identities with coverage. | read | M.11b | same |
| `POST /instruction-files` | Attach a PDF (multipart, up to 20 MB) to an item. | write | M.11c | same |
| `DELETE /instruction-files/{id}` | Archive a PDF association. | write | M.11c | same |
| `GET /instruction-files/{id}` | One file record. | read | M.11b | same |
| `PATCH /instruction-files/{id}` | Rename the label. | write | M.11c | same |
| `GET /instruction-files/{id}/content` | Download the PDF. | read | M.11b | same |
| `POST /instruction-files/{id}/restore` | Restore an archived record. | write | M.11c | same |

#### Prices

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `GET /items/{id}/prices` | Current prices and recorded observations of one item. | read | M.11b | `GET /items/{type}/{no}/prices` |
| `POST /items/{id}/prices` | Record one manual or valuation observation. | write | M.11c | `POST /items/{type}/{no}/prices` |
| `GET /items/{id}/prices/history` | Observation history of one item. | read | M.11b | `GET /items/{type}/{no}/prices/history` |
| `POST /items/{id}/prices/refresh` | Queue a market price refresh for one item. | write | M.11d | `POST /items/{type}/{no}/prices/refresh` |
| `GET /prices` | Current price per item, colour, condition and guide. | read | M.11b | same |
| `POST /prices/observations` | Record up to 500 observations in one transaction. | write | M.11c | same |
| `POST /prices/refresh` | Queue refresh jobs for every stale item. | write | M.11d | same |
| `GET /prices/stale` | Items whose price is older than the freshness rule. | read | M.11b | same |

#### Wishlist

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `GET /wishes` | Wishlist rows; under_max filters to rows priced under the wish maximum. | read | M.11b | same |
| `POST /wishes` | Add a wish (same colour and item adds to the live row on decision=another). | write | M.11c | same |
| `DELETE /wishes/{id}` | Archive the wish. | write | M.11c | same |
| `GET /wishes/{id}` | One wish. | read | M.11b | same |
| `PATCH /wishes/{id}` | Edit quantity, colour, condition, max price and currency, note. | write | M.11c | same |
| `PUT /wishes/{id}/flags` | Replace the wish flags. | write | M.11c | same |
| `POST /wishes/{id}/restore` | Restore an archived wish. | write | M.11c | same |
| `POST /wishes/{id}/to-owned` | Turn a wish into owned copies and archive the wish, one transaction. | write | M.11c | same |
| `GET /wishlists` | get wishlists | read | M.11b | same |
| `POST /wishlists` | post wishlists | write | M.11c | same |
| `DELETE /wishlists/{id}` | delete wishlists id | write | M.11c | same |
| `PATCH /wishlists/{id}` | patch wishlists id | write | M.11c | same |
| `GET /wishlists/{id}/export.csv` | Export wishlist as Rebrickable CSV | read | M.11b | same |
| `GET /wishlists/{id}/export.xml` | Export wishlist as BrickLink wanted list XML | read | M.11b | same |
| `POST /wishlists/{id}/restore` | post wishlists id restore | write | M.11c | same |
| `POST /wishlists/{id}/transfer` | post wishlists id transfer | write | M.11c | same |

#### Storages

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `GET /storages` | Active storages with counts, plus the virtual "Not stored". | read | M.11b | same |
| `POST /storages` | Create a storage. | write | M.11c | same |
| `DELETE /storages/{id}` | Archive; refuses non-empty unless move_to_unstored=true. | write | M.11c | same |
| `GET /storages/{id}` | Storage with its contents. | read | M.11b | same |
| `PATCH /storages/{id}` | Rename. | write | M.11c | same |
| `POST /storages/{id}/contents` | Move copies, stock and lots into this storage (id "unstored" for none). A lot carries its parts that sit in the lot's own storage, in the same receipt. | write | M.11c | same |
| `POST /storages/{id}/restore` | Restore an archived record. | write | M.11c | same |

#### Lots

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `GET /lots` | Part lots. | read | M.11b | same |
| `POST /lots` | Create a lot from existing stock lines. | write | M.11c | same |
| `DELETE /lots/{id}` | Archive the lot. | write | M.11c | same |
| `GET /lots/{id}` | Lot with its stock. | read | M.11b | same |
| `PATCH /lots/{id}` | Edit name, note, storage, purchase fields. | write | M.11c | same |
| `POST /lots/{id}/restore` | Restore an archived record. | write | M.11c | same |

#### Places

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `GET /places` | Purchase locations with counts and totals per currency. | read | M.11b | same |
| `POST /places` | Create a purchase location. | write | M.11c | same |
| `DELETE /places/{id}` | Archive, retaining references. Undo restores the place. | write | M.11c | same |
| `PATCH /places/{id}` | Rename. | write | M.11c | same |
| `POST /places/{id}/restore` | Restore an archived record. | write | M.11c | same |

#### Flags

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `GET /flags` | Flags of kind owner, status and tag. | read | M.11b | same |
| `POST /flags` | Create a flag. | write | M.11c | same |
| `DELETE /flags/{id}` | Archive, retaining flag links. Undo restores the flag. | write | M.11c | same |
| `PATCH /flags/{id}` | Rename. | write | M.11c | same |
| `POST /flags/{id}/restore` | Restore an archived record. | write | M.11c | same |

#### Planning

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `GET /export/missing.csv` | Missing parts of the chosen copies as CSV (the printable list, #43). | read | M.11b | same |
| `GET /export/missing.json` | The same missing-item aggregation and eligibility as XML, returned as JSON. | read | M.11b | same |
| `GET /export/missing.xml` | BrickLink wanted-list XML of missing items for chosen copies. | read | M.11b | same |
| `GET /export/picker.csv` | Part Picker results for the chosen copies as CSV, in pick order (#43). | read | M.11b | same |
| `GET /export/wishlist.csv` | The wishlist (one list or all) as CSV (#43). | read | M.11b | same |
| `GET /planning/ranking` | Owned copies ranked by cost to complete, with the repair settings used. | read | M.11b | same |

#### Orders

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `GET /orders` | Orders with line and receipt state. | read | M.11d | same |
| `POST /orders/documents` | Import an order document: pasted email, BrickLink XML, or fetch by order number with the user key. | write | M.11d | same |
| `GET /orders/export.csv` | Saved order lines (kind=lines) or one row per order with new and used totals (kind=summary) as CSV, filtered by order date and store (#44). Totals never mix currencies. | read | M.11d | same |
| `GET /orders/{id}` | Order with documents and lines. | read | M.11d | same |
| `POST /orders/{id}/allocate` | Allocate received lines to copies or stock. | write | M.11d | same |
| `GET /orders/{id}/allocation-review` | Saved lines, available received quantities and current copy-gap destinations, paginated. | read | M.11d | same |
| `GET /orders/{id}/allocations` | Allocation history, paginated. | read | M.11d | same |
| `POST /orders/{id}/allocations/retry` | Retry reviewed `chosen` allocations against current counts and gaps. Requires an Idempotency-Key. | write | M.11d | same |
| `POST /orders/{id}/documents/{doc_id}/phase` | Move a document: review, reopen or save. | write | M.11d | same |
| `GET /orders/{id}/history` | Ledger receipts from web and API operations, with Undo state, paginated. | read | M.11d | same |
| `PATCH /orders/{id}/lines/{line_id}` | Match a line to a catalogue identity. | write | M.11d | same |
| `PUT /orders/{id}/lines/{line_id}/hold` | Hold or release a line. | write | M.11d | same |
| `POST /orders/{id}/received` | Record received counts per line. | write | M.11d | same |
| `POST /orders/{id}/reconcile` | Reconcile the order. | write | M.11d | same |
| `GET /orders/{id}/short.xml` | BrickLink XML of the still-missing lines. | read | M.11d | same |

#### Events

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `GET /events` | Audit events, newest first. | read | M.11b | same |
| `GET /events/{id}` | One event with old and new values. | read | M.11b | same |
| `POST /events/{id}/undo` | Undo a receipt event. One endpoint for all receipt kinds. | write | M.11c | same |

#### Jobs

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `GET /jobs` | Import and refresh jobs with steps. | read | M.11d | same |
| `POST /jobs/drain` | Run one drain of due jobs in the request worker. | write | M.11d | same |
| `POST /jobs/instruction-identities` | Queue identity refresh for booklets without a file. | write | M.11d | same |
| `POST /jobs/pictures` | Queue a picture refresh for a scope. | write | M.11d | same |
| `GET /jobs/{id}` | One job. | read | M.11d | same |
| `POST /jobs/{id}/resume` | Resume an interrupted or budget-waiting job; a failed job needs retry. | write | M.11d | same |
| `POST /jobs/{id}/retry` | Retry failed steps (all, or one step). | write | M.11d | same |

#### Sources

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `POST /catalogue/import` | Rebuild the catalogue file from the configured BrickLink XML directory. | admin | M.11d | same |
| `POST /colors/sync` | Pull colours from BrickLink with the user key. | admin | M.11d | same |
| `GET /sources` | Sources with key state (configured yes or no), budget, usage today, last success and error. | read | M.11d | same |
| `PATCH /sources/{source}` | Enable or disable a source. | admin | M.11d | same |
| `DELETE /sources/{source}/key` | Archive stored key; Undo restores it. | admin | M.11d | same |
| `PUT /sources/{source}/key` | Store an encrypted source key (replaces a stored one). Write-only. | admin | M.11d | same |
| `POST /sources/{source}/key/test` | One budgeted call with the key in use; the result carries no key material. | admin | M.11d | same |

#### Settings

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `GET /exchange-rates` | Exchange rates per 1 EUR (hand-entered or ECB) and the display currency (#39). Stored amounts never change currency. | read | M.11d | same |
| `POST /exchange-rates/ecb` | Load the ECB daily reference rates (one keyless request); hand-entered rates are kept. | admin | M.11d | same |
| `PUT /exchange-rates/{code}` | Enter (or with null remove) one rate per 1 EUR by hand. | admin | M.11d | same |
| `GET /settings` | Allowed settings and freshness rules. | read | M.11c | same |
| `PATCH /settings` | Update allowed settings (whitelist). | admin | M.11c | same |

#### Admin

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `GET /database/check` | Integrity, foreign-key check and row counts. | admin | M.11d | same |
| `GET /database/export` | SQLite snapshot download. Stored source keys, even encrypted, are removed from the copy; refuses (409) if known plaintext credentials would remain. | admin | M.11d | same |
| `GET /identifications` | Photo identification history; archived rows hidden. | read | M.11d | same |
| `POST /identifications` | Upload an image for Brickognize identification (image, up to 8 MB). | write | M.11d | same |
| `DELETE /identifications/{id}` | Archive identification; Undo restores it. | write | M.11d | same |
| `GET /identifications/{id}` | Identification result. | read | M.11d | same |
| `GET /identifications/{id}/thumb` | Thumbnail bytes. | read | M.11d | same |
| `POST /imports/bricktracker` | Upload a BrickTracker app.db (any upstream version, up to 200 MB) and get an import plan. A copy is upgraded with upstream's migrations and compared with this collection; nothing is written to the collection. | admin | M.11d | same |
| `POST /imports/{id}/apply` | Apply an import plan: rows marked add are written in one transaction; locked rows (already imported, duplicate wishes) are always skipped. Undo with POST /events/{id}/undo (admin). | admin | M.11d | same |
| `GET /statistics` | Counts by completeness, theme, storage, place. | read | M.11b | same |

#### Matching

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `GET /gaps` | Missing items over all copies and loose figures. | read | M.11b | same |
| `GET /matches` | Suggestions: loose stock that fills a gap. | read | M.11b | same |

#### Tokens

| Operation | What it does | Scope | Piece | v1 |
|---|---|---|---|---|
| `GET /tokens` | Tokens including revoked rows; cursor, limit and direction. Never the secret or hash. | admin | M.11d | same |
| `POST /tokens` | Create a token. The secret is shown once in this response. | admin | M.11d | same |
| `DELETE /tokens/{id}` | Revoke a token; a second revocation is `409 conflict`. | admin | M.11d | same |


### 3.3 Dropped v1 operations

| v1 operation | Why it is gone |
|---|---|
| `GET /unresolved` | Replaced by `GET /links?status=to_check`. A link always has an item (design 3.2), so nothing is "unresolved without an item"; a to-check candidate is a link, and "looked, found nothing" is the item's provider status. |
| `POST /unresolved/resolve` | Resolving is adding or preferring a link (`PUT /items/{id}/links`) or merging the local item into a catalogue item (`POST /items/{id}/merge`). |
| `GET /id-matches` | The id match table is the link table: `GET /items/{id}/links` and `GET /links`. |

The `?` item type and the `item_type`, `item_no` and `color_id` members are gone from every body (section 1). Nothing else in v1's 179 operations is dropped: 176 are carried (13 of them with a changed path, the rest on the same path with changed bodies where they named an item).

---

## 4. Pieces and what is implemented

| Piece | What | Operations |
|---|---|---|
| **M.11a** | This contract and the OpenAPI twin; the `/api/v2` blueprint (auth, scopes, throttle, read-only, audit origin, envelopes, errors, body caps); meta; item addressing and the item and colour serializers; the merged-id `307`; v1's 410 names v2; the contract check covers v2 | 9 |
| **M.11b** | Reads: catalogue, colours, items (detail, inventory, used-in, colours, images, links, provider status), copies, stock, minifigures, gaps and matches, instructions, prices, wishes and wishlists, storages, lots, places, flags, planning, exports, events, statistics | 57 |
| **M.11c** | Writes: the v2 write contract, create by numbers with `422 unidentified`, the copy inventory switch and cancel, links, merge and unmerge, settings, undo | 65 |
| **M.11d** | Orders, jobs, sources and keys, sync, imports, identifications, tokens, admin; the dead v1 callers removed | 58 |
| **M.11e** | The MCP regenerated from this file, the v2 parity test, API and MCP docs | none |

Operations by piece: M.11a 9, M.11b 57, M.11c 65, M.11d 58 (189 in all). The two tables below are generated from the contract and the routes by `scripts/check_api_contract.py --write`, and that check (run by `scripts/check.sh`) fails when the contract, the routes or these tables disagree. A piece lands by adding itself to `brickwork.api2.DONE`.

### Implemented

<!-- api2-implemented:start -->
| Implemented operation | Piece | Backing |
|---|---|---|
| `GET /api/v2/health` | M.11a | `brickwork.api2.get_health` |
| `GET /api/v2/items/{id}` | M.11a | `brickwork.api2.items.get_items_by_id` |
| `GET /api/v2/lookup` | M.11a | `brickwork.api2.items.get_lookup` |
| `GET /api/v2/me` | M.11a | `brickwork.api2.get_me` |
| `GET /api/v2/minifigures/by-number/{no}` | M.11a | `brickwork.api2.items.get_minifigures_by_number_by_no` |
| `GET /api/v2/openapi.yaml` | M.11a | `brickwork.api2.get_openapi_yaml` |
| `GET /api/v2/parts/by-number/{no}` | M.11a | `brickwork.api2.items.get_parts_by_number_by_no` |
| `GET /api/v2/sets/by-number/{no}` | M.11a | `brickwork.api2.items.get_sets_by_number_by_no` |
| `GET /api/v2/version` | M.11a | `brickwork.api2.get_version` |
<!-- api2-implemented:end -->

### Not implemented yet (answer `501`)

`501 not_implemented` with a problem body that also carries `{"error": "not_implemented", "piece": "M.11x"}`. Authentication, scope and read-only come first, so a client without the right token still sees 401 or 403.

<!-- api2-pending:start -->
| Operation (answers 501 until its piece lands) | Piece |
|---|---|
| `POST /api/v2/catalogue/import` | M.11d |
| `GET /api/v2/catalogue/items` | M.11b |
| `GET /api/v2/catalogue/items/{id}` | M.11b |
| `GET /api/v2/catalogue/status` | M.11b |
| `GET /api/v2/colors` | M.11b |
| `POST /api/v2/colors/sync` | M.11d |
| `GET /api/v2/colors/{color_id}` | M.11b |
| `GET /api/v2/copies` | M.11b |
| `POST /api/v2/copies` | M.11c |
| `DELETE /api/v2/copies/{id}` | M.11c |
| `GET /api/v2/copies/{id}` | M.11b |
| `PATCH /api/v2/copies/{id}` | M.11c |
| `GET /api/v2/copies/{id}/check` | M.11b |
| `POST /api/v2/copies/{id}/check` | M.11c |
| `PUT /api/v2/copies/{id}/checked` | M.11c |
| `GET /api/v2/copies/{id}/completeness` | M.11b |
| `GET /api/v2/copies/{id}/figures` | M.11b |
| `PATCH /api/v2/copies/{id}/figures/{item_id}` | M.11c |
| `PUT /api/v2/copies/{id}/flags` | M.11c |
| `GET /api/v2/copies/{id}/gaps` | M.11b |
| `POST /api/v2/copies/{id}/inventory` | M.11c |
| `DELETE /api/v2/copies/{id}/inventory/pending` | M.11c |
| `GET /api/v2/copies/{id}/matches` | M.11b |
| `GET /api/v2/copies/{id}/parts` | M.11b |
| `POST /api/v2/copies/{id}/parts/bulk` | M.11c |
| `PATCH /api/v2/copies/{id}/parts/{part_id}` | M.11c |
| `POST /api/v2/copies/{id}/photos` | M.11c |
| `PUT /api/v2/copies/{id}/pin` | M.11c |
| `POST /api/v2/copies/{id}/restore` | M.11c |
| `POST /api/v2/copies/{id}/take` | M.11c |
| `GET /api/v2/database/check` | M.11d |
| `GET /api/v2/database/export` | M.11d |
| `GET /api/v2/events` | M.11b |
| `GET /api/v2/events/{id}` | M.11b |
| `POST /api/v2/events/{id}/undo` | M.11c |
| `GET /api/v2/exchange-rates` | M.11d |
| `POST /api/v2/exchange-rates/ecb` | M.11d |
| `PUT /api/v2/exchange-rates/{code}` | M.11d |
| `GET /api/v2/export/missing.csv` | M.11b |
| `GET /api/v2/export/missing.json` | M.11b |
| `GET /api/v2/export/missing.xml` | M.11b |
| `GET /api/v2/export/picker.csv` | M.11b |
| `GET /api/v2/export/wishlist.csv` | M.11b |
| `GET /api/v2/flags` | M.11b |
| `POST /api/v2/flags` | M.11c |
| `DELETE /api/v2/flags/{id}` | M.11c |
| `PATCH /api/v2/flags/{id}` | M.11c |
| `POST /api/v2/flags/{id}/restore` | M.11c |
| `POST /api/v2/found` | M.11c |
| `GET /api/v2/gaps` | M.11b |
| `GET /api/v2/identifications` | M.11d |
| `POST /api/v2/identifications` | M.11d |
| `DELETE /api/v2/identifications/{id}` | M.11d |
| `GET /api/v2/identifications/{id}` | M.11d |
| `GET /api/v2/identifications/{id}/thumb` | M.11d |
| `GET /api/v2/images/{id}/content` | M.11b |
| `POST /api/v2/imports/bricktracker` | M.11d |
| `POST /api/v2/imports/{id}/apply` | M.11d |
| `GET /api/v2/instruction-files` | M.11b |
| `POST /api/v2/instruction-files` | M.11c |
| `DELETE /api/v2/instruction-files/{id}` | M.11c |
| `GET /api/v2/instruction-files/{id}` | M.11b |
| `PATCH /api/v2/instruction-files/{id}` | M.11c |
| `GET /api/v2/instruction-files/{id}/content` | M.11b |
| `POST /api/v2/instruction-files/{id}/restore` | M.11c |
| `GET /api/v2/items` | M.11b |
| `GET /api/v2/items/{id}/colors` | M.11b |
| `GET /api/v2/items/{id}/detail` | M.11b |
| `GET /api/v2/items/{id}/images` | M.11b |
| `POST /api/v2/items/{id}/import` | M.11d |
| `GET /api/v2/items/{id}/inventory` | M.11b |
| `GET /api/v2/items/{id}/links` | M.11b |
| `PUT /api/v2/items/{id}/links` | M.11c |
| `POST /api/v2/items/{id}/merge` | M.11c |
| `GET /api/v2/items/{id}/prices` | M.11b |
| `POST /api/v2/items/{id}/prices` | M.11c |
| `GET /api/v2/items/{id}/prices/history` | M.11b |
| `POST /api/v2/items/{id}/prices/refresh` | M.11d |
| `GET /api/v2/items/{id}/provider-status` | M.11b |
| `POST /api/v2/items/{id}/unmerge` | M.11c |
| `GET /api/v2/items/{id}/used-in` | M.11b |
| `GET /api/v2/jobs` | M.11d |
| `POST /api/v2/jobs/drain` | M.11d |
| `POST /api/v2/jobs/instruction-identities` | M.11d |
| `POST /api/v2/jobs/pictures` | M.11d |
| `GET /api/v2/jobs/{id}` | M.11d |
| `POST /api/v2/jobs/{id}/resume` | M.11d |
| `POST /api/v2/jobs/{id}/retry` | M.11d |
| `GET /api/v2/links` | M.11b |
| `GET /api/v2/lots` | M.11b |
| `POST /api/v2/lots` | M.11c |
| `DELETE /api/v2/lots/{id}` | M.11c |
| `GET /api/v2/lots/{id}` | M.11b |
| `PATCH /api/v2/lots/{id}` | M.11c |
| `POST /api/v2/lots/{id}/restore` | M.11c |
| `GET /api/v2/matches` | M.11b |
| `GET /api/v2/minifigures` | M.11b |
| `GET /api/v2/minifigures/{id}` | M.11b |
| `GET /api/v2/orders` | M.11d |
| `POST /api/v2/orders/documents` | M.11d |
| `GET /api/v2/orders/export.csv` | M.11d |
| `GET /api/v2/orders/{id}` | M.11d |
| `POST /api/v2/orders/{id}/allocate` | M.11d |
| `GET /api/v2/orders/{id}/allocation-review` | M.11d |
| `GET /api/v2/orders/{id}/allocations` | M.11d |
| `POST /api/v2/orders/{id}/allocations/retry` | M.11d |
| `POST /api/v2/orders/{id}/documents/{doc_id}/phase` | M.11d |
| `GET /api/v2/orders/{id}/history` | M.11d |
| `PATCH /api/v2/orders/{id}/lines/{line_id}` | M.11d |
| `PUT /api/v2/orders/{id}/lines/{line_id}/hold` | M.11d |
| `POST /api/v2/orders/{id}/received` | M.11d |
| `POST /api/v2/orders/{id}/reconcile` | M.11d |
| `GET /api/v2/orders/{id}/short.xml` | M.11d |
| `GET /api/v2/places` | M.11b |
| `POST /api/v2/places` | M.11c |
| `DELETE /api/v2/places/{id}` | M.11c |
| `PATCH /api/v2/places/{id}` | M.11c |
| `POST /api/v2/places/{id}/restore` | M.11c |
| `GET /api/v2/planning/ranking` | M.11b |
| `GET /api/v2/prices` | M.11b |
| `POST /api/v2/prices/observations` | M.11c |
| `POST /api/v2/prices/refresh` | M.11d |
| `GET /api/v2/prices/stale` | M.11b |
| `GET /api/v2/settings` | M.11c |
| `PATCH /api/v2/settings` | M.11c |
| `GET /api/v2/sources` | M.11d |
| `PATCH /api/v2/sources/{source}` | M.11d |
| `DELETE /api/v2/sources/{source}/key` | M.11d |
| `PUT /api/v2/sources/{source}/key` | M.11d |
| `POST /api/v2/sources/{source}/key/test` | M.11d |
| `DELETE /api/v2/sources/{source}/user` | M.11d |
| `PUT /api/v2/sources/{source}/user` | M.11d |
| `POST /api/v2/sources/{source}/user/connect` | M.11d |
| `POST /api/v2/sources/{source}/user/test` | M.11d |
| `GET /api/v2/statistics` | M.11b |
| `GET /api/v2/stock` | M.11b |
| `POST /api/v2/stock` | M.11c |
| `POST /api/v2/stock/booklets` | M.11c |
| `DELETE /api/v2/stock/{id}` | M.11c |
| `GET /api/v2/stock/{id}` | M.11b |
| `PATCH /api/v2/stock/{id}` | M.11c |
| `PUT /api/v2/stock/{id}/flags` | M.11c |
| `POST /api/v2/stock/{id}/give` | M.11c |
| `GET /api/v2/stock/{id}/parts` | M.11b |
| `PATCH /api/v2/stock/{id}/parts` | M.11c |
| `POST /api/v2/stock/{id}/photos` | M.11c |
| `POST /api/v2/stock/{id}/restore` | M.11c |
| `GET /api/v2/storages` | M.11b |
| `POST /api/v2/storages` | M.11c |
| `DELETE /api/v2/storages/{id}` | M.11c |
| `GET /api/v2/storages/{id}` | M.11b |
| `PATCH /api/v2/storages/{id}` | M.11c |
| `POST /api/v2/storages/{id}/contents` | M.11c |
| `POST /api/v2/storages/{id}/restore` | M.11c |
| `GET /api/v2/sync/{source}` | M.11d |
| `PUT /api/v2/sync/{source}/link` | M.11d |
| `GET /api/v2/sync/{source}/lists` | M.11d |
| `POST /api/v2/sync/{source}/pull/apply` | M.11d |
| `POST /api/v2/sync/{source}/pull/plan` | M.11d |
| `POST /api/v2/sync/{source}/send/apply` | M.11d |
| `POST /api/v2/sync/{source}/send/plan` | M.11d |
| `GET /api/v2/tokens` | M.11d |
| `POST /api/v2/tokens` | M.11d |
| `DELETE /api/v2/tokens/{id}` | M.11d |
| `GET /api/v2/wishes` | M.11b |
| `POST /api/v2/wishes` | M.11c |
| `DELETE /api/v2/wishes/{id}` | M.11c |
| `GET /api/v2/wishes/{id}` | M.11b |
| `PATCH /api/v2/wishes/{id}` | M.11c |
| `PUT /api/v2/wishes/{id}/flags` | M.11c |
| `POST /api/v2/wishes/{id}/restore` | M.11c |
| `POST /api/v2/wishes/{id}/to-owned` | M.11c |
| `GET /api/v2/wishlists` | M.11b |
| `POST /api/v2/wishlists` | M.11c |
| `DELETE /api/v2/wishlists/{id}` | M.11c |
| `PATCH /api/v2/wishlists/{id}` | M.11c |
| `GET /api/v2/wishlists/{id}/export.csv` | M.11b |
| `GET /api/v2/wishlists/{id}/export.xml` | M.11b |
| `POST /api/v2/wishlists/{id}/restore` | M.11c |
| `POST /api/v2/wishlists/{id}/transfer` | M.11c |
<!-- api2-pending:end -->

---

## 5. Decisions

Decided by brick-works under Ulf's delegation on #113 (2026-10-27); design section 7 is the approved frame.

1. v2 is v1's resource set with the 4.0 identity, not a redesign.
2. `/items/{id}` is canonical; the number paths and `/lookup` answer `200` with the same item body.
3. The default provider for numbers is `bricklink` (parts, minifigures); `provider=rebrickable` for Rebrickable numbers; a set number is the same in both. Several matches are `409 ambiguous`, none `404`, `422 unidentified` on create.
4. Colours in a request are in the provider's space.
5. A merged id answers `307` on GET (amended from `301`, section 2.1) and `409 merged` on writes.
6. Wish ids are uuids; stored words are served.
7. The MCP keeps its tool names; its tools take numbers and a provider, never a Brick Work id.

Choices M.11a made where the scope comment and design section 7 were silent:

* `GET /items/{id}` returns exactly the section 7 item body. v1's item detail (properties, counts, copies, stock, wishes, prices) moves to `GET /items/{id}/detail` (M.11b), with `links` where v1 had `matches`.
* `/minifigures/{id}` (M.11b) is v1's figure aggregate (sets, loose lines, missing, matches, prices) by Brick Work id; the item body of a figure by number is `/minifigures/by-number/{no}`.
* `provider=brickwork` is for colours on id paths only; on number paths and `/lookup` it is `422`.
* A lookup given `color` answers `data.color` next to the item fields.
* `GET /items/{id}/provider-status` is read-only: reconcile writes `item_provider_status`; a person resolves a to-check row by adding a link or merging.
* `PUT /items/{id}/links` sets one manual link or makes one preferred for its colour scope; there is no link delete (Undo reverses a mistake).
* `POST /items/{id}/merge` takes `{"survivor": <item key>}` and names the merged item in the path; `POST /items/{id}/unmerge` names the merged id in the path and an optional `merge_id`.
* `GET /settings` is implemented with the settings writes (M.11c), not with the reads.
* Undo (`POST /events/{id}/undo`) is a write and belongs to M.11c.

---

## Appendix A: error codes

| `code` | HTTP | When |
|---|---|---|
| `bad_request` | 400 | malformed JSON, wrong content type |
| `unknown_filter` | 400 | filter or sort name not in the vocabulary |
| `unauthorized` | 401 | no, bad, expired or revoked token |
| `forbidden` | 403 | scope too low |
| `read_only_instance` | 403 | `BW_READ_ONLY` set and a write was attempted |
| `not_found` | 404 | no such path, item or record |
| `method_not_allowed` | 405 | unsupported HTTP method; `Allow` lists supported methods |
| `api_retired` | 410 | only API v1 answers it: the whole line is gone from 4.0 (its `/health` excepted); the text names v2 |
| `moved` | 307 | **new in v2.** GET of a merged item id: `307` with `Location` to the survivor and `Cache-Control: no-store`; also carries `survivor` |
| `archived` | 409 | write to an archived record |
| `ambiguous` | 409 | **new in v2.** a number names several items; `candidates` lists them as item bodies |
| `merged` | 409 | **new in v2.** a write names a merged item id; `survivor` names the live item |
| `conflict` | 409 | state changed, duplicate |
| `stale_match` | 409 | stock or gap counts changed |
| `undo_blocked` | 409 | later change to the same rows |
| `not_undoable` | 409 | event is not a receipt |
| `idempotency_conflict` | 409 | key reused with another body |
| `precondition_failed` | 412 | `If-Match` mismatch |
| `payload_too_large` | 413 | document over 1 MiB, PDF over 20 MB, photo over 15 MB; any body over its cap is refused unread |
| `unsupported_media_type` | 415 | not JSON or multipart where required |
| `validation_failed` | 422 | field errors |
| `unsupported_setting` | 422 | key not in the whitelist |
| `unidentified` | 422 | **new in v2.** a create names a number that resolves to no item and cannot make one |
| `source_not_configured` | 424 | key missing for the source |
| `source_disabled` | 424 | source disabled |
| `catalogue_not_loaded` | 424 | no catalogue file |
| `idempotency_key_required` | 428 | required key missing |
| `budget_exhausted` | 429 | daily budget spent, synchronous call |
| `source_throttled` | 429 | remote asked to wait |
| `too_many_attempts` | 429 | too many failed token checks from this client; `Retry-After` and `retry_after` give the wait |
| `source_error` | 502 | upstream failure, redacted text |
| `not_set_up` | 503 | database file missing |
| `api_disabled` | 503 | no token configured |
| `db_unavailable` | 503 | SQLite error |
| `internal_error` | 500 | anything else, no detail leaked |
| `not_implemented` | 501 | **new in v2.** the operation's piece has not landed; the body also carries `piece` and `error` |
