# 0005. Source keys stored encrypted in the app

- **Status:** accepted
- **Date:** 2026-10-15
- **Decided by:** Ulf (maintainer), question Q3 and the approved delegated decision of 2026-10-16

## Context

A standalone app needs the user's BrickLink, Rebrickable and Brickset keys. The contract draft recommended environment variables only.

## Options considered

1. **Environment keys only** — the draft's recommendation: no key storage code, no key in the database.
2. **In-app encrypted key store** — the user can enter keys on the Catalogues & keys page; costs an encryption secret and a write path that never returns a key.

Recommendation at the time: option 1. Ulf chose option 2.

## Decision

Source keys are stored encrypted (Fernet) with `BW_SECRET_KEY`. An environment key wins over a stored one. No endpoint returns a key; only configured state, origin and saved time are reported, and writes require admin scope. Without the encryption secret, key entry is disabled with a clear error. A database export strips stored keys instead of refusing to export (approved 2026-10-16).

## Consequences

- Users can set keys in the app without editing the environment.
- Losing `BW_SECRET_KEY` makes stored keys unreadable.
- Exported databases never carry keys.
- A no-secret test guards that keys are not leaked.

## Links

`docs/brickwork/api-v1.md` sections 8.2, 10 and 11 (DDL-4). Related: ADR 0001, 0003.
