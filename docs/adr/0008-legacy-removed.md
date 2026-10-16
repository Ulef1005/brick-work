# 0008. Legacy screens and stores removed

- **Status:** accepted
- **Date:** 2026-10-15
- **Decided by:** Ulf (maintainer)

## Context

The app began as a fork of an upstream project whose screens, stores, token setting and real-time layer were replaced by the new design. Keeping both made the code, tests and names inconsistent (ADR 0002).

## Options considered

Not recorded in detail. The decisions were: keep the importer, delete the rest, and drop the URL prefix without redirects.

Recommendation at the time: not recorded.

## Decision

- The legacy upstream screens and stores are removed.
- The importer for databases of the upstream project is kept (`brickwork/core/importer/`, `brickwork migrate --extras`, page `/manage/import-legacy`); it is the only place old table names may remain.
- The old `/house` URL prefix is dropped; old URLs answer 404 with no redirects.

## Consequences

- About 771 legacy files were removed in the cutover task; the old API, its token and refresh call, Socket.IO and the UI switch are gone (see ADR 0010).
- Bookmarks and shortcuts with the old prefix break; the changed paths are listed in `docs/brickwork/cutover-4.11j.md`.
- The scanner queue and view choice saved in the browser reset once after the rename.

## Links

`docs/brickwork/cutover-4.11j.md`. Related: ADR 0002, 0010.
