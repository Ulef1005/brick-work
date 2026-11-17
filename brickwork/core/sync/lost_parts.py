"""Lost Parts from Rebrickable (#457): the user's Lost Parts list becomes missing marks on the matching copy, as part of a Rebrickable pull.

Rebrickable records a lost part against a set, not a copy. A set with exactly one live copy here is applied automatically; with several the
plan lists that set's lost parts and the person picks the copy. A lost part is matched to a part line of the copy by part and colour through the
Rebrickable numbers the collection knows for the line's item and colour (a Rebrickable-born item or colour is its own number, a local BrickLink
one counts through a confirmed Rebrickable link), so a copy on BrickLink's part list matches too. What cannot be matched is listed with the reason.

Which count is kept is the setting `rebrickable_lost_parts_rule` (`RULES`). Nothing is cleared when the list was not read whole: a failed read or
any row that could not be read turns clearing off for that run, so a changed reply can never wipe the marks. The marks are written by
`checker.mark` (one `part_check` receipt per copy, the derived completeness follows); the pull's receipt keeps those event ids and its Undo
takes every one of them back."""
import json

from .. import checker, wishlists

KEY = 'rebrickable_lost_parts_rule'
DEFAULT_RULE = 'per_part'
# (value, label, one line) in the order Settings shows them.
RULES = (
    ('add_only', 'Add only', 'The sync only adds missing marks. Where both sides have a count, the larger is kept. Nothing is cleared.'),
    ('per_part', 'Rebrickable wins per part',
     "For a part Rebrickable lists as lost, Rebrickable's count replaces yours, also when it is smaller. Marks on other parts stay."),
    ('per_set', 'Rebrickable wins per set',
     "A set with at least one Lost Part on Rebrickable becomes exactly Rebrickable's list. Other missing marks on that copy are cleared."),
    ('everything', 'Rebrickable wins everywhere',
     "Every synced set becomes exactly Rebrickable's list. A set with no Lost Parts there loses its missing marks."))
RULE_VALUES = tuple(r[0] for r in RULES)
RULE_LABELS = {r[0]: r[1] for r in RULES}
RULE_NOTES = {r[0]: r[2] for r in RULES}


def valid_rule(value):
    """The rule named by `value`, or ValueError naming the four."""
    if value not in RULE_VALUES:
        raise ValueError('Choose add_only, per_part, per_set or everything for ' + KEY)
    return value


def rule(db):
    """The rule in force: the stored value when it is one of the four, else the default (an unknown stored value reads as the default)."""
    row = db.execute('SELECT value FROM main.setting WHERE key=?', (KEY,)).fetchone()
    return row[0] if row and row[0] in RULE_VALUES else DEFAULT_RULE


# Matching -------------------------------------------------------------------------------------

def _copies(db, item_ids):
    """`{item id: [copy row, ...]}` of the live copies, oldest first."""
    packed = json.dumps(sorted(set(item_ids)))
    found = {}
    for r in db.execute('''SELECT c.id, c.item_id, c.condition, c.completeness, c.note, c.created_at,
                                  (SELECT coalesce(sum(missing), 0) FROM main.copy_part p WHERE p.copy_id=c.id AND p.retired_at IS NULL) AS missing
                           FROM main.copy c WHERE c.archived_at IS NULL AND c.item_id IN (SELECT value FROM json_each(?)) ORDER BY c.created_at, c.id''', (packed,)):
        found.setdefault(r['item_id'], []).append(dict(r))
    return found


def copy_label(copy):
    """One line that tells copies of a set apart in the chooser."""
    words = [{'new': 'New', 'used': 'Used'}.get(copy['condition'], 'Condition not set'),
             {'sealed': 'sealed', 'complete': 'complete', 'incomplete': 'incomplete'}.get(copy['completeness'], 'completeness not set'),
             f"{copy['missing']} missing", 'added ' + str(copy['created_at'])[:10]]
    if copy.get('note'):
        words.append(str(copy['note'])[:40])
    return ' · '.join(words)


def _lines(db, copy_id):
    """The copy's live set lines (a figure's own parts are not Rebrickable's set lines) and the Rebrickable numbers of their items and colours."""
    lines = [dict(r) for r in db.execute('''SELECT id, item_id, color_id, is_spare, quantity, missing FROM main.copy_part
                                            WHERE copy_id=? AND copy_figure_id IS NULL AND retired_at IS NULL ORDER BY id''', (copy_id,))]
    numbers = wishlists._rebrickable_numbers(db, {l['item_id'] for l in lines})
    colours = wishlists._rebrickable_colours(db, {l['color_id'] for l in lines})
    index = {}
    for line in lines:
        for part_no in numbers.get(line['item_id'], ()):
            for colour in colours.get(line['color_id'], ()):
                index.setdefault((part_no, str(colour), bool(line['is_spare'])), []).append(line)
    return lines, index


def changes(db, copy_id, rows, how, *, clear_set=False):
    """What the rule does to one copy, from the set's lost rows `rows` (may be empty): `dict(edits, added, replaced, cleared, unmatched, same,
    not_cleared)`. `edits` is `[(token, fields)]` for `checker.mark`; `added`/`replaced`/`cleared` are lists of `dict(part_no, color_id,
    is_spare, before, after)`; `unmatched` lists `dict(part_no, color_id, is_spare, quantity, reason)`. `how` is the rule that applies (a rule
    that clears is passed as `per_part` when clearing is off). `clear_set` is true when the rule clears this set's other marks. A set with an
    unmatched lost part is not cleared (`not_cleared` says so): the line it names may be one that is marked here."""
    lines, index = _lines(db, copy_id)
    out = dict(edits=[], trail=[], added=[], replaced=[], cleared=[], unmatched=[], same=0, not_cleared=None)
    listed = set()

    def record(bucket, line, part_no, colour, after):
        out[bucket].append(dict(part_no=part_no, color_id=colour, is_spare=bool(line['is_spare']), before=line['missing'], after=after))
        out['edits'].append(('p:%d' % line['id'], dict(missing=after, checked=True) if after else dict(missing=0)))
        out['trail'].append(['p:%d' % line['id'], line['missing'], after])
    # An item can have several Rebrickable numbers, so two lost rows can name one line: they are one lost count on that line, never two edits.
    resolved = {}
    for row in rows:
        key = (row['part_no'], str(row['color_id']), bool(row['is_spare']))
        found = index.get(key, [])
        shown = dict(part_no=row['part_no'], color_id=row['color_id'], is_spare=bool(row['is_spare']), quantity=row['quantity'])
        if not found:
            out['unmatched'].append(dict(shown, reason='No line for this ' + ('spare ' if row['is_spare'] else '') + 'part in this colour on the copy'))
            continue
        if len({l['id'] for l in found}) > 1:
            out['unmatched'].append(dict(shown, reason='Several lines of the copy match this part and colour'))
            continue
        line = found[0]
        if line['id'] in resolved:
            resolved[line['id']][1]['quantity'] += row['quantity']
        else:
            resolved[line['id']] = (line, dict(row))
    for line, row in resolved.values():
        shown = dict(part_no=row['part_no'], color_id=row['color_id'], is_spare=bool(row['is_spare']), quantity=row['quantity'])
        listed.add(line['id'])
        if row['quantity'] > line['quantity']:
            out['unmatched'].append(dict(shown, reason=f"Rebrickable lost {row['quantity']} but the copy's line holds {line['quantity']}"))
            continue
        want = max(line['missing'], row['quantity']) if how == 'add_only' else row['quantity']
        if want == line['missing']:
            out['same'] += 1
        elif line['missing'] == 0:
            record('added', line, row['part_no'], row['color_id'], want)
        else:
            record('replaced', line, row['part_no'], row['color_id'], want)
    if clear_set:
        if out['unmatched']:
            out['not_cleared'] = 'Nothing was cleared on this copy because %d lost %s could not be matched' % (
                len(out['unmatched']), 'part' if len(out['unmatched']) == 1 else 'parts')
        else:
            numbers = wishlists._rebrickable_numbers(db, {l['item_id'] for l in lines})
            for line in lines:
                if line['id'] not in listed and line['missing'] > 0:
                    part_no = sorted(numbers.get(line['item_id'], {''}))[0]
                    out['cleared'].append(dict(part_no=part_no, color_id=None, is_spare=bool(line['is_spare']), before=line['missing'], after=0))
                    out['edits'].append(('p:%d' % line['id'], dict(missing=0)))
                    out['trail'].append(['p:%d' % line['id'], line['missing'], 0])
    return out


def fingerprint(result):
    """The edits of one `changes` result as plain data, `[line token, missing before, missing after]`: the plan keeps it, and the apply writes a copy only when the copy still gives the same
    edits, so a mark made after the preview is never cleared by a pull that did not show it."""
    return sorted(result['trail'])


def short(result):
    """The numbers of one `changes` result."""
    return dict(added=len(result['added']), replaced=len(result['replaced']), cleared=len(result['cleared']),
                cleared_pieces=sum(c['before'] for c in result['cleared']), unmatched=len(result['unmatched']), same=result['same'])


def clears(how, has_rows):
    """Whether the rule `how` clears the other marks of a set that has (`has_rows`) or has no Lost Parts on Rebrickable."""
    return how == 'everything' or (how == 'per_set' and has_rows)


# The plan ---------------------------------------------------------------------------------------

def by_set(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row['set_no'], []).append(row)
    return grouped


def plan_section(db, read, owned_numbers, translate, *, how, on):
    """The `lost` part of a pull plan. `read` is the adapter's answer (`dict(rows, unreadable)`) or the reason it failed (text), None when off;
    `owned_numbers` are the synced owned set numbers (what the everything rule works on); `translate` maps set numbers to item ids."""
    section = dict(on=on, rule=how, status='off', message=None, unreadable=0, rows=[], sets=[], unmatched_sets=[], clearing=True,
                   summary=dict(sets=0, added=0, replaced=0, cleared=0, cleared_pieces=0, unmatched=0, pick=0, unreadable=0))
    if not on:
        return section
    if not isinstance(read, dict):
        section.update(status='failed', message='Lost Parts were not read: ' + (read or 'no answer') + '. Nothing was changed for them.', clearing=False)
        return section
    rows = read['rows']
    section.update(status='read', rows=rows, unreadable=read['unreadable'])
    if read['unreadable']:
        section['clearing'] = False
        section['message'] = '%d %s could not be read, so nothing is cleared this time.' % (
            read['unreadable'], 'Lost Parts row' if read['unreadable'] == 1 else 'Lost Parts rows')
    effective = how if section['clearing'] else ('per_part' if how in ('per_set', 'everything') else how)
    grouped = by_set(rows)
    numbers = set(grouped) | (set(owned_numbers) if effective == 'everything' else set())
    mapping = translate(db, numbers)
    copies = _copies(db, [i for i in mapping.values() if i])
    summary = section['summary']
    summary['unreadable'] = read['unreadable']
    for number in sorted(numbers):
        mine = grouped.get(number, [])
        item = mapping.get(number)
        if item is None:
            if mine:
                section['unmatched_sets'].append(dict(set_no=number, parts=len(mine), pieces=sum(r['quantity'] for r in mine),
                                                      reason='No unique set in Brick Work for this number'))
                summary['unmatched'] += len(mine)
            continue
        held = copies.get(item, [])
        if not held:
            if mine:
                section['unmatched_sets'].append(dict(set_no=number, parts=len(mine), pieces=sum(r['quantity'] for r in mine),
                                                      reason='No copy of this set in the collection yet. Pull its copy first, then sync again'))
                summary['unmatched'] += len(mine)
            continue
        entry = dict(set_no=number, item_id=item, parts=len(mine), pieces=sum(r['quantity'] for r in mine),
                     copies=[dict(id=c['id'], label=copy_label(c)) for c in held], copy_id=None, state='ready', preview=None)
        if len(held) > 1:
            if not mine and not any(c['missing'] for c in held):
                continue                                    # nothing to choose a copy for
            entry['state'] = 'pick'
            entry['lost'] = [dict(part_no=r['part_no'], color_id=r['color_id'], quantity=r['quantity'], is_spare=r['is_spare']) for r in mine]
            summary['pick'] += 1
            # What choosing each copy would do, so the chooser says what it clears before the pull and the apply can tell a changed copy.
            entry['previews'] = {}
            for c, shown_copy in zip(held, entry['copies']):
                result = changes(db, c['id'], mine, effective, clear_set=clears(effective, bool(mine)))
                entry['previews'][c['id']] = dict(short(result), fingerprint=fingerprint(result))
                words = [w for w in ('adds %d' % len(result['added']) if result['added'] else '',
                                     'replaces %d' % len(result['replaced']) if result['replaced'] else '',
                                     'clears %d %s' % (len(result['cleared']), 'mark' if len(result['cleared']) == 1 else 'marks') if result['cleared'] else '',
                                     '%d not matched' % len(result['unmatched']) if result['unmatched'] else '') if w]
                shown_copy['effect'] = ', '.join(words) or 'no change'
        else:
            entry['copy_id'] = held[0]['id']
            result = changes(db, held[0]['id'], mine, effective, clear_set=clears(effective, bool(mine)))
            nothing = not (result['added'] or result['replaced'] or result['cleared'] or result['unmatched'])
            if nothing:
                continue
            entry['preview'] = dict(short(result), fingerprint=fingerprint(result), unmatched_list=result['unmatched'], not_cleared=result['not_cleared'],
                                    parts=result['added'] + result['replaced'], cleared_list=result['cleared'])
            for name in ('added', 'replaced', 'cleared', 'cleared_pieces', 'unmatched'):
                summary[name] += entry['preview'][name]
        section['sets'].append(entry)
    summary['sets'] = len(section['sets'])
    return section


# The apply --------------------------------------------------------------------------------------

def apply(db, section, ticked, picks, *, new_copies=()):
    """Write the ticked sets' marks inside the open pull transaction. `ticked` is the list of set numbers (None: every set that has a copy to
    use), `picks` maps a set number to the chosen copy id. Returns `dict(events, sets, added, replaced, cleared, unmatched, left_out)`; `events`
    are the `part_check` receipts the pull's Undo takes back. Everything is recomputed against what the collection holds now, with the rule
    the plan froze. A copy this pull just made is never written."""
    from .. import errors
    report = dict(events=[], sets=[], added=0, replaced=0, cleared=0, unmatched=[], left_out=[], skipped=[])
    if section.get('status') != 'read':
        return report
    how = section['rule'] if section['clearing'] else ('per_part' if section['rule'] in ('per_set', 'everything') else section['rule'])
    picks = picks or {}
    if not isinstance(picks, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in picks.items()):
        raise errors.ValidationFailed('Send the copy picks as {set number: copy id}')
    wanted = {s['set_no']: s for s in section['sets']}
    if ticked is not None:
        if not isinstance(ticked, list) or any(not isinstance(k, str) for k in ticked):
            raise errors.ValidationFailed('Send the ticked Lost Parts sets as a list of set numbers')
    unknown = (set(ticked or ()) | set(picks)) - set(wanted)
    if unknown:
        raise errors.ValidationFailed('Unknown Lost Parts sets: ' + ', '.join(sorted(unknown)[:5]))
    grouped = by_set(section['rows'])
    for number, entry in wanted.items():
        if ticked is not None and entry['state'] != 'pick' and number not in ticked:
            continue                                        # a set with several copies has no tick: its pick (or none) says
        held = [c for c in _copies(db, [entry['item_id']]).get(entry['item_id'], []) if c['id'] not in new_copies]
        ids = [c['id'] for c in held]
        if entry['state'] == 'pick':
            copy_id = picks.get(number)
            if not copy_id:
                report['left_out'].append(dict(set_no=number, parts=entry['parts'], reason='Choose a copy'))
                continue
            if copy_id not in ids:
                raise errors.ValidationFailed('That is not a copy of set ' + number)
        else:
            if ids != [entry['copy_id']]:
                report['skipped'].append(dict(set_no=number, reason='The copies of this set changed since the plan was made'))
                continue
            copy_id = entry['copy_id']
        mine = grouped.get(number, [])
        result = changes(db, copy_id, mine, how, clear_set=clears(how, bool(mine)))
        previewed = (entry.get('previews') or {}).get(copy_id) if entry['state'] == 'pick' else entry.get('preview')
        if previewed is not None and 'fingerprint' in previewed and [list(e) for e in previewed['fingerprint']] != fingerprint(result):
            report['skipped'].append(dict(set_no=number, reason='The missing parts of this copy changed since the preview. Preview the pull again'))
            continue
        report['unmatched'] += [dict(u, set_no=number) for u in result['unmatched']]
        if result['edits']:
            report['events'].append(checker.mark(db, copy_id, result['edits']))
        counted = short(result)
        report['sets'].append(dict(set_no=number, copy_id=copy_id, **counted, not_cleared=result['not_cleared']))
        for name in ('added', 'replaced', 'cleared'):
            report[name] += counted[name]
    return report
