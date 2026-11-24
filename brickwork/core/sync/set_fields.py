"""Brickset set notes and flags into Brick Work (#690): pull only.

Notes land on live copies of the set (or on its live wish in the linked wishlist when no copy exists).
Each Brickset flag maps to one Brick Work tag (via setting `brickset_flag_tags`); fallback names
`Brickset flag N` rename once when a label appears later."""
import json
from uuid import uuid4

from ...store4.connect import now as store_now
from .. import errors
from .. import undo as undoing
from ..admin import audit, origin
from ..transaction import transaction

FIELD = 'fields_receipt'
FALLBACK = 'Brickset flag {n}'
MAP_KEY = 'brickset_flag_tags'


def _sync():
    from .. import sync                                   # the package imports this module
    return sync


def _get_map(db):
    row = db.execute('SELECT value FROM main.setting WHERE key=?', (MAP_KEY,)).fetchone()
    return json.loads(row[0]) if row and row[0] else {}


def _put_map(db, mapping):
    if not mapping:
        db.execute('DELETE FROM main.setting WHERE key=?', (MAP_KEY,))
    else:
        db.execute(
            'INSERT INTO main.setting(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
            (MAP_KEY, json.dumps(mapping)),
        )


def _label_for(labels, n):
    if not labels:
        return None
    val = labels.get(n)
    if not val:
        val = labels.get(str(n))
    return val or None


def _tag_name(n, labels):
    return _label_for(labels, n) or FALLBACK.format(n=n)


def _live_copies(db, item_id):
    return db.execute(
        'SELECT id, note, rating FROM main.copy WHERE item_id=? AND archived_at IS NULL ORDER BY id',
        (item_id,),
    ).fetchall()


def _live_wishes(db, item_id, wish_list):
    return db.execute(
        'SELECT id, note, priority FROM main.wish WHERE wishlist_id=? AND item_id=? AND color_key=0 AND archived_at IS NULL ORDER BY id',
        (wish_list, item_id),
    ).fetchall()


def _field_row(kind, table, target_id, item_id, number, name, remote, here):
    is_add = here is None
    return dict(
        key=f'{kind}:{table}:{target_id}', kind=kind, table=table, target_id=target_id,
        item_id=item_id, number=number, name=name, flag=None, remote=remote,
        here=here, state='add' if is_add else 'conflict',
        options=[] if is_add else ['keep', 'take'],
        default=None if is_add else 'keep', tickable=is_add,
    )


def _plan_scalar(rows, not_kept, not_kept_key, kind, table, targets, item_id, number, name, remote):
    if not targets:
        not_kept[not_kept_key] += 1
        return
    for target_id, _, local_val in targets:
        if local_val == remote:
            continue
        rows.append(_field_row(kind, table, target_id, item_id, number, name, remote, local_val))


def _find_tag(db, flag_map, n, tag_name):
    """Existing tag id for Brickset flag `n`, or None if it has not been created yet."""
    mapped = flag_map.get(str(n))
    if mapped is not None:
        row = db.execute("SELECT id FROM main.flag WHERE id=? AND kind='tag' AND archived_at IS NULL", (mapped,)).fetchone()
        if row is not None:
            return row[0]
    row = db.execute("SELECT id FROM main.flag WHERE lower(name)=lower(?) AND kind='tag' AND archived_at IS NULL", (tag_name,)).fetchone()
    return row[0] if row is not None else None


def _has_flag(db, table, target_id, flag_id):
    link_tbl, col = ('main.copy_flag', 'copy_id') if table == 'copy' else ('main.wish_flag', 'wish_id')
    return db.execute(f'SELECT 1 FROM {link_tbl} WHERE {col}=? AND flag_id=?', (target_id, flag_id)).fetchone() is not None


def _rename_if_fallback(db, flag_id, new_name, n):
    """Rename `flag_id` once if its current name is still the fallback `Brickset flag N`."""
    row = db.execute("SELECT name FROM main.flag WHERE id=? AND kind='tag' AND archived_at IS NULL", (flag_id,)).fetchone()
    if row is None:
        return None
    fallback = FALLBACK.format(n=n)
    if row[0] == fallback and new_name != fallback:
        if db.execute("SELECT 1 FROM main.flag WHERE kind='tag' AND archived_at IS NULL AND lower(name)=lower(?) AND id<>?", (new_name, flag_id)).fetchone():
            return None                                    # another live tag already has that name: keep the fallback rather than make two
        db.execute('UPDATE main.flag SET name=? WHERE id=?', (new_name, flag_id))
        return dict(flag_id=flag_id, before=row[0], after=new_name)
    return None


def _ensure_tag(db, flag_map, n, tag_name):
    """Return `(flag_id, created, renamed_entry)` for Brickset flag `n`."""
    key = str(n)
    mapped = flag_map.get(key)
    if mapped is not None:
        row = db.execute("SELECT id FROM main.flag WHERE id=? AND kind='tag' AND archived_at IS NULL", (mapped,)).fetchone()
        if row is not None:
            return row[0], False, _rename_if_fallback(db, row[0], tag_name, n)
    row = db.execute("SELECT id FROM main.flag WHERE lower(name)=lower(?) AND kind='tag' AND archived_at IS NULL", (tag_name,)).fetchone()
    if row is not None:
        flag_map[key] = row[0]
        return row[0], False, None
    fid = uuid4().hex
    db.execute("INSERT INTO main.flag(id, name, kind, shown_on_grid, created_at) VALUES(?, ?, 'tag', 0, ?)", (fid, tag_name, store_now()))
    flag_map[key] = fid
    return fid, True, None


def plan(db, remote_fields, labels, *, wish_list='default'):
    """Preview a pull of Brickset set notes and flags. Writes nothing to the collection."""
    sync = _sync()
    numbers = sorted(remote_fields or {})
    translated = sync.translate(db, numbers) if numbers else {}
    item_ids = sorted({iid for iid in translated.values() if iid is not None})
    names = sync._names(db, item_ids) if item_ids else {}
    flag_map = _get_map(db)
    rows, unmatched = [], []
    new_names = set()
    not_kept = dict(notes=0, flags=0, ratings=0, priorities=0)
    for number in numbers:
        item_id = translated.get(number)
        if item_id is None:
            unmatched.append(number)
            continue
        entry = remote_fields[number] or {}
        remote_note = entry.get('notes') or ''
        remote_flags = sorted(set(entry.get('flags') or ()))
        copies = _live_copies(db, item_id)
        wishes = _live_wishes(db, item_id, wish_list)
        targets = [('copy', r[0], r[1]) for r in copies] if copies else [('wish', r[0], r[1]) for r in wishes]
        _, name = names.get(item_id, (number, ''))
        if remote_note:
            if not targets:
                not_kept['notes'] += 1
            else:
                for table, target_id, local_note in targets:
                    if local_note == remote_note:
                        continue
                    rows.append(_field_row('note', table, target_id, item_id, number, name, remote_note, local_note or None))
        for n in remote_flags:
            if not targets:
                not_kept['flags'] += 1
                continue
            tag_name = _tag_name(n, labels)
            existing_fid = _find_tag(db, flag_map, n, tag_name)
            if existing_fid is None:
                new_names.add(tag_name.lower())                   # apply creates this tag, so no rename may take its name
            shown = tag_name
            if existing_fid is not None:                    # apply links this tag, so the preview names it, whatever the label is now
                got = db.execute('SELECT name FROM main.flag WHERE id=?', (existing_fid,)).fetchone()
                shown = got[0] if got else tag_name
            for table, target_id, _ in targets:
                if existing_fid is not None and _has_flag(db, table, target_id, existing_fid):
                    continue
                rows.append(dict(
                    key=f'flag{n}:{table}:{target_id}', kind='flag', table=table, target_id=target_id,
                    item_id=item_id, number=number, name=name, flag=n, remote=shown,
                    here=None, state='add', options=[], default=None, tickable=True,
                ))
        remote_rating = entry.get('rating')
        if type(remote_rating) is int and 1 <= remote_rating <= 5:        # the store's own range: anything else is not a rating
            _plan_scalar(rows, not_kept, 'ratings', 'rating', 'copy', copies, item_id, number, name, remote_rating)
        remote_priority = entry.get('priority')
        if type(remote_priority) is int and 1 < remote_priority <= 999:  # 1 is Brickset's default; the store's range is 1 to 999
            _plan_scalar(rows, not_kept, 'priorities', 'priority', 'wish', wishes, item_id, number, name, remote_priority)
    plan_labels = {str(n): lbl for n, lbl in (labels or {}).items() if lbl}
    renames = []                                            # a tag still named `Brickset flag N` whose flag has a label now: apply renames it, whatever is ticked
    for str_n, label in sorted(plan_labels.items()):
        fid = flag_map.get(str_n)
        row = db.execute("SELECT name FROM main.flag WHERE id=? AND kind='tag' AND archived_at IS NULL", (fid,)).fetchone() if fid else None
        if row and row[0] == FALLBACK.format(n=int(str_n)) and label != row[0] and label.lower() not in new_names and not db.execute("SELECT 1 FROM main.flag WHERE kind='tag' AND archived_at IS NULL AND lower(name)=lower(?) AND id<>?", (label, fid)).fetchone():
            renames.append(dict(flag=int(str_n), flag_id=fid, before=row[0], after=label))
    value = dict(
        id=uuid4().hex, created_at=sync.now().isoformat(), direction='fields', source='brickset',
        rows=rows, unmatched=unmatched, not_kept=not_kept, labels=plan_labels, renames=renames,
        summary=dict(
            add=sum(1 for r in rows if r['state'] == 'add'),
            conflict=sum(1 for r in rows if r['state'] == 'conflict'),
            notes=sum(1 for r in rows if r['kind'] == 'note'),
            flags=sum(1 for r in rows if r['kind'] == 'flag'),
            ratings=sum(1 for r in rows if r['kind'] == 'rating'),
            priorities=sum(1 for r in rows if r['kind'] == 'priority'),
            unmatched=len(unmatched), renames=len(renames),
        ),
    )
    return sync._save_plan(db, value)


def _select_rows(value, ticked, choices):
    add_rows = [r for r in value['rows'] if r['state'] == 'add']
    conflict_rows = [r for r in value['rows'] if r['state'] == 'conflict']
    if ticked is None:
        chosen_keys = {r['key'] for r in add_rows}
    else:
        if isinstance(ticked, (str, bytes)) or not isinstance(ticked, (list, tuple, set)):
            raise errors.ValidationFailed('Send the ticked rows as a list of row keys')
        add_keys = {r['key'] for r in add_rows}
        if any(not isinstance(k, str) for k in ticked) or any(k not in add_keys for k in ticked):
            raise errors.ValidationFailed('Unknown set-field rows')
        chosen_keys = set(ticked)
    choices = {} if choices is None else choices
    if not isinstance(choices, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in choices.items()):
        raise errors.ValidationFailed('Send choices as an object of row key to option')
    conflict_by_key = {r['key']: r for r in conflict_rows}
    for k, v in choices.items():
        if k not in conflict_by_key or v not in conflict_by_key[k]['options']:
            raise errors.ValidationFailed('Unknown or invalid conflict choice')
    for r in conflict_rows:
        if choices.get(r['key'], r['default']) == 'take':
            chosen_keys.add(r['key'])
    return [r for r in value['rows'] if r['key'] in chosen_keys]


def apply(db, plan_id, ticked=None, *, choices=None, via=None, actor=None):
    """Apply ticked rows and chosen conflict takes in one transaction with one receipt (`sync:<plan>` / `fields_receipt`)."""
    from .. import plans
    sync = _sync()
    value = sync.load_plan(db, plan_id, 'fields')
    done = plans.applied(db, 'sync', plan_id)
    if done:
        return dict(event_id=done['event_id'], already_applied=True, counts=done['counts'])
    rows = _select_rows(value, ticked, choices)
    if via is None:
        via, actor = origin()
    stamp = store_now()
    receipt = dict(plan=plan_id, notes=[], ratings=[], priorities=[], links=[], tags_created=[], renamed=[], skipped=[], map_before=None)
    with transaction(db):
        done = plans.applied(db, 'sync', plan_id)
        if done:
            return dict(event_id=done['event_id'], already_applied=True, counts=done['counts'])
        map_before = _get_map(db)
        receipt['map_before'] = map_before
        flag_map = dict(map_before)
        for r in rows:
            if r['kind'] in ('note', 'rating', 'priority'):
                tbl = 'main.copy' if r['table'] == 'copy' else 'main.wish'
                col = r['kind']
                cur = db.execute(f'SELECT {col} FROM {tbl} WHERE id=? AND archived_at IS NULL', (r['target_id'],)).fetchone()
                if cur is None:                                       # archived since the plan
                    receipt['skipped'].append(dict(table=r['table'], id=r['target_id']))
                    continue
                cur_val = (cur[0] or None) if col == 'note' else cur[0]
                here_val = (r['here'] or None) if col == 'note' else r['here']
                if cur_val != here_val:                              # changed since the plan: never overwrite what the person wrote meanwhile
                    receipt['skipped'].append(dict(table=r['table'], id=r['target_id']))
                    continue
                if cur[0] != r['remote']:
                    db.execute(f'UPDATE {tbl} SET {col}=?, updated_at=? WHERE id=?', (r['remote'], stamp, r['target_id']))
                    entry = dict(id=r['target_id'], before=cur[0], after=r['remote'])
                    if col == 'note':
                        entry['table'] = r['table']
                        receipt['notes'].append(entry)
                    elif col == 'rating':
                        receipt['ratings'].append(entry)
                    else:
                        receipt['priorities'].append(entry)
            else:
                tbl = 'main.copy' if r['table'] == 'copy' else 'main.wish'
                if db.execute(f'SELECT 1 FROM {tbl} WHERE id=? AND archived_at IS NULL', (r['target_id'],)).fetchone() is None:
                    receipt['skipped'].append(dict(table=r['table'], id=r['target_id']))      # archived since the plan
                    continue
                fid, created, renamed_entry = _ensure_tag(db, flag_map, r['flag'], r['remote'])
                if created:
                    receipt['tags_created'].append(fid)
                if renamed_entry is not None:
                    receipt['renamed'].append(renamed_entry)
                link_tbl, col = ('main.copy_flag', 'copy_id') if r['table'] == 'copy' else ('main.wish_flag', 'wish_id')
                if db.execute(f'SELECT 1 FROM {link_tbl} WHERE {col}=? AND flag_id=?', (r['target_id'], fid)).fetchone() is None:
                    db.execute(f'INSERT INTO {link_tbl}({col}, flag_id) VALUES(?, ?)', (r['target_id'], fid))
                    receipt['links'].append(dict(table=r['table'], id=r['target_id'], flag_id=fid))
        for str_n, label in sorted((value.get('labels') or {}).items()):
            if label and str_n in flag_map:
                renamed_entry = _rename_if_fallback(db, flag_map[str_n], label, int(str_n))
                if renamed_entry is not None and renamed_entry not in receipt['renamed']:
                    receipt['renamed'].append(renamed_entry)
        receipt['map_added'] = sorted(k for k in flag_map if k not in map_before)
        receipt['map_changed'] = {k: v for k, v in map_before.items() if flag_map.get(k) != v}
        if flag_map != map_before:
            _put_map(db, flag_map)
        counts = dict(notes=len(receipt['notes']), flags=len(receipt['links']),
                      tags_created=len(receipt['tags_created']), renamed=len(receipt['renamed']))
        if receipt['ratings']:
            counts['ratings'] = len(receipt['ratings'])
        if receipt['priorities']:
            counts['priorities'] = len(receipt['priorities'])
        if receipt['skipped']:
            counts['skipped'] = len(receipt['skipped'])      # rows whose note changed, or whose copy or wish was archived, after the plan: left as they are
        receipt['counts'] = counts
        audit(db, 'sync:' + plan_id, FIELD, None, receipt, via=via, actor=actor)
        event = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        plans.mark(db, 'sync', plan_id, dict(event_id=event, counts=counts, at=stamp), source='brickset', created_at=value['created_at'])
    value['applied'] = dict(event_id=event, counts=counts, at=stamp)
    sync._store_plan(db, value)
    return dict(event_id=event, already_applied=False, counts=counts)


def _undo(db, event, via, actor):
    """Reverse one set-fields pull: restore notes when unchanged since, remove added links, unused created tags, renames, and map."""
    r = json.loads(event['new_value'])
    stamp = store_now()
    undo_fields = (('notes', None, 'note'), ('ratings', 'main.copy', 'rating'), ('priorities', 'main.wish', 'priority'))
    left = 0                                               # archived targets: nothing to restore on them
    for key, fixed_tbl, col in undo_fields:
        for entry in r.get(key) or ():
            tbl = fixed_tbl or ('main.copy' if entry['table'] == 'copy' else 'main.wish')
            row = db.execute(f'SELECT {col} FROM {tbl} WHERE id=? AND archived_at IS NULL', (entry['id'],)).fetchone()
            if row is None:
                left += 1                                  # archived since: its values stay as they are, and that is no reason to refuse the rest
                continue
            if row[0] != entry['after']:
                raise ValueError('Something from this sync has changed since · undo the later change first')
    for entry in r['renamed']:
        row = db.execute('SELECT name FROM main.flag WHERE id=?', (entry['flag_id'],)).fetchone()
        if row is None:
            continue                                       # the tag is gone: nothing to restore
        if (entry.get('after') is not None and row[0] != entry['after']) or db.execute("SELECT 1 FROM main.flag WHERE kind='tag' AND archived_at IS NULL AND lower(name)=lower(?) AND id<>?", (entry['before'], entry['flag_id'])).fetchone():
            raise ValueError('Something from this sync has changed since · undo the later change first')
    for key, fixed_tbl, col in undo_fields:
        for entry in reversed(r.get(key) or ()):
            tbl = fixed_tbl or ('main.copy' if entry['table'] == 'copy' else 'main.wish')
            db.execute(f'UPDATE {tbl} SET {col}=?, updated_at=? WHERE id=? AND archived_at IS NULL', (entry['before'], stamp, entry['id']))
    for link in reversed(r['links']):                      # links go even from an archived copy, so a tag this pull made can be removed
        link_tbl, col = ('main.copy_flag', 'copy_id') if link['table'] == 'copy' else ('main.wish_flag', 'wish_id')
        db.execute(f'DELETE FROM {link_tbl} WHERE {col}=? AND flag_id=?', (link['id'], link['flag_id']))
    for entry in reversed(r['renamed']):
        db.execute('UPDATE main.flag SET name=? WHERE id=?', (entry['before'], entry['flag_id']))
    deleted_tags = set()
    for fid in r['tags_created']:
        if not any(db.execute(f'SELECT 1 FROM main.{t} WHERE flag_id=? LIMIT 1', (fid,)).fetchone()
                   for t in ('copy_flag', 'stock_flag', 'wish_flag')):
            db.execute('DELETE FROM main.flag WHERE id=?', (fid,))
            deleted_tags.add(fid)
    current_map = _get_map(db)
    restored = dict(current_map)
    for k, v in list(restored.items()):
        if v in deleted_tags:
            restored.pop(k, None)
    surviving = set(r.get('tags_created') or ()) - deleted_tags
    for k in r.get('map_added') or ():
        if restored.get(k) not in surviving:             # a reused tag of the person's: the entry goes; a tag this pull made and that is in use keeps its entry
            restored.pop(k, None)
    for k, v in (r.get('map_changed') or {}).items():
        if restored.get(k) not in surviving:
            restored[k] = v
    for k, v in (r['map_before'] or {}).items():
        if k not in restored:
            restored[k] = v
    if restored != current_map:
        _put_map(db, restored)
    audit(db, 'sync:' + r['plan'], 'undo', None, dict({'undoes': event['id']}, **({'skipped': left} if left else {})), via=via, actor=actor)
    undo_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.execute('INSERT INTO main.event_undo(event_id, undo_event_id) VALUES(?, ?)', (event['id'], undo_id))
    return {'event_id': undo_id}


undoing.register('sync', FIELD, _undo)
