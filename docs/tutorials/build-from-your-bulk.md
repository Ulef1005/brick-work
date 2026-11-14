---
audience: user
verified: 1.0
---

# Build from your bulk

You have sets that lack a few parts and a pile of loose parts that might fill the gaps. In this tutorial you give the loose parts a home and pick the missing parts of several sets in one pass through your drawers. Then you let Brick Work show which sets your loose stock now finishes.

It takes about 20 minutes. You need a Brick Work install with some copies that have [recorded missing parts](../how-to/check-set-parts.md) and some loose parts in stock. Every picture comes from an invented collection, so your own numbers and names will differ.

## 1. Give your loose parts a drawer

1. Open **Workbench → Storage**. The list shows every storage you have, with its sets, figures and part lots. Anything with no place sits under **Not stored**.
2. Press **Add storage**.
3. Enter a **Name**, for example *Drawer 14*. Choose **Drawer** under **Type**. If the drawer is in a cabinet or a box, choose that under **Inside**.
4. Press **Add storage**. The new drawer appears in the list.
5. Open **Collection → Parts**, turn on **Select mode**, and tick the loose parts that belong in that drawer.
6. In the bar that appears, under **Change**, choose **Storage**. Under **Value**, choose your drawer. Press **Save**.
7. Go back to **Workbench → Storage** and select the drawer. The header counts its sets, figures, part lots and pieces, and the list below it shows each one.

<picture data-bw-screens><source media="(max-width: 600px)" srcset="../img/tutorials/tut-storage-phone-390-light.png"><img src="../img/tutorials/tut-storage-desktop-1024-light.png#only-light" alt="Workbench Storage with Drawer 3 open: the header counts its sets, figures, part lots and pieces."></picture>
<picture data-bw-screens><source media="(max-width: 600px)" srcset="../img/tutorials/tut-storage-phone-390-dark.png"><img src="../img/tutorials/tut-storage-desktop-1024-dark.png#only-dark" alt="Workbench Storage with Drawer 3 open: the header counts its sets, figures, part lots and pieces."></picture>

Repeat steps 2 to 6 for each drawer you want Part Runner to know about. [Know where things are](../how-to/storage.md) covers boxes inside boxes, moving things between storages and Undo.

## 2. Pick for several sets in one pass

Part Runner collects the missing parts of several sets while you walk along your drawers once. It works from the gaps recorded on your copies.

1. Open **Workbench → Part Runner**. Under **Pick for which sets?** you see every copy with recorded missing parts and how many it is missing.
2. Select **Choose sets** and tick three or four sets. (**All incomplete sets** takes every one.)
3. Select **Continue · N sets**, where N is the number you ticked.

<picture data-bw-screens><source media="(max-width: 600px)" srcset="../img/tutorials/tut-runner-sets-phone-390-light.png"><img src="../img/tutorials/tut-runner-sets-desktop-1024-light.png#only-light" alt="Part Runner: Choose sets is on, three sets are ticked and the button reads Continue · 3 sets."></picture>
<picture data-bw-screens><source media="(max-width: 600px)" srcset="../img/tutorials/tut-runner-sets-phone-390-dark.png"><img src="../img/tutorials/tut-runner-sets-desktop-1024-dark.png#only-dark" alt="Part Runner: Choose sets is on, three sets are ticked and the button reads Continue · 3 sets."></picture>

4. Under **In what order do you pick?**, you see the keys **Category**, **Category group**, **Colour**, **Size**, **Set** and **Storage**. A line under them says which order you get. Keep **Storage** switched on: it puts the parts that sit in the same drawer next to each other. A key with nothing to sort by is switched off and says why.
5. Select **Start picking**.

<picture data-bw-screens><source media="(max-width: 600px)" srcset="../img/tutorials/tut-runner-order-phone-390-light.png"><img src="../img/tutorials/tut-runner-order-desktop-1024-light.png#only-light" alt="The pick order: Category, Colour, Set and Storage are on, Size is off because no part sizes are recorded, and Category group is off."></picture>
<picture data-bw-screens><source media="(max-width: 600px)" srcset="../img/tutorials/tut-runner-order-phone-390-dark.png"><img src="../img/tutorials/tut-runner-order-desktop-1024-dark.png#only-dark" alt="The pick order: Category, Colour, Set and Storage are on, Size is off because no part sizes are recorded, and Category group is off."></picture>

6. Part Runner shows one part at a time: its picture, colour and number, **Pick N**, and which sets need how many. A part that three sets need appears once, with the total.
7. Find the part in your drawer and select **Found it**.
8. Choose where it goes. **Add to set** lowers the missing count of the sets that need it. Set how many go to each set with **−** and **+**. Select **Confirm**.

<picture data-bw-screens><source media="(max-width: 600px)" srcset="../img/tutorials/tut-runner-found-phone-390-light.png"><img src="../img/tutorials/tut-runner-found-desktop-1024-light.png#only-light" alt="Found it: choose Add to set, Add to loose parts or Add to pick list only."></picture>
<picture data-bw-screens><source media="(max-width: 600px)" srcset="../img/tutorials/tut-runner-found-phone-390-dark.png"><img src="../img/tutorials/tut-runner-found-desktop-1024-dark.png#only-dark" alt="Found it: choose Add to set, Add to loose parts or Add to pick list only."></picture>

9. Part Runner moves to the next part. Use **Skip for later** for a part you cannot find; its missing count stays as it is.
10. Select **Stop** when you are done. Every save is listed under **Recent saves**, each with its own **Undo**.

[Pick parts for several sets](../how-to/pick-parts.md) explains the pick order in full, the keyboard keys, and how to print the list or save it as CSV.

## 3. See which sets your loose stock finishes

Part Runner takes parts you find. Matchmaker works the other way round: it looks at your loose stock and shows which incomplete sets it can fill.

1. Open **Workbench → Matchmaker**. The heading says how many copies can be advanced and how many can become complete.
2. Look at the list. Copies that loose stock can finish come first and carry **Completes checked copy**. Each copy also shows **covers N of M missing**.

<picture data-bw-screens><source media="(max-width: 600px)" srcset="../img/tutorials/tut-matchmaker-phone-390-light.png"><img src="../img/tutorials/tut-matchmaker-desktop-1024-light.png#only-light" alt="Matchmaker: one copy shows Completes checked copy; the others cover only part of their gap."></picture>
<picture data-bw-screens><source media="(max-width: 600px)" srcset="../img/tutorials/tut-matchmaker-phone-390-dark.png"><img src="../img/tutorials/tut-matchmaker-desktop-1024-dark.png#only-dark" alt="Matchmaker: one copy shows Completes checked copy; the others cover only part of their gap."></picture>

3. Select a copy that completes to open it. Each line shows the part and **Needs N · have M**.
4. Find the part in your stock. Set **Transfer count** if you want to move fewer than suggested.
5. Select **Give N**. The loose stock goes down by that count and so does the copy's missing count. The page reloads with the new numbers.
6. Do the same for each line. When the last gap is filled the copy can count as complete.

A move is not a reservation: the same loose part can show against several copies, so work through one copy at a time. A copy becomes complete only when **Set is checked** is set on it. Every move is listed under **Recent saves** with an **Undo**.

## What next

You gave your loose parts a place, collected the missing parts of several sets in one trip, and moved loose stock into the sets it finishes. From here:

- [Know where things are](../how-to/storage.md) for more on storage.
- [Pick parts for several sets](../how-to/pick-parts.md) for the full pick order and printing.
- [Find sets your loose stock can finish](../how-to/match-stock-to-sets.md) for how matching works and how to narrow the list.

**Category group** is off by default. Switch it on to pick in the fixed category-group order, with **Other** last. Like **Category**, it is unavailable when none of the parts has a recorded category. It works independently of **Group parts by**.
