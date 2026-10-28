# Receive a parts order

*Since 0.5.0.*

Do this when a BrickLink order is on its way or has just arrived: bring its lines into Brick Work, count what came out of the bag and put each piece where it belongs.

Open **Workbench → Orders**.

## Import the order

The **Import an order** page offers three ways in.

- **Import a placed order** reads your BrickLink account. It needs a BrickLink key. Press **Load placed orders**, tick the orders you want and press **Import 1 order** (or **Import 2 orders**, and so on). Orders you already imported show **Already imported** and cannot be ticked.
- **Paste order email**: paste the store's whole confirmation email and press **Read email**.
- **BrickLink XML upload**: drop an `.xml` file (or open **Or paste XML**) and press **Import and review**. One order per file.

An order e-mail names colours and items by words, not numbers. Brick Work reads the BrickLink colour name and looks for an item with exactly that name; a name that fits several items (or none) leaves the line for you to match.

A total always comes with its currency: a document that gives a total without a currency leaves the order without a total. A currency can stand without a total: an e-mail has only line prices in EUR, so its order has the currency and no total, and the line prices show EUR. An order whose document names no currency at all shows **Currency not recorded** on its line prices. Orders stored by an earlier version get their currency from their document when Brick Work starts.

Importing the same document a second time adds nothing: Brick Work answers **Already imported · open the existing order**. To add a second document to an order you already have, such as the email after the XML, open **Link to an existing order** and choose that order.

## Review the lines

Each import starts as a draft. On the order's page, under **Documents · resume review**, open the document.

Brick Work places a line on an item by the BrickLink type, number and colour number the document names, looking in your collection's links and in the catalogue together. A line it could not place stays as the store wrote it, marked **Unmatched**. This happens when the number or colour is unknown, or when the number names more than one item: Brick Work never picks one of them for you. In that case the line offers **Could be** with the candidates.

1. For any line Brick Work could not place, choose a candidate under **Could be**, or use **Search the catalogue** and pick the item, or set **Item type** and **Number** to a number that names exactly one item. Choose the **Colour** for a part, then press **Match line**.
2. Press **Finish review**.
3. If the order already has saved lines, link each repeated line to its **Saved line** so it is counted once. Leave **New line** for an extra purchase.
4. Press **Save lines**.

**Reopen review** takes a reviewed document back to draft.

## Count what arrived

1. Press **Count what arrived**.
2. Set the **Received** number on each line with **+** and **−**, or press **Mark all received** if everything is there.
3. Press **Save partial receipt**.

Short lines stay open. Count them again when the rest arrives. Each save is listed under **Count audit** with an **Undo**.

## Allocate the pieces

1. Press **Review allocation**.
2. Brick Work suggests where each received piece goes: missing parts in your [copies](../concepts/collection-model.md) first, the rest to **Loose stock**. Change any number before you confirm.
3. For loose stock, choose a **Location** and a **Lot** if you want. A set line cannot go to loose stock: add the set as a copy in **Manage → Add**, and hold the line.
4. Press **Confirm allocation**.

**Reset suggestion** puts the suggested numbers back. After confirming, **Undo** next to **Allocated … pieces** reverses the whole allocation.

A line you don't want in stock yet can be put on hold: under **Allocations and reconcile**, press **Hold line …**. A held line adds nothing to stock until you press **Release line …**.

## Get what's still short

Under **Allocations and reconcile**, **Export short list · BrickLink XML** downloads `order-short.xml`. It lists every saved line with fewer pieces received than ordered, with the shortfall as the wanted quantity, ready to upload to a BrickLink wanted list. A line with no BrickLink number or colour cannot be named there: it is left out and listed in the download's `X-Bw-Skipped` header.

## Close the order

Under **Allocations and reconcile**, every line where received and allocated differ shows a **Fix** button. When every document is reviewed, no line is held and every received piece is allocated, press **Mark reconciled**.

The same view lists the **Allocation history**, with **Undo operation** per allocation, and the order's full **History**.

The order list shows each order's state: Draft, Reviewed, Open, Counting, Allocated, Held or Reconciled.

## Export orders as CSV

On **Workbench → Orders**, under **Already imported**, open **Export orders · CSV**.

1. Optionally set **From**, **To** and **Store**.
2. Under **Rows**, choose **One per order line** or **One per order · new and used totals**.
3. Press **Download CSV**.

Totals stay per currency. Shipping and fees are not stored separately; the per-order summary shows them as Other costs (grand total minus lines).

## What next

- [Check a set's parts](check-set-parts.md) for a copy the order just completed.
- [Know where things are](storage.md) to put the new loose stock away.
- [Undo a change](undo-a-change.md).
