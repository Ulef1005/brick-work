# 0011. Part-list rule

- **Status:** accepted
- **Date:** 2026-10-15
- **Decided by:** Ulf (maintainer)

## Context

BrickLink subsets bring spare parts and every part of every minifigure into a set's parts list. Neither fits the use case of checking whether a set is complete. Rebrickable's set-parts endpoint flags spares and excludes minifigure parts unless asked; Brickset's API v3 has no part-list method; BrickLink is the only source of the current list and already separates whole figures from figure inventories.

## Options considered

1. **Include spares and minifigure parts in the set check** — the earlier counting rule, which this decision reverses.
2. **Exclude them from the set check** — spares are excluded by default; each minifigure is one line in the set and its parts are checked on the figure.

Recommendation at the time: option 2 (design agreed with Ulf).

## Decision

The set check and counts use required lines only. Spares are excluded by default, and the last step asks "Include spare parts?" (default no, which covers about 99% of cases). Minifigure parts leave the set list: a figure is one line (present, missing, or "N parts missing"), its parts are checked on the figure inside the copy, and missing figure parts count on the figure, not on the set.

## Consequences

- Set counts, the checker and the Collection card follow the new rule.
- A "Check figure parts" step exists inside the copy.
- Existing columns (`copy_parts.spare`, `parent_minifig`) were enough; no new table was expected.

## Links

Related: ADR 0006.
