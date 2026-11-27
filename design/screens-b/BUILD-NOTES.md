# Build notes, B′ screens

Generated from the review rounds of commission U (review artifact https://claude.ai/artifact/FX8PAj3J9cgVkY42oPGc8a) and commission N (https://claude.ai/artifact/1sWRRsfiYxkEgHXxKxrsUn); the approvals are in `../APPROVALS.md`. For each approved item: every difference from the shipped screen, as listed under it in its round. A shipped text or control not named here stays as shipped, restyled through the tokens.

## Round 2

### R2-01 The shell: four tabs instead of the sidebar (`every frame`)

- **Removed:** the left sidebar with its 22 entries, the counts beside Sets, Parts and Wishlist (18, 6, 6), and the theme switch at its foot; the theme lives under Manage › Appearance, which is already a page.
- **Moved:** every sidebar entry to the row under its group tab. Add stays as the violet button top right and as a page under Manage.
- **SUCCESS:** Structure: one navigation model on phone and desktop. Simplify: one bar instead of a bar and a sidebar. Condense: the content gets the 232 px the sidebar took. Check: the counts are gone from the navigation, so they must stay on their pages.

### R2-02 The lockup in the app bar (`every frame`)

- **Changed:** the small mark without the X and “Brick Work” in Inter 600 (PR #482) become the lowercase lockup.

### R2-03 B′ tokens and type (`every frame`)

- **Fonts:** IBM Plex Sans, Sans Condensed and Mono, SIL OFL 1.1, self-hosted in design/fonts with their licences (no font service). Inter, Geist and Geist Mono leave the app; Patrick Hand leaves with the old wordmark.
- **Lines:** hairlines go from 0.5 px to 1 px, and a 1.5 px ink rule closes headers, tiles and the app bar, as on a ledger.
- **Status:** success, warning and info lose their colours. Status is told by shape and a word (a tag, a dashed tag, the X chip), so nothing in the chrome looks like a part colour. Errors keep one muted red, always with a word.
- **Dark mode:** built from these roles after your approval, as the review scope says; not shown.

### R2-04 Components (`00-components`)

- **The two Xs:** the logo’s X (white on a violet square) means “not checked yet”; the thin line X without a square means close or stop. Part Runner’s Stop keeps the thin one.
- **Focus:** the ink ring replaces the teal “logo blue” ring of 17.11., as you said, within milestone U.

### R2-05 Tools & Admin (`01-tools-and-admin`)

- **Changed:** Get started is a card under a violet tape strip (was a clay-soft card). Refresh is two outlined cells with their labels in capitals; Jobs is the row under them.
- **Copy, #465:** “Instruction files”: “Upload or rename the PDF booklets, or open each set’s official or Rebrickable instructions page.” (was “Fetch, upload or rename the PDF instruction booklets for your sets.”)
- **Copy, #465:** the Settings row “Labels and instructions” becomes “Labels”: “The address on printed labels.” (was “… and the largest instruction download.”)
- **Kept:** every row, note and signal (0 to decide, 0, for experts), Maintenance with Show 8 tools, About.
- **SUCCESS:** Say: “Things you do” as the page’s one message. Unify: one row style for every destination. Check: muted text 5.5:1, violet tape 6.7:1. Structure: set-up, refresh, then the groups in reading order.

### R2-06 Settings (`02-settings`)

- **Removed, #465:** “Largest instruction download · Up to 500 MB per file”, because nothing is downloaded any more; the group is renamed “Labels”.
- **Changed:** the back link is violet with the accent text token; the “for experts” chip is a dashed tag.
- **Kept:** Money and prices (Display currency and rates, Country for retail prices), Sets and parts (Group parts by, Part list for a new set, Lost Parts from Rebrickable), Address on printed labels, Where data comes from with Show 4 settings.

### R2-07 Find instructions (#465) (`03-find-instructions`)

- **Removed:** the steps (Choose sets, Tick files, Download), the file ticks, sizes, Download N files, the Downloading progress, Cancel and Retry, the Filter by source; the bulk “fetch missing booklets” action.
- **Removed elsewhere, #465:** Add’s greyed “Fetch instructions” switch is hidden; Settings’ “Largest instruction download” is gone (R2-06).
- **Kept:** the region choice (now “Region for official instructions”), Upload a PDF (the shipped upload on the set’s Instructions & Box tab).
- **Names:** the links say “Official instructions” and “Rebrickable” (marketing’s form); the address shows on hover. The alternative, “lego.com”, is open question 4.
- **SUCCESS:** Say: “4 sets have no booklet.” Express: links out, because the app downloads nothing. Check: no claim the app cannot keep. Simplify: one list, three actions per set.

## Round 3

### R3-01 Sets (`04-sets, 05-sets-without-storage`)

- **Your comment:** the storage tape and the storage index show only where storage is set: with no storage at all, neither appears; a set with no storage gets no tape. The per-copy bar stays, since it is about the check, not the storage.
- **New, issue A:** one bar per copy, to scale: violet found, hatched missing, dashed still to check; a copy never checked is all dashed with the X; two copies get two bars (#1, #2).
- **New, issue B:** the storage index on the left: every storage with its count of copies, plus Every storage and No storage; choosing one filters the grid. On the phone it is the “Storage: all” row.
- **Changed:** sets sit under their storage’s label tape (the shipped Group by storage, now the default); the status filter is a row of tabs with counts (was chips); Drawers and Ledger name the shipped grid and list switch; the set number is the tile’s headline in mono.
- **Moved:** the filter panel on the right becomes the Filter button (the same filters in a sheet); Options and Select mode move into it.
- **Kept:** the price on each tile (used average from BrickLink), search by number or name, Sort, the counts in the heading.
- **SUCCESS:** Say: “3 of 7 sets incomplete”. Check: bars to scale, 10 missing of 375 is a 2.7 % sliver; the counts add up (69 = 10 + 12 + 14 + 33). Express: the drawer is the structure. Structure: storage, then set, then copy.

- **Corrected 2026-11-20 (#494, C-1 and C-2):** `04` says "4 storages" (the storages that hold sets), the Filter button has the sliders icon on both frames (the phone app bar already has a magnifier), and `05` shows the status tabs and, on desktop, search and Sort: only the storage tape and index are absent with no storage. `04` at 390 is an excerpt of the page (two of the three S-0002 tiles): compare down to the last drawn tile row. Search and Sort sit in the Filter sheet below 1024 px. Frame figures are sample data: the app shows its own. **Pending Ulf's picture check (C-3, 2026-11-20; he chose the fixes: "Sort by number; wrap the text"):** `05` at 1440 lists the tiles by number (7213, 7938, 8043, 10210, 10254, 21028, 31120), as its Sort button says; at 390 the copy text under a bar (`#1 365/375 · 10 missing`, 23 characters, a phone tile holds 21) wraps to a second line inside the tile (`#1 365/375` / `10 missing`) on `04` and `05`, nothing cut or run over; a copy text of 21 characters or fewer stays on one line (`643/657 · 14 missing`). The 390 frames of `04` and `05` are excerpts (two tiles): compare down to the bottom of the second tile row. `48`, which draws the Sets page through the same generator, is rebuilt with these corrections (the "4 storages" text, the sliders icon, the wrapped copy text).

### R3-02 Set Inspector (`06-set-inspector`)

- **Your comments:** the old stepper is back on phone and desktop: “Found ×2” in the middle, − and + on either side change the count, Missing below; the part’s name block is filled with the part’s own colour (Dark Bluish Gray, Red), text in white or ink, whichever reads.
- **Named:** “Workbench · Set Inspector” above the set and the active tab, so a screenshot shows the feature’s name (marketing’s point).
- **New look, same data:** one cell per part line of the copy (131 lines: 54 found, 4 missing, 73 to check), from the saved per-copy check.
- **Kept, O10b:** missing lines are larger cards with a 96 px picture and a 56 px stepper, so the missing count stays editable; found lines are compact rows.
- **Kept:** the current part with Need, Found 2, Missing, Back, Skip for later, Undo; keys 1 to 9; “Saved 14:20 · resume any time”.
- **SUCCESS:** Say: “142 of 375 parts”. Unify: the same violet, hatch and dash as the Sets bar. Check: cells per line, so 375 parts never become 375 cells.

### R3-03 Part Runner (`07-part-runner`)

- **Your comments:** the old stepper: “Found ×3” is the button in the middle, − and + on either side change the count; Missing is a full-width button below; the name block takes the part’s colour. The Set Inspector uses the same row.
- **Changed:** the run strip has one segment per part of the run (52), the current one in ink; Pick 3 sits in a ruled count box; Found it is violet.
- **New on desktop:** the next parts in storage order under their storage’s tape, beside the current part (the phone keeps one part at a time).
- **Kept:** Print list, Stop (the thin X), the set and copy the part is for.

### R3-04 Sets, empty (`08-sets-empty`)

- **Says:** what is empty (no sets yet), what still works and the ways out: Add a set, and Bring your collection in (the existing Get started step, which reaches Rebrickable, Brickset, BrickTracker and a BrickLink file).
- **Only when true:** “The catalogue is loaded, so parts and pictures come with each set” shows only once the catalogue step is done, as in this state (Get started 1 of 4); a fresh install leaves the sentence out.
- **Kept:** the Get started card under its tape, while set-up is open.
- **Not the X:** an empty list gets a dashed tag; the X stays reserved for “not checked”.

## Round 4

### R4-01 Matchmaker (`09-matchmaker`)

- **Changed:** the copies that can be advanced sit under one tape, “Completable first, then coverage”; each has a coverage bar: violet what loose stock covers, hatched what is still missing, with “covers 7 of 12 missing”.
- **Named:** “Workbench · Matchmaker” above the heading and the active tab.
- **Kept:** the heading “3 copies can be advanced, 0 can become complete”, search, filter and sort, How matching works, Add instruction booklets, Recent saves (desktop; on the phone below the fold).
- **SUCCESS:** Say: the heading is the answer. Unify: the same bar language as Sets. Structure: completable first.

### R4-02 Build Scout (`10-build-scout`)

- **Changed:** each candidate set has a coverage bar (parts you hold, to scale) with “412 of 598 · 69 %”; the selected set is marked in violet soft with a violet edge; the panel’s “Parts you hold” uses the same bar.
- **Fixed:** the shipped “−245 parts” becomes “245 parts missing”: no minus before a number (DESIGN-CHECK); a set with no figures says “no figures”, not “0 of 0 figures”.
- **Kept:** every filter (Parts from, Min, Max missing, Theme, Years, Sort, Apply), the summary line, the panel’s part lines, “+ 20 more lines · Show all”, the price estimate, Build it · make a copy, Add to wishlist, Missing parts · XML and its undo note. On the phone the filters fold into “Filters · 6” and the panel opens as a sheet.
- **SUCCESS:** Check: bars to scale, percentages from the same numbers. Express: list plus detail, because the decision needs both.

- **Corrected 2026-11-21 (#499, found by brick-work's frame check; pending Ulf's picture check):** the shipped Size filter (fewest and most parts) was left out of the frame by omission although this note says every filter is kept: it sits beside Years (`Size any – any`), and the phone's button reads "Filters · 7". The panel's numbers add up: 186 missing in 23 lines with the largest gaps 14, 12 and 11 (they were 14, 9 and 6, which cannot lead 23 lines that sum to 186). Frame figures are sample data; the frame shows Min 0 %, the app's default is 60 %, so the check opens the page at `?min_percent=0`.

### R4-03 Storage (`11-storage`)

- **Changed:** the storage table has the label’s short code first, then name and type, then sets, figures and part lots in mono; the selected storage is marked in violet soft; its detail opens under its own label tape with its sets as tiles with their per-copy bars.
- **Kept:** Add storage, Purchase locations, Edit, the move hint, History; Print label sits beside Edit (labels approved in L01).
- **Empty storage:** a storage with nothing in it keeps the shipped empty state (“Bag 07 is empty.” and how to move things in), restyled; not drawn separately.
- **SUCCESS:** Unify: the same tape as Sets, so a shelf looks the same in both. Structure: storage, then contents.

- **Corrected 2026-11-21 (#500, decided by brick-work-product):** the storage type reads "Drawer", an existing type (Box, Shelf, Drawer, Bin, Bag, Case, Cabinet, Room, Other), not "Drawer unit"; the storage's own name "Parts drawer unit" stays. Pending Ulf's picture check.

- **Corrected 2026-11-21 (#500, found by brick-work's frame check; pending Ulf's picture check):** the controls the app keeps were left out of the frame by omission: Print labels sits beside Purchase locations in the header on desktop and under the list on the phone (below the fold of the 390 frame), and Select sits beside Print label and Edit. On the phone the list has no detail pane beside it, so no storage row is marked (the frame marked S-0002). The tile shows no copy condition (New/Used), as the approved Sets tile of R3-01 does; the condition is on Set detail.

## Round 6

### R6-01 Order missing parts (`15-order-missing-parts`)

- **Changed:** each set row has a bar to scale, violet found and hatched missing, with “12 parts missing · gain +€7.39” below it. The order list sits under one tape, “Order list · 59 lines · 59 pieces from 3 sets”. The four totals are ruled mono figures. Each line shows its source as a choice of two: the chosen one in violet soft, and Pick a Brick muted where a line has no element id.
- **New controls:** violet checkboxes and switches (Leave out sets to sell or part out, Only sets that gain value, Prefer Pick a Brick); All, BrickLink and Pick a Brick as a segment (round 3’s control).
- **Named:** “Planning · Order missing parts” above the heading, as on every B′ screen. The shipped link “Planning · Complete sets” stays as the back link.
- **Kept:** Search sets, Theme, Sort, the set count, Select all and Clear, Check in progress, figures missing, Expand all and Collapse all, part groups, the per-line set labels and condition, the cap note, the left-out and no-element-id warnings, Download BrickLink XML with its file name (below the lines, not drawn), the Pick a Brick tab, the error and empty states.
- **Phone:** one step at a time, as shipped. Filters fold into “Filters · 4”. The sticky bar “3 sets · 59 lines · 59 pieces” with Review list sits above the tab bar. The review step opens the order list alone, with “‹ Order missing parts” and Download BrickLink XML in the bar.
- **SUCCESS:** Say: the order list is the answer. Unify: the same bar language as Sets and Matchmaker. Check: totals in one currency, “no price” where nothing is known. Structure: choose sets, then review the list.

### R6-02 Set detail (`12-set-detail`)

- **Changed:** the hero carries the copy switcher as a segment and the copy’s status as tags (Incomplete hatched, Used, Checked), with BrickLink and Brickset beside them. Under the hero, the copy’s bar from #489 (violet found, hatched missing), with “4 can be taken · 6 to order” and Check parts, Edit parts and Check missing only. Missing lines are larger cards in the part’s own colour, with Take n (Set Inspector’s O10b). Rows carry the colour as a chip in its own colour.
- **Right column:** Sell this copy (tags, the asking price large, the arithmetic rows, part-out value and coverage, Copy listing text, Preview), Value · Copy 1 (Paid, Worth now, Gain, source line), then Info, Prices, Part list and Links, each a card with a small label heading and its one action at the right.
- **Kept:** every card’s rows and states as shipped: value-loss, no-price, no-quote, override, stale, other-currency; Sell unchecked, no quote, no rate and error; partout-no-key (Update price disabled, “Needs a BrickLink key”); the Part list switch sheet and change notes; the tabs Parts, Minifigures and Instructions & Box with the booklet states (ready, pending, failed, single, archived); the toolbar and its filter and sort sheets; Edit parts mode with its save bar; Found 1 and Found all; the retired lines; the Edit and Delete sheets; the lightbox. They are restyled through the tokens and not drawn.
- **Phone:** the hero, then the copy bar and Check parts, then the cards. The shipped phone puts the cards first and the bar inside Consists of, below them. Moving the bar up puts the copy’s state and its main action on the first screen (functionality before pixel perfection).
- **SUCCESS:** Say: the copy’s state is the first thing under its name. Unify: the same bar, tags and colour block as Sets and Set Inspector. Check: the arithmetic adds up (€48.58 less €2.40 is €46.18). Structure: the copy, then its parts, then its money.

### R6-03 Lot Sorter (`14-lot-sorter`)

- **Changed:** the lot’s facts are a single row of small labels under the heading, with Edit at the right; Set detection sits under its own tape. Each candidate’s score is an ink bar from zero to 100 %, not violet: the score is not “found” (it is not a probability, as the page says). Found parts are tiles with a violet edge, not-found-yet tiles are dashed.
- **Named:** “Workbench · Lot Sorter” above the heading. The B′ shell lists lots under Lot Sorter (R2-01).
- **Kept:** Min score, Theme, Years, Size, Ignore common parts, Apply; best match; Details and Hide details; Found in the lot, Not found yet and Swaps with their counts; Pull list and Open set; the sticker chooser, and the pull list with its search, filters and Expand all (restyled, not drawn); the add-part-lot state stays unbuilt as shipped.
- **Phone:** the Make a copy confirm as a bottom sheet over the pull list: the three counts, “The copy starts as Incomplete Not checked” with the logo’s X, and one violet button, “Make copy of 7938-1”. The pull list’s bar is violet found and dashed still to find.
- **SUCCESS:** Check: the score bar starts at zero and is not violet, because it is not a count of found parts. Express: tiles for parts, because you recognise a part by its picture. Simplify: one question per screen, “Which sets are in this lot?”

### R6-04 Orders (`16-orders`)

- **Changed:** the order list on the left: the selected order in violet soft with a violet edge, and status by shape: Draft and Counting dashed, Reconciled solid. Count what arrived has a bar to scale (violet counted, dashed still to count). Each line has the approved stepper, and its status is a tag: Complete solid, “3 short” hatched.
- **Named:** “Workbench · Orders” above the heading; the order’s tabs (Order detail, Count what arrived, Review allocation, Allocations and reconcile) use the Set detail tab style.
- **Kept:** Import an order with its three ways in (Import a placed order, Paste order email, BrickLink XML upload, Link to an existing order), Already imported with search, filter and sort, Save partial receipt, Mark all received, the short-lines note, Count audit with Undo, order detail, resume draft, line review, allocation history, undo and hold, reconcile and the XML link. Restyled, not drawn.
- **Phone:** the order alone with “‹ Orders”, tabs scrolled sideways, each line’s ordered count under its name.
- **SUCCESS:** Check: 56 of 95 counted, to scale. Unify: the same stepper as Set Inspector, the same status shapes as Sets. Structure: list, then the order, then the step.

### R6-05 Part Spotter (`13-part-spotter`)

- **Changed:** on desktop the four panels side by side, as shipped: camera and capture, then queue and results, then the review of the current piece. The review compares the reference with your photo, shows what you already hold, and offers the colour as swatches, the chosen one in violet soft. The viewfinder carries the piece number as a tape.
- **Kept:** Camera, Recognition (Local model not available yet), Identify; Take picture and Enable camera, Add a saved photo and its note; Space and the queue limit; the queue statuses (Ready, To review, Unidentified) and its search, filter and sort; Other possibilities; Quantity; Has a sticker; “Confirm · Light Bluish Gray ×1” (“· sticker” when on); Delete picture; the keyboard note; Results and Review inventory batch; the batch sheet (Loose parts or Assign to a lot, Condition, Keep photos); every camera and error message. Restyled, not drawn.
- **Phone:** one panel at a time, as shipped: Capture, Queue 3, Review and Results 1 as a segment, Review open.
- **SUCCESS:** Say: one piece at a time. Express: swatches for the colour, the one choice the photo cannot make. Unify: the colour block from Set Inspector, the tags from Sets.

- **Corrected 2026-11-21 (#508, found by brick-work's build; pending Ulf's picture check):** the queue tags carry the shipped statuses, as this note says: piece 1 reads "Ready" (the frame said "Confirmed") and the piece being read reads "Recognizing" (it said "To review"); "Confirmed" stays on the Results row. Decided without a picture because they change no layout: the delete cross on a queue row, the chevron on the camera field and the way to the other colours (a "More colours" link on the colour label row that opens the searchable list, the six swatches first and any other colour you hold) are shipped controls the frame left out; the "More colours" link is the one addition and is shown on the next review round. The phone header icons are at the same pixels in frames 04, 10, 11 and 13 (search 636,36 to 665,65; plus 712,36 to 739,63 at 2x).

- **Corrected 2026-11-21 (#509, found by brick-work's frame check; pending Ulf's picture check):** the 390 frame of the pull list left out shipped controls behind the scrim: under the Search parts field the tools row (To find, Category and Apply), the line "Expand all · Collapse all" and the first group header ("Brick · 120 to find", sample numbers). The phone sheet has no Cancel link: the scrim above it closes it, so the app hides Cancel on phones.

## Round 5: tokens only (#501)

These screens keep their layout and every shipped control and are rebuilt through the tokens and components, on the approved frames named. Shipped screen folders are those of `../screens/`.

| Row | Group | Screens | Shipped folders | Builds on |
|---|---|---|---|---|
| T1 | Collection | Minifigures, Parts, Instructions, Boxes (and Gear, Books, Catalogs when held) | `17-Item-lists`, `19-Item-lists`, `21-Collection-capabilities`, `24-Pager`, `25-Sets-filters-where-select-and-group-go` | R3-01 as drawn: the status tabs, the Filter sheet, Drawers and Ledger, the tile; nothing new to draw. |
| T2 | Collection | Minifigure, part, instruction and box detail; edit sheet; copy chooser | `12-Minifigure-detail`, `22-Minifigure-detail`, `13-Part-detail`, `14-Instruction-and-box-detail`, `11-Edit-sheet`, `18-Copy-chooser` | Fields, buttons, tabs and the colour block of R2-04 and R3-02; the layouts stay. |
| T3 | Workbench | Set Inspector start and its other states | `28-Check-set-parts`, `36-Check-this-copy`, `39-Include-spare-parts`, `40-Check-figure-parts` | R3-02: the cells, the stepper, the X for “not checked”; save error and JavaScript off use the status shape and word. |
| T4 | Planning | Complete sets | `43-Complete-sets`, `44-Complete-sets` | A list of copies with their missing parts, as shipped; no marketing surface shows it. Its order flow is N4. |
| T5 | Workbench | Storage labels, places and the theme picker | `34-Storage:labels-*`, `52-Place` | R4-03 and the approved labels (L01). |
| T6 | Planning | Wishlist, Prices, wanted watch, your max price | `41-Wishlist`, `42-Prices`, `45-Wanted-watch-and-alert`, `46-Your-max-price-with-a-currency` | Lists of rows; Prices’ filter chips become the R3-01 status tabs; the part colour chip uses R3-02’s colour block. |
| T7 | Manage | Add, Scan a set barcode, first run without keys | `47-Add`, `57-Scan-a-set-barcode`, `26-First-run-without-keys` | Forms and R3-04’s empty-state pattern (what is empty, what works, the ways out). |
| T8 | Manage | Statistics | `49-Statistics` | Charts as shipped (bars from zero, one scale); no marketing surface shows it. Needs the chart colour (question 2) before it is built. |
| T9 | Manage | Tools & Admin pages: Identify history, Jobs, Catalogues & keys, API tokens, Appearance, Not found (Collection sync is now Workbench · Sync, N1-01, commission N) | `50-Tools-and-admin-pages:identify-history`, `51-System-pages`, `53-Jobs-and-maintenance`, `54-Catalogues-and-keys`, `55-Api-tokens` (`56-Collection-sync`: N1-01 `17-sync-hub`) | R2-05 and R2-06: the rows, the label column, the sub-page header. |
| T10 | Shell | Jump results and the module states (loading, error, stale, thin data, no data, listings only) | `06-App-shell:jump`, `16-Module-states` | R2-01 shell and R2-04 status (shape and word); a loading state is a dashed box, an error the danger word. |

T8 Statistics: the chart colour is decided (ink bars, violet only where a bar means found or complete; BRAND.md § 10).

## Commission N, round 1 (#517)

The Sync hub and the Rebrickable page in B′ (review artifact https://claude.ai/artifact/1sWRRsfiYxkEgHXxKxrsUn, version 4), built by `../sources/n/n_frames.py`. The shipped screen is Tools & Admin · Collection sync (`../screens/56-Collection-sync`); every frame below is new, built on the approved round 0 wireframes (`../mockups/`).

### N1-01 Workbench · Sync, the hub (`17-sync-hub`, #518)

- **Drawn:** W0-01 in B′: the four site cards in one row, Import & export as its own wide card, the Sync log as a table (a list on the phone), then How sync works.
- **Text (brick-work-marketing, 19.11.):** one form for waiting changes, "3 changes waiting"; the Import & export card carries no tag, since "Files" is not a state.
- **Rule-decided:** every card button is the ink outline (Open, Connect). Violet stays for the one action of a page; four violet buttons in a row would be four primaries (Simplify).
- **Rule-decided:** status by shape: Connected and In sync and Done solid, Not connected and waiting dashed (BRAND.md § 10).
- **Phone:** the Workbench row is shown scrolled to Sync, so the active entry is in view (round 0 did the same); the row itself is round 2’s.
- **Differences from the shipped Collection sync (round 0, approved):**
  - **Moved:** Collection sync leaves Tools & Admin (screen 56) and becomes the Workbench entry "Sync"; old links redirect here (#518).
  - **Changed:** the shipped card had Pull, Review and send and Link on it; the hub card only opens the site page. The pills (Key not set, Not linked, Changes waiting, In sync, Not pulled yet) become Connected or Not connected plus one state word.
  - **Dropped from the card:** "Bring in Lost Parts" switch and its note (now in Choose what), "Link a collection".
  - **Text:** the intro "Bring a collection in from Rebrickable or Brickset, work on it here, then send the changes back." names no sites now ("from another site"); the log column "Source" becomes "Site" ("File" for file runs), its directions become Into Brick Work and To Rebrickable; "How sync works" is reworded for one run ("A run never deletes anything here unless you choose. … Changes to a site are always shown first, and removals there wait until you tick them."); its second paragraph (each source keeps its own link, each run uses the daily budget) moves to the site page, under Last runs.
  - **New:** BrickLink, Brick Owl and Import & export cards (their pages are round 2).
- **SUCCESS:** Say: where each site stands. Unify: every card has the same parts in the same order, tags as everywhere in B′. Condense: four cards in one row at 1440. Simplify: no violet on the hub but the active tab. Pass.

### N1-02 Rebrickable, the page at rest (`18-rebrickable`, #519)

- **Drawn:** W0-02 in B′: Start a sync is the page’s one violet action; the account and the last runs side by side, What syncs as a table under them.
- **Kept:** every text of W0-02 as approved, with the sample values.
- **Differences from the shipped Collection sync (round 0, approved):**
  - **New:** the page itself; the shipped app had only the card and the Link page.
  - **Kept:** Test and Remove; Retry for rows still waiting.
  - **Changed:** "Undo this pull" becomes "Undo this run"; "Last pulled · Last sent" becomes "Last run"; the waiting rows are part of their run.
  - **Changed:** the key moves here from Tools & Admin → Catalogues & keys, as #518 says; the daily budget shows here beside the speed.
- **SUCCESS:** Say: this site’s state and its one action. Structure: account, history, then the rules. Check: the budget is shown as used of the day’s 2,000. Pass.

### N1-03 Step 1, Connect (`19-rebrickable-connect`, #519)

- **Drawn:** W0-03 in B′, with the new step bar. The key and the account are two cards side by side at 1440. Per product (19.11.), the key lives only here; Prices’ "Add a key" and Get started’s keys step open this step and come back.
- **New component:** the step bar (see NC-01).
- **Kept:** all approved copy; Next is the ink outline, Connect the step’s violet action.
- **Differences from the shipped Collection sync (round 0, approved):**
  - **Moved:** the API key field from Catalogues & keys (today "needs a key" sends you there).
  - **New copy:** "The key reads Rebrickable's catalogue. Your account lets Brick Work read and change your lists." (marketing's wording).
  - **Kept:** Username or email, Password, Connect, "Paste a user token instead", "A user token is stored encrypted. It is never shown again."
  - **New:** the step bar (6 steps on desktop, "Step 1 of 6" with a bar on the phone).
- **SUCCESS:** Say: connect this account. Check: the password is never kept, said where it is typed. Pass.

### N1-04 Step 2, Choose what (`20-rebrickable-choose-what`, #519, #471, #469)

- **Drawn:** W0-04 in B′: the direction segment per kind of data (the approved segment control), the four Lost Parts rules as radio rows, loose stock Into Brick Work or Off (#471 decision 1), one lot per part list (#471 decision 2).
- **New component:** the radio row (NC-02) and the select field (NC-03).
- **Moved here:** the Lost Parts rule from Settings (#469); Settings keeps only the pointer row, C-03.
- **Differences from the shipped Collection sync (round 0, approved):**
  - **Kept, verbatim:** the owned-list hint, "Send changes to", "Wanted sets · go to the wishlist", "Wishlist here", "When both sides differ · Ask me each time", the four rule labels and notes.
  - **New:** the direction segments; Loose stock from part lists (#471: none ticked by default, Into Brick Work or Off, "Put new loose parts in · One lot per part list"; questions 4 and 5); Lost Parts to Rebrickable with "Which count wins" (#469; its options mirror the pull rules and are drawn in round 1); the Minifigures check.
  - **Moved:** the Lost Parts rule from Settings → Sets and parts (#469).
  - **Shipped default:** #469 keeps Lost Parts to Rebrickable off until you turn it on; the frame shows it turned on.
- **SUCCESS:** Express: one of four is a radio list, one of few a segment, on/off of lists a checkbox. Structure: what you own, then what you want, then loose, then the rules. Say: the step’s choices are the controls; Next is the ink outline, violet stays for Connect and Run. Pass.

### N1-05 Step 3, Pick sets (`21-rebrickable-pick-sets`, #519)

- **Drawn:** W0-05 in B′: By theme with four themes chosen picks 4 of the 7 sets; the picked count and what else comes along in a note above Next.
- **New component:** the filter chip (NC-04), chosen in violet soft as the source choice is.
- **Differences from the shipped Collection sync (round 0, approved):**
  - **New:** the whole step. The shipped sync always covers every linked set.
- **SUCCESS:** Say: which sets this run covers. Check: the count matches the ticks (4 of 7, the four sets the Preview compares). Pass; Next is the ink outline, since the step’s choice is the ticks, not a button.

### N1-06 Step 4, Preview (`22-rebrickable-preview`, #519)

- **Drawn:** W0-06 in B′. The conflict comes first, so the three-way choice is above the fold at 1440 (marketing’s screenshot 2). 9 differences: 6 into Brick Work, 2 to Rebrickable, 1 changed in both places; 7 are chosen, so the button reads "Run 7 changes".
- **New component:** the three-way conflict choice is the approved source choice with three options (NC-05); the info box for "Before you send" (NC-06).
- **Text (brick-work-marketing, 19.11.):** the choice names the number and the place in each option: "Keep 2 here" / "Nothing sent", "Take 1 from Rebrickable" / "Brick Work becomes 1", "Send 2 to Rebrickable" / "Rebrickable becomes 2".
- **Moved:** the conflict block from under the list to the top (screenshot 2).
- **Changed from round 0, approved as drawn:** W0-06’s row "Only here · Removes there" cannot happen (a set only here is not there to remove). Drawn as two rows: "Only here · Add 1 there" (10254-1, ticked) and "Gone there · Remove here" (31120-1, hatched, unticked, since nothing here is deleted unless you choose).
- **Differences from the shipped Collection sync (round 0, approved):**
  - **Changed copy:** "Nothing here is deleted by a pull. Choose what happens to each difference, then pull." becomes "Nothing in Brick Work is deleted unless you choose. Choose what happens to each difference, then run."; Before you send drops "Rebrickable has no undo" (a claim about another site we cannot keep checked) and keeps "Brick Work's Undo cannot take a sent change back. Removals are unticked until you tick them."
  - **Kept, verbatim:** New there, Different, Only here, Removes there, Add [n] here, "Checks, storage and notes stay here either way; only quantities are compared.", the Lost Parts summary line, "Choose a copy".
  - **Changed:** the conflict tickbox ("Take Rebrickable: add [n] here" or "Send [n] there") becomes a choice of three, Keep here first; the time at about 1 request a second joins "Budget today"; the button "Pull" or "Send" becomes "Run [n] changes".
  - **New:** the To Rebrickable and Loose stock chips; Lost Parts rows going to Rebrickable; a Loose stock section with "Put in" a lot per row (#471).
  - **Text:** "Nothing happens to these unless you tick them." becomes "…unless you choose."
- **SUCCESS:** Say: what will change, and the one choice that needs you. Check: the counts add up (6 + 2 + 1 = 9; 7 chosen; about 9 requests). Unify: the conflict choice looks like the source choice. Pass.

### N1-07 Step 5, Run (`23-rebrickable-run`, #519)

- **Drawn:** W0-07 in B′: one progress bar for the run, one per direction; violet what is done, dashed what is still to do, to scale (4 of 7, 4 of 5, 0 of 2).
- **Kept:** all approved copy.
- **Differences from the shipped Collection sync (round 0, approved):**
  - **New:** the whole step. The shipped sync shows only the busy button label ("Pulling", "Sending to Rebrickable").
  - **Derived:** the run continuing in Jobs, and Stop after this one; both follow the functionality rule and are yours to overrule.
- **SUCCESS:** Check: bars to scale from zero, the same notation as the copy bars. Say: how far, how long, and that you can leave. Pass.

### N1-08 Step 6, Result (`24-rebrickable-result`, #519)

- **Drawn:** W0-08 in B′: here and there side by side; the failed send hatched with its word and a Retry; the no-undo sentence for Rebrickable in the info box.
- **Kept:** all approved copy; "Open the set" is singular for the one set of the sample.
- **Differences from the shipped Collection sync (round 0, approved):**
  - **Kept:** "Open sync log", Retry, the failed state (here a ticked quantity change that Rebrickable did not answer).
  - **Changed:** the shipped banners ("Sent [n] changes to Rebrickable · [n] failed") become the two side blocks; "Undo this pull" becomes "Undo this run", with "It cannot change what was sent to Rebrickable."
  - **New:** "A change on Rebrickable cannot be undone here. To reverse it, change it back on Rebrickable or send again." (#517 asks for it), the Minifigures check.
- **SUCCESS:** Say: what changed where, and what failed. Check: 6 of 7 done, 1 failed, as the parts add up. Pass.

### Changed approved frames

**C-01 The Workbench row gains "Sync"** (frames 06, 07, 09, 10, 11, 13, 14, 16)

- **Change:** Sync is the last entry of the Workbench row (round 0, question 3). 0.010 % of each 1440 frame changes; the 390 frames do not change in view, since the phone row scrolls and Sync sits past the right edge until scrolled to.
- **How:** `../sources/b/b_frames.py` builds them; the round 1 changes are its defaults since the approval.
- **SUCCESS:** Unify: Sync looks like every other Workbench entry. Pass.

**C-02 Tools & Admin (R2-05)** (frame 01)

- **Dropped:** the "Collection sync" row from Your collection; its old page redirects to the hub (#518).
- **Text (brick-work-marketing, 19.11.):** the group hint "Bring it in, keep it in step, see it counted." becomes "See it counted and keep its details tidy."; Sets and parts loses "Lost Parts from Rebrickable": "How parts are grouped and which part list a new set starts on."; Keys and sources: "See how the local catalogue stands and which sites have a key." (no key is entered there now, per product).
- **Phone:** the change is below the 390 frame’s fold, so the 390 frame does not change in view.
- **SUCCESS:** Say: the group says only what it still does. Pass.

**C-03 Settings (R2-06)** (frame 02)

- **Dropped:** "Lost Parts from Rebrickable" from Sets and parts; the rule is on the Rebrickable page (N1-04).
- **New:** a group "Sync" with one pointer row, "Keys and sync rules are on each site's page", note "Open Sync to connect a site or change what it syncs.", leading to Workbench · Sync (#517; note brick-work-marketing, 19.11.).
- **Derived:** on the phone, the expert group moves below the 390 fold.
- **SUCCESS:** Say: one place for every sync rule. Pass.

### New components

Drawn inside the frames above; there is no separate sheet for them.

- **NC-01 Step bar:** Six labelled segments: ink and a tick for done, violet for the current step, divider for later ones. On the phone: "Step n of 6 · name · next: name" over six short segments.
- **NC-02 Radio row:** One of several long options: a 22 px ring, violet ring and dot when chosen, title and note.
- **NC-03 Select field:** The input’s box with a chevron, for a choice from a list.
- **NC-04 Filter chip:** A 34 px chip with a count; chosen in violet soft with a violet edge, as the source choice.
- **NC-05 Three-way choice:** The approved source choice with three options and a line under each.
- **NC-06 Info box:** An ink rule on the left over the pressed-row ground, for the one sentence a step must not hide.
## Dark

Every frame above also exists in dark (`dark-<width>`); the dark values and the picture-tile rule are in `../BRAND.md` § 3. R2-03’s “Dark mode: built from these roles after your approval … not shown” is superseded: the dark round (#512) drew dark and Ulf approved it.

## The stylesheet for the app (#492)

`../sources/b/b_frames.py` exports the frames' CSS as plain string literals, read by ast: `B_RESETS` (the frame page only) and `B_COMPONENTS`, a tuple of the round 2, round 3 and round 6 rules in cascade order, from which the app writes `static/brickwork/b-prime.css` scoped under `.bp`. `.bp` sets the base font (400 15px/1.45 var(--tw-font)) and colour itself, since they sit in the frame's `html,body` reset. Fields, picture tiles and their alt text use `--tw-field`, `--tw-tile` and `--tw-tile-ink`, now in TOKENS. The only dark swaps left in `SWAPS` are the three rgba values with no token: the sheet's shadow, the scrim and the hatched tag's tint. The split changed no pixel, light or dark.

W-Q6 (#526 round, approved 19.11.): a part tile's (`.ptile`) number in dark is `--tw-tile-ink`, #4A524F on the #E4E6E2 tile, 6.4:1. Before, it was the muted text colour at 2.08:1. Light is unchanged, because the light tile ink is the muted text colour. It changed the dark frames 14, 15 and 16.

## Commission N, round 2 (#517, #520 to #524, #531)
Brickset, BrickLink, Brick Owl, Import & export, the complete export and the list tags of #531 in B′ (review artifact https://claude.ai/artifact/1sWRRsfiYxkEgHXxKxrsUn, version 5; approved 2026-11-20), built by `../sources/n/n2_frames.py`. Every frame is new except three that change approved frames (N2-13 to N2-15, new folders beside `21`, `04` and `12`). A step that differs from the Rebrickable one only by the site's name is not drawn again: Brickset connect, pick, preview, run and result are N1-03 and N1-05 to N1-08; Brick Owl connect, pick and preview are N2-04 and N2-17 and N2-18 with collection lots and its budget line. Collector-first (Ulf, 2026-11-20, #521): no seller features. Wording by brick-work-marketing, facts by brick-work-product.

### N2-01 Brickset, the page at rest (`25-brickset`, #520)

- **Drawn:** The Rebrickable page at rest in the same parts: account, last runs, What syncs. Brickset has no purchase date, price or condition field; the page says so once.
- **Fact:** the daily budget is 100 calls, only getSets is charged (shipped docs); drawn as "0 of 100 calls".
- **SUCCESS:** Say: this site’s state and its one action. Unify: the same parts as N1-02. Pass.

### N2-02 Brickset, choose what (`26-brickset-choose-what`, #520)

- **Drawn:** Fields per direction for Sets, the eight flags (names are yours at Brickset, shown as tags on the copy), minifigures, and what happens when both sides differ.
- **Open (product):** "New and used counts" is drawn without a direction: the field name is unconfirmed and the app session checks it with a live call; if it fails, the row goes.
- **SUCCESS:** Express: fields are checkboxes, direction a segment. Say: what is never sent. Pass.

### N2-03 BrickLink, the page at rest (`27-bricklink`, #521)

- **Drawn:** Account, last runs, What syncs, and the wanted-list file. Collector-first (your decision of 20.11.): orders come in; store inventory is only your own loose stock, labelled that way; no order-fulfilment tools.
- **Fact:** the daily budget is 4,400 calls, a margin under the account’s 5,000.
- **State:** drawn after connecting and before the first sync, a later state than the hub card ("Not connected").
- **SUCCESS:** Say: connected, not synced yet, and what a file import last did. Pass.

### N2-04 BrickLink, connect (`28-bricklink-connect`, #521)

- **Drawn:** BrickLink ties the token to one IP address: the page shows this install’s address to register, then the four values.
- **Open (product):** whether BrickLink’s API needs a store registration is unconfirmed; the page says only what is confirmed.
- **SUCCESS:** Say: why a token can stop working. Check: nothing but the four values is typed. Pass.

### N2-05 BrickLink, choose what (`29-bricklink-choose-what`, #521)

- **Drawn:** Orders in, loose stock in or both ways, price guide in (region, condition, stock guide when nothing sold). BrickLink’s API offers no wanted lists and no collection, so wanted lists go by file.
- **Cut:** status and payment back to BrickLink (a seller action).
- **Open (product):** "Orders since" is a Brick Work setting and "Received and paid" its default; neither exists in the app yet.
- **SUCCESS:** Express: direction by segment, rules by checkbox and select. Pass.

### N2-06 BrickLink, wanted list by file (`30-bricklink-wanted-file`, #143, #521)

- **Drawn:** Pick a wishlist, see the file, download it, then upload it on BrickLink’s website; Brick Work does not see what happens there.
- **Sample:** the XML is a sample; #143 defines the real file.
- **SUCCESS:** Say: three steps, one per card. Pass.

### N2-07 Brick Owl, the page at rest (`31-brickowl`, #522)

- **Drawn:** Account, today’s budget, What syncs. Brick Owl has a real collection and wishlist API.
- **Fact:** 600 requests a minute and 2,000 collection reads a day; the other kinds read "per-endpoint quota" (product).
- **Cut:** inventory for sellers (collector-first).
- **SUCCESS:** Say: what is left of the day. Check: no number that is not published. Pass.

### N2-08 Brick Owl, choose what (`32-brickowl-choose-what`, #522)

- **Drawn:** Collection in or both ways, each wishlist linked to a Brick Work wishlist, orders in.
- **Cut:** tracking, note, status and feedback back to Brick Owl; the inventory card.
- **SUCCESS:** Express: direction by segment. Pass.

### N2-09 Brick Owl, run with a budget (`33-brickowl-run`, #522)

- **Drawn:** A run that stops by itself at the day’s collection-read budget; the rest waits for tomorrow, and nothing is lost if it stops early.
- **SUCCESS:** Say: how far, how many reads are left, and that stopping is safe. Pass.

### N2-10 Import & export (`34-import-export`, #523)

- **Drawn:** Every file the issues name, in and out, in one place, each with Choose; every file goes through the same steps.
- **Open:** only formats an issue names are drawn; the file type of "Part Runner and order files" is not confirmed.
- **SUCCESS:** Condense: one page for all files. Pass.

### N2-11 The complete export (`35-own-export`, #524)

- **Drawn:** What to include with counts, one zip with a manifest, a JSON file and one CSV per table. Keys and passwords never leave Brick Work. Marketing’s screenshot 3 at 390.
- **SUCCESS:** Say: what is in the file and what never is. Pass.

### N2-12 Re-import, preview (`36-re-import-preview`, #524)

- **Drawn:** The same preview as every sync: differences, one choice per row or for all, one Undo.
- **SUCCESS:** Unify: the Preview of N1-06. Pass.

### N2-17 BrickLink, pick orders and lots (`41-bricklink-pick-lots`, #521)

- **Drawn:** The pick step of the lots flow: orders to pull and BrickLink lots that changed, each ticked or not. Brick Owl’s pick and preview are the same with collection lots, so they are not drawn again.
- **SUCCESS:** Say: which orders and lots this run covers. Pass.

### N2-18 BrickLink, preview (`42-bricklink-preview`, #521)

- **Drawn:** Orders in, a lot that differs, a lot gone at BrickLink; a lot gone there is never removed here unless you tick it.
- **SUCCESS:** Say: what will change. Pass.

### N2-19 When a run stops (`43-sync-errors`, #521 to #523)

- **Drawn:** Bad token, too little budget, the site down: each says what happened and ends "Nothing was changed." (marketing). Brickset and Brick Owl say the same with their names.
- **SUCCESS:** Say: what happened, what to do, that nothing was lost. Pass.

## Commission N round 2, early landing for U (#489, #551)

Two frames of N round 2 land on main ahead of the rest of commission N, because #489 (the completeness bar of a pulled copy, with its "Checked on Rebrickable" label) is built in U for v1.2. Approved by Ulf on 2026-11-20 ("version 8 approved", [review artifact](https://claude.ai/artifact/1sWRRsfiYxkEgHXxKxrsUn) version 8). The other round 2 frames, the sources that build them (`sources/n/n_frames.py`, `n2_frames.py`, which need round 1's changed `b_frames.py`) and their notes stay on `design/sync-n` (draft PR #528) until N's build. Frame `48` is built on the approved Sets frame (`04`) and frame `44` on the approved Set detail frame (`12`); everything not named below is as in those frames.

### N2-20 Set detail, the source of a copy (`44-source-chip`, #551, #489)

- **Drawn:** Added via is one fixed value that never changes, shown as a chip (Added via Rebrickable sync, BrickLink file, By hand, Before this release); Last synced from is a separate line with the site, the list names and the date ("Last synced from Rebrickable: Main collection, 18 Nov, 21:40"). The copy states how it was checked: "Checked on Rebrickable" in the header and the Info card.
- **Changed from the first form (`39`):** no list tag under the name; the Info card reads "Tags: Not recorded" again, since a list name is source detail, not a tag.
- **Open (product):** whether a row can have more than one "last synced from" (a set in two lists, or from two sites).
- **SUCCESS:** Say: where this copy came from, when it last met a site and who checked it. Unify: the chip is a tag as everywhere in B′.

### N2-21 Sets, the Source filter (`45-sets-source-filter`, #551)

- **Drawn:** two rows of chips with counts under the tabs, nothing chosen: Added via (By hand 2, Rebrickable sync 4, Before this release 1) and Last synced from (Rebrickable · Main collection 5, Bought 2026 2, Lent to a friend 1). The two are separate facts: a set added by hand can be matched by a later sync. A chip with no rows is not shown. A Source row with a single chip is not shown when that chip matches every listed row, since it would filter nothing; a single chip that narrows the list is shown (Ulf, 2026-11-26, after #723: "Only if it matches all (Recommended)"; frames 05 and 48 stay as drawn). The item lists (tokens-only screens, #501) take the same row.
- **Supersedes (wiki-agent decision, 2026-11-25):** `45` is the Sets page with the Source filter (the chips show whenever a chip has rows); `04`, `05` and `48` stay as the base.
- **Inherited:** the 320 and 375 overflow of the approved Sets frame (`04`).
- **SUCCESS:** Condense: two rows replace the list chips. Say: filter by how it arrived and by the list it was last synced from.

### N2-22 Step 3, Pick sets, the list names as source detail (`46-rebrickable-pick-sources`, #531, #551)

- **Drawn:** each set row names the Rebrickable lists it is in as a plain line; the checkbox keeps them as the set's source detail. 6 of 7 picked.
- **Changed approved text:** N1-05's "Sets you do not pick stay as they are on both sides" reads "A set you do not pick keeps its copies, counts and fields; only its list names follow their lists" (Ulf, 2026-11-20: "approved - add detailed descriptions in the docs").
- **SUCCESS:** Say: which lists each set is in; the names are not a second kind of tag.

### N2-23 Step 4, Preview of list names (`47-rebrickable-preview-sources`, #531, #551)

- **Drawn:** one line per list, renamed, removed or unchanged, with the number of sets whose source detail changes; "Rename it" and "Drop the name".
- **SUCCESS:** Say: what happens to the names before it happens.

### N2-24 Sets, the label of a pulled copy (`48-sets-pulled-copy`, #489)

- **Drawn:** a pulled copy shows as checked by Rebrickable: its Lost Parts are the missing parts on the bar, a pulled copy without Lost Parts shows as complete, and a line under the bar names the source, "Checked on Rebrickable". A copy Brick Work checked itself has no label. 8043-1 is pulled without Lost Parts (complete), 21028-1 with 9; the header counts follow (4 of 7 incomplete, none unchecked, 2 complete). Place: under the bar on the Sets tile and as the parts-check tag on Set detail (N2-20).
- **Separate:** the label is the origin of the check, not the origin of the copy (the Added via chip) and not the status filter of #489.
- **SUCCESS:** Say: who checked this copy. Check: no label on copies Brick Work checked itself.

### List-name rules of #531 (detailed; Ulf: "approved - add detailed descriptions in the docs", 2026-11-20; source form decided the same day, "Source detail (Recommended)")

- **Where a list name comes from:** a Rebrickable list the set is in. A set in two lists carries two names; a set in no list carries none. The names are kept as the set's source detail ("Last synced from Rebrickable: <lists>, <date>") only when "Keep each set's Rebrickable list names as its source detail" is ticked on the Pick sets step (N2-22).
- **Rename at Rebrickable:** the next run shows one line in the Preview (N2-23): "Renamed at Rebrickable to <new name>; the source detail of <n> sets changes", with the choice "Rename it". The new name replaces the old on every set whose source detail carries it, picked or not; nothing else on a copy changes (copies, counts and fields stay).
- **Removal at Rebrickable:** one line "Removed at Rebrickable; the source detail of <n> sets changes", with the choice "Drop the name"; the sets stay.
- **Unchanged list:** one line, "Unchanged; the source detail of <n> set(s)", choice "Skip".
- **No tags:** the list names are not tags on the copy, so there is no read-only tag in Tags admin and rule (b) of #531 is dropped (Ulf, version 8). The user's own tags are never touched.
- **Filter:** the Sets Source filter offers the lists under "Last synced from" (N2-21).
- **Frame 13, 2026-11-22 (#508):** the colour row draws the shipped "More colours" link at the right of the label "Colour · you choose" (it opens the full colour list under the swatches). Approved with C-3 and P-1 to P-7 on review version 11. Generator output; no other frame changed.
- **N2-25 Select mode on a Storage tile (`49-storage-select-mode`, #500, asked by brick-work-product; approved 2026-11-22):** a checkbox beside each copy's bar is the select target (copy 2 of 7213-1 and the one copy of 7938-1 are picked), beside the Sealed tag for a sealed set; a bar "2 copies picked" with Move to another storage and Cancel; Select is the button beside Print label and Edit. On the phone a storage's page is drawn for the first time (the list of storages stays as in `11`). The copy text wraps at 14 characters on the phone and stays on one line on desktop, the room left beside the checkbox.
- **Frame 12, 2026-11-22 (#507, found by brick-work's build; pending Ulf's picture check):** (1) the missing-parts numbers did not add up (8 lines, 2 shown and "+ 6 more", 10 pieces: six more lines need at least 6 pieces): now 7 lines, "+ 5 more missing lines", "Priced 7 of 7 missing lines"; (2) the part-out value is a floor under the asking price in the app, so it must sit below €46.18: "Part-out value of what is present €41.80" and "Parted out ≈ €41.80", the present value as the app shows it, "prices for 117 of 130 lines" (the app counts lines its own way; below the first screen, so the PNGs are unchanged); asking price, Worth now, Gain and the bar stay; (3) three shipped controls the frame omitted: the "Set is checked" switch row with its hint under the bar text, the line "131 different parts · all checked", and "Check missing only" on the phone as the third button. Sample numbers and shipped controls only; no layout meaning changes. Generator output; no other frame changed.
- **Frame 12, 2026-11-22 (#507, pending Ulf's picture check):** the missing-line cards draw the shipped "Found 1" and "Found all" as small secondary links beside Take n (wrapping on the phone). Behaviour decided with brick-work and not drawn: "+ 5 more missing lines" expands in place and reads "Show fewer", and hides while a search or filter shows every matching line; in view mode a group header counts what it lists. Generator output; no other frame changed.
- **Frame 16, 2026-11-22 (#511):** a line at 0 received reads "Not counted" as a dashed tag (it said "36 short", which claims a count); Filters and Sort, shipped controls the frame omitted, sit under the search field of the order list and of the count panel. The progress text keeps "· 39 still to count". Approved with P-8 on review version 12. Generator output; no other frame changed.
- **Frames 50 to 52, 2026-11-23 (#503):** the 404 page comes in three versions, rotated by the app (A "This page is the missing piece": five bricks, one hatched gap with the X chip; B "Drawer 404 is empty": a drawer with its label tape; C "We looked everywhere": a part-count checklist ending "0 of 1 found"), each in light and dark at 1440 and 390; the 500 page reads "This drawer is stuck", "Your data is safe. Try again.", buttons Try again and Back to sets, drawer label "500 · JAMMED"; the allocation line (frame 52) puts "6 available · 0 allocated" on its own line under the name and the colour. No option says "LEGO": the #544 exception covers the question pages only. The SVGs and the checklist markup are in the frame HTML (`design/sources/b/frames_404.py`); brick-work inlines them. The offline page is frame 53.
- **Frame 53, 2026-11-23 (#503):** the offline page, same tone as the 404 and 500: the drawer with the label "OFFLINE", "Your drawers are out of reach", "No connection to your Brick Work server. Your collection is safe where it is. Reconnect and try again.", one button "Try again", code line "No connection · offline"; light and dark, 1440 and 390. brick-work sizes the service-worker fallback (not a v1.2 must).
- **Screen-gate baselines vs a fresh CI render, 2026-11-23 (#657):** the six `36-Check-this-copy` states re-rendered by the baselines workflow differ from the committed baselines (#629) in 36 of 36 files, text edges only, no layout change (up to 71,000 pixels more than 3 off). A render of the commit before #657 (707c2dd6) is pixel-identical to the render after it, 36 of 36, so the cause is the render environment, not the code: the committed baselines were produced in a different one (runner image or fonts; the pinned Chrome for Testing 157.0.8103.38 is the same in `scripts/chrome.py`). Nothing was re-approved: the committed PNGs stay. A baseline set from one CI run is only comparable to a later run if the runner is the same; re-render a screen's baselines in the run that approves them.
- **Frames 59 to 62, 2026-11-23 (#654, #655):** the Wishlist as one question, "can I buy this set now at a price I accept". Tile per wanted set: picture, number with one state tag, name, theme and year (and the list in all-lists view), what I want (condition, count), my max or "No max set" with "Set max", price now for that condition (the guide only: Used avg, Used listings; the source once under the title), the gap to the max in words. State tags: Buy now filled, Wait outlined, No max, Not comparable and No price dashed. Default sort buy now first. Kept from the shipped screen: the list switch, condition and price-state chips (with a new No price chip), Select, Upload CSV, the tile and list switch. Not on the tile: the min/avg/max strip, a second source, the "Wants any" badge, the retail line. Detail (#655): the answer first, "Your wish" card, the standard Prices card with one range strip to scale, "No sales" in small type for a condition without a price, a plain sentence instead of the trend line while there is one price. Built by `design/sources/b/wl_frames.py`. Data facts from brick-work: a row with a max and no price has no state in the app and counts under "No max set"; the build needs a state for it.
- **Frames 59 to 62, 2026-11-23, corrected to the built app (#654, approved by Ulf on 2026-11-23, "Approve redrawn frames"):** the first drawing invented controls and dropped shipped ones. Now drawn as built (f404abcf): list tabs (All lists, one per list) with Manage lists, Export, Print and Download CSV; search with Filters and Sort; condition tabs (All, Used, New, Not yet filled); the state chips (new); a select checkbox on every tile; no Select, Upload CSV or Add to wishlist; the empty state sends you to Add in the top bar; the detail keeps its main panel (Consists of: Parts, Minifigures, Instructions & Box) beside the aside (Your wish, Prices) and the BrickLink and Brickset links. Open for the build: on the phone the detail picture is full width in the app, the frame draws it 110 px beside the title so the answer line is on the first screen. Corrected 2026-11-26 as a pure correction under the delegation of 2026-11-20, picture check passed 2026-11-26: the range strip's marker stands at 27 % (avg €79.14 between min €5.44 and max €280.00), not 46 %.

## Commission N round 3 (#517), approved 2026-11-23

Five states of a sync run, built by `sources/n/n3_frames.py` (`build`, `check`), folders `54` to `58`; review artifact https://claude.ai/artifact/Qa2FNm4rBCtLN9uXZ2q9kx, version 2. Product decided the facts behind them (2026-11-23): a run waits up to 10 minutes for a rate limit, then stops with "Run again later" and keeps its place (decided, pending an app check); "Run the rest tomorrow" is a reminder in text with the time the budget returns, no schedule button (no scheduled runs in N); the bulk choices on waiting rows are "Keep Brick Work for all" and "Take Rebrickable for all", no "newest wins" for now; a long run saves its place regularly and goes on after a server restart, and no frame names the number.

- **R3-01 (`54-sync-rate-limit`):** 62 of 140 done, paused by Rebrickable, goes on in 38 s; the card says nothing is lost or repeated.
- **R3-02 (`55-sync-budget-used`):** Brickset, 100 of 100 calls, the run stopped after 61 of 83 sets; the rest waits and is run again when the budget is back.
- **R3-03 (`56-sync-conflicts-waiting`):** the result of a run with 3 rows that differ on both sides: none was changed; Choose per row, or Keep Brick Work / Take Rebrickable for all.
- **R3-04 (`57-sync-long-run`):** 1,120 of 4,000 done, about 1 h 50 min left; closing the page is safe; Open Jobs.
- **R3-05 (`58-sync-nothing-to-sync`):** "Everything already matches", with what was compared and when.
- **SUCCESS:** Say: each frame states what happened and that nothing was lost. Pass. Dark and 320/375 follow from the approved parts.

## Commission N round 4 (approved by Ulf 2026-11-24, "push your designs - they are approved"): frames 66 to 77

- **`66-sync-run-busy`:** the Preview step while the run is applied in one request (product, 2026-11-24): the footer button reads "Running 7 changes" with a spinner and is dimmed, Back is dimmed, and a line under it says to keep the page open and that the page above is locked. Built from frame 22 (`n4_frames.py`, imported from `n_frames.py`).
- **Frame 23 (`23-rebrickable-run`) stays approved** as the target of the job runner and the progress view, #685. The build of #519 has five steps (Connect, Choose what, Pick sets, Preview, Result) because it has no Run step until #685; frames 18 to 22 and 24 draw six.
- The sentence "Keep this page open until the run is done. Everything above is locked while it runs." is design's wording, for Ulf's check.
- **Frames 67 to 69 (Brickset, #520):** pick, preview and result drawn from what Brickset's API carries (`syncable-brickset.md`): quantities per set, 100 calls a day, rating 1 to 5 (0 is none), priority default 1, no purchase date or price.
- **Frame 70 (BrickLink result, #521):** orders pulled, lots updated, nothing sent; which store-lot fields can be written is "Unverified".
- **Frames 71 to 73 (Brick Owl, #522):** collection lots and wishlists confirmed for sets; orders and the collection's parts and minifigures "Unverified"; a lot Brick Work cannot place is skipped.
- **Frames 74 to 77 (Import & export, #523):** choose file with what the format carries, result with one Undo; export choose and result, no Undo. The Brickset CSV columns are "Unverified" until a real export is read.
- **Frame 44 supersedes frame 12 for the copy page** (wiki-agent, 2026-11-24): brick-work's frame check fails on 12 because the Source row is the only difference (21 % at 1440); brick-work points its check at 44, and 12 stays as the base of the frames. No frame changed.

## Commission N round 5 (draft, pending Ulf): every frame still missing (frames 78 to 93, the rail)

Gap list: `~/Workspace/_exports/design-brief-n/frame-gaps-n.md`. Requested by brick-work-product for Ulf, 2026-11-24: "ask design to write all missing frames".

- **G1, Workbench rail, Sync first (Ulf, 2026-11-24: "Put synch at place - (left side) on the workbench rail"):** the order is Sync, Set Inspector, Part Spotter, Lot Sorter, Part Runner, Matchmaker, Build Scout, Orders, Storage. Changed in `b_frames.GROUPS`, so every Workbench frame follows: 06, 07, 09, 10, 11, 13, 14, 16 (approved) and the Sync frames 17 to 77. A pure change of order. The phone Sync frames keep their three-entry row, now Sync first (F-04 stays Ulf's call); on the phone the row is clipped, as before, so the first items are the ones in view.
- **`78-stock-added-via`, `79-wishes-added-via` (#551):** the Added via chips and filter on loose stock and on the wishlist, as on Sets (45).
- **`80-bricklink-prices-preview`, `81-bricklink-prices-result` (#521):** the price guide: one price per row, typed prices kept unless ticked, the stock guide when nothing sold; read only, nothing sent.
- **`82` to `86` (#523):** choose file for BrickLink wanted-list and inventory XML, BrickLink order XML, Rebrickable CSV, BrickTracker and Brick Work CSV. Each says what the file carries; the columns are "Unverified" until a real file is read. Every imported row says Added via File import.
- **`87` to `92` (#523, #470):** choose what and format for the database file, insurance report, missing parts, Part Runner and order files, Brick Work CSV and the collection in another tool's format. Whether the database file holds site keys and Brickset's import columns are "Unverified".
- **`93-re-import-result` (#524):** the result of re-importing a complete export, one Undo. The run state is frame 66's busy button.
- **Design's wording, for Ulf's check:** every sentence in 78 to 93, the "Unverified" notes and "Before this release".
- **SUCCESS:** Say: one job per frame. Unify: the same Result step as every sync page. Check: counts add up in each frame. Pass. Dark and 320/375 follow from the approved parts.
- **`94-rebrickable-run-applying`, `95-sync-long-run-applying` (#685; brick-work-product, 2026-11-24):** frames 23 and 57 redrawn. The pull and the part lists apply in one transaction and cannot report "N of M", so they read "Applying the pull" with a spinner, no count and no ETA, and the pull cannot be stopped halfway. Sends and Lost Parts out keep "N of M" per call. In 95 the long run is 3,200 changes applied here plus 800 sends (640 sent of 800, about 3 min left, budget today 810 / 1,000, from the code's Rebrickable budget of 1,000), which also makes F-01's contradiction go away. 23 and 57 stay approved until Ulf approves 94 and 95.
- **Keys (brick-work-product, 2026-11-24):** "Keys are not included." on the database export (87) and the re-import result (93): keys, tokens and the Brickset password hash are never in an export; sync settings are. The approved complete export (35) already says "Settings · never includes keys"; the approved re-import preview (36) has no such line and is not changed.

## Inconsistencies in approved frames, fixed (Ulf, 2026-11-24, F-01 to F-04: "All a, going with your recommendations")

- **F-01 (`57-sync-long-run`):** corrected twice. Option A first put 5,000 on the page; product then gave the daily budgets from the code (Rebrickable 1,000, BrickLink 4,400, Brickset 100, Brick Owl 2,000; 2026-11-24), so every Rebrickable frame now reads "/ 1,000" (18, 22, 23, 54, 57, 66, 94, 95). Frame 57 reads "3,840 of 4,000 done, about 3 min left, budget today 810 / 1,000" and 95 shows the same run (3,200 changes applied, sending 640 of 800). Frame 95 replaces 57.
- **F-02 (`56-sync-conflicts-waiting`):** the head reads "137 of 140 done, 3 wait for you".
- **F-03 (`48-sets-pulled-copy`):** the phone frame carries "Checked on Rebrickable" on the first tile (7213-1, copy 1).
- **F-04 (all Sync frames, phone):** the phone sub row is the full Workbench row, as on the U frames, Sync first. Replaces the three-entry row of round 5.

## Commission N round 6 (approved by Ulf 2026-11-25, "All approved"): the interrupted run (#685, built in #707)

- **Copy, `95-sync-long-run-applying` and `57-sync-long-run`:** "If the server restarts, the run stops safely and shows what went out. Finished steps stay done." replaces "goes on from the last saved step / last sent change" (brick-work-product, 2026-11-24, from brick-work-n's build): after a restart finished stages stay done and a send in flight is never repeated, because a send is not safe to repeat.
- **`96-sync-run-interrupted`:** the run after a restart: Pull applied (Done, stays done); Sending (Interrupted) with the rows that went out (Sent), the row that was in flight (Not known) and the count (640 of 800 sent, 1 not known, 159 not sent); a note that a send is never repeated by itself; Send again and Open Jobs. The wording on the frame is design's and was approved with it.
- **Budget:** frames 57 and 95 show the same run with the Rebrickable budget of 1,000 (product, from the code), already on main with #705.
- **`96-sync-run-interrupted`, changed (brick-work-product, 2026-11-25):** the Not known row has its own choice, "Send it too" or "Leave it" (the person checks the row at the site first); Send again sends only the 159 not sent, and the Not known row stays out of it until the person chooses. The Pull applied card says "Undo for this pull is in Last runs, where this run is listed as Interrupted"; so the frame has no Undo of its own. Approved by Ulf 2026-11-25 ("approved"). The two buttons belong to the Not known row (one pair per row that is not known); the frame draws them directly under that row. This version replaces the round 6 one above.

- **`96-sync-run-interrupted`, redrawn to the build (#685, #718; Ulf, 2026-11-25: "Redraw to the app (Recommended)"; new picture approved 2026-11-25, review version 8, Q-04):** "Send it too" is a checkbox on the Not known row, off by default, in place of the two buttons; "Open the result" is a third action; only the rows that did not go out are listed (the app: the first 20, then "and N more not sent"; the frame draws three and "and 157 more"); the row sub-line is the set number and the send in lower case; the Pull applied card keeps "Undo for this pull is in Last runs, where this run is listed as Interrupted"; the info text reads "Check the row marked Not known on Rebrickable. Tick Send it too only if it is not there, then send the rest again." (both wordings: brick-work-product, 2026-11-25; the build adds them).

## Commission N picture check (approved 2026-11-27, "approve all, A and A")

Review artifact https://claude.ai/artifact/2rT6QJkS3wDAJF2ErShyAB, version 1; the rows are in `design/APPROVALS.md`. Two changes, built in #765:

- **`96-sync-run-interrupted`, pull undone:** in both undone cases (all applied, and one part not applied) the first card's heading is "Pull undone" with a plain "Undone" tag (not the hatched failed one). The sentences below do not change.
- **Record-only preview:** when the "sets compared" count is 0 and rows will be recorded, the page head is "checked <time>" plus "· last run <time>" where there is one. The empty-list line and the record-only line do not change.

Frame `94-rebrickable-run-applying` still draws the greyed Stop solid; the approved look is the app's dashed disabled style, and the frame is redrawn later.
