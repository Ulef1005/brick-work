# Changelog

## Unreleased

- `main` is the 4.0 line: the app runs on the 4.0 store; API v1 answers 410 (except `/api/v1/health`) until API v2 (M.11).
- The collection lists, the item page, the wish, lot and purchase-place pages and the jump search run on the 4.0 store. An item page is `/collection/item/<id>`; the old number URLs redirect to it. Screens show the Rebrickable number first with the BrickLink number beside it where it differs, a BrickLink-only item marked, and an unidentified item by its name; search takes both numbers. Conditions and completeness are words on every screen.
- Check Set Parts and the collection's writes run on the 4.0 store: a check keeps its answers by part line, so switching a copy to another part list keeps a check in progress; checks in progress before 4.0 start again. Editing, archiving, restoring and Undo (one receipt per save), own photos and captions, new part lots and the loose-stock merge on edit work as before. A figure's own parts are checked at `/workbench/check-parts/<copy>/figure/<line>`. Own photos are served at `/manage/images/<id>`.
- The Workbench runs on the 4.0 store: Part Picker, Matcher (Give and Take), Found it, instruction booklets, Part to Inventory (the page, its save and Undo), Storage with its history, and the printable lists with their CSV. A move writes one receipt and a `stock_transfer` row naming it. Matching is by item: a part, a figure, or a set's booklet or box meets the loose stock of the same item and colour, and an item still marked to check is matched like any other (the **Needs a check** list is gone). Instruction booklets are added by the numbers of booklets you already hold or the BrickLink item list names. Photo recognition in Part to Inventory comes back with Identify.
- Pictures, prices and keys run on the 4.0 store. The import job fetches a picture (from the Rebrickable catalogue, BrickLink and the Rebrickable API, in the order of the setting; parts try the catalogue first), Brickset metadata and retail price, and BrickLink prices for every colour a part is held in; calls are counted per source and day. An item with no BrickLink number ends the price step as **unidentified** instead of failing. The Prices screen works by item id and its Update buttons queue the same step. **Fetch from Rebrickable** now makes the copies (or the wish) the Add row asked for when the job is done, with its own Undo, and says so on the Add page. Updating from 3.3 turns the default picture order into the new default and splits a changed one into the catalogue and the API. See [Pictures, prices and where they come from](docs/how-to/pictures-and-prices.md).
- Planning, wishlists and money run on the 4.0 store. **Complete sets** ranks the copies with a gap by what a repair gains per unit spent, from the cached BrickLink quotes and the repair settings; a pin and the settings are saved and undone as events. Its **Export** names every line by BrickLink number and colour; an item BrickLink has no number for is left out of the file and named in the message instead of stopping the export. The **Wishlist** screen, the named lists (create, move, copy, archive, restore, Undo) and the BrickLink XML and Rebrickable CSV exports work by item id; a wish that cannot be named in the chosen format is left out and listed in the export summary. A wish id is now a uuid. Part-out value, retail on the wishlist, wish progress, exchange rates (a rate or the ECB's, converted figures marked ≈) and manual prices (Undo voids the observation) work as before.
- Orders and Identify run on the 4.0 store. An order document (BrickLink XML, the store's e-mail, the BrickLink API) is placed line by line on items through the BrickLink type, number and colour number, looking in your collection's links and the catalogue together; a key that names several items is never guessed: the line stays unmatched, offers its candidates under **Could be**, and you choose. Review, counting, allocation to a copy's gap or to loose stock, hold, reconcile, the short list and the CSV export work as before; every save is one event with Undo, and an undone import keeps its document and lines as provenance. An order keeps its total and currency together, so an e-mail without a total leaves the order without a currency. A set line cannot be allocated to loose stock (add the set as a copy). **What is this?** and Part to Inventory recognise a photo through Brickognize and list a number that names several items apart instead of choosing one. **Manage → Add** takes a photo again: it offers the matches, adds nothing until you choose one, and keeps the photo only with **Keep photo**.
- Tools & Admin runs on the 4.0 store: **Settings** (currencies, retail country, the source order, freshness rules; a save is one event with **Undo**), **Catalogues & keys** (sources with their budgets, write-only key cards, and a Catalogue card that says what is loaded and names the command when the catalogue is missing or not activated), **Values**, **Jobs**, **Bulk refresh prices**, **Statistics**, **Database** (the check keeps its result as `maintenance:database_check`; the export is the collection file), **Instruction files** (a PDF belongs to a set; a booklet shows the files of the set with its number), **Identify history** and **API tokens**. A new collection starts with the freshness rules of 0.5. The catalogue is built on the server with `python -m brickwork.store4`, not from the browser; the app's `catalogue` command is the same operation. `brickwork migrate4` is `python -m brickwork.store4 migrate`; the `brickwork wishlist` commands take wish ids as text. The BrickLink catalogue XML loader and the colour load are gone with the catalogue builds. **Unresolved figures** (identity admin) is still to come.
- `GET /api/v1/health` also returns the app version (`app`), so monitors and update checks need one call.
- Error responses never carry database or operating-system error text (#76).
- **Security:** `certifi` 2026.10.19, outside the range of the emSign root CA advisory (#81).
- An API write that queues a catalogue import (adding a set, part or wish, or moving a wish to owned) now starts the import worker; before, the import waited until something in the web app started it (#121).

## Brick Work 0.5.0 (first public release) · 2026-10-18

The first public release: a self-hosted web app for a brick collection that helps at the table, not only in the inventory. It is pre-1.0; the schema and the API can still change between minor versions.

- **Collection:** sets, minifigures, parts, instructions and boxes, with copies, storage, purchase details, statuses, tags and notes, in one SQLite file. Every list is searchable, filterable and sortable.
- **Check Set Parts:** count a copy's parts at the table, in inventory, colour or largest-first order, with a missing pass, Undo and resume.
- **Part Picker:** choose unfinished sets and get the parts you can pull from your sorted loose stock; **Complete sets** shows which sets that stock can finish.
- **Matcher, Part to Inventory and What is this?:** match loose stock to the sets that need it, and identify parts and minifigures from a photo (Brickognize) with what you already own of them.
- **Orders:** import a BrickLink order, an email or an XML file, count what arrived and allocate it to sets or loose stock.
- **Planning:** wishlists with a maximum price per wish, named lists and BrickLink XML or Rebrickable CSV export; prices from BrickLink, Rebrickable and Brickset with your own keys, including a part-out value.
- **Storage, printable lists, statistics** and an installable web app with light and dark themes.
- **For scripts and assistants:** a versioned REST API with scoped tokens and an Undo link on every change, an admin CLI and an MCP server.
- **Import** an existing collection from an older tracker database, read-only.
- **Self-hosted with Docker Compose.** No telemetry and no account with this project; no catalogue data or images are bundled, each install uses its owner's keys.

Source and compose files only; there is no container image for this release. Install: see the README.

### All changes in this release

- Kit controls: no control falls back to the grey bordered look any more. The off-design secondaries (Print missing parts, Pin, Take, the Matcher's help links, the ledger Filters) are the kit's outline clay, the Manage pages use the kit's neutral secondary, the value chips are filter chips, and every `.primary` is the kit's clay primary. The wish page follows frame 7b: Move or copy to another list is a quiet action in the Wanted module that opens a sheet with the lists as segments, and Undo is a quiet action.
- Error responses no longer carry database, file-system or other internal error text (#76): messages written for people still show, anything else is logged on the server and replaced by the handler's plain message.
- Tools & Admin → About: version, licence, source link, data credits, the LEGO disclaimer and BrickLink's required notice (also in THIRD_PARTY_NOTICES).
- What is this?: Enable camera opens a live preview with a guide, as in Part to Inventory; the next press (or Space) takes the picture and identifies it. A saved photo stays the quiet alternative, and the Part/Minifigure switch is a kit segment.
- README: how to get BrickLink, Rebrickable and Brickset keys and the limits each service sets; the install starts with the clone and asks for the password before the first start (found by a fresh-machine test).
- Demo: four copies hold a running set check made with the app's own checker at build time (first part, about 40 % answered, finished with six missing, finished clean), so Start, Resume and the finish screens show real states.
- Demo: the missing-picture tiles keep the item number and say where pictures come from: a set's picture from BrickLink when the set is added; part and figure pictures from Rebrickable or BrickLink with Refresh pictures.
- Publication review: the design test data uses invented owner names, and the private-material scans keep only generic patterns in the repository; a maintainer's own patterns come from `BW_PRIVATE_PATTERNS_FILE`.
- Static demo: `scripts/build_demo.py OUT --base /brick-work/demo/` renders the Sets, Minifigures and Parts lists, set and part pages, Check Set Parts, Part Picker, Part to Inventory, Wishlist, Prices, Complete sets and Storage with the real templates on an invented collection (no pictures, no network). Writes say "Demo with sample data: changes are not saved".
- The public snapshot keeps executable files executable (`scripts/check.sh`, `bin/brickwork`, `entrypoint.sh` had lost the bit in the first snapshot).
- Migration proof: the reviewed collection counts are re-pinned for the cutover (two set price lookups since the review added two items with their price, source and search rows).
- Item pages: Update price queues a market price refresh for that item (every colour it is used in) and says so. It opened the bulk refresh page, which lists stale prices only and so showed 0 for an item never priced.
- Storage: the selected storage is an inset, rounded band rather than a flush strip, and the list count no longer counts the Not stored row, so it matches the header (2 storages, not 3).
- Part Picker: the set list shows 15 sets a page with the Collection pager (#52). Ticked sets on other pages stay chosen.
- Tools & Admin: every option carries one short sentence on what you can do there.
- The app footer no longer carries the upstream credit; the README credits the upstream project in its closing Acknowledgements section.
- Wishlist management restyled after BrickLink's Wanted Lists: the lists as chips with counts, one row of outline actions (Manage lists, Export, Print, Download CSV), Export and Manage lists as sheets, and a selection bar with Move and Copy that shows while wishes are ticked.
- Part-out value: shown only when at least 90% of a set's lines have a price. With fewer, the price card says "Not enough prices yet" and offers Fetch part prices, which queues a market price refresh for the parts without one. It used to sum whatever few lines were priced (4 of 54 lines gave €0.18).
- Check Set Parts, running check: the header follows frame 3e (set line, name, progress). The bordered Choose another copy button is gone (it belongs to the Check this copy step, as a link) and the status pill shows at the finish only.
- Documentation site for GitHub Pages (`scripts/build_site.py`, `.github/workflows/pages.yml`): the README, the API reference from the OpenAPI contract, and a new MCP guide whose tool lists are generated from the server. A settings reference in the README lists all 38 settings. `tests/test_docs_drift.py` fails when the docs name a setting, a command or a link the code does not have, or the code reads a setting the reference does not list.
- Check Set Parts, *Largest first*: orders by the part's physical size (from its name and category: a baseplate, then a 2 x 4 brick, then a 2 x 4 plate, then a 1 x 1 plate), then by count and colour. It ordered by count alone, so twenty 1 x 1 plates came before the baseplate.
- Review follow-ups for #62 to #68: the add page's photo upload keeps its 8 MB; money such as -2.00 stays a number in CSV exports; the plan receipt search runs only for a plan file marked applied without a marker, and keeps the event id; the CLI says how to fix an unwritable data folder (and the README chowns it before setup); the session key file appears whole or not at all and a damaged one is replaced; the token form id is kept in the database.
- Small web defects (#68): query arguments named like url_for's own options (`_external`, `_anchor`, `kind`) no longer give a 500 or a link to another host; purchase places and collection sync show the usual notice before setup; reloading the page that showed a new token's secret does not create a second token; a read-only instance exports without writing an event; the embedded job drainer cannot miss a job queued while it stops.
- Sessions (#66): changing the password ends every open session; a cross-site link cannot log you out (logout also takes POST); `BW_SECURE_COOKIES=1` sends the session cookie only over HTTPS; every response carries `X-Content-Type-Options`, `X-Frame-Options` and `Referrer-Policy`; the navigation counts no longer show before login.
- Container (#65): runs as uid 1000 with the code read-only, writes only to `/app/data`, has a health check on `/api/v1/health`, and stops with the fix when `data/` is not writable (**after an upgrade from a root image: `sudo chown -R 1000:1000 data`**). Gunicorn's timeout is 120 s. `compose.local.yaml` publishes on `127.0.0.1`.
- CSV exports (lists, orders, wishlists) open as text in a spreadsheet (#67): a cell starting with `=`, `+`, `-`, `@`, a tab or a carriage return gets a leading apostrophe.
- Review follow-ups for #59 to #64: a warning when forwarded headers arrive with `BW_TRUSTED_PROXIES=0`; the check API returns the checker's own event and its Undo link again, and a repeated operation from another token is answered, not a 500; `brickwork mcp --transport http` also refuses an open install; browser uploads get their own caps (8 MB identification, 2 MB add list, 1 MB order files, 15 MB photos, 20 MB PDFs); the session key file is created once even with two workers; plans applied before this release are recognised by their receipt, markers are pruned after three days, and a repeated apply says so instead of repeating the counts.
- A sync pull or an import plan applies once (#64): two submits, or a crash between the commit and the plan file, applied it twice. The applied state is now a database row written in the same transaction.
- `POST /api/v1/copies/{id}/check` works after its first call (#63): it failed with 500 on any store that has the "Set is checked" flag. Its events now record `via='api'` and the token name, and the response's `event_id` names the API operation.
- Request bodies are capped before they are read (#62): 4 MB for JSON and forms, 8 MB for identification photos, the import limit (`BW_IMPORT_MAX_MB`, default 200) for other uploads; larger bodies answer 413.
- The legacy import's "Build a new database instead" form (#61): the browser form only reads and writes inside the data folder; `brickwork migrate` keeps taking any path.
- First run (#60): an empty `BW_AUTHENTICATION_KEY` no longer breaks every page; a session key is generated into `data/session.key`. **The server refuses to start without `BW_AUTHENTICATION_PASSWORD` unless `BW_ALLOW_NO_LOGIN=1`**, and `compose.yaml` publishes the port on `127.0.0.1` only.
- Forwarded headers are trusted only with `BW_TRUSTED_PROXIES` set (#59): a client reaching the app directly can no longer pick its own address to escape the login and token back-off. **Behind a reverse proxy, set `BW_TRUSTED_PROXIES=1`.** MCP over HTTP counts each client on its own.
- Release files: README status, privacy, repository and trademark sections; `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 3.0), `THIRD_PARTY_NOTICES.md` and the Patrick Hand licence; issue templates; a CI workflow running `scripts/check.sh` with read-only permissions and pinned actions; Dependabot; `scripts/public_snapshot.py`, which exports the public tree without internal build notes and checks it for private material and secrets.
- Remaining upstream code replaced: one settings module (13 settings) and one `.env` loader, login in `web/auth.py`, unused packages and Socket.IO hooks removed, upstream user docs and screenshots removed, upstream history moved to `docs/upstream-CHANGELOG.md`.
- Settings no longer read (setting them does nothing): `BW_UI`, `BW_TIMEZONE`, `BW_HIDE_MISSING_PARTS` (use `BW_HIDE_ALL_PROBLEMS_PARTS`), `BW_HIDE_TABLE_CHECKED_PARTS`, `BW_BRICKLINK_LINKS` and the other upstream `BW_*` display, pagination, folder and socket settings.

## 4.6d-1 · Collection design comparison (partial)

- Capture the Collection design frames and deployed app; record differences, approved deviations and blocked visual checks.
- Align open cards, compact detail heroes, identity order, mobile module order, Info facts, Prices typography, status dots and edit segments with the kit.
- Keep existing database reads, transactions, events and Undo; post-change screenshots and remaining component differences are still outstanding.

## 4.5v · list cost and quiet name refresh

- Select list pictures by source priority and recency without filesystem checks; keep containment and missing-file checks on the image route.
- Refresh only changed names and source properties, and report changed identities rather than every catalogue match.
- Label wishlist quantities “wanted”; reserve “missing” for collection defects.

## 4.5u · names, colours and identity

- Map catalogue names into migrated items with Rebrickable fallback and property provenance; refresh held names on later catalogue loads.
- Load validated BrickLink colour RGB in Catalogues & keys and show colour coverage.
- Show identity numbers once, omit absent names and leading separators, and share unsigned defect labels between templates and browser rows.
- Restore versioned PWA assets offline, focused-button keyboard activation, missing-asset URL fallback and the Part to Inventory shortcut.

- Fix review findings: start Planning refresh after commit, require login for all Planning actions, classify migrated/reference pictures consistently, preserve merged stock defects and tolerate later receipt quantities.
- Preserve Planning export selection and Collection row/image nodes across filtering and sorting, restore keyboard actions after button focus, show batch expiry and bulk picture failure reasons, and version Brick Work assets by deployed file mtime.
- Make Settings SQL tracing and navigation-count tests measure the actual paths; document the manifest shortcut blocked by the task's path allowlist.

- Suppress cooperative yields during SQLite transactions; materialize inventory per copy and yield after commit.
- Recover same-pid import owners that this process did not claim, without a schema change.
- Poll future budget waits at their earliest deadline, capped at 60 seconds; require editable mode and CSRF for selective and all-failed-step Retry.

- Yield between picture identities and other import work units so gevent can serve requests during long jobs.
- Start checkpoint recovery at app startup and retain the existing atomic process-owner claims.
- Show interrupted import jobs with Resume; preserve completed work and budget deadlines.
- Batch Import jobs step reads and test fixture yield timing, restart, concurrent claims and CLI operation without gevent.

- Replace the Settings picture identity payload with a small SQL count matrix. Skip picture file checks on page loads; retain exact confirmation selection and report queued counts that differ from the dialog estimate.

- Keep the rail theme picker below an independently scrolling navigation list at iPad landscape and desktop sizes.

- Share picture-kind classification between existing-file imports and pipeline downloads: only Rebrickable parts are renders, so refreshing imported set and minifigure photos replaces the same kind.

- Add Settings picture refresh: source choice, missing/replace scope, colour-specific counts, budgeted import progress and searchable findings. Verify and copy existing BrickTracker cache files using migrated identity evidence; preserve originals and picture priority.

- Fix Planning phone rows: put wish edits and copy actions in separate flowing blocks, hide closed/hidden controls and empty feedback, and show row prices with at most two decimals while preserving stored precision.

- Add Planning Wishlist, Prices and Complete sets on brickwork.db, with shared cached prices, audited pins/settings, loose-stock repair estimates and BrickLink XML export. Queue market-price refreshes through the budgeted pipeline. Share missing/damaged gaps with Workbench and move mobile footer clearance into the shell. Report the missing wish-currency and alert-storage contracts before enabling wanted-watch comparisons.

- Speed up Collection lists with SQL reads scoped to the listed kind and identities; clear the bottom tab bar in every shared list. Merge colliding loose-stock edits by item, colour, condition, lot and storage, retaining minifigures separately, per-row events and exact receipt Undo. Show the remaining stock row after a merge.

- Rebuild Collection and the home Sets list on brickwork.db: bulk-decorated item lists, shared Info/Prices/Matching/Consists of details, canonical jump links, colour-specific wishes, copy editing and archive Undo, local photos/captions/lightbox, lots, grouping and purchase-location totals. Share bounded matching and reversible transfers into loose-minifigure part gaps. Preserve the previous home at `/house/collection-legacy-home`.

- Schema 3.2 adds storage archival. Delete shows copy/entry/piece counts and either requires an empty location or explicitly moves live contents to Not stored atomically. Hide archived locations in pickers and lists; guarded Undo restores contents, and creation Undo archives the new location. Include the NULL archive column in migration mapping and proof.

- Merge loose-stock additions by live item, colour, condition, lot and storage across Add, Part to Inventory and Orders; keep figures separate and guard quantity Undo with audited before/after receipts. Identification IDs stay independent; photos follow the stock row.

- Rebuild Part to Inventory on brickwork.db: camera/saved-photo capture, audited Brickognize parts and figures, colour-confirmed queue, atomic loose-stock/lot batches, own photos and receipt Undo. Local model remains unavailable.
- Add v3 Orders review/import, receipt counting, explicit copy/stock allocation, holds, reconciliation and audited Undo; add Storage counts, location detail/edit and atomic moves. Rebuild navigation. Location archive and creation Undo are available with schema 3.2.

- Fix checker phone layout: consolidate Saved/Undo above the copy and part headings, remove the floating toast and sticky answer overlap, show colour/name/number once, and replace the wrapped “to go” label with “remaining”.

- Brick Work 4.2e: schema 3.1 wishlist row ids, colour and quantity, live-key uniqueness and row-id flags. Preserve XML colour/quantity and user notes; explicitly add duplicate quantities with exact Undo. Migrate deterministic wish ids/flags and checksum colour/quantity; include wishes in price colour discovery and live navigation counts.

- Share derived completeness between checker and workbench: damaged non-spare parts block Complete. Validate booklet batches against catalogue instructions with explicit unknown/ambiguous line errors, index exact stock matches and picker gap counts, and validate transfers only against their requested source and gap.

- Clear process-global metadata caches when shell test fixtures finish, preventing picker/matcher tests from leaking wish-owner columns into fresh capture databases.

- Add Part Picker and Matcher on `brickwork.db`: copy selection, completion ranking, colour grids and found receipts, exact loose-stock Take/Give for parts, whole figures, physical booklets and boxes, bulk booklet entry, atomic history/events and guarded Undo.

- Add Manage → Add on `brickwork.db`: all eight BrickLink types, local catalogue search, paste/XML/CSV review, budgeted Brickognize candidates, explicit confirmation, duplicate choices, audited collection receipts and Undo, durable per-item imports and batch progress. Skip hidden AppleDouble files during catalogue loading.

- Fix Check Set Parts to use the migrated “Set is checked” status flag for Finish, Undo, derived completeness and chooser defaults. Return save deltas without inventory-wide picture lookups.

- Rebuild Check Set Parts on `brickwork.db`: copy chooser, immediate audited counts, figure and spare passes, full miss history, Found 1 recovery, derived-only finish, Undo and an ordered offline queue.

- Add Manage → Tools & Admin on `brickwork.db`: source keys and catalogues, durable refresh jobs, unresolved identity review, statistics, values, database export/checks, settings, theme and identification history. Keep the retired tools routes reachable.

- Add the Toni v2 Brick Work shell: four navigation groups, responsive rails and bottom tabs, read-only counts, local brand assets, system pages and Home Screen installation with a shell-only offline fallback.

- Pin production dependencies and Python 3.14.8; build the local Brick Work image reproducibly.

Fork work since upstream `8b0b85f`:

### House data store and API

- Add an independent Rebrickable side catalogue and house SQLite store with idempotent migrations, collection tracking and price history.
- Add authenticated house API and CLI workflows for capture, copy/wishlist editing, missing parts, loose inventory, identification history, minifigure resolution and BrickLink XML import/export.
- Add physical box/booklet tracking, manual completeness, reviewed database maintenance and receipt-protected loose-stock transfers with reconciliation after split commits.

### Toni UI

- Add selectable toni/upstream UI modes, local light/dark/system themes, responsive navigation and global item jump.
- Rebuild collection lists, item and copy details, inventory tabs, parts checking, editing, statistics, jobs and administration; improve sorting, filters, repeated-figure grouping and mobile controls.
- Add enlarged pictures, booklet reference images, direct found-count saving and a full-width checker Found action.
- Brand the fork surfaces as Brick Work while retaining upstream credits and technical names.

### Prices and orders

- Add paced Brickset fetching, BrickLink price slots, condition-aware valuations, settings, colour maps, offline catalogue indexing and part-price observations with due keys.
- Add completion ranking, repair pricing, email/XML/Store API order import, receipt-ledger review, reconciliation and received/reviewed allocation.
- Normalize price formatting and numeric sorting, and provide bounded authenticated BrickLink image caching and fallbacks.

### Scanner and matcher

- Add Workbench parts scanning and matching, conservative colour/name matching, mould/alternate resolution and manual figure mappings.
- Resolve scanner-added pictures with authoritative part mappings and exact-colour sources; show owned sets needing loose stock and support reviewed inventory transfers.

### Tests

- Add offline Python coverage for stores, API, migrations, imports, prices, matching and UI contracts, plus Node runtime harnesses for toni interactions.
- Add the repository check gate and synthetic order fixtures with invented order, set and catalogue identities.

## Upstream history

Releases 1.4.2 and older come from the upstream BrickTracker project: see [docs/upstream-CHANGELOG.md](docs/upstream-CHANGELOG.md).
