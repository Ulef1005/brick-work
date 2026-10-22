# Spike #102: Rebrickable dump, mappings to BrickLink, measured

Throwaway code for issue #102, kept on this branch only (not for `main`). Run on 22 Oct 2026 on a Raspberry Pi 5 against copies of the test instance's `brickwork.db` and `bricklink-catalog.db`; `report.json` and `figs.json` are the output (aggregates and catalogue numbers only).

| Script | What it does | Calls |
|---|---|---|
| `rb_import.py <dump dir> <out.db>` | imports the 12 Rebrickable CSV files | none |
| `rb_ext.py <rb.db>` | Rebrickable `external_ids` for all colours and parts (`BW_REBRICKABLE_API_KEY`) | 66 |
| `bl_subsets.py <brickwork.db> <rb.db> <n>` | BrickLink `subsets` for n held sets, chosen by hash (`BW_BRICKLINK_*`) | n (50) |
| `analyse.py <rb.db> <bricklink-catalog.db> <brickwork.db> <report.json>` | mapping shape, coverage, accuracy | none |
| `gaps.py <rb.db> <brickwork.db>` | the accuracy gaps by part number, ignoring colour | none |
| `bl_figs.py <rb.db> <brickwork.db> <n> <figs.json>` | BrickLink inventories of n migration-matched minifigures vs the dump's composition; composition uniqueness across all Rebrickable figures | n (100) |

The findings are in the report comment on #102.
