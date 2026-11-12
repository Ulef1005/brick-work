# 0028. Stickers: a flag, a choice kept as an undoable event, and a documented evidence rule

- **Status:** accepted
- **Date:** 2026-11-12
- **Decided by:** the brief of issue #201 (the flag, the chooser, the evidence rule); the storage and the factors are the implementer's choice inside it, for review

## Context

Brickognize sees the base part under a sticker, so the print is a clue only the person can read. #201 lets them mark a part as having a sticker and later choose the sticker. The catalogue has sticker sheets (parts of the category `Stickers`) but no link from a sticker to the part it goes on. The choice must be undoable in one step and must count as evidence in set detection (#200).

## Options considered

1. **A table `stock_sticker`.** The obvious shape. It needs a schema step (4.3): a one-way upgrade, a prod rollout under ADR 0018, changes to the dump, merge and audit lists, and every schema-version test. A lot for one small fact per part line.
2. **A tag flag per chosen set** ("Sticker of 1682-1"). No schema change, undo for free, but the flag list would fill with names that carry data, and the sheet is lost.
3. **The event log.** An event `stock_sticker:<stock id>` with the field `confirm` (the set, the sheet, the lot) or `clear`. The line's state is its newest such event that was not undone, so Undo of a later choice shows the earlier one again. No schema change.

## Decision

Option 3. The Sticker flag is a `tag` flag named Sticker, made on first use and put on the stock line when the batch is filed (the filing receipt records the link it made, so its Undo takes only that back). "This one" writes `confirm`, "Not a sticker" removes the flag and writes `clear`; each is one event with a registered undoer. A confirmation counts only while the line holds the flag. The scoring engine reads the latest event of the line when it builds its input.

Evidence rule (`core/set_scoring.py`, applied after the cached ranking so the cache key stays the parts):

- **Unconfirmed sticker:** for each set that holds the line and a sticker sheet, the line's evidence is raised by a quarter of its own share (`HINT_FACTOR = 1.25`, never more than the 1.5 times the brief allows). Other sets are unchanged.
- **Confirmed sticker:** for the chosen set the line's evidence is `2 * ln N` (`CONFIRMED_FACTOR`), twice the largest weight any line can carry, in place of its own share; other sets get nothing extra from that line. The set's reasons say "sticker of set X confirmed".
- A flagged line is never dropped by Ignore common parts: a sticker base part is usually a tile or a brick many sets hold.

## Consequences

- No schema change and no prod rollout. If a table is wanted later, the events are the history to migrate from.
- The state of a line is read from the log: one indexed query per flagged line (`event_entity`).
- The factors are constants in the module, documented in the reference page, not settings.
- A merged stock row (the same part, colour, condition and lot) carries one flag for all its pieces.
- The chooser lists sets by their own latest inventory; sub-sets are not expanded there, though the engine expands them.

## Links

Issue #201; [ADR 0026](0026-set-scoring-weights.md); the reference page Set scoring.
