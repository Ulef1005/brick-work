# 0004. API v1 writes and audit

- **Status:** accepted
- **Date:** 2026-10-15
- **Decided by:** Ulf (maintainer), questions Q2, Q4, Q9 and Q12 of the API contract

## Context

API writes must be distinguishable in the event log, deletes must stay recoverable, and Undo must behave consistently for prices entered through the API.

## Options considered

The contract draft asked each of these as a question. The rejected alternatives are not recorded.

Recommendation at the time: not recorded.

## Decision

- Q2: schema 3.3 adds `api` to `events.via` and replaces the earlier private origin value.
- Q4: `DELETE /copies/{id}` archives; `POST /copies/{id}/restore` restores.
- Q9: purchase places and flags gain `archived_at`; deleting archives, and Undo restores them.
- Q12: Undo of an API manual price marks the observation `error='undone'` and recomputes `price_current`, so the observation is voided rather than deleted.

## Consequences

- Nothing is hard-deleted through the API; archived rows can be restored.
- The append-only events table is rebuilt in 3.3 with the new `via` values and its append-only triggers recreated.
- A single `POST /events/{id}/undo` dispatches over all receipt kinds.

## Links

`docs/brickwork/api-v1.md` sections 4, 10 and 11 (DDL-1, DDL-3). Related: ADR 0003.
