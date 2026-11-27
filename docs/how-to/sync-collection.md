---
audience: user
verified: 1.0
---

# Sync with Rebrickable and Brickset

*Since 0.6.0.*

Do this to bring the sets you already keep on Rebrickable or Brickset into Brick Work, or to send what you hold here back to the site. Pull never deletes anything here; send always shows the changes first and asks before it removes anything there. Open **Workbench → Sync**, then **Open** on the site. The old page under Tools & Admin sends you there. Rebrickable and Brickset each have their own page with six steps, described next; the sections after them describe the rules both share.

## A Rebrickable run

The **Rebrickable** page shows your account (API key, speed, today's budget, with **Test**, **Change** and **Remove**), the last runs and a table of **What syncs**. It reads nothing from Rebrickable until you start a run. **Start a sync** reads Rebrickable with the choices you saved and takes you through the steps; the step bar names them.

1. **Connect.** The API key and your account, side by side. The key reads Rebrickable's catalogue; your account lets Brick Work read and change your lists. **Save and test** keeps a key you paste; **Test** and **Remove** work on a stored key. A key from the environment can only be changed there. The keys step of **Get started** and the **Needs a Rebrickable key** line lead to this step.
2. **Choose what.** For each kind of data a direction: **Into Brick Work**, **Both ways**, **To Rebrickable** or **Off** (loose stock and Lost Parts are **Into Brick Work** or **Off**). Owned sets: the set lists that hold sets you own (none ticked means every list except the wishlist list) and the list that receives what you send. Wishlist: the wishlist list there and **Wishlist here**. Loose stock: the part lists that are loose parts. Lost Parts: the direction and the rules below. **When both sides differ** is fixed: the preview asks each time. **Next: pick sets** saves the choices and reads Rebrickable; **Save** only saves.
3. **Pick sets.** The sets the run could touch, **All linked**, **By list**, **By theme**, **By year** or **One by one**. In the first four every set starts picked and a chip ticks or unticks all its sets; **One by one** starts with none. A set you do not pick stays as it is on both sides. **By list** also has **Keep each set's Rebrickable list names as its source detail**; turning it off or on reads the pull again.
4. **Preview.** Every difference with a choice. A row only Rebrickable has is ticked **Add here**. A set only you have is ticked **Add there**. A set whose quantity you raised or lowered is listed with its choice. **Changed in both places** comes first, with three choices. **Keep** sends nothing. **Take** uses Rebrickable's count; it is offered only when Rebrickable has more, since a pull never lowers or removes a count here. **Send** uses yours. A set you lowered or removed since the last run, while Rebrickable still holds more, is unticked with **Keep**, **Add back here** and what sending would do there. Lost Parts, loose stock and the changes to list names have their own sections. **Before you send** names the requests, the time at about one request a second and today's budget. **Run** shows the number of changes you have chosen; a list you rename or drop counts as one. The tabs filter the rows: **To Rebrickable** includes the Lost Parts to send, and **Changed in both places** shows only the conflicts. A difference the last run did not take comes back unticked, with that said under it, so choosing every row cannot overwrite it. That covers a row left unticked, a set not picked and a kind that was off. The result calls a budget pause **waiting**, not failed, and counts cleared Lost Parts marks and changed list names among the changes here.
5. **Result.** What changed here, with **Undo this run**, and what happened on Rebrickable, with a **Retry** for a row that failed. **Undo this run** takes back the pull and the part-list pull of the run in one step; it cannot change what was sent to Rebrickable. The **Last runs** on the page keep **Undo this run** for the newest run.

A run is applied in one request, so there is no progress page; the **Run** button says it is running. A run is kept for 24 hours; after that start a new one.

## A Brickset run

The **Brickset** page works like the Rebrickable one and has the same six steps. Brickset's side holds owned and wanted sets with counts, and that is all this page syncs. Notes, ratings, flags, wanted priority, new and used counts and loose minifigures are not synced yet. Purchase date and price never leave Brick Work: Brickset has no field for them.

The page shows your account (API key and today's budget, with **Test**, **Change** and **Remove**), the last runs with **Undo this run** and a table of **What syncs**. It reads nothing from Brickset until you start a run. The account name is the username you typed when you connected, and the Sync hub shows it on the site's card too. Brickset does not return it, so a pasted hash has none. The API key line says when the key last worked, for example **checked 18 Nov**: the day of the newest call that succeeded with it. A key you replaced shows no day until its first call.

1. **Connect.** The API key and your account. Enter your Brickset **Username** and password and choose **Connect**, or open **Paste a user hash instead**. The password goes to Brickset once and is never stored. **Save and test** keeps a key you paste; a key from the environment can only be changed there. The keys step of **Get started** and the **Needs a Brickset key** line lead to this step.
2. **Choose what.** A direction for **Owned sets** and one for **Wanted sets**: **Into Brick Work**, **Both ways**, **To Brickset** or **Off**. **Wishlist here** is the Brick Work wishlist that takes the wanted sets. **When both sides differ** is fixed: the preview asks each time.
3. **Pick sets.** The sets the run could touch, **All linked**, **By theme**, **By year** or **One by one** (Brickset has no lists to pick by). A set you do not pick stays as it is on both sides.
4. **Preview.** The same rows and choices as on the Rebrickable page: **Add here**, **Add there**, a quantity that differs, and **Changed in both places** with **Keep**, **Take** and **Send**. A wanted set has a quantity on both sides. **Before you send** names the number of changes and today's budget. A run reads your owned and wanted sets once, for both directions. A set that changes in more than one way is sent in one call.
5. **Result.** What changed here, with **Undo this run**, and what happened on Brickset, with a **Retry** for a row that failed. A change sent to Brickset cannot be undone here.

Brickset allows 100 calls a day unless it raises the limit for your key. Brickset now counts every call, not only `getSets`. The page counts reads, sends and the check of your user hash. Brickset also counts key checks and logins, so its own number can be a few higher.

## A BrickLink run

The **BrickLink** page has the same six steps, but its data is different: BrickLink's API has no personal collection and no wanted lists. This page pulls your **orders** into Orders. The price guide it reads is the one that already prices your sets and parts.

The page shows your account (key and today's budget, with **Test**, **Change** and **Remove**), the last runs with **Undo this run** and a table of **What syncs**. It reads nothing from BrickLink until you start a run.

1. **Connect.** BrickLink asks for four values: the consumer key and secret, and the token value and secret. Paste them and choose **Save**; Brick Work tests the key once with one call. BrickLink binds the token to one IP address that you registered with it, so register the address of the machine that runs Brick Work. A key from the environment can only be changed there.
2. **Choose what.** **Orders**: **Into Brick Work** or **Off**, with an optional **Orders since** date and **Orders to pull**, either **Received and paid** or **All orders**. **Price guide**: the region that prices are read for. An installation can lock the region (`BW_PRICE_SETTINGS_LOCK`, on by default); the control then shows the region and cannot change it.
3. **Pick lots.** The orders the run could pull, newest first. Ticked orders come in; an order you already imported is marked **Imported** and stays as it is. After **Undo this run**, its orders are no longer marked on this page and you can pull them again here.
4. **Preview.** One row for each picked order. **Pull in** brings an order into Orders as a draft, with its lines placed on your items. Nothing changes until you run.
5. **Result.** What each order did, with a link to it, and **Undo this run**. One Undo takes back every order the run pulled.

Loose stock on BrickLink and the wanted-list file follow on this page. Until then, build a wanted-list file from a wishlist with **Export**.

BrickLink's daily limit depends on your key. The page shows how many calls are used.

## Connect a site

Each site needs its API key and your own account credential. Rebrickable: step 1 of its page holds both, and **Connect** on the hub opens it. Brickset: step 1 of its page holds both, and **Connect** on the hub opens it. On Rebrickable, enter **Username or email** and your password and choose **Connect**. Or open **Paste a user token instead** and save what you generated on the site. On Brickset the fields are **Username** and **Paste a user hash instead**. The password goes to the site once and is never stored. Only the token (Rebrickable) or hash (Brickset) is kept, encrypted like the API keys. The username you type is kept as well, to show on the page. **Test** asks the site whether it still accepts it; **Remove** forgets it; you connect again to use the site. At most 10 logins per site per day.

## Link the lists

For both sites this is step 2, **Choose what**, of the page. Choose which of your set lists hold what you own, which one is your wishlist, and which owned list receives what you send. Both sites: choose the Brick Work wishlist that pulls and sends wishes (**Wishlist here**). The Rebrickable choices are labelled **Owned sets**, **Wanted sets · go to the wishlist** and **Send changes to**. A collection moved from 3.3 keeps its link. The first sync after the move compares everything, with no history to tell who changed what.

## Pull

**Pull** fetches your lists and compares them with this collection, set by set:

- **New there**: the site has more than you hold here. These rows are ticked; the count is how many copies (or wishes) would be added.
- **Different**: you hold more here than the site lists. **Only here**: the site lists none. Nothing is pulled for either; you decide. Rows where both sides agree are not listed.
- **Changed in both places**: both sides changed since the last sync and they differ. Both numbers are shown and nothing is ticked.
- **Not matched**: a number that names no single item in Brick Work, or only a part or a figure. It is listed and never guessed.

A set becomes one **copy** per missing unit, with the part list the set has. Its condition and completeness are not recorded, and it is tagged *imported from Rebrickable* or *… Brickset*. An item the catalogue knows as another kind (a gear item, a book, an instruction booklet) becomes loose stock of that kind, as when you add it. Missing wishes go to the linked wishlist, or raise the quantity of a wish you have. The plan expires after 24 hours.

**Undo this pull** (shown on the sync page right after a pull) archives the copies, takes the stock and wish quantities back and removes the tag. It is refused once you have changed any of them (**Something from this sync has changed since**).

**Where each row came from.** Every copy, loose-stock row and wish records how it arrived: **By hand**, **Rebrickable sync**, **Brickset sync**, a file or an import from another app. A row made through the API, the CLI or MCP reads **Via the API**, **Via the CLI** or **Via MCP**. That value never changes. A pull also records, on each copy, stock row and wish whose set the site holds, that it was **last synced from** that site, with the date. This holds for rows you added by hand too. It also holds for a sync run with nothing to add. The preview then says how many rows here already match the site, and **Run** is available for that alone. The result reads *Last synced from recorded on N rows*. Rows from before version 4.8 of the data read **Before this release**. Undo of a pull takes its "last synced from" dates back as well. The API returns both as `source` on a copy, a stock row and a wish.

## Where a copy came from

Open a copy and look under its tags: the **Source** row says how it got here and when a site last met it.

- **Added via** is one fixed value that never changes. It reads *By hand*, *Via the API*, *Via the CLI* or *Via MCP*. It can also name a site (*Rebrickable sync*, *Brickset sync*, *BrickLink sync* or *Brick Owl sync*). It can name a file (*BrickLink file*, *Rebrickable file*, *Brickset file*, *Brick Owl file* or *Brick Work export*). A row can also come from an import of the earlier app this one grew out of. Rows that exist from before this release read *Before this release*.
- **Last synced from** is a separate line per site and list, such as *Last synced from Rebrickable: Main collection · 18 Nov, 21:40*. It changes with every sync that matches the row. A set you added by hand can show it too: a later sync matched it to a set on the site, which does not change how it was added. A set in two Rebrickable lists shows one line for each.

On the Sets page, two chip rows under the status tabs filter by the same records: **Added via** and **Last synced from**, each chip with its count of sets. Press a chip to filter and press it again to clear it. The two rows combine with each other and with the status tabs. A set with several copies counts under every value its copies have.

The Wishlist and the loose-stock lists, such as Parts and Minifigures, have the **Added via** row too. Its counts are list rows. Each row carries a chip that names where it came from. A single chip that every listed row matches is not shown. A row that groups stock from several origins shows each one. Pieces that are only inside sets have no chip of their own.

Undo of a sync run uses these records to take back exactly what the run did.

## Rebrickable list names

If you keep your sets in several Rebrickable set lists, each set keeps the names of the lists it is in. They are the detail of its source: *Last synced from Rebrickable: Main collection, Bought 2026*. The names are not tags, and your own tags are never touched.

**What is kept.** The switch **Keep each set's Rebrickable list names as its source detail** is on unless you turn it off; the pull remembers your choice. With it on, a pull records each linked list that holds a set on every copy of that set, and on loose stock and wishes the same way. A set in two lists carries two names, and a set in no list carries none. A set you leave unticked in the preview gets no new date. With the switch off, a pull records only the site and the date.

**A list renamed at Rebrickable.** The next pull shows one line for it: *Renamed at Rebrickable to Home collection; the source detail of 5 sets changes*. **Rename it** is chosen. It puts the new name on every set that carries the list, picked or not. **Keep** leaves the old name, also on the sets this pull matches.

**A list removed at Rebrickable.** One line, *Removed at Rebrickable; the source detail of 2 sets changes*, with **Drop the name** chosen. The name goes from every set that carries it; the sets, their copies and counts stay. **Keep** leaves the name.

**A list you unlinked at Rebrickable.** One line, *Unlinked at Rebrickable; its names stay*, with **Keep** chosen. The list still exists there, so nothing is dropped.

**An unchanged list.** One line, *Unchanged*, with **Skip**.

A rename or a removal changes only the list name: copies, counts and every other field stay as they are, on sets you pick and sets you do not. **Undo this pull** puts the names back as they were before the pull.

## Loose parts from Rebrickable part lists

Brick Work can bring your Rebrickable part lists in as loose parts. It only reads them: nothing goes back to Rebrickable.

**Choose the lists.** None is chosen until you choose. Each chosen list lands in a lot of its own, made at the first pull and named after the list. The lot is remembered, so the next pull compares with it.

**The preview** compares each list with the loose parts in its lot, by part and colour:

- **New there**: Rebrickable lists more. The row is ticked with the difference.
- **Different**: you hold more here. **Only here**: the list has none. Nothing is pulled for either.
- **Not matched**: a part number or colour that Brick Work does not know, with the reason. It is never guessed.

A row can go into another lot of yours instead. A second pull with nothing changed lists nothing.

**Apply** adds the ticked rows in one step. Each new row reads *Added via Rebrickable sync*, carries the tag *imported from Rebrickable* and is *last synced from* its list. **Undo** takes the parts back off the stock, removes the tag and archives a lot the pull made once it is empty. Undo is refused once you have changed one of those rows.

## Lost Parts from Rebrickable

Rebrickable keeps a list of the parts you lost. A Rebrickable pull can bring it in and mark those parts as missing on the matching copy. On the **Rebrickable** page, step 2 has a **Lost Parts** card. Its direction **Into Brick Work** (the default) brings them in; **Off** does not read them at all. Brick Work remembers your choice, and the rule is on the same card.

The preview shows a **Lost Parts from Rebrickable** section before anything is written. For each set it lists the parts that will be marked, the counts that change, the marks that will be cleared and the parts that cannot be matched.

**Rebrickable wins, and the rule says how far that goes.** Choose it on step 2 of the Rebrickable page, under **Into Brick Work: which count wins**. It moved there from Settings; Settings keeps a row that points to Sync. It is one of four, and each one can clear something different:

- **Add only.** The sync adds missing marks and keeps the larger count where both sides have one. It never lowers or clears a mark.
- **Rebrickable wins per part** (the default). For a part Rebrickable lists as lost, Rebrickable's count replaces yours, also when it is smaller. Marks on parts Rebrickable does not list stay. A count can go down, and it can go to the lower number Rebrickable says, but no other mark is cleared.
- **Rebrickable wins per set.** A set that has at least one Lost Part on Rebrickable becomes exactly Rebrickable's list. Every other missing mark on that copy is cleared. Sets with no Lost Parts on Rebrickable stay as they are.
- **Rebrickable wins everywhere.** Every synced Rebrickable set (a set with one copy, or the copy you pick) becomes exactly Rebrickable's list. A set with no Lost Parts there loses all its missing marks. The preview says how many marks and pieces it will clear before you pull.

Nothing is cleared when Brick Work could not read the whole list. If Rebrickable could not be reached, or any row of the list could not be read, the preview says so and that pull clears nothing. The sets and wishes are pulled as usual.

**Several copies of one set.** Rebrickable records a lost part against a set, not a copy. With exactly one copy of the set, the marks go to that copy. With several, the preview lists that set's lost parts and a chooser asks which copy to use. A set with no copy picked is left out, and the result lists it as **Choose a copy**. Sync again to pick one. Archived copies do not count. Each copy in the chooser says what choosing it would do, for example **adds 2, clears 1 mark**.

**A set the same pull brings in.** Say a set has no copy here yet and the pull adds exactly one. Its Lost Parts are marked on that new copy in the same pull, and the preview shows them like any other set. When the pull adds several copies of the set, the set is listed as not matched. Sync again afterward and pick the copy. When you untick the set's row, no copy is made and its Lost Parts wait for the next sync.

**A copy that changed after the preview.** The pull writes a copy only when its missing parts are still what the preview showed. If you changed them in between, that set is left out and the result says so. Preview the pull again.

**Parts that cannot be matched.** A lost part is matched to a line of the copy by part and colour. Brick Work uses the numbers it knows for Rebrickable, so a copy on BrickLink's part list matches too. A spare part matches a spare line. Four cases are listed with the reason, never dropped. They are a part with no matching line, a count above the line's quantity and a set that is not in Brick Work. The fourth is a set with no copy here that this pull does not bring in. A set with a part that cannot be matched is not cleared, because the line it names may be one you marked.

**Checked on Rebrickable.** A copy that gets its Lost Parts from a pull shows the line **Checked on Rebrickable**. It sits under its bar on the Sets page and in the Info card of the set. The Lost Parts are its missing parts, and every other part counts as found.

A pulled copy of a set with no Lost Parts on Rebrickable gets the same line, and it shows as complete. That needs the whole Lost Parts list to have been read. It also needs a set with exactly one copy. The copy must carry the tag *imported from Rebrickable* and have no check or mark of yours.

The line goes only on the copy that received the pull: the single copy, or the copy you picked. Other copies of the same set are not touched. A sealed copy, or a copy whose completeness you chose yourself, gets no line.

When you check the copy or mark a part yourself, the line goes. A copy you checked is yours, so it carries no label. Undo of the pull puts the earlier state back.

**Sending Lost Parts to Rebrickable** is not available in this version: Brick Work brings them in and does not send any back. Parts you find or newly miss here are corrected on Rebrickable by hand. A direction saved earlier as **To Rebrickable** has no effect.

**Undo.** **Undo this pull** takes the Lost Parts marks back with the copies, stock and wishes of the same pull, in one step. Each marked copy also keeps its own entry in its history. Undo is refused when a mark was changed after the pull (**Something from this sync has changed since**).

## Send

On a site's page the send is part of a run: the preview lists the sets to add there and the quantities to change. **Review and send**, the single screen the page's **Retry** opens, lists the remote changes first; **Send** on that screen sends them: sets to add there, counts to change and removals. Removals stay unticked until you tick them. An item with no number yet (a local item added without one) cannot be named to a site. It is listed as *Not on Rebrickable* and cannot be ticked. Link a number in **Unresolved items** first. Wishes are sent only to a linked Rebrickable wishlist: with none linked, they are listed as *Link a Rebrickable wishlist to send wishes to* and cannot be ticked. A row that fails shows the reason next to it. A daily budget that runs out pauses the rest of the send, and a rejected token stops it; **Retry** sends only what was not sent. **Brick Work's Undo cannot reverse a change made at a site.**

Condition, completeness, box, instructions and storage never leave Brick Work.

## From the command line

```text
brickwork sync rebrickable status
brickwork sync rebrickable pull                 # make a plan
brickwork sync rebrickable pull --apply PLAN    # apply it (--tick ROW to choose rows)
brickwork sync rebrickable pull --lost-parts off   # leave the Lost Parts out (remembered)
brickwork sync rebrickable pull --apply PLAN --pick 2070-1=COPY_ID   # the copy for a set with several copies
```

See the [CLI reference](../reference/cli.md#sync).
