# Choose and switch a part list

*Since 4.0.*

Do this when a set has more than one part list to build a copy from: several Rebrickable versions, or BrickLink's list. A copy carries the list it was built from, so a check, a gap and a count always say which one.

## See which list a copy uses

Open the copy (**Collection → Sets**, then the set and its **Set 1**, **Set 2**…). The **Part list** card says where its lines come from: "Rebrickable · version 2 of 3" (with **latest** when it is) or "BrickLink's list", and how many lines and minifigures it has. Each minifigure line says where its own parts came from, because a figure's parts always come from the figure's own Rebrickable list, even in a copy built from BrickLink's.

The card shows **Switch** only when there is something to switch to.

## Pick a list when you add a set

In **Manage → Add**, a set row shows a **Part list** picker only when there is a choice. It starts on:

1. the choice you saved for this set,
2. BrickLink's list, if you turned on the BrickLink preference in Settings and a BrickLink key is set,
3. the latest Rebrickable version.

The line under the picker says which one it started on. If you pick another list, tick **Use this for new copies of this set** to remember it. Without a BrickLink key, BrickLink's list is never offered.

## Switch a copy to another list

1. On the copy, press **Switch** on the **Part list** card.
2. Choose a list. The sheet shows **What changes**: lines added, lines retired, and quantities capped.
3. Read **Marks that will not carry over**. A line that is missing, damaged or checked and is not in the new list is retired with its marks; a quantity that is lower in the new list caps the marks on it.
4. Press **Switch**. **Undo** takes the switch back, and the page says so.

Ticking **Use this for new copies of this set** is part of the switch: it is remembered in the same step, and **Undo** takes both back. The box is not offered for a list fetched from Rebrickable (a set newer than your catalogue), which cannot be remembered.

Nothing is deleted. A line that is not in the new list is **retired**: it stays with its marks and leaves every count and check. A note under the parts says "n retired lines kept · m with marks", and opens to list them. If you switch back to a list that has the line again, it comes back with its marks.

## BrickLink's list for a copy that is not on it

A copy already on BrickLink's list switches to a newer fetched BrickLink list the same way.


If BrickLink's list for the set was fetched before, the copy switches at once. If not, choosing it fetches the list: the sheet says "Fetches BrickLink's list; the copy switches when it arrives". The copy keeps working on its Rebrickable list, and its **Part list** card says **BrickLink list pending**.

- The card says what it is waiting for: the job running, today's BrickLink budget, or the network.
- When the list arrives, a copy with no checks or marks switches by itself. A copy with marks stays pending and offers **Switch now** with what would not carry over.
- **Cancel** stops waiting and leaves the copy on its Rebrickable list. If you ticked **Use this for new copies of this set** with the request, Cancel puts the set's earlier choice back (unless you changed it since). When the list arrives and the copy switches, one **Undo** takes back the switch and the remembered choice together.

Without a BrickLink key the choice is greyed with "needs a BrickLink key".

## When a list changed

After a catalogue download, a copy whose list is no longer the one in the catalogue says "Rebrickable changed version 3 of 3 since this copy was built · n lines differ", for the copy and for each figure line. Nothing switches by itself. Press **Switch to the current list** to see what would change and decide. For a copy on BrickLink's list the note says "needs a BrickLink key" instead when no key is set; the page always opens without one.
