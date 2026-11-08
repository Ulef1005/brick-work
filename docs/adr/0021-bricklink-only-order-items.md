# 0021. An order line for an item only BrickLink has becomes a local BrickLink-born item from the loaded BrickLink list

- **Status:** accepted
- **Date:** 2026-11-04
- **Decided by:** the maintainer made #154 blocking for milestone B (via the wiki-agent, 4 Nov 2026). The shape was set by the brick-work session and narrowed in six Codex review rounds (PR #156)

## Context

In B.4, the maintainer's real BrickLink order #30028491 (64 lines, pasted e-mail) could not be saved. Five lines named items the catalogue does not hold: three instruction booklets (Rebrickable has no instructions kind) and two BrickLink-only sticker and pattern parts. No route could match them (import, hand match by number, API, Add), and review refuses while any line is unmatched. The BrickLink item lists, when loaded, name all five.

## Options considered

1. **Let review skip a held line.** The order could be saved, but the pieces would never reach the collection, and the line would carry no identity.
2. **Create a local BrickLink-born item from the loaded list** at import and at hand match by number, as the part-list fetch (`store4/bricklink_subsets.py`) and the booklet entry (`core/workbench.py`) already do.
3. **Ask the user to add the item first.** Add can't create such items either.

## Decision

Option 2. `core/orders._listed_local` creates the item once (idempotent on its born key) and links it (`method='bricklink_list'`). It does so only when the list names the key and **no item holds it in any colour scope**: the pooled inverse without a colour, and every collection and catalogue link (a projected item's own links decide). A booklet comes through `booklet_item`, so "(Instructions) for Set 7946" names `7946-1`. A booklet is reused only when it is BrickLink's own and has one owner by a confirmed link. The API's fallback for a BrickLink key that names no item creates only from the list (`listed_only`), never another provider's number.

## Consequences

- A real order with BrickLink-only items can be reviewed, saved, received and allocated (proved on the test instance: 45/64 placed, then the whole flow and Undo).
- The behaviour depends on the BrickLink item lists being loaded. Prod has none yet; loading them is the maintainer's decision at B's close-out.
- An import's Undo leaves the created item, unused, as the booklet entry does.
- Name matching stays exact. Seller notes and BrickLink renames still need hand matching (#155).
