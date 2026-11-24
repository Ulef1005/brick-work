# 0041. Your rating and priority: `copy.rating` and `wish.priority`

- **Status:** proposed (accepted when the pull request for #690 merges)
- **Date:** 2026-11-24
- **Decided by:** Ulf, issue #690 ("Reduce nothing: build the full frames"), 2026-11-24. The two columns and their ranges are the build's proposal.

## Context

Brickset holds a rating and a wanted priority for each set. Brick Work has no place for either, so the Brickset sync page cannot show or sync them.

## Decision

- `copy.rating`: a whole number from 1 to 5, or NULL for not rated. The person's own stars for one copy.
- `wish.priority`: a whole number of 1 or more, or NULL for none. 1 is the highest. Brickset's own top value cannot be seen from its answers (a live read showed only 1, its default), so no upper limit is set.
- Schema 4.8 to 4.9, one additive step. Every row already there stays NULL. No index, no trigger and no CHECK: the range is validated in the write path (a rating 1 to 5, a priority 1 or more); Brickset's rating 0 means not rated and maps to NULL in its adapter, because an upgrade step can only add and a wrong CHECK would stay.
- Both are ordinary editable fields: the edit path, Undo, API v2 and the own export and import carry them. The own CSV gets a `Rating` column for sets.
- The Brickset mapping is not part of this change. A set's Brickset rating goes to every live copy of the set, and its priority to the wish; that rule belongs to the Brickset sync (#690, the sync session).

- A rating on a copy counts as the person's work: the Undo of an Add refuses when it was set after the Add. A merge of two wishes keeps a priority the surviving wish lacks.
- A hand edit of one copy stays until the next Brickset pull, which sets every live copy of the set alike. A set with no copy keeps no rating here.

## Alternatives

- **Keep the existing model.** A read-only mirror in `item_property` (source `brickset`, one value per set) needs no column. It would lose Edit, Undo, API v2 and the own export, and the complete export of #524 must carry both values. Rejected (architect review, 2026-11-24).
- **A per-set rating table.** Rejected: the plan with the Brickset session is per copy.

## Consequences

- Moving a row between a set and loose stock does not carry a rating; its Undo restores it.
- A set with several copies can hold several ratings here. A Brickset pull sets them all alike.
- The rating range is Brick Work's own. A site that uses another scale is mapped by its adapter.
