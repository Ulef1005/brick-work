---
audience: user
verified: 1.0
---

# Pull a set out of a lot

*Since 1.1.0.*

Set detection says a set is probably in your bulk lot. The pull list shows which of its parts you still have to find and lets you tick them off as you find them. It ends with an owned copy of the set.

## Open the pull list

1. Open the lot and go to **Which sets are in this lot?**
2. On a candidate set, select **Pull list**.

The list has every part of the set (the latest part list, spare parts left out, whole minifigures as their own lines) grouped by category with pictures. Each line shows a counter, for example **2 of 4**: the pieces found of the pieces the set has. Pieces the lot already holds count as found and are marked *already in the lot*. A line with all its pieces found turns green and ticked.

## Tick parts as you find them

- Use **−** and **+** on a line, or the box on the left to say all pieces of the line are found. Each tap saves at once, and the page comes back to the same line. It works without scripts.
- **Search parts**, **Show** (To find, Found, All) and **Sort** (Category, Number) narrow the list. The top of the page shows how many pieces are found and how many are left.
- Your progress is kept. You can stop and come back, on this or another device.

A piece you tick is not filed in the lot until you make the copy. Saving progress changes nothing else and has no Undo.

## Make it a copy

1. Select **Make it a copy** (the card on the right, the bar at the foot of a phone).
2. The confirm shows three numbers: the found pieces that move out of the lot, the pieces recorded as missing on the copy, and the pieces that stay in the lot.
3. Select **Make copy of 6080-1**.

One step does everything: the pieces you ticked are filed in the lot, then exactly the found pieces move from this lot into a new copy of the set. Everything the set has and you did not find is recorded as missing on the copy, so it shows in Matcher, Complete sets and the missing-parts XML. The copy starts as incomplete (complete when nothing is missing) and not checked. The lot keeps the leftovers; run set detection again to find the next set. Nothing in another lot is touched.

The page you return to shows **Open the copy** and **Undo**. Undo puts the pieces back in the lot and archives the copy. The pieces you ticked in the bulk stay filed in the lot, so they count as found if you pull the set again.

## When it is refused

Nothing is written when the set is made of other sets (Make it a copy does not handle those yet) or when nothing is found yet. The page says why. On a read-only instance the list shows but the counters and Make it a copy are off.

## The API

`GET /api/v2/lots/{id}/pull-list/{set_id}` (tool `get_lot_pull_list`) reads the list; `POST .../found` saves a count (no event); `POST .../make-copy` (tool `make_copy_from_lot`) makes the copy as one event, undone through `POST /api/v2/events/{id}/undo`. The progress is kept in a setting row, not a table (ADR 0029).
