"""#690 part 2: pull Brickset set notes and flags into Brick Work."""
from contextlib import closing
import json

import pytest

from brickwork.core import undo
from brickwork.core.connect import connect
from brickwork.core.sync import set_fields
from tests.app4 import Coll
from tests.test_bw_sync import EXTRA


@pytest.fixture
def pair(tmp_path):
    from tests.app4 import make_pair
    return make_pair(tmp_path, rich=True, extra_dump=EXTRA)


def db_of(pair):
    return closing(connect(pair))


def _copies(db, number):
    return db.execute(
        'SELECT c.id, c.note FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key=? AND c.archived_at IS NULL ORDER BY c.id',
        (number,),
    ).fetchall()


def _wishes(db, number, wish_list='default'):
    return db.execute(
        'SELECT w.id, w.note FROM wish w JOIN item i ON i.id=w.item_id '
        'WHERE w.wishlist_id=? AND i.born_key=? AND w.color_key=0 AND w.archived_at IS NULL ORDER BY w.id',
        (wish_list, number),
    ).fetchall()


def _copy_tags(db, copy_id):
    return db.execute(
        "SELECT f.id, f.name, f.kind, f.shown_on_grid FROM copy_flag cf JOIN flag f ON f.id=cf.flag_id WHERE cf.copy_id=? ORDER BY f.id",
        (copy_id,),
    ).fetchall()


def _wish_tags(db, wish_id):
    return db.execute(
        "SELECT f.id, f.name FROM wish_flag wf JOIN flag f ON f.id=wf.flag_id WHERE wf.wish_id=? ORDER BY f.id",
        (wish_id,),
    ).fetchall()


def test_note_add_on_one_copy_and_two_copies_without_truncation(pair):
    long_note = 'x' * 1200
    with db_of(pair) as db:
        coll = Coll(db)
        coll.add_copy('1000-1')
        coll.add_copy('1000-1')
        coll.add_copy('2070-1')
        p = set_fields.plan(db, {'1000-1': {'notes': 'boxed', 'flags': []}, '2070-1': {'notes': long_note, 'flags': []}}, {})
        assert len(p['rows']) == 3
        assert all(r['state'] == 'add' and r['tickable'] for r in p['rows'])
        res = set_fields.apply(db, p['id'])
        assert res['already_applied'] is False
        assert res['counts'] == {'notes': 3, 'flags': 0, 'tags_created': 0, 'renamed': 0}
        assert [r[1] for r in _copies(db, '1000-1')] == ['boxed', 'boxed']
        assert [r[1] for r in _copies(db, '2070-1')] == [long_note]


def test_conflict_keeps_by_default_takes_when_chosen_and_equal_note_gives_no_row(pair):
    with db_of(pair) as db:
        coll = Coll(db)
        coll.add_copy('1000-1')
        coll.add_copy('2070-1')
        c1 = _copies(db, '1000-1')[0][0]
        c2 = _copies(db, '2070-1')[0][0]
        db.execute('UPDATE copy SET note=? WHERE id=?', ('local note', c1))
        db.execute('UPDATE copy SET note=? WHERE id=?', ('same note', c2))
        db.commit()
        remote = {'1000-1': {'notes': 'remote note', 'flags': []}, '2070-1': {'notes': 'same note', 'flags': []}}
        p = set_fields.plan(db, remote, {})
        assert len(p['rows']) == 1
        row = p['rows'][0]
        assert row['key'] == f'note:copy:{c1}' and row['state'] == 'conflict'
        assert row['options'] == ['keep', 'take'] and row['default'] == 'keep'
        assert row['here'] == 'local note' and row['remote'] == 'remote note'
        res1 = set_fields.apply(db, p['id'])
        assert res1['counts']['notes'] == 0
        assert _copies(db, '1000-1')[0][1] == 'local note'
        p2 = set_fields.plan(db, remote, {})
        res2 = set_fields.apply(db, p2['id'], choices={row['key']: 'take'})
        assert res2['counts']['notes'] == 1
        assert _copies(db, '1000-1')[0][1] == 'remote note'


def test_wanted_only_set_uses_wish_and_untargeted_set_counts_in_not_kept(pair):
    with db_of(pair) as db:
        coll = Coll(db)
        coll.add_wish(coll.item('sets', '1000-2'), quantity=1)
        p = set_fields.plan(db, {
            '1000-2': {'notes': 'wish note', 'flags': [3]},
            '1000-3': {'notes': 'no target', 'flags': [1, 2]},
            '9999-1': {'notes': 'unknown set', 'flags': [1]},
        }, {3: 'Wanted'})
        assert p['unmatched'] == ['9999-1']
        assert p['not_kept'] == {'notes': 1, 'flags': 2}
        assert [r['table'] for r in p['rows']] == ['wish', 'wish']
        res = set_fields.apply(db, p['id'])
        assert res['counts'] == {'notes': 1, 'flags': 1, 'tags_created': 1, 'renamed': 0}
        w = _wishes(db, '1000-2')[0]
        assert w[1] == 'wish note'
        assert [t[1] for t in _wish_tags(db, w[0])] == ['Wanted']


def test_flags_fallback_and_label_two_flags_existing_skipped_and_apply_idempotent(pair):
    with db_of(pair) as db:
        Coll(db).add_copy('1000-1')
        cid = _copies(db, '1000-1')[0][0]
        remote = {'1000-1': {'notes': 'kept', 'flags': [2, 5]}}
        p = set_fields.plan(db, remote, {2: 'Display'})
        res = set_fields.apply(db, p['id'])
        assert res['already_applied'] is False
        assert res['counts'] == {'notes': 1, 'flags': 2, 'tags_created': 2, 'renamed': 0}
        tags = _copy_tags(db, cid)
        assert sorted((t[1], t[2], t[3]) for t in tags) == [('Brickset flag 5', 'tag', 0), ('Display', 'tag', 0)]
        events = db.execute('SELECT id, new_value FROM event WHERE field=?', (set_fields.FIELD,)).fetchall()
        assert len(events) == 1
        receipt = json.loads(events[0][1])
        assert receipt['plan'] == p['id']
        assert len(receipt['notes']) == 1 and len(receipt['links']) == 2 and len(receipt['tags_created']) == 2
        again = set_fields.apply(db, p['id'])
        assert again == {'event_id': res['event_id'], 'already_applied': True, 'counts': res['counts']}
        assert db.execute('SELECT count(*) FROM event WHERE field=?', (set_fields.FIELD,)).fetchone()[0] == 1
        p_next = set_fields.plan(db, remote, {2: 'Display'})
        assert p_next['rows'] == []


def test_undo_restores_notes_links_and_created_tags_and_blocks_if_note_changed(pair):
    with db_of(pair) as db:
        coll = Coll(db)
        coll.add_copy('1000-1')
        coll.add_copy('2070-1')
        c_empty = _copies(db, '1000-1')[0][0]
        c_orig = _copies(db, '2070-1')[0][0]
        db.execute('UPDATE copy SET note=? WHERE id=?', ('orig', c_orig))
        db.commit()
        p = set_fields.plan(db, {'1000-1': {'notes': 'added', 'flags': [1]}, '2070-1': {'notes': 'new', 'flags': []}}, {})
        res = set_fields.apply(db, p['id'], choices={f'note:copy:{c_orig}': 'take'})
        assert _copies(db, '1000-1')[0][1] == 'added' and _copies(db, '2070-1')[0][1] == 'new'
        undo_res = undo.undo_event(db, res['event_id'])
        assert _copies(db, '1000-1')[0][1] is None and _copies(db, '2070-1')[0][1] == 'orig'
        assert _copy_tags(db, c_empty) == []
        assert db.execute("SELECT 1 FROM flag WHERE kind='tag'").fetchone() is None
        assert db.execute('SELECT 1 FROM setting WHERE key=?', (set_fields.MAP_KEY,)).fetchone() is None
        undo_ev = db.execute('SELECT field, new_value FROM event WHERE id=?', (undo_res['undo_event_id'],)).fetchone()
        assert undo_ev[0] == 'undo' and json.loads(undo_ev[1]) == {'undoes': res['event_id']}

        p2 = set_fields.plan(db, {'1000-1': {'notes': 'pulled', 'flags': [2]}}, {})
        res2 = set_fields.apply(db, p2['id'])
        db.execute('UPDATE copy SET note=? WHERE id=?', ('edited later', c_empty))
        db.commit()
        with pytest.raises(ValueError, match='changed since'):
            undo.undo_event(db, res2['event_id'])
        assert _copies(db, '1000-1')[0][1] == 'edited later'
        assert [t[1] for t in _copy_tags(db, c_empty)] == ['Brickset flag 2']


def test_tag_reused_and_late_label_renames_fallback_once_leaving_user_renamed_alone(pair):
    with db_of(pair) as db:
        coll = Coll(db)
        coll.add_copy('1000-1')
        coll.add_copy('2070-1')
        coll.add_copy('1000-3')
        c1 = _copies(db, '1000-1')[0][0]
        c2 = _copies(db, '2070-1')[0][0]
        c3 = _copies(db, '1000-3')[0][0]

        p1 = set_fields.plan(db, {'1000-1': {'notes': '', 'flags': [4]}}, {})
        r1 = set_fields.apply(db, p1['id'])
        assert r1['counts'] == {'notes': 0, 'flags': 1, 'tags_created': 1, 'renamed': 0}

        p2 = set_fields.plan(db, {'2070-1': {'notes': '', 'flags': [4]}}, {})
        r2 = set_fields.apply(db, p2['id'])
        assert r2['counts'] == {'notes': 0, 'flags': 1, 'tags_created': 0, 'renamed': 0}
        assert _copy_tags(db, c1) == _copy_tags(db, c2)

        p3 = set_fields.plan(db, {'1000-1': {'notes': '', 'flags': [4]}}, {4: 'Built'})
        r3 = set_fields.apply(db, p3['id'])
        assert r3['counts']['renamed'] == 1
        assert [t[1] for t in _copy_tags(db, c1)] == ['Built']

        p4 = set_fields.plan(db, {'1000-1': {'notes': '', 'flags': [4]}}, {4: 'Renamed Again'})
        r4 = set_fields.apply(db, p4['id'])
        assert r4['counts']['renamed'] == 0
        assert [t[1] for t in _copy_tags(db, c1)] == ['Built']

        p5 = set_fields.plan(db, {'1000-3': {'notes': '', 'flags': [7]}}, {})
        set_fields.apply(db, p5['id'])
        fid7 = _copy_tags(db, c3)[0][0]
        db.execute('UPDATE flag SET name=? WHERE id=?', ('My Shelf', fid7))
        db.commit()
        p6 = set_fields.plan(db, {'1000-3': {'notes': '', 'flags': [7]}}, {7: 'Brickset Name'})
        r6 = set_fields.apply(db, p6['id'])
        assert r6['counts']['renamed'] == 0
        assert [t[1] for t in _copy_tags(db, c3)] == ['My Shelf']
