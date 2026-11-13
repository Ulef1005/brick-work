---
audience: user
verified: 1.0
---

# Change an item's variant

*Since 1.1.0.* On the item page of a figure or part, **Identity** has a **Change variant…** button; the same action is on the API (`POST /items/{id}/change-variant`).

Do this when the catalogue lists the same figure (or part) twice, an older and a reissued variant, and your collection owns the wrong one. A figure from a reissued set may carry a new Rebrickable number while BrickLink still has one number for it. Unlike a [merge](merge-items.md), both items stay: the item you leave is an ordinary catalogue item afterwards, never deleted and never merged.

## Steps

1. Open the item page of the figure or part you own now. In the **Links** card, press **Change variant…** (next to where **Merge into…** sits for an item you added yourself). The button is there for an item of the live catalogue that is a figure or a part, not a set and not merged, and only when changes are switched on.
2. Under **Change to**, Brick Work suggests the live items of the same kind that hold one of this item's BrickLink numbers, or that a link to check of this item names. To find another, search by number or name; only items of the same kind are listed.
3. Choose the variant you own. It gets the **Chosen** mark, and **What moves** appears: the loose figures (or parts), the figure (or part) lines in your copies, the wishes, and the BrickLink number that follows to the other item. Nothing is changed yet. The preview also says that the old item stays in the catalogue and its link to the number goes to **Links to check**.
4. If the red message says **This change is not allowed** (see below), nothing can be done with this pair: pick another item. Otherwise press **Change variant**.
5. The other item's page opens with *Changed variant from … to this item · n rows moved* and **Undo**.

## What it does

The change moves what you own from the item you start on (**from**) to the variant you pick (**to**). Both must be of the same kind, and neither may be merged. Brick Work does the following as one change:

- **Moves what you own.** Loose stock, wishes and the figure lines of your copies move to the new variant and keep their ids, counts, checks and history. A copy keeps its whole part list; only the line now names the new figure. A line that was attached to a catalogue part list the new variant does not have becomes a **migrated** list: its parts stay as they are, and **Choose a part list** ([Choose and switch a part list](part-lists.md)) can attach it to a list of the new variant later.
- **Moves the BrickLink number.** The number is the one the old variant prefers, else the one link to check on the new variant. The new variant gets it as your own (`manual`) link and as its **preferred** one ([Links and the preferred number](links-and-preferred-numbers.md)); a link to check there is confirmed, a missing one is added. The old variant's link of that number becomes **to check** and is no longer preferred, so the number finds only the new variant. Nothing is deleted.
- **Leaves the rest.** Prices, properties, pictures, fetched part lists and order lines stay with the old variant.

The change is one event. **Undo** ([Undo a change](undo-a-change.md)) puts every row and link back exactly, and is refused with **… changed since the change of variant · undo the later change first** once a row it moved has been changed.

## When it is refused

The page shows the reason in its red message before you confirm, and nothing is changed, when:

- the items are of different kinds, the same item, or either is merged (a set cannot change variant here: a copy's part list belongs to its set);
- a job (a price or part list fetch) for either item is still running: let it finish or cancel it, then try again;
- a copy, a loose figure or a part list holds a line for **both** items: correct that line by hand first;
- a stock row or a wish of the old variant would meet a live one of the new variant (same colour, condition, lot and storage; same wish list and colour). The rows are not added up silently: change or archive one of them first;
- a row holds a part list fetched for the old variant: switch its part list first.

## From the API

`POST /api/v2/items/{id}/change-variant` with `{"to": {"id": 123}}` (or a provider number) and an `Idempotency-Key`; the answer names both items, the BrickLink number that moved (or `null`) and the receipt. Undo is `POST /api/v2/events/{id}/undo`.
