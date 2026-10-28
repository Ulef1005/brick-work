"""Check Set Parts on the 4.0 store (M.8d, issue #110; design 5 `part_check`, 4.4, 4.5, 2.4 invariant 10).

A session is a `part_check` row per copy (and one per figure line inside the copy): its order and answers are kept by token, and a
token is a line's own id, which an in-place part-list switch keeps: `p:<copy_part.id>` for a required or spare part line and
`f:<copy_figure.id>` for a whole figure line. Only live lines (`retired_at IS NULL`) are in a check. The set sequence is the required
parts, then the whole figures, then an optional spare pass the user opts into at the end; a figure's own parts (its `copy_part` rows,
`copy_figure_id` set) are checked in a separate session inside the copy.

Every answer is ONE event `(part_check, <copy id>[:fig:<line id>], save)` holding the old and new state of what it touched (the
session row, the lines, the "Set is checked" flag, the copy's derived completeness) and the client's `operation` id, so a retried
request returns the first answer's result. Undo is the registered undoer of that event (`core.undo`): it refuses when the touched rows
changed since, restores them and writes `event_undo`. Check sessions restart at 4.0: the 3.3 `checker:*` settings were not migrated.
"""
from collections import defaultdict
from contextvars import ContextVar
import json
import re
import uuid

from ..store4.audit import value_text
from ..store4.connect import now
from . import errors
from . import undo as undoing
from .admin import OPERATION_KEY, audit, origin
from .completeness import derived_state
from .transaction import transaction

CHECKED_FLAG = 'Set is checked'
ORDERS = ('inventory', 'largest', 'colour')
SESSION_COLUMNS = ('session_id', 'order_mode', 'spares', 'session_json', 'finished', 'started_at', 'updated_at')
_REQUEST = ContextVar('checker_request_operation', default=None)       # the client's operation id while an Undo runs, for its receipt


def entity_id(copy_id, figure=None):
    """The event entity id of a session: the copy, or one figure line inside it."""
    return copy_id + (':fig:' + str(figure) if figure else '')


def _figure_of(entity):
    copy_id, _, figure = entity.partition(':fig:')
    return copy_id, int(figure) if figure else None


# ---------- ordering ----------

def sorter(mode, position):
    """Sort key of the rows of one kind for an order mode. Largest first is the physical size from the catalogue name and category
    (`part_size.volume`; the item's `size_key` is the sorted dimensions of the same name and cannot tell a plate from a brick), then
    the larger count, then one colour after another so a part's colours stay together."""
    if mode == 'largest':
        from .part_size import volume
        return lambda r: (-volume(r.get('name') or '', r.get('category') or ''), -(r['quantity'] or 0),
                          (r.get('color_name') or '').casefold(), r.get('item_no') or '', position[r['token']])
    if mode == 'colour':
        return lambda r: (r.get('color_name') or 'Unknown colour', r.get('item_no') or '', position[r['token']])
    return lambda r: position[r['token']]


def normalise(s, kinds):
    """Read model of a stored session against the current sequence.

    Tokens that are no longer part of the sequence (a line a switch retired, or spare rows before the spare question was answered
    "Yes") are dropped from the visible order without error, and the cursor keeps pointing at the same remaining step. A required line the
    session has not met (a switch to another part list added it, design 4.4) joins the end of the walk, so the check can still answer it and
    finish. Nothing stored is rewritten here; the next save persists the changed form and its receipt keeps the raw old value."""
    if not s:
        return s
    keep_spares = s['spares'] == 'yes'

    def visible(token):
        return token in kinds and (kinds[token] != 'spare' or keep_spares)
    dropped = sum(not visible(t) for t in s['order'][:s['cursor']])
    s['order'] = [t for t in s['order'] if visible(t)]
    s['cursor'] = max(0, min(len(s['order']), s['cursor'] - dropped))
    known = set(s['order'])
    s['order'] += [t for t, kind in kinds.items() if kind != 'spare' and t not in known]
    s['answers'] = {t: a for t, a in s['answers'].items() if visible(t)}
    s['misses'] = [t for t in s['misses'] if visible(t)]
    return s


# ---------- the copy, the flag, the rows ----------

def copy(db, copy_id):
    row = db.execute('SELECT * FROM main.copy WHERE id=? AND archived_at IS NULL', (copy_id,)).fetchone()
    if not row:
        raise ValueError('This copy is no longer available')
    return dict(row)


def checked_flag(db, create=False):
    """The id of the status flag "Set is checked" (live), or None; with `create` it is made as a system flag and the creation is audited."""
    row = db.execute("SELECT id FROM main.flag WHERE archived_at IS NULL AND kind='status' AND name=? ORDER BY id LIMIT 1", (CHECKED_FLAG,)).fetchone()
    if row:
        return row[0]
    if not create:
        return None
    flag = dict(id=uuid.uuid4().hex, name=CHECKED_FLAG, kind='status', shown_on_grid=1, system=1, created_at=now())
    db.execute('INSERT INTO main.flag(id,name,kind,shown_on_grid,system,created_at) VALUES(:id,:name,:kind,:shown_on_grid,:system,:created_at)', flag)
    audit(db, 'flag:' + flag['id'], 'record', None, flag)
    return flag['id']


def checked(db, copy_id):
    return db.execute("""SELECT 1 FROM main.copy_flag cf JOIN main.flag f ON f.id=cf.flag_id AND f.archived_at IS NULL
                         WHERE cf.copy_id=? AND f.kind='status' AND f.name=?""", (copy_id, CHECKED_FLAG)).fetchone() is not None


def _tidy(text):
    return (text or '').replace('LEGO', '').strip()


_PARTS = '''SELECT p.id,p.item_id,p.color_id,p.is_spare,p.quantity,p.missing,p.damaged,p.checked,i.name,i.category_name AS category,c.name AS color_name
            FROM main.copy_part p JOIN main.item i ON i.id=p.item_id LEFT JOIN main.color c ON c.id=p.color_id
            WHERE p.copy_id=? AND p.retired_at IS NULL AND '''
_FIGURES = '''SELECT f.id,f.item_id,NULL AS color_id,0 AS is_spare,f.quantity,f.missing,0 AS damaged,0 AS checked,i.name,i.category_name AS category,NULL AS color_name
              FROM main.copy_figure f JOIN main.item i ON i.id=f.item_id WHERE f.copy_id=? AND f.retired_at IS NULL ORDER BY f.id'''


def rows(db, copy_id, images=True, tokens=None, decorate=True, figure=None):
    """The sequence of a check: the required parts, the whole figures and the spare lines of a copy, all live.

    With `figure` (a `copy_figure` id) the rows are exactly that figure's required (non-spare) component lines. `decorate=False` is the
    write path's light read (names and sizes for ordering, no identity or picture lookups); `images=False` leaves the pictures out of
    the decorated rows. Each row: `token`, `kind` (`part`, `figure`, `spare`), `id`, `item_id`, `color_id`, `quantity`, `missing`,
    `damaged`, `checked` (a figure line has no `damaged` or `checked`: its `missing` is the answer)."""
    result = []
    if figure:
        sources = [('part', _PARTS + 'p.copy_figure_id=? AND p.is_spare=0 ORDER BY p.id', (copy_id, figure))]
        components = {}
    else:
        sources = [('part', _PARTS + 'p.copy_figure_id IS NULL ORDER BY p.id', (copy_id,)), ('figure', _FIGURES, (copy_id,))]
        components = {r[0]: (r[1], r[2] or 0) for r in db.execute(
            '''SELECT copy_figure_id,count(*),sum(missing) FROM main.copy_part WHERE copy_id=? AND copy_figure_id IS NOT NULL
               AND retired_at IS NULL AND is_spare=0 GROUP BY copy_figure_id''', (copy_id,))}
    for table, sql, params in sources:
        for raw in db.execute(sql, params):
            r = dict(raw)
            r['token'] = ('p:' if table == 'part' else 'f:') + str(r['id'])
            if tokens is not None and r['token'] not in tokens:
                continue
            r['kind'] = 'spare' if r['is_spare'] else table
            if table == 'figure':
                r['parts_lines'], r['parts_missing'] = components.get(r['id'], (0, 0))
            result.append(r)
    if decorate and result:
        from . import collection
        for r, d in zip(result, collection.decorate(db, result)):
            kind = r['kind']
            r.update(d)
            r['kind'] = kind                                           # the row's role in the check, not the item's kind
            r['name'] = _tidy(d['name']) or d['item_no']
            r['color_name'] = d.get('color_name') or 'Unknown colour'
            r['rgb'] = '#' + d['rgb'] if d.get('rgb') else None
            if not r['rgb']:
                r['ink'] = None
            if not images:
                r.pop('image', None)
    return result


def header(db, copy_id):
    c = copy(db, copy_id)
    from . import collection
    base = collection.decorate(db, [dict(item_id=c['item_id'])])[0]
    siblings = [r[0] for r in db.execute('SELECT id FROM main.copy WHERE item_id=? AND archived_at IS NULL ORDER BY created_at,id', (c['item_id'],))]
    c['label'] = 'Set ' + str(siblings.index(copy_id) + 1)
    c['name'] = _tidy(base['name']) or base['number_text']
    c['set_no'] = base['number_text'] or ''
    c['item_type'] = 'S'
    c['image'] = base['image']
    c['set_checked'] = checked(db, copy_id)
    return c


# ---------- the session ----------

def _session_row(db, copy_id, figure=None):
    return db.execute('SELECT * FROM main.part_check WHERE copy_id=? AND figure_key=?', (copy_id, figure or 0)).fetchone()


def _model(row):
    """The client's session from a `part_check` row."""
    if row is None:
        return None
    body = json.loads(row['session_json'])
    return dict(id=row['session_id'], order=body['order'], cursor=body['cursor'], answers=body['answers'], misses=body['misses'], undo=body['undo'],
                finished=bool(row['finished']), sort=row['order_mode'], spares=row['spares'])


def session(db, copy_id, figure=None):
    return _model(_session_row(db, copy_id, figure))


def _put_session(db, copy_id, figure, s, started_at=None):
    """Write the session `s` (the client's model) as the copy's row, replacing the one there (nothing else points at the row)."""
    db.execute('DELETE FROM main.part_check WHERE copy_id=? AND figure_key=?', (copy_id, figure or 0))
    stamp = now()
    body = json.dumps(dict(order=s['order'], cursor=s['cursor'], answers=s['answers'], misses=s['misses'], undo=s['undo']), separators=(',', ':'))
    db.execute('''INSERT INTO main.part_check(copy_id,copy_figure_id,session_id,order_mode,spares,session_json,finished,started_at,updated_at)
                  VALUES(?,?,?,?,?,?,?,?,?)''', (copy_id, figure, s['id'], s['sort'], s['spares'], body, int(bool(s['finished'])), started_at or stamp, stamp))


def _row_state(row):
    """A `part_check` row as a receipt keeps it (every stored column, the body as the text it is)."""
    return None if row is None else {k: row[k] for k in SESSION_COLUMNS}


def _restore_session(db, copy_id, figure, state):
    db.execute('DELETE FROM main.part_check WHERE copy_id=? AND figure_key=?', (copy_id, figure or 0))
    if state is not None:
        db.execute(f'INSERT INTO main.part_check(copy_id,copy_figure_id,{",".join(SESSION_COLUMNS)}) VALUES(?,?,{",".join("?" * len(SESSION_COLUMNS))})',
                   (copy_id, figure, *(state[k] for k in SESSION_COLUMNS)))


def snapshot(db, copy_id, tokens=(), figure=None):
    """What an answer touches, exactly as a receipt keeps it and an Undo compares it."""
    c = copy(db, copy_id)
    parts, figures = [], []
    for token in tokens:
        if token.startswith('p:'):
            row = db.execute('SELECT id,checked,missing,damaged FROM main.copy_part WHERE copy_id=? AND id=?', (copy_id, int(token[2:]))).fetchone()
            if row:
                parts.append(dict(row))
        elif token.startswith('f:'):
            row = db.execute('SELECT id,missing,updated_at FROM main.copy_figure WHERE copy_id=? AND id=?', (copy_id, int(token[2:]))).fetchone()
            if row:
                figures.append(dict(row))
    result = dict(session=_row_state(_session_row(db, copy_id, figure)), parts=parts, figures=figures)
    if not figure:
        # A figure check never touches the set's checked flag or completeness.
        result.update(checked_flag=checked(db, copy_id), copy={k: c[k] for k in ('completeness', 'completeness_source', 'updated_at')})
    return result


def _restore(db, copy_id, value, figure=None):
    if 'checked_flag' in value:
        flag = checked_flag(db, create=bool(value['checked_flag']))
        if flag:
            db.execute('DELETE FROM main.copy_flag WHERE copy_id=? AND flag_id=?', (copy_id, flag))
            if value['checked_flag']:
                db.execute('INSERT INTO main.copy_flag(copy_id,flag_id) VALUES(?,?)', (copy_id, flag))
    for r in value['parts']:
        db.execute('UPDATE main.copy_part SET checked=?,missing=?,damaged=? WHERE copy_id=? AND id=?', (r['checked'], r['missing'], r['damaged'], copy_id, r['id']))
    for r in value['figures']:
        db.execute('UPDATE main.copy_figure SET missing=?,updated_at=? WHERE copy_id=? AND id=?', (r['missing'], r['updated_at'], copy_id, r['id']))
    if 'copy' in value:
        c = value['copy']
        db.execute('UPDATE main.copy SET completeness=?,completeness_source=?,updated_at=? WHERE id=?', (c['completeness'], c['completeness_source'], c['updated_at'], copy_id))
    _restore_session(db, copy_id, figure, value['session'])


def _tokens(value):
    return ['p:' + str(r['id']) for r in value['parts']] + ['f:' + str(r['id']) for r in value['figures']]


def recompute(db, copy_id):
    """Derived completeness after an answer (only a copy whose completeness is derived changes)."""
    state = derived_state(db, copy_id)
    if state is not None:
        db.execute('UPDATE main.copy SET completeness=?,updated_at=? WHERE id=?', (state, now(), copy_id))


# ---------- the screens' reads ----------

def view(db, copy_id):
    c = header(db, copy_id)
    inventory = rows(db, copy_id)
    s = normalise(session(db, copy_id), {r['token']: r['kind'] for r in inventory})
    saved = db.execute("SELECT at FROM main.event WHERE entity_kind='part_check' AND entity_id=? AND field='save' AND via IN ('app','api','cli') ORDER BY id DESC LIMIT 1",
                       (entity_id(copy_id),)).fetchone() if s else None
    return dict(copy=c, rows=inventory, session=s, saved_at=saved[0] if saved else None)


def figure_view(db, copy_id, figure_id):
    """Check figure parts: one whole figure line's component rows inside this copy."""
    c = header(db, copy_id)
    whole = db.execute('SELECT * FROM main.copy_figure WHERE copy_id=? AND id=? AND retired_at IS NULL', (copy_id, figure_id)).fetchone()
    if not whole:
        raise ValueError('This figure is not in this copy')
    from . import collection
    label = collection.decorate(db, [dict(item_id=whole['item_id'])])[0]
    inventory = rows(db, copy_id, figure=figure_id)
    info = dict(id=figure_id, item_id=whole['item_id'], item_type='M', item_no=label['item_no'], quantity=whole['quantity'], missing=whole['missing'],
                name=_tidy(label['name']) or label['item_no'], image=label['image'])
    s = normalise(session(db, copy_id, figure_id), {r['token']: r['kind'] for r in inventory})
    return dict(copy=c, figure=info, rows=inventory, session=s)


def choices(db):
    """The chooser: every live copy with its counts and its set-level session. A fixed number of queries, however many copies."""
    from . import collection
    flagged = {r[0] for r in db.execute("""SELECT cf.copy_id FROM main.copy_flag cf JOIN main.flag f ON f.id=cf.flag_id AND f.archived_at IS NULL
                                           WHERE f.kind='status' AND f.name=?""", (CHECKED_FLAG,))}
    sessions = {r['copy_id']: _model(r) for r in db.execute('SELECT * FROM main.part_check WHERE copy_figure_id IS NULL')}
    required = defaultdict(set)
    if sessions:
        wanted = json.dumps(sorted(sessions))
        for r in db.execute('''SELECT copy_id,id FROM main.copy_part WHERE retired_at IS NULL AND is_spare=0 AND copy_figure_id IS NULL
                               AND copy_id IN (SELECT value FROM json_each(?))''', (wanted,)):
            required[r[0]].add('p:' + str(r[1]))
        for r in db.execute('SELECT copy_id,id FROM main.copy_figure WHERE retired_at IS NULL AND copy_id IN (SELECT value FROM json_each(?))', (wanted,)):
            required[r[0]].add('f:' + str(r[1]))
    counts = {r[0]: (r[1], r[2]) for r in db.execute('''SELECT copy_id,count(*),sum(is_spare=0) FROM main.copy_part
                                                         WHERE retired_at IS NULL AND copy_figure_id IS NULL GROUP BY copy_id''')}
    figures = {r[0]: r[1] for r in db.execute('SELECT copy_id,count(*) FROM main.copy_figure WHERE retired_at IS NULL GROUP BY copy_id')}
    base = [dict(r) for r in db.execute('SELECT * FROM main.copy WHERE archived_at IS NULL ORDER BY item_id,created_at,id')]
    decorated = {r['item_id']: r for r in collection.decorate(db, [dict(item_id=i) for i in sorted({c['item_id'] for c in base})])}
    result, ordinals = [], defaultdict(int)
    for c in base:
        ordinals[c['item_id']] += 1
        d = decorated[c['item_id']]
        c['label'] = 'Set ' + str(ordinals[c['item_id']])
        c['name'] = _tidy(d['name']) or d['number_text']
        c['set_no'] = d['number_text'] or ''
        c['item_type'] = 'S'
        c['image'] = d['image']
        c['set_checked'] = c['id'] in flagged
        stored = sessions.get(c['id'])
        wanted_tokens = required.get(c['id'], set())
        completed = sum((stored or {}).get('answers', {}).get(t) == 'answered' for t in wanted_tokens)   # skipped tokens stay to check
        lines, parts = counts.get(c['id'], (0, 0))
        result.append(dict(copy=c, entries=lines + figures.get(c['id'], 0), parts=parts or 0, session=stored, completed=completed, total=len(wanted_tokens)))
    return sorted(result, key=lambda r: (0 if r['session'] and not r['session']['finished'] else 2 if r['copy']['set_checked'] else 1, -r['entries'], r['copy']['id']))


def saved_view(db, copy_id, tokens=(), figure=None):
    """The reply of a save: the changed rows only (the client keeps what it has, pictures included) and the progress counts."""
    inventory = rows(db, copy_id, decorate=False, figure=figure)
    s = normalise(session(db, copy_id, figure), {r['token']: r['kind'] for r in inventory})
    counts = dict(found=0, missing=0, skipped=0, remaining=0)
    for r in inventory:
        if r['kind'] == 'spare':
            continue
        answer = (s or {}).get('answers', {}).get(r['token'])
        category = 'remaining' if not answer else 'skipped' if answer == 'skipped' else 'missing' if (r['missing'] or 0) > 0 else 'found'
        counts[category] += 1
    c = copy(db, copy_id)
    c['set_checked'] = checked(db, copy_id)
    return dict(partial=True, copy=c, rows=rows(db, copy_id, images=False, tokens=set(tokens), figure=figure), progress=counts, session=s)


# ---------- the writes ----------

def mark_row(db, table, key, row, fields):
    """The checker's bounds and update for an answer (design 2.4 invariant 10: each count on its own, 0 to the quantity)."""
    if not fields:
        raise errors.ValidationFailed('Choose a count to change')
    for field, value in fields.items():
        if field == 'checked':
            if type(value) is not bool:
                raise errors.ValidationFailed('Choose whether the part is checked')
        elif type(value) is not int or not 0 <= value <= row['quantity']:
            raise errors.ValidationFailed('Choose a count within the required quantity')
    values = {k: int(v) if k == 'checked' else v for k, v in fields.items()}
    if table == 'copy_figure':
        values['updated_at'] = now()
    db.execute('UPDATE main.' + table + ' SET ' + ','.join(k + '=?' for k in values) + ' WHERE ' + ' AND '.join(k + '=?' for k in key),
               (*values.values(), *key.values()))


def _figure_line(db, copy_id, figure):
    if not figure or not db.execute('SELECT 1 FROM main.copy_figure WHERE copy_id=? AND id=? AND retired_at IS NULL', (copy_id, figure)).fetchone():
        raise ValueError('This figure is not in this copy')


def _earlier(db, operation, entity):
    """The tokens of the answer already saved under this operation id, or None."""
    found = db.execute("""SELECT field,new_value FROM main.event WHERE entity_kind='part_check' AND entity_id=? AND field IN ('save','undo')
                          AND json_extract(new_value,'$.operation')=? ORDER BY id LIMIT 1""", (entity, operation)).fetchone()
    if not found:
        return None
    value = json.loads(found['new_value'])
    return value['tokens'] if found['field'] == 'undo' else _tokens(value)


def write(db, copy_id, payload, figure=None):
    """One ordered, idempotent answer and its receipt. `figure` is a `copy_figure` id (a figure check inside the copy)."""
    operation = payload.get('operation')
    if not isinstance(operation, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,80}', operation):
        raise ValueError('A save receipt is required')
    entity = entity_id(copy_id, figure)
    with transaction(db):
        copy(db, copy_id)
        if figure:
            _figure_line(db, copy_id, figure)
        earlier = _earlier(db, operation, entity)
        if earlier is not None:
            return saved_view(db, copy_id, earlier, figure)
        if not figure:
            checked_flag(db, create=True)
        action = payload.get('action')
        all_rows = rows(db, copy_id, decorate=False, figure=figure)
        by_token = {r['token']: r for r in all_rows}
        position = {r['token']: i for i, r in enumerate(all_rows)}
        s = normalise(session(db, copy_id, figure), {t: r['kind'] for t, r in by_token.items()})
        token = payload.get('token')
        tokens = [token] if token in by_token else []

        def settle():
            if not figure:                                   # a figure check never changes the set's derived completeness
                recompute(db, copy_id)

        if action == 'undo':
            if s and payload.get('session') != s['id']:
                raise ValueError('This check changed. Reload to continue.')
            if not s or not s['undo']:
                raise ValueError('Nothing to undo')
            via, actor = origin()
            event = db.execute('SELECT * FROM main.event WHERE id=?', (s['undo'][-1],)).fetchone()
            tokens = _tokens(json.loads(event['new_value']))
            marker = _REQUEST.set((operation, tokens))
            try:
                undoing.undo_event(db, event['id'], via=via, actor=actor)
            finally:
                _REQUEST.reset(marker)
            return saved_view(db, copy_id, tokens, figure)
        old = snapshot(db, copy_id, tokens, figure)
        old_row = _session_row(db, copy_id, figure)
        started_at = old_row['started_at'] if old_row else None
        if action in ('start', 'restart'):
            if action == 'restart' and (not s or payload.get('session') != s['id']):
                raise ValueError('This check changed. Reload to continue.')
            if action == 'start' and s and not s.get('finished'):
                return saved_view(db, copy_id, figure=figure)
            order_mode = payload.get('order', 'inventory')
            if order_mode not in ORDERS:
                raise ValueError('Choose an order')
            sort = sorter(order_mode, position)
            ordered = sorted((r for r in all_rows if r['kind'] != 'spare'), key=lambda r: ({'part': 0, 'figure': 1}[r['kind']], sort(r)))
            if figure and not ordered:
                raise ValueError('This figure has no recorded parts')
            s = dict(id=uuid.uuid4().hex, order=[r['token'] for r in ordered], cursor=0, answers={}, misses=[], undo=[], finished=False, sort=order_mode, spares=None)
            started_at = None
        else:
            if not s or payload.get('session') != s['id']:
                raise ValueError('This check changed. Reload to continue.')
            if action in ('answer', 'found_one', 'skip', 'select'):
                if not tokens or token not in s['order']:
                    raise ValueError('Choose a part from this copy')
                r = by_token[token]
                if action == 'select':
                    s['cursor'] = s['order'].index(token)
                elif action == 'skip':
                    s['answers'][token] = 'skipped'
                    s['cursor'] = min(s['order'].index(token) + 1, len(s['order']))
                    settle()
                else:
                    quantity = r['quantity']
                    found = quantity - (r['missing'] or 0) + 1 if action == 'found_one' else payload.get('found')
                    if isinstance(found, bool) or not isinstance(found, int) or not 0 <= found <= quantity:
                        raise ValueError('Choose a count within the required quantity')
                    missing = quantity - found
                    if token.startswith('p:'):
                        mark_row(db, 'copy_part', dict(id=r['id'], copy_id=copy_id), r, dict(checked=True, missing=missing))
                    else:
                        mark_row(db, 'copy_figure', dict(id=r['id'], copy_id=copy_id), r, dict(missing=missing))
                    s['answers'][token] = 'answered'
                    if missing:
                        s['misses'] = [token] + [t for t in s['misses'] if t != token]
                    if action == 'answer':
                        s['cursor'] = min(s['order'].index(token) + 1, len(s['order']))
                    settle()
            elif action in ('back', 'next'):
                s['cursor'] = max(0, min(len(s['order']), s['cursor'] + (-1 if action == 'back' else 1)))
            elif action == 'spares':
                # The last step of the set check: spare parts are opt in, default no (design 4.5).
                include = payload.get('include')
                spare = [r for r in all_rows if r['kind'] == 'spare']
                if figure or not spare:
                    raise ValueError('This copy has no spare parts')
                if not isinstance(include, bool):
                    raise ValueError('Choose whether to include spare parts')
                if s['spares'] == 'yes':
                    raise ValueError('Spare parts are already included')
                s['spares'] = 'yes' if include else 'no'
                if include:
                    sort = sorter(s.get('sort', 'inventory'), position)
                    s['order'] += [r['token'] for r in sorted(spare, key=sort) if r['token'] not in s['order']]
            elif action == 'finish':
                if not figure:
                    required = [r for r in all_rows if r['kind'] != 'spare']
                    wants = payload.get('checked')
                    if not isinstance(wants, bool):
                        raise ValueError('Choose whether the set is checked')
                    if wants and any(s['answers'].get(r['token']) != 'answered' for r in required):
                        raise ValueError('Answer the skipped and unchecked parts and figures first')
                    flag = checked_flag(db)
                    if wants:
                        db.execute('INSERT OR IGNORE INTO main.copy_flag(copy_id,flag_id) VALUES(?,?)', (copy_id, flag))
                    else:
                        db.execute('DELETE FROM main.copy_flag WHERE copy_id=? AND flag_id=?', (copy_id, flag))
                s['finished'] = True
                settle()
            else:
                raise ValueError('Unknown checker action')
        event_id = db.execute('SELECT coalesce(max(id),0)+1 FROM main.event').fetchone()[0]
        s['undo'].append(event_id)                                   # the session names the receipt that undoes this step
        _put_session(db, copy_id, figure, s, started_at)
        new = snapshot(db, copy_id, tokens, figure)
        via, actor = origin()
        stored = db.execute('''INSERT INTO main.event(at,via,actor,entity_kind,entity_id,field,old_value,new_value,operation_key)
                               VALUES(?,?,?,?,?,?,?,?,?)''', (now(), via, actor, 'part_check', entity, 'save', value_text(old),
                                                              value_text(dict(new, operation=operation)), OPERATION_KEY.get())).lastrowid
        if stored != event_id:
            raise RuntimeError('The save receipt got another id than the check session recorded')
    return saved_view(db, copy_id, tokens, figure)


# ---------- marks outside a check session (API v2, M.11c) ----------
#
# A person (or a client) sets a line's missing, damaged or checked count without walking a session, ticks a whole copy "checked", or sets the
# counts of a loose figure's parts. Each is ONE receipt: a copy's marks and its checked flag are `part_check` events of the same shape a check
# answer writes (`snapshot` before and after, so `_undo_save` takes them back and refuses when the touched rows changed since); a loose figure's
# parts are a `collection` receipt over `stock_part`, which the collection's undoer reverses.

def _record(db, copy_id, old, new):
    via, actor = origin()
    return db.execute('''INSERT INTO main.event(at,via,actor,entity_kind,entity_id,field,old_value,new_value,operation_key)
                          VALUES(?,?,?,?,?,?,?,?,?)''', (now(), via, actor, 'part_check', entity_id(copy_id), 'save', value_text(old), value_text(new),
                                                         OPERATION_KEY.get())).lastrowid


def mark(db, copy_id, edits):
    """Set counts on lines of a live copy: `edits` is `[(token, fields)]`, a token `p:<copy_part id>` or `f:<copy_figure id>` (a figure
    line takes `missing` only) and fields among `missing`, `damaged` (each 0 to the line's quantity) and `checked`. One receipt; the derived
    completeness follows. A token that is no live line of the copy is `NotFound`. Returns the event id."""
    with transaction(db):
        copy(db, copy_id)
        tokens = [token for token, _ in edits]
        old = snapshot(db, copy_id, tokens)
        for token, fields in edits:
            kind, _, identifier = token.partition(':')
            table = {'p': 'copy_part', 'f': 'copy_figure'}[kind]
            row = db.execute(f'SELECT * FROM main.{table} WHERE copy_id=? AND id=? AND retired_at IS NULL', (copy_id, int(identifier))).fetchone()
            if row is None:
                raise errors.NotFound('No such line in this copy')
            if table == 'copy_figure' and set(fields) - {'missing'}:
                raise errors.ValidationFailed('A whole figure has a missing count only')
            mark_row(db, table, dict(id=row['id'], copy_id=copy_id), row, fields)
        recompute(db, copy_id)
        return _record(db, copy_id, old, snapshot(db, copy_id, tokens))


def set_checked(db, copy_id, wanted):
    """Set or clear the status flag "Set is checked" on a live copy (made when it does not exist yet and is wanted) and let the derived
    completeness follow. One receipt, also when nothing changes. Returns the event id."""
    with transaction(db):
        copy(db, copy_id)
        flag = checked_flag(db, create=bool(wanted))
        old = snapshot(db, copy_id)
        if flag:
            db.execute('DELETE FROM main.copy_flag WHERE copy_id=? AND flag_id=?', (copy_id, flag))
            if wanted:
                db.execute('INSERT INTO main.copy_flag(copy_id,flag_id) VALUES(?,?)', (copy_id, flag))
        recompute(db, copy_id)
        return _record(db, copy_id, old, snapshot(db, copy_id))


def mark_stock_parts(db, stock_id, edits):
    """Set counts on the part lines of a live loose minifigure: `edits` is `[(item id, colour id, spare 0 or 1, fields)]` with fields among
    `missing`, `damaged` (each 0 to the line's quantity) and `checked`. One `collection` receipt over `stock_part`. Returns the event id."""
    from . import collection
    with transaction(db):
        figure = db.execute('SELECT * FROM main.stock WHERE id=? AND archived_at IS NULL', (stock_id,)).fetchone()
        if figure is None:
            raise errors.NotFound('No such stock line')
        if figure['kind'] != 'minifigure':
            raise errors.ValidationFailed('Only a loose minifigure has parts')
        lines = []
        for item_id, color_id, spare, fields in edits:
            row = db.execute('SELECT * FROM main.stock_part WHERE stock_id=? AND item_id=? AND color_id=? AND is_spare=? AND retired_at IS NULL',
                             (stock_id, item_id, color_id, spare)).fetchone()
            if row is None:
                raise errors.NotFound('This figure has no such part line')
            lines.append((row, fields))
        ids = [row['id'] for row, _ in lines]
        if len(set(ids)) != len(ids):
            raise errors.ValidationFailed('Name each part line once')
        old = collection.snapshot(db, 'stock_part', ids)
        for row, fields in lines:
            mark_row(db, 'stock_part', dict(id=row['id'], stock_id=stock_id), row, fields)
        return collection.receipt(db, [('stock_part', old, collection.snapshot(db, 'stock_part', ids))], 'save')


def _undo_save(db, event, via, actor):
    """Undo one answer: refused when what it touched changed since; restores the old state and the old session."""
    copy_id, figure = _figure_of(event['entity_id'])
    previous, following = json.loads(event['old_value']), json.loads(event['new_value'])
    following.pop('operation', None)
    if snapshot(db, copy_id, _tokens(following), figure) != following:
        raise ValueError('This answer changed elsewhere. Reload before undoing.')
    _restore(db, copy_id, previous, figure)
    request = _REQUEST.get()
    note = dict(undoes=event['id'], **({'operation': request[0], 'tokens': request[1]} if request else {}))
    audit(db, 'part_check:' + event['entity_id'], 'undo', None, note, via=via, actor=actor)
    undo_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.execute('INSERT INTO main.event_undo(event_id, undo_event_id) VALUES(?, ?)', (event['id'], undo_id))
    return {'event_id': undo_id}


undoing.register('part_check', 'save', _undo_save)
