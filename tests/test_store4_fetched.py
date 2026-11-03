"""Fetched part lists, local items and colours, and the shared inventory digest (design 2.4, 3.1, 3.2, 4.1, 6.3)."""
from contextlib import closing
import hashlib
import sqlite3

import pytest

from brickwork.store4 import fetched, identity
from brickwork.store4.audit import Events
from brickwork.store4.bldigest import inventory_digest
from brickwork.store4.connect import connect
from brickwork.store4.errors import Store4Error
from tests.store4_dump import default
from tests.store4_fixtures import pair
from tests.test_store4_builder import activated, rows, run

LOCAL = 1_000_000_000


@pytest.fixture
def db(tmp_path):
    col, cat = pair(tmp_path)
    with closing(connect(col, cat)) as conn:
        for item in (10, 11, 16):                               # a set and two parts
            identity.project(conn, item)
        identity.project_color(conn, 3)
        identity.project_color(conn, 4)
        conn.commit()
        yield conn


def old_digest(parts, figs=(), sets=()):
    """The formula the builder used before the shared function existed."""
    lines = sorted([('p', *l) for l in parts] + [('f', i, 0, 0, q) for i, q in figs] + [('s', i, 0, 0, q) for i, q in sets])
    return hashlib.sha256(repr(lines).encode()).hexdigest()


def test_digest_is_the_old_builder_formula():
    parts, figs, sets = [(5, 3, 0, 2), (4, 3, 1, 1), (4, 2, 0, 7)], [(9, 2), (8, 1)], [(3, 1)]
    assert inventory_digest(parts, figs, sets) == old_digest(parts, figs, sets)
    assert inventory_digest(parts) == old_digest(parts) and inventory_digest([]) == old_digest([])
    assert inventory_digest(reversed(parts), figs, sets) == inventory_digest(parts, figs, sets)


def test_builder_digests_match_the_old_formula(tmp_path):
    _, cat = run(tmp_path)
    with closing(sqlite3.connect(f'file:{cat}?mode=ro', uri=True)) as c:
        found = c.execute('SELECT id, digest, part_lines, figure_lines, set_lines FROM inventory').fetchall()
        assert found
        for inv, digest, npart, nfig, nset in found:
            parts = c.execute('SELECT item_id, color_id, is_spare, quantity FROM inventory_part WHERE inventory_id=?', (inv,)).fetchall()
            figs = c.execute('SELECT item_id, quantity FROM inventory_figure WHERE inventory_id=?', (inv,)).fetchall()
            sets = c.execute('SELECT item_id, quantity FROM inventory_set WHERE inventory_id=?', (inv,)).fetchall()
            assert digest == old_digest(parts, figs, sets)
            assert (npart, nfig, nset) == (len(parts), len(figs), len(sets))
    assert any(r[4] for r in found) and any(r[3] for r in found)     # figure and set lines were exercised


def test_digest_of_a_fetched_list_equals_the_catalogue_version(tmp_path):
    _, cat = run(tmp_path)
    col = activated(tmp_path, cat, ref_keys=('6081-1',))
    with closing(connect(col, cat)) as db:
        item = db.execute("SELECT id FROM catalogue.item WHERE born_key='6081-1'").fetchone()[0]
        inv = db.execute('SELECT id, digest FROM catalogue.inventory WHERE item_id=? AND version=1', (item,)).fetchone()
        parts = db.execute('SELECT item_id, color_id, is_spare, quantity FROM catalogue.inventory_part WHERE inventory_id=?', (inv[0],)).fetchall()
        figs = db.execute('SELECT item_id, quantity FROM catalogue.inventory_figure WHERE inventory_id=?', (inv[0],)).fetchall()
        for p in {p[0] for p in parts}:
            identity.project(db, p)
        for f in {f[0] for f in figs}:
            identity.project(db, f)
        for c in {p[1] for p in parts}:
            identity.project_color(db, c)
        fid = fetched.write_fetched(db, item, 'rebrickable_api', [tuple(p) for p in parts], [tuple(f) for f in figs])
        assert db.execute('SELECT digest FROM main.fetched_inventory WHERE id=?', (fid,)).fetchone()[0] == inv[1]


def test_seq_and_latest_across_two_fetches(db):
    first = fetched.write_fetched(db, 10, 'bricklink', [(11, 3, 0, 2)])
    other = fetched.write_fetched(db, 10, 'rebrickable_api', [(11, 3, 0, 2)])
    second = fetched.write_fetched(db, 10, 'bricklink', [(11, 3, 0, 3)], provider_version=4)
    got = {r['id']: r for r in db.execute('SELECT * FROM main.fetched_inventory')}
    assert (got[first]['seq'], got[first]['is_latest']) == (1, 0)
    assert (got[second]['seq'], got[second]['is_latest'], got[second]['provider_version']) == (2, 1, 4)
    assert (got[other]['seq'], got[other]['is_latest']) == (1, 1)                  # another source is its own sequence
    assert db.execute('SELECT quantity FROM main.fetched_inventory_part WHERE fetched_inventory_id=?', (first,)).fetchone()[0] == 2
    assert got[first]['digest'] == got[other]['digest'] != got[second]['digest']


def test_duplicate_keys_are_summed_and_counted(db):
    fig = fetched.create_local_item(db, kind='minifigure', born_provider='bricklink', born_namespace='M', born_key='sw0001', name='Figure')
    fid = fetched.write_fetched(db, 10, 'bricklink', [(11, 3, 0, 2), (11, 3, 0, 5), (11, 3, 1, 1), (16, 4, False, 1)],
                                [(fig, 1), (fig, 2)])
    assert sorted(tuple(r) for r in db.execute('SELECT item_id, color_id, is_spare, quantity FROM main.fetched_inventory_part')) == \
        [(11, 3, 0, 7), (11, 3, 1, 1), (16, 4, 0, 1)]
    assert tuple(db.execute('SELECT item_id, quantity FROM main.fetched_inventory_figure').fetchone()) == (fig, 3)
    r = db.execute('SELECT digest, part_lines, figure_lines FROM main.fetched_inventory WHERE id=?', (fid,)).fetchone()
    assert (r['part_lines'], r['figure_lines']) == (3, 1)
    assert r['digest'] == old_digest([(11, 3, 0, 7), (11, 3, 1, 1), (16, 4, 0, 1)], [(fig, 3)])


@pytest.mark.parametrize('parts, figs', [([], []), ([(11, 3, 0, 0)], []), ([(11, 3, 0, -1)], []), ([(11, 3, 0, 1.5)], []),
                                         ([(11, 3, 0, True)], []), ([(11, 3, 0, 1)], [(10, 0)]),
                                         ([(999, 3, 0, 1)], []), ([(11, 999, 0, 1)], [])])
def test_refused_lists_leave_nothing(db, parts, figs):
    with pytest.raises(Store4Error):
        fetched.write_fetched(db, 10, 'bricklink', parts, figs)
    assert db.execute('SELECT count(*) FROM main.fetched_inventory').fetchone()[0] == 0


def test_unknown_owner_is_named(db):
    with pytest.raises(Store4Error, match='item 4242'):
        fetched.write_fetched(db, 4242, 'bricklink', [(11, 3, 0, 1)])
    with pytest.raises(Store4Error, match='colour 999'):
        fetched.write_fetched(db, 10, 'bricklink', [(11, 999, 0, 1)])


def test_schema_kind_triggers_refuse_wrong_kinds(db):
    first = fetched.write_fetched(db, 10, 'bricklink', [(11, 3, 0, 1)])
    with pytest.raises(sqlite3.IntegrityError):
        fetched.write_fetched(db, 11, 'bricklink', [(11, 3, 0, 1)])                # a part owns no list
    with pytest.raises(sqlite3.IntegrityError):
        fetched.write_fetched(db, 10, 'bricklink', [(10, 3, 0, 1)])                # a set is no part line
    with pytest.raises(sqlite3.IntegrityError):
        fetched.write_fetched(db, 10, 'bricklink', [(11, 3, 0, 1)], [(11, 1)])     # a part is no figure line
    # the failed attempts did not clear the latest flag of the stored list
    assert [tuple(r) for r in db.execute('SELECT id, seq, is_latest FROM main.fetched_inventory')] == [(first, 1, 1)]


def test_local_ids_start_at_the_base_and_run(db):
    a = fetched.create_local_item(db, kind='set', born_provider='rebrickable', born_namespace='sets', born_key='9000-1', name='A', year=2026)
    b = fetched.create_local_item(db, kind='part', born_provider='bricklink', born_namespace='P', born_key='x1', name='B')
    assert (a, b) == (LOCAL, LOCAL + 1)
    row = db.execute('SELECT * FROM main.item WHERE id=?', (a,)).fetchone()
    assert (row['origin'], row['kind_source'], row['year'], row['name']) == ('local', 'namespace', 2026, 'A')
    c1 = fetched.create_local_color(db, bricklink_key=200, name='Neon')
    c2 = fetched.create_local_color(db, bricklink_key=201, name='Neon 2')
    assert (c1, c2) == (LOCAL, LOCAL + 1)
    assert tuple(db.execute('SELECT origin, born_provider, born_key, is_trans FROM main.color WHERE id=?', (c1,)).fetchone()) == ('local', 'bricklink', '200', 0)
    assert tuple(db.execute('SELECT provider, provider_key, status, method, inverse_preferred FROM main.color_link WHERE color_id=?', (c1,)).fetchone()) == \
        ('bricklink', '200', 'matched', 'bricklink_api', 1)


def test_local_writers_are_idempotent(db):
    a = fetched.create_local_item(db, kind='set', born_provider='rebrickable', born_namespace='sets', born_key='9000-1', name='A')
    assert fetched.create_local_item(db, kind='set', born_provider='rebrickable', born_namespace='sets', born_key='9000-1', name='other') == a
    with pytest.raises(Store4Error):
        fetched.create_local_item(db, kind='part', born_provider='rebrickable', born_namespace='sets', born_key='9000-1', name='A')
    unidentified = dict(kind='set', born_provider=None, born_namespace=None, born_key=None, name='typed', kind_source='manual')
    u1 = fetched.create_local_item(db, **unidentified)
    assert fetched.create_local_item(db, **unidentified) != u1        # no born key: never the same item
    c = fetched.create_local_color(db, bricklink_key='200', name='Neon')
    assert fetched.create_local_color(db, bricklink_key=200, name='Neon') == c
    assert db.execute('SELECT count(*) FROM main.color_link WHERE color_id=?', (c,)).fetchone()[0] == 1
    kw = dict(provider='bricklink', provider_kind='S', provider_key='9000-1', status='matched', method='bricklink_api', origin='api')
    link = fetched.add_item_link(db, a, **kw)
    assert fetched.add_item_link(db, a, **kw) == link
    assert db.execute('SELECT count(*) FROM main.item_link WHERE item_id=?', (a,)).fetchone()[0] == 1
    r1 = fetched.store_source_record(db, source='bricklink', kind='subsets', key='9000-1', payload={'b': 1, 'a': [2]})
    assert fetched.store_source_record(db, source='bricklink', kind='subsets', key='9000-1', payload='{"a": [2], "b": 1}') == r1
    r2 = fetched.store_source_record(db, source='bricklink', kind='subsets', key='9000-1', payload={'a': 3})
    assert r2 != r1
    rec = db.execute('SELECT * FROM main.source_record WHERE id=?', (r1,)).fetchone()
    assert (rec['payload'], rec['bytes'], rec['status'], rec['digest']) == \
        ('{"a": [2], "b": 1}', 18, 'ok', hashlib.sha256(b'{"a": [2], "b": 1}').hexdigest())


def test_a_local_colour_may_not_steal_a_held_bricklink_key(db):
    with pytest.raises(Store4Error, match='BrickLink colour 5'):
        fetched.create_local_color(db, bricklink_key=5, name='Red again')              # colour 3 holds BrickLink 5


def test_link_status_is_never_downgraded(db):
    base = dict(provider='bricklink', provider_kind='S', provider_key='6081-1', method='m', origin='api')
    manual = db.execute("SELECT id FROM main.item_link WHERE item_id=10 AND provider_key='6081-1'").fetchone()[0]
    assert fetched.add_item_link(db, 10, status='to_check', **base) == manual
    assert db.execute('SELECT status, origin FROM main.item_link WHERE id=?', (manual,)).fetchone()[:] == ('matched', 'shipped')
    cand = fetched.add_item_link(db, 10, status='to_check', **dict(base, provider_key='6081-2'))
    assert fetched.add_item_link(db, 10, status='to_check', **dict(base, provider_key='6081-2')) == cand
    up = fetched.add_item_link(db, 10, status='matched', **dict(base, provider_key='6081-2', method='bricklink_api'))
    assert up == cand and db.execute('SELECT status, method FROM main.item_link WHERE id=?', (cand,)).fetchone()[:] == ('matched', 'bricklink_api')
    assert fetched.add_item_link(db, 10, status='to_check', **dict(base, provider_key='6081-2')) == cand
    assert db.execute('SELECT status FROM main.item_link WHERE id=?', (cand,)).fetchone()[0] == 'matched'
    scoped = fetched.add_item_link(db, 10, color_id=3, status='to_check', evidence={'why': 'x'}, **base)
    assert scoped != manual and db.execute('SELECT evidence_json FROM main.item_link WHERE id=?', (scoped,)).fetchone()[0] == '{"why": "x"}'


def test_catalogue_held_key_is_refused_but_a_projected_item_is_returned(db):
    with pytest.raises(Store4Error, match='catalogue holds'):
        fetched.create_local_item(db, kind='part', born_provider='rebrickable', born_namespace='parts', born_key='970c03', name='Hips')
    assert fetched.create_local_item(db, kind='set', born_provider='rebrickable', born_namespace='sets', born_key='6081-1', name='x') == 10
    assert db.execute("SELECT count(*) FROM main.item WHERE origin='local'").fetchone()[0] == 0


def test_a_merged_local_item_is_followed(db):
    a = fetched.create_local_item(db, kind='set', born_provider='rebrickable', born_namespace='sets', born_key='9000-1', name='A')
    db.execute('UPDATE main.item SET merged_into=10 WHERE id=?', (a,))
    assert fetched.create_local_item(db, kind='set', born_provider='rebrickable', born_namespace='sets', born_key='9000-1', name='A') == 10
    with pytest.raises(Store4Error):
        fetched.create_local_item(db, kind='part', born_provider='rebrickable', born_namespace='sets', born_key='9000-1', name='A')


def test_a_rollback_undoes_the_whole_fetch(db):
    ev = Events(db, 'api', 'test')
    db.commit()
    db.execute('BEGIN')
    item = fetched.create_local_item(db, kind='set', born_provider='rebrickable', born_namespace='sets', born_key='9000-1', name='A', events=ev)
    col = fetched.create_local_color(db, bricklink_key=200, name='Neon', events=ev)
    part = fetched.create_local_item(db, kind='part', born_provider='bricklink', born_namespace='P', born_key='x1', name='P')
    fetched.add_item_link(db, item, provider='bricklink', provider_kind='S', provider_key='9000-1', status='matched', method='bricklink_api',
                          origin='api', events=ev)
    rec = fetched.store_source_record(db, source='bricklink', kind='subsets', key='9000-1', payload={'a': 1})
    fetched.write_fetched(db, item, 'bricklink', [(part, col, 0, 1)], source_record_id=rec, events=ev)
    assert ev.count == 4
    db.rollback()
    for table in ('source_record', 'fetched_inventory', 'fetched_inventory_part', 'event'):
        assert db.execute(f'SELECT count(*) FROM main.{table}').fetchone()[0] == 0
    assert db.execute('SELECT count(*) FROM main.color WHERE id>=?', (LOCAL,)).fetchone()[0] == 0
    assert db.execute('SELECT count(*) FROM main.item WHERE id>=?', (LOCAL,)).fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM main.item_link WHERE provider_key='9000-1'").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM main.color_link WHERE provider_key='200'").fetchone()[0] == 0


def test_a_failed_write_inside_the_callers_transaction_rolls_back_only_itself(db):
    keep = fetched.write_fetched(db, 10, 'bricklink', [(11, 3, 0, 1)])
    with pytest.raises(sqlite3.IntegrityError):
        fetched.write_fetched(db, 10, 'bricklink', [(11, 3, 0, 1), (10, 3, 0, 1)])
    assert [tuple(r) for r in db.execute('SELECT id, seq, is_latest FROM main.fetched_inventory')] == [(keep, 1, 1)]
    db.commit()


def test_events_are_written_only_on_request(db):
    fetched.write_fetched(db, 10, 'bricklink', [(11, 3, 0, 1)])
    assert db.execute('SELECT count(*) FROM main.event').fetchone()[0] == 0
    ev = Events(db, 'api', 'tester')
    fid = fetched.write_fetched(db, 10, 'bricklink', [(11, 3, 0, 2)], events=ev)
    item = fetched.create_local_item(db, kind='set', born_provider='rebrickable', born_namespace='sets', born_key='9000-1', name='A', events=ev)
    fetched.create_local_color(db, bricklink_key=200, name='Neon', events=ev)
    link = fetched.add_item_link(db, item, provider='bricklink', provider_kind='S', provider_key='9000-1', status='to_check', method='m',
                                 origin='api', events=ev)
    got = [tuple(r) for r in db.execute('SELECT entity_kind, entity_id, field, via, actor FROM main.event ORDER BY id')]
    assert got == [('fetched_inventory', str(fid), 'created', 'api', 'tester'), ('item', str(item), 'created', 'api', 'tester'),
                   ('color', str(LOCAL), 'created', 'api', 'tester'), ('item_link', str(link), 'created', 'api', 'tester')]
    new = db.execute("SELECT new_value FROM main.event WHERE entity_kind='fetched_inventory'").fetchone()[0]
    assert new == ('{"digest": "%s", "figure_lines": 0, "item_id": 10, "part_lines": 1, "seq": 2, "source": "bricklink"}'
                   % inventory_digest([(11, 3, 0, 2)]))


def test_a_local_item_created_here_is_adopted_by_the_next_build(tmp_path):
    t = default()
    t['sets'] = [s for s in t['sets'] if s[0] != '9999-1']
    t['inventories'] = [i for i in t['inventories'] if i[2] != '9999-1']
    t['inventory_sets'] = []
    _, cat = run(tmp_path, **t)
    col = activated(tmp_path, cat)
    with closing(connect(col, cat)) as db:
        item = fetched.create_local_item(db, kind='set', born_provider='rebrickable', born_namespace='sets', born_key='9999-1', name='Fetched Set')
        part = identity.project(db, [r for r in db.execute("SELECT id FROM catalogue.item WHERE born_key='3023'")][0][0])
        identity.project_color(db, 4)
        fid = fetched.write_fetched(db, item, 'rebrickable_api', [(part, 4, 0, 2)])
        db.commit()
        assert item == LOCAL
    report, _ = run(tmp_path, 'd2', collection=col)                       # the new dump has 9999-1
    row = rows(cat, "SELECT id, adopted FROM item WHERE born_key='9999-1'")[0]
    assert (row['id'], row['adopted']) == (LOCAL, 1) and report['counts']['adopted'] == 1
    with closing(connect(col, cat)) as db:                                # the fetched list still hangs on the same id
        assert db.execute('SELECT item_id FROM main.fetched_inventory WHERE id=?', (fid,)).fetchone()[0] == LOCAL


def test_local_colour_refused_for_a_key_another_colour_owns(db):
    db.execute("UPDATE main.color_link SET inverse_preferred=0, status='manual' WHERE color_id=3 AND provider='bricklink'")
    for key in ('5', '1', '72'):                                # Red without the flag, unprojected White, the shared 72
        with pytest.raises(fetched.LocalItemError):
            fetched.create_local_color(db, bricklink_key=key, name='dup')
    assert db.execute("SELECT count(*) FROM main.color WHERE origin='local'").fetchone()[0] == 0


def test_a_failing_link_event_leaves_no_link(db):
    bad = Events(db, 'nowhere', 'test')                          # via fails the event table's CHECK
    with pytest.raises(sqlite3.IntegrityError):
        fetched.add_item_link(db, 11, provider='bricklink', provider_kind='P', provider_key='x9', status='to_check',
                              method='candidate', origin='api', events=bad)
    assert db.execute("SELECT count(*) FROM main.item_link WHERE provider_key='x9'").fetchone()[0] == 0
