# See an item's links and choose the preferred number

*Since 0.6.0.*

Every item page has a **Links** card: the numbers other catalogues use for the item. Brick Work uses them for prices, BrickLink exports and matching orders.

## What the card shows

- **One block per catalogue** (BrickLink, Rebrickable), with each number in mono type.
- **A status pill.** *matched* (the catalogue or a list says so), *inferred* (a rule guessed it, such as the set number), *manual* (you chose it), *to check* (a guess waiting for your decision). A number that came with the item shows *catalogue number* or *own number*.
- **Colour.** A number that holds for one colour only shows that colour's swatch and "only"; the other numbers read "All colours", or "All other colours" next to such a one. A leg part, for example, is one BrickLink number in Black and another in every other colour.
- **Used for …** marks the number that answers for the colour you are looking at; **Preferred** marks the one you or a rule preferred.
- **No number.** A catalogue with nothing for the item says so, with the reason: no match found, or to check (no candidate, the kind differs, from the migration).

## Choose the preferred number

When an item has several numbers at one catalogue (a sticker sheet that BrickLink sells as three), press **Choose preferred BrickLink number**. Pick a number, then **Prefer for all colours**, or **Prefer for [colour] only**. The second adds a number of your own for that colour; the other colours keep their choice. **Undo** is offered straight after ([Undo a change](undo-a-change.md)).

## An item with no number

An item added without a number says **Not identified yet**. Price updates skip it, so it shows no sales, and BrickLink export and order matching leave it out. Everything else works. Type its BrickLink number and press **Add link**, or **Merge into a catalogue item** ([Resolve unresolved items and merge items](merge-items.md)). A number another item already holds is refused with a pointer to the merge.
