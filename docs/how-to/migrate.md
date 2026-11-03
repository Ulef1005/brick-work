# Bring your collection in from another app

*Since 0.8.0.*

Do this when your collection lives somewhere else today and you want it here without typing it in again. Open **Get started** (the empty **Sets** page, or **Tools & Admin › Get started**) and choose **Choose where it is** on step 3, **Bring your collection in**. Every way in shows a preview before anything is added, and an import can be undone. Load the catalogue first: an import finds every item in it.

While you follow a choice, the pages it opens show **‹ Back to Get started**. Back there, **In your collection** counts the copies, loose entries and wishes that came in. It also says how many copies still have no condition or completeness, because an import leaves those for you to set. Each **imported from …** line opens **Sets** filtered to the copies that site brought in.

## Rebrickable or Brickset account

Your sets and wishlist come over through **Collection sync**, with a preview row by row. You need the site's API key (the keys step of **Get started**) and your own account login on **Collection sync**. See [Sync with Rebrickable and Brickset](sync-collection.md). Imported copies are tagged **imported from Rebrickable** or **imported from Brickset**.

Or export **My Sets** from Brickset as a CSV file and choose **Choose a CSV file**, which opens **Add** with **File** selected. With **Owned** (or **Loose**) Brick Work takes the sets marked owned, with their count; an owned count split into new and used becomes a row per condition. With **Wishlist** it takes the sets marked wanted. The set number is Brickset's number and variant, such as `8285-1`, and your Brickset notes become the note. A file without the columns this needs is refused with their names. The CSV needs no Brickset key, and its copies get no **imported from** tag.

## BrickLink

Download your wanted list or a store inventory from BrickLink as an XML file, then choose **Choose an XML file**. It opens **Add** with **File** selected. Brick Work reads the item type, number, colour, quantity and condition of each line, and for a wanted list also the maximum price, remarks and the wanted list it came from. The review asks, row by row, whether a line is owned, loose or a wish. BrickLink files some Rebrickable parts under one number: its 3001 also names the old mould 3556. Brick Work then takes the part with the same number and says so in the review. If none has the same number, the line names the parts it could be: add the one you mean by its Rebrickable number.

## BrickTracker

Choose **Import app.db** and upload BrickTracker's `app.db`, any version. See [Import from BrickTracker](import-from-bricktracker.md).

## Another app's file

Many collection apps can export one of two formats that Brick Work reads. Check your app's export menu for one of them:

- **BrickLink XML**: an inventory or wanted list, as above.
- **Rebrickable CSV**: a set list or part list with the columns `set_num`, `part_num` or `minifig_num`, plus `quantity` and `color_id`.

Choose **Choose a file**, which opens **Add** with **File** selected. A file can be up to 2 MB, and one review shows up to 500 rows. Lines Brick Work cannot match are listed and left out. Copies added from a file get no **imported from** tag.

## By hand

**Add a set** opens **Add**: search by number or name, paste a list of numbers, take a photo, or add from an order.
