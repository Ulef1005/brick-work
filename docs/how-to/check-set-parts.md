# Check a set's parts

*Since 0.5.0.*

Go through one [copy](../concepts/collection-model.md) of a set part by part and record what is missing. Do this when you sort out a used or half-built set. The copy needs its part list in your catalogue first.

## Run the check

1. Open **Workbench → Check Set Parts**. The list shows copies **In progress**, **Not checked** and **Checked**; it opens on **Not checked**. Change that under the filter, or sort by **Largest first**, **Number** or **Name**.
2. Choose a copy.
3. Under **Order**, pick **Inventory order**, **By colour** or **Largest first**. Then select **Start**.
4. For each part, set the number you found with **−** and **+**, then select **Found N** (N is your count) to save it. The difference is recorded as missing.
   - **Missing** records the whole line as missing.
   - **Skip for later** leaves the line unanswered.
   - **Back** and **Undo** step back or reverse the last answer.
5. Minifigures come after the required parts, as a **Figure review**. Count the whole figure like a part.
6. If the set has spare parts, you are asked **Include spare parts?** Select **No, skip them** or **Yes, check them**. Spares are never counted as missing.
7. The **Missing so far** list shows every gap. If you find a piece later in the pile, select **Found 1** next to it and the count drops by one.
8. Select **Done · N still missing** to reach **Finish**. Tick **Set is checked** if you have also inspected the build and the figures, then select **Done**.

Every answer saves as you go. You can close the page and come back later: the copy shows under **In progress** and its start screen offers **Resume check**. **Start over** starts a new pass.

Checks that were in progress before the move to the 4.0 data model (Brick Work 4.0) are not carried over: the copy shows as **Not checked** and you start again. The counts you recorded stay. Switching a copy to another part list keeps a check in progress and its answers for every line the two lists share.

Keyboard: **F** found all, **M** missing, **1 to 9** count, **S** skip, **Z** undo, **←** back, **→** or **Enter** next.

## What the check changes

- Each answer sets that line's missing count on the copy. Those counts are what Part Picker, Matcher and the exports work from.
- **Set is checked** can only be ticked once no part or figure is left skipped or unanswered.
- With **Set is checked** ticked and nothing missing, the copy's completeness becomes Complete. With gaps it stays Incomplete. If you set the copy's completeness by hand, the check leaves it as it is.

## Check a minifigure's own parts

*Since 0.5.0.*

On a figure's step, **Check figure parts** opens a check of that figure's own parts, if the catalogue lists them. Parts missing from a figure count on the figure, not on the set, so they do not change the set's missing count or completeness. **Done** takes you back to the set's figures.

## Export the gaps

*Since 0.5.0.*

1. Open **Planning → Complete sets**. It lists your copies that have recorded gaps.
2. Tick the copies you want.
3. Choose one:
   - **Export N · BrickLink XML** downloads `missing-parts.xml` for a BrickLink Wanted List: every missing or damaged part and every missing figure of the ticked copies, by BrickLink number and colour, with the condition of the copy. Something Brick Work cannot name for BrickLink, because it has no BrickLink number or its colour has none, is left out of the file and named in the message; the rest still exports. With *Use loose stock* on in the repair settings, the quantities are what you still have to buy ([Decide which set to repair first](plan-repairs.md)).
   - **Print missing parts of N** opens a printable list. **Download CSV** on that page saves the same list as a CSV file (item type, number, name, colour, condition, quantity and a note for items not matched yet). Items not matched yet stay on this list, marked.

The REST API offers the same missing-parts lists as XML, CSV and JSON.

## What next

- [Pick parts for several sets](pick-parts.md) to work through the gaps at your drawers.
- [Find sets your loose stock can finish](match-stock-to-sets.md) to fill gaps from parts you already own.
