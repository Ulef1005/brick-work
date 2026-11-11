# Set scoring

*Unreleased (#199).* For developers. Set scoring ranks the catalogue's sets by how much of a pile of loose parts each one explains. It is one read-only engine that features build on (finding the sets in a lot, Buildable sets); it writes nothing. The code is `brickwork/core/set_scoring.py`.

## What goes in

A parts multiset: `{(item id, colour id): quantity}`. A loose minifigure is `(item id, None)`. Each line may carry flags (strings, such as `sticker`) that the answer hands back untouched. Builders make the multiset from the collection:

| Builder | Input |
|---|---|
| `from_lot(db, lot_id)` | the live loose parts and figures in a lot |
| `from_storage(db, storage_id)` | the live loose stock in a storage and in the storages inside it (`below=False`: that storage only) |
| `from_loose(db)` | all live loose parts and figures |
| `from_stock(db, stock_ids)` | a saved selection of stock lines |

Each returns `(parts, flags)`; the flags are the stock rows' own flag names. A loose figure is one whole-figure line, not its parts, so a figure is never counted twice. `score(db, parts, flags, limit=20, offset=0, detail=10)` ranks.

```python
from brickwork.core import set_scoring
parts, flags = set_scoring.from_lot(db, lot_id)
answer = set_scoring.score(db, parts, flags, limit=10)
```

## The index

For every (part, colour), the set of sets whose inventory holds it, with the quantity. A query touches only the sets that share a line with the input. The index is built once per catalogue build and process (a few seconds on the full catalogue), kept as two compact arrays per line, and replaced when the catalogue file, its newest build or the collection's activated builds change.

- **Candidates** are sets with a live, latest inventory that has at least one line. Spare lines are left out, as the part-list rule says. Figures, parts, boxes and booklets are not candidates.
- **A minifigure** in a set counts twice, as separate lines: its own parts (the figure's latest inventory, times the figure's quantity in the set) and the whole figure. A set's line and quantity totals include both.
- **A sub-set** of a set is expanded into it with its quantity multiplied, recursively; a cycle is cut where it closes.

## Weight, evidence, coverage

| Field | Value |
|---|---|
| Definition | How much a line says about which set a pile came from: rare lines say a lot, common ones almost nothing |
| Formula | `w = ln(N / df)`: N the candidate sets, df the sets that hold the line |
| Unit | Nats (a line in every set weighs 0; one in 2 of 25,000 sets weighs about 9.4; one in 2,500 about 2.3) |
| Code | `brickwork/core/set_scoring.py::build_index` |

| Field | Value |
|---|---|
| Definition | What one set explains of the pile |
| Formula | `evidence = sum over the set's lines that the pile has of w * min(have, need) / need`; `coverage = evidence / sum of w over all the set's lines` |
| Unit | Evidence in nats; coverage 0 to 1 |
| Code | `brickwork/core/set_scoring.py::rank` |

Sets are ranked by evidence, then coverage, then set id. A set shows its covered quantity and lines, the lines covered in full, and the distinctive lines found of its own (a line held by at most 25 sets is distinctive).

## Swaps

Swaps are listed per returned set and never counted: not in the evidence, the coverage or any other number. A swap is the pile's leftover on a line (its quantity less what this set takes of it) against a line of the set that the pile does not cover:

- **colour**: the same part in another colour;
- **mould**: an alternate mould in the same colour, by the catalogue's part relationships of type A (alternate) and M (mould variation), in either direction. Print, pattern, pair and sub-part relations are not swaps.

A set whose only overlap is a swap is not ranked. One input line may appear in several swaps; nothing is allocated across them.

## Result

`score` returns `catalogue` (the index: sets, lines), `input` (lines, quantity, matched and unmatched lines, up to 50 unmatched), `total` (sets sharing a line with the pile), `limit`, `offset`, `cached` and `results`. Each result has `rank`, `evidence`, `coverage`, `covered_quantity`, `set_quantity`, `covered_lines`, `complete_lines`, `set_lines`, `distinctive_found`, `distinctive_total`, `matched` (the heaviest `detail` lines, each with its need, covered quantity, weight and flags), `flags` (per flag: lines, covered quantity, evidence) and `swaps` (`lines`, `quantity`, up to 20 `items`).

The ranking is cached per catalogue build and input (the last 8 inputs in a process), so paging is cheap; each page's detail is built fresh.

## API

`GET /api/v2/planning/set-scores` takes exactly one of `lot`, `storage`, `loose=true` or `stock` (repeated), plus `limit` (1 to 100), `offset` and `detail` (0 to 50). It needs a read token and writes nothing. An arbitrary multiset is not an API input (a read is a GET); call `score` from Python. The MCP tool is `get_planning_set_scores`.

## Candidate sets of a lot (Lot Detective, #200)

`brickwork/core/candidate_sets.py` turns the engine's ranking of a lot into the answer to "which sets came in this lot?". `candidates(db, lot_id, *, min_score, theme, year_from, year_to, parts_min, parts_max, ignore_common, limit, offset)` is the service; `GET /api/v2/lots/{id}/candidate-sets` (MCP tool `get_lot_candidate_sets`) is the API. It reads the lot's live loose parts and figures, scores them and writes nothing. The screen is built on it later.

| Field | Value |
|---|---|
| Definition | How strongly the found parts point to a set, relative to the best candidate. Not a probability |
| Formula | `score = round(100 * evidence / best evidence)`, a whole number 0 to 100; the best candidate is the first set that passes the theme, year and size filters, so it scores 100 |
| Unit | Percent of the best candidate |
| Code | `brickwork/core/candidate_sets.py::candidates` |

Order of work: the lot's lines; **ignore common** (a line held by more than N sets is dropped before scoring, so it moves no evidence and the digest of the input changes); the engine's cached ranking; sets with no evidence dropped; the set filters; normalise; `min_score`; page. `total` counts the sets left after all of that, so paging and `total` are right under every filter.

- **Ignore common** is on by default. N is the stored setting `candidate_sets_common_max` (the `setting` table, shown by `GET /settings`, changed by `PATCH /settings` with the `admin` scope, audited), default 300, a whole number of at least 25 (the engine's distinctive limit, so a distinctive line is never dropped). An invalid stored value reads as 300. No environment variable.
- **Filters.** `theme` is a catalogue theme id (digits) or a name (case-insensitive) and takes the themes below it too; an unknown theme is an error. Years and part counts are the catalogue item's `year` and `num_parts`; a set without the value does not pass a filter on it. The part count is the catalogue's number for the set, not the engine's `set_quantity` (which counts figure lines twice).
- **Distinctive parts.** A distinctive line is a (part, colour) line that at most 25 sets hold (`DISTINCTIVE_MAX`). `distinctive_found_parts` are the ones the lot has, `distinctive_missing_parts` the ones it has none of yet, heaviest first, up to 20 each; the counts `distinctive_found` and `distinctive_total` are for the whole set. A part that exactly one set holds in that colour is *only in this set*.
- **Printed.** A part is printed when its number holds a print suffix, `pr` followed by a digit (3626bpr0001, 973pr1234c01), or when the catalogue lists it as the child of a part relationship of type P (Rebrickable's print). It is derived from the catalogue; nothing is stored. Only parts that are *only in this set* are marked.
- **Reasons**, in order: "N of M distinctive parts found" (when the set has any); "Matched on common parts only" (when none was found); "N printed parts only in this set"; "N (other) parts only in this set"; "N of M part lines of the set are in the lot". The counts cover the whole set, not only the listed parts.
- **Flags and stickers** (#201, [ADR 0027](../adr/0027-sticker-evidence.md)). A stock flag named Sticker (any case) is passed to the engine as `sticker` and comes back per set in `flags`. An *unconfirmed* sticker raises, for each set that holds the line and a sticker sheet (a part of the category named Stickers), the line's evidence by a quarter of its own share (`HINT_FACTOR` 1.25, never above 1.5). A *confirmed* sticker ("This one") is near-certain evidence: for the chosen set the line's evidence is `2 * ln N` (`CONFIRMED_FACTOR`), twice the largest weight a line can carry, and the reasons say "sticker of set 1682-1 confirmed"; other sets get nothing extra. A flagged line is never dropped by Ignore common parts. The rule is applied after the cached ranking (`apply_stickers`), so a changed flag changes the order at once. `GET /planning/set-scores` applies it too.
- **Swaps.** Each set lists the engine's swaps (the lot has the part in another colour, or an alternate mould), up to 20, apart from every number. The lot page shows them under "Swaps, not counted in the score".
- **Cache.** The ranking is the engine's, cached per catalogue build and input, so an unchanged lot is not ranked again and a changed lot (a different input) is. The filters and the page are applied on each call.

## Speed

Measured on a Mac with a catalogue of about 21,000 sets (1.6 million postings): the index takes about 2 s to build (the first query pays it) and about 400 MB at its peak while loading; a 2,000-line pile is then ranked with its first page of 20 sets in about 0.1 s, and another page of the same input in about 0.04 s. The target is under 10 s for such a pile on the machine that serves the app, cold. `python scripts/bench_set_scoring.py path/to/catalogue.db` builds a random pile from a real catalogue file (read-only) and prints the load and build times, the memory, the cold and warm query times and PASS or FAIL against the target, so it can be run on that machine.
