# 0010. Live import progress polls over HTTP

- **Status:** accepted
- **Date:** 2026-10-16
- **Decided by:** Ulf (maintainer)

## Context

Legacy import screens showed live progress over Socket.IO, a dependency of the removed upstream code.

## Options considered

1. **Keep Socket.IO** — not recorded as weighed beyond its removal with the legacy code.
2. **Poll over HTTP.**

Recommendation at the time: not recorded.

## Decision

Live import progress polls over HTTP. Socket.IO is removed.

## Consequences

- One transport fewer to ship and secure.
- Progress updates arrive at the polling interval rather than instantly.
- The polling widget has an end-to-end test (a bug with unknown step states was fixed in review).

## Links

Related: ADR 0008.
