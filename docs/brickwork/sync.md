# Collection sync with Rebrickable and Brickset

Issue #10, backend; on the 4.0 store since M.8j (issue #110). Owned sets and wanted sets only; loose parts, minifigures, missing parts, BrickLink, two-way merge and scheduled sync are out of scope. Code: `brickwork/core/sync/` (service) and `brickwork/core/sync/adapters.py` (remote calls). The API v1 routes named below answer 410 on the 4.0 line until API v2 (M.11); the screens (Tools & Admin → Collection sync) and `brickwork sync` run the same service.

## Credentials

Both sites need their API key (Catalogues & keys) and a per-user credential:

- **Connect** (`POST /api/v1/sources/{source}/user/connect`, `brickwork sync <source> connect --username NAME`): the username and password go straight to the site, once. Rebrickable: `POST https://rebrickable.com/api/v3/users/_token/` (form `username`, `password`, header `Authorization: key <api key>`) returns `user_token`. Brickset: `POST https://brickset.com/api/v3.asmx/login` (`apiKey`, `username`, `password`) returns `hash`. Only the token or hash is stored, encrypted like the API keys (`source_key` rows `rebrickable_user`, `brickset_user`). The password is not recorded: the connect call bypasses the recorded transport, the API replay check stores a keyed fingerprint, and the CLI asks for it without echo. At most 10 logins per site per UTC day (counted from the day's `sync` events of that kind: an attempt writes one, with no credential in it).
- **Paste** (`PUT /api/v1/sources/{source}/user`, `brickwork sync <source> paste`): a token or hash generated on the site.
- **Remove** (`DELETE …/user`, Undo restores it) and **Test** (`POST …/user/test`: Rebrickable `GET /users/{token}/setlists/?page_size=1`, Brickset `checkUserHash`).
- Environment overrides: `BW_REBRICKABLE_USER_TOKEN`, `BW_BRICKSET_USER_HASH`.

## Link

`PUT /api/v1/sync/{source}/link`. Rebrickable: `owned` (set list ids; empty = every list except the wishlist list), `wishlist` (one set list id), `send_to` (the owned list that receives sends; defaults to the only owned list). Both: `wish_list` (the Brick Work wishlist that pulls and sends wishes, default `default`). `GET /api/v1/sync/rebrickable/lists` lists the set lists.

## Remote calls

| Site | Call | Parameters | Budget |
|---|---|---|---|
| Rebrickable | `GET /api/v3/users/{token}/setlists/` | `page`, `page_size=1000` | counted (`BW_REBRICKABLE_DAILY_BUDGET`, 1 s spacing) |
| Rebrickable | `GET /api/v3/users/{token}/setlists/{id}/sets/` | `page`, `page_size=1000` | counted |
| Rebrickable | `POST …/setlists/{id}/sets/` | `set_num`, `quantity`, `include_spares=true` | counted |
| Rebrickable | `PUT …/setlists/{id}/sets/{set_num}/` | `quantity`, `include_spares=true` | counted |
| Rebrickable | `DELETE …/setlists/{id}/sets/{set_num}/` | | counted |
| Brickset | `getSets` | `apiKey`, `userHash`, `params={"owned":1 or "wanted":1 or "setNumber":…, "pageSize":500, "pageNumber":n}` | counted against the key (100/day) |
| Brickset | `setCollection` | `apiKey`, `userHash`, `SetID`, `params={"own":1,"qtyOwned":n}` / `{"own":0}` / `{"want":1}` / `{"want":0}` | not counted by Brickset; local cap 500 per UTC day |
| Brickset | `checkUserHash` | `apiKey`, `userHash` | not counted |

Recorded jobs and source records name the path template, never the token or hash.

## Translation

A remote set number is a Rebrickable number (Brickset's `number-variant` is the same numbering). It names the item whose born key it is; when a number is born by a local BrickLink-born item and by a Rebrickable-born one, the Rebrickable one wins. When no born key matches, one confirmed BrickLink link naming the number decides (`items.find`'s rules, in one batched query). A number that names several items, none, or only a part or a figure is listed as unmatched and never guessed. Sending goes the other way: an item is named by its Rebrickable number, else by its BrickLink number (`items.bricklink_key`); an item with no number at all is listed as not on the site and cannot be ticked. Brickset's `setID` for a send comes from the pull data, otherwise one `getSets` by set number per 500 sets.

## Pull

`POST /sync/{source}/pull/plan` (write scope) fetches and compares. Rows per set and kind (`owned`, `wanted`): `add` (the site has more: count to add, ticked), `only_here`, `differs` (here has more; nothing to pull), `conflict` (both sides changed since the last pull or send and they differ: both values, no default; a collection with no baseline yet, as after the migration, shows a full comparison and no conflict), plus `unmatched`. The plan is a file under `data/sync/` and expires after 24 hours.

`POST /sync/{source}/pull/apply` (`plan_id`, optional `ticked` row keys; write scope, Idempotency-Key) places each item by its current kind (design § 3.5). A set becomes one copy per missing unit through `store4.copies.create_copy_in` with design § 4.3's preselection (condition and completeness unset, no box, instructions or storage, tag `imported from Rebrickable|Brickset`); every other kind (a gear, book, catalog, instructions or box item) becomes loose stock of that kind. Missing wishes go to the linked wishlist (or raise a wish's quantity, keeping its condition), the normal pipeline is queued for the new items, and one `sync:<plan>` receipt event is written. Nothing here is deleted or lowered. Undo (`POST /events/{id}/undo`, or the button on the sync page) archives what the pull created, takes the quantities back off stock and wishes, removes its flag and puts the baseline back; it refuses after a later edit to anything the pull wrote. Whether a plan was applied is its `plan` row (`kind=sync_pull`), written in the apply transaction.

## Send

`POST /sync/{source}/send/plan` lists the remote calls: per set whose count differs, the count to send (live copies here; wishes by quantity on Rebrickable, wanted yes/no on Brickset). Removals (`remove`, here 0) and conflicts are never ticked by default. `POST /sync/{source}/send/apply` (admin scope) performs the ticked rows in order; each row reports `sent`, `unchanged`, `failed` (with the reason), `paused` (daily budget; the rest pause too) or `key_rejected` (the rest stop). Re-applying the same plan retries only rows not yet sent. Remote changes are not undone by Brick Work's Undo.

Condition, completeness, box, instructions and storage never leave Brick Work.

## State

One `sync_state` row per source: `link_json` (carried by the migration), `baseline_json` (remote and here counts per item id at the last pull or send, for conflict detection), `last_pull_json`, `last_send_json`; the baseline and the last pull and send start empty. `GET /sync/{source}` returns them with the credential states (never the values) and the number of rows waiting from the last send.

## Open facts

- Rebrickable user tokens: Rebrickable documents no expiry; a refused token surfaces as `key_rejected`.
- Brickset `setCollection` and `login` limits are not published; the local caps above are Brick Work's own.
- Brickset wanted sets carry no quantity in the API; wishes send as wanted yes/no.
