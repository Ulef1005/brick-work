# Brick Work import pipeline (4.2c)

The canonical key is always the BrickLink `(item_type, item_no)`, including all
S/M/P/G/B/C/I/O types. Call `pipeline.import_item(type, number, via='app', path=...)`
from an order or Part to Inventory adapter. The Add page queues the same six
steps transactionally with collection receipts; see [Add](../web-ui/add-41b2.md). This creates the catalogue
item before source work. Existing pages and legacy collection writers are not
rewired by this change. The reusable UI component is ready for the Add page.

```sh
brickwork import S 123-1
brickwork jobs
brickwork jobs --failed
brickwork jobs retry 42
brickwork jobs retry 42 inventory
```

Import runs in the foreground and prints short progress lines. `--json` suppresses
those lines and returns the job snapshot. Failed imports exit 1; budget waits exit
0. `jobs --failed` includes any job with a failed step, even when another step
is still waiting for budget. `BW_DB_PATH` or Flask `BRICKWORK_DB_PATH` selects the new database, with the default
`data/brickwork.db`. Source and image transports are injectable.

## Jobs, steps and restart behavior

`jobs.source='import'`, `kind='item'` is the parent job, holding the canonical
item, origin (`payload.via`), state, attempts, error and retry time. One job is
created per canonical item; repeated imports resume its unfinished steps. A
completed job returns its saved snapshot. `Pipeline.retry(job, step=None)` queues
failed steps and executes them, preserving all successful steps and calls.

Three **new** runtime tables are installed idempotently by `import.sql`:

- `import_steps`: primary key `(job_id, name)`, ordered position, snapshotted
  source list, selected source index/name, state, safe error and retry time.
- `import_calls`: primary key `(job_id, step, operation)`, completed JSON result
  or the exact source request job awaiting a budget. These checkpoints prevent
  repeating completed calls within multi-call matching, image and price steps.
- `import_owners`: job and local process id, used for atomic claims. Live workers
  exclude competing workers; a restarted worker recovers a dead process's jobs.
  This is a local SQLite worker model, not a distributed queue.

The existing v3 tables and migration mappings are unchanged. Parent job and step
state changes append `events` with `via='import'`. API clients retain their
separate budget reservations, source request jobs and raw reply transactions.
Each successful source call and step commits independently. A failed step
tries its configured fallback, leaves successful work intact, and permits later
steps to proceed. Missing inventory is therefore visible as a failed step while
the item, image, metadata and prices remain saved. A budget wait retains its
source job and next retry time; it does not switch sources merely to evade a
budget. Failed steps require Retry. Non-applicable steps finish without fetching.

A process can die between a source commit and its call checkpoint. That narrow
window can repeat a request on recovery; spent budget and both raw replies remain
recorded. Inventory and image writes replace source-owned rows; price attempts
remain observations. No promise of exactly-once network requests is made.

`Pipeline.drain(limit=100)` and `pipeline.worker(path=...)` drain queued and due
waiting jobs once. Pass a `threading.Event` as `worker(stop=event)` to poll until
shutdown and resume budget waits automatically. The app can run this worker in
its existing Socket.IO background task with an app context; deployments can
schedule the one-shot worker instead. No worker is started on module import.

## Settings

`settings.source_priority` retains the 4.2a JSON structure: step → item type
(or `*`) → ordered source names. Step names in order are `identity`, `inventory`,
`matching`, `pictures`, `metadata`, `market_price`.

| Step | Default source list |
| --- | --- |
| identity | `bricklink:local`, `bricklink:api` |
| inventory | `bricklink:subsets` (sets and minifigures) |
| matching | `rebrickable`, `part_resolutions`, `manual` (when needed) |
| pictures | P: `rebrickable`, `bricklink`; others: `bricklink`, `rebrickable` |
| metadata | S: `brickset` |
| market_price | `bricklink` |

`settings.import_order:<TYPE>` is a JSON list of all six step names, defaulting
to that order. Both settings are seeded without replacing existing values and
are editable using `brickwork settings set KEY JSON`. Jobs snapshot their order
and source lists; changing settings affects new jobs. Rebrickable images require
resolved foreign identifiers; moving pictures ahead of matching can make its
fallback necessary. A handler extension maps `(step, source)` to a callable; new
sources use the existing `sources`, `id_match` and raw record tables, with no DDL.

The local catalogue now stores XML year when present, with compatibility for
older catalogue files lacking that column. Migrated part-resolution and manual
matches are read locally first. Rebrickable parts use `bricklink_id` reverse
lookups; colour ids come only from `external_ids.BrickLink.ext_ids`. Ambiguous
identifiers remain evidence for manual resolution, never canonical keys.
Minifigure image fallbacks require a confirmed `id_match.kind='minifigure'`.
Foreign identifiers are fetched only where required by a source operation.

## Images and credentials

Images are downloaded to `data/images/<source>/<TYPE>/<sha256>.<extension>` beside
`brickwork.db` (or under the explicitly supplied root). `item_images` records the
relative local path, original URL, canonical colour, source, photo/render kind,
width, height and fetch timestamp. The URL is provenance; a page must render the
local file. Shared files are content-addressed and atomically installed. Invalid
image bytes, redirects, untrusted hosts and oversized replies are rejected.

Rebrickable uses `BW_REBRICKABLE_API_KEY` in the Authorization header,
`BW_REBRICKABLE_DAILY_BUDGET` (positive integer, default 1,000), and durable pacing
of at least one second between attempts. API throttle replies persist a short
retry deadline (the reported wait, or 60 seconds), separate from daily exhaustion.
Its raw replies are retained through
4.2b's source interface with credential redaction. These authentication, external
id, part-colour image and pacing rules follow the
[official API v3 documentation](https://rebrickable.com/api/v3/docs/).

## Add page progress contract

Use the **existing** upstream Socket.IO namespace and path, with these events:

- Server → client `import_progress`.
- Client → server `import_retry`: `{job_id: integer, step: string|null}`.
  `register_import_socket(brick_socket, db_path)` registers this authenticated
  retry handler when the Add page adopts it. It uses the upstream authentication
  and background-task wrapper and opens its own new-store connection.

Every progress payload contains:

```json
{
  "job_id": 42,
  "item_type": "S",
  "item_no": "123-1",
  "step": "inventory",
  "source": "bricklink:subsets",
  "state": "progress",
  "count": 38,
  "total": 112,
  "completed_steps": 1,
  "total_steps": 6,
  "job_state": "running",
  "message": "Fetching parts from BrickLink · 38 of 112",
  "error": null,
  "retry": false
}
```

`state` is `started`, `progress`, `done`, `failed` or `waiting`.
`step=null` identifies the final parent-job notification. `job_state` uses the
persisted `waiting_for_budget` spelling. Counts measure distinct inventory lines;
whole minifigures are counted alongside parts. Progress counts are emitted while
reporting the normalized inventory, following the committed subsets reply.
`error` is a credential-safe short string for failure. `retry=true` occurs on a
failed step. Final failures name the failed source. Observer disconnects do not
change durable results. Progress emitted in a socket request targets its SID;
worker emissions in an app context broadcast and clients filter by `job_id`.

Include `toni/components/import_progress.html` with `import_job_id`, load
`import-progress.js` after the Toni socket transport, and instantiate
`new BrickImportProgress(element, existingSocket, {jobId})`. The component shows
one 8 px clay bar with a short status line below and a Retry for failed steps.
It keeps failed steps while other steps succeed, uses `textContent`, filters
other jobs, disables Retry offline, prevents duplicate retries and cleans up
listeners with `destroy()`. A future Add route can instead supply a `retry(job,
step)` callback. That callback should return `false` if it cannot send the write.
The Brick Work Add page now includes this component, using its CSRF-protected
HTTP Retry callback and read-only snapshots to recover missed socket broadcasts.

## Verification

Python tests mock the API transport and image transport, using only synthetic
records and a generated 3 × 2 PNG fixture. The Node runtime harness exercises
progress, job filtering, failure persistence, Retry, disconnects, safe text and
cleanup. No test uses a provider or a real credential.

## Tools & Admin integration (4.1b-1)

Manage queues selective `market_price` and `pictures` refreshes with
`Pipeline.queue_steps`, including local Rebrickable reference pictures for
unresolved identities. Selective refresh jobs retain their own step checkpoints;
existing imports are not reset. `queue_retry` schedules failed steps without
network work in the HTTP request; the background worker executes them.

App-initiated workers enter `sources.base.audit_origin('app')` so their durable
source and step transactions append app events. Source calls outside that scope
retain import events. Admin/CLI/pipeline now agree on `BW_DB_PATH`, an explicit
Flask `BRICKWORK_DB_PATH`, or the default `data/brickwork.db`.

`brickwork worker` drains one due batch; schedule it to resume budget waits.
The admin background task polls until no queued, running or budget-wait imports remain. See
[Tools & Admin](../web-ui/tools-admin-41b1.md) for routes and design deviations.

## Add integration (4.1b-2)

Add queues a full, ordered pipeline job per confirmed review row, in the same
transaction as its collection additions and app receipt. A successful set
inventory step materializes parts for Add-created copies once, guarded by a
per-copy event under a database write lock. Imported/manual completeness and
existing migrated checks are preserved. The shared Tools & Admin worker emits
progress under app audit origin; Add keeps both per-item and batch bars. The
job and step records remain available in Jobs after leaving the page.

## Web worker cooperation and recovery (4.5w)

`yield_worker()` is the single event-loop seam. It calls the installed Socket.IO
server's `sleep(0)` in an app context, or the already-loaded gevent hub when
`app.py` has patched time. An ordinary CLI process neither imports nor requires
gevent. `cooperative()` yields after each unit, including skipped checkpoints.
Picture identities, candidate files, streaming cache-directory entries and
retained source envelopes use it. Pipeline steps, source fallbacks, colour/page
work, inventory reporting, source normalization and Add inventory materialization
also cooperate. Local cache traversal no longer sorts the entire tree before its
first yield. JSON decoding, individual SQLite statements, hashing and Pillow
verification remain indivisible; cooperation cannot preempt a single C call.

The migration-based fixture with 320 additional local-picture identities measured
986 yield boundaries and a longest stretch of **4.72 ms** in the resumed review run,
including pipeline setup, cache scanning, image verification/storage and final
receipt persistence. This is a fixture measurement, not a production latency
promise. A separate subprocess test verifies a real gevent observer runs between
picture units; tests also count yields for checkpoint replay and all six steps.

At Flask UI installation, the patched gevent runtime schedules a startup callback
for after `create_app` installs Socket.IO. Existing queued, running and budget-wait
imports start the same background drainer as web actions. One app-local active
flag prevents redundant drainers; the existing SQLite `BEGIN IMMEDIATE` claim and
`import_owners.pid` protect each job across workers. No second ownership table or
schema change is introduced. Live owners are excluded for every job state. Dead
owners are replaced when work is due. Completed identity/call checkpoints are
replayed without fetching again. The app drainer sleeps between polls and stays
available for future budget deadlines; the CLI one-shot behavior stays unchanged.

`/manage/jobs` reads owners in one query and labels an ownerless running job
(or a budget-wait job retaining a dead owner) **Interrupted · Resume**. Resume uses
the existing CSRF-protected POST and starts the drainer without resetting steps,
checkpoints or budget deadlines. Ordinary budget waits keep their budget label.
The kit's Manage 5b/7e system-page status pill and existing job action are reused;
there are no new components, routes, image sources or JS. The interrupted label
is a small state variant needed to explain worker death. The jobs list now loads
all step rows together; a 320-job trace test asserts three list queries. The
large picture save test also bounds SQL statements per identity with a trace
callback. Startup tests cover one recovery drainer and automatic continuation
after a preserved budget deadline. Resume validation itself is read-only.

App workers retain `audit_origin('app')`; state and checkpoint writes use the
existing import event writer. Resume adds no collection data. **Undo does not
reverse import jobs, source observations, budget spend or stored pictures**;
completed work and original cache files stay available. A source commit before
its call checkpoint can still repeat on process death, as described above.

The deployment gate belongs to the orchestrator: deploy this task commit,
resume stuck job 1 on a test instance, request `/` once a second during the run,
require every response under 1 s and check container logs for no `WORKER TIMEOUT`.
Local fixture tests do not establish that deployment gate.


### 4.5w round 2: transaction boundaries and restart identity

`cooperative(db, rows)` passes its connection to `yield_worker(db)`. The shared
helper suppresses scheduler switches whenever `db.in_transaction` is true,
including all source normalization consumers. Add materialization retains one
atomic transaction per copy and yields between committed copies; it does not
request yields between inventory lines. SQLite's busy handler must never block
the gevent hub while a suspended greenlet holds the write lock.

The unchanged `import_owners` schema only has `job_id` and `pid`, so runtime
ownership uses an in-memory set of active claims keyed by pid, database path and
job id. A row with the current pid is stale unless this process claimed that job.
The same test drives the Interrupted label. Other pids still use process liveness.
Finished and budget-waiting jobs release their in-memory and persisted claims;
including pid in the key also excludes claims inherited through a fork.

When only future budget waits remain, the app drainer sleeps until the earliest
`retry_at`, capped at 60 seconds, before reopening connections. Runnable work
retains the short poll interval; an empty queue stops the drainer. New jobs queued
while it sleeps can wait up to 60 seconds for this active drainer.

Jobs POST Retry intentionally retries every failed step when `step` is absent.
Both that path and selective Retry require the same editable gate and CSRF token
as Resume. Resume still preserves checkpoints and budget deadlines.

Regression tests install a fake scheduler that asserts the connection is outside
a transaction on every actual yield during complete imports (including source
consumers), standalone BrickLink consume, picture refresh and Add materialization.
Recovery covers an unclaimed owner row with the current pid, while polling covers
short deadlines, multi-hour waits and runnable work. The deployment latency gate
above remains separate from local verification.
