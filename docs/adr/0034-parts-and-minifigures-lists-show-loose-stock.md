# 0034. Parts and Minifigures list loose stock by default

- **Status:** accepted
- **Date:** 2026-11-17
- **Decided by:** Ulf (maintainer), in decision issue #20, option A, confirmed 2026-11-17

## Context

The Parts list showed every part line of every set copy, with "0 loose · 12 in sets" on a row. The rail said Parts 135 while the page held 7,446 entries. Minifigures had the same gap, 564 on the page against 300 in the rail. The design's Parts page lists loose parts. Issue #20 asked what the lists should show by default.

## Options considered

1. **A:** list what you own loose by default, so the list matches the rail. A scope chip **In sets** shows the parts and figures inside set copies. Search across everything stays in the jump bar.
2. **B:** keep everything in one list and make the rail and the headline match it, saying "loose" and "in sets" per row.
3. **C:** loose only, with parts inside sets only on set detail.

Recommendation at the time: A, because most of it was already built (the Stock filter and the data headlines).

## Decision

Option A. Parts and Minifigures open on **Loose**. The chips **Loose** and **In sets** sit above the list and in the Filters sheet, and they are exclusive: one scope is shown at a time. **In sets** lists the parts and figures that sit inside set copies, with the in-set quantity first. The headline and the first figure of the sub-line follow the scope. In the default view the loose total is the number the rail shows. A stored list state without a scope opens on Loose. A link that needs the in-set rows asks for them with `?stock=sets`.

## Consequences

- The default list agrees with the rail and with the design's Parts page.
- Parts and figures inside sets stay one tap away and in the jump bar.
- Other lists (Instructions, Boxes) keep their Stock filter with Any, since they have nothing inside sets.
- The page still sends every row to the browser. The scope is applied there, so switching is instant.
- Damaged and missing counts on a row still add loose and in-set pieces. Splitting them is a later change.

## Links

Decision issue #20 (milestone G). Related: [0013](0013-item-detail-pages.md).
