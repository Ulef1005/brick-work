# Check a set's parts

*Since 0.5.0.*

Use Set Inspector (was Check Set Parts) to go through one [copy](../concepts/collection-model.md) of a set part by part and record what is missing. Do this when you sort out a used or half-built set. The copy needs its part list in your catalogue first.

## Run the check

1. Open **Workbench → Set Inspector**. The list shows copies **In progress**, **Not checked** and **Checked**; it opens on **Not checked**. Change that under the filter, or sort by **Largest first**, **Number** or **Name**.
2. Choose a copy.
3. Under **Order**, pick **Inventory order**, **By colour**, **Largest first** or **Category group**. Then select **Start**.
4. For each part, set the number you found with **−** and **+**, then select **Found N** (N is your count) to save it. The difference is recorded as missing.
   - **Missing** records the whole line as missing.
   - **Skip for later** leaves the line unanswered.
   - **Back** and **Undo** step back or reverse the last answer.
5. Minifigures come after the required parts, as a **Figure review**. Count the whole figure like a part.
6. If the set has spare parts, you are asked **Include spare parts?** Select **No, skip them** or **Yes, check them**. Spares are never counted as missing.
7. The **Missing so far** list shows every gap, the newest on top. If you find a piece later in the pile, select **Found 1** next to it and the count drops by one; the entry stays where it is in the list.
8. When the last part is answered, the end of the check has three steps, shown at the top: **1 Skipped**, **2 Missing**, **3 Save**.
   - **Skipped** lists the parts you skipped, each with **Check**. Select **Check the N skipped parts** to walk them in the usual part view, or **Leave them unchecked** to go on. The **Missing so far** list is shown dimmed below as the next step. With nothing skipped, the screen starts at step 2.
   - **Missing** is the **Missing so far** list. Select **Done · N still missing** to continue.
   - **Save** is **Finish**. Tick **Set is checked** if you have also inspected the build and the figures, then select **Done**.

Every answer saves as you go. You can close the page and come back later: the copy shows under **In progress** and its start screen offers **Resume check**. **Start over** starts a new pass.

Checks that were in progress before the move to the 4.0 data model (Brick Work 4.0) are not carried over: the copy shows as **Not checked** and you start again. The counts you recorded stay. Switching a copy to another part list keeps a check in progress and its answers for every line the two lists share.

Keyboard: **F** found all, **M** missing, **1 to 9** count, **S** skip, **Z** undo, **←** back, **→** or **Enter** next.

## Check only the missing parts

When a copy already has missing parts, **Check missing only** on the set's page (beside **Check parts**) starts a run over just those parts. Use it after a visit to the pile, or when you have found parts since the last check. The heading reads **Missing part 1 of N** with a **Missing only** tag, the progress line ends with **· missing parts only**, and each part shows **Missing since the last check: X of Y**. Buttons, keys and the end of the check are as above. The other parts keep their answers from the earlier check. Checking the skipped parts inside a missing-only run keeps it a missing-only run. Reloading the page resumes whatever check is running. Starting a missing-only run replaces a check that is in progress; **Undo** brings the earlier check back.

## Mark a found part on the set's page

Every missing part card on a copy's page has **Found 1**. It lowers that part's missing count by one, the same as **Found 1** in Set Inspector, and the loose stock is not touched. An **Undo** appears at the top of the page. On a card that has **Take N** (loose stock covers the gap) **Found 1** is a text link under **Take**, so **Take** stays the main action; otherwise it is an outline button. See also [Find sets your loose stock can finish](match-stock-to-sets.md).

## What the check changes

- Each answer sets that line's missing count on the copy. Those counts are what Part Runner, Matchmaker and the exports work from.
- **Set is checked** can only be ticked once no part or figure is left skipped or unanswered.
- With **Set is checked** ticked and nothing missing, the copy's completeness becomes Complete. With gaps it stays Incomplete. If you set the copy's completeness by hand, the check leaves it as it is.

## Check a minifigure's own parts

*Since 0.5.0.*

On a figure's step, **Check figure parts** opens a check of that figure's own parts, if the catalogue lists them. Parts missing from a figure count on the figure, not on the set, so they do not change the set's missing count or completeness. **Done** takes you back to the set's figures.

## What next

- [Export or print the missing parts](export-missing-parts.md) to buy them or hand the list on.
- [Pick parts for several sets](pick-parts.md) to work through the gaps at your drawers.
- [Find sets your loose stock can finish](match-stock-to-sets.md) to fill gaps from parts you already own.

**Category group** follows the fixed category-group order, with **Other** last, and largest parts first within each group. It is always available, independently of **Group parts by**. Parts without a recorded category go in **Other**.
