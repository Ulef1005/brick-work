# Identify a minifigure from a photo

*Since 0.5.0.*

Do this when you hold a minifigure and want to know which one it is and whether you already own it.

Brick Work asks Brickognize, an outside recognition service. It sends only the photo you choose, resized to at most 1600 pixels; nothing from your collection goes with it. Each photo uses one request from the daily budget.

## Identify the figure

1. Open the jump search (**Jump to a set, copy, figure or part**, or ⌘K) and choose **What is this? · identify a part by photo**.
2. Under **Recognise**, choose **Minifigure**.
3. Press **Enable camera** and allow camera access. Place the figure inside the guide and press **Take picture** (or Space). Or press **Choose a saved photo**.
4. Brick Work lists the matches, best first. Each card shows the figure's number, its match score (0 to 1) and what you already have of it, or **Not in your collection**.

The camera needs a secure page (HTTPS or `localhost`); elsewhere only the saved photo is offered. A photo must be smaller than 8 MB.

Brick Work shows only matches it finds in the local BrickLink catalogue. If nothing matches, it says **Nothing identified · try another photo**.

## Accept a result

**What is this?** saves nothing. On the card that shows your figure, choose:

- **Open minifigure** opens the figure's page in your collection.
- **Add to stock** opens **Manage → Add** with the figure filled in as loose stock.
- **Fill a missing part** appears when copies of your sets are missing this figure. It opens the **Matcher**.

## Identify several figures and add them

1. Open **Workbench → Part to Inventory** and set **Identify** to **Figures**.
2. Take a picture of each figure (up to 6 in the queue).
3. For each one, check **Reference · best match**, or pick one of the **Other possibilities** (keys 1 to 9). Choose a colour and press **Confirm**.
4. On **Results**, press **Review inventory batch**, choose **Add to**, **Condition** and **Keep photos**, and save the batch.

The notice after saving offers **Undo**, which takes the figures out of stock and archives their identifications.

## Look back at saved identifications

Open **Manage → Tools & Admin → Identify history**. It lists saved identifications, newest first, with the candidates Brickognize offered and their match scores.

Only Part to Inventory batches and API identifications are saved; **What is this?** results are not. Archived ones are hidden.

## The daily budget

Brick Work allows 100 Brickognize requests a day by default. Change it with `BW_BRICKOGNIZE_DAILY_BUDGET`. Every photo counts, whether you keep the result or not; Undo does not give requests back.

**Manage → Tools & Admin → Catalogues & keys** shows Brickognize's **Budget today**. When it is used up, Brick Work sends no more photos until it resets at 00:00 UTC.

## Through the API

`POST /api/v1/identifications` takes one photo as the multipart field `file` and needs a token with the `write` scope. It returns the candidates with what you own of each and saves the result to the Identify history, with a 256-pixel thumbnail that keeps no photo metadata. `DELETE /api/v1/identifications/{id}` archives a result; its Undo restores it.

## What next

- [Undo a change](undo-a-change.md) if you added the wrong figure.
- [Connect an assistant](connect-an-assistant.md) to create the API token.
- [Back up and restore](back-up-and-restore.md): identification thumbnails sit with your other media, outside the database.
- [Settings](../reference/settings.md) for `BW_BRICKOGNIZE_DAILY_BUDGET`.
