---
audience: user
verified: 1.0
---

# Find and download the instructions for a set

**Not available yet.** On an install today Brick Work cannot find or download booklets, because no source is set up. To add the instructions for a set, download the PDF yourself and use **Upload a PDF** under **Tools & Admin → Instruction files** ([Instruction files](../how-to/settings-and-maintenance.md#instruction-files)). Finding instructions comes back as links to each set's instructions pages ([#465](https://github.com/Ulef1005/brick-work/issues/465)). The steps below describe the finder as it is built.

You own a set but have no instruction booklets for it in Brick Work. In this tutorial you let Brick Work look for the booklets on the Official source, choose which ones you want, and download them. They end up attached to the set as PDF files.

It takes about 10 minutes. You need a Brick Work install with the catalogue loaded and at least one set in your collection. The install needs network access to the Official source. Every number and name comes from an invented collection, so yours will differ.

## 1. Switch it on while you add a set

You can ask for instructions when you add a set. You can also start from the finder later, as step 2 shows.

1. Open **Add** and find the set as usual. Select it and go on to **Review and add**.
2. Turn on **Fetch instructions**. It starts off. If the switch is greyed out, no instruction source is set up on this instance yet.
3. Select **Add**. The set is added as before, and Brick Work queues a search for its booklets.
4. On the **Added** screen, read the result line. It says what was found. The **Review** link opens the list of files.

Nothing is downloaded at this point. The search only looks up the booklets and shows them to you. Brick Work asks again before it fetches a single file.

## 2. Find the booklets for more sets

1. Open **Tools & Admin → Instruction files** and select **Find instructions**. You can also open it from the **Instructions & Box** tab of one set.
2. Choose **All sets without instructions**, or choose **These set numbers** and paste them, one per line or separated by commas. The list follows the order you give.
3. Select **Find instructions**. A line says that the search downloads nothing. Brick Work looks up one set at a time and waits at least one second between requests to the same site. It stops after a fixed number of sets in one run.

The search runs only when you select the button. Brick Work never looks up a set you did not choose. A set with no booklet stays in the list and says which sources were tried.

## 3. Choose the files with the tick list

1. Read the sets in the order you chose them. Each booklet shows its title, for example *Mighty Dinosaurs · 2 of 3*, its source, its language and its size.
2. Check **Region** in the summary. The Official files differ per region, so a German booklet is a different file from the English one. It starts from your retail country in Settings and remembers your last choice.
3. Tick the booklets you want. Use **Select all** or **Clear** to change the whole list at once. **Search** and **Filter** narrow a long list.
4. Watch the line **N files ticked · N MB**. It adds up the sizes of the ticked files. A file with an unknown size is not ticked for you.

Booklets can arrive out of order, and a set may list an alternative model as its own group. Brick Work groups them by title, so booklet 1 of 3 comes before 3 of 3.

Brick Work ticks files for you. It ticks the booklets that match your **Region** and that fit the limit below, and a Peeron scan when it is the only file for its set. Untick what you do not want. Files you already have show **Already have this file** and cannot be ticked.

## 4. Stay under the download size limit

Some booklets are large. One for a big set can be more than 300 MB, while most are between 1 and 8 MB.

1. Files from other sources are limited to 20 MB each. Downloads from the Official source have their own limit, **Official download limit in MB**, which is 500 by default.
2. A file over its limit stays in the list with its size, for example *Over 500 MB*, but you cannot tick it.
3. The automatic ticks also stop when the ticked Official files add up to the limit. Tick more by hand if you want them.
4. Change the limit in **Tools & Admin → Settings**, under **Largest instruction download**. Check that the disk has room first.

## 5. Download and attach the PDFs

1. Select **Download N files**. The button counts the ticked files and stays off until you tick at least one.
2. Follow the progress bar. Each file shows its own state, such as **Not started**, **Waiting for the source** or finished. The download runs as a job, so you can leave the page and follow it in **Tools & Admin → Jobs**.
3. When a file fails, select **Retry failed files**. Finished files are not fetched again. **Cancel not started files** stops the rest of the run.

Brick Work checks that each file is a real PDF before it keeps it. It stores the file the same way as an upload, so two identical files are kept once. The booklet title becomes the label, and the PDF appears under the set on the **Instructions & Box** tab.

If the Official source says **needs a page renderer: not set up**, this instance cannot read its pages yet, and no other source is set up.

## What next

You found the booklets for a set, chose the ones you wanted within the size limit and attached them as PDFs. From here:

- [Add a box or instructions](../how-to/add-a-box-or-instructions.md) for the full reference of the finder and the limits.
- [Settings and maintenance](../how-to/settings-and-maintenance.md) for the download size limit and the instruction files list.
- [Undo a change](../how-to/undo-a-change.md).
