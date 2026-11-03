# The data model: two files and one id per item

*Since 0.6.0.*

Brick Work keeps what anyone could download apart from what only you have. That split explains why a catalogue update never touches your collection, why the catalogue needs no backup, and why every item has a number of Brick Work's own.

## Two files

**`catalogue.db`, the catalogue.** Rebrickable's catalogue: every set, part, minifigure and colour, the part lists of sets and figures, element ids and picture addresses. It also holds the mapping to BrickLink numbers and, if you load them, BrickLink's own item lists. It can be rebuilt at any time from Rebrickable's free download, and only the catalogue builder writes it.

**`brickwork.db`, your collection.** Copies, loose stock, lots, storage, wishes, orders, prices, your decisions about numbers, part lists that cost an API call, items that exist only in your collection, keys, tokens and settings. It cannot be rebuilt from anywhere else: this is the file you back up. Pictures, your own photos and instruction PDFs are files in the media folder (`data/images`, `data/thumbs`, `data/instructions`, `data/identifications`) that the database points to; back them up with it ([Back up the media folder](../how-to/back-up-and-restore.md#back-up-the-media-folder)).

The two files are a pair. The collection file is bound to one catalogue, and the **Database** check in **Tools & Admin** confirms that they belong together ([Back up and restore](../how-to/back-up-and-restore.md#check-the-database)).

## A Brick Work id for every item and colour

Every set, part, minifigure, booklet, box and colour has a **Brick Work id**, a running number. Rebrickable and BrickLink numbers are not ids. They are links that point at an item.

- **Catalogue items** are numbered by the catalogue builder. A new download keeps every id it already knows, matched by Rebrickable's number, so an update never renumbers what your collection uses.
- **Items born in your collection** get numbers from 1,000,000,000 up: an item you added by its BrickLink number only, a set newer than the catalogue fetched through Rebrickable's API, or an item you added before it was identified. The two ranges never meet.
- An id is **never reused**. When you merge a duplicate into a catalogue item, the old id points to the new one ([Resolve unresolved items and merge items](../how-to/merge-items.md)).

The item page's address uses this id (`/collection/item/<id>`), and so does API v2.

## Links to Rebrickable and BrickLink

An item reaches other catalogues through **links**. One item can have several numbers at one catalogue, and a link can hold for one colour only. A leg part, for example, is one BrickLink number in Black and another in every other colour. Each link has a status that says where it came from: *matched*, *inferred*, *manual* or *to check*. "This item has no BrickLink number" is stored as a fact about the item, so a price update knows to skip it rather than fail.

Prices, BrickLink exports and order matching follow these links. When there is a choice, you set the preferred number ([See an item's links and choose the preferred number](../how-to/links-and-preferred-numbers.md)).

## Part lists

A **part list** is what goes into a set or a figure. A copy names the list it was built from:

- a Rebrickable version from the catalogue (sets can have several versions), or
- a list stored in your collection file: BrickLink's list for that set, or Rebrickable's list of a set newer than your catalogue.

A copy's own lines (what is missing, what you checked, what you took from loose stock) belong to the copy, not to the catalogue. When you switch a copy to another list, its lines are updated in place: lines that stay keep their marks, new lines are added and vanished lines are retired, so your check history always points at real lines. A new catalogue never switches a copy by itself. When it changes the list a copy was built from, the copy says so and offers **Switch to the current list**, and you decide ([Choose and switch a part list](../how-to/part-lists.md)).

## The collection on top

Copies, minifigures, loose stock, lots, storage, wishes and orders are described in [Sets, copies, lots and stock](collection-model.md). In this model they all name items and colours by Brick Work id, so they work the same for an item from the catalogue, from BrickLink only, or one you have not identified yet.

## Updating the catalogue

**Re-download** and **Rebuild** in **Tools & Admin → Catalogue** build a new `catalogue.db` beside the old one and swap it in when it is ready, then reconcile your collection with it ([Settings and maintenance](../how-to/settings-and-maintenance.md#catalogue)). A new file is checked before it is swapped in, and one that fails its checks never replaces the old one. **Rebuild** moves the current file aside rather than deleting it. Nothing you own is stored in the catalogue file, so a build never changes your collection.

## Every change is an event

A save writes one **event** that names what changed. That is what **Undo** reverses, and it is the history the API's audit log shows ([Undo a change](../how-to/undo-a-change.md)).

## From 0.5

A 0.5 collection (schema 3.3) is moved with `brickwork migrate4`. The command reads the old file without changing it, translates every BrickLink number and colour to a Brick Work item and colour, proves the result, and writes a report of everything it could not carry ([CLI](../reference/cli.md#migrate4)).

The full design, with the tables, the DDL and the reasoning, is on the [Design](../../design/data-model-4.0/) pages.
