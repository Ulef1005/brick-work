# Settings and maintenance

*Since 0.6.0.*

Do this to change how Brick Work behaves (the retail country, where pictures come from, how old a price may be), to look after the catalogue and your keys, and to keep the collection healthy. Everything is under **Manage → Tools & Admin**.

## Settings

**Tools & Admin → Settings** holds the preferences that are yours to choose. Change what you want and press **Save settings**. The page then says **Settings saved** with an **Undo** next to it; Undo puts back exactly what was there before, and is refused with **Item changed · undo the later save first** once you have saved again.

- **Currencies.** The currency amounts are shown in, and the exchange rates used to compare amounts in different currencies. A rate is per one euro. **Load ECB reference rates** fetches the European Central Bank's daily rates (no key); a rate you entered by hand is kept. Stored amounts never change currency.
- **Retail country.** DE, US, UK or CA: which LEGO price Brickset's retail figure uses.
- **Part lists.** **Prefer BrickLink's part list for new copies.** When it is on, a new copy of a set starts on Rebrickable's list and switches to BrickLink's list as soon as it arrives; a set's own pinned choice still comes first. The switch needs a BrickLink key: without one it is off and says so, with a link to **Catalogues & keys**. It has its own **Save** button and saves at once, with no Undo; turn it off again the same way.
- **Picture source order.** Where Brick Work looks for a picture, first to last: for **Parts**, and for **Everything else**. Each list names the three sources in plain words (the Rebrickable catalogue, BrickLink, the Rebrickable API). Use the switch to leave a source out and the arrows to move it, then press **Save settings**. The first source that has a picture wins. The setting applies to jobs queued afterwards. See [Pictures, prices and where they come from](pictures-and-prices.md).
- **Source priority.** For the other steps that call a source (metadata, market price) and each kind of item, the sources to try, first to last, separated by commas. A blank kind uses the default list.
- **Freshness.** Days before a source's data counts as stale, per source and kind of data. Empty means it never goes stale. A fresh install starts with prices 30 days, metadata 365 days and pictures never. **Bulk refresh prices** lists what is stale by these rules.
- **Pictures.** How many of the things you hold have a picture and from which source. **Refresh pictures** queues a job for the missing pictures, or for every item; the dialog says how many items that is before you confirm. There is no Undo for a refresh, and existing files are kept.

The BrickLink region and currency and the repair settings of Complete sets are set where they are used (the [command line](../reference/cli.md#settings) and the planning screens).

## Catalogues & keys

**Tools & Admin → Catalogues & keys** shows each source with its daily budget, its last success and its last error, and a switch to turn a source off. A card per key lets you enter a key: it is write-only, tested once and stored encrypted, and it is never shown again. **Replace** and **Remove** are there afterwards, and **Undo** right after a removal.

The **Catalogue** card says what the catalogue file beside your collection holds, when it was built and last reconciled, and whether the optional BrickLink item lists are loaded. The pages below do the rest from the browser.

## Catalogue

**First run.** An empty install shows **Nothing here yet** on **Sets**. **Download the catalogue** there needs no key and no login: it fetches Rebrickable's twelve files (about 17 MB), builds the catalogue, creates your collection file if it is missing and switches the catalogue on, as a background job with a progress bar. Rebrickable asks for at most one download a day, so if today's files are on disk already the button reads **Build from today's files** and fetches nothing. When it is done, **Add a set** opens: add a set by its number and open **Check Set Parts**. Keys are optional; they bring prices and part lists for sets newer than the catalogue. A catalogue file that is beside the collection but not switched on yet shows **Activate the catalogue**.

**Tools & Admin → Catalogue → Build** shows the current catalogue: when it was built, the date of the Rebrickable download it came from, how many items and colours it holds, how many retired items it keeps (items that left Rebrickable's files keep their ids), and when your collection was last reconciled with it.

- **Re-download** fetches Rebrickable's twelve files again (about 17 MB, no login) and builds the catalogue from them, then reconciles your collection. Rebrickable asks for at most one download a day: if today's files are on disk already, they are used instead.
- **Rebuild** builds the catalogue again from the files already downloaded, with no network. The current file is moved aside as `catalogue.db.damaged-DATE`, never deleted. It is disabled until a download is on disk.

Both run in the background. The page shows a progress bar and the step it is on, and you can leave it: the result is there when you come back. Only one job runs at a time; the buttons come back when it finishes. If a job fails, the page says why in plain words (folder names are cut to the file name, and an unexpected error says only that the details are in the server log), and the catalogue that was in place before stays in place.

When a job is done the page lists what changed (items, colours, retired items kept, names refreshed, links upgraded) and the **copies whose part list changed** against the new catalogue, each as "Set 2 · 1 list changed" with a link to that copy. Nothing switches on its own: open the copy to see the change and switch it.

**Reconcile** brings your collection up to date with the catalogue (names, links, kinds, part lists to check). It writes only your collection. If the new catalogue is in place but the collection has not been reconciled yet, the page says **Not reconciled yet**. Brick Work reconciles at the next start by itself, as a job you can see under **Jobs**; **Reconcile now** does it straight away.

## BrickLink item lists

**Tools & Admin → Catalogue → BrickLink lists** is optional. BrickLink's own catalogue lists confirm BrickLink numbers for sets, offer same-number candidates and correct the kind of zero-part sets. Loading them never adds an item. Put BrickLink's catalogue XML files (all eight item types) in a folder under `bricklink-lists/` beside your collection, choose the folder and press **Load lists**.

The page keeps the last load: how many items were listed, how many links were upgraded, how many **candidates to check** there are (open **Unresolved items** to decide them) and how many kinds were corrected. A candidate is never confirmed on its own.

## Mappings and coverage

**Tools & Admin → Catalogue → Mappings** shows where BrickLink numbers come from: your own links first, then the BrickLink lists, then the local mapping files in `mappings/` beside your collection, then the files that ship with the app and the rules. It lists the shipped and local files with their rows and version.

Two figures say how well that covers your collection: how many of your items have a BrickLink number, and how many part and colour pairs have a known picture. Each is a count and a bar. The items figure appears after the first reconcile.

For the commands that do the same work on the server, see [Commands](../reference/cli.md#catalogue).

## Migration report

After a move from 3.3, **Tools & Admin → Migration report** reads the report the migration wrote: the summary, whether the proof passed (each part of the proof with what it checked), the identity matches you decided by hand and every report file with its row count and a **Download** link. It shows whether the report's digest matches the one recorded in your collection. The report is read from `migration-report/` beside your collection, or from the folder in `BW_MIGRATION_REPORT` ([Settings reference](../reference/settings.md)). With no report there, the page says so.

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
