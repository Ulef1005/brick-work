# Pictures, prices and where they come from

*Since 0.6.0.*

Do this to understand why an item has a picture or a price, to change where pictures come from, or to fetch a set Brick Work does not know yet. Pictures and prices are cached copies: nothing in them is your data, and every one can be fetched again.

## What happens when you add something

Each row you confirm in **Manage → Add** gets one background job with six steps. Three of them reach out to other sites:

| Step | What it fetches | Needs a key |
|---|---|---|
| Downloading images | The item's picture, once per colour for a part you hold in several colours. | Only the Rebrickable API source does. |
| Fetching set metadata | Brickset's theme, piece count and years of sale for a set, and the retail price in your retail country. | A Brickset key. |
| Fetching market price | BrickLink's price guide for new and used, in your region and currency. | The four BrickLink values. |

While you review a row on **Add**, a set, minifigure or other item without a picture gets one fetched and stored at once from the free sources (Rebrickable's file and BrickLink's image), so you see what you are adding; a part waits for its colour. This never spends the Rebrickable API's daily budget; the Add job still tries every source. That picture is kept even if you do not add the item (the page says so), as are the item's catalogue details it belongs to; nothing of your collection changes before the last step.

When **Add** makes copies of a set, the parts and minifigures of those copies that have no picture yet are queued too, as one bulk action under **Jobs › Bulk actions**; your own work still goes first. When a copy switches to BrickLink's list by itself once it is fetched, its new parts are queued the same way; if you accept an offered list by hand, **Refresh pictures** fetches what is still missing.

**Add** is not the only place. These also queue a **Downloading images** step for an item that has no picture yet (for every colour you hold), so the picture is there without pressing **Refresh pictures**:

- placing an order line into loose stock (**Workbench → Orders**, **Allocate**);
- **Part Spotter**;
- the import of another app's file (**Tools & Admin**);
- a **Collection sync** pull from Rebrickable or Brickset;
- **Found** in the Workbench, when you put the part into loose stock.

Nothing is queued for an item that has its pictures, for an unidentified item, or while a picture job for the item is already waiting. If you undo the change, the queued job stays and just fetches the picture.

An item with no number from any provider (an *unidentified* item) cannot be asked for anything. Its steps end **done** with the finding **unidentified**, nothing is called, and the job does not fail. Prices and the BrickLink export also skip an item BrickLink has no number for; add a link or merge it into a catalogue item to resolve it.

## Where pictures come from

Three sources, tried in this order:

- **For parts:** the Rebrickable catalogue (a plain image download for the colours the catalogue shows the part in), then BrickLink (a plain image download by the part's BrickLink number and colour), then the Rebrickable API.
- **For everything else:** BrickLink, then the Rebrickable catalogue. The catalogue carries pictures of parts only, so a set or figure is pictured by BrickLink unless you add the Rebrickable API to its order.

The first two need no key and make no API call. Add your keys under **Tools & Admin → Catalogues & keys**: it shows each source with its budget for the day, the last success and the last error, and a card per key where a key is entered write-only, tested once and stored encrypted. The Rebrickable API source needs your Rebrickable key and counts against the day's budget. A part in a colour the catalogue has no picture for falls through to BrickLink and then to the API. If no source can serve it, the step fails with the reason, and **Retry** on the job runs it again once something has changed.

Change the order under **Picture source order** in **Manage → Tools & Admin → Settings** (one list for parts, one for everything else; the page's **Pictures** card shows what is covered, and **Refresh pictures** queues the missing ones or all of them); the setting applies to jobs queued afterwards. **Catalogues & keys** shows the same order on its **Pictures** card. Updating from 3.3 keeps your order: the default becomes the one above, and a changed order keeps its sequence with Rebrickable split into the catalogue and then the API.

### A part with no known picture

Before you confirm, the Add review warns **No picture known for this colour** on a part row when no source can serve it: the catalogue has no picture for that colour, BrickLink has no number for the part, and no Rebrickable key is set. The part is still added; a key, or a link to a BrickLink number, lets the picture step find one later.

## Prices and budgets

Prices are fetched for every colour a part is held in, new and used, as BrickLink's sold average (or the listings when nothing sold). **Update price** on an item page and **Update** on the Prices screen queue the same step for that item. Each price remembers the BrickLink number and colour it was asked for.

Calls count against a daily budget per source (`BW_BRICKLINK_DAILY_BUDGET` and `BW_REBRICKABLE_DAILY_BUDGET` set the limits; Brickset allows 100 a day). When a day's budget is used up, or a source asks you to slow down, the job waits and carries on by itself; a price that already arrived is not asked for again.

A collection moved from 3.3 may also hold Brickset's **New** and **Used** values for its sets. Brick Work 3.3 read them from Brickset's website; Brickset's API, which Brick Work uses now, has no such values, so they are never refreshed. The item page lists them under **Price records** marked *legacy · Brickset 3.3, not refreshed*, and an **Estimate** that comes from one says *legacy*. Current market prices are BrickLink's, above, and **Set estimate** on a copy sets your own.

## Fetch from Rebrickable

A number that is in neither the catalogue nor your collection shows **Not in the catalogue** on its Add row with two ways out, side by side: **Fetch from Rebrickable** (greyed with "needs a Rebrickable key" when no key is set) and **Add as unidentified**, plus **Skip**. Nothing is added until you choose one; the row never guesses. An unidentified item is a local item with the name you typed and works on every screen; link it to a BrickLink number or merge it into a catalogue item later.

Add a set Brick Work does not know yet (newer than your catalogue), and the row offers **Fetch from Rebrickable** when a Rebrickable key is set. It queues one job: the set, its parts and its figures (three calls and one more for each figure the catalogue lacks).

When the job is done the copies you asked for are made, with the condition, completeness and note you chose, from the list it fetched; a wish row makes the wish. The job's progress line says **Fetched · 2 copies added**. **Undo** on the Add page takes them back. If the job fails, nothing is added and the line says **Fetch failed · nothing was added**; **Retry** queues it again and the copies follow when it succeeds.
