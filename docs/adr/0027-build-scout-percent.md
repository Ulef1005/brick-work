# 0027. Build Scout: percent available counts a set's own parts, figures apart

- **Status:** accepted
- **Date:** 2026-11-12
- **Decided by:** the brief of issue #9 (parts available and missing, figures, cost, swaps listed apart); how "% of parts available" is defined is the implementer's choice inside it, for review on the pull request.

## Context

Build Scout ranks every catalogue set by how much of it the loose stock already makes, and its **Build it** action moves those parts into a copy. The scoring engine (ADR 0026) counts a minifigure twice, as its component parts folded into the set's own `(part, colour)` lines and as a whole-figure line, and counts that whole figure as one piece of the set. That is right for finding where a pile came from; for "how complete would this set be" it would show a set as missing parts of a figure you hold whole, and count a figure as a piece.

## Options considered

1. **The engine's numbers.** Covered quantity over the set quantity. Rejected: a held figure would read as missing parts, and a figure would be one "part".
2. **Parts and figure components together, a loose figure covering its components.** Closest to a physical set. Rejected for a first version: it needs the figure inventories in the index and a rule for loose parts of the same figure; the copy it makes would need the same rule.
3. **Own parts only, figures apart (chosen).** The percentage is over the set's own part lines; the whole figures are a separate "n of m figures".

## Decision

Option 3. `parts_available = sum over the set's part lines of min(have, need)`, `percent = parts_available / parts_total`, `missing_parts = parts_total - parts_available`, where the part lines are the set's own parts with spares left out (ADR 0011) and the parts of sub-sets expanded with their quantity; a minifigure's components are not part lines. `figures_available = sum over the whole-figure lines of min(have, need)` and a loose whole figure counts. Swaps (ADR 0026) stay apart and enter no number. The two indexes are built with the engine's `build_index` from the engine's `load_rows`, so sub-sets and spares are handled by the same code.

The stock is one eligibility rule shared by the ranking and by Build it: live loose parts and minifigures, with the quantity `workbench.available` gives (damaged off unless asked for, a figure with defective parts none).

Build it makes a copy of the catalogue's latest Rebrickable part list (the list the numbers came from) and moves exactly what the percentage counted, as one event whose Undo archives the copy and puts the stock back. A set made of other sets is not built, because a copy's part list does not expand sub-sets.

Cost to complete uses the current prices of the missing lines, in the one currency most are priced in; a line without a price is counted, never guessed.

## Consequences

- "398 of 430 parts · 1 of 3 figures" is two statements, and a set's figure components never lower its percentage.
- A figure held as loose parts does not count as the figure; to count it, put the parts together as a figure in loose stock.
- The percentage is over parts the stock could give: damaged stock is off by default.
- Sets that contain other sets rank, but cannot be built from the screen yet.
- The whole-figure line and the sub-set expansion are the engine's, so a change to either (ADR 0026) changes Build Scout too.

## Links

Issue #9; [ADR 0026](0026-set-scoring-weights.md); [ADR 0011](0011-part-list-rule.md); the reference page Set scoring (`docs/reference/set-scoring.md`).
