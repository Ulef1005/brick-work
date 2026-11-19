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

### R4-03 Storage (`11-storage`)

- **Changed:** the storage table has the label’s short code first, then name and type, then sets, figures and part lots in mono; the selected storage is marked in violet soft; its detail opens under its own label tape with its sets as tiles with their per-copy bars.
- **Kept:** Add storage, Purchase locations, Edit, the move hint, History; Print label sits beside Edit (labels approved in L01).
- **Empty storage:** a storage with nothing in it keeps the shipped empty state (“Bag 07 is empty.” and how to move things in), restyled; not drawn separately.
- **SUCCESS:** Unify: the same tape as Sets, so a shelf looks the same in both. Structure: storage, then contents.

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
