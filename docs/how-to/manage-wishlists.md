---
audience: user
verified: 0.9
---

# Manage wishlists

*Since 0.5.0.*

Do this when one wishlist is no longer enough. Use separate lists for a project, for gifts or for one BrickLink wanted list, and move wishes between them.

Open **Planning → Wishlist**. The lists sit at the top as chips, each with its count. **All lists** shows every wish from every active list and labels each one with its list's name.

## Read a wish's state

Each wish answers one question: can you buy this set now at a price you accept. The tile shows the picture, the number with one **state** tag, the name, the theme and year, and, under **All lists**, the list. It shows what you want: the condition, and how many you have of how many. It shows your max, or **No max set** with **Set max**. It shows the price now for that condition (**Used avg**, **Used listings**, **New avg** or **New listings**) and the gap to your max in words. The heading says how many wishes are under your max, and the line under it names where the prices come from.

| Tag | Meaning |
|---|---|
| **Buy now** (filled) | The price now is at or under your max. |
| **Wait** (outlined) | The price now is over your max. |
| **No max** (dashed) | The wish has no max, so there is nothing to compare with. |
| **Not comparable** (dashed) | The max and the price are in different currencies and no exchange rate covers them, or a currency is not recorded. |
| **No price** (dashed) | The wish has a max, but there is no sale or listing for the condition you want yet. |

<picture data-bw-screens><source media="(max-width: 600px)" srcset="../img/tutorials/tut-wishlist-states-phone-390-light.png"><img src="../img/tutorials/tut-wishlist-states-desktop-1024-light.png#only-light" alt="Wishlist tiles: each shows its state tag, here Buy now, beside the number, then what you want, your max, the price now and the gap to your max."></picture>
<picture data-bw-screens><source media="(max-width: 600px)" srcset="../img/tutorials/tut-wishlist-states-phone-390-dark.png"><img src="../img/tutorials/tut-wishlist-states-desktop-1024-dark.png#only-dark" alt="Wishlist tiles: each shows its state tag, here Buy now, beside the number, then what you want, your max, the price now and the gap to your max."></picture>

The picture shows where the tag sits on a tile; these wishes are all under their max. The table above lists all five tags.

The **State** chips under the condition chips filter by these tags and show how many wishes each holds. The list is sorted **Buy now first** until you pick another sort under **Sort**. Press the wish to open its page. The answer comes first. Then come **Your wish** (condition, how many are filled, list, max and max with box, with **Edit**) and **Prices**. **Prices** has one strip from the lowest to the highest sale and a mark at the average. A condition with no sales says **No sales**. With a single price, the page says so instead of drawing a trend line.

The heading counts wishes, never pieces. A list of sets says "2 of 5 wanted sets are under your max" and **5 sets wanted**. A list that also holds parts says "wanted items" and **14 wanted**, however many pieces each part wish asks for. To change the condition you want (New, Used or Any), the max or the max with box, press **Edit** on the wish's page.

## Create, rename and archive lists

1. Press **Manage lists**.
2. To create a list, open **New list**, enter a **Name**, and optionally a **Note** and a **BrickLink wanted list id**. Press **Create list**.
3. To rename a list, open it, change **Name** (or the note or id) and press **Save list**.
4. To archive a list, open it and press **Archive list**. Its wishes are archived with it.

Names may repeat. A BrickLink wanted list id can be linked to one list only.

### Restore a list

Archived lists stay in **Manage lists**, marked **Archived**. Open one and press **Restore list**. The wishes that were archived together with the list come back; wishes you had archived on their own before stay archived.

If a wish coming back would duplicate a live wish for the same item and colour in that list, nothing is restored. Archive or edit the other wish first.

## Move or copy wishes

### Several at once

1. Tick the wishes in the list. A bar shows how many are selected.
2. Under **To**, choose the target list.
3. Press **Move** or **Copy**.

**Clear** unticks everything. You can move or copy up to 500 wishes at a time.

### One wish

On a wish's page, press **Move or copy to another list**, choose the list under **To list**, then **Move** or **Copy**. The action shows only when there is another active list.

A copy keeps the quantity, condition, maximum prices and their currencies, colour, note and flags.

### Collisions

A list holds one live wish per item and colour. If any selected wish already exists in the target list, or two selected wishes are the same item and colour, the whole move or copy is refused and nothing changes. Edit or archive the duplicate, then try again.

## Undo

After a change, the message at the top of the list reads *Saved* with an **Undo** button beside it. **Undo** reverses the last change: a move puts the wishes back, a copy archives the new wishes, an archive restores the list.

Undo is refused if something changed since, for example when a later save touched the same wishes. Undo the later change first. If the list the wishes came from has been archived since, restore it before you undo the move.

## Export a list

1. Choose a list chip, or **All lists**.
2. Press **Export**.
3. Choose the **Format**:
   - **BrickLink XML** uploads into a BrickLink wanted list.
   - **Rebrickable CSV** imports into a Rebrickable list. Choose **Parts** or **Sets** under **Rebrickable list of**.
4. Press **Export**.

The file downloads, and **Export summary** says how many rows were exported and which were left out and why. Archived lists and wishes are never exported.

A wish Brick Work cannot name in the format you chose is left out and listed, never exported under a made-up number. The reasons are:

- *No BrickLink number* or *No BrickLink colour* for the XML
- *Missing or ambiguous Rebrickable mapping* for the CSV
- *Outside selected export kind* for a set in a parts file and the other way round

The rest still exports.

A few things to know about the files:

- A maximum price goes into the BrickLink file only when it is above zero and in your BrickLink currency. Otherwise the limit is left out and the summary says so.
- The maximum price with box is never exported: a BrickLink wanted list has no such field.
- The BrickLink wanted list id is written only when you linked one to the list.
- The Rebrickable file includes only items with a known Rebrickable number and colour. The rest are listed in the summary.

**Download CSV** and **Print** next to **Export** give the current list in Brick Work's own columns, for a spreadsheet or for paper.

## What next

- [Undo a change](undo-a-change.md).
- [Receive a parts order](receive-an-order.md) when the wishes arrive.
