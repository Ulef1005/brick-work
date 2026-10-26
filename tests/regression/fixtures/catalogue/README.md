# Fixture catalogue for the migration mint tests (design 8.11)

Never committed as a `.db`: `tests/store4_mint_fixtures.py` builds a catalogue from these files at test time with the real
catalogue builder.

- `dump/` holds a handful of **real rows of the Rebrickable dump** (2026-10-23): parts `3001`, `3023`, `970c03` and the red-legs
  `970c22`, the sticker sheet `003402`, the figure `fig-000004` with its list, the set `2070-1` in two versions, the zero-part set
  `10018247-1` (theme Gear, so kind `gear`), and the colours they use. Rebrickable data, free to use with acknowledgement.
- `mappings/` holds the **shipped mapping rows** (`brickwork/catalogue/mappings/`) for those parts and colours, including the
  Pastel Blue / Maersk Blue pair that shares BrickLink colour 72.
- `dump/rebrickable-minifigs.csv` and `local/figure-composition.csv` are stored under these names (the builder wants `minifigs.csv`; the
  repo guard `test_no_minifig_mapping_ships` refuses any tracked file of that name). `local/figure-composition.csv` is one **synthetic** composition row, written by hand. Nothing here comes from BrickStore, a BrickLink API
  reply or a Rebrickable API reply.

Tests add further synthetic rows (marked `syn` in their names) in code where they need a case the real rows lack, such as a BrickLink
number with two Rebrickable parts.
