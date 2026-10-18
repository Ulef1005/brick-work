"""Copy checker on v3. Session metadata uses settings; events are reversible receipts.

4.8a: the set sequence is required non-figure parts, then whole figures, then an
optional spare pass the user opts into at the end. A figure's own parts are checked
in a separate figure session inside the copy (``figure=(type, number)``).
"""
from collections import defaultdict
import json
import re
import uuid
from pathlib import Path

from .admin import settings
from . import errors
from .transaction import transaction
from .completeness import derived_state
from .sources.base import now


def key(copy_id, figure=None):
    """Session key; a figure check inside a copy has its own session."""
    return 'checker:' + copy_id + (':fig:' + figure[0] + ':' + figure[1] if figure else '')


def session(db, copy_id, figure=None):
    row = db.execute('SELECT value FROM settings WHERE key=?', (key(copy_id, figure),)).fetchone()
    value = json.loads(row[0]) if row else None
    if value:
        value.pop('set_checked', None)
    return value


def normalise(s, kinds):
    """Read model of a stored session against the current sequence.

    Tokens that are no longer part of the sequence (figure component rows saved
    by an older session, or spare rows before the spare question was answered
    "Yes") are dropped from the visible order without error, and the cursor keeps
    pointing at the same remaining step. Nothing stored is rewritten here; the
    next save persists the pruned form and its receipt keeps the raw old value.
    """
    if not s:
        return s
    s.setdefault('spares', None)
    keep_spares = s['spares'] == 'yes'

    def visible(token):
        return token in kinds and (kinds[token] != 'spare' or keep_spares)
    dropped = sum(not visible(t) for t in s['order'][:s['cursor']])
    s['order'] = [t for t in s['order'] if visible(t)]
    s['cursor'] = max(0, min(len(s['order']), s['cursor'] - dropped))
    s['answers'] = {t: a for t, a in s['answers'].items() if visible(t)}
    s['misses'] = [t for t in s['misses'] if visible(t)]
    return s


def sorter(mode, position):
    if mode == 'largest':
        # Physically largest first (core/part_size.py); among equal pieces the larger count first, then
        # one colour after another, so a part's colours stay together.
        from .part_size import volume
        return lambda r: (-volume(r.get('name') or '', r.get('category') or ''), -(r['quantity'] or 0),
                          (r.get('color_name') or '').casefold(), r['item_no'], position[r['token']])
    if mode == 'colour':
        return lambda r: (r.get('color_name') or 'Unknown colour', r['item_no'])
    return lambda r: position[r['token']]


def copy(db, copy_id):
    row = db.execute('SELECT * FROM copies WHERE id=? AND archived_at IS NULL', (copy_id,)).fetchone()
    if not row:
        raise ValueError('This copy is no longer available')
    return dict(row)


def checked_flag(db, create=False):
    """4.2 preserves metadata names and ids; resolve the status by its name."""
    row = db.execute("SELECT id FROM flags WHERE archived_at IS NULL AND kind='status' AND name='Set is checked' ORDER BY id LIMIT 1").fetchone()
    if row:
        return row[0]
    if not create:
        return None
    flag = dict(id=uuid.uuid4().hex, name='Set is checked', kind='status', shown_on_grid=1)
    db.execute('INSERT INTO flags(id,name,kind,shown_on_grid) VALUES(:id,:name,:kind,:shown_on_grid)', flag)
    # Through audit() like other non-receipt audits: the web writes an event row; an API write's bundle keeps only receipts.
    from .admin import audit
    audit(db, 'flags:' + flag['id'], 'record', None, flag)
    return flag['id']


def checked(db, copy_id):
    return bool(db.execute("""SELECT 1 FROM item_flags f JOIN flags s ON s.id=f.flag_id AND s.archived_at IS NULL
        WHERE f.entity_type='copy' AND f.entity_id=? AND s.kind='status' AND s.name='Set is checked'""", (copy_id,)).fetchone())


def picture(db, root, kind, number, color=None, *, priorities=None, candidates=None):
    priorities = priorities if priorities is not None else settings(db)['priority']['pictures']
    sources = priorities.get(kind, priorities.get('*', []))
    rows = list(candidates) if candidates is not None else list(db.execute('''SELECT im.* FROM item_images im JOIN sources s ON s.source=im.source
        WHERE im.item_type=? AND im.item_no=? AND im.color_id IS ? AND s.enabled=1
        ORDER BY im.fetched_at DESC,im.id DESC''', (kind, number, color)))
    rows = [r for r in rows if r['source'] in sources]
    rows.sort(key=lambda r: sources.index(r['source']))
    for row in rows:
        target = (Path(root) / row['local_path']).resolve()
        if target.is_relative_to((Path(root) / 'data/images').resolve()) and target.is_file():
            return row['id']
    return None


def rows(db, copy_id, root, images=True, tokens=None, decorate=True, figure=None):
    """The set sequence: required non-figure parts, whole figures and spare lines.

    Figure component rows are not part of the set. With ``figure=(type, number)``
    the rows are exactly that figure's required (non-spare) component rows.
    """
    result = []
    parts_sql = '''SELECT p.*,i.name,i.category,c.name color_name,c.rgb FROM copy_parts p
            JOIN items i USING(item_type,item_no) LEFT JOIN colors c USING(color_id) WHERE copy_id=? AND '''
    components = {}
    if figure:
        sources = [('part', parts_sql + 'p.parent_minifig_type=? AND p.parent_minifig=? AND coalesce(p.spare,0)=0 ORDER BY p.id', (copy_id, *figure))]
    else:
        sources = [('part', parts_sql + '(p.parent_minifig IS NULL OR coalesce(p.spare,0)=1) ORDER BY p.id', (copy_id,)),
                   ('figure', '''SELECT f.*,f.minifig_no item_no,i.name,i.category FROM copy_minifigs f
            JOIN items i ON i.item_type=f.item_type AND i.item_no=f.minifig_no WHERE copy_id=? ORDER BY f.item_type,f.minifig_no''', (copy_id,))]
        components = {(r[0], r[1]): (r[2], r[3] or 0) for r in db.execute(
            '''SELECT parent_minifig_type,parent_minifig,count(*),sum(coalesce(missing,0)) FROM copy_parts
            WHERE copy_id=? AND parent_minifig IS NOT NULL AND coalesce(spare,0)=0 GROUP BY 1,2''', (copy_id,))}
    for table, sql, params in sources:
        for raw in db.execute(sql, params):
            r = dict(raw)
            r['token'] = 'p:' + str(r['id']) if table == 'part' else 'm:' + json.dumps([r['item_type'], r['item_no']], separators=(',', ':'))
            if tokens is not None and r['token'] not in tokens:
                continue
            r['kind'] = 'spare' if r.get('spare') else table
            if table == 'figure':
                r['parts_lines'], r['parts_missing'] = components.get((r['item_type'], r['item_no']), (0, 0))
            if not decorate:
                result.append(r)
                continue
            r['name'] = (r['name'] or r['item_no']).replace('LEGO', '').strip()
            r['color_name'] = r.get('color_name') or 'Unknown colour'
            rgb = r.get('rgb') or ''
            r['rgb'] = '#' + rgb.lstrip('#') if re.fullmatch(r'#?[0-9a-fA-F]{6}', rgb) else None
            if r['rgb']:
                channels = [int(r['rgb'][i:i+2], 16)/255 for i in (1, 3, 5)]
                channels = [c/12.92 if c <= .04045 else ((c+.055)/1.055)**2.4 for c in channels]
                r['ink'] = '#1A1816' if sum(c*w for c,w in zip(channels, (.2126,.7152,.0722))) > .45 else '#FAFAF8'
            result.append(r)
    if decorate and result:
        # One query each for the id matches and the pictures of every row, never one per row.
        scope = " (item_type,item_no) IN (SELECT json_extract(value,'$[0]'),json_extract(value,'$[1]') FROM json_each(?))"
        identities = json.dumps(sorted({(r['item_type'], r['item_no']) for r in result}))
        pending = {(m[0], m[1]) for m in db.execute("SELECT item_type,item_no FROM id_match WHERE status='to_check' AND" + scope, (identities,))}
        for r in result:
            r['unresolved'] = r['item_type'] == '?' or (r['item_type'], r['item_no']) in pending
        if images:
            candidates = defaultdict(list)
            for im in db.execute("""SELECT im.* FROM item_images im JOIN sources s ON s.source=im.source
                    WHERE s.enabled=1 AND (im.item_type,im.item_no) IN
                    (SELECT json_extract(value,'$[0]'),json_extract(value,'$[1]') FROM json_each(?))
                    ORDER BY im.fetched_at DESC,im.id DESC""", (identities,)):
                candidates[im['item_type'], im['item_no'], im['color_id']].append(im)
            priorities = settings(db)['priority']['pictures']
            for r in result:
                r['image'] = picture(db, root, r['item_type'], r['item_no'], r.get('color_id'), priorities=priorities,
                                     candidates=candidates[r['item_type'], r['item_no'], r.get('color_id')])
    return result


def header(db, copy_id, root):
    c = copy(db, copy_id)
    siblings = [r[0] for r in db.execute('SELECT id FROM copies WHERE item_type=? AND set_no=? AND archived_at IS NULL ORDER BY id', (c['item_type'], c['set_no']))]
    c['label'] = 'Set ' + str(siblings.index(copy_id)+1)
    c['name'] = (db.execute('SELECT name FROM items WHERE item_type=? AND item_no=?', (c['item_type'], c['set_no'])).fetchone()[0] or c['set_no']).replace('LEGO', '').strip()
    c['set_checked'] = checked(db, copy_id)
    c['image'] = picture(db, root, c['item_type'], c['set_no'])
    return c


def view(db, copy_id, root):
    c = header(db, copy_id, root)
    inventory = rows(db, copy_id, root)
    s = normalise(session(db, copy_id), {r['token']: r['kind'] for r in inventory})
    saved = db.execute("SELECT at FROM events WHERE entity=? AND via IN ('app','api','cli') ORDER BY id DESC LIMIT 1", (key(copy_id),)).fetchone() if s else None
    return dict(copy=c, rows=inventory, session=s, saved_at=saved[0] if saved else None)


def figure_view(db, copy_id, root, minifig_type, minifig_no):
    """Check figure parts: one whole figure's component rows inside this copy."""
    c = header(db, copy_id, root)
    whole = db.execute('''SELECT f.*,i.name FROM copy_minifigs f JOIN items i ON i.item_type=f.item_type AND i.item_no=f.minifig_no
        WHERE f.copy_id=? AND f.item_type=? AND f.minifig_no=?''', (copy_id, minifig_type, minifig_no)).fetchone()
    if not whole:
        raise ValueError('This figure is not in this copy')
    figure = (minifig_type, minifig_no)
    inventory = rows(db, copy_id, root, figure=figure)
    figure_info = dict(item_type=minifig_type, item_no=minifig_no, quantity=whole['quantity'], missing=whole['missing'],
                       name=(whole['name'] or minifig_no).replace('LEGO', '').strip(),
                       image=picture(db, root, minifig_type, minifig_no))
    s = normalise(session(db, copy_id, figure), {r['token']: r['kind'] for r in inventory})
    return dict(copy=c, figure=figure_info, rows=inventory, session=s)


def choices(db, root):
    # The chooser needs counts, not every inventory row and its image lookup.
    result, ordinals, images = [], {}, {}
    checked_copies = {r[0] for r in db.execute("""SELECT f.entity_id FROM item_flags f JOIN flags s ON s.id=f.flag_id AND s.archived_at IS NULL
        WHERE f.entity_type='copy' AND s.kind='status' AND s.name='Set is checked'""")}
    sessions = {r['key']: json.loads(r['value']) for r in db.execute("SELECT key,value FROM settings WHERE key LIKE 'checker:%'")}
    required_tokens = {}
    for r in db.execute('SELECT copy_id,id FROM copy_parts WHERE coalesce(spare,0)=0 AND parent_minifig IS NULL'):
        required_tokens.setdefault(r['copy_id'], set()).add('p:'+str(r['id']))
    for r in db.execute('SELECT copy_id,item_type,minifig_no FROM copy_minifigs'):
        token = 'm:' + json.dumps([r['item_type'], r['minifig_no']], separators=(',', ':'))
        required_tokens.setdefault(r['copy_id'], set()).add(token)
    priorities = settings(db)['priority']['pictures']
    candidates = list(db.execute("""SELECT im.* FROM item_images im JOIN sources s ON s.source=im.source
        WHERE s.enabled=1 AND im.color_id IS NULL ORDER BY im.fetched_at DESC,im.id DESC"""))
    by_identity = {}
    for image in candidates:
        by_identity.setdefault((image['item_type'], image['item_no']), []).append(image)
    for row in db.execute("""SELECT c.*, i.name,
            coalesce(p.entries,0) +
            (SELECT count(*) FROM copy_minifigs f WHERE f.copy_id=c.id) entries,
            coalesce(p.parts,0) parts
            FROM copies c JOIN items i ON i.item_type=c.item_type AND i.item_no=c.set_no
            LEFT JOIN (SELECT copy_id,
                sum(CASE WHEN parent_minifig IS NULL OR coalesce(spare,0)=1 THEN 1 ELSE 0 END) entries,
                sum(CASE WHEN coalesce(spare,0)=0 AND parent_minifig IS NULL THEN 1 ELSE 0 END) parts
                FROM copy_parts GROUP BY copy_id) p ON p.copy_id=c.id
            WHERE c.archived_at IS NULL ORDER BY c.set_no,c.id"""):
        c = dict(row)
        identity = c['item_type'], c['set_no']
        ordinals[identity] = ordinals.get(identity, 0) + 1
        c['label'] = 'Set ' + str(ordinals[identity])
        c['name'] = (c['name'] or c['set_no']).replace('LEGO', '').strip()
        if identity not in images:
            images[identity] = picture(db, root, *identity, priorities=priorities, candidates=by_identity.get(identity, []))
        c['set_checked'] = c['id'] in checked_copies
        c['image'] = images[identity]
        stored = sessions.get(key(c['id']))
        if stored:
            stored.pop('set_checked', None)
        # Only saved answered tokens are completed; skipped tokens remain to check.
        required = required_tokens.get(c['id'], set())
        completed = sum((stored or {}).get('answers', {}).get(t) == 'answered' for t in required)
        result.append(dict(copy=c, entries=c['entries'], parts=c['parts'], session=stored, completed=completed, total=len(required)))
    return sorted(result, key=lambda r: (0 if r['session'] and not r['session']['finished'] else 2 if r['copy']['set_checked'] else 1, -r['entries'], r['copy']['id']))


def snapshot(db, copy_id, tokens=(), figure=None):
    c = copy(db, copy_id)
    parts, figures = [], []
    for token in tokens:
        if token.startswith('p:'):
            row = db.execute('SELECT id,checked,missing FROM copy_parts WHERE copy_id=? AND id=?', (copy_id, int(token[2:]))).fetchone()
            if row:
                parts.append(dict(row))
        elif token.startswith('m:'):
            row = db.execute('SELECT item_type,minifig_no,missing,updated_at FROM copy_minifigs WHERE copy_id=? AND item_type=? AND minifig_no=?', (copy_id, *json.loads(token[2:]))).fetchone()
            if row:
                figures.append(dict(row))
    result = dict(session=session(db, copy_id, figure), parts=parts, figures=figures)
    if not figure:
        # A figure check never touches the set's checked flag or completeness.
        flag = checked_flag(db)
        association = db.execute("SELECT * FROM item_flags WHERE entity_type='copy' AND entity_id=? AND flag_id=?", (copy_id, flag)).fetchone()
        result.update(checked_flag=dict(association) if association else None,
                      copy={k:c[k] for k in ('completeness', 'completeness_source', 'updated_at')})
    return result


def restore(db, copy_id, value, figure=None):
    if 'checked_flag' in value:
        flag = checked_flag(db)
        db.execute("DELETE FROM item_flags WHERE entity_type='copy' AND entity_id=? AND flag_id=?", (copy_id, flag))
        if value['checked_flag']:
            db.execute('INSERT INTO item_flags(entity_type,entity_id,flag_id) VALUES(:entity_type,:entity_id,:flag_id)', value['checked_flag'])
    for r in value['parts']:
        db.execute('UPDATE copy_parts SET checked=?,missing=? WHERE copy_id=? AND id=?', (r['checked'], r['missing'], copy_id, r['id']))
    for r in value['figures']:
        db.execute('UPDATE copy_minifigs SET missing=?,updated_at=? WHERE copy_id=? AND item_type=? AND minifig_no=?', (r['missing'], r['updated_at'], copy_id, r['item_type'], r['minifig_no']))
    if 'copy' in value:
        c = value['copy']
        db.execute('UPDATE copies SET completeness=?,completeness_source=?,updated_at=? WHERE id=?', (c['completeness'], c['completeness_source'], c['updated_at'], copy_id))
    if value['session'] is None:
        db.execute('DELETE FROM settings WHERE key=?', (key(copy_id, figure),))
    else:
        db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key(copy_id, figure), json.dumps(value['session'])))


def recompute(db, copy_id, s=None):
    copy(db, copy_id)
    state = derived_state(db, copy_id)
    if state is None:
        return
    db.execute('UPDATE copies SET completeness=?,updated_at=? WHERE id=?', (state, now().isoformat(), copy_id))


def saved_view(db, copy_id, root, tokens=(), figure=None):
    """Save deltas retain GET's images in the client and do no picture work."""
    inventory = rows(db, copy_id, root, images=False, decorate=False, figure=figure)
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
    return dict(partial=True, copy=c, rows=rows(db, copy_id, root, images=False, tokens=set(tokens), figure=figure), progress=counts, session=s)


def figure_row(db, copy_id, figure):
    if not figure or not db.execute('SELECT 1 FROM copy_minifigs WHERE copy_id=? AND item_type=? AND minifig_no=?', (copy_id, *figure)).fetchone():
        raise ValueError('This figure is not in this copy')


def write(db, copy_id, payload, root, figure=None):
    """One ordered, idempotent mutation and a full old/new receipt per request."""
    if payload.get('action') in ('mark', 'bulk', 'mark_figure', 'checked', 'loose_parts'):
        return mark(db, copy_id, payload)
    if payload.get('action') == 'undo_event':
        return undo_event(db, payload['event_id'], payload.get('receipt'))
    operation = payload.get('operation')
    if not isinstance(operation, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,80}', operation):
        raise ValueError('A save receipt is required')
    entity, field = key(copy_id, figure), 'checker:' + operation
    with transaction(db):
        copy(db, copy_id)
        if figure:
            figure_row(db, copy_id, figure)
        receipt = db.execute("SELECT new_value FROM events WHERE entity=? AND field=? AND via IN ('app','api','cli')", (entity, field)).fetchone()
        if receipt:
            value = json.loads(receipt[0])
            tokens = ['p:'+str(r['id']) for r in value['parts']] + ['m:'+json.dumps([r['item_type'], r['minifig_no']], separators=(',', ':')) for r in value['figures']]
            return saved_view(db, copy_id, root, tokens, figure)
        if not figure:
            checked_flag(db, create=True)
        action = payload.get('action')
        all_rows = rows(db, copy_id, root, images=False, decorate=False, figure=figure)
        by_token = {r['token']:r for r in all_rows}
        position = {r['token']:i for i, r in enumerate(all_rows)}
        s = normalise(session(db, copy_id, figure), {t: r['kind'] for t, r in by_token.items()})
        token = payload.get('token')
        tokens = [token] if token in by_token else []

        def settle():
            # A figure check never changes the set's derived completeness.
            if not figure:
                recompute(db, copy_id, s)
        if action == 'undo':
            if s and payload.get('session') != s['id']:
                raise ValueError('This check changed. Reload to continue.')
            if not s or not s['undo']:
                raise ValueError('Nothing to undo')
            event = db.execute('SELECT * FROM events WHERE id=? AND entity=?', (s['undo'][-1], entity)).fetchone()
            previous, following = json.loads(event['old_value']), json.loads(event['new_value'])
            tokens, old = restore_answer(db, copy_id, previous, following, figure)
        else:
            old = snapshot(db, copy_id, tokens, figure)
            if action in ('start', 'restart'):
                if action == 'restart' and (not s or payload.get('session') != s['id']):
                    raise ValueError('This check changed. Reload to continue.')
                if action == 'start' and s and not s.get('finished'):
                    return saved_view(db, copy_id, root, figure=figure)
                order_mode = payload.get('order', 'inventory')
                if order_mode not in ('inventory','largest','colour'):
                    raise ValueError('Choose an order')
                sort = sorter(order_mode, position)
                ordered = sorted((r for r in all_rows if r['kind'] != 'spare'), key=lambda r: ({'part':0,'figure':1}[r['kind']], sort(r)))
                if figure and not ordered:
                    raise ValueError('This figure has no recorded parts')
                s = dict(id=uuid.uuid4().hex, order=[r['token'] for r in ordered], cursor=0, answers={}, misses=[], undo=[], finished=False, sort=order_mode, spares=None)
            else:
                if not s or payload.get('session') != s['id']:
                    raise ValueError('This check changed. Reload to continue.')
                if action in ('answer','found_one','skip','select'):
                    if not tokens or token not in s['order']:
                        raise ValueError('Choose a part from this copy')
                    r = by_token[token]
                    if action == 'select':
                        s['cursor'] = s['order'].index(token)
                    elif action == 'skip':
                        s['answers'][token] = 'skipped'
                        s['cursor'] = min(s['order'].index(token)+1, len(s['order']))
                        settle()
                    else:
                        quantity = r['quantity']
                        if quantity is None or quantity < 0:
                            raise ValueError('The required count is not available. Resolve the inventory first.')
                        found = quantity - (r['missing'] or 0) + 1 if action == 'found_one' else payload.get('found')
                        if isinstance(found, bool) or not isinstance(found, int) or not 0 <= found <= quantity:
                            raise ValueError('Choose a count within the required quantity')
                        missing = quantity - found
                        if token.startswith('p:'):
                            mark_row(db, 'copy_parts', {'id':r['id'], 'copy_id':copy_id}, r, dict(checked=True,missing=missing))
                        else:
                            mark_row(db, 'copy_minifigs', dict(copy_id=copy_id,item_type=r['item_type'],minifig_no=r['item_no']), r, dict(missing=missing))
                        s['answers'][token] = 'answered'
                        if missing:
                            s['misses'] = [token] + [t for t in s['misses'] if t != token]
                        if action == 'answer':
                            s['cursor'] = min(s['order'].index(token)+1,len(s['order']))
                        settle()
                elif action in ('back','next'):
                    s['cursor'] = max(0,min(len(s['order']),s['cursor']+(-1 if action == 'back' else 1)))
                elif action == 'spares':
                    # The last step of the set check: spare parts are opt in, default no.
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
                        checked = payload.get('checked')
                        if not isinstance(checked, bool):
                            raise ValueError('Choose whether the set is checked')
                        if checked and any(s['answers'].get(r['token']) != 'answered' for r in required):
                            raise ValueError('Answer the skipped and unchecked parts and figures first')
                        flag = checked_flag(db)
                        if checked:
                            db.execute("INSERT OR IGNORE INTO item_flags VALUES('copy',?,?)", (copy_id, flag))
                        else:
                            db.execute("DELETE FROM item_flags WHERE entity_type='copy' AND entity_id=? AND flag_id=?", (copy_id, flag))
                    s['finished'] = True
                    settle()
                else:
                    raise ValueError('Unknown checker action')
            event_id = db.execute('SELECT coalesce(max(id),0)+1 FROM events').fetchone()[0]
            s['undo'].append(event_id)
            db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (entity,json.dumps(s)))
        new = snapshot(db, copy_id, tokens, figure)
        from .admin import origin
        via, actor = origin()
        db.execute('INSERT INTO events(entity,field,old_value,new_value,at,via,actor) VALUES(?,?,?,?,?,?,?)',
                   (entity,field,json.dumps(old),json.dumps(new),now().isoformat(),via,actor))
    return saved_view(db, copy_id, root, tokens, figure)


def mark_row(db, table, key, row, fields):
    """Shared checker bounds and update for session answers and direct marking."""
    if not fields:
        raise errors.ValidationFailed('Choose a count to change')
    for field, value in fields.items():
        if field == 'checked':
            if type(value) is not bool:
                raise errors.ValidationFailed('Choose whether the part is checked')
        elif type(value) is not int or row['quantity'] is None or not 0 <= value <= row['quantity']:
            raise errors.ValidationFailed('Choose a count within the required quantity')
    values = dict(fields)
    if table == 'copy_minifigs':
        values['updated_at'] = now().isoformat()
    db.execute('UPDATE '+table+' SET '+','.join(k+'=?' for k in values)+' WHERE '+
               ' AND '.join(k+' IS ?' for k in key), (*values.values(), *key.values()))


def mark(db, identifier, payload):
    """Stateless checker actions, composed with the existing guarded Undo owner.

    Figure components and spares never contribute to set completeness. Direct
    marking leaves the browser's session progress alone.
    """
    from . import workbench as wb
    action = payload['action']
    changes, skipped, applied = [], [], 0
    with transaction(db):
        table = 'loose_stock' if action == 'loose_parts' else 'copies'
        owner = db.execute('SELECT * FROM '+table+' WHERE id=?', (identifier,)).fetchone()
        if not owner:
            raise errors.NotFound()
        if owner['archived_at']:
            raise errors.Archived()
        def update(table, key, fields):
            nonlocal applied
            existing = wb.snapshot(db, table, key)
            if len(existing) != 1:
                raise errors.NotFound('Inventory line is unavailable or ambiguous')
            wb.record(db, changes, table, key, lambda: mark_row(db,table,key,existing[0],fields))
            applied += 1
            return dict(existing[0], **fields)
        if action == 'checked':
            flag = checked_flag(db)
            if not flag and not payload['checked']:
                # Clearing a mark that was never set is a no-op: no flag row, no change.
                wb.finish(db,changes,'checker_'+action,{})
                return None
            if not flag:
                # The system flag is shared by every copy: create it outside the receipt so
                # Undo of one mark removes only that copy's association, never the flag.
                flag = checked_flag(db, create=True)
            key = dict(entity_type='copy',entity_id=identifier,flag_id=flag)
            wb.record(db,changes,'item_flags',key,lambda:db.execute(
                "INSERT OR IGNORE INTO item_flags VALUES(?,?,?)" if payload['checked'] else
                "DELETE FROM item_flags WHERE entity_type=? AND entity_id=? AND flag_id=?", tuple(key.values())))
            result = None
        elif action == 'mark':
            result = update('copy_parts',dict(copy_id=identifier,id=payload['part_id']),payload['fields'])
        elif action == 'mark_figure':
            result = update('copy_minifigs',dict(copy_id=identifier,item_type=payload['type'],minifig_no=payload['no']),{'missing':payload['missing']})
        elif action == 'loose_parts':
            if owner['item_type'] != 'M':
                raise errors.ValidationFailed('Choose a loose figure')
            result, seen = [], set()
            for part in payload['parts']:
                key = dict(stock_id=identifier,item_type=part.get('item_type','P'),item_no=part['item_no'],color_id=part.get('color_id'),spare=part.get('spare',0))
                identity = tuple(key.values())
                if identity in seen: raise errors.ValidationFailed('Duplicate part line')
                seen.add(identity)
                result.append(update('loose_minifig_parts',key,{k:v for k,v in part.items() if k in ('missing','damaged','checked')}))
        else:
            seen = set()
            for i, part in enumerate(payload['items']):
                identity = part['item_no'], part['color_id']
                if identity in seen: raise errors.ValidationFailed('Duplicate part line')
                seen.add(identity)
                matches = list(db.execute("SELECT * FROM copy_parts WHERE copy_id=? AND item_type='P' AND item_no=? AND color_id=? AND parent_minifig IS NULL AND coalesce(spare,0)=0", (identifier,*identity)))
                if len(matches) != 1:
                    skipped.append(dict(field=f'items.{i}',code='not_found' if not matches else 'conflict',message='Inventory line is unavailable or ambiguous'))
                    continue
                row = matches[0]
                missing = part['missing'] + ((row['missing'] or 0) if payload.get('mode','set') == 'add' else 0)
                update('copy_parts',dict(id=row['id']),dict(missing=missing))
            result = dict(applied=applied,skipped=skipped,dry_run=payload.get('dry_run',False))
        if action != 'loose_parts':
            wb.recompute(db, changes, identifier)
        wb.finish(db,changes,'checker_'+action,{})
        return result


def undo_event(db, event_id, receipt=None):
    """Guard and restore the exact checker receipt, including its session."""
    from .admin import audit
    with transaction(db):
        row = receipt if receipt is not None else db.execute('SELECT * FROM events WHERE id=?', (event_id,)).fetchone()
        if not row or not row['entity'].startswith('checker:') or not row['field'].startswith('checker:'):
            raise ValueError('Choose a checker receipt')
        identity = row['entity'][len('checker:'):].split(':fig:')
        copy_id = identity[0]
        figure = tuple(identity[1].split(':', 1)) if len(identity) == 2 else None
        previous, following = json.loads(row['old_value']), json.loads(row['new_value'])
        # An Undo action's receipt restores an earlier session and is not itself undoable.
        if not following.get('session') or event_id not in following['session']['undo']:
            raise ValueError('Choose a checker receipt')
        restore_answer(db, copy_id, previous, following, figure)
        audit(db, row['entity'], 'undo', following, int(event_id))


def restore_answer(db, copy_id, previous, following, figure=None):
    """The same snapshot guard and restoration for web and API checker Undo."""
    tokens = ['p:'+str(r['id']) for r in following['parts']] + ['m:'+json.dumps([r['item_type'],r['minifig_no']], separators=(',', ':')) for r in following['figures']]
    current = snapshot(db, copy_id, tokens, figure)
    if current != following:
        raise ValueError('This answer changed elsewhere. Reload before undoing.')
    restore(db, copy_id, previous, figure)
    return tokens, current
