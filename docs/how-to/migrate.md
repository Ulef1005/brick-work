# Bring your collection in from another app

*Since 0.8.0.*

Do this when your collection lives somewhere else today and you want it here without typing it in again. Open **Get started** (the empty **Sets** page, or **Tools & Admin › Get started**) and choose **Choose where it is** on step 3, **Bring your collection in**. Every way in shows a preview before anything is added, and an import can be undone. Load the catalogue first: an import finds every item in it.

While you follow a choice, the pages it opens show **‹ Back to Get started**. Back there, **In your collection** counts the copies, loose entries and wishes that came in. It also says how many copies still have no condition or completeness, because an import leaves those for you to set. Each **imported from …** line opens **Sets** filtered to the copies that site brought in.

## Rebrickable or Brickset account

Your sets and wishlist come over through **Collection sync**, with a preview row by row. You need the site's API key (the keys step of **Get started**) and your own account login on **Collection sync**. See [Sync with Rebrickable and Brickset](sync-collection.md). Imported copies are tagged **imported from Rebrickable** or **imported from Brickset**.

A Brickset CSV file cannot be read yet. Use the account sync instead.

## BrickLink

Download your wanted list or a store inventory from BrickLink as an XML file, then choose **Choose an XML file**. It opens **Add** with **File** selected. Brick Work reads the item type, number, colour, quantity and condition of each line, and for a wanted list also the maximum price, remarks and the wanted list it came from. The review asks, row by row, whether a line is owned, loose or a wish.

## BrickTracker

Choose **Import app.db** and upload BrickTracker's `app.db`, any version. See [Import from BrickTracker](import-from-bricktracker.md).

## Another app's file

Many collection apps can export one of two formats that Brick Work reads. Check your app's export menu for one of them:

- **BrickLink XML**: an inventory or wanted list, as above.
- **Rebrickable CSV**: a set list or part list with the columns `set_num`, `part_num` or `minifig_num`, plus `quantity` and `color_id`.

Choose **Choose a file**, which opens **Add** with **File** selected. A file can be up to 2 MB, and one review shows up to 500 rows. Lines Brick Work cannot match are listed and left out. Copies added from a file get no **imported from** tag.

## By hand

**Add a set** opens **Add**: search by number or name, paste a list of numbers, take a photo, or add from an order.
