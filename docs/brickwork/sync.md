---
audience: developer
verified: 1.0
---

# Collection sync with Rebrickable and Brickset

Issue #10, backend; on the 4.0 store since M.8j (issue #110). Owned sets and wanted sets only; loose parts, minifigures, missing parts, BrickLink, two-way merge and scheduled sync are out of scope. Code: `brickwork/core/sync/` (service) and `brickwork/core/sync/adapters.py` (remote calls). The routes named below are API v2 (`brickwork/api2/`); API v1 is retired and answers 410, except `/api/v1/health`. The screens (Workbench → Sync) and `brickwork sync` run the same service.

## Credentials

Both sites need their API key (Catalogues & keys) and a per-user credential:

- **Connect** (`POST /api/v2/sources/{source}/user/connect`, `brickwork sync <source> connect --username NAME`): the username and password go straight to the site, once. Rebrickable: `POST https://rebrickable.com/api/v3/users/_token/` (form `username`, `password`, header `Authorization: key <api key>`) returns `user_token`. Brickset: `POST https://brickset.com/api/v3.asmx/login` (`apiKey`, `username`, `password`) returns `hash`. Only the token or hash is stored, encrypted like the API keys (`source_key` rows `rebrickable_user`, `brickset_user`). The username you typed (without leading and trailing spaces) is kept too, in the setting `<source>_account_name`, for the page to show. A pasted token or hash, and a removal, clear it. The password is not recorded: the connect call bypasses the recorded transport, the API replay check stores a keyed fingerprint, and the command-line tool asks for it without echo. At most 10 logins per site per UTC day (counted from the day's `sync` events of that kind: an attempt writes one, with no credential in it).
- **Paste** (`PUT /api/v2/sources/{source}/user`, `brickwork sync <source> paste`): a token or hash generated on the site.
- **Remove** (`DELETE …/user`, Undo restores the credential but not the account name the page shows) and **Test** (`POST …/user/test`: Rebrickable `GET /users/{token}/setlists/?page_size=1`, Brickset `checkUserHash`).
- Environment overrides: `BW_REBRICKABLE_USER_TOKEN`, `BW_BRICKSET_USER_HASH`.

## Link

`PUT /api/v2/sync/{source}/link`. Rebrickable: `owned` (set list ids; empty = every list except the wishlist list), `wishlist` (one set list id), `send_to` (the owned list that receives sends; defaults to the only owned list). Both: `wish_list` (the Brick Work wishlist that pulls and sends wishes, default `default`). `GET /api/v2/sync/rebrickable/lists` lists the set lists. Plans answer 201 and an unknown source answers 404. The MCP tools `get_sync_status`, `plan_sync_pull`, `apply_sync_pull` and `plan_sync_send` run the same service.

## Remote calls

| Site | Call | Parameters | Budget |
|---|---|---|---|
| Rebrickable | `GET /api/v3/users/{token}/setlists/` | `page`, `page_size=1000` | counted (`BW_REBRICKABLE_DAILY_BUDGET`, 1 s spacing) |
| Rebrickable | `GET /api/v3/users/{token}/setlists/{id}/sets/` | `page`, `page_size=1000` | counted |
| Rebrickable | `POST …/setlists/{id}/sets/` | `set_num`, `quantity`, `include_spares=true` | counted |
| Rebrickable | `PUT …/setlists/{id}/sets/{set_num}/` | `quantity`, `include_spares=true` | counted |
| Rebrickable | `DELETE …/setlists/{id}/sets/{set_num}/` | | counted |
| Brickset | `getSets` | `apiKey`, `userHash`, `params={"owned":1 or "wanted":1 or "setNumber":…, "pageSize":500, "pageNumber":n}` | counted against the key (100/day) |
| Brickset | `setCollection` | `apiKey`, `userHash`, `SetID`, `params` per set: `{"own":1,"qtyOwned":n}` or `{"own":0}`, with `{"qtyWanted":n}` or `{"want":0}`, in one call | counted against the key |
| Brickset | `checkUserHash` | `apiKey`, `userHash` | counted against the key |
| Brickset | `getUserFlagLabels` | `apiKey`, `userHash` | counted against the key |

Recorded jobs and source records name the path template and never the token or hash.

## Translation

A remote set number is a Rebrickable number (Brickset's `number-variant` is the same numbering). It names the item whose born key it is; when a number is born by a local BrickLink-born item and by a Rebrickable-born one, the Rebrickable one wins. When no born key matches, one confirmed BrickLink link naming the number decides (`items.find`'s rules, in one batched query). A number that names several items, none, or only a part or a figure is listed as unmatched and never guessed. Sending goes the other way: an item is named by its Rebrickable number, else by its BrickLink number (`items.bricklink_key`). An item with no number at all is listed as not on the site and cannot be ticked. Brickset's `setID` for a send comes from the pull data, otherwise one `getSets` by set number per 500 sets.

## Pull

`POST /sync/{source}/pull/plan` (write scope) fetches and compares. Rows per set and kind (`owned`, `wanted`):

- `add` (the site has more: count to add, ticked)
- `only_here`
- `differs` (here has more; nothing to pull)
- `conflict` (both sides changed since the last pull or send and they differ: both values, no default). A collection with no baseline yet (as after the migration) shows a full comparison and no conflict.
- `unmatched`

The plan is a file under `data/sync/` and expires after 24 hours.

`POST /sync/{source}/pull/apply` (`plan_id`, optional `ticked` row keys; write scope; these writes accept an optional Idempotency-Key, and none requires one) places each item by its current kind (design § 3.5). A set becomes one copy per missing unit. Each is made by `core/add._add_copy`, which calls `create_copy_in`, with design § 4.3's preselection (condition and completeness unset, no box, instructions or storage, tag `imported from Rebrickable|Brickset`; a set with no part list gets `inventory_source='none'`). Every other kind (a gear, book, catalog, instructions or box item) becomes loose stock of that kind, with the same tag. Missing wishes go to the linked wishlist (or raise a wish's quantity, keeping its condition), the normal pipeline is queued for the new items, and one `sync:<plan>` receipt event is written. Nothing here is deleted or lowered. Undo (`POST /events/{id}/undo`, or the button on the sync page) archives what the pull created and takes the quantities back off stock and wishes. It also removes its flag and puts the baseline back, and it refuses after a later edit to anything the pull wrote. Whether a plan was applied is its `plan` row (`kind=sync_pull`), written in the apply transaction.

## Lost parts from Rebrickable

A Rebrickable pull plan also reads `GET /users/{token}/lost_parts/` (`page`, `page_size`) through the same budgeted, recorded transport, unless the switch is off. The switch is the link option `lost_parts` (`PUT /sync/rebrickable/link`, true or false, on when never set). The plan carries a `lost` object: `on`, `rule`, `status` (`off`, `read`, `failed`), `message`, `unreadable`, `clearing`, `sets` (per set: `copies`, `copy_id`, `state` `ready`, `pick` or `new`, `preview` with the parts, the counts that change, the cleared marks and the unmatched parts), `unmatched_sets` and a `summary`. A failed read (an error, a throttle) sets `status: failed` and never stops the set comparison.

The reply's items are not described in Rebrickable's OpenAPI file. The parser (`parse_lost_part` in `core/sync/adapters.py`) assumes `{lost_part_id, lost_quantity, inv_part: {part: {part_num}, color: {id}, set_num, is_spare}}`. A row it cannot read is counted in `unreadable`, and a plan with such a row clears nothing.

The rule is the setting `rebrickable_lost_parts_rule` (`add_only`, `per_part` (default), `per_set`, `everything`; `GET` and `PATCH /settings`, `brickwork settings set`). The plan freezes it. A lost part is matched to a live set line of the copy by part and colour. The match uses the Rebrickable numbers of the line's item and colour (`wishlists._rebrickable_numbers` and `_rebrickable_colours`). A copy on BrickLink's part list matches through a confirmed Rebrickable link. A spare row matches a spare line. A row with no line, several lines, or a count above the line's quantity is listed as unmatched, and a copy with an unmatched row is not cleared.

`POST /sync/{source}/pull/apply` takes `lost_ticked` (set numbers; left out: every set with one copy to use) and `copy_picks` (`{set number: copy id}`; a set with several copies and no pick is left out and listed). Each copy's marks are one `checker.mark` receipt (`part_check`, field `save`); the pull's receipt keeps their event ids in `lost.events`, and its one Undo takes them back first. The counts gain `lost_sets`, `lost_added`, `lost_replaced` and `lost_cleared` when a set was written. A set with no live copy that the same pull adds exactly once is planned as `state: new` (#513). Its preview matches against the lines that copy gets from the Add preselection (`lost_parts.preview_new`). Those lines are built and projected inside a savepoint that is rolled back, so the plan writes nothing. The apply then marks the copy the pull just made. A set the pull adds several times is listed in `unmatched_sets` for a pick on the next sync. Any other copy the same pull created takes no marks.

## Send

`POST /sync/{source}/send/plan` lists the remote calls: per set whose count differs, the count to send (live copies here; wishes by quantity on both sites). Removals (`remove`, here 0) and conflicts are never ticked by default. `POST /sync/{source}/send/apply` (admin scope) performs the ticked rows in order; each row reports `sent`, `unchanged`, `failed` (with the reason), `paused` (daily budget; the rest pause too) or `key_rejected` (the rest stop). Re-applying the same plan retries only rows not yet sent. On Rebrickable, a wish row can't be ticked while no `wishlist` is linked (#514). Its `reason` says *Link a Rebrickable wishlist to send wishes to*. An owned row with no list to send to can't be ticked either. Remote changes are not undone by Brick Work's Undo.

Condition, completeness, box, instructions, and storage never leave Brick Work.

## A run as a job

A run of the Rebrickable or Brickset page has five steps: choose, pick, preview, run, and result. A short run is applied in one request. A long run is a durable job (`core.sync.run_job`, #685, [ADR 0042](https://github.com/Ulef1005/brick-work/blob/main/docs/adr/0042-sync-run-as-a-job.md)).

`run_job.queue` freezes the validated choices into the run record. It adds one `job` row of kind `sync_run`, with one `job_step` for each stage that has work: `pull`, `parts`, `send` and `lost_out`. The embedded drainer, or `brickwork worker`, runs it. It survives a restart and shows in Jobs. In `GET /jobs`, a step's `count` and `total` are the changes done and chosen.

Runs start from the web page only. The API has no start or stop endpoint. Jobs lists the job, but retry and resume answer `404`, because they are for pipeline jobs. `POST /jobs/drain` does not run it either. The drainer takes it up by itself, and Send again is `run.retry_send`.

- **Progress is what Brick Work knows.** The pull and the part-list stages are one transaction, with one undo event for the whole run. They go from 0 to done. The send and Lost Parts out stages go one call at a time (Brickset: one call per set number). Their count is the rows done, and it advances after each call.
- **Stop after this one** (`run_job.request_stop`) takes effect between calls and between stages, never halfway through a call. What was done stays done. The unfinished stages are `stopped` in the run's result. Their job steps end `done`, and the job ends `done` with the note *Stopped at your request*. A job that waits for the budget is stopped at once.
- **A restart never repeats a send.** A stage recorded as started when its worker died is not run again. It becomes `failed` ("Interrupted") with the rows of the send plan. Send again (`run.retry_send`) can then send what did not go out, once the person has checked. The pull, part-list and Lost Parts stages are not retried from the result. A new run offers their rows again.
- **Budget.** A paused call ends the job `waiting_for_budget` with the retry time of the source. The job resumes by itself and sends only the rows not yet sent. A plan lasts 24 hours from the last write of the job. A job that waits or is down for longer has lost its run, and a new run offers the rows again.
- **An unexpected error** ends the job `failed` and settles the run as it stands, with its audit entry. Undo of the run is then one step. If the closing write failed as well, the run has no audit entry, and Undo reverts one event at a time. A run that never began is released and can be queued again.
- The synchronous `run.apply`, `save_pick` and `retry_send` leave a run with an unfinished job alone.

## State

One `sync_state` row per source: `link_json` (carried by the migration), `baseline_json` (remote and here counts per item id at the last pull or send, for conflict detection), `last_pull_json` and `last_send_json`. Each row of the last send keeps its `result` and its `detail`, the reason a row failed (#514). The baseline and the last pull and send start empty. `GET /sync/{source}` returns them with the credential states (never the values) and the number of rows waiting from the last send.

## Open facts

- Rebrickable user tokens: Rebrickable documents no expiry; a refused token surfaces as `key_rejected`.
- Brickset counts every call against the key, not only `getSets` (100 a day to start; the change came in November 2026). Brick Work counts `getSets`, `setCollection`, `checkUserHash` and `getUserFlagLabels`. Brickset also counts key checks and logins, so its own number can be a few higher. `login` has a local cap of 10 a day.
- Brickset keeps a wanted quantity (`qtyWanted`); a wish sends its quantity.
- Brickset notes and flags (pull, back end only until the page has its frames): the two `getSets` reads already carry them, and `getUserFlagLabels` names the flags. `sync.set_fields` plans and applies the pull as its own stage with its own receipt and Undo. A note goes to every live copy of the set that has none, or to the set's wish when there is no copy. A different note is a conflict that is kept unless chosen. A note changed after the plan is left alone. Each flag is one tag, named by its label or `Brickset flag N`, kept in the setting `brickset_flag_tags`. A pull only adds links to tags. It also renames a tag that is still named `Brickset flag N` to its label, whatever is ticked, unless another live tag has that name; the plan lists those renames. A copy or wish archived after the plan is skipped.
