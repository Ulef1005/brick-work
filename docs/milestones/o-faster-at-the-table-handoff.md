# Milestone O (Faster at the table): handoff for the next agent

**Historical record: the state on 22.11.2026. It is not kept up to date, and nothing in it is an instruction for today.** The live status is on the GitHub issues, under #303. What has changed since, as of 27.11.2026:

- v1.2 has shipped, so milestone U no longer holds back shell, template, CSS or UI work.
- N's #551 and #520, which #303 and #8 waited on, are closed, and the schema has moved past 4.8 ([n-handoff.md](n-handoff.md)). A new schema step takes the next free number in `UPGRADES`.
- The rule in *Rules carried* that no agent merges applied to that cloud thread.

Written 2026-11-22 by the cloud thread "Build code for milestone O". O is GitHub milestone 20. Its six open issues are #303, #42, #58, #8, #545 and #546. O has no gate issue yet.

## State
| Issue | State | Branch / PR | Waiting on |
|---|---|---|---|
| #58 bulk edit | Backend done | `o/58-bulk-edit`, draft #599 | Ulf's merge; B′ frame and Ulf's approval for the UI after v1.2 |
| #546 element id search | Done | `o/546-element-search`, draft #601 | Ulf's merge |
| #303 lot switch | Not started (backend planned) | `o/303-add-into-lot` (to make) | N's #551 lands (both change `add.confirm`); then the frame 20 B′ redraw with the set variant |
| #42 faster part entry | Backend done (known colours, owned rows, save into a row, JSON lookup) | `o/42-faster-part-entry`, draft #603 | Ulf's merge; UI on Part Spotter (frame 13) after v1.2 with an approved frame |
| #545 saved views | Not started | none | Schema slot: after N #551 (4.8) and P #14; new table `saved_view`; a frame after v1.2 |
| #8 barcode | Not started | none | N's Brickset adapter (#520); unverified: Brickset EAN lookup; frames 57 redraw |

## Decisions (Ulf, 2026-11-22, "recommendations approved")
- #58 v1: storage, condition, completeness, tags, statuses, purchase location and archive. Prices later, a cap of 500, one Undo.
- #546: the element id of a part you don't own shows the catalogue part, labelled "not in your collection".
- #545: saved views get their own table. Schema steps are numbered in merge order: N #551 takes 4.8, P #14 the next one, then O #545. Steps are additive through `UPGRADES` (`brickwork/store4/connect.py`).
- Order: #58 and #546 first, then #42's backend (coordinator, 22.11.: built ahead of #303, no overlap), then #303 after #551. #545 and #8 wait.

## PR order
#601, #599 and #603 are independent of each other. #599 changes `collection.save` (split into `_save_changes`), so any branch that edits `save()` rebases on it.

## Open guesses
- Brickset API v3 lookup by EAN/UPC: unverified.
- #546: one element id is one part and colour (it is the primary key).
- `tests/test_upgrade_path.py::test_a_050...` fails in the cloud container on main too (sqlite `?mode=ro` ATTACH). It is environmental; it is not caused by O. The same fault hides real upgrade failures: run the test with `sqlite3.connect` patched to `uri=True` before you call a failure pre-existing ([n-handoff.md](n-handoff.md)).

## Rules carried
One branch per issue, `o/<issue>-<slug>`. One draft PR each, and no merges by agents. Claim comment on an issue before starting. No shell, templates or CSS while U is open. Design steps need Ulf's written approval.

## On GitHub
- Overall handoff: [#303 comment](https://github.com/Ulef1005/brick-work/issues/303#issuecomment-7081947539).
- Per issue: [#58](https://github.com/Ulef1005/brick-work/issues/58#issuecomment-7081646245), [#546](https://github.com/Ulef1005/brick-work/issues/546#issuecomment-7081764416), [#42](https://github.com/Ulef1005/brick-work/issues/42#issuecomment-7081947278); claims and plans on #303, #545 and #8 (22.11.).
- Draft PRs: #599 (#58), #601 (#546), #603 (#42); CI is green on all three (22.11.).

## Next steps
1. Ulf reviews and merges #599, #601 and #603. They can go in any order. A branch that edits `collection.save` rebases on #599.
2. When N's #551 is on main: start `o/303-add-into-lot` off main. Add the lot switch to `add.confirm` (`brickwork/core/add.py`): a new or existing lot, purchase details, and the price split over the copies. No schema change. Backend first.
3. When the N (4.8) and P (#14) schema steps are on main: #545 gets the next number for a `saved_view` table. Then the API and MCP create, list, rename and delete views, and CSV export.
4. When N's Brickset adapter (#520) is on main: check whether Brickset can look up a set by EAN/UPC, then #8.
5. After v1.2 ships: brick-work-design draws B′ frames for #58 (bulk bar), #42 (Part Spotter review step), #303 (frame 20 with the set variant), #545 and #8. Ulf approves them in writing, and then the UI is built.
