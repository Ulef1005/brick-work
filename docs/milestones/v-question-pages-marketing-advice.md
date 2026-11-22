# Marketing advisor on #544, the question pages P1 to P7 (2026-11-22)

Answered by the marketing advisor (ask-role, Opus 5.5) from read-only copies of the marketing role pages, the launch kit, positioning, the SEO report and the decision log, and from docs/ and CHANGELOG.md on main. It is advice: the marketing session reviews the texts (#544), and the endings marked "Ulf's" are Ulf's to decide.

Correction by the build thread: the advisor says "main is now at 95bd62fd". That is wrong. 95bd62fd is the scaffold commit on branch `v/544-question-pages` (draft PR #594). Main is 83918ec.

## Missing or stale

1. **The docs fallback is not in the decision log.** #544 credits marketing (2026-11-20) with the rule "a page whose feature the demo cannot show ends in the docs". The decision log has no entry for it, and the launch kit says every page "ends in the demo". Unverified. Edit 1 below records it.
2. **The "November 2026 Pick a Brick pause" is still unverified.** P4 does not mention it.
3. **Positioning § Claims lacks four features.** It has no row for Sell this copy, Storage with QR labels, Lot Sorter's pull list, or Order missing parts and its files. The advisor checked these claims against docs/ and CHANGELOG instead. Edit 3 adds the rows.
4. **Some button labels are v1.2's.** The docs on main describe the v1.2 screens, so the pages must deploy with v1.2 or later. Site pages deploy on release only, so this costs nothing.

## Last step per page

| # | Last step | Reason |
|---|---|---|
| P1 | Demo: Set Inspector run, `demo/workbench/check-parts/<copy>/?run=1` | The page's promise is visible in the demo. Taps answer "not saved". |
| P2 | Demo: a set's page with the Sell this copy card | The card shows from saved prices, no key needed. The text says your own install needs a BrickLink key. |
| P3 | Docs: tutorials/find-the-sets-in-a-bulk-lot/ | Lot Sorter is not in the demo. |
| P4 | Docs: how-to/order-missing-parts/ | Not in the demo. The demo's Orders list is a different screen and would mislead. |
| P5 | Demo: `demo/workbench/storage` | Storage is in the demo. The text links the labels tutorial first, since the demo prints no labels. |
| P6 | Docs: tutorials/build-from-what-you-have/, with the Matchmaker demo linked in the text | Build Scout is not in the demo. Matchmaker answers a different question (opinion). |
| P7 | **Ulf's call.** Demo: `demo/collection/sets` (advisor), or docs: how-to/sync-collection/ (strict #544 rule) | The demo's sync page shows "Key not set" and reads as broken. The Sets list shows "one list" (opinion). |

## The seven texts

Every title and meta follows the rules: "LEGO®" only as an adjective, with ® every time, or as "the LEGO Group". Title lengths are 38 to 47 characters, each meta is 155 characters or fewer, and link text never reads "LEGO.com", which the new test fails.

### P1 · /questions/missing-parts-used-set/

**Title / H1:** Which parts is my used LEGO® set missing?

**Meta:** Check a used or inherited LEGO® set against its parts list, line by line, and end with an exact list of what is missing. Free and step by step.

**The answer.** If you bought the set new, ask the LEGO Group first: its [replacement parts page](https://www.lego.com/en-us/service/replacement-parts/missing) is the route for missing pieces from a new set. For a used or inherited set, you need its parts list and some patience:
1. Find the set's parts list. It names each part, its colour and how many the set needs.
2. Spread the parts out, roughly by colour or by type, so you can find each one fast.
3. Go through the list one line at a time. Count what you find and write down the difference. A line with 4 needed and 3 found is 1 missing.
4. Leave the spare parts aside. A set comes with a few spares, and they are not part of the build.
5. Check the minifigures after the parts, as whole figures.
6. Keep the list of gaps. It is your shopping list, and it tells you whether the set is worth finishing.

**How Brick Work does it.** Set Inspector walks you through one copy of a set, part line by part line, and saves every answer as you go.
- Pick the copy and an order to work in: the inventory order, by colour, largest first or by category.
- For each line, count with − and + and confirm what you found. The difference is recorded as missing. **Missing** marks the whole line, **Skip for later** leaves it open, and **Undo** takes back the last answer.
- The part's name is filled with its own colour, so you can match it against the pile.
- Minifigures come after the parts. Spare parts are optional and never counted as missing.
- The top of the page shows how far you are, such as "142 of 375 parts". Close the page and resume any time.
- At the end you get the list of everything still missing. Part Runner, Matchmaker and the BrickLink wanted-list export all work from it.

The copy needs its part list from the catalogue that Brick Work loads. (docs/how-to/check-set-parts.md; CHANGELOG Unreleased #495)

**Last step:** Try Set Inspector in the demo. It is the real interface on an invented collection, and nothing you tap is saved.

Flag: the copy rule asks to name the *free* route *for new sets*. Both rest on a search snippet, so the advisor left "free" out (unverified).

### P2 · /questions/used-set-worth/

**Title / H1:** What is my incomplete LEGO® set worth?

**Meta:** Start from recent used sales, take off each missing part and minifigure, then compare with the part-out value. How to price an incomplete LEGO® set.

**The answer.** An incomplete set is worth what a complete used one sells for, less what it would cost a buyer to finish it. Its parts sold one by one set the lowest price that makes sense.
1. Look up what the set has actually sold for used recently. Use sold prices, not asking prices.
2. List what is missing: each part and each minifigure.
3. Take off what each missing piece costs to buy used. Minifigures usually make the biggest difference.
4. Work out the part-out value: what all the parts you have would fetch sold one at a time.
5. Compare the two. If the parts are worth clearly more than the set, parting out may pay, if the work and fees are worth it to you. If the figures are close, selling the set whole is less work.
6. Say exactly what is missing in the listing. Buyers pay more for a set they can trust.

**How Brick Work does it.** On a set's page, Brick Work puts the figures side by side for the copy you hold:
- **Prices:** BrickLink's used and new sold average for the set, with the number of sales and the age of the quote.
- **Parted out:** what the copy's parts and figures fetch one at a time. It is shown only when at least 90 % of the lines have a price, and a line says by how much the parts beat the copy's value when they clearly do.
- **Sell this copy:** an asking price that starts from the used sold average and takes off the used price of each missing part and figure, line by line. A line with no fresh price is marked and left out of the sum. The part-out value is the floor.
- **Preview** writes a listing text that names the set, its condition, what is missing and whether the box and instructions are there. You can edit and copy it. Brick Work posts nothing.

The prices come from BrickLink, so your own install needs a BrickLink key. Without one you only see prices already stored. The deductions are exact once you have checked the copy part by part. (docs/tutorials/value-and-selling.md; CHANGELOG 1.1.0 #53)

**Last step:** Open a set in the demo and read its Sell this copy card. The demo uses saved prices, so it needs no key.

### P3 · /questions/sets-in-a-bulk-lot/

**Title / H1:** Which LEGO® sets could my bulk lot be from?

**Meta:** Rare and printed parts point to few sets. How to find the LEGO® sets a mixed bulk lot may have come from, then pull one set's parts out of the pile.

**The answer.** No photo of a pile tells you its sets. The parts that only a few sets hold do.
1. Pick out the evidence first: minifigures, printed parts and unusual parts in unusual colours. A plain 2×4 brick is in thousands of sets and says almost nothing.
2. Look each one up in an online parts catalogue to see which sets hold it.
3. Note the sets that come up again and again. They are the sets the lot may have come from.
4. Take the strongest candidate's parts list and check it against the pile.
5. Expect gaps. A bulk lot is often parts of many sets, and rarely one set complete.

**How Brick Work does it.** In Brick Work, a lot is a pile of loose parts you record. You enter it part by part, with Part Spotter and your camera or by hand. Then Lot Sorter's set detection answers **Which sets are in this lot?** with the sets the lot may have come from, ranked by score:
- The score weighs the parts that point to a set: distinctive parts (held by 25 sets or fewer), printed parts only that set holds, and how many of its part lines the lot has. Parts that more than 300 sets hold are left out by default.
- The best candidate scores 100 %, and the others are measured against it. It is evidence, not a probability. Each candidate says why, such as "20 of 133 distinctive parts found".
- **Details** shows the distinctive parts found and the ones still to dig for. Narrow the list by score, theme, years and size.
- A part with a sticker can be pinned to the set whose sticker you recognise. A confirmed sticker counts strongly.
- Open a candidate's **Pull list** and tick the parts as you dig them out. **Make it a copy** moves them into a new copy of the set and records what you did not find as missing. One Undo takes it back.

Set detection only reads and changes nothing in your collection. (docs/how-to/find-the-sets-in-a-bulk-lot.md; docs/tutorials/find-the-sets-in-a-bulk-lot.md; CHANGELOG 1.1.0 #412)

**Last step:** Follow the tutorial: find the sets in a bulk lot. It takes about 15 minutes, with screenshots of every step.

### P4 · /questions/buy-missing-parts/

**Title / H1:** Missing LEGO® parts: Pick a Brick or BrickLink?

**Meta:** Buying missing LEGO® parts: use your own loose parts first, then batch one list across your sets and split it between Pick a Brick and BrickLink.

**The answer.** The cheapest part is the one you already own. After that, a single list beats many small orders.
1. **Check your own loose parts first.** A spare from another set or a bulk lot costs nothing.
2. **Batch.** Put the missing parts of every set you want to finish into one list before you buy anything. Orders and shipping add up per order, not per part.
3. **Split the list by source, line by line.** The LEGO Group's [Pick a Brick](https://www.lego.com/en-gb/pick-and-build/pick-a-brick) sells new single parts by their element number. BrickLink is a marketplace of sellers, with new and used parts and older parts that are no longer made.
4. **Compare per line, not per shop.** Neither source is cheaper for everything.

**How Brick Work does it.** **Order missing parts** turns the gaps you recorded into one order list:
- Tick the sets you want to finish. Sets tagged to sell or part out are left out by default.
- Each line is one part, colour and condition, combined over the ticked sets. A chip names the set it comes from, such as `6080-1 ×2`.
- Turn on **Use loose stock** in the repair settings, and your loose parts are taken off first. It is off until you turn it on.
- Each line goes to BrickLink, with its stored price and its age, or to Pick a Brick when Brick Work holds the part's element number. You choose. Brick Work does not ask the LEGO Group for prices, so it cannot pick the cheaper source for you.
- Download a BrickLink wanted list (XML) and a Pick a Brick file (CSV) to upload on each site.
- Before you buy, Part Runner leads you through your drawers to pull what you already hold.

The page only reads and changes nothing in your collection. (docs/how-to/order-missing-parts.md; docs/how-to/plan-repairs.md; CHANGELOG 1.1.0 #225, #54; `repair_use_loose_stock=False`)

**Last step:** Read the guide: order the parts all your sets are missing.

Flags: there is no "cheapest price" claim and no mention of the Pick a Brick pause (unverified). The advisor also left out the docs' claims about the LEGO Group's service ("rolling out by country", "400 part types per upload"). Step 3's descriptions of Pick a Brick and BrickLink are general knowledge (unverified).

### P5 · /questions/store-and-label-parts/

**Title / H1:** How should I store and label loose LEGO® parts?

**Meta:** Sort by part type, give every bin and drawer a name, and keep a list of what is where, including LEGO® sets stored taken apart. Then label the bins.

**The answer.** Storage works when you can find a part without opening every box.
1. **Sort by part type, not by colour.** Finding a red 1×2 plate among all the 1×2 plates is faster than finding it among all the red parts.
2. **Give every place a name.** Room, shelf, drawer, bin: "Shelf A, Drawer 3" beats "the grey box".
3. **Nest the places.** A bin sits in a drawer, the drawer on a shelf. Then a short name is enough.
4. **Keep a list of what is where,** including sets you stored taken apart, each in its own bag or box.
5. **Label last,** once the places have settled. A label that matches your list is the one you trust.

**How Brick Work does it.** In **Storage**, every place is a storage you name: a box, shelf, drawer, bin, bag, case, cabinet or room. Storages can sit inside each other.
- Give a set copy, a minifigure or a part lot its place, one at a time or many at once. Anything without a place shows under **Not stored**.
- Open a storage to see what it holds, grouped as sets, minifigures and part lots, with search and filters.
- **Print labels** makes QR bin labels on A4 sheets (21 or 14 per sheet) or 62 mm label tape. Each label carries a short id that is never reused. Scan it with your phone camera to open that bin's contents. These are bin labels with a QR code, not labels with part pictures.
- Every move is listed in the storage's **History**, with **Undo**.

(docs/tutorials/storage-and-labels.md; docs/how-to/storage.md; docs/how-to/storage-labels.md; CHANGELOG 1.1.0 #31)

Before the last step: How to print the labels (the tutorial; the demo prints no labels).

**Last step:** Open Storage in the demo. It shows a sample collection filed in its storages, and nothing is saved.

### P6 · /questions/build-from-loose-parts/

**Title / H1:** Which LEGO® sets can my loose parts build?

**Meta:** Rank official LEGO® sets by how much of each your loose parts already make, see what the best ones still lack, and turn one into a set you own.

**The answer.** There are two questions here, and both need a list of the loose parts you hold:
- **Sets you do not own:** which official sets do my parts already mostly make? Compare your list with each set's parts list. Count only the exact part in the exact colour, and the minifigures as whole figures. A set at 90 % is often a small order away.
- **Sets you own but cannot finish:** which of my incomplete sets can my loose parts fill? Compare your loose parts with what each set is missing.

Without a list of your parts, neither question has an answer. Recording your loose parts is the real first step.

**How Brick Work does it.**
- **Build Scout** ranks every set in the catalogue by how much of it your loose stock covers, such as "398 of 430 · 93 %". It also shows the missing parts, the missing minifigures and an approximate cost to finish. Narrow it by theme, years, size and which stock counts.
- A part in another colour is shown as a swap and never counted in the percentage.
- **Build it · make a copy** moves the parts you hold into a new copy of the set and records what is still missing on it, with **Undo**. **Missing parts · XML** downloads the rest as a BrickLink wanted list.
- **Matchmaker** answers the second question. It lists your incomplete copies that your loose stock can advance, such as "covers 7 of 12 missing". **Give** or **Take** moves the parts across. (Link: See Matchmaker in the demo.)

Both work from the catalogue and the stock on your own install. (docs/how-to/find-sets-to-build.md; docs/tutorials/build-from-what-you-have.md; docs/how-to/match-stock-to-sets.md; CHANGELOG 1.1.0 #9)

**Last step:** Follow the tutorial: build from what you have.

### P7 · /questions/track-your-collection/

**Title / H1:** How do I keep my LEGO® collection in one list?

**Meta:** Sets, minifigures, loose parts and missing parts in one list. Bring Rebrickable and Brickset over, import BrickLink and BrickTracker files, keep it yours.

**The answer.**
1. **Choose one list as the one you trust.** Everything else feeds it, and you stop asking which list is right.
2. **Record more than sets.** Loose parts, minifigures and what each copy is missing are what you look up most when you build.
3. **Bring your lists over instead of retyping them.** Most collection sites and apps export a file, and some can be read directly.
4. **Record each copy on its own.** Two copies of the same set are rarely in the same state.
5. **Keep it where you can take it with you,** with an export or a backup you control.

**How Brick Work does it.** Brick Work keeps your sets, each copy on its own, plus minifigures, loose parts, part lots, instructions and boxes in one collection on your own machine.
- **Sync with Rebrickable and Brickset.** Pull your sets and wishlist in, with a preview row by row. A pull never deletes anything in Brick Work. Sending back shows every change first, and removals stay unticked until you tick them. It needs the site's API key and your own account login. (Link: Read the sync guide.)
- **Lost Parts from Rebrickable:** a pull can mark the parts you listed as lost there as missing on the matching copy.
- **Import files:** a BrickLink wanted list or store inventory (XML), a Brickset CSV, a Rebrickable CSV, or BrickTracker's database.
- Every import shows a preview before anything is added, and can be undone.

(docs/how-to/sync-collection.md; docs/how-to/migrate.md; docs/how-to/import-from-bricktracker.md; CHANGELOG 1.1.1 #457)

**Last step:** See a collection in one list in the demo. Sync needs your own accounts, so the demo shows the list, not the sync. Rewrite this page when N ships.

## What the advisor would change

1. Record the docs-fallback rule in the decision log (edit 1).
2. Add Lot Sorter, Order missing parts and Build Scout to the demo in a later milestone. That is product's call. Opinion: it is the cheapest way for P3, P4 and P6 to end in the demo.
3. Fix P4's copy rule: "loose stock first" needs **Use loose stock**, which is off by default (edit 2).
4. End P7 in the demo's Sets list (Ulf's call).
5. Opinion: allow naming Rebrickable and BrickLink in the answer-first sections as places to look a part or set up, never as "official" (edit 5, Ulf's call).
6. Link text never reads "LEGO.com" (edit 4).
7. Before publishing, check the LEGO Group's replacement-parts page for "free" and "new sets only", and check the Pick a Brick pause.

## Proposed edits (for the marketing documents; written only once approved)

1. **Decision log, append:** "2026-11-22: brick-work (build thread, relayed by Ulf) asked for the last step and the texts of the seven #544 question pages, given what the demo at 83918ec shows. Advice: P1, P2 and P5 end in the demo; P7 ends in the demo's Sets list; P3, P4 and P6 end in the docs, with P6 linking the Matchmaker demo in its text. The rule 'a page whose feature the demo cannot show ends in the docs' is recorded here for the first time. Decision: open (the P7 ending is Ulf's)."
2. **Launch kit, copy rule P4:** "**P4** promises your own loose parts first (with **Use loose stock** on: the setting is off by default) and one batched list, never 'the cheapest price'."
3. **Positioning § Claims, new rows:**
   - Sell this copy: shipped 1.1.0, #53, needs a BrickLink key.
   - Storage and QR labels: shipped, Storage 0.5.0 and labels 1.1.0, #31; QR bin labels, not part pictures.
   - Order missing parts with its BrickLink XML and Pick a Brick CSV: shipped 1.1.0, #225 and #54; loose stock only with Use loose stock on, never "cheapest".
   - Lot Sorter's pull list and Make it a copy: shipped 1.1.0, #412; the lot is entered part by part, and the copy says "may have come from".
4. **Launch kit, copy rules:** "Link text never reads 'LEGO.com': the #544 name test fails a bare 'LEGO'."
5. **Positioning § Third-party names (opinion, Ulf's call):** "On the question pages' answer-first sections, Rebrickable and BrickLink may be named as places to look a part or set up; never 'official' or 'the only'."
