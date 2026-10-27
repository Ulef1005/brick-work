# Pictures, prices and where they come from

*Since 4.0.*

Do this to understand why an item has a picture or a price, to change where pictures come from, or to fetch a set Brick Work does not know yet. Pictures and prices are cached copies: nothing in them is your data, and every one can be fetched again.

## What happens when you add something

Each row you confirm in **Manage → Add** gets one background job with six steps. Three of them reach out to other sites:

| Step | What it fetches | Needs a key |
|---|---|---|
| Downloading images | The item's picture, once per colour for a part you hold in several colours. | Only the Rebrickable API source does. |
| Fetching set metadata | Brickset's theme, piece count and years of sale for a set, and the retail price in your retail country. | A Brickset key. |
| Fetching market price | BrickLink's price guide for new and used, in your region and currency. | The four BrickLink values. |

An item with no number from any provider (an *unidentified* item) cannot be asked for anything. Its steps end **done** with the finding **unidentified**, nothing is called, and the job does not fail. Prices and the BrickLink export also skip an item BrickLink has no number for; add a link or merge it into a catalogue item to resolve it.

## Where pictures come from

Three sources, tried in this order:

- **For parts:** the Rebrickable catalogue (a plain image download for the colours the catalogue shows the part in), then BrickLink (a plain image download by the part's BrickLink number and colour), then the Rebrickable API.
- **For everything else:** BrickLink, then the Rebrickable catalogue. The catalogue carries pictures of parts only, so a set or figure is pictured by BrickLink unless you add the Rebrickable API to its order.

The first two need no key and make no API call. The Rebrickable API source needs your Rebrickable key and counts against the day's budget. A part in a colour the catalogue has no picture for falls through to BrickLink and then to the API. If no source can serve it, the step fails with the reason, and **Retry** on the job runs it again once something has changed.

Change the order in **Tools & Admin → Settings**; the setting applies to jobs queued afterwards. Updating from 3.3 keeps your order: the default becomes the one above, and a changed order keeps its sequence with Rebrickable split into the catalogue and then the API.

## Prices and budgets

Prices are fetched for every colour a part is held in, new and used, as BrickLink's sold average (or the listings when nothing sold). **Update price** on an item page and **Update** on the Prices screen queue the same step for that item. Each price remembers the BrickLink number and colour it was asked for.

Calls count against a daily budget per source (`BW_BRICKLINK_DAILY_BUDGET` and `BW_REBRICKABLE_DAILY_BUDGET` set the limits; Brickset allows 100 a day). When a day's budget is used up, or a source asks you to slow down, the job waits and carries on by itself; a price that already arrived is not asked for again.

## Fetch from Rebrickable

Add a set Brick Work does not know yet (newer than your catalogue), and the row offers **Fetch from Rebrickable** when a Rebrickable key is set. It queues one job: the set, its parts and its figures (three calls and one more for each figure the catalogue lacks).

When the job is done the copies you asked for are made, with the condition, completeness and note you chose, from the list it fetched; a wish row makes the wish. The job's progress line says **Fetched · 2 copies added**. **Undo** on the Add page takes them back. If the job fails, nothing is added and the line says **Fetch failed · nothing was added**; **Retry** queues it again and the copies follow when it succeeds.
