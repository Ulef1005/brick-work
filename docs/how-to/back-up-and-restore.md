# Back up and restore

*Since 0.5.0.*

Do this before an upgrade, before a large import, and on a regular schedule. A backup has two parts: the database snapshot and the media folder.

## Export the database

1. Open **Manage → Tools & Admin → Database**.
2. Press **Export database**.
3. Keep the downloaded `brickwork.db` somewhere outside the Brick Work folder.

The export is a consistent copy of the whole database, taken while the app runs. It is one SQLite file that opens on its own. You don't need to stop Brick Work first.

The export leaves out:

- **Your source keys.** BrickLink, Rebrickable and Brickset keys never leave the app, not even encrypted. Keep your keys somewhere safe so you can enter them again.
- **Media.** Pictures, thumbnails, your own photos, instruction PDFs and identification thumbnails are files, not database rows. See below.
- **The catalogue.** Rebrickable's catalogue is the separate file `catalogue.db` beside the database. It can be built again from Rebrickable's download, so it is not part of the export; keep `data/catalogue-src/` (the downloaded files, so a rebuild works offline) and `data/mappings/` (your own mapping files, if you have any) with the media.

Each export is recorded in the event log. On a read-only instance (`BW_READ_ONLY`) the export still works and records nothing.

### Through the API

`GET /api/v1/database/export` returns the same snapshot. It needs a token with the `admin` scope:

```sh
curl -H "Authorization: Bearer YOUR_ADMIN_TOKEN" -o brickwork.db \
  http://127.0.0.1:3333/api/v1/database/export
```

If known credentials would still be in the copy, the API refuses with `409` instead of sending it.

## Back up the media folder

Media lives in a `data/` folder under the media root: `data/images`, `data/thumbs`, `data/instructions` and `data/identifications` (your own photos are under `data/images/own`). The media root is `BW_MEDIA_PATH` if you set it, otherwise the folder that holds the database (`BW_DB_PATH`).

Copy those folders with your usual file backup. The database stores only relative paths, so the files must keep the same layout under `data/`.

Also keep your settings file (`data/.env`, or wherever you set your `BW_*` variables).

## Check the database

1. Open **Manage → Tools & Admin → Database**.
2. Press **Run integrity check**.

The check reads the whole file, so it runs only when you ask. Afterwards the page shows **Database checks passed** or **Database needs attention**, the time of the check, the integrity result of the collection and of the catalogue file, the number of foreign key findings, whether the two files belong together (**Collection and catalogue are a pair**, **Catalogue ids keep their born keys**, **Part lists exist in the catalogue**, **Digests agree**; a failure says what is wrong and the fix) and the rows in each table. The result stays on the page until the next check.

The same check is available elsewhere:

- On the server: `brickwork check` (with Docker: `docker compose exec brickwork brickwork check`). It prints the same checks and exits with an error status when one finds a problem. Run it after you restore: it shows that the collection and the catalogue file come from one archive.
- Through the API: `GET /api/v1/database/check`, with an `admin` token.

Only the check in the app keeps its result on the **Database** page. On a read-only instance **Run integrity check** is switched off; use `brickwork check` instead.

## Restore

Brick Work has no restore button, API call or command.

## What next

- [Undo a change](undo-a-change.md) to take back a single wrong edit.
- [Connect an assistant](connect-an-assistant.md) to create an `admin` token for scripted exports.
- [Settings](../reference/settings.md) for `BW_DB_PATH`, `BW_MEDIA_PATH` and `BW_READ_ONLY`.
- [Commands](../reference/cli.md) for `brickwork check`.
