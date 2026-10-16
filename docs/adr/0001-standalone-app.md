# 0001. Standalone app

- **Status:** accepted
- **Date:** 2026-10-15
- **Decided by:** Ulf (maintainer)

## Context

Brick Work started as part of a private home setup. A public release has to work for anyone who installs it, without any private service next to it. The first public snapshot must hold no private integration code, token, route or naming.

## Options considered

1. **Standalone app with its own surfaces** — the app calls BrickLink, Rebrickable and Brickset itself with the user's own keys, and offers an API, a CLI and later an MCP server. Outside tools plug into those surfaces.
2. **Keep a private integration inside the app** — not recorded as an option that was weighed.

Recommendation at the time: option 1, surface first (CLI plus an app-owned API, documented, with the MCP server as a thin layer over the same functions). Ulf confirmed the plan.

## Decision

The app runs completely standalone on the user's own BrickLink, Rebrickable and Brickset keys. Integrations use only the app's own API, CLI and MCP server. A private client of this API uses the same standard API as everyone else.

## Consequences

- The old external price-refresh call and the private API blueprint go away; the app refreshes prices itself.
- The API has to be defined first (reads and writes for sets, parts, minifigures, prices, wishlist and the rest), see ADR 0003 to 0006.
- A standalone smoke test (no keys, no network, empty data folder) guards the rule, and a name gate in the check script keeps private names out.
- The README claims only what works standalone.

## Links

API contract: `docs/brickwork/api-v1.md` (sections 0 and 10). Related: ADR 0002, 0003, 0005, 0007, 0008.
