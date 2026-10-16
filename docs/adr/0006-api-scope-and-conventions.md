# 0006. API v1 scope and conventions

- **Status:** accepted
- **Date:** 2026-10-15
- **Decided by:** Ulf (maintainer), questions Q5, Q8, Q10, Q6 and Q14 of the API contract

## Context

Several scope and convention questions were open in the contract draft: what uploads belong in v1, how enums look on the wire, where price settings live, how background jobs run, and the default BrickLink request budget.

## Options considered

- Q5 uploads: the draft had PDFs only; photo and identification upload were the alternative added. Other options not recorded.
- Q8, Q10, Q6, Q14: rejected alternatives not recorded.

Recommendation at the time: not recorded, except for Q5 where the draft recommended PDFs only and Ulf extended it.

## Decision

- Q5: instruction PDFs, own photos (15 MB) and Brickognize identification upload, result, thumbnail and archive are in v1.
- Q8: API enums use words; stored codes do not change.
- Q10: price settings move into the v3 `settings` store before the port; readers use that store.
- Q6: an embedded job drainer runs by default; `brickwork worker` is documented for headless installs; `POST /jobs/drain` stays available.
- Q14: `BW_BRICKLINK_DAILY_BUDGET` stays at 4,400, a safety margin for other tools sharing a key.

## Consequences

- Clients can upload photos and identification images through the API.
- Wire values are readable; the database keeps its codes.
- One settings store for prices; the old price settings table is retired.
- Headless installs need the worker command; others need nothing.

## Links

`docs/brickwork/api-v1.md` sections 8.3 and 10. Related: ADR 0003, 0005.
