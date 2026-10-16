# 0003. API v1 authentication

- **Status:** accepted
- **Date:** 2026-10-15
- **Decided by:** Ulf (maintainer), questions Q1, Q7 and Q11 of the API contract

## Context

The API needs a way to identify callers, limit what they may do and record who did what. The contract draft asked these as open questions.

## Options considered

1. **Single static token** — not recorded as weighed.
2. **Stored, scoped tokens plus an environment bootstrap token** — tokens carry `read`, `write` or `admin` scope; the environment token cannot be revoked through the API.

For rate limits and the audit actor, the options considered are not recorded.

Recommendation at the time: not recorded beyond the contract draft.

## Decision

- Q1: stored scoped tokens (`api_tokens`) plus the `BW_API_TOKEN` bootstrap token.
- Q7: no per-token rate limit in v1.
- Q11: `events.actor` is added in schema 3.3 and holds the API token name; it is NULL for web, CLI and imports.

## Consequences

- Several tokens can be issued and revoked, managed with the `brickwork token` CLI.
- The audit trail shows which token made a write.
- No per-token throttling in v1; this can be revisited in a later version.
- Schema 3.3 adds `api_tokens` and `events.actor` (the contract's decision 11 notes that the schema was being rebuilt anyway).

## Links

`docs/brickwork/api-v1.md` sections 2.9, 10 and 11 (DDL-1, DDL-2). Related: ADR 0004.
