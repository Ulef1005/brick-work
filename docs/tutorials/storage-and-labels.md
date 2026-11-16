---
audience: user
verified: 1.0
---

# Give every bin a place, then label it

You have bins, drawers and shelves full of bricks and no way to tell which one holds what. In this tutorial you name your storage places, put things in them and print QR labels for the bins. Then you scan a label to open a bin and find a part by where it is stored.

It takes about 20 minutes. You need a Brick Work install with a few sets, minifigures or part lots in the [collection](../concepts/collection-model.md), and a printer that takes A4 paper. A phone with a camera helps for step 4. Your own names and numbers will differ from the examples.

## 1. Add your storage places

A storage is any place you name: a box, a drawer, a shelf, a room. Storages can sit inside each other, so a drawer can live on a shelf.

1. Open **Workbench → Storage**. On a new install it says **No storages yet.**
2. Select **Add storage**.
3. Enter a **Name**, for example *Shelf A*. Choose a **Type**, here **Shelf**, and leave **Inside** on **Nothing, top level**.
4. Select **Add storage** again to save it.
5. Repeat for a bin on that shelf. Name it *Bin 3*, choose the type **Bin** and set **Inside** to *Shelf A*.

Add a few more bins the same way. The list shows each storage with the number of sets, figures and part lots it holds, and a **Note** field is there for anything you want to remember about a place.

## 2. Put things in them

You can give one item a place, or many at once.

1. Open an item from **Collection**, for example a set copy, and select **Edit**.
2. Choose its **Storage**, then select **Save**. The page now shows where the item is.
3. To file many items at once, open a **Collection** list and turn on **Select mode**. Tick the items.
4. In the bar that appears, under **Change**, choose **Storage**. Under **Value** choose the bin, then select **Save**.

Anything without a place stays under **Not stored** in the Storage list. That entry is a quick way to see what you have not filed yet. [Know where things are](../how-to/storage.md) has the other ways in, including moving things between storages.

## 3. Print the labels

1. On **Workbench → Storage**, select **Print labels**. A tick box appears on every storage and a bar opens at the bottom. It reads **0 selected · 200 labels at most per download**, and its button says **Choose storages**.
2. Tick the bins you want, for example three of them. The button now reads **Print labels · 3**. **Clear** unticks everything. **Select all** ticks every storage, up to the limit of 200 labels per download.
3. Select **Print labels · 3**. A sheet opens with one chip for each chosen storage. Select the **×** on a chip to drop that storage.
4. Under **Layout**, choose an A4 layout: **A4 · 21 labels, 63.5 × 38.1 mm** or **A4 · 14 labels, 99.1 × 38.1 mm**. The other choice is for 62 mm label tape.
5. Check the preview. With more labels than fit on one sheet, **Previous** and **Next** page through the sheets.

For one bin only, open it from the list and select **Print label**. The same sheet opens with that one storage chosen.

### Check the address on the codes

Under **Address on the codes** the sheet shows where the QR codes lead, as *address/workbench/storage/…*. Your phone camera opens this address, so it must work from your phone.

If the address uses localhost or a bare IP number, the sheet warns **This address uses localhost or a bare IP. Your phone may not open it.** A code printed now would only work on the computer that runs Brick Work.

1. Select **Change** next to the address. This opens **Tools & Admin → Settings**.
2. Under **Address for labels**, enter an address your phone can open, for example *https://bricks.example*. Use HTTP or HTTPS, with no path. Select **Save**.
3. Go back to **Workbench → Storage** and open the label sheet again. The warning is gone.

Leave the setting empty to use the address you opened Brick Work on.

### Download and print

1. Select **Download PDF**.
2. Print the PDF at 100 %, not fit to page. The cut guides you saw in the preview are not part of the print.
3. Cut the labels and stick one on each bin.

Each label shows a short id and a QR code. A short id belongs to its storage for good and is never reused, even after you archive that storage.

## 4. Scan a label

1. Point your phone camera at a label on a bin and open the link it shows.
2. Brick Work asks you to sign in if you are not signed in yet. After you sign in it takes you straight to that storage.
3. Read the contents, grouped as **Sets**, **Minifigures**, **Part lots** and **Other**.

If you printed a label for a storage you later archived, the page says **This storage is not here** and links back to **Storage**.

## 5. Find a part by where it is stored

Say you need a part and remember only that it is in a bin on the shelf.

1. On **Workbench → Storage**, select the bin. Its page lists what it holds. Use **Search** to narrow a long list, and the filters beside it.
2. Select the name of a part, set or minifigure to open its page. The facts there show its storage.
3. To search the other way round, open a **Collection** list and filter or group it by **Storage**.
4. If you know only the short id from a label, use **Jump to a set, copy, figure or part** at the top of any page and type the id.

When you take things out or reorganise, open a storage, select **Select**, tick the items and choose **Move to another storage**. Nothing is lost: the **History** at the bottom of the page lists each move with an **Undo**.

## What next

You named your storage places, filed items in them, printed labels with a working address and used a label to open a bin. From here:

- [Know where things are](../how-to/storage.md) for moving items, archiving a storage and purchase locations.
- [Print storage labels](../how-to/storage-labels.md) for tape labels, the limits and the exact address rules.
- [Pick parts](../how-to/pick-parts.md) from your sorted loose stock.
- [Undo a change](../how-to/undo-a-change.md).
