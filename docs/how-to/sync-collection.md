---
audience: user
verified: 1.0
---

# Sync with Rebrickable and Brickset

*Since 0.6.0.*

Do this to bring the sets you already keep on Rebrickable or Brickset into Brick Work, or to send what you hold here back to the site. Pull never deletes anything here; send always shows the changes first and asks before it removes anything there. Open **Manage → Tools & Admin → Collection sync**.

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

## Send

**Review and send** on the site's card lists the remote changes first; **Send** on that screen sends them: sets to add there, counts to change and removals. Removals stay unticked until you tick them. An item with no number yet (a local item added without one) cannot be named to a site. It is listed as *Not on Rebrickable* and cannot be ticked. Link a number in **Unresolved items** first. A daily budget that runs out pauses the rest of the send, and a rejected token stops it; **Retry** sends only what was not sent. **Brick Work's Undo cannot reverse a change made at a site.**

Condition, completeness, box, instructions and storage never leave Brick Work.

## From the command line

```text
brickwork sync rebrickable status
brickwork sync rebrickable pull                 # make a plan
brickwork sync rebrickable pull --apply PLAN    # apply it (--tick ROW to choose rows)
```

See the [CLI reference](../reference/cli.md#sync).
