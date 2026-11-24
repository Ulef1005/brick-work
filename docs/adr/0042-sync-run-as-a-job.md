# 0042. A sync run is a durable job in the shared job table

- **Status:** accepted (slice 1 merged in #707)
- **Date:** 2026-11-24
- **Decided by:** the product session's frames 94 and 95 (Ulf approved the designs, 2026-11-24); progress only where Brick Work can report it truthfully (brick-work-product, 2026-11-24). The architect check for a column, run before any schema work, found none needed.

## Context

A sync run applied in one web request cannot show progress, cannot be left while it works and does not survive a restart. A large account (thousands of changes at about one call a second) needs all three. Frames 94 and 95 show "N of M done", the time left, a Stop after this one and "it goes on from the last saved step".

## Decision

- A run becomes one row of the existing `job` table (kind `sync_run`, `source` the site) with a `job_step` per stage; `job.kind` is free text, so there is **no schema change**. The embedded drainer runs it beside the other kinds, after the quick ones.
- The choices are frozen into the run record when the job is queued; the worker never needs the form.
- Progress is real only where Brick Work knows it: per call for sends and Lost Parts out, per stage for the pull and the part-list pull (one transaction, one undo event; chunking it would break the single Undo). Stop works between calls.
- A stage recorded as started is never run again after a takeover (sends are not idempotent). Its rows keep the send plan's results so the person can retry after checking.
- The run record is the one place for the result (`stages`, `applied`); the job row carries state, the retry time and the step counts.

## Alternatives

- **A thread inside the web process.** Rejected: no restart survival, no `BW_EMBEDDED_WORKER=0`, nothing in Jobs.
- **Chunk the pull for a progress bar.** Rejected: the run's Undo is one event.
- **A new table or column for progress.** Rejected: `job_step.count` and `total` exist.

## Consequences

- A sync run shows in Jobs, and `JobStep` carries `count` and `total` for every job kind.
- Known limits (the first two on the failure path only): a settled run whose closing write failed has no run audit entry; a stale write over a concurrent retry shows old counts; a job that waits or is down for more than 24 hours has lost its run (a plan lasts 24 hours from the job's last write).
