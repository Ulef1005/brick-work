# Build notes, B′ screens

Generated from the review rounds of commission U (review artifact https://claude.ai/artifact/FX8PAj3J9cgVkY42oPGc8a); the approvals are in `../APPROVALS.md`. For each approved item: every difference from the shipped screen, as listed under it in its round. A shipped text or control not named here stays as shipped, restyled through the tokens.

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
| T9 | Manage | Tools & Admin pages: Identify history, Jobs, Catalogues & keys, API tokens, Collection sync, Appearance, Not found | `50-Tools-and-admin-pages:identify-history`, `51-System-pages`, `53-Jobs-and-maintenance`, `54-Catalogues-and-keys`, `55-Api-tokens`, `56-Collection-sync` | R2-05 and R2-06: the rows, the label column, the sub-page header. |
| T10 | Shell | Jump results and the module states (loading, error, stale, thin data, no data, listings only) | `06-App-shell:jump`, `16-Module-states` | R2-01 shell and R2-04 status (shape and word); a loading state is a dashed box, an error the danger word. |

T8 Statistics: the chart colour is decided (ink bars, violet only where a bar means found or complete; BRAND.md § 10).

## Dark

Every frame above also exists in dark (`dark-<width>`); the dark values and the picture-tile rule are in `../BRAND.md` § 3. R2-03’s “Dark mode: built from these roles after your approval … not shown” is superseded: the dark round (#512) drew dark and Ulf approved it.

## The stylesheet for the app (#492)

`../sources/b/b_frames.py` exports the frames' CSS as plain string literals, read by ast: `B_RESETS` (the frame page only) and `B_COMPONENTS`, a tuple of the round 2, round 3 and round 6 rules in cascade order, from which the app writes `static/brickwork/b-prime.css` scoped under `.bp`. `.bp` sets the base font (400 15px/1.45 var(--tw-font)) and colour itself, since they sit in the frame's `html,body` reset. Fields, picture tiles and their alt text use `--tw-field`, `--tw-tile` and `--tw-tile-ink`, now in TOKENS. The only dark swaps left in `SWAPS` are the three rgba values with no token: the sheet's shadow, the scrim and the hatched tag's tint. The split changed no pixel, light or dark.

W-Q6 (#526 round, approved 19.11.): a part tile's (`.ptile`) number in dark is `--tw-tile-ink`, #4A524F on the #E4E6E2 tile, 6.4:1. Before, it was the muted text colour at 2.08:1. Light is unchanged, because the light tile ink is the muted text colour. It changed the dark frames 14, 15 and 16.

## Commission N round 2, early landing for U (#489, #551)

Two frames of N round 2 land on main ahead of the rest of commission N, because #489 (the completeness bar of a pulled copy, with its "Checked on Rebrickable" label) is built in U for v1.2. Approved by Ulf on 2026-11-20 ("version 8 approved", [review artifact](https://claude.ai/artifact/1sWRRsfiYxkEgHXxKxrsUn) version 8). The other round 2 frames, the sources that build them (`sources/n/n_frames.py`, `n2_frames.py`, which need round 1's changed `b_frames.py`) and their notes stay on `design/sync-n` (draft PR #528) until N's build. Frame `48` is built on the approved Sets frame (`04`) and frame `44` on the approved Set detail frame (`12`); everything not named below is as in those frames.

### N2-20 Set detail, the source of a copy (`44-source-chip`, #551, #489)

- **Drawn:** Added via is one fixed value that never changes, shown as a chip (Added via Rebrickable sync, BrickLink file, By hand, Before this release); Last synced from is a separate line with the site, the list names and the date ("Last synced from Rebrickable: Main collection, 18 Nov, 21:40"). The copy states how it was checked: "Checked on Rebrickable" in the header and the Info card.
- **Changed from the first form (`39`):** no list tag under the name; the Info card reads "Tags: Not recorded" again, since a list name is source detail, not a tag.
- **Open (product):** whether a row can have more than one "last synced from" (a set in two lists, or from two sites).
- **SUCCESS:** Say: where this copy came from, when it last met a site and who checked it. Unify: the chip is a tag as everywhere in B′.

### N2-24 Sets, the label of a pulled copy (`48-sets-pulled-copy`, #489)

- **Drawn:** a pulled copy shows as checked by Rebrickable: its Lost Parts are the missing parts on the bar, a pulled copy without Lost Parts shows as complete, and a line under the bar names the source, "Checked on Rebrickable". A copy Brick Work checked itself has no label. 8043-1 is pulled without Lost Parts (complete), 21028-1 with 9; the header counts follow (4 of 7 incomplete, none unchecked, 2 complete). Place: under the bar on the Sets tile and as the parts-check tag on Set detail (N2-20).
- **Separate:** the label is the origin of the check, not the origin of the copy (the Added via chip) and not the status filter of #489.
- **SUCCESS:** Say: who checked this copy. Check: no label on copies Brick Work checked itself.
- **Frame 13, 2026-11-22 (#508):** the colour row draws the shipped "More colours" link at the right of the label "Colour · you choose" (it opens the full colour list under the swatches). Approved with C-3 and P-1 to P-7 on review version 11. Generator output; no other frame changed.
- **N2-25 Select mode on a Storage tile (`49-storage-select-mode`, #500, asked by brick-work-product; approved 2026-11-22):** a checkbox beside each copy's bar is the select target (copy 2 of 7213-1 and the one copy of 7938-1 are picked), beside the Sealed tag for a sealed set; a bar "2 copies picked" with Move to another storage and Cancel; Select is the button beside Print label and Edit. On the phone a storage's page is drawn for the first time (the list of storages stays as in `11`). The copy text wraps at 14 characters on the phone and stays on one line on desktop, the room left beside the checkbox.
- **Frame 12, 2026-11-22 (#507, found by brick-work's build; pending Ulf's picture check):** (1) the missing-parts numbers did not add up (8 lines, 2 shown and "+ 6 more", 10 pieces: six more lines need at least 6 pieces): now 7 lines, "+ 5 more missing lines", "Priced 7 of 7 missing lines"; (2) the part-out value is a floor under the asking price in the app, so it must sit below €46.18: "Part-out value of what is present €41.80" and "Parted out ≈ €41.80", the present value as the app shows it, "prices for 117 of 130 lines" (the app counts lines its own way; below the first screen, so the PNGs are unchanged); asking price, Worth now, Gain and the bar stay; (3) three shipped controls the frame omitted: the "Set is checked" switch row with its hint under the bar text, the line "131 different parts · all checked", and "Check missing only" on the phone as the third button. Sample numbers and shipped controls only; no layout meaning changes. Generator output; no other frame changed.
- **Frame 12, 2026-11-22 (#507, pending Ulf's picture check):** the missing-line cards draw the shipped "Found 1" and "Found all" as small secondary links beside Take n (wrapping on the phone). Behaviour decided with brick-work and not drawn: "+ 5 more missing lines" expands in place and reads "Show fewer", and hides while a search or filter shows every matching line; in view mode a group header counts what it lists. Generator output; no other frame changed.
- **Frame 16, 2026-11-22 (#511):** a line at 0 received reads "Not counted" as a dashed tag (it said "36 short", which claims a count); Filters and Sort, shipped controls the frame omitted, sit under the search field of the order list and of the count panel. The progress text keeps "· 39 still to count". Approved with P-8 on review version 12. Generator output; no other frame changed.
- **Frames 50 to 52, 2026-11-23 (#503):** the 404 page comes in three versions, rotated by the app (A "This page is the missing piece": five bricks, one hatched gap with the X chip; B "Drawer 404 is empty": a drawer with its label tape; C "We looked everywhere": a part-count checklist ending "0 of 1 found"), each in light and dark at 1440 and 390; the 500 page reads "This drawer is stuck", "Your data is safe. Try again.", buttons Try again and Back to sets, drawer label "500 · JAMMED"; the allocation line (frame 52) puts "6 available · 0 allocated" on its own line under the name and the colour. No option says "LEGO": the #544 exception covers the question pages only. The SVGs and the checklist markup are in the frame HTML (`design/sources/b/frames_404.py`); brick-work inlines them. The offline page is frame 53.
- **Frame 53, 2026-11-23 (#503):** the offline page, same tone as the 404 and 500: the drawer with the label "OFFLINE", "Your drawers are out of reach", "No connection to your Brick Work server. Your collection is safe where it is. Reconnect and try again.", one button "Try again", code line "No connection · offline"; light and dark, 1440 and 390. brick-work sizes the service-worker fallback (not a v1.2 must).
- **Frames 59 to 62, 2026-11-23 (#654, #655):** the Wishlist as one question, "can I buy this set now at a price I accept". Tile per wanted set: picture, number with one state tag, name, theme and year (and the list in all-lists view), what I want (condition, count), my max or "No max set" with "Set max", price now for that condition (the guide only: Used avg, Used listings; the source once under the title), the gap to the max in words. State tags: Buy now filled, Wait outlined, No max, Not comparable and No price dashed. Default sort buy now first. Kept from the shipped screen: the list switch, condition and price-state chips (with a new No price chip), Select, Upload CSV, the tile and list switch. Not on the tile: the min/avg/max strip, a second source, the "Wants any" badge, the retail line. Detail (#655): the answer first, "Your wish" card, the standard Prices card with one range strip to scale, "No sales" in small type for a condition without a price, a plain sentence instead of the trend line while there is one price. Built by `design/sources/b/wl_frames.py`. Data facts from brick-work: a row with a max and no price has no state in the app and counts under "No max set"; the build needs a state for it.
- **Frames 59 to 62, 2026-11-23, corrected to the built app (#654, pending Ulf's picture check):** the first drawing invented controls and dropped shipped ones. Now drawn as built (f404abcf): list tabs (All lists, one per list) with Manage lists, Export, Print and Download CSV; search with Filters and Sort; condition tabs (All, Used, New, Not yet filled); the state chips (new); a select checkbox on every tile; no Select, Upload CSV or Add to wishlist; the empty state sends you to Add in the top bar; the detail keeps its main panel (Consists of: Parts, Minifigures, Instructions & Box) beside the aside (Your wish, Prices) and the BrickLink and Brickset links. Open for the build: on the phone the detail picture is full width in the app, the frame draws it 110 px beside the title so the answer line is on the first screen.
