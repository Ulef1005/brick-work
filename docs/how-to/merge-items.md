# Resolve unresolved items and merge items

*Since 4.0.*

Do this when Brick Work holds an item it cannot yet name: a part or figure the migration could not place, an item you added without a number, or a local item that is really a catalogue item under another number. Open **Manage → Tools & Admin → Unresolved items**. The list holds only what needs a decision: the hub row says how many.

## What each row asks

- **May be this catalogue item** (a local item with candidates). A candidate is a catalogue item the migration suggested, or one whose BrickLink number is the same as this item's. **Merge into this** moves everything that named the local item (copies, loose stock, wishes, prices, links, pictures) onto the catalogue item. You can also type a number in the box under the row and press **Merge into the item with this number**.
- **A link to check** (**Confirm** / **Reject**). Confirm makes the link yours (it is no longer replaced by a catalogue refresh); Reject removes it.
- **A status to check.** **Keep as unmatched** records that you looked and the item stays as it is. When BrickLink and the catalogue disagree on an item's kind, **Move to …** changes the kind.
- **No number at all** (an item added as unidentified). Type its BrickLink number and press **Link BrickLink number**, or merge it into the catalogue item that it is.

Every decision is saved as one event, and the page offers **Undo** straight after it ([Undo a change](undo-a-change.md)).

## What a merge does

A merge is allowed only for a local item (or one the catalogue has retired), into an item of the same kind that is not merged itself. The local item stays in the database, marked as merged, and its page redirects to the item it went into.

- **Added up.** Loose stock of the same condition, lot and storage becomes one row with the quantities added; the other row is archived. Two wishes for the same list and colour become one with the quantities added.
- **The catalogue item's row stays.** Where both items hold the same price key, property, picture, link, set preference or status, the catalogue item's row stays and the local one is dropped. A migration guess that asked for this very decision is dropped too.
- **The number is kept.** The local item's own number stays on the catalogue item as a link, so the number still finds it.
- **Refused.** A copy, a loose figure or a fetched part list that holds a line for both items in one colour. Correct that line by hand first; the message names the copy.

**Undo** on a merge puts every row back exactly. It is refused with **… changed since the merge · undo the later change first** once any of those rows has been changed since.

## Moving an item to another kind

An item whose kind was guessed from its theme can be wrong (a set that is really a gear item). When BrickLink says so and the item is already held, **Move to …** changes its kind and replaces the copies by loose stock of the new kind, or the other way round, keeping the condition, storage, price, note, flags and photos. It is refused when it would lose something: a copy with part lines, a damaged piece becoming a copy, or a lot. Undo restores the copies or stock rows exactly.
