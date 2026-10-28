# Import from BrickTracker

*Since 0.6.0.*

Do this to bring a collection kept in BrickTracker into this one. BrickTracker stores Rebrickable numbers, and Brick Work's catalogue is built on Rebrickable's numbers, so nothing is translated: every set, part, figure and colour the catalogue knows is placed exactly, and what it does not know is listed and left out. Open **Manage → Tools & Admin → Import from BrickTracker**.

## Upload and read the preview

Choose BrickTracker's `app.db` (up to 200 MB here; larger files with `brickwork import-bricktracker` on the server). Any BrickTracker version is read: a copy is brought to the newest schema this import knows, and your file is never changed. The preview lists, for every set, loose part, loose figure, part lot and wish, whether it is **New**, a **Duplicate** (you already hold that set, pile, lot name or wish; unticked) or **Already here** (an earlier import of this file placed it). Tick what you want and press **Import**. Nothing is written before that.

Below the table, **not placed** lists what the catalogue does not know (for example a set newer than your catalogue: add it by hand and Brick Work fetches it from Rebrickable) with the reason, and the part marks whose line the set's part list lacks.

## What an import makes

- **A copy per set**, through the same path as Add: its lines come from the part list by design 4.3's preselection, and BrickTracker's *missing*, *damaged* and *checked* marks are put on the lines they name. A copy flagged *Set is checked* in BrickTracker, or with marks, gets a derived completeness. Note, storage, purchase place, date and price come across; BrickTracker records no currency, so a price takes your BrickLink currency setting.
- **Loose parts and figures as stock** of their kind (a loose figure with its own part list and its marks), with their lot, storage and purchase. Condition is not recorded.
- **Wishes** on the default wishlist, with their owner tags. A set of another kind (a gear item) becomes stock of that kind.
- **Storages, purchase places, tags, statuses and owners** matched by name and reused, or created.

The import is one event. **Undo this import** archives everything it made and takes back what it added to existing stock; it is refused once you have changed any of it. Pictures and instruction files are not copied: Brick Work fetches pictures through its sources. Importing the same file again skips what is already here.

## From the command line

```text
brickwork import-bricktracker APP_DB --plan-only     # make the plan and print its summary
brickwork import-bricktracker --apply PLAN_ID        # apply it once
```

See the [CLI reference](../reference/cli.md#import-bricktracker). A 3.3 collection of Brick Work moves to 4.0 with `brickwork migrate4`, not with this import.
