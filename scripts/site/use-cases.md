# Use cases

Brick Work is for private collectors who want the collection to help them finish what they started. Each case below says what you do and which part of the app does it. For the steps, see the [workflows](../workflows/), or try them in the [demo](../demo/).

## Finish the set you started

You built half a set years ago and do not know what is missing. Open the copy, run **Check Set Parts** against its inventory and note the shortfall as you go. The missing parts become a list you can act on, with a count of how far along the copy is.

## Build from your bulk

You have boxes of sorted loose parts and several unfinished sets. **Part Picker** takes the sets you tick and lists the missing parts you can pull from your own stock, in your own sort order, so one pass through the drawers serves many sets. **Matcher** shows which incomplete copies your loose stock can finish outright.

## Receive a parts order

A BrickLink order arrives. Import it from your BrickLink account, paste the confirmation email, or upload the order XML; a line that is already imported is never added twice. Count the parts as they come out of the bag and allocate them to the sets that need them. This is **Orders**.

## Decide what to buy

Open **Wishlist**, **Prices** and **Complete sets** to see which sets are worth finishing. Part-out values show only when at least 90% of a set's lines have a price, and one action fetches prices for the parts that lack one.

## Bring an old collection over

Run the read-only importer on your previous tracker database, review the row-count and checksum proof, then point Brick Work at the new database. The old database is never changed.

## Keep it in one place

Sets, minifigures, loose parts, instructions and boxes are all items with the same fields: storage location, notes, prices and history. Every change is recorded and can be undone.

## Ask an assistant about your collection

Connect an AI assistant over MCP and ask which sets are closest to complete or what is stored in a box. The assistant reads with a read-only token; write tools stay off unless you enable them and the token allows them. See the [MCP guide](../mcp/).

## Script your collection

Export for a spreadsheet, add sets from a script, or hook the collection into your own tools with the versioned [REST API](../api/). Creates need an idempotency key, so a retried request cannot add twice.

## What is not here yet

Buildable sets, collection sync with Rebrickable, BrickLink and Brickset, and a pile check by photo are planned and not built. They are tracked on the [public roadmap](https://github.com/users/Ulef1005/projects/3).
