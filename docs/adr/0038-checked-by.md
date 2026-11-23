# 0038. A copy records who checked it: `copy.checked_by`

- **Status:** accepted
- **Date:** 2026-11-20
- **Decided by:** Ulf, issue #489 (answers relayed on 2026-11-20)

## Context

A copy pulled from Rebrickable can carry Lost Parts. Rebrickable records them against a set, not a copy. The Sets page shows one bar per copy, so a pulled copy needs a status of its own, and a person needs to see who vouches for it: Rebrickable or Brick Work.

## Options considered

1. **A column on the copy** — one nullable value, written by the pull and cleared by a hand check. It costs a schema step. It is cheap to read in the list, the API and the Undo receipts.
2. **A flag on the copy** — no schema step, but flags are the person's own tags and can be edited, merged or deleted by them.
3. **Work it out from the events** — no stored value, but a list read would have to scan the event log for every copy.

Recommendation at the time: option 1, the column.

## Decision

Ulf's answers on 2026-11-20:

- Reading: "Yes, that reading (Recommended)". A pulled copy shows as checked by Rebrickable. Its Lost Parts are the missing parts on the bar. A pulled copy without Lost Parts shows as complete. A line under the bar names the source, "Checked on Rebrickable". A copy Brick Work checked itself carries no such label.
- Marker: "A: copy.checked_by column (Recommended)". A nullable column `copy.checked_by`: NULL means Brick Work, or not set by a pull. `'rebrickable'` means a Rebrickable pull set it. The schema moves from 4.6 to 4.7 with a migration.
- Damaged and spare parts: "Yes, stay out (Recommended)". They stay out of the bar. The line under the bar names damaged pieces.

Rules that follow from the data:

- A Lost Part belongs to a set on Rebrickable. The pull writes `checked_by='rebrickable'` only on the copy that received it: the set's single copy, or the copy the person picked. Never on every copy of a set.
- A pulled copy without Lost Parts gets the marker only when the pull read the whole Lost Parts list, and only on a copy the pull made, or on a set's single copy that nobody has checked or marked by hand.
- A check or mark by hand clears the marker, so a copy Brick Work checked itself carries no label. The marker travels in the same event as the marks, so the pull's Undo restores it.
- A copy marked this way counts every piece that is not missing as found, as a copy with "Set is checked" does.

## Consequences

- Schema 4.7 adds one nullable column through an additive upgrade. Every existing copy stays NULL, because its source is unknown: it reads as Brick Work's own and carries no label.
- An older version cannot open a 4.7 file, as with every schema step. The way back is the backup.
- The column is shown read-only as `checked_by` in the copy representation of API v2, the CLI and MCP.
- The column is reversible: drop it (`ALTER TABLE copy DROP COLUMN checked_by`) and the label goes. Nothing else reads it.
- A second source of checks (for example BrickLink) needs a new value in the CHECK, so another schema step.

## Links

Issue #489, [Sync with Rebrickable](../how-to/sync-collection.md), and [ADR 0033](0033-instruction-thumbnails.md) for the pattern of an additive column.
