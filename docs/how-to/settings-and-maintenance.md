---
audience: user
verified: 1.0
---

# Settings and maintenance

*Since 0.6.0.*

Do this to change how Brick Work behaves (the retail country, where pictures come from, how old a price may be). Also do it to look after the catalogue and your keys, and to keep the collection healthy. Everything is under **Manage → Tools & Admin**.

## Tools & Admin

The page is for things you do. Choices you make once are under **Settings**. From the top:

- **Get started.** A card with how many set-up steps are done. It is there only while set-up is open. Skipping the optional keys counts as done. When set-up is over the card is gone and the steps stay under **About → Set-up steps**.
- **Refresh.** Two cells. The first says how many prices are out of date and has **Refresh prices**, which opens **Bulk refresh prices**. It is the one main button on the page, and only while something is out of date. The second says how many pictures are missing and has **Refresh pictures**, which opens the picture refresh dialog. There you choose **Missing pictures only** or **Replace all** and the kinds of item to include, and you see how many items that is before you confirm. There is no Undo for a refresh, and existing files are kept. When there is nothing to do, the cells say **Prices are up to date** and **No pictures missing**. Without a BrickLink key the first cell says **Prices need a BrickLink key** and offers **Add a key**. On an install where changes are switched off, both buttons are disabled and say so. Below the cells, **Jobs** shows how many jobs there are.
- **Your collection.** Statistics, Collection sync, Unresolved items (with how many are to decide), Instruction files (with how many files you have) and **Owners, tags and places**.
- **Settings.** One row for each section of the Settings page, **Keys and sources** and **Appearance**.
- **Maintenance.** Collapsed. **Show 8 tools** lists Catalogue, BrickLink item lists, Mappings and coverage, Backup and database check, API tokens, Import from BrickTracker, Migration report and Part Spotter history.
- **About.** About Brick Work and, once the card is gone, Set-up steps.

## Settings

**Tools & Admin → Settings** holds the preferences that are yours to choose, in four sections. Each row shows its title and its current value on one line, so most visits need no row opened. Select a row to open it in place and change it. Only one row is open at a time. A link such as `Settings#pictures` opens the row it names, and the four section rows on **Tools & Admin** open the page at their section.

Some rows have their own **Save** button and save at once. They are **Display currency and rates** (the currency, each rate and **Load ECB reference rates**), **Address on printed labels** and the BrickLink switch in **Part list for a new set**. The other rows save together: **Country for retail prices**, **Group parts by**, **Lost Parts from Rebrickable** and **Largest instruction download**. So do the three expert rows: **Where pictures come from**, **Where set details and prices come from** and **When data counts as out of date**. Press **Save settings** in any of them and every change in those rows is saved. The page then opens the row you saved and says **Settings saved** with an **Undo** next to it. Undo puts back exactly what was there before. It is refused with **Item changed · undo the later save first** once you have saved again.

**Money and prices**

- **Display currency and rates.** The row reads like "EUR · 3 rates, ECB 14 Nov": the display currency, how many rates you have and where the newest one came from. Open it to set the currency amounts are shown in, and the exchange rates used to compare amounts in different currencies. A rate is per one euro. **Load ECB reference rates** fetches the European Central Bank's daily rates (no key); a rate you entered by hand is kept. Stored amounts never change currency.
<!-- vale Microsoft.We = NO -->
- **Country for retail prices.** DE, US, UK or CA: which retail price Brickset's figure uses.
<!-- vale Microsoft.We = YES -->

**Sets and parts**

- **Group parts by.** The row says how parts are grouped, and how many categories you moved. Open it for **Grouped categories**, **BrickLink categories** or **No grouping**, how groups collapse, and **Edit grouping**. See [Part lists](part-lists.md).
- **Part list for a new set.** The row says whether BrickLink's list is preferred. Open it for **Prefer BrickLink's part list for new copies**. When it is on, a new copy of a set starts on Rebrickable's list and switches to BrickLink's list as soon as it arrives. A set's own pinned choice still comes first. The switch needs a BrickLink key: without one it is off and says so, with a link to **Keys and sources**. It has its own **Save** button and saves at once, with no Undo; turn it off again the same way.
- **Lost Parts from Rebrickable.** The row names the rule in use. Which count a Rebrickable pull keeps when it brings in your Lost Parts. **Add only** adds missing marks and keeps the larger count, and clears nothing. **Rebrickable wins per part** (the default) lets Rebrickable's count replace yours for each part it lists as lost, also when it is smaller, and leaves the other marks alone. **Rebrickable wins per set** makes a set that has Lost Parts on Rebrickable exactly Rebrickable's list, so its other missing marks are cleared. **Rebrickable wins everywhere** does that for every synced set, so a set with no Lost Parts there loses its missing marks. The pull preview says how many marks it will clear before you pull. Undo takes them back. From the command line: `brickwork settings set rebrickable_lost_parts_rule per_part`. See [Lost Parts from Rebrickable](sync-collection.md#lost-parts-from-rebrickable).

**Labels and instructions**

- **Address on printed labels.** The address, or "Uses the request address" when it is empty. See [Storage labels](storage-labels.md).
- **Largest instruction download.** The Official file limit, initially 500 MB per file. See [Instruction download limit](#instruction-download-limit).

**Where data comes from** is for experts and starts collapsed. **Show 4 settings** opens it.

- **Pictures you have.** The row says how many of the things you hold have a picture and how many have none. Open it for the counts per kind of item and source and the items that cannot be identified. It also links to the import jobs and to **Refresh pictures** on **Tools & Admin**.
- **Where pictures come from.** The row lists the sources for parts in order. Open it to see where Brick Work looks for a picture, first to last: for **Parts**, and for **Everything else**. Each list names the three sources in plain words (the Rebrickable catalogue, BrickLink, the Rebrickable API). Use the switch to leave a source out and the arrows to move it, then press **Save settings**. The first source that has a picture wins. The setting applies to jobs queued afterward. See [Pictures, prices and where they come from](pictures-and-prices.md).
- **Where set details and prices come from.** The row says **Default order**, or how many kinds of item differ from it. For the other steps that call a source (set details, prices) and each kind of item, the sources to try, first to last, separated by commas. A blank kind uses the default list.
- **When data counts as out of date.** The row gives the days for prices, set details and pictures. Days before a source's data counts as stale, per source and kind of data. Empty means it never goes stale. A fresh install starts with prices 30 days, set details 365 days and pictures never. **Bulk refresh prices** lists what is stale by these rules.

Settings stays one column, because a row opens below itself.

The BrickLink region and currency and the repair settings of Complete sets are set where they are used (the [command line](../reference/cli.md#settings) and the planning screens).

## Catalogues & keys

**Tools & Admin → Settings → Keys and sources** opens **Catalogues & keys**. It shows each source with its daily budget, its last success and its last error, and a switch to turn a source off. A card per key lets you enter a key: it is write-only, tested once and stored encrypted, and it is never shown again. **Replace** and **Remove** are there afterward, and **Undo** right after a removal.

### Getting keys

Keys are optional, and each service's own terms apply. Brickognize needs no key.

- **BrickLink** gives API access to registered sellers. Each access token is tied to one registered static IP address, so register the address your server calls from.
- **Rebrickable** asks for about one request per second. Brick Work's own daily cap for it is `BW_REBRICKABLE_DAILY_BUDGET`.
- **Brickset** keys allow 100 `getSets` calls a day unless Brickset raises the limit for you.

The **Catalogue** card says what the catalogue file beside your collection holds, when it was built and last reconciled, and whether the optional BrickLink item lists are loaded. The pages below do the rest from the browser.

## Catalogue

**First run.** An empty install shows **Nothing here yet** on **Sets**. **Download the catalogue** there needs no key and no login. As a background job with a progress bar, it fetches Rebrickable's twelve files (about 17 MB) and builds the catalogue. It also creates your collection file if it is missing and switches the catalogue on. It takes about a minute: 51 s on a Raspberry Pi 5, most of it building the catalogue. Rebrickable asks for at most one download a day, so if today's files are on disk already the button reads **Build from today's files** and fetches nothing. When it is done, **Add a set** opens: add a set by its number and open **Set Inspector**. Keys are optional; they bring prices and part lists for sets newer than the catalogue. A catalogue file that is beside the collection but not switched on yet shows **Activate the catalogue**.

The first run is one flow of four steps:

1. **Load the catalogue**
2. **Set up your keys** (optional)
3. **Bring your collection in** (see [Bring your collection in from another app](migrate.md))
4. **See how the inventory works**: five short cards on sets and copies, completeness, loose stock and lots, the workflows at the table and an assistant. Each card links to its screen.

**Got it** at its end marks it read. Each step shows whether it is done, where the flow picks up, or what it waits for: bringing your collection in waits for the catalogue. **Skip for now** sets a step aside, and **Back into the flow** takes it back. Once your collection holds something, the flow lives on **Tools & Admin › Get started**, with how many steps are done, and it resumes at the first open step. When set-up is over, it is under **About › Set-up steps**. A step counts as done only when it happened. That means a catalogue is switched on, a key is stored, the collection holds a copy or loose stock, or the guide was read. Skipped steps are remembered in `onboarding.json` beside the collection file. **What the catalogue is**, under the first step, says what the catalogue holds and how Brick Work ids relate to the BrickLink, Rebrickable and Brickset numbers. It also says what comes later: pictures, prices and newer sets. Once the catalogue is active, the step shows how many items and colours it holds and the date of Rebrickable's files it came from. A download keeps running when you leave the page; coming back shows its progress, and a failed one shows the error and the button to try again. On **Get started**, the keys step has a card per source, as on **Catalogues & keys**. Each card has what the key gives you, a link to the site's page where you make it, the fields and **Test and save**. For a saved key it has **Test key**, **Replace** and **Remove**. A rejected key shows the site's reason on its card. Every key action comes back to the flow. Until a key is stored the step says what is missing without one: prices, and part lists for sets newer than the catalogue.

**Tools & Admin → Maintenance → Catalogue** shows the current catalogue under **Current build**. It shows when it was built, the date of the Rebrickable download it came from and how many items and colours it holds. It also shows how many retired items it keeps (items that left Rebrickable's files keep their ids), and when your collection was last reconciled with it.

- **Re-download** fetches Rebrickable's twelve files again (about 17 MB, no login) and builds the catalogue from them, then reconciles your collection. Rebrickable asks for at most one download a day: if today's files are on disk already, they are used instead.
- **Rebuild** builds the catalogue again from the files already downloaded, with no network. The current file is moved aside as `catalogue.db.damaged-DATE`, never deleted. It is disabled until a download is on disk.

Both run in the background. The page shows a progress bar and the step it is on, and you can leave it: the result is there when you come back. Only one job runs at a time; the buttons come back when it finishes. If a job fails, the page says why in plain words. Folder names are cut to the file name, and an unexpected error says only that the details are in the server log. The catalogue that was in place before stays in place.

When a job is done the page lists what changed (items, colours, retired items kept, names refreshed, links upgraded). It also lists the **copies whose part list changed** against the new catalogue, each as "Set 2 · 1 list changed" with a link to that copy. Nothing switches on its own: open the copy to see the change and switch it.

**Reconcile** brings your collection up to date with the catalogue (names, links, kinds, part lists to check). It writes only your collection. If the new catalogue is in place but the collection has not been reconciled yet, the page says **Not reconciled yet**. Brick Work reconciles at the next start by itself, as a job you can see under **Jobs**; **Reconcile now** does it straight away.

## BrickLink item lists

**Tools & Admin → Maintenance → BrickLink item lists** is optional. BrickLink's own catalogue lists confirm BrickLink numbers for sets, offer same-number candidates and correct the kind of zero-part sets. Loading them adds no item by itself. They also help **Orders**. An order e-mail's item names are matched against BrickLink's names. A line naming an item only BrickLink has (an instruction booklet, some sticker and printed parts) becomes an item of Brick Work's own when the order is read (#154). See [Receive a parts order](receive-an-order.md). Put BrickLink's catalogue XML files (all eight item types) in a folder under `bricklink-lists/` beside your collection, choose the folder and press **Load lists**.

The page keeps the last load: how many items were listed and how many links were upgraded. It also shows how many **candidates to check** there are (open **Unresolved items** to decide them) and how many kinds were corrected. A candidate is never confirmed on its own.

## Mappings and coverage

**Tools & Admin → Maintenance → Mappings and coverage** shows where BrickLink numbers come from. Your own links come first, then the BrickLink lists, then the local mapping files in `mappings/` beside your collection. Then come the files that ship with the app and the rules. It lists the shipped and local files with their rows and version.

Two figures say how well that covers your collection: how many of your items have a BrickLink number, and how many part and colour pairs have a known picture. Each is a count and a bar. The items figure appears after the first reconcile.

For the commands that do the same work on the server, see [Commands](../reference/cli.md#catalogue).

## Migration report

After a move from 3.3, **Tools & Admin → Maintenance → Migration report** reads the report the migration wrote:

- The summary.
- Whether the proof passed (each part of the proof with what it checked).
- The identity matches you decided by hand.
- Every report file with its row count and a **Download** link.

It shows whether the report's digest matches the one recorded in your collection. The report is read from `migration-report/` beside your collection, or from the folder in `BW_MIGRATION_REPORT` ([Settings reference](../reference/settings.md)). With no report there, the page says so.

## Values

**Tools & Admin → Owners, tags and places** (the **Values** page) edits the lists the forms offer: owners, statuses, tags, storage locations and purchase places. Rename a value in place; **Archive** hides it from the forms and keeps what refers to it. A value Brick Work uses itself (such as the status that marks a set as checked) is listed but cannot be renamed or archived. A storage location can only be archived when it holds nothing; its own page, **Open location · moves and Undo**, moves things out and undoes the archive.

## Statistics

**Tools & Admin → Statistics** counts your live copies four ways: by completeness, by theme, by storage and by purchase place. The headline says how many copies are incomplete ("9 of 25 copies are incomplete"). Each chart's title states its point ("Only 5 copies are complete" or "Harbour is the biggest theme, 3 copies"). When rows tie for the lead the title says so ("Icons and Police lead, 2 copies each" or "3 places share the lead, 5 copies each"). Every bar is one line, label, bar and value, and all four charts share one scale, copies starting at zero, so bars compare across charts. Completeness is in status order (Complete, Incomplete, Not checked, Sealed); the others run from most to fewest copies. After six rows the rest folds into one outlined row, for example **14 more themes**, with their summed copies. Below the charts, a card compares what you paid with LEGO's retail price. Under it, **Paid vs value** compares what you paid with what the copies are worth now. It starts with a title that states the point ("Worth €4,312.00 against €3,177.32 paid"). Next are the totals, the gain and the number of copies without a price paid. Then come two bar lists, **By theme** and **By purchase year**. Each shows the paid amount as an outline bar and the worth as a solid bar on one scale from zero. The gain is written at the end of the row. With fewer than three copies that have both a price paid and a worth it says **Charts need more data**. With no price paid on any copy it shows the worth alone. With no sold prices it offers **Update prices**. Amounts are in your display currency, and a note gives the date of the rates when something was converted. **Insurance report** opens the page described in [Make an insurance report](insurance-report.md).

## Jobs and Bulk refresh prices

**Jobs** lists the newest jobs with their steps. A failed step has **Retry**; a job that was running when the app stopped has **Resume**. While a job or bulk action is queued, running or waiting, the page keeps itself current every few seconds. States, step counts, progress bars and new jobs appear without a reload, and your search and filters stay. When nothing changes for a while (a job waiting for a daily budget, an interrupted job) it looks less often, up to once a minute. Once everything has settled it still looks once a minute for jobs started elsewhere. It does not look while the tab is in the background. **Refresh prices** in the **Refresh** block of **Tools & Admin** opens **Bulk refresh prices**. It queues a price job for every held or wanted item whose price is stale, and needs the BrickLink key.

A bulk action (**Bulk refresh prices**, **Refresh pictures**, fetching missing booklets) is one row under **Bulk actions** at the top of **Jobs**. The row shows how many of its items are done, failed, cancelled and still to go, and a progress bar. When it waits for a source's daily budget, it shows until when. **… failed · why** lists the items that failed with the reason (the first 50). **Cancel** stops the items not started yet; the one running finishes, and a cancelled item is not retried. While a bulk action runs, your own work goes first. An Add's import, its part list and a single **Update price** run before the next item of the batch. So a new set gets its picture and price in seconds, not after the whole refresh. The daily budgets of each source hold for the batch's items as for any job. A step that only lacks a key (no BrickLink key for a price, no Brickset key for set data) is not a failure. It shows **Waiting for a key · runs once it is stored**. Storing the key, or starting Brick Work with the key in its environment, runs it. A key the site refuses fails the step, with the site's reason.

## Instruction files

A PDF is attached to a **set**; a booklet shows the files of the set with its number. **Upload a PDF** takes a set number (or a booklet's number, which names the same set) and a label. **Find instructions** opens candidate discovery and downloads nothing until you confirm ticked files. No instruction source is set up yet. See [Find and download instructions](add-a-box-or-instructions.md#find-and-download-instructions).

## Database

**Tools & Admin → Maintenance → Backup and database check** opens the **Database** page. **Run integrity check** checks the collection file and the catalogue file and keeps the result, with its time, on the page. **Export database** downloads a consistent copy of the collection (never your keys). See [Back up and restore](back-up-and-restore.md).

## API tokens

**Tools & Admin → Maintenance → API tokens** creates and revokes the tokens scripts and assistants use. A new token's secret is shown once. After a revoke the banner offers **Undo** for 10 minutes. See [Connect an assistant](connect-an-assistant.md).

## What next

- [Undo a change](undo-a-change.md) for what can be taken back.
- [Pictures, prices and where they come from](pictures-and-prices.md) for the sources behind the settings.
- [Commands](../reference/cli.md) for `brickwork settings`, `brickwork catalogue` and `brickwork check`.

## Instruction download limit

**Settings → Labels and instructions → Largest instruction download** controls the Official file limit, initially 500 MB. Values range from 1 to 5000 MB.
Uploads and other instruction sources retain their 20 MB limit.
