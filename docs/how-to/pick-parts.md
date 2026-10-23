# Pick parts for several sets

*Since 0.5.0.*

Collect the missing parts of several sets in one pass through your drawers. Part Picker works from the missing counts that [Check Set Parts](check-set-parts.md) records, so check the sets first.

## Pick the parts

1. Open **Workbench → Part Picker**. Under **Pick for which sets?** you see every [copy](../concepts/collection-model.md) with recorded missing parts and how many it is missing.
2. Keep **All incomplete sets**, or select **Choose sets** and tick the copies you want. The list shows 15 sets a page; ticks on other pages stay.
3. Select **Continue · N sets**.
4. Under **In what order do you pick?**, switch the sort keys on or off and drag them into order: **Category**, **Colour**, **Size**, **Set**, **Storage**. The line under the keys shows the order you get. Select **Start picking**.
5. The picker shows one part at a time: its picture, colour and number, **Pick N**, and which copies need how many.
6. When you have the part in hand, select **Found it** and choose where it goes:
   - **Add to set** lowers the missing count of the copies that need it. Set how many go to each copy with **−** and **+**.
   - **Add to loose parts** adds them to your loose stock instead. Enter the **Found count**.
   - **Add to pick list only** records the find in **Recent saves** without changing any count.
7. Select **Confirm**. The picker moves to the next part.
8. Use **Skip for later** for a part you cannot find now; its missing count stays as it is. **Back** returns to the previous part.
9. Select **Stop** when you are done.

Keyboard: **F** or **Enter** opens Found it, **1**, **2**, **3** choose the destination, **M** leaves the part missing, **S** skips, **Z** undoes, **←** and **→** move between parts.

Every save appears under **Recent saves**, each with its own **Undo**.

## The pick order

- Parts are grouped by part and colour, so a part that three sets need appears once, with the total to pick.
- The keys sort in the order you set. **Storage** sorts by the named storage that holds usable loose stock of that part. **Category** uses the part category from your catalogue.
- A key with nothing to sort by is switched off and says why: "No category is recorded for these parts", "No usable loose parts have a recorded location" or "No part sizes are recorded".
- Parts with no value for a key come after the ones that have one.
- On a tie, a part that finishes more checked copies comes first.

Part Picker lists every missing part of the chosen copies, whether or not you have it in loose stock. Use the **Storage** key to see which drawer to try. Under **Details**, the filters can narrow the list by colour or set, and the sort can switch to **Name**, **Number**, **Missing count** or **Colour**.

## Print the list or save it as CSV

*Since 0.5.0.*

1. While picking, select **Print list**.
2. The print view lists the parts in your pick order with a rank number, the sets that need each part and their storage. **Hide pictures** gives a shorter printout.
3. Select **Print**, or **Download CSV** for a file with rank, item type, item number, name, colour, colour id, quantity, sets and storage.

**Back** returns you to the picker.

## What next

- [Find sets your loose stock can finish](match-stock-to-sets.md) to move loose parts you already have into the copies that need them.
- [Check a set's parts](check-set-parts.md) to record gaps for more sets.
