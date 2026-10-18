# 0014. GitHub is the canonical repository, starting from a snapshot

- **Status:** accepted
- **Date:** 2026-10-18 (decided 2026-10-15 and 2026-10-16)
- **Decided by:** Ulf (maintainer)

## Context

Brick Work grew out of a private fork. Until the release cutover its history lived on the maintainer's private Git server: about 930 commits, including internal build reports, design diffs, migration runbooks and personal collection data. An open source release needs a public repository that outside contributors can file issues against and send changes to, without publishing that history.

## Options considered

1. **Publish the full history** — keeps every commit; publishes everything that was ever committed, which would need a history rewrite to clean.
2. **Private server stays canonical, GitHub as a push mirror** — no change to how work lands; outside contributions would have to be carried over by hand.
3. **A fresh GitHub repository, starting from a snapshot of the tree** — the published history starts clean; the old history is kept privately.

Recommendation at the time: option 3.

## Decision

`github.com/Ulef1005/brick-work` is the canonical repository. Its app history starts with one snapshot commit of the tree at the cutover, built by `scripts/public_snapshot.py`, which leaves out internal paths and scans for private material and secrets. Changes land directly on `main`. The pre-release history is frozen read-only on the private server as a permanent archive and is never published. A read-only pull mirror keeps a private copy for backups.

## Consequences

- Commit identifiers before the snapshot are not in this repository; older notes that cite them refer to the private archive.
- Every change is published from the moment it lands, so the snapshot scan's rules (no host names, private addresses, home paths or vault references) apply to every commit.
- The repository stays private until the maintainer makes it public; that step is separate from this decision.

## Links

Snapshot commit `4b8e1bc`. Related: [0001](0001-standalone-app.md), [0012](0012-licence-mit.md).
