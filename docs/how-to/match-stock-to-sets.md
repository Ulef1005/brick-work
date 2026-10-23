# Find sets your loose stock can finish

*Since 0.5.0.*

See which incomplete [copies](../concepts/collection-model.md) your loose stock can fill, and move the parts across. Do this after you have checked some sets and added loose parts, minifigures, booklets or boxes to your stock.

Matcher works from the gaps recorded on your copies: missing and damaged parts, missing minifigures, and a missing box or instruction booklet. Loose minifigures with missing parts count as well.

## Move loose stock into a copy

1. Open **Workbench → Matcher**. (The addresses `/workbench/matcher` and `/workbench/match` open the same page.)
2. The heading tells you how many copies can be advanced and how many can become complete. Copies that loose stock can finish come first, then the rest by how much of their gap your stock covers.
3. Each copy shows **covers N of M missing**, the kinds of item that match (**Parts**, **Figures**, **Instruction**, **Box**), and **Completes checked copy** if the matches would finish it.
4. Open a copy to see its matches. Each line shows the item, **Needs N · have M** and any note on the loose stock.
5. Find the physical item and check it. Set **Transfer count** if you want to move fewer than suggested.
6. Select **Give N** or **Take N**. Both move the items: the loose stock goes down by that count and so does the copy's missing count. The page reloads with the new numbers.

Every move appears under **Recent saves**, with an **Undo** on each line.

## How matching works

- Parts match by exact part and colour, figures by catalogue identity, and booklets and boxes by the exact set number.
- Matches are candidates from current stock, not reservations. The same loose item can appear against several copies.
- Within one copy, coverage counts each loose stock item once, so a lot of 2 does not cover two gaps of 2.
- Damaged loose stock and loose minifigures with missing parts are not offered.
- Items still waiting to be identified are not matched. They appear under **Needs a check**, with the copy and how many are missing.
- A copy becomes Complete only when **Set is checked** is set on it and no required part or minifigure is missing. If you set its completeness by hand, Matcher leaves it as it is.

## Narrow the list

Use search to find a copy by set number, name or the parts it needs. The filter limits the list to **Parts**, **Minifigures**, **Instructions** or **Boxes**. Sort by **Completes first**, **Name**, **Number**, **Missing count** or **Colour**.

## Add instruction booklets

*Since 0.5.0.*

Booklets you own but have not recorded can be added from the Matcher page. They go into your loose stock, where Matcher can match them to a copy that lacks its booklet.

1. Under **Add instruction booklets**, enter one catalogue booklet number per line in **Set numbers**. Use the full number when a set has several booklets.
2. Set **Quantity per line**, or add a comma and a quantity to a line to override it.
3. Select **Add booklets**.

## What next

- [Pick parts for several sets](pick-parts.md) for the gaps your loose stock does not cover.
- [Check a set's parts](check-set-parts.md) to record gaps on more copies, so Matcher has more to work with.
