---
audience: user
verified: 1.0
---

# Check a set's parts

*Since 0.5.0.*

Use Set Inspector (was Check Set Parts) to go through one [copy](../concepts/collection-model.md) of a set part by part and record what is missing. Do this when you sort out a used or half-built set. The copy needs its part list in your catalogue first.

## Run the check

1. Open **Workbench → Set Inspector**. The list shows copies **In progress**, **Not checked** and **Checked**; it opens on **Not checked**. Change that under the filter, or sort by **Largest first**, **Number** or **Name**.
2. Choose a copy.
3. Under **Order**, pick **Inventory order**, **By colour**, **Largest first** or **Category group**. Then select **Start**.
4. For each part line, set the number you found with **−** and **+**, then select **Found ×N** (N is your count) to save it. The difference is recorded as missing. The name of the part is filled with the part's own colour, so you can match it against the pile.
   - **Missing** records the whole line as missing.
   - **Skip for later** leaves the line unanswered.
   - **Back** and **Undo** step back or reverse the last answer.
5. Minifigures come after the required parts, as a **Figure review**. Count the whole figure like a part.
6. If the set has spare parts, you are asked **Include spare parts?** Select **No, skip them** or **Yes, check them**. Spares are never counted as missing.
7. **Checked so far** shows your last four answers, the newest first. A line with parts missing is a larger card with its own **−** and **+**, so you can change the missing count at once. Select **−** to find one, and **+** to mark one more missing. At zero the line moves to **Found**. Select **Show all N checked lines** to see every answer. On a phone the list sits below the part.
8. At the end of the check the **Missing so far** list shows every gap, the newest on top. If you find a piece later in the pile, select **Found 1** next to it and the count drops by one. The entry stays where it is until you have found them all, then it leaves the list.
9. When the last part is answered, the end of the check has three steps, shown at the top: **1 Skipped**, **2 Missing**, **3 Save**.
   - **Skipped** lists the parts you skipped, each with **Check**. Select **Check the N skipped parts** to walk them in the usual part view, or **Leave them unchecked** to go on. The **Missing so far** list is shown dimmed below as the next step. With nothing skipped, the screen starts at step 2.
   - **Missing** is the **Missing so far** list. Select **Done · N still missing** to continue.
   - **Save** is **Finish**. Tick **Set is checked** if you have also inspected the build and the figures, then select **Done**.

The top of the page names the copy and shows how far you are. The large figure reads **142 of 375 parts**: the pieces of the lines you have answered, out of all pieces. Beside it are the lines found, the lines missing and the lines **to check**. A skipped line counts as to check. On a wide screen a strip of cells shows one cell per part line. A found line is violet, a line with missing parts is hatched, and a line still to check is dashed. A long list shares one cell between several lines, so the strip never grows with the number of parts. **Saved 14:20 · resume any time** shows when your last answer was saved.

Every answer saves as you go. You can close the page and come back later: the copy shows under **In progress** and its start screen offers **Resume check**. **Start over** starts a new pass.

Checks that were in progress before the move to the 4.0 data model (Brick Work 4.0) are not carried over. The copy shows as **Not checked** and you start again. The counts you recorded stay. Switching a copy to another part list keeps a check in progress and its answers for every line the two lists share.

Keyboard: **F** found all, **M** missing, **1 to 9** count, **S** skip, **Z** undo, **←** back, **→** or **Enter** next.

## Check only the missing parts

When a copy already has missing parts, **Check missing only** starts a run over just those parts. It is the third button beside **Check parts** and **Edit parts**, under the copy's bar on the set's page, shown only when parts are missing. Use it after a visit to the pile, or when you have found parts since the last check. The heading reads **Missing part line 1 of N** with a **Missing only** tag. The counts end with **missing parts only**. Each part shows **Missing since the last check: X of Y**. Buttons, keys and the end of the check are as above. The other parts keep their answers from the earlier check. Checking the skipped parts inside a missing-only run keeps it a missing-only run. Reloading the page resumes whatever check is running. Starting a missing-only run replaces a check that is in progress; **Undo** brings the earlier check back.

## The copy on the set's page

Under the set's name, the selected copy has its own head. It starts with a line such as **10 parts missing, 4 in loose stock** and a bar of what is present; the hatched end is what is missing. Under the bar are **365/375 · 10 missing** and **4 can be taken · 6 to order**. The last line counts the different parts and how many are checked. **Check parts**, **Edit parts** and, when parts are missing, **Check missing only** sit beside it. On a phone they come under it.

On the **Parts** tab the missing parts come first, as cards under **Missing parts · N lines**. Each card is drawn in the part's own colour. It says what the set needs and how many are missing. A part you hold in loose stock shows **n in loose stock** and **Take n**. **Found 1** and **Found all** sit beside it. The first two cards show; **+ N more missing lines** opens the rest, and **Show fewer** closes them again. While you search or filter, every matching missing part shows. The sections below list the parts that are not missing, and each section header counts only what it lists.

## Mark missing parts on the set's page

You can record missing parts on a copy's page without a check. Under the copy's bar, next to **Check parts**, select **Edit parts**. The bar then gives way to **Editing parts**, and the buttons are hidden. Each missing part goes back into its section of the part list, so you tick every part in one place.

1. Tick the box on each part that is missing. A part you need more than once shows a stepper: set how many are missing with **−** and **+**. It starts at 1 and stops at the number the set needs.
2. Parts that are already missing open ticked, with their count. Untick one to mark it found.
3. Each section header shows how many parts you ticked, and the bar at the bottom shows the total.
4. Select **Save missing**. Nothing is saved before that. **Cancel** drops all your ticks.

One save is one step: it shows a receipt line with **Undo**, and **Undo** takes back every part of that save. A ticked part saved as missing also counts as checked, so it leaves the **to check** count of its section. Parts you did not tick stay as they were. If the save fails, your ticks stay and the button reads **Retry**.

**Set is checked** is a switch under the copy's bar, in both modes. It never turns on by itself, and saving missing parts does not move it. It saves at once, with its own receipt and **Undo**. If you are editing, your unsaved ticks come back after the page reloads, and **Cancel** does not undo the switch. A copy with missing parts stays Incomplete even when the switch is on.

On an instance where editing is switched off, the part list has no buttons, ticks or switch, and **Check parts** is hidden too.

## Mark a found part on the set's page

Every missing part row on a copy's page has **Found 1**. A row with more than one part missing also has **Found all**. **Found 1** lowers that part's missing count by one, the same as **Found 1** in Set Inspector. **Found all** sets it to zero. The loose stock is not touched. The receipt line with **Undo** sits above the list. A row that has **Take N** (loose stock covers the gap) shows **Take** next to them. See also [Find sets your loose stock can finish](match-stock-to-sets.md).

## What the check changes

- Each answer sets that line's missing count on the copy. Those counts are what Part Runner, Matchmaker and the exports work from.
- In Set Inspector, **Set is checked** can only be ticked once no part or figure is left skipped or unanswered. The switch on the set's page has no such rule.
- With **Set is checked** ticked and nothing missing, the copy's completeness becomes Complete. With gaps it stays Incomplete. If you set the copy's completeness by hand, the check leaves it as it is.

## Check a minifigure's own parts

*Since 0.5.0.*

On a figure's step, **Check figure parts** opens a check of that figure's own parts, if the catalogue lists them. Parts missing from a figure count on the figure, not on the set, so they do not change the set's missing count or completeness. On the set's page, the figure's line names the missing parts in short, such as **Torso · Legs**. Point at the line to see the full catalogue names. The check itself lists the full names. **Done** takes you back to the set's figures.

## What next

- [Export or print the missing parts](export-missing-parts.md) to buy them or hand the list on.
- [Pick parts for several sets](pick-parts.md) to work through the gaps at your drawers.
- [Find sets your loose stock can finish](match-stock-to-sets.md) to fill gaps from parts you already own.

**Category group** follows the fixed category-group order, with **Other** last, and largest parts first within each group. It is always available, independently of **Group parts by**. Parts without a recorded category go in **Other**.

Your ticks stay when you switch to Minifigures or Instructions & Box and back to Parts.
The edit controls show on Parts; the receipt and Undo stay visible on every tab.
If saving fails, including an unreadable server response, your ticks stay ready for Retry.
While Found 1 or Found all saves a row, both buttons wait for the result.

The copy's bar, its three buttons and the **Set is checked** switch sit above the tabs, so they show on every tab.
Found and Take on a minifigure keep your unsaved part ticks across the reload, just like the switch.
If Found receives an unreadable response, it shows **The server did not answer · try again**.
