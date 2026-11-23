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
"""
import json
import sqlite3

from .. import wishlists
from . import adapters, lost_parts

KEY = 'rebrickable_lost_parts_send'
DEFAULT_RULE = lost_parts.DEFAULT_RULE
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
    how = lost_parts.valid_rule(rule or lost_parts.rule(db))
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
        if missing_part_list and has_remote_marks and how in ('per_set', 'everything'):
            out['unmatched'].append(dict(
                set_no=set_no,
                parts=len(remote_map),
                pieces=sum(int(r['quantity']) for r in remote_map.values()),
                reason='The set has no part list yet',
            ))
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
                if how == 'add_only' and local_qty < remote_qty:
                    continue
                state = 'change'
            else:
                if not out['clearing'] or unmatched or missing_part_list or how == 'add_only':
                    continue
                if how == 'per_part' and not (has_local_marks and has_remote_marks and (part_no, color_id, is_spare) in present_keys):
                    continue
                if how == 'per_set' and not has_local_marks:
                    continue
                state = 'remove'

            inv_part_id = (remote_entry.get('inv_part_id') if remote_entry else None) or _lookup_inv_part_id(
                db, set_no, part_no, color_id, is_spare, remote_inv_parts)
            ids = list(remote_entry.get('ids') or ()) if remote_entry else []
            ids_complete = (bool(remote_entry.get('ids_complete', bool(ids))) and bool(ids)) if remote_entry else True
            reason = None
            if state in ('change', 'remove') and not ids_complete:
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
                before=remote_qty,
                after=local_qty,
                quantity=local_qty if state != 'remove' else remote_qty,
                tickable=tickable,
                ticked=ticked,
                reason=reason,
                copies=copies,
                inv_part_id=inv_part_id,
                ids=ids,
                ids_complete=ids_complete,
                removed=False,
            )
            out['rows'].append(row)
            out['summary'][state] += 1

    out['summary']['unmatched'] = len(out['unmatched'])
    return out


def _matches_tick(row, selected):
    tuple_key = (row['set_no'], row['part_no'], int(row['color_id']), bool(row['is_spare']))
    return row['key'] in selected or tuple_key in selected


def apply(db, client, planned, ticked=None, *, via='web', actor='user'):
    """Send the ticked rows of `planned` through `client`. Writes nothing locally."""
    del db, via, actor
    rows = list((planned or {}).get('rows') or ())
    if ticked is None:
        chosen = [r for r in rows if r.get('ticked') and r.get('tickable', True)]
    else:
        selected = set(ticked)
        chosen = [r for r in rows if _matches_tick(r, selected)]

    sent, failed, remaining = [], [], []
    for idx, orig_row in enumerate(chosen):
        row = dict(orig_row)
        state = row['state']
        if not row.get('tickable', True):
            failed.append(dict(row, reason=row.get('reason') or 'Row is not sendable'))
            continue
        if state in ('add', 'change') and not row.get('inv_part_id'):
            failed.append(dict(row, reason=row.get('reason') or 'Rebrickable inventory part id unknown'))
            continue
        removed = bool(row.get('removed'))
        removed_ids = list(row.get('removed_ids') or ())
        if state in ('change', 'remove') and not removed and (not row.get('ids') or not row.get('ids_complete', True)):
            failed.append(dict(row, reason=row.get('reason') or 'Missing Rebrickable lost part id'))
            continue
        try:
            if state in ('change', 'remove') and not removed:
                for lost_id in row.get('ids') or ():
                    if lost_id in removed_ids:
                        continue
                    client.lost_part_remove(lost_id)
                    removed_ids.append(lost_id)
                removed = True
            if state in ('add', 'change'):
                client.lost_part_add(row['inv_part_id'], row['after'])
            elif state != 'remove':
                failed.append(dict(row, reason=f'Unknown state: {state}'))
                continue
        except adapters.KeyRejected:
            raise
        except (adapters.RemoteBudgetExceeded, adapters.WaitingForBudget):
            if state in ('change', 'remove'):
                row['removed'] = removed
                if removed_ids:
                    row['removed_ids'] = removed_ids
            remaining.append(row)
            remaining.extend(chosen[idx + 1:])
            break
        except adapters.SourceError as exc:
            if state in ('change', 'remove'):
                row['removed'] = removed
                if removed_ids:
                    row['removed_ids'] = removed_ids
            failed.append(dict(row, reason=str(exc) or 'Rebrickable API unsuccessful'))
            continue
        if state in ('change', 'remove'):
            row['removed'] = removed
            if removed_ids:
                row['removed_ids'] = removed_ids
        sent.append(row)
    return dict(sent=sent, failed=failed, remaining=remaining, note=UNDO_NOTE)
