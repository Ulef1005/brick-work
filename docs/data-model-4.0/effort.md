# Brick Work 4.0: effort re-estimate (revision 2)

Written 2026-10-23 for the revised design in this folder. The units are weeks of session work, each piece landing through the check gate and a review. The initial design said 12 weeks. The cold review said 17–20, because the test suite and the screens for the new concepts were not counted. This estimate counts both, and the work the decisions of 23 Oct added or removed.

**Size of the code it touches** *(measured on `main` `5fe64ec`)*:

- app code: 20,027 lines of Python in `brickwork/`, of which 9,864 are in `brickwork/core/*.py`. 55 app files reference `item_type`, `item_no`, `copy_parts`, `loose_stock` or `id_match`.
- tests: 23,478 lines in 121 Python files under `tests/`. 61 of those files reference `item_type`.

## Per piece

| # | Piece | Weeks | What is in it |
|---|---|---|---|
| 1 | Schema and connection | 1.0 | Both DDL halves (`schema-4.0.sql`, tested); `connect()` for two files: read-only attach, `journal_mode=DELETE` for the catalogue, binding and the high-water and build checks; the generated guard triggers; `identity.project()`; the resolution function (§ 3.2) and its inverse; the SQLite version assertion |
| 2 | Catalogue builder | 2.5 | Dump loader in the measured shape; id seeding from the old file and the collection; high-water marks; carrying retired rows; build-and-swap; theme kinds; `bl_digest`; FTS; the shipped, rule and local mapping layers; BrickLink list and colours as a seeded rebuild; `same_number` pass; reconcile (names, kinds with `kind_differs`, upgrades, retirement, adoption, coverage); `catalogue import/rebuild/reconcile/status` CLI |
| 3 | Shipped mappings, built once | 1.0 | `colors.csv` with BrickLink ids and names from Rebrickable's colour `external_ids`, plus inverse flags; `parts.csv` from `external_ids` and element ids; the leg-rule generator for `970cNN` with colour scope; `set_exceptions.csv`; `theme_kinds.csv` for the zero-part themes; the `.gitignore` negation; the check-gate test that keeps `minifigs.csv` out of the repo |
| 4 | BrickStore minifigure mapping test (private, one-off) | 0.75 | Read BrickStore's database format; project 17,293 Rebrickable figures to BrickLink keys; compare compositions; write `data/mappings/minifigs.csv` and its manifest; measure agreement with prod's 546 matched and 20 manual figure decisions and with the spike's 100 |
| 5 | Acquired part lists | 0.75 | `fetched_inventory` and its lines; the BrickLink `subsets` adapter with the extras fix (required = quantity − extra); line resolution to local BrickLink-born items; the Rebrickable API fetch for newer sets and figures; adoption by the next dump |
| 6 | Copies: materialisation and switching | 1.0 | Materialise from catalogue or fetched lists; the in-place switch with retirement and capped carry-over; the receipt; the pending BrickLink state and the automatic switch (decision F); `set_preference`; the global switch (Q13); "part list changed" detection for copies and figure lines |
| 7 | Migration 3.3 → 4.0 | 2.0 | The colour-scoped, context-aware, injective mint; the `?` rule; extras correction; Q7 sums; Q12 and Q15 attachment through `bl_digest`; timestamp and money-pair rules; settings translation and the sync link; the BrickLink-space proof; the report files; the fixture catalogue and the new 3.3 fixture; a rehearsal on test pinned to the cutover catalogue file; the prod measurements of design § 8.11 |
| 8 | Core modules on `item_id` | 4.5 | The 55 app files: collection, add, checker, workbench, planning, partout, orders, receipts, ledger, stock, wishlists, pictures (three sources and the order setting), names, sync, the BrickTracker importer, identify, completeness, recompute, `collection_prices`, exports. Also `item_link`/`item_provider_status` in place of `id_match`, retired lines excluded everywhere, and the `unidentified` step error |
| 9 | Test-suite rewrite | 2.5 | 61 test files that build 3.3 rows by type and number move to `item_id` fixtures; a shared fixture catalogue; the review's failure cases as regression tests (the SQLite probes of design § 12 become pytest cases); the API parity test against v2 |
| 10 | Screens for the new concepts | 2.0 | Item page: links per provider and colour, preferred choice, provider status, merge and unmerge. Unresolved list (`to_check` links plus provider status). Add review: part-list picker, *Fetch from Rebrickable*, *Add as unidentified*, picture warning. Copy page: "version n of m", switch, "BrickLink list pending" with cancel, figure-part source, "part list changed", retired-line note. Tools & Admin: re-download with the once-a-day text, rebuild, BrickLink list load, local mapping status, coverage. Settings: prefer BrickLink, picture order. Migration report view. Each in the three sizes of the brickwork-design kit |
| 11 | API v2 and clients | 1.5 | Paths with number lookups, serialisers, write contract, OpenAPI v2, MCP regenerated (number-taking tools), `410` for v1, `lego-add` and the House API pass-through with `test_lego.py`, the API docs |
| 12 | Onboarding, checks, cutover | 0.75 | Onboarding step 1 on the dump (#85); `brickwork check` cross-file checks (born keys, inventory natural keys, digests); Borg file list; ADR 0016; the cutover runbook and checklist |
| 13 | Contingency | 1.0 | About 5 %: the items below are uncertain enough to need it |
| | **Total** | **21.25 → about 20 weeks** (range 18–22) | Pieces 2, 3 and 4 can run beside piece 1. 8 and 9 overlap in practice, since tests move with the modules. The single-number figure assumes that overlap saves about a week |

## Compared with the review's 17–20

| Change | Effect |
|---|---|
| The migration scope shrank (no events, `id_match`, `source_records`, jobs or orders) | −0.5 against the initial migration line |
| … but the mint is now colour-scoped and injective, with a BrickLink-space proof, a fixture catalogue and settings translation | +0.75 |
| Acquired lists move to the collection; build-and-swap with seeded running ids | about +0.5 in pieces 2 and 5, as the review assumed |
| The BrickStore test is a new piece | +0.75 |
| The pending state, the in-place switch and the Add picker (Q13, Q23, F) | +0.5 (piece 6 and part of 10) |
| Screens counted explicitly | 2.0, against the review's 1–1.5 allowance for identity and version screens only |

## Least certain lines

1. **Core modules (4.5).** The figure comes from counting files, not from reading each module. Planning, partout and the BrickTracker importer carry the most typed-key logic. Re-estimate after the first three modules.
2. **Test-suite rewrite (2.5).** 61 files construct typed rows by hand. If most go through shared helpers the figure falls; if not, it rises. Count helper use before starting.
3. **BrickStore test (0.75).** The file format has not been read here. If it is not a documented or easily read format, this piece can double.
4. **Screens (2.0).** No screen exists yet in the design kit for links, merge, the picker or the pending state. The figure assumes the kit's existing patterns fit.
5. **Migration (2.0).** It depends on prod measurements not taken yet (design § 8.11): the number of local items and collisions the mint produces, the Q12 hit rate, and rows that break the count bounds. A large number of to-check items would add review screens and time.
