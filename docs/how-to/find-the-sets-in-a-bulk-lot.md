# Find the sets in a bulk lot

*Since 1.0.2.*

A lot is a pile of loose parts bought together. **Set detection** on the lot page ranks the catalogue's sets by how strongly the parts in the lot point to them, so you can see which sets the pile was made from.

1. Open **Collection → Parts**, group by lot, and open the lot. Below **Parts in this lot** is **Which sets are in this lot?**
2. Read the candidates, best first. The **score** is the evidence for a set compared with the best candidate (the best scores 100%). It is not a probability.
3. Under each score the reasons say why: how many of the set's distinctive parts are in the lot (a distinctive part is held by 25 sets or fewer), how many printed parts only this set holds, and how many of the set's part lines the lot has.
4. Select **Details** to see **Found in the lot** (the distinctive parts the lot has, with pictures), **Not found yet**, and **Swaps, not counted in the score** (the lot has the part in another colour, or as an alternate mould). Select **Open set** to see the set in the catalogue. The best candidate is open already.

## Narrow the list

- **Min score** hides the faintest candidates (30% to start with).
- **Theme**, **Years** and **Size** (the set's part count) keep only matching sets. A theme includes the themes below it.
- **Ignore common parts** (on by default) leaves out parts that more than 300 sets hold, because they say little. The line above the list says how many of the lot's parts were too common to count. The limit is the setting `candidate_sets_common_max` (see [Settings](../reference/settings.md)).

Select **Apply**; the filters are in the page's address, so you can bookmark or share a view. The page works without scripts.

A lot with no parts says so, and so does a filter that matches no set; **Clear the filters** brings the list back. The page only reads: nothing is changed. The same answer is in the API (`GET /api/v2/lots/{id}/candidate-sets`) and the assistant tool `get_lot_candidate_sets`.

Parts you flagged as having a sticker count for more: see [Mark a sticker](mark-a-sticker.md). How the score is worked out is in [Set scoring](../reference/set-scoring.md).

To get a detected set out of the pile, open its **Pull list**: see [Pull a set out of a lot](pull-a-set-out-of-a-lot.md).
