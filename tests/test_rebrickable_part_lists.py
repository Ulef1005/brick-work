"""#471: Rebrickable part lists into loose stock, pull only. The person chooses the lists; each lands in a lot of its own made at the first pull
and named after the list; the preview lists New there (ticked), Different and Only here by part and colour, and unmatched numbers with the
reason; one apply is one undoable step with the tag *imported from Rebrickable*, Added via Rebrickable and Last synced from per list; a second
pull with nothing changed lists nothing. Invented data against the fake Rebrickable of test_bw_sync."""
import json

import pytest

from brickwork.core import errors, stock, sync
from brickwork.core.sync import adapters, part_lists
from brickwork.core.transaction import transaction
from tests.test_bw_sync import Rebrickable, rebrickable_ready, store  # noqa: F401
from tests.test_bw_sync import pair  # noqa: F401


class WithParts(Rebrickable):
    """The fake Rebrickable with part lists: 31 'Bin A' and 32 'Bin B'."""

    def __init__(self):
        super().__init__()
        self.part_lists = {31: ('Bin A', [('3001', 4, 5), ('3023', 15, 2), ('99999', 4, 1), ('3001', 77777, 1)]), 32: ('Bin B', [('3001', 15, 3)])}

    def __call__(self, request):
        path = request.full_url.split('/api/v3/users/', 1)[-1].split('?')[0]
        parts = path.strip('/').split('/')[1:]
        if parts == ['partlists']:
            return {'count': len(self.part_lists), 'next': None, 'results': [
                {'id': i, 'name': name, 'num_parts': len(rows)} for i, (name, rows) in self.part_lists.items()]}
        if len(parts) == 3 and parts[0] == 'partlists' and parts[2] == 'parts':
            name, rows = self.part_lists[int(parts[1])]
            return {'count': len(rows), 'next': None, 'results': [
                {'quantity': q, 'part': {'part_num': p}, 'color': {'id': c}, 'element_id': None} for p, c, q in rows] + [{'broken': True}]}
        return super().__call__(request)


def ready(db, lists=(31,)):
    remote = rebrickable_ready(db, WithParts())
    sync.link(db, 'rebrickable', {'part_lists': list(lists)})
    return remote


def lot_rows(db, name):
    return {(r[0], r[1]): r[2] for r in db.execute('''SELECT i.born_key, c.born_key, s.quantity FROM stock s JOIN lot l ON l.id=s.lot_id
        JOIN item i ON i.id=s.item_id JOIN color c ON c.id=s.color_id WHERE l.name=? AND l.archived_at IS NULL AND s.archived_at IS NULL''', (name,))}


def test_nothing_is_chosen_by_default(store):
    rebrickable_ready(store, WithParts())
    assert part_lists.chosen(store) == []
    with pytest.raises(errors.ValidationFailed, match='Choose the Rebrickable part lists'):
        part_lists.plan(store, http=WithParts())
    for bad in ([0], ['31'], [31, 31]):
        with pytest.raises(errors.ValidationFailed):
            sync.link(store, 'rebrickable', {'part_lists': bad})


def test_the_preview_lists_new_rows_and_the_unmatched_with_the_reason(store):
    remote = ready(store)
    plan = part_lists.plan(store, http=remote)
    assert [(r['part_no'], r['color_no'], r['state'], r['count'], r['tickable']) for r in plan['rows']] == [('3001', 4, 'add', 5, True), ('3023', 15, 'add', 2, True)]
    assert sorted(u['reason'] for u in plan['unmatched']) == ['No colour with this Rebrickable id here', 'No part with this number here',
                                                              'Rebrickable sent a row that could not be read']
    assert plan['lists'] == [dict(id=31, name='Bin A', lot_id=None, new_lot=True)]


def test_apply_lands_in_one_lot_per_list_tagged_and_undo_takes_it_all_back(store):
    remote = ready(store, (31, 32))
    plan = part_lists.plan(store, http=remote)
    result = part_lists.apply(store, plan['id'])
    assert result['counts'] == dict(rows=3, pieces=10, lots_made=2)
    assert lot_rows(store, 'Bin A') == {('3001', '4'): 5, ('3023', '15'): 2} and lot_rows(store, 'Bin B') == {('3001', '15'): 3}
    rows = store.execute("SELECT id, added_via FROM stock WHERE archived_at IS NULL").fetchall()
    assert {r['added_via'] for r in rows} == {'rebrickable'}
    tags = {r[0] for r in store.execute('SELECT f.name FROM stock_flag s JOIN flag f ON f.id=s.flag_id')}
    assert tags == {'imported from Rebrickable'}
    assert {tuple(r) for r in store.execute('SELECT list_key, list_name FROM synced_from')} == {('part:31', 'Bin A'), ('part:32', 'Bin B')}
    assert part_lists.apply(store, plan['id'])['already_applied']
    sync.undo(store, result['event_id'])
    assert not store.execute('SELECT 1 FROM stock WHERE archived_at IS NULL').fetchone()
    assert not store.execute('SELECT 1 FROM lot WHERE archived_at IS NULL').fetchone()
    assert not store.execute('SELECT 1 FROM synced_from').fetchone() and not store.execute("SELECT 1 FROM flag WHERE name LIKE 'imported from%'").fetchone()
    assert sync._setting(store, 'rebrickable', 'link')['part_list_lots'] == {}


def test_a_second_pull_with_nothing_changed_lists_nothing_and_a_change_lists_only_it(store):
    remote = ready(store)
    part_lists.apply(store, part_lists.plan(store, http=remote)['id'])
    again = part_lists.plan(store, http=remote)
    assert again['rows'] == [] and again['lists'][0]['new_lot'] is False
    remote.part_lists[31] = ('Bin A', [('3001', 4, 7), ('3023', 15, 1)])
    rows = {(r['part_no'] or '', r['state'], r['count']) for r in part_lists.plan(store, http=remote)['rows']}
    assert rows == {('3001', 'add', 2), ('3023', 'differs', 0)}
    remote.part_lists[31] = ('Bin A', [('3001', 4, 5)])
    assert {r['state'] for r in part_lists.plan(store, http=remote)['rows']} == {'only_here'}


def test_unticked_rows_and_a_row_put_in_another_lot(store):
    remote = ready(store)
    plan = part_lists.plan(store, http=remote)
    keys = {r['part_no']: r['key'] for r in plan['rows']}
    with transaction(store):
        store.execute("INSERT INTO lot(id, name, created_at, updated_at) VALUES('mine', 'My drawer', 'x', 'x')")
    part_lists.apply(store, plan['id'], [keys['3001']], lots={keys['3001']: 'mine'})
    assert lot_rows(store, 'My drawer') == {('3001', '4'): 5} and not store.execute("SELECT 1 FROM lot WHERE name='Bin A'").fetchone()
    with pytest.raises(errors.ValidationFailed):
        part_lists.apply(store, part_lists.plan(store, http=remote)['id'], lots={'nope': 'mine'})


def test_undo_is_refused_once_the_stock_changed(store):
    remote = ready(store)
    result = part_lists.apply(store, part_lists.plan(store, http=remote)['id'])
    row = store.execute("SELECT id FROM stock WHERE archived_at IS NULL LIMIT 1").fetchone()[0]
    with transaction(store):
        store.execute("UPDATE stock SET note='mine now' WHERE id=?", (row,))
    with pytest.raises(Exception, match='changed since'):
        sync.undo(store, result['event_id'])


def test_the_row_parser_refuses_what_it_cannot_read():
    assert adapters.parse_part_list_row({'quantity': '3', 'part': {'part_num': '3001'}, 'color': {'id': '4'}}) == dict(part_no='3001', color_id=4, quantity=3)
    for bad in ({}, {'quantity': 0, 'part': {'part_num': '3001'}, 'color': {'id': 4}}, {'quantity': 1, 'part': {'part_num': '3001'}, 'color': {'id': 'red'}}):
        assert adapters.parse_part_list_row(bad) is None


def test_a_set_pull_keeps_part_list_synced_from_lines(store):
    remote = ready(store)
    part_lists.apply(store, part_lists.plan(store, http=remote)['id'])
    before = {tuple(r) for r in store.execute("SELECT stock_id, list_key, list_name FROM synced_from WHERE stock_id IS NOT NULL")}
    assert before and {r[1:] for r in before} == {('part:31', 'Bin A')}
    assert 'part:31' not in sync.origins.lists_of(store, 'rebrickable')
    set_plan = sync.plan_pull(store, 'rebrickable', http=remote)
    assert not any(line['key'].startswith('part:') for line in set_plan['lists']['preview'])
    sync.apply_pull(store, set_plan['id'])
    after = {tuple(r) for r in store.execute("SELECT stock_id, list_key, list_name FROM synced_from WHERE list_key='part:31'")}
    assert after == before


def test_undoing_one_pull_keeps_another_pulls_lot(store):
    remote = ready(store, (31,))
    first = part_lists.apply(store, part_lists.plan(store, http=remote)['id'])
    sync.link(store, 'rebrickable', {'part_lists': [31, 32]})
    part_lists.apply(store, part_lists.plan(store, http=remote)['id'])
    lots_before = dict(sync._setting(store, 'rebrickable', 'link')['part_list_lots'])
    assert set(lots_before) == {'31', '32'}
    sync.undo(store, first['event_id'])
    assert sync._setting(store, 'rebrickable', 'link')['part_list_lots'] == {'32': lots_before['32']}
    assert lot_rows(store, 'Bin B') == {('3001', '15'): 3}
    assert not store.execute("SELECT 1 FROM lot WHERE id=? AND archived_at IS NULL", (lots_before['31'],)).fetchone()


def test_rebrickable_colour_zero_keeps_color_no_zero(store):
    remote = ready(store)
    part_lists.apply(store, part_lists.plan(store, http=remote)['id'])
    lot_id = sync._setting(store, 'rebrickable', 'link')['part_list_lots']['31']
    item_id = store.execute("SELECT id FROM main.item WHERE born_key='3001'").fetchone()[0]
    black = store.execute("SELECT id FROM main.color WHERE born_provider='rebrickable' AND born_key='0'").fetchone()
    if black:
        black_id = black[0]
    else:
        sample = dict(store.execute("SELECT * FROM main.color WHERE born_provider='rebrickable' LIMIT 1").fetchone())
        sample['id'], sample['born_key'] = 990000, '0'
        if 'name' in sample:
            sample['name'] = 'Black (syn)'
        black_id = sample['id']
        with transaction(store):
            store.execute(f"INSERT INTO main.color({', '.join(sample)}) VALUES({','.join('?' * len(sample))})", tuple(sample.values()))
    with transaction(store):
        stock.add_loose(store, item_id=item_id, color_id=black_id, quantity=2, condition=None, lot_id=lot_id, via='cli', actor=None)
    row = next(r for r in part_lists.plan(store, http=remote)['rows'] if r['color_id'] == black_id)
    assert row['state'] == 'only_here' and row['color_no'] == 0


def test_row_parser_rejects_double_minus_colour_and_null_part_num():
    assert adapters.parse_part_list_row({'quantity': 1, 'part': {'part_num': '3001'}, 'color': {'id': '--4'}}) is None
    assert adapters.parse_part_list_row({'quantity': 1, 'part': {'part_num': None}, 'color': {'id': 4}}) is None
    assert adapters.parse_part_list_row({'quantity': 1, 'part': {'part_num': ''}, 'color': {'id': 4}}) is None


def test_link_rejects_falsy_non_list_part_lists(store):
    rebrickable_ready(store, WithParts())
    for bad in (False, 0, '', {}):
        with pytest.raises(errors.ValidationFailed):
            sync.link(store, 'rebrickable', {'part_lists': bad})
    sync.link(store, 'rebrickable', {'part_lists': None})
    assert part_lists.chosen(store) == []


def test_redirected_row_does_not_reappear_on_next_plan(store):
    remote = ready(store)
    plan = part_lists.plan(store, http=remote)
    keys = {r['part_no']: r['key'] for r in plan['rows']}
    with transaction(store):
        store.execute("INSERT INTO lot(id, name, created_at, updated_at) VALUES('mine', 'My drawer', 'x', 'x')")
    part_lists.apply(store, plan['id'], lots={keys['3001']: 'mine'})
    assert lot_rows(store, 'My drawer') == {('3001', '4'): 5} and lot_rows(store, 'Bin A') == {('3023', '15'): 2}
    assert part_lists.plan(store, http=remote)['rows'] == []
