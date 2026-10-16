# 0002. One name: brickwork

- **Status:** accepted
- **Date:** 2026-10-15
- **Decided by:** Ulf (maintainer)

## Context

The code base came from an upstream project and carried several names in packages, environment variables, blueprints and docs. A public release needs one consistent name.

## Options considered

1. **brickwork everywhere**, with exceptions only for upstream credit and the importer.
2. Other options: not recorded.

Recommendation at the time: not recorded beyond Ulf's instruction.

## Decision

Only the name brickwork is used, with no upstream product wording anywhere. The exceptions are upstream credit and the importer, which keeps the old table names it reads.

## Consequences

- Packages became `brickwork/core` and `brickwork/web`, tests moved to `tests/`, and environment names use the `BW_` prefix.
- URL paths did not change in the rename itself (verified by test).
- A name gate (`scripts/check_names.py` with `scripts/name-allowlist.txt`) runs in `scripts/check.sh`; the allowlist shrank from 3,931 lines to 13 entries once the legacy code was removed (ADR 0008).

## Links

Related: ADR 0001, 0008.
