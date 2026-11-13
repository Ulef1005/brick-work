---
audience: user
verified: 1.0
---

# Mark a sticker

*Since 1.1.0.*

The photo shows only the base part under a sticker, so the print is a clue only you can read. Mark the part as having a sticker; later you pick the sticker, and set detection uses it.

## When you file the part

1. In **Workbench → Part Spotter**, on the review step of a piece, turn on **Has a sticker** (under Quantity). The button reads **Confirm · White ×1 · sticker**.
2. File the batch as usual. The stock line gets the tag **Sticker**. (Filing again the same part, colour, condition and lot adds to the same line, and the tag covers all its pieces.) Undo of the batch takes the tag back.

## Choose the sticker

1. Open the lot. A flagged part shows **Sticker · not chosen** and **Which sticker?**.
2. The chooser lists the sets that hold this part in its colour and a sticker sheet. The catalogue does not say which part a sticker goes on, so this is a list of possibilities, not a fact. Sets with a sheet picture come first; **Show all** lists the rest.
3. Select **This one** on the set you recognise. The part now reads **Sticker · set 1682-1** with **Change**. Choosing is one step, and **Undo** appears on the page you return to.
4. **Keep as a hint** closes the chooser and leaves the part open. **Not a sticker** removes the tag.

## What it does to set detection

An open sticker raises, a little, the sets that hold the part and a sticker sheet. A chosen sticker counts as strong evidence for its set, and the set's reasons say "sticker of set 1682-1 confirmed." A flagged part is never left out as a common part. Details: [Set scoring](../reference/set-scoring.md). Read-only instances show the lists but no buttons.

The API has the same: `GET /api/v2/lots/{id}/stock/{stock_id}/stickers`, `POST` and `DELETE` on `.../sticker`, and the tools `list_sticker_candidates`, `confirm_sticker` and `clear_sticker`. See [Find the sets in a bulk lot](find-the-sets-in-a-bulk-lot.md).
