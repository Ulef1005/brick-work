---
audience: user
verified: 1.0
---

# Sync with Rebrickable and Brickset

*Since 0.6.0.*

Do this to bring the sets you already keep on Rebrickable or Brickset into Brick Work, or to send what you hold here back to the site. Pull never deletes anything here; send always shows the changes first and asks before it removes anything there. Open **Workbench → Sync**, then **Open** on the site. The old page under Tools & Admin sends you there.

## Connect a site

Each site needs its API key (**Catalogues & keys**) and your own account credential. On the site's card, choose **Link a collection** (the screen is titled **Link Rebrickable** or **Link Brickset**). Either enter **Username or email** and your password and choose **Connect**, or open **Paste a user token instead** (Brickset: **user hash**) and save what you generated on the site. The password goes to the site once and is never stored: only the token (Rebrickable) or hash (Brickset) is kept, encrypted like the API keys. **Test** asks the site whether it still accepts it; **Remove** forgets it; you connect again to use the site. At most 10 logins per site per day.

## Link the lists

For Rebrickable, choose which of your set lists hold what you own, which one is your wishlist, and which owned list receives what you send. Both sites: choose the Brick Work wishlist that pulls and sends wishes (**Wishlist here**). The Rebrickable choices are labelled **Owned sets**, the wishlist list and **Send changes to**. **Link and preview pull** saves the link and runs a pull preview straight away. A collection moved from 3.3 keeps its link; the first sync after the move compares everything, with no history to tell who changed what.

## Pull

**Pull** fetches your lists and compares them with this collection, set by set:

- **New there**: the site has more than you hold here. These rows are ticked; the count is how many copies (or wishes) would be added.
- **Different**: you hold more here than the site lists. **Only here**: the site lists none. Nothing is pulled for either; you decide. Rows where both sides agree are not listed.
- **Changed in both places**: both sides changed since the last sync and they differ. Both numbers are shown and nothing is ticked.
- **Not matched**: a number that names no single item in Brick Work, or only a part or a figure. It is listed and never guessed.

A set becomes one **copy** per missing unit, with the part list the set has. Its condition and completeness are not recorded, and it is tagged *imported from Rebrickable* or *… Brickset*. An item the catalogue knows as another kind (a gear item, a book, an instruction booklet) becomes loose stock of that kind, as when you add it. Missing wishes go to the linked wishlist, or raise the quantity of a wish you have. The plan expires after 24 hours.

**Undo this pull** (shown on the sync page right after a pull) archives the copies, takes the stock and wish quantities back and removes the tag. It is refused once you have changed any of them (**Something from this sync has changed since**).

## Lost Parts from Rebrickable

Rebrickable keeps a list of the parts you lost. A Rebrickable pull can bring it in and mark those parts as missing on the matching copy. On the **Rebrickable** card, the switch **Bring in Lost Parts** sits beside **Pull**. It is on by default, and Brick Work remembers your choice. Under the switch, one line says what it does and which rule applies. It links to **Settings**, where you choose the rule. With the switch off, Brick Work does not read your Lost Parts at all.

The preview shows a **Lost Parts from Rebrickable** section before anything is written. For each set it lists the parts that will be marked, the counts that change, the marks that will be cleared and the parts that cannot be matched.

**Rebrickable wins, and the rule says how far that goes.** Choose it under **Settings → Sets and parts → Lost Parts from Rebrickable**. It is one of four, and each one can clear something different:

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

**Undo.** **Undo this pull** takes the Lost Parts marks back with the copies, stock and wishes of the same pull, in one step. Each marked copy also keeps its own entry in its history. Undo is refused when a mark was changed after the pull (**Something from this sync has changed since**).

## Send

**Review and send** on the site's card lists the remote changes first; **Send** on that screen sends them: sets to add there, counts to change and removals. Removals stay unticked until you tick them. An item with no number yet (a local item added without one) cannot be named to a site. It is listed as *Not on Rebrickable* and cannot be ticked. Link a number in **Unresolved items** first. Wishes are sent only to a linked Rebrickable wishlist: with none linked, they are listed as *Link a Rebrickable wishlist to send wishes to* and cannot be ticked. A row that fails shows the reason next to it. A daily budget that runs out pauses the rest of the send, and a rejected token stops it; **Retry** sends only what was not sent. **Brick Work's Undo cannot reverse a change made at a site.**

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
