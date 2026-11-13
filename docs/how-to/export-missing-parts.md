# Export or print the missing parts

*Since 0.5.0.*

Use this to turn the gaps you recorded in [Set Inspector](check-set-parts.md) into a list you can buy from or hand on: a BrickLink Wanted List file, a printable list or a CSV file.

## Export the list

1. Open **Planning → Complete sets**. It lists your copies that have recorded gaps.
2. Tick the copies you want.
3. Choose one:
   - **Export N · BrickLink XML** downloads `missing-parts.xml` for a BrickLink Wanted List: every missing or damaged part and every missing figure of the ticked copies, by BrickLink number and colour, with the condition of the copy. Something Brick Work cannot name for BrickLink, because it has no BrickLink number or its colour has none, is left out of the file and named in the message; the rest still exports. With *Use loose stock* on in the repair settings, the quantities are what you still have to buy ([Decide which set to repair first](plan-repairs.md)).
   - **Print missing parts of N** opens a printable list. **Download CSV** on that page saves the same list as a CSV file (item type, number, name, colour, condition, quantity and a note for items not matched yet). Items not matched yet stay on this list, marked.

The REST API offers the same missing-parts lists as XML, CSV and JSON.

## What next

- [Decide which set to repair first](plan-repairs.md) to rank the copies by what a repair is worth.
- [Order the parts all your sets are missing](order-missing-parts.md) to combine the gaps of several sets in one order.
