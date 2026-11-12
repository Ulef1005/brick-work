# Order the parts all your sets are missing

*Since 1.1.0.*

Do this when several of your sets have gaps and you want one BrickLink wanted list for the parts of the sets you choose, with each line combined across them and showing which sets it comes from.

Open **Planning → Complete sets** and press **Order missing parts**, or open `/planning/order-missing-parts`. The page only reads: it changes nothing in your collection, and it works on a read-only instance too. [Check a set's parts](check-set-parts.md) records the gaps it works from.

## Choose the sets

The left side lists every copy that has a recorded gap, one row per copy ("Set 2" is your second copy of a set). A row shows the set number and name, its theme and year, and the gap: **−12 parts**, or **−9 parts · −1 figure** when a minifigure is missing. A copy whose Set Inspector check is not finished says **Check in progress**; its gaps may still change. Under the gap, **gain +€18.40** is the net gain the [repair ranking](plan-repairs.md) works out for that copy.

Tick the copies you want. **Select all** ticks every set on the screen that is not left out, **Clear** unticks everything. The subtitle counts: **7 sets have gaps · 6 in the list**.

Narrow the list with:

- **Search sets:** a number, a name or "Set 2".
- **Theme.**
- **Leave out sets to sell or part out** (on by default). A copy with a status or tag whose name says so, such as *To sell*, *For sale*, *Part out*, *Parted out* or *Donor*, is left out: it stays in the list, greyed and unticked, with its tag and **left out**. Tick it yourself if you want its parts anyway. Brick Work has no built-in mark for this; name the tag whatever you like from those words.
- **Only sets that gain value** (off by default). A copy the repair ranking gives no gain is left out. A copy whose price is missing or too old has no gain figure and counts as no gain; the page says how many.
- **Sort:** most missing (the default), fewest missing, most gain, number or name.

Only the sets you can see count: a set hidden by the search or the theme is not in the list. Every choice is in the page's address, so you can bookmark or share the view. Without JavaScript, press **Update list** after changing a filter or a tick.

## Read the order list

The right side (on a phone, the second step, **Review list**) is what you would buy for the ticked sets only. Its heading counts them exactly: **14 lines · 42 pieces from 6 sets**, where a figure counts as one piece each.

Each line is a part, colour and condition, combined over the ticked sets, with the quantity still to buy. It is worked out as in [Decide which set to repair first](plan-repairs.md#export-the-repair-list): with **Use loose stock** on in the repair settings, loose parts are taken off first, from the sets in set-number order. Under the name, a chip per set shows where the quantity comes from, for example `6080-1 ×2`, so you can check a number back to its set. The first four lines show; **Show all** opens the rest.

A line Brick Work cannot name for BrickLink, because the item has no BrickLink number or its colour has none, is left out of the file and listed in the yellow box with a link to the item, so you can link it and come back.

## Download the file

Press **Export 6 sets · BrickLink XML**. The file `missing-parts.xml` is exactly what **Export N · BrickLink XML** on Complete sets downloads for the same copies. Upload it to BrickLink as a wanted list.

## What next

- [Decide which set to repair first](plan-repairs.md) ranks the repairs by what they gain.
- [Pick parts for several sets](pick-parts.md) fills gaps from your drawers before you buy.
