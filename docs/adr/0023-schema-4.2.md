# 0023. Schema 4.2: a job owner is a pid on one boot with one start time; an order line keeps why it is unplaced

- **Status:** accepted
- **Date:** 2026-11-04
- **Decided by:** the maintainer chose option A, "schema 4.2, with #155" (4 Nov 2026, relayed by the wiki-agent, recorded on #167 and #155). The column shapes and the liveness rule were set by the brick-work session

## Context

Two findings from milestone B need a column each.

- **#167:** `job_owner` stores only the owner's pid. After a container restart the new container's pids start again from 1, so a job left `running` can have its old pid taken by a different live process (gunicorn, a worker). The job then counts as owned, `_claim` skips it, and it stays `running` for good. `catalogue-job.json` has the same flaw: its stale `running` state refuses every new catalogue job as Busy.
- **#155:** an order line that can't be placed shows `unplaced: true` with no reason, although `_place` computes one ("The BrickLink number is not in the catalogue", "The name matches several items").

## Options considered

1. **A time-based check, no schema change** (branch `fix/167-job-claim-boot`): a live pid owns a job only if its process started before `claimed_at`, read from `/proc/<pid>/stat` and `/proc/stat` `btime`, with 2 s of slack. Codex found two holes, both verified against the code:
   - a forward wall-clock step moves `btime`, so a live owner can look newer than its claim and be taken over, and two processes then run the job;
   - a pid reused within the slack still counts as the owner.
2. **Schema 4.2: store the owner's identity and compare it exactly.** One additive step, together with #155's column.
3. **Two separate schema steps,** one per issue. That means two upgrades and two rollouts for the same users in the same week.

## Decision

Option 2, one step `4.1 → 4.2` in `store4/connect.UPGRADES`, additive only, run at the first read-write start:

- **`job_owner.boot_id`** (the kernel's `/proc/sys/kernel/random/boot_id`) and **`job_owner.start_ticks`** (the owner's start time in clock ticks since boot, `/proc/<pid>/stat` field 22). Both are monotonic facts of one boot, so no wall clock is involved.
  - The owner is alive only if its pid is alive **and** both values equal the stored ones, compared exactly.
  - A row without them was written before 4.2, so before the restart that ran the upgrade: it is dead.
  - Where `/proc` can't answer (macOS development), only the pid is checked, as before.
  - `catalogue-job.json` records and checks the same identity.
- **`order_line.unplaced_reason`**, NULL when the line is placed; API v2 returns it.
- In the same release, but with no column: the name suggestions (longest prefix, then all words), and the re-import of an undone document: it revives the document in its order, through the same header and currency checks as a chosen order, its lines paired with the old ones by position and updated in place. Nothing is deleted, so Undo of the revival puts every row back; lines that no longer pair refuse the import. The summary export lists only orders with saved lines.

4.2 goes to prod under the data-cutover rule (ADR 0018's shape): a runbook with T (rehearsal on test from a fresh prod backup), P (prod) and R (rollback), in `rasp-infra` `stack/brick-work/rollout-4.2.md`. The prod rollout is the maintainer's.

## Consequences

- A job or catalogue job left `running` by a dead process can be claimed again after a restart, without a timeout and without trusting the clock.
- **The upgrade is one-way.** 0.8.x refuses a 4.2 file, so the only way back is the 4.1 backup taken before the deploy, and writes made after it are lost.
- `Source.reserve()` still counts a call before sending it, so a process killed mid-request costs that call twice. That is by design: better to over-count than to overspend. The jobs docs say so, and advise restarting between jobs or once the day's budget is used up.
- The time-based branch `fix/167-job-claim-boot` is not merged. Its `/proc` parser and tests were reused.

## Links

[#167](https://github.com/Ulef1005/brick-work/issues/167), [#155](https://github.com/Ulef1005/brick-work/issues/155), [0018](0018-schema-cutover.md), [0021](0021-bricklink-only-order-items.md); `rasp-infra` `stack/brick-work/rollout-4.2.md`.
