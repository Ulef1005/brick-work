---
audience: user
verified: 1.0
---

# Pick parts for several sets

*Since 0.5.0.*

Part Runner (was Part Picker) is the Workbench workflow described here.

Collect the missing parts of several sets in one pass through your drawers. Part Runner works from the missing counts that [Set Inspector](check-set-parts.md) records, so check the sets first.

## Pick the parts

1. Open **Workbench → Part Runner**. Under **Pick for which sets?** you see every [copy](../concepts/collection-model.md) with recorded missing parts and how many it is missing.
2. Keep **All incomplete sets**, or select **Choose sets** and tick the copies you want. The list shows 15 sets a page; ticks on other pages stay.
3. Select **Continue · N sets**.
4. Under **In what order do you pick?**, switch the sort keys on or off and drag them into order: **Category**, **Category group**, **Colour**, **Size**, **Set**, **Storage**. The line under the keys shows the order you get. Select **Start picking**.
5. Part Runner shows one part at a time. Above it, **Collecting for N sets** and **Part 7 / 52** say how far you are. A strip has one segment per part: violet for parts you found or marked missing, dark for the current one, dashed for the rest.
   The part's picture comes first. Beside its name, in the part's own colour, **Pick N** says how many to take. A line such as "for 10210-1 · copy 1 · 3 missing" says which copy needs them.
   On a wide screen the next three parts sit beside it under a tape with the code of their storage, such as "S-0002 Shelf A2 · 3 parts next." A phone shows one part at a time.
6. Take the parts you need and set the count with **−** and **+**; the middle button says **Found ×N**. Select it and choose where the parts go:
   - **Add to set** lowers the missing count of the copies that need it. The count is shared out over the copies in order; change how many go to each copy with **−** and **+**.
   - **Add to loose parts** adds them to your loose stock instead. Enter the **Found count**.
   - **Add to pick list only** records the find in **Recent saves** without changing any count.
   Select **Missing** instead when you cannot find the part now; its missing count stays as it is.
7. Select **Confirm**. Part Runner moves to the next part.
8. Use **Skip for later** for a part you cannot find now; its missing count stays as it is. **Back** returns to the previous part. A link with `?part=7` opens the run on its 7th part.
9. Select **Stop** when you are done.

Keyboard: **F** or **Enter** opens the destination form for the count shown on **Found ×N**, and **1** to **9** set that count. While the form is open, **1**, **2**, **3** choose the destination.
**M** leaves the part missing, **S** skips, **Z** undoes, and **←** and **→** move between parts.

Every save appears under **Recent saves**, each with its own **Undo**.

## The pick order

- Parts are grouped by part and colour, so a part that three sets need appears once, with the total to pick.
- The keys sort in the order you set. **Storage** sorts by the named storage that holds usable loose stock of that part. **Category** uses the part category from your catalogue.
- A key with nothing to sort by is switched off and says why, with one of these messages:
    - "No category is recorded for these parts"
    - "No usable loose parts have a recorded location"
    - "No part sizes are recorded"
- Parts with no value for a key come after the ones that have one.
- On a tie, a part that finishes more checked copies comes first.

Part Runner lists every missing part of the chosen copies, whether or not you have it in loose stock. Use the **Storage** key to see which drawer to try. Under **Details**, the filters can narrow the list by colour or set, and the sort can switch to **Name**, **Number**, **Missing count** or **Colour**.

## Print the list or save it as CSV

*Since 0.5.0.*

1. While picking, select **Print list**.
2. The print view lists the parts in your pick order with a rank number, the sets that need each part and their storage. **Hide pictures** gives a shorter printout.
3. Select **Print**, or **Download CSV** for a file with rank, item type, item number, name, colour, colour id, quantity, sets and storage.

**Back** returns you to Part Runner.

## What next

- [Find sets your loose stock can finish](match-stock-to-sets.md) to move loose parts you already have into the copies that need them.
- [Check a set's parts](check-set-parts.md) to record gaps for more sets.

**Category group** is off by default. Switch it on to pick in the fixed category-group order, with **Other** last. Like **Category**, it is unavailable when none of the parts has a recorded category. It works independently of **Group parts by**.
