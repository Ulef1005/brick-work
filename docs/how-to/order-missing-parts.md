---
audience: user
verified: 1.0
---

# Order the parts all your sets are missing

*Since 1.1.0.*

Do this when several of your sets have gaps and you want one list for the parts of the sets you choose. Each line is combined across those sets and shows which sets it comes from. You also get a BrickLink wanted list and a Pick a Brick file to buy the parts with.

Open **Planning → Complete sets** and press **Order missing parts**, or open `/planning/order-missing-parts`. The page only reads: it changes nothing in your collection, and it works on a read-only instance too. [Check a set's parts](check-set-parts.md) records the gaps it works from.

## Choose the sets

The left side lists every copy that has a recorded gap, one row per copy ("Set 2" is your second copy of a set). A row shows the set number and name, its theme and year, and the gap: **12 parts missing**, or **9 parts missing · 1 figure missing** when a minifigure is missing. A copy whose Set Inspector check is not finished says **Check in progress**; its gaps may still change. Under the gap, **gain +€18.40** is the net gain the [repair ranking](plan-repairs.md) works out for that copy.

Tick the copies you want. **Select all** ticks every set on the screen that is not left out, **Clear** unticks everything. The subtitle counts: **7 sets have gaps · 6 in the list**.

Narrow the list with:

- **Search sets:** a number, a name or "Set 2."
- **Theme.**
- **Leave out sets to sell or part out** (on by default). A copy with a status or tag whose name says so, such as *To sell*, *For sale*, *Part out*, *Parted out* or *Donor*, is left out. It stays in the list, greyed and unticked, with its tag and **left out**. Tick it yourself if you want its parts anyway. Brick Work has no built-in mark for this; name the tag whatever you like from those words.
- **Only sets that gain value** (off by default). A copy the repair ranking gives no gain is left out. A copy whose price is missing or too old has no gain figure and counts as no gain; the page says how many.
- **Sort:** most missing (the default), fewest missing, most gain, number or name.

Only the sets you can see count: a set hidden by the search or the theme is not in the list. Every choice is in the page's address, so you can bookmark or share the view. Without JavaScript, press **Update list** after changing a filter or a tick.

## Read the order list

The right side (on a phone, the second step, **Review list**) is what you would buy for the ticked sets only. Its heading counts them exactly: **14 lines · 42 pieces from 6 sets**, where a figure counts as one piece each.

Each line is a part, colour and condition, combined over the ticked sets, with the quantity still to buy. It is worked out as in [Decide which set to repair first](plan-repairs.md#export-the-repair-list). With **Use loose stock** on in the repair settings, loose parts are taken off first, from the sets in set-number order. Under the name, a chip per set shows where the quantity comes from, for example `6080-1 ×2`, so you can check a number back to its set. The first four lines show; **Show all** opens the rest.

A line Brick Work cannot name for BrickLink is left out of the file. That happens when the item has no BrickLink number or its colour has none. The line is listed in the yellow box with a link to the item, so you can link it and come back.

## Choose where each line is bought

Every line has two choice chips under it:

- **BrickLink**, with its cached price and the age of the price (or **no sales**)
- **Pick a Brick**, with the element id Brick Work has stored for that part in that colour

The chip with the clay outline is where the line goes; tap the other one to move the line. A line with no stored element id has a dashed **Pick a Brick** chip that says **no element id**. It can only go to BrickLink, and the yellow note under the list names those lines.

Lines start on BrickLink. Turn on **Prefer Pick a Brick where a line has an element id** to start every line that has one on Pick a Brick instead. A line you moved by hand stays where you put it. Brick Work does not ask LEGO.com for prices or availability, so it cannot pick the cheaper source for you: the choice is yours.

The tabs **All**, **BrickLink** and **Pick a Brick** show each source's lines with the number of lines. Under the tabs:

- **BrickLink:** the estimated total of the lines that have a cached price, their lines and pieces, and how many have **no sales** (those are not in the total).
- **Pick a Brick:** its lines and pieces and **no price**. Pick a Brick has no price here.
- **Shipping, estimate:** the shipping from the repair settings, for the BrickLink order only, and the **Estimated total** of parts and shipping. Nothing is added for Pick a Brick.

If a part and colour has several element ids in the catalogue, Brick Work uses the lowest one.

## Download the two files

- **Download BrickLink XML:** `missing-parts.xml` holds the lines on BrickLink. When no line is on Pick a Brick it is exactly what **Export N · BrickLink XML** on Complete sets downloads for the same copies. Upload it to BrickLink as a wanted list.
- **Download Pick a Brick CSV:** `pick-a-brick.csv` has a header `elementId,quantity` and one row per line on Pick a Brick. Upload it on LEGO's Pick a Brick page with its upload button. The feature is rolling out by country, and LEGO reports a limit of 400 part types per upload; Brick Work does not split the file.

A button is greyed, with the reason under it, when no line is on that source.

## What next

- [Decide which set to repair first](plan-repairs.md) ranks the repairs by what they gain.
- [Pick parts for several sets](pick-parts.md) fills gaps from your drawers before you buy.
