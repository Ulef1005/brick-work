# Decide which set to repair first

*Since 0.5.0.*

Do this when several of your sets have gaps (missing or damaged parts, missing figures) and you want to know which repair is worth buying first, and to put the parts on a BrickLink wanted list.

**Planning → Complete sets** lists your copies that have a recorded gap and ranks them by the value a repair gains for each unit of money spent. It works from prices Brick Work already holds: nothing is fetched when you open the page. [Check a set's parts](check-set-parts.md) records the gaps, and [Pictures, prices and where they come from](pictures-and-prices.md) fills in the prices.

## Read the ranking

The page title names the best repair, for example **Repair 10497-1 first: 2.10 gained per 1 spent**. Each row shows the set, the copy ("Set 2" is your second copy of that set) and, under **Details**, the numbers:

- **Complete value:** what the set sells for complete, from BrickLink's sold average for the copy's condition (a copy with no condition counts as used), in your BrickLink currency and region. A price older than 7 days does not count.
- **As is:** what the copy is worth now. That is the **current value** you entered on the copy, if it is in your BrickLink currency; otherwise the complete value less the **incomplete discount** (30 % unless you changed it).
- **Repair cost:** the missing and damaged parts and figures at their cached prices, plus shipping, fees, and the top-up to the minimum order.
- **Gained:** complete value less as is. **Net gain:** gained less repair cost. The ratio is gained for each unit of repair cost.

Rows fall into four groups:

| Group | Meaning |
|---|---|
| Ranked | The repair gains more than it costs. Highest ratio first. |
| Free repair | There is a gain and the repair costs nothing. |
| Outside break-even | The repair costs more than it gains (or the copy is worth more as is). |
| Needs evidence | A price is missing or too old. **Details** names each one, for example *no cached price · 3001* or *stale quote · complete value*, so you know which price to refresh. |

A figure that has no BrickLink number cannot be priced and is named as *unmapped figure*.

## Pin a copy

Press **Pin** on a row to list that copy first whatever its ratio; the title then ends **· pins listed first**. **Unpin** puts it back in order. **Undo** appears next to the message at the top and takes the pin back.

## Change the repair settings

Open **Repair settings** above the list: **Shipping**, **Fees**, **Minimum order** and the **Incomplete discount**, and **Use loose stock**. With *Use loose stock* on, parts you hold loose count against a gap before anything is bought, so a gap your loose parts cover costs nothing but the fixed charges. Parts already promised to an incoming order are not counted. Press **Save settings**; **Undo** puts the old values back unless you saved again since.

The BrickLink region and currency that prices must be in are set in Tools & Admin → Settings, not on this page.

## Know what parting out is worth

When 9 in 10 of a copy's present lines have a used price, **Details** adds **Parted out ≈ …**: the parts and figures you have, one by one, at their used prices. The copy's own page shows it too, beside the complete and as-is values, and says when parting out is worth clearly more. With fewer prices the page says **Not enough prices yet**, and **Fetch part prices** queues the missing ones.

## Export the repair list

1. Tick the copies. The button counts them.
2. Press **Export N · BrickLink XML**. A file `missing-parts.xml` downloads, for a BrickLink wanted list.

Each line is an item, colour and condition with the quantity still to buy: with *Use loose stock* on, the quantity is the gap less your loose parts. A line Brick Work cannot name for BrickLink, because the item has no BrickLink number or its colour has none, is left out of the file and named in the message ("Exported · 1 left out: …"). The rest exports. Exporting works on a read-only instance too.

**Print missing parts of N** opens a printable list of the same copies; see [Check a set's parts](check-set-parts.md#export-the-gaps).

## What next

- [Pick parts for several sets](pick-parts.md) to fill the gaps from your drawers before buying.
- [Find sets your loose stock can finish](match-stock-to-sets.md).
- [Undo a change](undo-a-change.md).
