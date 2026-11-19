---
audience: user
verified: 1.0
---

# Add a box or instructions

*Since 1.1.0.*

Use this when you own the original box or the instruction booklet of a set and want them in your collection as items of their own. The catalogue holds sets, minifigures and parts but no boxes or instructions, so Brick Work offers them through their set.

## Find the box

1. Open **Manage → Add** and under **What** choose **Box** or **Instruction**.
2. Type the number or the name of the set, for example `6382-1` or `fire station`. The results are the matching sets, shown as boxes or instructions, each with the set's picture.
3. Select the ones you own and press **Review**.

A BrickLink box or instruction has the number of its set, which is why the search runs over the sets. A box you added before shows as the item itself and says how many you own.

## Add it

1. The review lists each box or instruction with its set's name. Choose the **Where**, the **Condition** and the quantity.
2. Press **Add**. The first time, Brick Work creates the item, named as the set. It links the item to BrickLink as `O` (box) or `I` (instructions) with the set's number. Your copy is added as loose stock.
3. The panel under **Importing** has an **Open** link to the item's page.

**With a BrickLink key**, Brick Work asks BrickLink once for each box or instruction you pick that is not in your collection yet, at the review. If BrickLink knows it, the item takes BrickLink's name. If BrickLink does not list a box or instruction for that set number, the review says so and the item's link is left to check; you can still add it. Without a key, or when BrickLink does not answer, nothing is checked and the item is named as the set. One lookup is one call of the shared daily BrickLink budget, and one review looks up at most 20 picks; the rest are not checked.

You can also paste set numbers with **Box** or **Instruction** chosen. A number that no set has is offered as an unidentified item, as for any other type.

**Undo** takes your copy back. The item it created stays, with none owned, and the next add of the same box uses it.

## Find and download instructions

**Not available yet.** On an install today no instruction source is set up, so **Find instructions** finds nothing. Download the PDF yourself and use **Upload a PDF** ([Instruction files](settings-and-maintenance.md#instruction-files)). Links to each set's instructions pages are planned ([#465](https://github.com/Ulef1005/brick-work/issues/465)).

Find instructions separates finding candidate PDFs from downloading them. Finding never downloads a file.
Official is registered but needs a rendered page fetcher. Until configured, the list says **Official needs a page renderer: not set up**.
No other source is registered.

Discovery uses the existing job queue and stores the sources tried, including searches with no candidates.
Downloads require a confirmed list of ticked files. Each file has its own result and can be retried after failure.
PDFs use the upload storage path and content hash. Official downloads have a separate limit, initially 500 MB; uploads retain 20 MB.

1. Open **Tools & Admin → Instruction files → Find instructions**.
2. Choose all owned sets without PDFs, or paste set numbers in your preferred order.
3. Choose a region and tick the files you want. Press **Download N files** to confirm.
4. Follow progress here or in **Tools & Admin → Jobs**. Retry failed files without repeating finished ones.

The Instructions & Box tab also links to **Find instructions · Upload a PDF** for that set.
On Add, **Fetch instructions** starts off. Turning it on finds files for the added sets and adds a **Review** link.
Finding still downloads nothing. Official searches show the renderer setup message until a renderer is configured.

The region starts from your retail country. This browser remembers your last choice as a preference.
Changing the region preserves choices you changed by hand and updates only untouched rows.
A Peeron scan is ticked initially only when it is the sole candidate for its set.
Files above their source limit and candidates already attached cannot be ticked.
Untouched defaults fit within the Official limit in total. Files with unknown sizes start unticked.
Unknown file sizes have their own count outside the known total.

Downloads allow 50 files per job. Requests to the same host wait at least one second between starts.
Sources receive the fixed Brick Work identification header. A source's Retry-After pauses the remaining files until its deadline.

“All sets without instructions” queues up to 50 sets per request. For larger selections it reports the total and the number remaining; run it again for the rest.

Booklet discovery uses the set with the booklet's number, just like PDF upload. UK and GB use the same region defaults.
Sets with instruction searches or candidates cannot change kind. Merges wait while a confirmed download for either set is active.
If a candidate has been removed, its download step fails with “Candidate was removed” and other files can continue.
Schema 4.5 adds database guards for discovery references; writable opens upgrade older collections automatically.

Add enables Fetch instructions only when at least one adapter is available. Otherwise it shows the adapter setup reason; completion keeps discovery errors visible. A new search clears the previous download address, and Retry failed files appears only after the download owner has stopped.

## Preview several booklets

The Instructions & Box tab shows page one when a set has several PDFs. One PDF keeps its compact row.
Each card shows the booklet title, size and Open action. Rename changes the title; Archive hides the file under Show archived.
Open Show archived to see archived booklets. Restore puts one back among the cards; Undo reverses it. Restore appears only when changes are switched on.
A progress tile means the preview job is waiting or running. No image means the preview failed; the PDF still opens.
Previews accept PDFs up to 20 MB and stop after 10 seconds. Pending tiles update automatically for one minute. Reload later if a job is still waiting.
