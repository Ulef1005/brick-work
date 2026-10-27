# Settings and maintenance

*Since 4.0.*

Do this to change how Brick Work behaves (the retail country, where pictures come from, how old a price may be), to look after the catalogue and your keys, and to keep the collection healthy. Everything is under **Manage → Tools & Admin**.

## Settings

**Tools & Admin → Settings** holds the preferences that are yours to choose. Change what you want and press **Save settings**. The page then says **Settings saved** with an **Undo** next to it; Undo puts back exactly what was there before, and is refused with **Item changed · undo the later save first** once you have saved again.

- **Currencies.** The currency amounts are shown in, and the exchange rates used to compare amounts in different currencies. A rate is per one euro. **Load ECB reference rates** fetches the European Central Bank's daily rates (no key); a rate you entered by hand is kept. Stored amounts never change currency.
- **Retail country.** DE, US, UK or CA: which LEGO price Brickset's retail figure uses.
- **Source priority.** For each step that calls a source (pictures, metadata, market price) and each kind of item, the sources to try, first to last, separated by commas. A blank kind uses the default list. The setting applies to jobs queued afterwards. See [Pictures, prices and where they come from](pictures-and-prices.md).
- **Freshness.** Days before a source's data counts as stale, per source and kind of data. Empty means it never goes stale. A fresh install starts with prices 30 days, metadata 365 days and pictures never. **Bulk refresh prices** lists what is stale by these rules.
- **Pictures.** How many of the things you hold have a picture and from which source. **Refresh pictures** queues a job for the missing pictures, or for every item; the dialog says how many items that is before you confirm. There is no Undo for a refresh, and existing files are kept.

The BrickLink region and currency and the repair settings of Complete sets are set where they are used (the [command line](../reference/cli.md#settings) and the planning screens).

## Catalogues & keys

**Tools & Admin → Catalogues & keys** shows each source with its daily budget, its last success and its last error, and a switch to turn a source off. A card per key lets you enter a key: it is write-only, tested once and stored encrypted, and it is never shown again. **Replace** and **Remove** are there afterwards, and **Undo** right after a removal.

The **Catalogue** card says what the catalogue file beside your collection holds, when it was built and last reconciled, and whether the optional BrickLink item lists are loaded. The catalogue is built on the server, not in the browser. When it is missing, or has not been activated yet (for example after copying `catalogue.db` in by hand), the card shows the command to run:

```text
python -m brickwork.store4 --data DATA_FOLDER catalogue download
python -m brickwork.store4 --data DATA_FOLDER catalogue import
python -m brickwork.store4 --data DATA_FOLDER catalogue reconcile
```

`download` fetches Rebrickable's files (they ask for at most one download a day), `import` builds the catalogue from them and activates it, and `reconcile` activates a catalogue that is in place already. To add the BrickLink item lists, run `brickwork catalogue import bricklink --from FOLDER`. See [Commands](../reference/cli.md#catalogue).

## Values

**Values** edits the lists the forms offer: owners, statuses, tags, storage locations and purchase places. Rename a value in place; **Archive** hides it from the forms and keeps what refers to it. A value Brick Work uses itself (such as the status that marks a set as checked) is listed but cannot be renamed or archived. A storage location can only be archived when it holds nothing; its own page, **Open location · moves and Undo**, moves things out and undoes the archive.

## Jobs and Bulk refresh prices

**Jobs** lists the newest jobs with their steps. A failed step has **Retry**; a job that was running when the app stopped has **Resume**. **Bulk refresh prices** queues a price job for every held or wanted item whose price is stale, and needs the BrickLink key.

## Instruction files

A PDF is attached to a **set**; a booklet shows the files of the set with its number. **Upload a PDF** takes a set number (or a booklet's number, which names the same set) and a label; **Fetch missing** only refreshes the identity of booklets that have no PDF and downloads nothing.

## Database

**Run integrity check** checks the collection file and the catalogue file and keeps the result, with its time, on the page. **Export database** downloads a consistent copy of the collection (never your keys). See [Back up and restore](back-up-and-restore.md).

## API tokens

**API tokens** creates and revokes the tokens scripts and assistants use. A new token's secret is shown once. After a revoke the banner offers **Undo** for 10 minutes. See [Connect an assistant](connect-an-assistant.md).

## What next

- [Undo a change](undo-a-change.md) for what can be taken back.
- [Pictures, prices and where they come from](pictures-and-prices.md) for the sources behind the settings.
- [Commands](../reference/cli.md) for `brickwork settings`, `brickwork catalogue` and `brickwork check`.
