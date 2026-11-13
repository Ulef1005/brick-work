---
audience: user
verified: 1.0
---

# Make an insurance report

Do this when you want a list of every copy you own with what you paid and what it is worth now. Keep it for yourself or hand it to an insurer.

The report uses the same figures as [Value and gain of a copy](pictures-and-prices.md#value-and-gain-of-a-copy): the price paid on the copy, and its worth. The worth is the value you set ("Your value") or the used or new sold average of its set. Set a price paid and a purchase date in a copy's **Edit** sheet, and refresh the set's prices, before you make the report.

## Open it

1. Open **Tools & Admin → Statistics**.
2. In the **Paid vs value** card, press **Insurance report**.

The page shows the report as it prints. At the top: the date it was made, how many copies it lists, the total paid and the total worth. The note under the totals says which copies they count. The total paid and the total worth cover only the copies that have both a price paid and a worth, so the gain compares like with like. A copy whose price or value is in a currency with no rate in Settings says **needs a rate** and is listed. That note names it as left out of the totals. Copies without a price paid are still listed, with **No price paid**, and copies with no sold prices say **no sales**.

## What is in each row

There is one row per copy, in set-number order. The columns are set number, name, year, condition, completeness, purchased (the date), price paid, and worth now. Worth now comes with its source and the date of the quote ("Used sold average," "New sold average" or "Your value"; an old quote is marked **stale**). Under the row is a strip of your own photos of that copy, up to four, then "n more." A copy with no photo shows a dashed **No photo** tile: the set's cover picture is never used in its place. A figure that was converted from another currency shows what you paid in the original currency.

The page shows 15 copies at a time with the pager at the foot. Print and Download CSV always cover every copy, whichever page you are on.

**The column set is a proposal.** The **Proposal** note at the top says it: the columns stay provisional until it is clear what insurers ask for. Post what yours needs in the Discussions on GitHub.

## Print it, or save it as a PDF

1. Press **Print**. The report opens in a new tab as a print view and your browser's print dialog opens by itself.
2. To keep it as a file, choose **Save as PDF** as the destination.
3. Print it on A4, portrait. The first page carries the header with the totals. The following pages say "Insurance report, continued" and repeat the column heads. In browsers that support page counters, each page has "Page n of m" at the foot. A row and its photos are never split across two pages.

The print view is always light, whatever theme the app is in. If the dialog does not open, press **Print** in the toolbar at the top of the tab.

## Download the CSV

Press **Download CSV**. The file, `brickwork-insurance-report.csv`, has one line per copy with the same columns as the report and the figures in your display currency. It also has a **Remarks** column that says why a figure is missing, what was converted at which rate, an old quote or the incomplete-set discount. It is made safe to open in a spreadsheet. The same file is `GET /api/v2/export/insurance.csv` in the API.

## An empty collection

With no copy, **Download CSV** and **Print** are off and the page says **No copies to report**, with **Add a set** to start.
