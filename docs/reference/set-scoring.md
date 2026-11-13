---
audience: user
verified: 1.0
---

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

For every (part, colour), the set of sets whose inventory holds it, with the quantity. A query touches only the sets that share a line with the input. The index is built once per catalogue build and process (a few seconds on the full catalogue) and kept as two compact arrays per line. It is replaced when the catalogue file, its newest build or the collection's activated builds change.

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

Sets are ranked by evidence, then coverage, then set id. A set shows its covered quantity and lines, the lines covered in full, and the distinctive lines found of its own. A line held by at most 25 sets is distinctive.

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

`brickwork/core/candidate_sets.py` answers "which sets came in this lot?" from the engine's ranking of a lot. `candidates(db, lot_id, *, min_score, theme, year_from, year_to, parts_min, parts_max, ignore_common, limit, offset)` is the service; `GET /api/v2/lots/{id}/candidate-sets` (MCP tool `get_lot_candidate_sets`) is the API. It reads the lot's live loose parts and figures, scores them and writes nothing. The screen is built on it later.

| Field | Value |
|---|---|
| Definition | How strongly the found parts point to a set, relative to the best candidate. Not a probability |
| Formula | `score = round(100 * evidence / best evidence)`, a whole number 0 to 100; the best candidate is the first set that passes the theme, year and size filters, so it scores 100 |
| Unit | Percent of the best candidate |
| Code | `brickwork/core/candidate_sets.py::candidates` |

Order of work:

1. The lot's lines.
2. **ignore common** (a line held by more than N sets is dropped before scoring, so it moves no evidence and the digest of the input changes).
3. The engine's cached ranking.
4. Sets with no evidence dropped.
5. The set filters.
6. Normalise.
7. `min_score`.
8. Page.

`total` counts the sets left after all of that, so paging and `total` are right under every filter.

- **Ignore common** is on by default. N is the stored setting `candidate_sets_common_max` (the `setting` table, shown by `GET /settings`, changed by `PATCH /settings` with the `admin` scope, audited). Its default is 300, and it is a whole number of at least 25 (the engine's distinctive limit, so a distinctive line is never dropped). An invalid stored value reads as 300. No environment variable.
- **Filters.** `theme` is a catalogue theme id (digits) or a name (case-insensitive) and takes the themes below it too; an unknown theme is an error. Years and part counts are the catalogue item's `year` and `num_parts`; a set without the value does not pass a filter on it. The part count is the catalogue's number for the set, not the engine's `set_quantity` (which counts figure lines twice).
- **Distinctive parts.** A distinctive line is a (part, colour) line that at most 25 sets hold (`DISTINCTIVE_MAX`). `distinctive_found_parts` are the ones the lot has, `distinctive_missing_parts` the ones it has none of yet, heaviest first, up to 20 each; the counts `distinctive_found` and `distinctive_total` are for the whole set. A part that exactly one set holds in that colour is *only in this set*.
- **Printed.** A part is printed when its number holds a print suffix, `pr` followed by a digit (3626bpr0001, 973pr1234c01). It is also printed when the catalogue lists it as the child of a part relationship of type P (Rebrickable's print). It is derived from the catalogue; nothing is stored. Only parts that are *only in this set* are marked.
- **Reasons**, in order (the counts cover the whole set, not only the listed parts):
    - "N of M distinctive parts found" (when the set has any)
    - "Matched on common parts only" (when none was found)
    - "N printed parts only in this set"
    - "N (other) parts only in this set"
    - "N of M part lines of the set are in the lot"
- **Flags and stickers** (#201, ADR 0028). A stock flag named Sticker (any case) is passed to the engine as `sticker` and comes back per set in `flags`. An *unconfirmed* sticker raises the line's evidence by a quarter of its own share (`HINT_FACTOR` 1.25, never above 1.5). It does so for each set that holds the line and a sticker sheet (a part of the category named Stickers). A *confirmed* sticker ("This one") is near-certain evidence. For the chosen set the line's evidence is `2 * ln N` (`CONFIRMED_FACTOR`), twice the largest weight a line can carry. The reasons say "sticker of set 1682-1 confirmed" and other sets get nothing extra. A flagged line is never dropped by Ignore common parts. The rule is applied after the cached ranking (`apply_stickers`), so a changed flag changes the order at once. `GET /planning/set-scores` applies it too.
- **Swaps.** Each set lists the engine's swaps (the lot has the part in another colour, or an alternate mould), up to 20, apart from every number. Under "Swaps, not counted in the score" the lot page shows them.
- **Cache.** The ranking is the engine's, cached per catalogue build and input, so an unchanged lot is not ranked again and a changed lot (a different input) is. The filters and the page are applied on each call.

## Speed

Measured on a Mac with a catalogue of about 21,000 sets (1.6 million postings):

- The index takes about 2 s to build (the first query pays it) and about 400 MB at its peak while loading.
- A 2,000-line pile is then ranked with its first page of 20 sets in about 0.1 s. Another page of the same input takes about 0.04 s.

The target is under 10 s for such a pile on the machine that serves the app, cold. `python scripts/bench_set_scoring.py path/to/catalogue.db` builds a random pile from a real catalogue file (read-only). It prints the load and build times, the memory, the cold and warm query times and PASS or FAIL against the target, so it can be run on that machine.

## Build Scout

*Unreleased (#9).* Build Scout (`brickwork/core/build_scout.py`) answers a different question from the ranking above: not which set a pile came from, but how much of each set the pile already makes. It reads the same catalogue through the same code (`load_rows`, `build_index`), as two indexes built once per catalogue build and process. They are the **parts** index (a set's own parts, sub-sets expanded, spares left out) and the **figures** index (whole figures only, sub-sets expanded). The rarity weight plays no part. ADR 0027 records the definitions.

| Field | Value |
|---|---|
| Definition | Pieces of a set the stock covers |
| Formula | `parts_available = sum over the set's part lines of min(have, need)`; `have` is the quantity of the same part in the same colour in the chosen stock |
| Unit | Pieces |
| Code | `brickwork/core/build_scout.py::covered_by` |

| Field | Value |
|---|---|
| Definition | The share of a set's parts the stock covers |
| Formula | `percent = 100 * parts_available / parts_total`, one decimal; `parts_total` is the sum of the set's part-line quantities (spares and a minifigure's components are not part lines) |
| Unit | Percent |
| Code | `brickwork/core/build_scout.py::ranked` |

`missing_parts = parts_total - parts_available` (pieces) and `missing_lines` is the number of part lines the stock does not cover in full. **Figures** are counted apart: `figures_available = sum over the set's whole-figure lines of min(have, need)` against `figures_required`; a loose whole figure counts, loose parts of a figure never do. **Swaps** are the engine's (another colour, an alternate mould), listed per set and never in a number above. Sets are sorted by `percent`, then fewest missing parts, then set id.

**Cost to complete** adds `price * missing` over the missing part lines and missing figures that have a price in `price_current`. The price used prefers the used price before the new one, a sold average before a stock listing, the newest observation last. The sum is in the currency most of the page's missing lines are priced in. A line with no price, or a price in another currency, is not added and is counted as `unpriced_lines`; with no priced line the amount is `null`. It is worked out for the page shown, never for the whole catalogue.

**The stock** is one rule for the ranking and for Build it (`stock_rows`): live loose parts and minifigures. Each is counted as `workbench.available` says. A damaged row counts for nothing unless asked for, a figure with defective parts for nothing, and a row's missing and damaged counts are taken off. A selection is the union of the stock kept in no lot or storage (`loose`), the chosen lots and the chosen storages with the storages inside them. None chosen means all loose stock. A row in a chosen lot and a chosen storage counts once.

**Build it** (`build_scout.build_set`, over `brickwork/store4/found_copy.py::make_copy_in`) takes from exactly those rows, the largest usable row first and then the lowest id. It takes `min(have, need)` of every part line and of every whole-figure line, into one new copy of the catalogue's latest Rebrickable part list. The rest is `missing` on the copy (a missing figure's components too). It is one transaction and one event, `copy` / `make_from_stock`, whose receipt is a row log; `stock_transfer` rows are kept as provenance. Undo (the event's registered undoer) puts the stock rows back and archives the copy. It is refused when any row it changed differs now or the copy has been given flags, a check, photos or other transfers since. A set made of other sets is refused: the copy's part list does not expand sub-sets, the Scout's index does. `make_copy_in(db, set_item_id, takes, ...)` is the shared piece for any action that turns held parts into a copy (`takes` is a list of `(stock id, amount)`).

**API.** `GET /api/v2/planning/build-scout` (MCP tool `get_planning_build_scout`) and `POST /api/v2/items/{id}/build` (see the API v2 reference, 2.10). `scripts/bench_build_scout.py` times it on a real catalogue. On a catalogue of about 21,000 sets:

- The two indexes take about 2 s and 390 MB at the peak while loading.
- Ranking every set that shares a part with a pile of 2,000 lines takes about 0.1 s (0.2 s for 8,000 lines).

## Pull list

*Unreleased (#202).* The pull list of a candidate set (`brickwork/core/pull_list.py`) is not a score. It reads the set's lines as Build Scout does (own parts with sub-sets expanded, spares left out, whole figures as lines) and compares them with one lot. Per line, `need` is what the set has, and `held` what the lot can give (damaged rows give nothing, capped at `need`). `found` is `held` plus the pieces ticked in the bulk and not filed yet. The ticks are one setting row `pull:<lot id>:<set item id>` (ADR 0029); each is clamped to what the line still lacks. The three numbers of the confirm are `moves` = the sum of `found`, `missing` = the sum of `need` minus `moves`, and `stays` = the pieces the lot holds, plus the ticked ones, minus `moves`. Make it a copy files the ticked pieces in the lot and moves `min(have, need)` per line with `found_copy.make_copy_in`, one event. See [Pull a set out of a lot](../how-to/pull-a-set-out-of-a-lot.md).
