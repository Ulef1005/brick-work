"""Send local missing part marks to Rebrickable's Lost Parts list (#469 part B).

Candidate sets are the live copies' sets that have a Rebrickable set number. Missing counts on live set lines
(`copy_figure_id IS NULL AND retired_at IS NULL`) are capped per copy at the line's quantity, summed across all live copies of each
candidate set, and translated to Rebrickable `(set_no, part_no, color_id, is_spare)` coordinates through `lost_parts._copies`,
`lost_parts._lines` and `lost_parts.copy_label`, so a copy on a BrickLink part list is translated through confirmed Rebrickable links.

Rule mapping (`RULES`, mirroring `lost_parts.RULES` in the send direction):
- `add_only`: adds parts missing locally that are not on Rebrickable (`add`), and increases counts where the local missing sum exceeds
  Rebrickable's count (`change` upward only). Never lowers a remote count and never removes a remote Lost Part.
- `per_part`: adds new missing parts (`add`), changes differing counts both upward and downward (`change`), and removes remote Lost Parts
  whose part line is present on the local copies of sets listed on both sides (`remove`, unticked by default).
- `per_set`: every candidate set with at least one local missing mark becomes the local list (`add`, `change`, and `remove` for any other
  remote Lost Part on that set whose live copies have a part list). Sets with no local missing marks are left alone.
- `everything`: every candidate set becomes the local list, including candidate sets with zero local missing marks (`remove` for all
  remaining remote Lost Parts on candidate sets whose live copies have a part list).

Limits:
The plan is recomputed by the caller just before `apply` (`apply` sends the plan's numbers as planned). The inventory part id of a new
Lost Part comes from the cached set parts (`RebrickableUser.lost_parts()` returns none for parts not yet on Rebrickable). The endpoint
shapes are assumed from Rebrickable's documentation and must be tried with a real user token before the switch is offered. Candidate sets
are the sets of all live copies that have a Rebrickable number, not only the sets on a linked list.
"""
import json
import sqlite3

from .. import wishlists
from . import adapters, lost_parts

KEY = 'rebrickable_lost_parts_send'
RULE_KEY = 'rebrickable_lost_parts_send_rule'
DEFAULT_RULE = 'add_only'
RULES = (
    ('add_only', 'Add only',
     'Only sends new Lost Parts and larger counts. Where both sides have a count, the larger is kept. Nothing is removed on Rebrickable.'),
    ('per_part', 'Brick Work wins per part',
     "For parts on sets listed on both sides, Brick Work's missing count replaces Rebrickable's, also when smaller or zero."),
    ('per_set', 'Brick Work wins per set',
     'A set with at least one missing part in Brick Work becomes exactly your list. Other Lost Parts on that set are offered for removal.'),
    ('everything', 'Brick Work wins everywhere',
     'Every synced set becomes exactly your list. A synced set with no missing parts here has its Lost Parts offered for removal.'),
)
RULE_VALUES = tuple(r[0] for r in RULES)
UNDO_NOTE = 'Undo cannot reverse a remote change on Rebrickable.'


def enabled(db):
    """Whether sending Lost Parts to Rebrickable is switched on in `main.setting` (off by default)."""
    row = db.execute('SELECT value FROM main.setting WHERE key=?', (KEY,)).fetchone()
    return bool(row and str(row[0]).strip().lower() in ('1', 'true', 'yes', 'on'))


def valid_rule(value):
    """The send rule named by `value`, or ValueError naming the four."""
    if value not in RULE_VALUES:
        raise ValueError('Choose add_only, per_part, per_set or everything for ' + RULE_KEY)
    return value


def send_rule(db):
    """The send rule in force: the stored value when it is one of the four, else `DEFAULT_RULE`."""
    row = db.execute('SELECT value FROM main.setting WHERE key=?', (RULE_KEY,)).fetchone()
    return row[0] if row and row[0] in RULE_VALUES else DEFAULT_RULE


def row_key(set_no, part_no, color_id, is_spare):
    """Stable identifier for one planned `(set_no, part_no, color_id, is_spare)` row."""
    return f'{set_no}:{part_no}:{int(color_id)}:{int(bool(is_spare))}'


def _candidate_set_numbers(db, remote_rows):
    item_ids = [r[0] for r in db.execute('SELECT DISTINCT item_id FROM main.copy WHERE archived_at IS NULL')]
    numbers = {r['set_no'] for r in remote_rows}
    for names in wishlists._rebrickable_numbers(db, set(item_ids)).values():
        numbers.update(names)
    return numbers


def _lookup_inv_part_id(db, set_no, part_no, color_id, is_spare, remote_inv_parts):
    direct = remote_inv_parts.get((set_no, str(part_no), int(color_id), bool(is_spare)))
    if direct is not None:
        return direct
    try:
        row = db.execute("SELECT payload FROM main.source_record WHERE kind='rebrickable_set_parts' AND key=?", (set_no,)).fetchone()
        if row and row[0]:
            for entry in json.loads(row[0]).get('results', ()):
                part = (entry.get('part') or {}).get('part_num')
                colour = (entry.get('color') or {}).get('id')
                if part == str(part_no) and colour == int(color_id) and bool(entry.get('is_spare')) is bool(is_spare):
                    return entry.get('inv_part_id') or entry.get('id')
    except (sqlite3.Error, ValueError, TypeError, AttributeError):
        pass
    return None


def _collect_set_lines(db, set_no, held):
    """Aggregate live set lines across all live `held` copies of one set into Rebrickable coordinates."""
    aggregated = {}
    present_keys = set()
    unmatched = []
    missing_part_list = False
    for copy in held:
        label = lost_parts.copy_label(copy)
        inv_row = db.execute('SELECT inventory_source FROM main.copy WHERE id=?', (copy['id'],)).fetchone()
        inv_source = inv_row[0] if inv_row else None
        lines = [dict(r) for r in db.execute(
            '''SELECT id, item_id, color_id, is_spare, quantity, missing FROM main.copy_part
               WHERE copy_id=? AND copy_figure_id IS NULL AND retired_at IS NULL ORDER BY id''', (copy['id'],))]
        if inv_source == 'none' or not lines:
            missing_part_list = True
            continue
        numbers = wishlists._rebrickable_numbers(db, {l['item_id'] for l in lines})
        colours = wishlists._rebrickable_colours(db, {l['color_id'] for l in lines})
        _, _ = lost_parts._lines(db, copy['id'], lines)
        for line in lines:
            part_nos = sorted(numbers.get(line['item_id'], ()))
            colour_ids = sorted(colours.get(line['color_id'], ()), key=lambda c: int(c) if str(c).isdigit() else str(c))
            spare = bool(line['is_spare'])
            capped = min(line['missing'], max(0, line['quantity']))
            if len(part_nos) != 1 or len(colour_ids) != 1:
                if capped > 0:
                    reason = ('No Rebrickable number for this part or colour'
                              if not part_nos or not colour_ids else
                              'Several Rebrickable numbers match this part or colour')
                    unmatched.append(dict(set_no=set_no, copy_id=copy['id'], copy_label=label, item_id=line['item_id'],
                                          color_id=line['color_id'], is_spare=spare, missing=capped, reason=reason))
                continue
            key = (part_nos[0], int(colour_ids[0]), spare)
            present_keys.add(key)
            if capped > 0:
                bucket = aggregated.setdefault(key, dict(missing=0, copies={}, inv_part_id=None))
                bucket['missing'] += capped
                entry = bucket['copies'].setdefault(copy['id'], dict(id=copy['id'], label=label, missing=0))
                entry['missing'] += capped
    return aggregated, present_keys, unmatched, missing_part_list


def plan(db, remote, translate, *, rule=None, on=True):
    """Build the pure send plan comparing local missing set-line sums with `remote` (`RebrickableUser.lost_parts()` or failure text)."""
    how = valid_rule(send_rule(db) if rule is None else rule)
    out = dict(on=bool(on), rule=how, status='off', message=None, unreadable=0, clearing=True, rows=[], unmatched=[],
               summary=dict(add=0, change=0, remove=0, unmatched=0, unreadable=0))
    if not on:
        return out
    if not isinstance(remote, dict):
        out.update(status='unavailable', clearing=False,
                   message='Lost Parts were not read: ' + (remote or 'no answer') + '. Nothing can be sent until the list is read.')
        return out
    unreadable = int(remote.get('unreadable') or 0)
    if unreadable > 0:
        out.update(status='unavailable', unreadable=unreadable, clearing=False,
                   message='%d %s could not be read, so nothing can be sent this time.' % (
                       unreadable, 'Lost Parts row' if unreadable == 1 else 'Lost Parts rows'))
        out['summary']['unreadable'] = unreadable
        return out
    remote_rows = list(remote.get('rows') or ())
    remote_inv_parts = dict(remote.get('inv_parts') or {})
    out.update(status='read', unreadable=0)

    remote_by_set = lost_parts.by_set(remote_rows)
    numbers = _candidate_set_numbers(db, remote_rows)
    mapping = translate(db, numbers)
    copies_by_item = lost_parts._copies(db, [i for i in mapping.values() if i])

    for set_no in sorted(numbers):
        item_id = mapping.get(set_no)
        if not item_id:
            continue
        held = copies_by_item.get(item_id, [])
        if not held:
            continue
        local_map, present_keys, unmatched, missing_part_list = _collect_set_lines(db, set_no, held)
        out['unmatched'].extend(unmatched)
        remote_map = {}
        for r in remote_by_set.get(set_no, ()):
            rkey = (str(r['part_no']), int(r['color_id']), bool(r['is_spare']))
            remote_map[rkey] = r
            if r.get('inv_part_id') is not None:
                remote_inv_parts[(set_no, rkey[0], rkey[1], rkey[2])] = r['inv_part_id']

        has_local_marks = bool(local_map or unmatched)
        has_remote_marks = bool(remote_map)
        noted_missing_list = False
        if missing_part_list and has_remote_marks and how in ('per_set', 'everything'):
            out['unmatched'].append(dict(
                set_no=set_no,
                parts=len(remote_map),
                pieces=sum(int(r['quantity']) for r in remote_map.values()),
                reason='The set has no part list yet',
            ))
            noted_missing_list = True
        all_keys = sorted(set(local_map) | set(remote_map))
        for part_no, color_id, is_spare in all_keys:
            local_entry = local_map.get((part_no, color_id, is_spare))
            remote_entry = remote_map.get((part_no, color_id, is_spare))
            local_qty = local_entry['missing'] if local_entry else 0
            remote_qty = int(remote_entry['quantity']) if remote_entry else 0
            if local_qty == remote_qty:
                continue
            if local_qty > 0 and remote_qty == 0:
                state = 'add'
            elif local_qty > 0 and remote_qty > 0:
                if local_qty < remote_qty:
                    if how == 'add_only':
                        continue
                    if not out['clearing'] or unmatched or missing_part_list:
                        if missing_part_list and not noted_missing_list:
                            out['unmatched'].append(dict(
                                set_no=set_no,
                                parts=len(remote_map),
                                pieces=sum(int(r['quantity']) for r in remote_map.values()),
                                reason='The set has no part list yet',
                            ))
                            noted_missing_list = True
                        continue
                state = 'change'
            else:
                if how == 'add_only':
                    continue
                if how == 'per_part' and not (has_local_marks and has_remote_marks and (part_no, color_id, is_spare) in present_keys):
                    continue
                if how == 'per_set' and not has_local_marks:
                    continue
                if not out['clearing'] or unmatched or missing_part_list:
                    if missing_part_list and not noted_missing_list:
                        out['unmatched'].append(dict(
                            set_no=set_no,
                            parts=len(remote_map),
                            pieces=sum(int(r['quantity']) for r in remote_map.values()),
                            reason='The set has no part list yet',
                        ))
                        noted_missing_list = True
                    continue
                state = 'remove'

            inv_part_id = (remote_entry.get('inv_part_id') if remote_entry else None) or _lookup_inv_part_id(
                db, set_no, part_no, color_id, is_spare, remote_inv_parts)
            ids = list(remote_entry.get('ids') or ()) if remote_entry else []
            ids_complete = (bool(remote_entry.get('ids_complete', bool(ids))) and bool(ids)) if remote_entry else True
            reason = None
            needs_remove = state == 'remove' or (state == 'change' and how != 'add_only')
            if needs_remove and not ids_complete:
                tickable = False
                ticked = False
                reason = 'Missing Rebrickable lost part id'
            elif state in ('add', 'change') and not inv_part_id:
                tickable = False
                ticked = False
                reason = 'Rebrickable inventory part id unknown'
            else:
                tickable = True
                ticked = state != 'remove'
            copies = (list(local_entry['copies'].values()) if local_entry else
                      [dict(id=c['id'], label=lost_parts.copy_label(c), missing=0) for c in held])
            row = dict(
                key=row_key(set_no, part_no, color_id, is_spare),
                set_no=set_no,
                part_no=part_no,
                color_id=color_id,
                is_spare=is_spare,
                state=state,
                rule=how,
                before=remote_qty,
                after=local_qty,
                quantity=(local_qty - remote_qty) if (state == 'change' and how == 'add_only') else (local_qty if state != 'remove' else remote_qty),
                tickable=tickable,
                ticked=ticked,
                reason=reason,
                copies=copies,
                inv_part_id=inv_part_id,
                ids=ids,
                ids_complete=ids_complete,
                added=False,
                removed=False,
            )
            out['rows'].append(row)
            out['summary'][state] += 1

    out['summary']['unmatched'] = len(out['unmatched'])
    return out


def _matches_tick(row, selected):
    if 'key' in row and row['key'] in selected:
        return True
    if all(k in row for k in ('set_no', 'part_no', 'color_id', 'is_spare')):
        try:
            tuple_key = (row['set_no'], row['part_no'], int(row['color_id']), bool(row['is_spare']))
            return tuple_key in selected
        except (TypeError, ValueError):
            return False
    return False


def _is_pos_int(value):
    return type(value) is int and value >= 1


def _validate_row(row, plan_rule):
    if not row.get('tickable', True):
        return row.get('reason') or 'Row is not sendable'
    state = row.get('state')
    if state not in ('add', 'change', 'remove'):
        return f'Unknown state: {state}'
    add_only_change = state == 'change' and (row.get('rule') or plan_rule) == 'add_only'
    if state in ('add', 'change'):
        if not _is_pos_int(row.get('inv_part_id')):
            return row.get('reason') or (
                'Rebrickable inventory part id unknown'
                if row.get('inv_part_id') is None
                else 'Invalid Rebrickable inventory part id'
            )
        if not _is_pos_int(row.get('after')):
            return 'Invalid target quantity'
        if add_only_change:
            before = row.get('before')
            if type(before) is not int or before < 0 or row['after'] <= before:
                return 'Invalid quantity change for add_only'
    ids = row.get('ids')
    if ids is not None:
        if not isinstance(ids, (list, tuple)) or not all(_is_pos_int(lost_id) for lost_id in ids):
            return 'Invalid Rebrickable lost part id'
    if (state == 'remove' or (state == 'change' and not add_only_change)) and not row.get('removed'):
        if not row.get('ids_complete', True) or not ids:
            return row.get('reason') or 'Missing Rebrickable lost part id'
    return None


def apply(db, client, planned, ticked=None, *, via='web', actor='user'):
    """Send the ticked rows of `planned` through `client`. Writes nothing locally."""
    del db, via, actor
    plan_rule = (planned or {}).get('rule')
    rows = list((planned or {}).get('rows') or ())
    if ticked is None:
        chosen = [r for r in rows if r.get('ticked')]
    else:
        if isinstance(ticked, (str, bytes, bytearray)):
            raise ValueError('ticked must be an iterable of hashable keys')
        try:
            selected = set(ticked)
        except TypeError as exc:
            raise ValueError('ticked must be an iterable of hashable keys') from exc
        chosen = [r for r in rows if _matches_tick(r, selected)]

    def _partition_tail(tail_rows):
        for tail in tail_rows:
            copy_row = dict(tail)
            err = _validate_row(copy_row, plan_rule)
            if err is not None:
                failed.append(dict(copy_row, reason=err))
            else:
                copy_row['ticked'] = True
                remaining.append(copy_row)

    sent, failed, remaining = [], [], []
    for idx, orig_row in enumerate(chosen):
        row = dict(orig_row)
        err = _validate_row(row, plan_rule)
        if err is not None:
            failed.append(dict(row, reason=err))
            continue
        state = row['state']
        add_only_change = state == 'change' and (row.get('rule') or plan_rule) == 'add_only'
        added = bool(row.get('added'))
        removed = bool(row.get('removed'))
        removed_ids = list(row.get('removed_ids') or ())

        def _save_progress():
            if state in ('add', 'change'):
                row['added'] = added
            if state == 'remove' or (state == 'change' and not add_only_change):
                row['removed'] = removed
                if removed_ids:
                    row['removed_ids'] = removed_ids

        try:
            if state == 'add':
                if not added:
                    client.lost_part_add(row['inv_part_id'], row['after'])
                    added = True
            elif state == 'change':
                if not added:
                    qty = (row['after'] - row['before']) if add_only_change else row['after']
                    client.lost_part_add(row['inv_part_id'], qty)
                    added = True
                if not add_only_change and not removed:
                    for lost_id in row.get('ids') or ():
                        if lost_id in removed_ids:
                            continue
                        client.lost_part_remove(lost_id)
                        removed_ids.append(lost_id)
                    removed = True
            elif state == 'remove':
                if not removed:
                    for lost_id in row.get('ids') or ():
                        if lost_id in removed_ids:
                            continue
                        client.lost_part_remove(lost_id)
                        removed_ids.append(lost_id)
                    removed = True
        except adapters.KeyRejected as exc:
            _save_progress()
            row['ticked'] = True
            remaining.append(row)
            _partition_tail(chosen[idx + 1:])
            exc.partial = dict(sent=sent, failed=failed, remaining=remaining, note=UNDO_NOTE)
            raise
        except (adapters.RemoteBudgetExceeded, adapters.WaitingForBudget):
            _save_progress()
            row['ticked'] = True
            remaining.append(row)
            _partition_tail(chosen[idx + 1:])
            break
        except adapters.SourceError as exc:
            _save_progress()
            failed.append(dict(row, reason=str(exc) or 'Rebrickable API unsuccessful'))
            continue
        _save_progress()
        sent.append(row)
    return dict(sent=sent, failed=failed, remaining=remaining, note=UNDO_NOTE)
