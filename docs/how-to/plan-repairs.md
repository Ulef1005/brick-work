---
audience: user
verified: 1.0
---

# Decide which set to repair first

*Since 0.5.0.*

Do this when several of your sets have gaps (missing or damaged parts, missing figures). Use it to find which repair is worth buying first, and to put the parts on a BrickLink wanted list.

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

When 9 in 10 present lines have a used price, the list shows **Parted out ≈ …** below the gap.
The copy's page compares this total with complete and as-is values when their currencies match.
It says when parting out is worth clearly more.
With fewer prices, the copy's page says **Not enough prices yet**.
**Fetch part prices** queues missing prices and updates the card here when finished.

## Export the repair list

1. Tick the copies. The button counts them.
2. Press **Export N · BrickLink XML**. A file `missing-parts.xml` downloads, for a BrickLink wanted list.

Each line is an item, colour and condition with the quantity still to buy: with *Use loose stock* on, the quantity is the gap less your loose parts. Brick Work cannot name some lines for BrickLink, because the item has no BrickLink number or its colour has none. Such a line is left out of the file and named in the message ("Exported · 1 left out: …"). The rest exports. Exporting works on a read-only instance too.

To order the parts of many sets at once, press **Order missing parts** instead. Each line is combined and shows which sets it comes from. See [Order the parts all your sets are missing](order-missing-parts.md).

**Print missing parts of N** opens a printable list of the same copies; see [Export or print the missing parts](export-missing-parts.md).

## What next

- [Pick parts for several sets](pick-parts.md) to fill the gaps from your drawers before buying.
- [Find sets your loose stock can finish](match-stock-to-sets.md).
- [Undo a change](undo-a-change.md).

## Compare minifigures

Open **Planning › Complete sets › Figures** to compare complete value, present parts and the cost to complete each figure.
Each place with missing or damaged parts has its own row, with loose figures first and set copies next.
Figures without enough fresh used prices wait under **Needs evidence**.

The comparison uses the repair settings and the same price coverage and meaningful gain rules as set part-out values.
Open a minifigure to see its **Complete or part out** card and the missing parts behind its cost.


Search by number or name, then use **Filters** for place, recommendation, theme or storage.
Remove a filter with its chip.
**Sort** offers gain from completing, cost to complete, part-out value, number and name.
The list shows 15 places per page.

**How this is decided** explains the shared recommendation rule.
Completing must beat parting out by 10% and at least €5.00; the reverse supports **Part out**.
Smaller differences say **Keep as is**.
In another currency, the minimum is five units of that currency.
The part-out total needs prices for at least 90% of the component lines.
One unpriced line in a four-part figure therefore hides the total and recommendation.

The card's **Copy** picker chooses the loose record or set copy to describe.
A figure link inside a set copy opens that place's comparison.
Missing-part lines show the colour first, the part number, and the fresh used quote with its date.
**Shipping and fees** applies the repair settings per figure.
A minimum order adjustment has its own line when needed.
Complete figures show only Complete and Parts; unidentified figures keep their Info note.

**Fetch prices** queues the missing quotes when a BrickLink key and enough daily budget are available.
The budget line explains why fetching is disabled.
After fetching, reload to see the comparison; **Retry** handles a failed request.

### Sort copies by part-out value

Choose **Part-out value** in Sort for the highest total first.
Copies without a total come last.
The part-out line sits below the gap and wraps on narrow screens.
If no copy has a total, the list keeps number order and points to **Fetch part prices** on a set page.
