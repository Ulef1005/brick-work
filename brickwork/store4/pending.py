"""A copy waiting for BrickLink's part list (design 4.3 decision F as amended; issue #108, M.6c).

`copies.create_copy` puts a copy on Rebrickable's list with `inventory_pending='bricklink'` and a queued `bricklink_subsets` job.
Nothing is added to the schema: the state is read from the copy and its job (Ulf's decision 1).

- `settle_pending` runs after the job (`jobs.run` calls it): a `done` job switches each copy on it automatically, but only while
  nothing on the copy is checked or marked; a marked copy stays pending, which with a `done` job IS the offer "BrickLink list
  ready, switch now?". A job that ended `failed` for good releases its copies (the copy stays on Rebrickable's list).
- `pending_offer` reads the state for a screen; `accept_pending` is the M.6b switch; `cancel_pending` declines.

Every write is its own transaction with one event on the copy: `part_list_switch` (receipt `trigger`), `pending_failed` or
`pending_cancel`."""
from . import copies
from .audit import Events, transaction
from .connect import now
from .errors import Store4Error

FAILED, CANCEL = 'pending_failed', 'pending_cancel'
BRICKLINK = {'source': 'bricklink'}


class NotPending(Store4Error):
    """The copy is not waiting for a BrickLink list."""


class NotReady(Store4Error):
    """The copy's BrickLink list is not fetched yet, so there is nothing to switch to."""


def _job(db, job_id):
    row = db.execute('SELECT id, state, error_code, error, retry_at, attempts FROM main.job WHERE id=?', (job_id,)).fetchone()
    return None if row is None else dict(row)


def _final_failure(job):
    """A failed job with no retry left or due; a failed job with a `retry_at` is still waiting."""
    return job['state'] == 'failed' and job['retry_at'] is None


has_marks = copies.has_marks


def _fetched(db, item_id):
    return copies._latest_fetched(db, item_id, 'bricklink')


def pending_offer(db, copy_id):
    """None when the copy is not pending, else what a screen says about it:

    - `{'state': 'waiting', 'job': {...}}`: "BrickLink list pending"; the job is queued, running, waiting for budget or retrying.
    - `{'state': 'ready', 'job': {...}, 'marked': bool, 'preview': preview_switch(...)}`: "BrickLink list ready, switch now?";
      `preview['not_carried_over']` lists what the switch would not carry over. A copy with no marks is switched by
      `settle_pending` on its own; `ready` is what a marked copy shows.
    - `{'state': 'failed', 'job': {...}}`: the job failed for good and `settle_pending` has not released the copy yet."""
    copy = copies._copy_row(db, copy_id)
    if copy['inventory_pending'] is None:
        return None
    job = _job(db, copy['pending_job_id'])
    if job['state'] == 'done' and _fetched(db, copy['item_id']) is not None:
        return {'state': 'ready', 'job': job, 'marked': has_marks(db, copy_id), 'preview': copies.preview_switch(db, copy_id, BRICKLINK)}
    if _final_failure(job):
        return {'state': 'failed', 'job': job}
    return {'state': 'waiting', 'job': job}


def accept_pending(db, copy_id, *, via, actor=None):
    """The user accepts the offer: the M.6b switch to BrickLink's fetched list, receipt `trigger` `{'accepted': True, 'job_id'}`.
    Refused (`NotPending`, `NotReady`) unless the copy is pending and its job is done with a list stored. Returns the receipt."""
    with transaction(db, 'accepting a pending BrickLink list'):
        return accept_pending_in(db, copy_id, via=via, actor=actor)


def accept_pending_in(db, copy_id, *, via, actor=None):
    """`accept_pending` inside the caller's open write transaction (it opens none and commits nothing)."""
    if not db.in_transaction:
        raise Store4Error('accept_pending_in needs the caller\'s open write transaction; use accept_pending()')
    copy = copies._copy_row(db, copy_id)
    if copy['inventory_pending'] is None:
        raise NotPending(f'copy {copy_id} is not waiting for a BrickLink list')
    job = _job(db, copy['pending_job_id'])
    if job['state'] != 'done' or _fetched(db, copy['item_id']) is None:
        raise NotReady(f'the BrickLink list for copy {copy_id} is not fetched yet (job {job["id"]} is {job["state"]})')
    return copies.switch_part_list_in(db, copy_id, BRICKLINK, via=via, actor=actor, while_pending_on=job['id'],
                                      trigger={'accepted': True, 'job_id': job['id']})


def cancel_pending(db, copy_id, *, via, actor=None):
    """The user declines (or gives up waiting): pending and its job id are cleared in one transaction with one event (`copy`,
    field `pending_cancel`). Rebrickable's lines are not touched. The job is left alone: `jobs` has no cancel path and no state
    for one, and a fetched list is useful to the set's next copy anyway. Returns the event's `new_value`."""
    with transaction(db, 'cancelling a pending BrickLink list'):
        return cancel_pending_in(db, copy_id, via=via, actor=actor)


def cancel_pending_in(db, copy_id, *, via, actor=None):
    """The user declines (or gives up waiting): pending and its job id are cleared in one transaction with one event (`copy`,
    field `pending_cancel`). Rebrickable's lines are not touched. The job is left alone: `jobs` has no cancel path and no state
    for one, and a fetched list is useful to the set's next copy anyway. Returns the event's `new_value`.

    `cancel_pending` inside the caller's open write transaction (it opens none and commits nothing)."""
    if not db.in_transaction:
        raise Store4Error('cancel_pending_in needs the caller\'s open write transaction; use cancel_pending()')
    return _release(db, copy_id, CANCEL, via, actor, why=None)


def _release(db, copy_id, field, via, actor, *, why, job_id=None):
    copy = copies._copy_row(db, copy_id)
    if copy['inventory_pending'] is None or (job_id is not None and copy['pending_job_id'] != job_id):
        raise NotPending(f'copy {copy_id} is not waiting for a BrickLink list' + (f' from job {job_id}' if job_id else ''))
    job = _job(db, copy['pending_job_id'])
    db.execute('UPDATE main.copy SET inventory_pending=NULL, pending_job_id=NULL, updated_at=? WHERE id=?', (now(), copy_id))
    new = {'job_id': job['id'], 'job_state': job['state'], 'inventory_source': copy['inventory_source'],
           'inventory_version': copy['inventory_version']}
    if why:
        new.update(error_code=job['error_code'], error=job['error'])
    Events(db, via, actor).write('copy', copy_id, field, old={'inventory_pending': 'bricklink', 'pending_job_id': job['id']}, new=new)
    return new


def settle_pending(db, job_id=None, *, via, actor=None):
    """Settle the copies waiting on `job_id` (all pending copies when None) and return one entry per copy that was acted on or
    deliberately left, `{'copy_id', 'job_id', 'outcome'}`:

    - `switched`: the job is done with a BrickLink list stored and nothing on the copy is checked or marked; the copy switched
      (receipt `trigger` `{'automatic': True, 'job_id'}`, `event_id` added here).
    - `offered`: done, but the copy has marks; it stays pending, `pending_offer` says what would not carry over.
    - `released`: the job failed for good (not_found, invalid_reply, unidentified, source_not_configured, retries used up); pending
      is cleared with a `pending_failed` event naming the job's error code, the copy stays on its Rebrickable list.
    - `error`: the switch itself was refused (`error` has the text); the copy stays pending and usable.

    A queued, running, waiting or retrying job leaves its copies pending and is not reported. Each copy is its own transaction."""
    args = () if job_id is None else (job_id,)
    ids = [r[0] for r in db.execute(f"""SELECT id FROM main.copy WHERE inventory_pending='bricklink'
                                        {'' if job_id is None else 'AND pending_job_id=?'} ORDER BY created_at, id""", args)]
    out = []
    for copy_id in ids:
        copy = copies._copy_row(db, copy_id)
        if copy['inventory_pending'] is None:                       # settled by an earlier step of this loop
            continue
        job = _job(db, copy['pending_job_id'])
        entry = {'copy_id': copy_id, 'job_id': job['id']}
        if job['state'] == 'done' and _fetched(db, copy['item_id']) is not None:
            try:
                receipt = copies.switch_part_list(db, copy_id, BRICKLINK, via=via, actor=actor, unless_marked=True,
                                                  while_pending_on=job['id'], trigger={'automatic': True, 'job_id': job['id']})
            except copies.PendingChanged:                           # cancelled or settled by another connection meanwhile
                continue
            except copies.CopyMarked:
                out.append({**entry, 'outcome': 'offered'})
            except Store4Error as exc:
                out.append({**entry, 'outcome': 'error', 'error': str(exc)})
            else:
                out.append({**entry, 'outcome': 'switched', 'event_id': receipt['event_id']})
        elif _final_failure(job):
            try:
                with transaction(db, 'releasing a pending copy'):
                    _release(db, copy_id, FAILED, via, actor, why=True, job_id=job['id'])
            except NotPending:                                      # cancelled or settled by another connection meanwhile
                continue
            out.append({**entry, 'outcome': 'released', 'error_code': job['error_code']})
    return out
