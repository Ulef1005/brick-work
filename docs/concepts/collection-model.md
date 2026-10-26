# Sets, copies, lots and stock

*Since 0.5.0.*

Brick Work keeps apart what a thing *is* and the thing *you own*. These are the words every guide uses.

## Catalogue item

A catalogue item is a thing that exists in the Lego world: a set, a minifigure, a part, an instruction booklet, a box, gear, a book or a catalog. It has a number, a name and, for sets and figures, an inventory of what goes in it. A catalogue item says nothing about whether you own it.

On screen an item shows its Rebrickable number first, and its BrickLink number beside it where the two differ (`970c03 · BrickLink 970c11`). An item that exists only on BrickLink, because you added it by its BrickLink number, shows that number marked *BrickLink*. An item with no number from any catalogue, such as a part you added from a photo before it was identified, is *Unidentified*: it shows its name, and it works like any other item in your lists, copies and stock. Search takes either number.

## Set and copy

A **set** is the catalogue item, such as 6081. A **copy** is one set you own. Own the same set twice and you have two copies, each with its own condition (new or used), storage, purchase details, notes and photos, so they never blur into one.

Each copy carries its own list of parts and minifigures, taken from the set's inventory. When you check a copy, you mark on that list what is missing or damaged, for that copy only. Whether the copy is complete is its [completeness](completeness.md).

## Minifigures

A minifigure in a set belongs to that copy and is counted there: a missing figure makes the copy incomplete.

A **loose minifigure** is a figure you own on its own. It can carry its own list of parts (head, torso, legs, accessories), so you can see which figures you can put together from parts and what each one still lacks.

## Loose stock

**Loose stock** is everything you own outside a copy: parts by part and colour, loose minifigures, and other items such as booklets and boxes. Each entry has a quantity, a condition (new, used or damaged) and optionally a storage place and a lot. Parts inside a copy are not loose stock: they are needed there.

Part Picker, the Matcher and Complete sets look in loose stock for parts that your copies are missing.

## Lots

A **lot** is a named group of loose stock that came together, such as "Flea market bag, March". It can have its own storage and purchase details. Putting stock in a lot keeps the quantities and the original lines; it only groups them.

## Boxes and instructions

An original **box** or an instruction **booklet** is a catalogue item of its own. You own one as loose stock, next to (not inside) the copy of its set. Instruction PDFs you add are kept with the set, so every copy of it shares them.

## Storage

A **storage** is a place: a drawer, a bin, a shelf, a room. Copies, loose stock and lots can each be given one, so you know where everything is. Something without a storage shows as *Not stored*.

## Wishes and wishlists

A **wish** is something you want: a set, a minifigure, a part in a colour, or another item, with a quantity, the condition you accept and, if you like, your maximum price. Wishes live in **wishlists**; you start with one called *Wishlist* and can add more named lists.

Brick Work shows how much of each wish you already have, counted from what you own: copies for sets, loose stock for parts and figures. Parts inside copies never count, since they are needed there.

## Orders

An **order** is a purchase from BrickLink, imported from your account, a confirmation email or the order XML. Its lines are what you bought. When the parcel arrives you count what came, then allocate each line either to a copy that is missing it or to loose stock.

## How they fit together

- A catalogue item can have many copies, loose stock entries and wishes, or none.
- A copy belongs to one set and has its own part and minifigure list.
- Loose stock may sit in one lot and one storage; a copy sits in one storage.
- Order lines end up in copies or in loose stock.
- Every change records an event, and most can be undone.
