# 0018. A schema cutover: one pinned catalogue, a rehearsal from a prod backup, the clients in the window

- **Status:** accepted
- **Date:** 2026-10-28
- **Decided by:** the maintainer approved the cutover (#115, Session Decisions seq 165). The procedure was set by the brick-work session under the maintainer's delegation, cleared step by step by the wiki-agent (Session Decisions seq 173–178)

## Context

Prod moved from schema 3.3 to 4.0 with one migration (`migrate4`, design § 8). Its result depends on more than the code:

- **The catalogue file:** item ids are seeded when the catalogue is built.
- **The mapping layers:** the local minifigure map from M.4 decides about 60 percentage points of the attachment. Without it, 16% of copies attach to their Rebrickable lists instead of 75%.
- **The clients:** they break at the switch, whichever side of it they run on.

Prod is the maintainer's only copy of the collection, so a failed cutover has to be undone in minutes, with nothing lost.

## Options considered

1. **Build the catalogue and migrate on prod during the window.** This is one step fewer, but the result then differs from anything that was checked.
2. **Build the catalogue once, pin it, and rehearse the whole runbook on test from a prod backup before prod.** The rehearsal includes the clients, the rollback and the go-forward.

Recommendation: 2.

## Decision

- **One catalogue file (`CAT`) and one mappings folder (`MAP`):** built once with the release commit from one Rebrickable download, and their sha256s recorded. The prod migration runs with `--pin` against the rehearsal's `proof.json`, so it refuses any other catalogue or mappings. No BrickLink item lists go into `CAT` for the cutover; they can be loaded later from Tools & Admin.
- **The rehearsal on test:** the image that prod then runs unchanged, a fresh copy of the newest prod backup, the counts against the backup, `brickwork check` with its cross checks, a write and its Undo, every client, and a rollback to prod's current image followed by a go-forward. A 4.0 file made earlier is never reused.
- **On prod:** stop; a fresh backup by a fixed recipe (`.backup`, `integrity_check`, live-vs-copy counts, a tar of the rest, `SHA256SUMS`, a copy off the host); the pinned migration; the counts, reported before anything starts again. A separate clearance comes before the stop and before the start.
- **The clients land inside the cutover window and in one order:** host glue, then the skill, then the backup unit. None of them lands before it.
- **Rollback:** the 3.3 file stays beside the new one as `brickwork-3.3.db`, with the old image. Rollback is a rename and an image tag, and deleting either needs the maintainer's yes.
- **The runbook is host glue:** it lives beside the prod compose file in `rasp-infra` (`stack/brick-work/cutover-4.0.md`), not in the app repo.

## Consequences

- The prod numbers equalled the rehearsal's exactly: copies 196, loose stock 355, wishes 183, storages 2, items 4,699 → 4,719 through the mint, and attachment 75.0% / 77.5% / 84.2%. Prod was down from 12:49 to 13:00.
- The rehearsal found five runbook defects and one app gap (a set's theme in the Toni App) before prod.
- Two things it could not catch, both now in the runbook:
  - a client configuration that pinned the old API base (the House API's environment template), because the rehearsal ran the pass-through in-process with its own URL;
  - a cutover-day backup run prunes that night's archive, because of the daily retention.
- A future schema change follows the same shape: pin the inputs, rehearse from a prod backup, land the clients in the window, roll back by renaming.

## Links

[#115](https://github.com/Ulef1005/brick-work/issues/115) (the cutover note), [#114](https://github.com/Ulef1005/brick-work/issues/114) (the rehearsal), design § 8; `rasp-infra` `stack/brick-work/cutover-4.0.md`; [0016](0016-data-model-4.md), [0017](0017-api-v2.md).
