# 4.0 regression map: which test guards which check of design 12

Design § 12 ran three scripts and a dump build against the design's DDL in SQLite. This page maps every check of the three scripts
to the test in the suite that guards it now, against the real `brickwork/store4/*.sql`, so a later reader can see each failure the
design's review demonstrated (§ 13) guarded. Written for M.9 (issue #111). The scripts and their logs are in the design's scratchpad
(not in the repo); the labels below are the logs' own.

`tests/test_store4_schema.py::test_halves_equal_the_design_ddl` holds the two halves of the shipped DDL equal to `schema-4.0.sql`, so a
check that passed on the design's copy passes on what ships.

| Script | Checks | Covered before M.9 | Ported in M.9 | Not portable |
|---|---|---|---|---|
| `test_constraints.py` (`constraints.log`) | 97 | 97 (M.1) | 0 | 0 |
| `test_procedures.py` (`procedures.log`) | 16 | 15 (M.2, M.7) | 1 (A3, second half) | 0 |
| `test_journey.py` (`journey.log`) | 1 replay, 8 steps | step checks in module tests; no replay | 1 test, through the app's writers | 0 (3 rows differ from the journey text, see below; setup's system flags and event were added to match it) |

## 1. Constraint checks (97)

C1 to C9 run against `catalogue.sql`, L0 to L15 against `brickwork.sql`; each test file function is one database, in the log's order.
The review case each guards is in section 4.

| # | Check | Test |
|---|---|---|
| 1 | C1 colour 1 = Rebrickable 9999 | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 2 | C1 colour 2 = Rebrickable -1 | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 3 | C1 fixed id 1 cannot hold another colour | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 4 | C1 Rebrickable 9999 cannot take another id | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 5 | C2 a part cannot be classified by theme | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 6 | C2 namespace kind must match the namespace | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 7 | C2 born key unique (provider, namespace, key) | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 8 | C2 same key in another namespace is another item | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 9 | C3 kind change keeps the id (theme guess corrected by BrickLink) | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 10 | C3 id 15 still the same born key | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 11 | C3 a part cannot change kind | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 12 | C4 catalogue cannot mint into the local range | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 13 | C4 catalogue adopts a local id (set fetched via API before the dump) | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 14 | C5 one inventory per (item, version) | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 15 | C5 one latest inventory per item | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 16 | C6 inventory line key is the primary key (no surrogate id) | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 17 | C6 inventory_part is WITHOUT ROWID | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 18 | C7 leg rule: 970c03 in Black -> BrickLink 970c00 (colour-scoped) | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 19 | C7 leg rule: 970c03 in other colours -> 970c11 (unscoped) | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 20 | C7 duplicate unscoped link refused (NULL colour coalesced) | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 21 | C7 two preferred links for one (item, provider, colour) | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 22 | C7 a catalogue link needs an item | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 23 | C7 status 'unmatched' no longer exists on links | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 24 | C8 BrickLink 72 <- Rebrickable 1051 (inverse preferred) | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 25 | C8 BrickLink 72 <- Rebrickable 313 too | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 26 | C8 only one inverse per BrickLink colour | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 27 | C9 catalogue foreign_key_check clean | `tests/test_store4_schema.py::test_catalogue_constraints` |
| 28 | L0 setup seeds colours 1 and 2 | `tests/test_store4_schema.py::test_collection_constraints` |
| 29 | L0 a second Rebrickable 9999 colour | `tests/test_store4_schema.py::test_collection_constraints` |
| 30 | L0 a BrickLink-only colour is local, above the base | `tests/test_store4_schema.py::test_collection_constraints` |
| 31 | L1 a local item below the base | `tests/test_store4_schema.py::test_collection_constraints` |
| 32 | L1 an unidentified item: local, no born key | `tests/test_store4_schema.py::test_collection_constraints` |
| 33 | L1 a catalogue item needs a Rebrickable born key | `tests/test_store4_schema.py::test_collection_constraints` |
| 34 | L2 job source 'import' (pipeline) is a seeded source | `tests/test_store4_schema.py::test_collection_constraints` |
| 35 | L2 copy on Rebrickable v1 with BrickLink list pending | `tests/test_store4_schema.py::test_collection_constraints` |
| 36 | L2 pending without its job | `tests/test_store4_schema.py::test_collection_constraints` |
| 37 | L2 source 'bricklink' needs a fetched list | `tests/test_store4_schema.py::test_collection_constraints` |
| 38 | L2 set_preference 'bricklink' before any list was fetched | `tests/test_store4_schema.py::test_collection_constraints` |
| 39 | L2 a copy cannot use another set's fetched list (composite FK) | `tests/test_store4_schema.py::test_collection_constraints` |
| 40 | L2 two latest fetched lists per (item, source) | `tests/test_store4_schema.py::test_collection_constraints` |
| 41 | L2 a second fetch is seq 2, latest; seq 1 stays for copies built from it | `tests/test_store4_schema.py::test_collection_constraints` |
| 42 | L2 fetched line key is the primary key | `tests/test_store4_schema.py::test_collection_constraints` |
| 43 | L3 copy_part cannot name another copy's figure (composite FK) | `tests/test_store4_schema.py::test_collection_constraints` |
| 44 | L3 copy_part of its own figure | `tests/test_store4_schema.py::test_collection_constraints` |
| 45 | L3 one row per line key in a copy | `tests/test_store4_schema.py::test_collection_constraints` |
| 46 | L4 missing=2, damaged=1 of 2 (today's per-field bounds, checker.py:454-468) | `tests/test_store4_schema.py::test_collection_constraints` |
| 47 | L4 missing above quantity | `tests/test_store4_schema.py::test_collection_constraints` |
| 48 | L5 the initial design's 'replace the rows' fails once a Take/allocation exists | `tests/test_store4_schema.py::test_collection_constraints` |
| 49 | L5 switch by in-place update + retire commits with Take, allocation and check session in place | `tests/test_store4_schema.py::test_collection_constraints` |
| 50 | L5 switching back re-activates the same row id | `tests/test_store4_schema.py::test_collection_constraints` |
| 51 | L5 stock_transfer still points at row 104 | `tests/test_store4_schema.py::test_collection_constraints` |
| 52 | L6 a live catalogue item cannot be merged away | `tests/test_store4_schema.py::test_collection_constraints` |
| 53 | L6 a local item cannot be merged while referenced | `tests/test_store4_schema.py::test_collection_constraints` |
| 54 | L6 local BrickLink-born 970c00 merged into catalogue 970c03 after moving references | `tests/test_store4_schema.py::test_collection_constraints` |
| 55 | L6 a redirect must match its merge | `tests/test_store4_schema.py::test_collection_constraints` |
| 56 | L6 INSERT naming a merged item (copy_part) | `tests/test_store4_schema.py::test_collection_constraints` |
| 57 | L6 UPDATE to a merged item (copy_part) | `tests/test_store4_schema.py::test_collection_constraints` |
| 58 | L6 INSERT naming a merged item (stock_part, not guarded before) | `tests/test_store4_schema.py::test_collection_constraints` |
| 59 | L6 INSERT naming a merged item (price_observation, not guarded before) | `tests/test_store4_schema.py::test_collection_constraints` |
| 60 | L6 materialising a catalogue line still works (no catalogue row names a merged id) | `tests/test_store4_schema.py::test_collection_constraints` |
| 61 | L6 a retired catalogue item can be merged only after its references move | `tests/test_store4_schema.py::test_collection_constraints` |
| 62 | L6 a retired, unreferenced catalogue item (a Rebrickable rename) can be merged | `tests/test_store4_schema.py::test_collection_constraints` |
| 63 | L6 merge into an item of another kind | `tests/test_store4_schema.py::test_collection_constraints` |
| 64 | L7 3023 White used, no lot, no storage | `tests/test_store4_schema.py::test_collection_constraints` |
| 65 | L7 the identical line again (NULL lot and storage) | `tests/test_store4_schema.py::test_collection_constraints` |
| 66 | L7 3023 White with condition NULL | `tests/test_store4_schema.py::test_collection_constraints` |
| 67 | L7 the same with condition NULL again | `tests/test_store4_schema.py::test_collection_constraints` |
| 68 | L7 a new live line after the old one was archived | `tests/test_store4_schema.py::test_collection_constraints` |
| 69 | L7 two identical loose figures stay two rows | `tests/test_store4_schema.py::test_collection_constraints` |
| 70 | L7 a loose figure needs a part-list source (G6) | `tests/test_store4_schema.py::test_collection_constraints` |
| 71 | L7 a loose part has no part-list source | `tests/test_store4_schema.py::test_collection_constraints` |
| 72 | L8 item 2339 has no BrickLink id: item_provider_status | `tests/test_store4_schema.py::test_collection_constraints` |
| 73 | L8 a migrated figure with no candidate: to_check without a key | `tests/test_store4_schema.py::test_collection_constraints` |
| 74 | L8 item_link without an item | `tests/test_store4_schema.py::test_collection_constraints` |
| 75 | L8 item_link status 'unmatched' | `tests/test_store4_schema.py::test_collection_constraints` |
| 76 | L8 same_number candidate as to_check link | `tests/test_store4_schema.py::test_collection_constraints` |
| 77 | L8 the same link twice (NULL colour scope coalesced) | `tests/test_store4_schema.py::test_collection_constraints` |
| 78 | L8 'manual' only from the user | `tests/test_store4_schema.py::test_collection_constraints` |
| 79 | L9 an unreferenced theme-guessed item changes kind, same id | `tests/test_store4_schema.py::test_collection_constraints` |
| 80 | L9 a set referenced by a copy cannot become gear | `tests/test_store4_schema.py::test_collection_constraints` |
| 81 | L9 gear held as stock cannot silently become a set | `tests/test_store4_schema.py::test_collection_constraints` |
| 82 | L9 ... reconcile records it instead (reason 'kind_differs') | `tests/test_store4_schema.py::test_collection_constraints` |
| 83 | L9 UPDATE copy.item_id to a part | `tests/test_store4_schema.py::test_collection_constraints` |
| 84 | L9 INSERT copy of a gear item | `tests/test_store4_schema.py::test_collection_constraints` |
| 85 | L9 UPDATE stock.kind away from the item kind | `tests/test_store4_schema.py::test_collection_constraints` |
| 86 | L9 INSERT wish with a kind that is not the item kind | `tests/test_store4_schema.py::test_collection_constraints` |
| 87 | L10 preferred 970c11 for 970c03 in Red (colour-scoped row) | `tests/test_store4_schema.py::test_collection_constraints` |
| 88 | L10 preferred 970c11 for 970c03 in any other colour | `tests/test_store4_schema.py::test_collection_constraints` |
| 89 | L10 a second preferred link for (970c03, bricklink, Black) | `tests/test_store4_schema.py::test_collection_constraints` |
| 90 | L11 wish for a set (colour NULL) | `tests/test_store4_schema.py::test_collection_constraints` |
| 91 | L11 the same live wish again (NULL colour coalesced) | `tests/test_store4_schema.py::test_collection_constraints` |
| 92 | L12 events are append-only | `tests/test_store4_schema.py::test_collection_constraints` |
| 93 | L13 step error 'unidentified' (G9) | `tests/test_store4_schema.py::test_collection_constraints` |
| 94 | L13 unknown step error code | `tests/test_store4_schema.py::test_collection_constraints` |
| 95 | L14 a system flag cannot be archived | `tests/test_store4_schema.py::test_collection_constraints` |
| 96 | L15 collection foreign_key_check clean | `tests/test_store4_schema.py::test_collection_constraints` |
| 97 | L15 collection integrity_check ok | `tests/test_store4_schema.py::test_collection_constraints` |

L2 "job source 'import' is a seeded source" is an INSERT of a job with `source='import'` under `foreign_keys=ON` (the test's own `SELECT 1` is the
design's, the insert before it is the check).

## 2. Procedure checks (16)

| Check | Test |
|---|---|
| A1 re-download (rows reordered, one vanished, one new): every old key keeps its id | `tests/test_store4_builder.py::test_a1_redownload_keeps_ids_retires_and_revives`<br>`tests/test_store4_reconcile.py::test_done_when_1_a_redownload_keeps_every_id_the_collection_uses` |
| A1 the vanished key is carried, retired, same id | `tests/test_store4_builder.py::test_a1_redownload_keeps_ids_retires_and_revives` |
| A1 the new key is numbered above the high-water mark | `tests/test_store4_builder.py::test_a1_redownload_keeps_ids_retires_and_revives` |
| A1 catalogue_id kept | `tests/test_store4_builder.py::test_a1_redownload_keeps_ids_retires_and_revives` |
| A2 rebuild without the old catalogue: every id the collection references is kept | `tests/test_store4_builder.py::test_a2_catalogue_lost_rebuild_from_the_collection`<br>`tests/test_store4_reconcile.py::test_done_when_2_a_rebuild_from_scratch_seeded_by_the_collection_keeps_the_ids` |
| A2 unreferenced keys get numbers above the collection's high-water mark | `tests/test_store4_builder.py::test_a2_catalogue_lost_rebuild_from_the_collection` |
| A2 and the pair binds (same catalogue_id) | `tests/test_store4_builder.py::test_a2_catalogue_lost_rebuild_from_the_collection` |
| A3 another install numbers differently (decided) and has another catalogue_id | `tests/test_store4_regression.py::test_a3_an_install_with_another_history_numbers_the_same_dump_differently`<br>`tests/test_store4_builder.py::test_a3_another_install_has_a_new_catalogue_id_and_the_same_ids` |
| A4 a set first fetched through the API is adopted by the next dump with its local id | `tests/test_store4_builder.py::test_a4_a_local_item_is_adopted_by_the_next_build`<br>`tests/test_store4_reconcile.py::test_a4_an_adopted_local_item_is_flipped_by_reconcile_and_a_merged_one_is_listed` |
| B1 colour-scoped inverse (970c00/Black to 970c03, 970c11/Red to 970c03, 970c00/Red to 970c05) | `tests/test_store4_mint.py::test_leg_rule_candidates_are_scoped_to_the_minted_colour`<br>`tests/test_store4_identity.py::test_inverse_finds_item_and_colour_with_the_leg_rule` |
| B1 BrickLink colour 72 resolves to the inverse-preferred Rebrickable colour | `tests/test_store4_mint.py::test_colour_links_prefer_the_inverse_preferred_one`<br>`tests/test_store4_identity.py::test_inverse_bricklink_colour_72_takes_the_preferred_rebrickable_colour` |
| B2 sticker sheets: the first keeps the catalogue item, the second becomes a local item | `tests/test_store4_mint.py::test_b3_the_sticker_sheets_are_kept_apart`<br>`tests/test_store4_migrate.py::test_sticker_sheets_stay_apart`<br>`tests/test_store4_identity.py::test_inverse_keeps_sticker_sheets_apart_and_is_injective`<br>`tests/test_store4_regression.py::test_b5_b6_eight_lines_of_one_copy_insert_under_the_line_key_and_read_back_in_bricklink_space` |
| B3 an unmapped BrickLink part becomes a local BrickLink-born item | `tests/test_store4_mint.py::test_rule_5_no_candidate_is_a_local_bricklink_born_item`<br>`tests/test_store4_regression.py::test_b5_b6_eight_lines_of_one_copy_insert_under_the_line_key_and_read_back_in_bricklink_space` |
| B4 the mint is injective on (item, colour) | `tests/test_store4_mint.py::test_b5_the_mint_is_injective`<br>`tests/test_store4_mint.py::test_injectivity_runs_across_holders`<br>`tests/test_store4_identity.py::test_inverse_keeps_sticker_sheets_apart_and_is_injective` |
| B5 all eight 3.3 lines insert without a unique-key collision | `tests/test_store4_regression.py::test_b5_b6_eight_lines_of_one_copy_insert_under_the_line_key_and_read_back_in_bricklink_space`<br>`tests/test_store4_migrate.py::test_every_regression_fixture_migrates` |
| B6 proof in BrickLink space: the 4.0 lines read back through the mint table equal the 3.3 lines | `tests/test_store4_mint.py::test_b6_read_back_in_bricklink_space_equals_the_3_3_keys`<br>`tests/test_store4_migrate_run.py::test_the_proof_passes_on_the_synthetic_store`<br>`tests/test_store4_migrate_run.py::test_the_proof_passes_on_every_regression_fixture`<br>`tests/test_store4_regression.py::test_b5_b6_eight_lines_of_one_copy_insert_under_the_line_key_and_read_back_in_bricklink_space` |

The numbering of the mint tests differs from the design's (the file's docstring says so): its `test_b3_...` is the design's B2, its `test_b5_...`
the design's B4. Rows above use the design's numbers.

## 3. The journey replay

`user-journey.md` is replayed by one test, `tests/test_store4_regression.py::test_the_user_journey_replays_through_the_apps_writers`, on a fixture catalogue (the fixture
dump plus the set `6081-1`, its figures and the arch `2339`, built at test time by the real builder). Every row comes from a writer of the
app: setup and activation (the pair fixture), `core.keys` (save, check with a fake transport), the Add routes (review, confirm), the BrickLink
part-list job (`store4.jobs`), the pipeline's six steps with fake transports, `core.identify.store`. It ends with `foreign_key_check` and
`integrity_check` clean.

| Journey step (`journey.log`) | Where in the test | Writer |
|---|---|---|
| § 0 setup | "0 and 1.1" block | `connect`, `store4.activate` |
| § 1.1 activate: colours, colour links, one event | "0 and 1.1" block | `store4.activate` |
| § 1.2 key saved and tested | "1.2" block | `core.keys.save`, `core.keys.check` |
| § 2 copy of 6081-1: items projected, figure lines, `copy_part` rows with spares | "2" block | Add review and confirm |
| § 2 jobs: picture row, price observation, set link upgraded by the reply | "the job" block | pipeline steps `pictures`, `market_price` |
| § 2.1 pending copy switched in place to BrickLink's list, lines retired, none deleted | "2.1" block | Add with the preference, `jobs.drain` |
| § 3 three stock rows, merge on repeat, 2339 no-match status, prices with `provider_key`, step error `unidentified` | "3" block | Add (loose), pipeline `matching`, `market_price` |
| § 4 two loose figures, the waiter with no match and a candidate | "4" block | Add (loose figure), `matching`, `identify.store` |
| end: foreign_key_check clean, integrity ok | last block | `PRAGMA` |

Where the app does not do what the journey text says, the test asserts what the app does:

- `core.identify.store` writes the `identification` row only; the journey's `item_link` to Brickognize with status `to_check` is not written
  by any writer, so it is not asserted.
- Without a Brickset key the `metadata` step ends `failed` with `source_not_configured` (the journey says the step errors without a key and
  does not say which state).
- The BrickLink list in § 2.1 leaves the Rebrickable arch `2339` unmatched, so BrickLink's own `2339` becomes a local item and the Rebrickable
  line is retired (two retired lines in the test, one in the journey, whose BrickLink list differed by one line only).

## 4. The review's demonstrated failures (design § 12 and § 13)

| Review case | Guarded by |
|---|---|
| FK failure on re-materialisation (L5) | `tests/test_store4_schema.py::test_collection_constraints (L5)`<br>`tests/test_store4_switch.py::test_references_survive_a_switch_away_and_back_and_the_rows_come_back_under_the_same_id`<br>`tests/test_store4_switch.py::test_a_switch_updates_inserts_and_retires_by_key_and_deletes_nothing` |
| Merged id in a live inventory aborts the next Add (L6) | `tests/test_store4_schema.py::test_collection_constraints (L6)`<br>`tests/test_store4_schema.py::test_every_item_reference_has_both_guards`<br>`tests/test_store4_merge.py` |
| NULLs in the stock merge key (L7) | `tests/test_store4_schema.py::test_collection_constraints (L7)`<br>`tests/test_bw_add.py::test_loose_parts_merge_and_undo_restores_the_quantity`<br>`tests/test_store4_regression.py::test_the_user_journey_replays_through_the_apps_writers` |
| Unmatched with an item (L8, C7) | `tests/test_store4_schema.py::test_collection_constraints (L8)`<br>`tests/test_store4_schema.py::test_catalogue_constraints (C7)`<br>`tests/test_store4_regression.py::test_the_user_journey_replays_through_the_apps_writers` |
| Kind change (C3, L9) | `tests/test_store4_schema.py::test_catalogue_constraints (C3)`<br>`tests/test_store4_schema.py::test_collection_constraints (L9)`<br>`tests/test_store4_builder.py::test_bricklink_corrected_kind_is_kept`<br>`tests/test_store4_reconcile.py::test_a_referenced_kind_is_kept_and_recorded_as_kind_differs_then_cleared` |
| Pending BrickLink state (L2) | `tests/test_store4_schema.py::test_collection_constraints (L2)`<br>`tests/test_store4_pending.py`<br>`tests/test_bw_add.py::test_bricklink_pending_settles_end_to_end_through_add`<br>`tests/test_store4_regression.py::test_the_user_journey_replays_through_the_apps_writers` |
| Mint collisions, findings 1 (B1 to B6) | section 2 |
| Review 2, fragile line references (L2, L5, C6) | `tests/test_store4_schema.py::test_collection_constraints (L5)`<br>`tests/test_store4_schema.py::test_catalogue_constraints (C6)`<br>`tests/test_store4_switch.py` |
| Review 8, constraints not enforced (L3, L6, L7, L11) | `tests/test_store4_schema.py::test_collection_constraints`<br>`tests/test_store4_schema.py::test_every_item_reference_has_both_guards`<br>`tests/test_store4_schema.py::test_every_collection_foreign_key_has_an_index_but_three_recorded` |

The `build_dump.py` run (a real 22 October dump: 110,746 items, 0 duplicate line keys, 0 FK violations) needs the real dump and is not in the
suite. `scripts/store4_build_dump.py` builds it by hand; the builder's own tests (`tests/test_store4_builder.py`) cover the same invariants on
invented dumps. Not testable here either: anything that needs prod data (§ 8.11), timing on the Pi, the BrickStore file format.
