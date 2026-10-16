# 0013. Item detail pages

- **Status:** accepted
- **Date:** 2026-10-16
- **Decided by:** Ulf (maintainer), in decision issue #16, option A

## Context

Set detail showed a Matching module that the design does not include, and every item detail page (set, minifigure, part, instruction, box) showed Instances and Own photos below the design's modules. Issue #16 asked how to resolve this.

## Options considered

1. **A:** remove Matching from set detail (Take on the missing-part cards does the same job; the Matcher page stays for cross-set matching) and move Instances and Own photos into the Edit panel.
2. **B:** keep all three modules below the parts, styled to the design kit.
3. **C:** remove all three modules from set detail.

Recommendation at the time: A.

## Decision

Option A. The Matching module leaves set detail (Take on the cards does the same job; the Matcher page stays). Instances and Own photos move into the Edit panel on every item detail page. Minifigure and part detail keep their Matching module, which their designs include.

## Consequences

- Detail pages match the design modules.
- Instances and Own photos are reached through Edit.
- The change runs after the minifigure and part detail tasks because they touch the same templates.

## Links

Decision issue #16 (closed when the change is live).
