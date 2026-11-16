---
audience: user
verified: 1.0
---

# Print storage labels

Open **Workbench > Storage**, then choose **Print labels**. Tick the storages, or choose **Select all**. Choose **Print labels · N**.

Remove any unwanted storage chips. Choose an A4 layout or 62 mm label tape. Check the preview, then choose **Download PDF** or **Download N PNG**.

Choose at most 200 storages per download. If Select all ticks more, remove storages until Download is available. When labels span several sheets, use **Previous** and **Next** to inspect each sheet.

Print sheets at 100 %, without fitting to the page. Cut guides appear only in the preview. Tape downloads contain one PNG per label, zipped for multiple labels.

Each label shows a permanent short id and a QR code. Short ids are never reused, even after deletion. Find one through Jump search. Scan the code with your phone camera to open the storage contents. Login returns you there.

Set **Address for labels** in **Tools & Admin > Settings** to an address your phone can open. An empty setting uses the request address.

Archived storages cannot be selected. An older printed label explains that the storage was archived and links back to Storage. This also works on a phone.

Restoring an older backup assigns short ids in creation order. Earlier storage edits can still be undone without changing those ids.

The label address must use HTTP or HTTPS, without a path, user information, query or fragment.
Even empty query, fragment and user information markers are rejected.
Missing selections show **Choose between 1 and 200 storages**. Invalid preview sheet numbers show **Choose a preview sheet**.
The download limit appears in the label selection bar; the item move bar shows only the selected count.
