# 0020. A bulk action is one batch that interactive work overtakes, tagged in the job payload

- **Status:** accepted
- **Date:** 2026-11-03
- **Decided by:** the maintainer took #127 into milestone A (re-plan, 3 Nov 2026). The shape was set by the brick-work session

## Context

After the 4.0 cutover, one **Refresh pictures** on prod made about 4,700 pipeline jobs. The drain ran them oldest first, so an Add queued during the refresh waited behind all of them, up to about 45 minutes for a new set's picture and price. **Jobs** showed thousands of rows for one action, and cancelling meant one job at a time.

## Options considered

1. **A batch table:** a new `batch` row with its own state, and jobs pointing to it. This means schema 4.2, an upgrade step and a migration of the API's job resources.
2. **A batch tag in the job's JSON payload** (`batch`), with the drain choosing interactive jobs first and the Jobs page summing a batch from its jobs. No schema change.
3. **A priority column on `job`.** This is also a schema change, and it says nothing about grouping or cancelling.

Recommendation: 2.

## Decision

- **Bulk refresh prices, Refresh pictures and fetching missing booklets** tag their jobs with one id per action, such as `pictures-3f9a1c2b`. A single Update and an Add's jobs carry none.
- **The drain picks one job at a time:** interactive before batch, oldest first within each. Before a batch job, a runnable fetch job (an Add's Rebrickable set or BrickLink part list) ends the pass, so the drainer runs it next. A new set waits at most for the job in hand.
- **Budgets are untouched:** a batch item that hits a source's daily budget waits like any job, and the rest of the batch goes on.
- **Cancel** ends the batch's jobs that have not started, or are waiting for budget, as failed `Cancelled`, with no retry and one event. The job in hand finishes.
- **Jobs** shows each batch as one row under **Bulk actions**: progress, done, failed, cancelled and to go, the budget wait, the failed items with their reasons (the first 50), and Cancel. Its jobs are no longer rows of their own.

## Consequences

- No schema change and no upgrade: older jobs simply have no tag.
- API v2's job list still shows a batch's jobs one by one. Grouping them there is an API change, left for a later issue if wanted.
- Ordering by a JSON field costs a scan of the open jobs per pick. That is fine at thousands of jobs; a much larger queue would want an index on the expression.
