# Milestone N: build handoff

**Historical record: the state on 22.11.2026. It is not kept up to date, and nothing in it is an instruction for today.** The live status is on the GitHub issues and on the gate, #525. What has changed since, as of 26.11.2026:

- The three pull requests of the stack (#595, #596, #598) are merged.
- #36, #143, #517, #519, #520, #524 and #551 are closed. #469 is closed with the Lost Parts send **locked**; what is needed to unlock it is #750.
- The build was later split between two local sessions (the #525 comments of 24.11. and 26.11.), and the schema is now 4.9.
- The rule in *PR stack* that no agent merges applied to that cloud thread.

Cloud thread, 22.11.2026. Written so another agent could pick up the rest of N; the same text was posted on gate #525. Status as of 22.11. 17:40 CET. Ulf's go for the plan: 22.11. in the project thread ("yes" to Phase A now and Phase B after v1.2, one branch per issue `n/<issue>-<slug>`, claim comments on issues).

## Plan and why

- **Phase A, now:** back end only (`brickwork/core/sync`, importer, exports, `store4`). No shell, templates or CSS, because U (v1.2, due on prod 30.11.) is rebuilding those (frames 06 to 16, Tools & Admin `u/493`, Set detail #507).
- **Phase B, after v1.2 ships and #528 (`design/sync-n`) merges:** the hub and site pages to the approved frames (`design/screens-b/17` to `48` on `design/sync-n`; APPROVALS lines 110 to 115).

## PR stack (merge in this order; none merged, none to be merged by an agent)

| # | Branch | Issue | Base | State |
|---|---|---|---|---|
| #595 | `n/551-added-via` | #551 | `main` | open, CI green; review round fixed in `faad704b` (see below) |
| #596 | `n/531-list-names` | #531 | `n/551-added-via` | open, CI green; retarget to `main` after #595 |
| #598 | `n/471-part-lists` | #471 | `n/531-list-names` | open, CI green; retarget after #596 |

## Review round on #595 (`faad704b`, merged up into #596 and #598)

- Undo of a loose-stock add (`core/stock.py` `undo_added`) and of the import from another app (its guard, `core/importer/`) compares through `as_current`, so a receipt from before 4.8 still undoes.
- Undo of a kind move (`store4/merge.py` `_refuse_later_sync`) is refused with *undo that sync first* when a later sync matched a row the move made. Accepted limit, not a bug.
- `synced_from.id` is `AUTOINCREMENT`, so #531's Undo can put a dropped list line back under its old id.
- Tests: the last three in `tests/test_origins.py`. Full `check.sh` result: see the gate section below.

## Schema step order

- `main` and every `u/*` and `design/*` branch are at **4.7** (checked 22.11.).
- N takes **4.8** in #595 (`origin`, `added_via` on copy/stock/wish, `synced_from`; ADR 0039 *proposed*).
- P (#14 build state, #37 custom items) and O (#545 saved views) have no schema step on any branch yet. Whichever lands after #595 takes 4.9 and so on. `UPGRADES` in `brickwork/store4/connect.py` is additive: on a conflict, keep both and renumber the later one. The 4.7 to 4.8 test edits (`tests/test_store4_upgrade.py`, `tests/regression/test_migrates_to_4.py`, `tests/test_gate_edge_world.py` fingerprints, `tests/bench_reference.json`) show what the next step must touch.

## Issue status

| Issue | Status | Next |
|---|---|---|
| #551 added-via | back end in #595 | UI: chip and Last synced from on Set detail (frame 44), Source filter on Sets (45) and the stock lists, in Phase B |
| #531 list names | back end in #596 | UI: Pick sets line (46) and Preview lines (47) on the Rebrickable page (#519) |
| #471 part lists | core in #598 | API v2 routes (`/sync/rebrickable/parts/plan` and `/apply`; update contract, `api-v2.md` and the MCP parity list) and the page, with #519 |
| #469 Lost Parts send | **not started** (claimed) | `plan_send` in `core/sync/__init__.py` plus `lost_parts.py`. Rebrickable needs `inv_part_id`: likely `GET /lego/sets/{set}/parts/` (one paged call per set), then `POST /users/{token}/lost_parts/` `{inv_part_id, lost_quantity}` and `DELETE /users/{token}/lost_parts/{id}/`. All of this is *unconfirmed*: mark it ASSUMED as `parse_lost_part` does. The switch is off by default. Removals stay unticked. |
| #470 export, #524 own export | not started (claimed) | `core/list_exports.py`, `core/order_exports.py`. #524 re-import writes Added via `brickwork_export`. |
| #143 BrickLink wanted XML | not started (claimed) | export side of `add.file_rows`'s XML reader |
| #36 Brick Owl import | not started (claimed) | importer; Added via `brickowl_xml` |
| #520 Brickset data | not started (claimed) | open fact: Brickset's new/used field name |
| #518, #519, #521, #522, #523 pages | Phase B, unclaimed | frames on `design/sync-n`; follow `design/DESIGN-CHECK.md` and the `frame_check` flow |
| #517 design | brick-work-design's | round 3 (errors, rate limits, long runs, nothing to sync) not drawn yet |

## Open guesses waiting on Ulf (each is listed in its PR)

1. #595: a lookup table `origin` instead of a CHECK. 3.3-migrated rows read "Before this release". API, CLI, order and build rows read "By hand". A row unticked in the preview gets no new sync date.
2. #596: "Keep" on a renamed list keeps the old name, also on matched sets. The switch is on by default, as frame 46 draws it.
3. #598: the Rebrickable part-list reply shape (not checked live).

## Open facts (product or real account)

- BrickLink API store registration (#521) and Brick Owl per-endpoint quotas (#522).
- The file type of "Part Runner and order files" (#523).
- Each page still needs its check against a real account on the test instance (the #457 pattern). No cloud session has keys.

## How to run the gate in a cloud container

`CHROME=/opt/pw-browsers/chromium BW_CHROME_NO_SANDBOX=1 bash scripts/check.sh`. The container's Python sqlite has URI filenames off, so `tests/test_upgrade_path.py` fails there on its `ATTACH 'file:…?mode=ro'` with *unable to open database*. That hides real failures: run it with `sqlite3.connect` patched to `uri=True` (a 6-line pytest wrapper) before you call it pre-existing. CI judges it for real.

Full gate on `n/471-part-lists` (22.11.): 5531 passed, 2 failed, both fixed since: the generated `brickwork/api2/write_contract.json` (`python -m scripts.generate_api_writes --write` after any OpenAPI write change) and `test_upgrade_path` counts for 4.8 (`edf41083`).
