# Find sets to build from your loose stock

*Unreleased (#9).* Build Scout is a Workbench workflow.

Build Scout asks the question [Matchmaker](match-stock-to-sets.md) does not: for **every set in the catalogue**, how much of it do your loose parts already make? Matchmaker fills the gaps of copies you own. Build Scout looks at sets you may not own at all, and shows the ones you could build, or nearly build, from parts that sit in your drawers.

Do this once you have recorded a good amount of [loose stock](../concepts/collection-model.md): parts and minifigures that are not part of a copy.

## Read the list

1. Open **Workbench → Build Scout**.
2. Each row is a set, best first. The bar and the percentage say how much of the set's parts your stock covers (**85%**, **398 of 430 parts**). On the right: the parts still missing (**−32 parts**), how many of its minifigures are missing (**2 of 3 figures missing**) and an approximate cost to complete (**≈ €31.20 · 3 lines unpriced**).
3. Sets are sorted by the percentage available, then by the fewest missing parts.
4. On a wide screen the set you select shows its details beside the list; on a phone, open the set. The details give **Parts you hold**, the biggest missing lines with their colours (**−6**), **Show all** for the rest, and the figures you hold of those the set needs.

**What counts as a part.** A set's parts are its own part lines, with spare parts left out and the parts of any sets inside it counted. The parts of its minifigures are not counted here: a minifigure is counted on its own, as one whole figure. A loose whole minifigure in your stock counts as one of the set's figures; loose parts that would make up a figure do not. So **398 of 430 parts** is parts only, and **1 of 3 figures** is figures only.

**Swaps are never in the percentage.** The same part in another colour, or an alternate mould of it, would not be the set's own part. When your stock holds such a part, the set's details say **Swaps, not in the %** and name an example (**Dark Bluish Gray for Black**).

**Cost.** The cost adds up the missing parts and figures that have a price, in the currency most of them are priced in. Lines with no price, or a price in another currency, are left out and counted: **3 lines unpriced**. When nothing has a price the row says **not priced**. Prices come from the current prices Brick Work holds ([Pictures, prices and where they come from](pictures-and-prices.md)).

## Choose the stock and narrow the list

- **Parts from** chooses which loose stock is counted: **Loose stock** (stock that is in no lot and no storage), any **lots** and any **storages** (with the storages inside them). Choose none to count all your loose stock. **Count damaged parts too** adds stock marked damaged; it is off by default, as in Matchmaker. A loose minifigure with missing or damaged parts is never counted.
- **Min** is the least percentage of a set's parts that must be available. It starts at 60.
- **Max missing** is the most missing parts a set may have.
- **Theme** takes a theme name or number and includes its sub-themes.
- **Years** and **Size** (the number of parts, spares left out) take a range; leave an end empty for no limit.

The line under the filters says how many sets match, out of how many are in the catalogue, and how many loose pieces were counted. The list shows 25 sets a page. Saved filter sets are not part of this first version.

## Act on a set

- **Build it · make a copy** makes a copy of the set and moves the matching parts and whole figures out of the stock you chose into it. What the stock does not cover is recorded as missing on the copy, so the copy shows up in Matchmaker, Part Runner and Set Inspector as any incomplete copy. The message says how many pieces moved, and **Undo** puts the stock back and archives the copy. Undo is refused once the copy or the stock has been changed since. The copy is made from the catalogue's latest Rebrickable part list and is marked used. Build it is not offered for a set that is made of other sets, nor when the chosen stock holds nothing the set needs.
- **Add to wishlist** puts the set on the default wishlist with the note **Buildable from stock**, so you can tell it apart later. A set already on a wishlist is not added again.
- **Missing parts · XML** downloads the missing parts and figures as a BrickLink wanted list, the same file the copies' export makes ([Decide which set to repair first](plan-repairs.md)).

On a read-only instance there is no **Build it** and no **Add to wishlist**; the list and the XML stay.

## From the API and the assistant

`GET /api/v2/planning/build-scout` takes the same stock and filters (`lot` and `storage`, repeated; `loose`; `damaged`; `min_percent`; `max_missing`; `theme`; `year_from`; `year_to`; `size_from`; `size_to`), pages with `limit` and `offset`, and with `detail` also lists each set's biggest missing lines, missing figures, cost and swaps. The assistant tool is `get_planning_build_scout`. `POST /api/v2/items/{id}/build` is **Build it**, with an `Idempotency-Key`; Undo is `POST /api/v2/events/{id}/undo`. See [Set scoring](../reference/set-scoring.md#build-scout) for the definitions.

## What next

- [Pick parts for several sets](pick-parts.md) for the missing parts of the sets you start.
- [Find sets your loose stock can finish](match-stock-to-sets.md) for copies you own.
- [Undo a change](undo-a-change.md).
