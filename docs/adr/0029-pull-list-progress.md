# 0029. Pull list: found counts kept in a setting row, Make it a copy as the one event

- **Status:** accepted
- **Date:** 2026-11-12
- **Decided by:** the brief of issue #202 (pull list, kept progress, one undoable Make it a copy); the storage and the order of the steps are the implementer's choice inside it, for review

## Context

#202 lets a person pull a detected set out of a lot: the set's parts minus what the lot holds, ticked off as they are found in the bulk, ending in an owned copy. The progress has to survive between visits. Ticking is frequent, so one undoable event per tick would bury the history. A table would need a schema step (4.3) and a prod rollout under ADR 0018.

## Options considered

1. **A table `pull_progress`.** Plain, but a schema step for a note that is cleared at the end.
2. **An event per tick**, read back like the sticker choice (ADR 0028). No schema step, but dozens of events per set and an Undo that undoes one tick.
3. **A `setting` row** `pull:<lot id>:<set item id>` holding `{"found": {"<item>:<colour or 0>": n}}`. No schema step, one row per (lot, set), no event, deleted when the copy is made.

## Decision

Option 3. Saving a count is a note, not a change of the collection: it writes no event and has nothing to undo. The row holds only the pieces ticked in the bulk that are not in the lot yet; what the lot already holds counts as found without being stored, so a part that arrives in the lot meanwhile is never counted twice (the reader clamps each count to what the line still lacks). The setting list the app shows reads named keys only, so `pull:*` rows appear nowhere.

**Make it a copy** is the only event. In one transaction it files the ticked pieces in the lot as stock (`stock.add_loose` without its own audit event, condition used, note "Found in the bulk (pull list)"), takes `min(have, need)` per line from the lot's own stock rows (`build_scout.plan_takes`), moves them with `found_copy.make_copy_in` (Build Scout's function: the copy, the rest recorded as missing, one `copy` / `make_from_stock` event), and deletes the progress row. Nothing of another lot is touched. A set made of other sets, nothing found, and a set with no part list are refused with nothing written.

**Undo** is Build Scout's undoer. The stock rows return as the event left them and the copy is archived. The ticked pieces were filed in the lot before the event, so after an Undo the lot holds them and they count as found; the ticks themselves are not restored, which would count them twice.

## Consequences

- No schema change and no prod rollout.
- A stale `pull:*` row (a lot or set that is gone) is harmless and small; Make it a copy and a count of 0 delete it.
- The API has no tool for the found count: it is a chatty note and the MCP adapter maps a body colour to the set path's item. The read and Make it a copy have tools.
