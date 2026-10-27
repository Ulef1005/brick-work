# Undo a change

*Since 0.5.0.*

Do this when you saved something by mistake: a wrong count, a copy archived too early, a batch added to the wrong lot. Brick Work records every change as an event, and most events can be undone.

## In the app

Undo appears where you made the change:

- **Right after a save.** The notice that confirms a save ends in **Undo** on item pages, in **Manage → Add**, in **Part to Inventory** and in **Check Set Parts**. On an item page the Undo stays offered while that browser tab is open, also after a reload.
- **On the planning screens.** After a pin or a change to the repair settings on Complete sets, and after any change to the lists on the Wishlist, **Undo** appears next to the message at the top of the page.
- **In a history list.** **Part Picker** and **Matcher** list **Recent saves**. A storage location's page has **History**, and an order has **Allocation history**. Each row that can still be undone has an **Undo** button; rows already undone say **Undone**.
- **For tokens.** After you revoke an API token, the banner offers **Undo** for 10 minutes.

Press **Undo**. The change is reversed and recorded as a new event. An Undo cannot be undone itself; make the change again instead.

### When Undo is refused

Undo puts back the state from before your save, so it first checks that nothing has changed since. If a later save touched the same rows, Brick Work refuses with a message such as **Item changed · undo the later save first**. Undo the later change first, then this one. Check Set Parts says **This answer changed elsewhere. Reload before undoing.**

### What Undo can't take back

- Import jobs, price lookups and pictures already stored. Picture refresh says so: **No Undo for picture refresh**. The copies a **Fetch from Rebrickable** made are the exception: Undo on the Add page takes them back like any other Add row.
- Requests already spent from a source's daily budget, such as Brickognize identifications.
- Changes sent to Rebrickable or Brickset with collection sync. Undo in Brick Work cannot reach the other site.
- A database check, and an Undo itself.

Archiving is not deleting. An archived copy, list, location or value stays in the database, and Undo restores it.

## Through the API

Every write through the API returns an `event_id` and, when the change can be undone, an `undo_url`:

```json
{"data": {"...": "..."}, "event_id": 4812, "undo_url": "/api/v1/events/4812/undo", "idempotent_replay": false}
```

To undo it, send `POST` to that URL with no body, a token with the `write` scope and an `Idempotency-Key` header:

```sh
curl -X POST http://127.0.0.1:3333/api/v1/events/4812/undo \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Idempotency-Key: $(uuidgen)"
```

One endpoint undoes every kind of change, including changes made in the app. Find their ids with `GET /api/v1/events`, which marks each event `undoable` and `undone`.

The answers:

- `200` with `already_undone: false`: the change is reversed.
- `200` with `already_undone: true`: it was undone before; nothing happens.
- `409 undo_blocked`: a later change touched the same rows. The message names what to undo first.
- `409 not_undoable`: this event is not a change that can be undone.

An API write that changed several things at once is one event, and its Undo reverses all of them. In the app's history lists such a row says **Undo reverses all N receipts in this API operation**. Undoing a token, source key or source change needs the `admin` scope, as making it did.

Assistants connected over MCP get the same with the `undo_event` tool.

## What next

- [Back up and restore](back-up-and-restore.md) before a change too large to undo row by row.
- [Connect an assistant](connect-an-assistant.md) to create a token.
- [Receive an order](receive-an-order.md) for allocation Undo in context.
- [Commands](../reference/cli.md): `brickwork wishlist undo` takes back a wishlist change from the command line.
