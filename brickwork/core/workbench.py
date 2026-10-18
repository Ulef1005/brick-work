"""Exact gap matching and picker receipts on the v3 collection only."""
from .transaction import transaction
from .errors import StaleMatch
import json
import re
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from uuid import uuid4

from .add import catalogue_path, decorate, decorate_many, lookup, quantity
from .admin import audit
from .completeness import derived_state
from .sources.base import now


def stamp():
    return now().isoformat()


def flag(db, name):
    rows = db.execute("SELECT id FROM flags WHERE archived_at IS NULL AND kind='status' AND lower(name)=lower(?)", (name,)).fetchall()
    if len(rows) != 1:
        return None
    return rows[0][0]


def asserted(db, copy, name):
    identifier = flag(db, name)
    return bool(identifier and db.execute("SELECT 1 FROM item_flags WHERE entity_type='copy' AND entity_id=? AND flag_id=?", (copy, identifier)).fetchone())


def unresolved(db, kind, number, keys=None):
    if keys is not None:
        return kind=='?' or (kind,number) in keys
    return kind == '?' or bool(db.execute("SELECT 1 FROM id_match WHERE item_type=? AND item_no=? AND status='to_check'", (kind, number)).fetchone())


def available(db, row, *, unresolved_keys=None, defective_figures=None):
    if row['condition'] == 'D' or unresolved(db, row['item_type'], row['item_no'], unresolved_keys):
        return 0
    if row['item_type'] == 'M':
        defective = row['id'] in defective_figures if defective_figures is not None else db.execute('SELECT 1 FROM loose_minifig_parts WHERE stock_id=? AND (coalesce(missing,0)>0 OR coalesce(damaged,0)>0)', (row['id'],)).fetchone()
        if defective:
            return 0
    return max(0, (row['quantity'] or 0) - (row['missing'] or 0) - (row['damaged'] or 0))


def part_gap(row, whole_missing=0):
    """Required replacements, with whole missing figures covering constituents."""
    return max(0, (row['missing'] or 0) + (row['damaged'] or 0)
               - whole_missing * (row['quantity'] or 0))


def relevant(db, kind, number, colour, *, copy_ids=(), stock_ids=()):
    """Copies and loose figures whose gaps can reach the matches of one item.

    A superset is fine: `gaps(only=...)` returns every gap of these, in global order, and
    the caller filters. A copy is relevant when it holds a gap on the item's identity or is
    named; its other gaps matter because `completes` counts all of a copy's gaps.
    """
    copies, stock = set(copy_ids), set(stock_ids)
    copies.update(r[0] for r in db.execute(
        'SELECT DISTINCT copy_id FROM copy_parts WHERE item_type=? AND item_no=? AND color_id IS ? AND coalesce(spare,0)=0 '
        'AND parent_minifig IS NULL AND (coalesce(missing,0)>0 OR coalesce(damaged,0)>0)', (kind, number, colour)))
    copies.update(r[0] for r in db.execute(
        'SELECT DISTINCT copy_id FROM copy_minifigs WHERE item_type=? AND minifig_no=? AND missing>0', (kind, number)))
    stock.update(r[0] for r in db.execute(
        'SELECT DISTINCT stock_id FROM loose_minifig_parts WHERE item_type=? AND item_no=? AND color_id IS ? AND coalesce(spare,0)=0 AND missing>0',
        (kind, number, colour)))
    if kind in ('I', 'O'):  # booklet and box gaps carry the set number
        copies.update(r[0] for r in db.execute('SELECT id FROM copies WHERE set_no=?', (number,)))
    return copies, stock


def gaps(db, only=None):
    """Every gap; `only=(copy_ids, stock_ids)` keeps just those copies' and loose figures' gaps, in the same
    order within each copy or loose figure (stock-part rows of different figures may interleave differently)."""
    result = []
    keep_copies, keep_stock = (set(only[0]), set(only[1])) if only is not None else (None, None)
    scope_sql = lambda column: f' AND {column} IN (SELECT value FROM json_each(?))' if only is not None else ''
    copies = {r['id']: dict(r) for r in db.execute("SELECT c.*,i.name AS set_name FROM copies c JOIN items i ON i.item_type=c.item_type AND i.item_no=c.set_no WHERE c.archived_at IS NULL ORDER BY c.set_no,c.id")}
    unresolved_keys = {(r[0], r[1]) for r in db.execute("SELECT item_type,item_no FROM id_match WHERE status='to_check'")}
    def pending(kind, number):
        return kind == '?' or (kind, number) in unresolved_keys
    status_flags = {r['name'].lower(): r['id'] for r in db.execute("SELECT id,name FROM flags WHERE archived_at IS NULL AND kind='status'")}
    assertions = {(r[0],r[1]) for r in db.execute("SELECT entity_id,flag_id FROM item_flags WHERE entity_type='copy'")}
    labels = {}
    for c in copies.values():
        labels[c['set_no']] = labels.get(c['set_no'], 0) + 1
        c['label'] = 'Set ' + str(labels[c['set_no']])
        c['unresolved'] = pending(c['item_type'],c['set_no'])
    if keep_copies is not None:
        copies = {k: v for k, v in copies.items() if k in keep_copies}
    for row in db.execute('SELECT p.*,i.name,i.category,co.name AS color_name,co.rgb FROM copy_parts p JOIN items i ON i.item_type=p.item_type AND i.item_no=p.item_no LEFT JOIN colors co ON co.color_id=p.color_id WHERE coalesce(p.spare,0)=0 AND p.parent_minifig IS NULL AND (coalesce(p.missing,0)>0 OR coalesce(p.damaged,0)>0)' + scope_sql('p.copy_id') + (' ORDER BY p.id' if only is not None else ''),
                          (json.dumps(sorted(keep_copies)),) if only is not None else ()):
        row = dict(row)
        if row['copy_id'] not in copies:
            continue
        # 4.8a: figure component rows are not set gaps (the query excludes them).
        need = part_gap(row)
        if need:
            result.append(dict(row, target='part', target_id=row['id'], need=need, copy=copies[row['copy_id']]))
    for row in db.execute('SELECT m.*,i.name FROM copy_minifigs m JOIN items i ON i.item_type=m.item_type AND i.item_no=m.minifig_no WHERE m.missing>0' + scope_sql('m.copy_id') + (' ORDER BY m.rowid' if only is not None else ''),
                          (json.dumps(sorted(keep_copies)),) if only is not None else ()):
        if row['copy_id'] in copies:
            result.append(dict(row, item_no=row['minifig_no'], color_id=None, target='figure', target_id=row['minifig_no'], need=row['missing'], copy=copies[row['copy_id']]))
    for c in copies.values():
        if c['item_type'] != 'S':
            continue
        for kind, name, target in [('I', 'Instructions present', 'instructions'), ('O', 'Box present', 'box')]:
            if status_flags.get(name.lower()) and (c['id'],status_flags[name.lower()]) not in assertions:
                result.append(dict(item_type=kind,item_no=c['set_no'],color_id=None,name=name.replace(' present',' missing'),copy_id=c['id'],copy=c,target=target,target_id=c['set_no'],need=1))
    for raw in db.execute("""SELECT p.*,i.name,s.item_no AS figure_no,fi.name AS figure_name
        FROM loose_minifig_parts p JOIN loose_stock s ON s.id=p.stock_id
        JOIN items i ON (i.item_type,i.item_no)=(p.item_type,p.item_no)
        JOIN items fi ON (fi.item_type,fi.item_no)=(s.item_type,s.item_no)
        WHERE s.archived_at IS NULL AND s.quantity>0 AND s.item_type='M'
        AND coalesce(p.spare,0)=0 AND p.missing>0""" + scope_sql('s.id') + (' ORDER BY s.rowid,p.rowid' if only is not None else ''),
        (json.dumps(sorted(keep_stock)),) if only is not None else ()):
        r=dict(raw)
        result.append(dict(r,copy_id=r['stock_id'],target='stock-part',
            target_id=[r['item_type'],r['item_no'],r['color_id'],r['spare']],need=r['missing'],
            copy=dict(id=r['stock_id'],item_type='M',set_no=r['figure_no'],set_name=r['figure_name'],
                label='Loose minifigure',unresolved=pending('M',r['figure_no']))))
    result = decorate_many(db, result)
    for r in result:
        r['unresolved'] = r['unresolved'] or r['copy']['unresolved'] or bool(r.get('parent_minifig') and pending(r['parent_minifig_type'],r['parent_minifig']))
    return result


def identity(row):
    return row['item_type'], row['item_no'], row['color_id']



def merged_inventory(rows):
    """Read projection only: keep every original row behind an exact identity.

    Matcher receipts and checker answers still use the original row identifiers.
    Unrecorded checks stay explicit; aggregates never supply a writable row key.
    """
    groups = {}
    for row in rows:
        key = (*identity(row), bool(row.get('spare')))
        group = groups.setdefault(key, dict(row, contexts=[]))
        group['contexts'].append(row)
    for group in groups.values():
        contexts = group['contexts']
        group['quantity'] = (sum(r.get('quantity') or 0 for r in contexts)
                             if all(r.get('quantity') is not None for r in contexts) else None)
        for field in ('missing', 'damaged'):
            group[field] = (sum(r.get(field) or 0 for r in contexts)
                            if any(r.get(field) is not None for r in contexts) else None)
        group['missing_recorded'] = all(r.get('missing') is not None for r in contexts)
        group['deficit'] = sum(r.get('deficit', 0) for r in contexts)
        group['can_take'] = sum(r.get('can_take', 0) for r in contexts)
        group['checked'] = (int(all(r.get('checked') for r in contexts))
                            if any(r.get('checked') is not None for r in contexts) else None)
        group['unresolved'] = any(r.get('unresolved') for r in contexts)
        group['spare'] = all(r.get('spare') for r in contexts)
        if len(contexts) > 1:
            # An aggregate must never masquerade as the first writable row.
            group['id'] = None
        group['parent_minifig'] = None
    return list(groups.values())

def completion_context(db, all_gaps):
    """Group required gaps once and load copy-level ranking facts once."""
    counts = defaultdict(Counter)
    for gap in all_gaps:
        if gap['target'] in ('part', 'figure'):
            counts[gap['copy_id']][identity(gap)] += 1
    identifier = flag(db, 'Set is checked')
    checked = {r[0] for r in db.execute("SELECT entity_id FROM item_flags WHERE entity_type='copy' AND flag_id=?", (identifier,))}
    return counts, checked


def matches(db, *, all_gaps=None):
    all_gaps = gaps(db) if all_gaps is None else all_gaps
    counts, eligible = completion_context(db, all_gaps)
    totals = {copy_id: sum(keys.values()) for copy_id, keys in counts.items()}
    stock = defaultdict(list)
    unresolved_keys = {(r[0],r[1]) for r in db.execute("SELECT item_type,item_no FROM id_match WHERE status='to_check'")}
    defective_figures = {r[0] for r in db.execute('SELECT DISTINCT stock_id FROM loose_minifig_parts WHERE coalesce(missing,0)>0 OR coalesce(damaged,0)>0')}
    wanted = {identity(g) for g in all_gaps}  # a stock row only matters for an identity that has a gap
    for row in db.execute('SELECT * FROM loose_stock WHERE archived_at IS NULL AND quantity>0').fetchall():
        source = dict(row)
        if identity(source) not in wanted:
            continue
        have = available(db, source, unresolved_keys=unresolved_keys, defective_figures=defective_figures)
        if have:
            stock[identity(source)].append((source, have))
    result = []
    for gap in all_gaps:
        if gap['unresolved'] or (gap['item_type'] == 'P' and gap['color_id'] is None):
            continue
        for source, have in stock.get(identity(gap), ()):
            completes = gap['target'] in ('part', 'figure') and totals[gap['copy_id']] == 1 and gap['copy_id'] in eligible and have >= gap['need']
            result.append(dict(gap, source_id=source['id'], have=have, suggested=min(have,gap['need']), completes=bool(completes), source_note=source['note'], storage=source['storage_id']))
    return sorted(result, key=lambda r: (not r['completes'], -r['suggested'], r['copy']['set_no'], r['copy_id'], r['source_id']))


def group_matches(db, rows, all_gaps):
    """Candidate coverage per copy; stock is capped within each copy, not reserved."""
    grouped = {}
    for row in rows:
        group = grouped.setdefault(row['copy_id'], dict(copy=row['copy'], rows=[], covered=0, missing=0, completes=False, owned_copy=row['target'] != 'stock-part'))
        group['rows'].append(row)
    _, checked_copies = completion_context(db, all_gaps)
    gaps_by_copy = defaultdict(list)
    for gap in all_gaps:
        gaps_by_copy[gap['copy_id']].append(gap)
    for identifier, group in grouped.items():
        remaining = {r['source_id']: r['have'] for r in group['rows']}
        candidates = defaultdict(list)
        for row in group['rows']:
            candidates[(row['target'], str(row['target_id']))].append(row)
        required_missing = required_covered = 0
        for gap in gaps_by_copy[identifier]:
            need, covered = gap['need'], 0
            for row in candidates[(gap['target'], str(gap['target_id']))]:
                amount = min(need - covered, remaining[row['source_id']])
                covered += amount
                remaining[row['source_id']] -= amount
            group['missing'] += need
            group['covered'] += covered
            if gap['target'] in ('part', 'figure'):
                required_missing += need
                required_covered += covered
        c = group['copy']
        group['completes'] = bool(required_missing and required_missing == required_covered
            and identifier in checked_copies and c.get('completeness_source') == 'derived')
        group['kinds'] = list(dict.fromkeys(r['item_type'] for r in group['rows']))
    # A stale candidate snapshot may contain copies whose gaps have disappeared.
    groups = sorted((g for g in grouped.values() if g['missing']), key=lambda g: (not g['completes'], -(g['covered']/g['missing'] if g['missing'] else 1), g['copy']['set_no'], g['copy']['id']))
    pictures = decorate_many(db, [dict(g['copy'], item_no=g['copy']['set_no']) for g in groups])
    for group, picture in zip(groups, pictures):
        group['copy'] = picture
    return groups


def snapshot(db, table, key):
    return [dict(r) for r in db.execute('SELECT * FROM '+table+' WHERE '+ ' AND '.join(k+' IS ?' for k in key), tuple(key.values()))]


def record(db, changes, table, key, operation):
    old = snapshot(db, table, key)
    operation()
    new = snapshot(db, table, key)
    if old != new:
        changes.append(dict(table=table,key=key,old=old,new=new))
        audit(db, 'bw_workbench:' + table, 'change', old, new)


def recompute(db, changes, copy_id):
    row = db.execute('SELECT * FROM copies WHERE id=?', (copy_id,)).fetchone()
    state = derived_state(db, copy_id)
    if state is None:
        return
    if state != row['completeness']:
        record(db, changes, 'copies', {'id':copy_id}, lambda: db.execute('UPDATE copies SET completeness=?,updated_at=? WHERE id=?',(state,stamp(),copy_id)))


def finish(db, changes, action, data):
    merged = {}
    for change in changes:
        key = change['table'], json.dumps(change['key'], sort_keys=True)
        if key in merged:
            merged[key]['new'] = change['new']
        else:
            merged[key] = dict(change)
    receipt = dict(action=action,changes=list(merged.values()),**data)
    audit(db, 'bw_workbench', 'receipt', None, receipt)
    return db.execute('SELECT last_insert_rowid()').fetchone()[0]


def reduce_gap(db, changes, gap, amount, *, update_completeness=True):
    if gap['target'] == 'part':
        record(db,changes,'copy_parts',{'id':gap['target_id']},lambda:db.execute('UPDATE copy_parts SET missing=max(0,coalesce(missing,0)-?),damaged=max(0,coalesce(damaged,0)-max(0,?-coalesce(missing,0))) WHERE id=?',(amount,amount,gap['target_id'])))
    elif gap['target'] == 'stock-part':
        key=dict(stock_id=gap['copy_id'],item_type=gap['item_type'],item_no=gap['item_no'],color_id=gap['color_id'],spare=gap['spare'])
        record(db,changes,'loose_minifig_parts',key,lambda:db.execute(
            'UPDATE loose_minifig_parts SET missing=missing-? WHERE stock_id=? AND item_type=? AND item_no=? AND color_id IS ? AND spare IS ?',
            (amount,*key.values())))
    elif gap['target'] == 'figure':
        key = dict(copy_id=gap['copy_id'],item_type=gap['item_type'],minifig_no=gap['item_no'])
        record(db,changes,'copy_minifigs',key,lambda:db.execute('UPDATE copy_minifigs SET missing=missing-?,updated_at=? WHERE copy_id=? AND item_type=? AND minifig_no=?',(amount,stamp(),gap['copy_id'],gap['item_type'],gap['item_no'])))
        # Parts covered by the whole missing figure cease to be missing too.
        for part in db.execute('SELECT * FROM copy_parts WHERE copy_id=? AND parent_minifig_type=? AND parent_minifig=? AND coalesce(spare,0)=0', (gap['copy_id'],gap['item_type'],gap['item_no'])).fetchall():
            delta = min((part['missing'] or 0) + (part['damaged'] or 0), amount * (part['quantity'] or 0))
            record(db,changes,'copy_parts',{'id':part['id']},lambda p=part,d=delta:db.execute('UPDATE copy_parts SET missing=max(0,coalesce(missing,0)-?),damaged=max(0,coalesce(damaged,0)-max(0,?-coalesce(missing,0))) WHERE id=?',(d,d,p['id'])))
    else:
        name = 'Instructions present' if gap['target'] == 'instructions' else 'Box present'
        key = dict(entity_type='copy',entity_id=gap['copy_id'],flag_id=flag(db,name))
        record(db,changes,'item_flags',key,lambda:db.execute('INSERT INTO item_flags(entity_type,entity_id,flag_id) VALUES(?,?,?)',tuple(key.values())))
    if update_completeness and gap['target'] != 'stock-part':
        recompute(db,changes,gap['copy_id'])


def requested_gap(db, source, copy_id, target, target_id):
    """Read only the requested copy and inventory row under the write lock."""
    if target=='stock-part':
        figure=db.execute("SELECT * FROM loose_stock WHERE id=? AND archived_at IS NULL AND quantity>0 AND item_type='M'",(copy_id,)).fetchone()
        if not figure or unresolved(db,figure['item_type'],figure['item_no']) or not isinstance(target_id,(list,tuple)) or len(target_id)!=4:
            return None
        row=db.execute('SELECT * FROM loose_minifig_parts WHERE stock_id=? AND item_type=? AND item_no=? AND color_id IS ? AND spare IS ? AND coalesce(spare,0)=0 AND missing>0',(copy_id,*target_id)).fetchone()
        if not row: return None
        gap=dict(row,copy_id=copy_id,target=target,target_id=target_id,need=row['missing'])
        if identity(gap)!=identity(source) or unresolved(db,gap['item_type'],gap['item_no']) or (gap['item_type']=='P' and gap['color_id'] is None):
            return None
        return gap
    copy = db.execute('SELECT * FROM copies WHERE id=? AND archived_at IS NULL', (copy_id,)).fetchone()
    if not copy or unresolved(db, copy['item_type'], copy['set_no']):
        return None
    if target == 'part':
        row = db.execute('SELECT * FROM copy_parts WHERE copy_id=? AND id=? AND coalesce(spare,0)=0 AND parent_minifig IS NULL AND (coalesce(missing,0)>0 OR coalesce(damaged,0)>0)', (copy_id, target_id)).fetchone()
        if not row:
            return None
        gap = dict(row)
        target_id = row['id']
        whole = db.execute('SELECT missing FROM copy_minifigs WHERE copy_id=? AND item_type IS ? AND minifig_no IS ?', (copy_id, row['parent_minifig_type'], row['parent_minifig'])).fetchone() if row['parent_minifig'] else None
        gap['need'] = part_gap(row, (whole[0] or 0) if whole else 0)
        if row['parent_minifig'] and unresolved(db, row['parent_minifig_type'], row['parent_minifig']):
            return None
    elif target == 'figure':
        row = db.execute('SELECT *,minifig_no AS item_no FROM copy_minifigs WHERE copy_id=? AND item_type=? AND minifig_no=? AND missing>0', (copy_id, source['item_type'], target_id)).fetchone()
        if not row:
            return None
        gap = dict(row, color_id=None, need=row['missing'])
    elif target in ('instructions', 'box'):
        kind, name = ('I', 'Instructions present') if target == 'instructions' else ('O', 'Box present')
        if copy['item_type'] != 'S' or str(target_id) != copy['set_no'] or not flag(db, name) or asserted(db, copy_id, name):
            return None
        gap = dict(item_type=kind, item_no=copy['set_no'], color_id=None, need=1)
    else:
        return None
    if identity(gap) != identity(source) or not gap['need'] or unresolved(db, gap['item_type'], gap['item_no']) or (gap['item_type'] == 'P' and gap['color_id'] is None):
        return None
    return dict(gap, copy_id=copy_id, target=target, target_id=target_id)


def move_stock(db, changes, source, match, amount):
    """One source row into one gap: the stock arithmetic behind every transfer and take."""
    source_id, target, target_id, copy_id = source['id'], match['target'], match['target_id'], match['copy_id']
    record(db,changes,'loose_stock',{'id':source_id},lambda:db.execute('UPDATE loose_stock SET quantity=quantity-?,updated_at=? WHERE id=?',(amount,stamp(),source_id)))
    reduce_gap(db,changes,match,amount)
    cursor = db.execute('INSERT INTO match_history(at,kind,source_stock_id,copy_id,quantity,item_type,item_no,item_key,source_snapshot) VALUES(?,?,?,?,?,?,?,?,?)',(stamp(),target,source_id,None if target=='stock-part' else copy_id,amount,match['item_type'],match['item_no'],json.dumps([match['item_type'],match['item_no'],match['color_id'],target_id,copy_id] if target=='stock-part' else [match['item_type'],match['item_no'],match['color_id'],target_id]),json.dumps(source)))
    audit(db,'bw_workbench:match_history','created',None,dict(db.execute('SELECT * FROM match_history WHERE id=?',(cursor.lastrowid,)).fetchone()))
    return cursor.lastrowid


def transfer(db, source_id, copy_id, target, target_id, amount):
    amount = quantity(amount)
    with transaction(db):
        row = db.execute('SELECT * FROM loose_stock WHERE id=? AND archived_at IS NULL AND quantity>0', (source_id,)).fetchone()
        source = dict(row) if row else None
        match = requested_gap(db, source, copy_id, target, target_id) if source else None
        if not match or amount > min(available(db, source), match['need']):
            raise StaleMatch('Stock or missing count changed · review matches again')
        changes = []
        history = move_stock(db, changes, source, match, amount)
        return finish(db,changes,'transfer',dict(history_id=history,quantity=amount))


def take_for_gap(db, copy_id, item_type, item_no, color_id, quantity_wanted):
    """Take N of one missing part (or whole minifigure) from loose stock into a set copy, all or nothing.

    Sources follow the Matcher's order per gap (largest usable amount first, then
    stock id); one transaction and one receipt, so one Undo reverses every move.
    """
    amount = quantity(quantity_wanted)
    figure = item_type == 'M'
    if figure:
        color_id = None
    elif item_type != 'P' or color_id is None:
        raise ValueError('Only parts with a colour and whole minifigures can be taken')
    with transaction(db):
        stock = [dict(r) for r in db.execute('SELECT * FROM loose_stock WHERE item_type=? AND item_no=? AND color_id IS ? AND archived_at IS NULL AND quantity>0 ORDER BY id', (item_type, item_no, color_id))]
        if not stock:
            raise ValueError('Nothing is left in loose stock')
        sample = stock[0]
        wanted = []
        if figure:
            gap = requested_gap(db, sample, copy_id, 'figure', item_no)
            if gap:
                wanted.append(gap)
        else:
            for row in db.execute("SELECT id FROM copy_parts WHERE copy_id=? AND item_type=? AND item_no=? AND color_id IS ? AND coalesce(spare,0)=0 AND parent_minifig IS NULL AND (coalesce(missing,0)>0 OR coalesce(damaged,0)>0) ORDER BY id", (copy_id, item_type, item_no, color_id)).fetchall():
                gap = requested_gap(db, sample, copy_id, 'part', row['id'])
                if gap:
                    wanted.append(gap)
        missing = sum(g['need'] for g in wanted)
        if not missing:
            raise ValueError('Nothing is missing of this ' + ('minifigure' if figure else 'part'))
        if amount > missing:
            raise ValueError(f'Only {missing} are missing')
        pending = {(r[0], r[1]) for r in db.execute("SELECT item_type,item_no FROM id_match WHERE status='to_check' AND item_type=? AND item_no=?", (item_type, item_no))}
        defective = {r[0] for r in db.execute('SELECT DISTINCT stock_id FROM loose_minifig_parts WHERE coalesce(missing,0)>0 OR coalesce(damaged,0)>0')} if figure else None
        have = {s['id']: available(db, s, unresolved_keys=pending, defective_figures=defective) for s in stock}
        usable = sum(have.values())
        if amount > usable:
            raise ValueError(f'Only {usable} are left in loose stock' if usable else 'Nothing is left in loose stock')
        by_id = {s['id']: s for s in stock if have[s['id']]}
        changes, histories, left = [], [], amount
        for gap in wanted:
            need = gap['need']
            while left and need and by_id:
                # Matcher order from the in-memory amounts: largest usable first, then lowest id.
                chosen = min(by_id, key=lambda i: (-min(have[i], need), i))
                source = by_id[chosen]
                step = min(left, need, have[chosen])
                histories.append(move_stock(db, changes, source, gap, step))
                source['quantity'] -= step
                have[chosen] -= step
                if not have[chosen]:
                    del by_id[chosen]
                left -= step
                need -= step
        if left:
            raise StaleMatch('Stock or missing count changed · try again')
        return finish(db,changes,'transfer',dict(history_id=histories[0],history_ids=histories,quantity=amount))


def picker(db, selected, ranking=None, *, all_gaps=None):
    all_gaps = gaps(db) if all_gaps is None else all_gaps
    selected = set(selected)
    counts, eligible = completion_context(db, all_gaps)
    totals = {copy_id: sum(keys.values()) for copy_id, keys in counts.items()}
    rows = [r for r in all_gaps if r['target']=='part' and r['copy_id'] in selected]
    grouped = {}
    for r in rows:
        key = r['item_type'],r['item_no'],r['color_id']
        g = grouped.setdefault(key,dict(r,needs=[],total=0,completes=0))
        g['needs'].append(r)
        g['total'] += r['need']
    for g in grouped.values():
        for copy_id in {r['copy_id'] for r in g['needs']}:
            if totals[copy_id] == counts[copy_id][identity(g)] and copy_id in eligible:
                g['completes'] += 1
    categories = {}
    for raw in db.execute("SELECT item_type,item_no,value FROM item_properties WHERE key='rebrickable.category' AND source='rebrickable'"):
        value = (raw['value'] or '').strip()
        if value:
            categories[(raw['item_type'], raw['item_no'])] = 'Rebrickable category ' + value
    for g in grouped.values():
        g['category'] = g.get('category') or categories.get((g['item_type'], g['item_no']))
    storage_names = defaultdict(set)
    unresolved_keys = {(r[0], r[1]) for r in db.execute("SELECT item_type,item_no FROM id_match WHERE status='to_check'")}
    for raw in db.execute("""SELECT s.*,t.name AS storage_name FROM loose_stock s JOIN storages t ON t.id=s.storage_id
            WHERE s.item_type='P' AND s.archived_at IS NULL AND t.archived_at IS NULL AND t.name IS NOT NULL"""):
        source = dict(raw)
        if source['storage_name'] and available(db, source, unresolved_keys=unresolved_keys):
            storage_names[identity(source)].add(source['storage_name'])
    for g in grouped.values():
        g['rank_set'] = min(r['copy']['set_no'] for r in g['needs'])
        g['rank_storage'] = ' · '.join(sorted(storage_names[identity(g)]))
    return order_picker(list(grouped.values()), ranking)


PICKER_KEYS = ('category', 'colour', 'size', 'set', 'storage')
PICKER_DEFAULT = PICKER_KEYS


def picker_keys(rows):
    """Availability is based on the selected snapshot, never guessed dimensions."""
    reasons = dict(size='No part sizes are recorded',
        category='' if any(r.get('category') for r in rows) else 'No category is recorded for these parts',
        storage='' if any(r.get('rank_storage') for r in rows) else 'No usable loose parts have a recorded location')
    return [dict(key=k, label=k.capitalize(),
                 reason=reasons.get(k, '')) for k in PICKER_KEYS]


def order_picker(rows, ranking=None):
    enabled = set(k['key'] for k in picker_keys(rows) if not k['reason'])
    ranking = list(dict.fromkeys(k for k in (PICKER_DEFAULT if ranking is None else ranking) if k in enabled))
    def key(row):
        values = dict(completes=-row['completes'], colour=row.get('color_name') or '',
                      category=row.get('category') or '', set=row['rank_set'], storage=row['rank_storage'])
        return tuple((k != 'colour' and values[k] == '', values[k]) for k in ranking) + (-row['completes'], row['item_no'], row['color_id'] or 0)
    return sorted(rows, key=key)


def found(db, kind, number, color, destination, assignments, amount):
    amount = quantity(amount)
    if destination not in ('set','loose','list') or kind != 'P':
        raise ValueError('Choose a resolved part and destination')
    with transaction(db):
        if unresolved(db,kind,number) or not db.execute('SELECT 1 FROM items WHERE item_type=? AND item_no=?',(kind,number)).fetchone() or not db.execute('SELECT 1 FROM colors WHERE color_id=?',(color,)).fetchone():
            raise ValueError('Part or colour is unavailable')
        changes = []
        if destination == 'set':
            current = {str(r['target_id']):r for r in gaps(db) if r['target']=='part' and not r['unresolved'] and (r['item_type'],r['item_no'],r['color_id'])==(kind,number,color)}
            if not isinstance(assignments,dict) or not assignments or sum(quantity(q) for q in assignments.values()) != amount:
                raise ValueError('Assign the found count to copies')
            for identifier,q in assignments.items():
                q = quantity(q)
                gap = current.get(str(identifier))
                if not gap or q > gap['need']:
                    raise StaleMatch('Missing count changed · review the part again')
                reduce_gap(db,changes,gap,q)
        elif destination == 'loose':
            identifier = uuid4().hex
            record(db,changes,'loose_stock',{'id':identifier},lambda:db.execute('INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition,created_at,updated_at) VALUES(?,?,?,?,?,\'U\',?,?)',(identifier,kind,number,color,amount,stamp(),stamp())))
        return finish(db,changes,'found',dict(item_type=kind,item_no=number,color_id=color,destination=destination,quantity=amount))


def booklet_number(db, number):
    if '-' in number:
        return lookup(db, 'I', number), 'unknown booklet number'
    path = catalogue_path(db)
    candidates = []
    if path.is_file():
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as cat:
            candidates = [r[0] for r in cat.execute("SELECT item_no FROM items WHERE item_type='I' AND item_no GLOB ?", (number + '-[0-9]*',))
                          if re.fullmatch(re.escape(number) + r'-[0-9]+', r[0])]
    if len(candidates) != 1:
        return None, 'ambiguous; enter the full booklet number' if candidates else 'unknown booklet number'
    return lookup(db, 'I', candidates[0]), 'unknown booklet number'


def booklets(db, text, amount):
    amount = quantity(amount)
    if amount > 99 or not isinstance(text,str) or len(text)>20000:
        raise ValueError('Enter up to 200 booklet lines · quantity 1 to 99')
    lines = [(index, s.strip()) for index, s in enumerate(text.splitlines(), 1) if s.strip()]
    if not 1 <= len(lines) <= 200:
        raise ValueError('Enter 1 to 200 booklet lines')
    parsed, errors = [], []
    for index,line in lines:
        cells = [s.strip() for s in line.split(',')]
        if len(cells)>2 or not re.fullmatch(r'[A-Za-z0-9]+(?:-[0-9]+)?',cells[0]):
            raise ValueError(f'Line {index}: use a set number, optionally comma and quantity')
        q = quantity(cells[1]) if len(cells)==2 else amount
        if q > 99:
            raise ValueError(f'Line {index}: quantity must be 1 to 99')
        item, reason = booklet_number(db, cells[0])
        if item is None:
            errors.append(f'Line {index}: {cells[0]} · {reason}')
        else:
            parsed.append((item,q))
    if errors:
        raise ValueError('Nothing was saved · ' + '; '.join(errors))
    with transaction(db):
        changes = []
        for item,q in parsed:
            number = item['item_no']
            record(db,changes,'items',dict(item_type='I',item_no=number),lambda i=item:db.execute("INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES('I',?,?)",(i['item_no'],i['name'])))
            identifier = uuid4().hex
            record(db,changes,'loose_stock',{'id':identifier},lambda n=number,q=q,i=identifier:db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity,condition,created_at,updated_at) VALUES(?,'I',?,?,'U',?,?)",(i,n,q,stamp(),stamp())))
        return finish(db,changes,'booklets',dict(lines=len(parsed)))


def undo(db, event_id, *, receipt=None):
    with transaction(db):
        row = receipt if receipt is not None else db.execute("SELECT * FROM events WHERE id=? AND entity='bw_workbench' AND field='receipt'",(event_id,)).fetchone()
        if not row:
            raise ValueError('Save is unavailable')
        if db.execute("SELECT 1 FROM events WHERE entity='bw_workbench' AND field='undo' AND new_value=?",(json.dumps(int(event_id)),)).fetchone():
            return
        receipt = json.loads(row['new_value'])
        for c in receipt['changes']:
            if snapshot(db,c['table'],c['key']) != c['new']:
                raise ValueError('This item changed after saving · undo the later save first')
        for c in reversed(receipt['changes']):
            table,key = c['table'],c['key']
            clause = ' AND '.join(k+' IS ?' for k in key)
            if not c['old']:
                if table == 'flags':
                    # Receipts from before the shared system flag was created outside them still carry
                    # its creation. Never archive it, nor any flag other records still use.
                    flag = db.execute('SELECT kind,name FROM flags WHERE id=?',(key.get('id'),)).fetchone()
                    shared = db.execute('SELECT 1 FROM item_flags WHERE flag_id=?',(key.get('id'),)).fetchone()
                    if (flag and (flag['kind'],flag['name'])==('status','Set is checked')) or shared:
                        continue
                    db.execute('UPDATE flags SET archived_at=? WHERE '+clause,(stamp(),*key.values()))
                elif table == 'loose_stock':
                    db.execute('UPDATE loose_stock SET archived_at=?,updated_at=? WHERE '+clause,(stamp(),stamp(),*key.values()))
                # Catalogue identities remain; undo does not delete referenced items.
            elif table == 'item_flags' or not c['new']:
                db.execute('INSERT OR IGNORE INTO '+table+'('+','.join(c['old'][0])+') VALUES('+','.join('?' for _ in c['old'][0])+')',tuple(c['old'][0].values()))
            else:
                old = c['old'][0]
                db.execute('UPDATE '+table+' SET '+','.join(k+'=?' for k in old)+' WHERE '+clause,(*old.values(),*key.values()))
            if table == 'item_flags' and not c['old']:
                db.execute('DELETE FROM item_flags WHERE '+clause,tuple(key.values()))
            audit(db,'bw_workbench:'+table,'undo',c['new'],snapshot(db,table,key))
        audit(db,'bw_workbench','undo',receipt,int(event_id))
