"""Reads for the copy page's part list (design 4.2 to 4.5; issue #112, M.10 batch A): which list a copy carries and how to say so, the
retired lines it keeps, where each figure line's parts came from, the pending BrickLink switch in words and the switch choices.
Read-only: every write is `copies` and `pending`."""
from . import copies, pending
from .connect import has_catalogue, now


def choice_key(choice):
    """A choice as the text a form carries: `rebrickable:2`, `rebrickable_api`, `bricklink`."""
    if choice is None:
        return ''
    return f'rebrickable:{choice["version"]}' if choice['source'] == 'rebrickable' else choice['source']


def parse_choice(text):
    """The inverse of `choice_key`; a ValueError for text it did not write."""
    source, _, version = str(text).partition(':')
    if source == 'rebrickable' and version.isdecimal():
        return {'source': 'rebrickable', 'version': int(version)}
    if source in ('bricklink', 'rebrickable_api') and not version:
        return {'source': source}
    raise ValueError('Choose a part list')


def _ordinals(db, item_id):
    versions = copies._versions(db, item_id)
    return {v['version']: (v['ordinal'], len(versions), bool(v['is_latest'])) for v in versions}


def source_label(db, source, version, item_id, fetched_id=None):
    """`(label, is_latest)` of a list: "Rebrickable · version 2 of 3" (latest when it is), "Rebrickable · fetched", "BrickLink's list"."""
    if source == 'rebrickable':
        found = _ordinals(db, item_id).get(version)
        return (f'Rebrickable · version {found[0]} of {found[1]}', found[2]) if found else (f'Rebrickable · version {version}', False)
    if source == 'rebrickable_api':
        return 'Rebrickable · fetched', True
    if source == 'bricklink':
        return "BrickLink's list", False
    if source == 'migrated':
        return 'Migrated list', False
    return 'No part list', False


def figure_source(db, row):
    """What a figure line (a `copy_figure` row) says about where its parts came from (design 4.5)."""
    source = row['inventory_source']
    if source == 'rebrickable':
        label, latest = source_label(db, source, row['inventory_version'], row['item_id'])
        return f'Parts from {label}'
    if source == 'rebrickable_api':
        return 'Parts fetched from Rebrickable'
    if source == 'none':
        return 'Parts unknown for this figure: no Rebrickable list'
    return 'Parts from a migrated list'


def retired_counts(db, copy_id):
    """`{'lines': n, 'marked': m}`: the copy's retired part lines and figure lines, and those that carried a mark when they left."""
    lines = db.execute('''SELECT count(*), coalesce(sum(checked>0 OR missing>0 OR damaged>0), 0) FROM main.copy_part
                          WHERE copy_id=? AND retired_at IS NOT NULL''', (copy_id,)).fetchone()
    figures = db.execute('''SELECT count(*), coalesce(sum(missing>0), 0) FROM main.copy_figure
                            WHERE copy_id=? AND retired_at IS NOT NULL''', (copy_id,)).fetchone()
    return {'lines': lines[0] + figures[0], 'marked': lines[1] + figures[1]}


def retired_lines(db, copy_id):
    """The retired rows themselves, newest set lines first: part lines `{item_id, color_id, quantity, missing, damaged, checked,
    figure_item_id}` and figure lines (`color_id` None, `figure_item_id` None, `figure` True)."""
    rows = [dict(r, figure=False) for r in db.execute(
        '''SELECT p.item_id, p.color_id, p.quantity, p.missing, p.damaged, p.checked, p.is_spare, f.item_id AS figure_item_id
           FROM main.copy_part p LEFT JOIN main.copy_figure f ON f.id=p.copy_figure_id
           WHERE p.copy_id=? AND p.retired_at IS NOT NULL ORDER BY p.retired_at DESC, p.id''', (copy_id,))]
    rows += [dict(r, figure=True, color_id=None, damaged=0, checked=0, is_spare=0, figure_item_id=None) for r in db.execute(
        '''SELECT item_id, quantity, missing FROM main.copy_figure WHERE copy_id=? AND retired_at IS NOT NULL ORDER BY id''', (copy_id,))]
    return rows


def _pending_words(db, copy_id):
    offer = pending.pending_offer(db, copy_id)
    if offer is None:
        return None
    job, state = offer['job'], offer['state']
    retry = (job.get('retry_at') or '')[:16].replace('T', ' ')
    if state == 'ready':
        return {'state': 'ready', 'marked': offer['marked'], 'title': 'BrickLink list ready',
                'detail': "Fetched. This copy has marks, so it stays on Rebrickable's list until you switch.", 'job_id': job['id']}
    if state == 'failed':
        return {'state': 'failed', 'title': 'BrickLink list not fetched',
                'detail': "The fetch failed. The copy stays on Rebrickable's list; cancel to stop waiting.", 'job_id': job['id']}
    if job['state'] == 'waiting_for_budget':
        why = f"Waiting for today's BrickLink budget{' · tries again ' + retry + ' UTC' if retry else ''}"
    elif job['state'] == 'failed':
        why = f"Waiting for the network{' · tries again ' + retry + ' UTC' if retry else ''}"
    else:
        why = 'Fetching now' if job['state'] == 'running' else 'Queued to fetch'
    return {'state': 'waiting', 'title': 'BrickLink list pending', 'job_id': job['id'], 'job_state': job['state'],
            'detail': f"{why}. The copy stays usable on Rebrickable's list and switches by itself when the list arrives."}


def copy_part_list(db, copy_id):
    """Everything the copy page's Part list control and notes say. `choices` is the Add picker's read for the set; `control` is
    whether the Switch action is offered (only when there is a choice, or the copy's own list is gone or migrated)."""
    copy = copies._copy_row(db, copy_id)
    label, latest = source_label(db, copy['inventory_source'], copy['inventory_version'], copy['item_id'], copy['fetched_inventory_id'])
    picker = copies.part_list_choices(db, copy['item_id'])
    lines = db.execute('''SELECT count(*) FROM main.copy_part WHERE copy_id=? AND copy_figure_id IS NULL AND retired_at IS NULL AND is_spare=0''',
                       (copy_id,)).fetchone()[0]
    spare = db.execute('''SELECT count(*) FROM main.copy_part WHERE copy_id=? AND copy_figure_id IS NULL AND retired_at IS NULL AND is_spare=1''',
                       (copy_id,)).fetchone()[0]
    figures = db.execute('SELECT count(*) FROM main.copy_figure WHERE copy_id=? AND retired_at IS NULL', (copy_id,)).fetchone()[0]
    changes = copies.part_list_changes(db, copy_id) if has_catalogue(db) else []
    plan = None
    if any(c['choice'] and c['kind'] == copies.CHANGED for c in changes):
        copy_row = copies._copy_row(db, copy_id)                                       # `_plan` is what the real switch runs: it counts the lines that differ
        own_choice = next(c['choice'] for c in changes if c['choice'] and c['kind'] == copies.CHANGED)
        plan = copies._plan(db, copy_row, copies.build_target(db, copy_row['item_id'], own_choice), now())
    for c in changes:
        c['choice_key'] = choice_key(c['choice'])
        c['title'] = None
        if c['kind'] == copies.CHANGED and plan is not None:
            fig = c['figure_item_id']
            differ = sum(1 for o in plan['lines'] if (o['key'][0] if o.get('key') else None) == fig)
            what = source_label(db, c['source'], c['version'], fig if fig is not None else c['item_id'])[0]
            subject = what if fig is None else "this figure's list, " + what.replace('Rebrickable · ', '')
            c['differ'] = differ
            c['title'] = (f"Rebrickable changed {what.replace('Rebrickable · ', '')} since this copy was built" if fig is None else
                          f"Rebrickable changed {subject} since this copy was built") + (
                f" · {differ} {'line differs' if differ == 1 else 'lines differ'}" if differ else ' · no line differs')
    own = next((c for c in changes if c['figure_id'] is None), None)
    figure_changes = {c['figure_id']: c for c in changes if c['figure_id'] is not None}
    gone = own is not None and own['kind'] == copies.GONE
    return {'copy_id': copy_id, 'item_id': copy['item_id'], 'source': copy['inventory_source'], 'version': copy['inventory_version'],
            'label': label, 'latest': latest, 'lines': lines, 'spare': spare, 'figures': figures,
            'choices': picker, 'control': bool(picker['needs_choice'] or gone or copy['inventory_source'] == 'migrated'),
            'pending': _pending_words(db, copy_id), 'changed': own, 'figure_changes': figure_changes,
            'retired': retired_counts(db, copy_id)}
