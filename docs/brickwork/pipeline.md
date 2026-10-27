# Brick Work import pipeline (4.0)

One **job** per confirmed Add row, six **steps**, run in the background beside the fetch jobs. Everything lives in the collection file's
`job`, `job_step` and `job_owner` tables, so a job survives a restart. The data model is in the
[4.0 design](../data-model-4.0/data-model-design.md) (§ 4.3, § 5.2, § 6.5); the Add screen is described in the
[user journey](../data-model-4.0/user-journey.md).

## What a job is

`job(source='import', kind='item', item_id, state, via, actor, attempts, retry_at, error, error_code)` with one `job_step(job_id, name,
position, sources, source_index, source, state, error, error_code, retry_at, count, total)` per step. `job.state` and `job_step.state` are
`queued`, `running`, `waiting_for_budget`, `failed` or `done`. Add queues the job in the same transaction as the copies, stock or wish
it confirms (`Pipeline.queue_steps`), so a row and its job commit or roll back together.

The two fetch kinds (`bricklink_subsets`, `rebrickable_set`) live in the same table and are run by `store4.jobs`. Each runner ignores the
other's kinds; `core.drainer` runs both, fetch jobs first, and stops when neither has anything queued, running, waiting or due for a retry.

## The six steps

Names and order come from the setting `import_order:<kind>` (kind words: `set`, `part`, `minifigure`, `instructions`, `box`, `gear`,
`book`, `catalog`), default `identity`, `inventory`, `matching`, `pictures`, `metadata`, `market_price`. `sources` is
the step's list for the item's kind: `['catalogue']` for the first three, otherwise the setting `source_priority` (step → kind or `*` →
source ids) with the defaults pictures `bricklink`, `rebrickable_api` (parts: `rebrickable_dump`, `bricklink`), metadata `brickset` (sets),
market_price `bricklink`. Changing the settings affects new jobs only.

| Step | What it does now | Ends `done` with |
| --- | --- | --- |
| `identity` | checks that the item has a number from some provider | `unidentified` when it has none |
| `inventory` | checks that a set or figure has a part list (catalogue or fetched) | `unidentified` (no number), `not_found` (identified, no list) |
| `matching` | checks for a confirmed BrickLink number; when none, records `item_provider_status(bricklink, unmatched, no_match)` | `unidentified` when there is no BrickLink number |
| `pictures`, `metadata`, `market_price` | **skipped until the sources piece (M.8f)**: no handler is registered | `error` = "skipped: no source handler on the 4.0 store yet", count 0, no source |

A step that finds nothing to work with ends `done` with the finding, never `failed`: the job finishes. A **user-asked** BrickLink
fetch that finds no number for the set stays `failed` (`store4.jobs`, error code `unidentified`). Only a step a handler failed is
`failed`; `Pipeline.queue_retry(job, step=None)` puts failed steps back to `queued` and leaves done (and skipped) steps alone.

The copies an Add confirms are materialised in the Add transaction from the catalogue's list (or BrickLink's, as decision F describes), so no
step builds part lines. BrickLink's list for a copy is a separate `bricklink_subsets` job; when it succeeds, `store4.pending` switches the
copy that is waiting for it.

## Handlers (for the sources piece)

`pipeline.register(step, source, handler)` runs `handler(db, job, step)` when a step tries `source`. It returns normally (step done),
or raises `StepDone(code, message)` (done with a finding such as `unidentified`), `StepWait(retry_at, why)` (the step and job
`waiting_for_budget`, retried when due) or `StepFailed(code, message)` (the next source is tried; the step fails after the last).

## Claims and restarts

A run claims the job in `job_owner` (pid and time) inside a write transaction. A job whose owner is another live process is left alone;
a claim by a dead pid, or by this pid when this process does not hold it, is taken over. An interrupt leaves the job `queued` and
unclaimed. The embedded drainer starts at app start-up when a job is active, and `BW_EMBEDDED_WORKER=0` leaves draining to
`brickwork worker`.

## Progress

`GET /manage/add/jobs/<id>` returns the steps as events for the progress widget (`import-progress.js`): `started`, `progress`, `waiting`,
`failed` or `done` per step and a final event for the job. Nothing else leaves the server: no payloads, no keys. The Add page polls it; the
Retry button posts to `/manage/add/jobs/<id>/retry` with the page's CSRF token. Undo does not reverse a job: stored pictures, prices and
spent budget stay.
