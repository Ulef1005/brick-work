"""Activation and reconcile (M.2c): the id-stability probes end to end (design 12: A1, A2, A4), the link rules of 3.2, the
kinds of 3.5 and what is reported and never applied, with invented dumps and mapping files only."""
from contextlib import closing
import json
import sqlite3

import pytest

from brickwork.store4 import identity
from brickwork.store4.activate import activate
from brickwork.store4.builder import build
from brickwork.store4.connect import connect
from brickwork.store4.errors import CatalogueMismatch, NotActivated, Store4Error
from brickwork.store4.reconcile import reconcile
from tests.store4_dump import default, write_dump, write_mappings


def tables():
    """The invented dump with one more part, 3626, which the mapping links as a candidate to check."""
    t = default()
    t['parts'] = t['parts'] + [('3626', 'Minifig Head', '5', 'Plastic')]
    return t


STAMP = '2026-10-23T12:00:00.000Z'
COLORS = [('0', 'Black', 'bricklink', '11', 'Black', 0, 9), ('4', 'Red', 'bricklink', '5', 'Red', 0, 9), ('15', 'White', 'bricklink', '1', 'White', 0, 9)]


def part(num, key, status='matched', color='', kind='P', preferred=0):
    return (num, color, 'bricklink', kind, key, status, 'external_ids', preferred)


PARTS = [part('3023', '3023', 'inferred'), part('3001', '3001'), part('3626', 'x', 'to_check')]


def make(tmp_path, name='d1', *, links=PARTS, colours=COLORS, target=None, collection=None, **given):
    maps = write_mappings(tmp_path / f'maps-{name}', colors=colours, parts=links)
    dump = write_dump(tmp_path / name, **{**tables(), **given})
    target = target or tmp_path / 'catalogue.db'
    return build(dump, target, collection=collection, app_version='t', now=STAMP, mappings_dir=maps), target


def q(path, sql, *args):
    with closing(sqlite3.connect(f'file:{path}?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute(sql, args)]


def ids(path, table='item', key='born_key'):
    return {r[key]: r['id'] for r in q(path, f'SELECT id, {key} FROM {table}')}


class World:
    """A catalogue built from the invented dump, a collection that activated it and projected `keys`."""

    def __init__(self, tmp_path, keys=('6081-1', '3023', '3001'), **kw):
        self.tmp, self.kw = tmp_path, kw
        _, self.cat = make(tmp_path, **kw)
        self.col = tmp_path / 'brickwork.db'
        self.db = connect(self.col, self.cat)
        activate(self.db)
        for k in keys:
            identity.project(self.db, ids(self.cat)[k])
        self.db.commit()
        self.id = ids(self.cat)

    def edit_cat(self, *statements):
        """Change the catalogue file (the collection attaches it read-only) and attach it again."""
        self.db.close()
        with closing(sqlite3.connect(self.cat)) as c:
            for sql, *args in statements:
                c.execute(sql, args)
            c.commit()
        self.db = connect(self.col, self.cat)

    def sql(self, sql, *args):
        rows = [dict(r) for r in self.db.execute(sql, args).fetchall()]
        self.db.commit()
        return rows

    def reconcile(self, **kw):
        return reconcile(self.db, **kw)

    def events(self):
        return self.sql('SELECT * FROM event ORDER BY id')

    def link(self, key, kind='bricklink', item_key='3023'):
        return self.sql('SELECT * FROM item_link WHERE item_id=? AND provider=? AND provider_key=?', self.id[item_key], kind, key)[0]

    def close(self):
        self.db.close()


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    w.close()


# ---------- activation ----------

def test_activation_binds_copies_marks_projects_colours_and_writes_one_event(tmp_path):
    _, cat = make(tmp_path)
    with closing(connect(tmp_path / 'brickwork.db', cat)) as db:
        report = activate(db, actor='ulf')
        meta = dict(db.execute('SELECT key, value FROM main.meta').fetchall())
        cmeta = dict(db.execute('SELECT key, value FROM catalogue.meta').fetchall())
        assert meta['catalogue_id'] == cmeta['catalogue_id']
        assert meta['catalogue_item_high_water'] == cmeta['item_high_water'] == '12' and meta['catalogue_color_high_water'] == '6'
        builds = [dict(r) for r in db.execute('SELECT * FROM main.catalogue_build')]
        assert [(b['id'], b['kind'], b['reconciled_at']) for b in builds] == [(1, 'rebrickable_dump', None)]
        assert builds[0]['mapping_version'] == '2099.1.1.1' and json.loads(builds[0]['counts_json'])['items'] == 12
        assert db.execute('SELECT count(*) FROM main.color').fetchone()[0] == 6                    # all of the catalogue's, incl. 1 and 2
        links = {r['color_id']: r['provider_key'] for r in db.execute("SELECT * FROM main.color_link WHERE provider='bricklink'")}
        assert links == {3: '11', 4: '5', 5: '1'}
        ev = [dict(r) for r in db.execute('SELECT * FROM event')]
        assert len(ev) == 1 and (ev[0]['entity_kind'], ev[0]['entity_id'], ev[0]['field'], ev[0]['via'], ev[0]['actor']) == ('catalogue_build', '1', 'activated', 'cli', 'ulf')
        assert report['builds'] == [1] and report['bound'] and report['colours'] == 4 and report['colour_links'] == 3


def test_the_fixed_colours_get_their_links_at_activation(tmp_path):
    maps = write_mappings(tmp_path / 'm', colors=[('9999', '[No Color/Any Color]', 'bricklink', '0', '(Not Applicable)', 0, 9)], parts=PARTS)
    build(write_dump(tmp_path / 'd'), tmp_path / 'catalogue.db', app_version='t', now=STAMP, mappings_dir=maps)
    with closing(connect(tmp_path / 'brickwork.db', tmp_path / 'catalogue.db')) as db:
        assert db.execute('SELECT count(*) FROM main.color_link WHERE color_id=1').fetchone()[0] == 0
        activate(db)
        assert [r[0] for r in db.execute('SELECT provider_key FROM main.color_link WHERE color_id=1')] == ['0']


def test_activation_is_idempotent(world):
    n = len(world.events())
    again = activate(world.db)
    assert again['builds'] == [] and not again['bound'] and again['colours'] == 0 and again['colour_links'] == 0
    assert len(world.events()) == n and world.sql('SELECT count(*) AS n FROM catalogue_build')[0]['n'] == 1


def test_activation_activates_each_new_build_and_never_lowers_a_mark(world):
    world.edit_cat(("INSERT INTO build(id, kind, started_at, app_version, files_json, counts_json) VALUES(2, 'mapping', ?, 't', '[]', '{\"x\": 1}')", STAMP),
                   ("UPDATE meta SET value='50' WHERE key='item_high_water'",))
    report = activate(world.db)
    assert report['builds'] == [2]
    assert world.sql("SELECT value FROM meta WHERE key='catalogue_item_high_water'")[0]['value'] == '50'
    assert world.sql('SELECT id, kind, counts_json FROM catalogue_build WHERE id=2') == [{'id': 2, 'kind': 'mapping', 'counts_json': '{"x": 1}'}]
    assert world.events()[-1]['entity_id'] == '2'


def test_activation_refuses_an_older_catalogue_and_changes_nothing(tmp_path):
    _, cat = make(tmp_path)
    with closing(connect(tmp_path / 'brickwork.db', cat)) as db:
        db.execute("INSERT INTO meta VALUES('catalogue_item_high_water', '99')")      # after the attach check: the collection moved on
        db.commit()
        with pytest.raises(CatalogueMismatch, match='older than this collection'):
            activate(db)
        assert db.execute('SELECT count(*) FROM main.catalogue_build').fetchone()[0] == 0 and db.execute('SELECT count(*) FROM main.event').fetchone()[0] == 0
        assert not db.in_transaction
        db.execute("UPDATE meta SET value='1' WHERE key='catalogue_item_high_water'")
        db.execute("INSERT INTO meta VALUES('catalogue_id', 'someone-else')")
        db.commit()
        with pytest.raises(CatalogueMismatch, match='another catalogue'):
            activate(db)


def test_reconcile_needs_an_activated_catalogue(tmp_path):
    _, cat = make(tmp_path)
    with closing(connect(tmp_path / 'brickwork.db', cat)) as db:
        with pytest.raises(NotActivated, match=r'\[1\]'):
            reconcile(db)
        db.execute('BEGIN')
        with pytest.raises(Store4Error, match='own transaction'):
            activate(db)
        db.rollback()


# ---------- the two "Done when" checks of issue 104, end to end ----------

def reference(w, set_key='6081-1', version=1):
    """What the collection owns: a copy of a set with its lines from a catalogue inventory, a loose part and a wish."""
    db = w.db
    inv = db.execute('SELECT id, digest FROM catalogue.inventory WHERE item_id=? AND version=?', (w.id[set_key], version)).fetchone()
    db.execute("""INSERT INTO copy(id, item_id, inventory_source, inventory_version, inventory_digest, created_at, updated_at)
                  VALUES('copy-1', ?, 'rebrickable', ?, ?, ?, ?)""", (w.id[set_key], version, inv['digest'], STAMP, STAMP))
    for item_id, color_id, spare, qty in db.execute('SELECT item_id, color_id, is_spare, quantity FROM catalogue.inventory_part WHERE inventory_id=?', (inv['id'],)).fetchall():
        identity.project(db, item_id)
        db.execute('INSERT INTO copy_part(copy_id, item_id, color_id, is_spare, quantity) VALUES(?, ?, ?, ?, ?)', ('copy-1', item_id, color_id, spare, qty))
    for item_id, qty in db.execute('SELECT item_id, quantity FROM catalogue.inventory_figure WHERE inventory_id=?', (inv['id'],)).fetchall():
        identity.project(db, item_id)                                   # a materialised copy owns every item of its list
        fig = db.execute('SELECT digest FROM catalogue.inventory WHERE item_id=? AND version=1', (item_id,)).fetchone()
        line = db.execute('INSERT INTO copy_figure(copy_id, item_id, inventory_source, inventory_version, inventory_digest, quantity, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?)',
                          ('copy-1', item_id, 'rebrickable' if fig else 'none', 1 if fig else None, fig and fig[0], qty, STAMP)).lastrowid
        for part_id, color_id, spare, pq in db.execute('''SELECT p.item_id, p.color_id, p.is_spare, p.quantity FROM catalogue.inventory_part p
                                                          JOIN catalogue.inventory i ON i.id=p.inventory_id WHERE i.item_id=? AND i.version=1''', (item_id,)).fetchall():
            identity.project(db, part_id)
            db.execute('INSERT INTO copy_part(copy_id, copy_figure_id, item_id, color_id, is_spare, quantity) VALUES(?, ?, ?, ?, ?, ?)',
                       ('copy-1', line, part_id, color_id, spare, pq))
    identity.project(db, w.id['3001'])
    db.execute("INSERT INTO stock(id, kind, item_id, color_id, quantity, created_at, updated_at) VALUES('stock-1', 'part', ?, 5, 4, ?, ?)", (w.id['3001'], STAMP, STAMP))
    db.execute("INSERT INTO wish(id, kind, item_id, color_id, added_at, updated_at) VALUES('wish-1', 'part', ?, 4, ?, ?)", (w.id['3023'], STAMP, STAMP))
    db.commit()


def referenced(w):
    return {k: w.sql(sql) for k, sql in dict(
        copy='SELECT * FROM copy', lines='SELECT * FROM copy_part ORDER BY id', stock='SELECT * FROM stock', wish='SELECT * FROM wish',
        item_ids='SELECT id, born_key FROM item ORDER BY id', colour_ids='SELECT id, born_key FROM color ORDER BY id').items()}


def test_done_when_1_a_redownload_keeps_every_id_the_collection_uses(tmp_path):
    w = World(tmp_path)
    reference(w)
    before = referenced(w)
    assert len(before['lines']) == 3
    w.close()
    t = tables()                                                       # d2: a part vanishes, one set is new
    t['parts'] = [p for p in t['parts'] if p[0] != '3001']
    t['inventory_parts'] = [p for p in t['inventory_parts'] if p[1] != '3001']
    t['elements'] = [e for e in t['elements'] if e[1] != '3001']
    t['part_relationships'] = []
    t['sets'] = list(reversed(t['sets'])) + [('7000-1', 'New Set 4 x 4', '2020', '186', '9', '')]
    t['parts'] = list(reversed(t['parts']))
    make(tmp_path, 'd2', collection=w.col, **t)
    assert ids(w.cat)['3001'] == w.id['3001'] and ids(w.cat)['7000-1'] == 13
    db = connect(w.col, w.cat)                                          # attaches cleanly: same catalogue, builds and marks agree
    a, r = activate(db), reconcile(db)
    assert a['builds'] == [2]
    assert [dict(x) for x in db.execute('SELECT id, born_key FROM item ORDER BY id')] == before['item_ids']       # every referenced id is unchanged
    assert [dict(x) for x in db.execute('SELECT id, born_key FROM color ORDER BY id')][:len(before['colour_ids'])] == before['colour_ids']
    for table, key in (('copy', 'copy'), ('copy_part', 'lines'), ('stock', 'stock'), ('wish', 'wish')):
        assert [dict(x) for x in db.execute(f'SELECT * FROM {table}' + (' ORDER BY id' if table == 'copy_part' else ''))] == before[key]
    retired = {x['born_key']: x['catalogue_retired_at'] for x in db.execute('SELECT born_key, catalogue_retired_at FROM item')}
    assert retired['3001'] == STAMP and retired['6081-1'] is None and retired['3023'] is None          # the retired one is mirrored
    assert r['changes']['retirement_set'] == 1
    # the copy's list lost a line, so it is listed, not touched
    assert r['inventory_changes'] == [dict(table='copy', id='copy-1', item_id=w.id['6081-1'], inventory_version=1, reasons=['digest_changed'])]
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert [x[0] for x in db.execute('SELECT id FROM catalogue_build WHERE reconciled_at IS NOT NULL ORDER BY id')] == [1, 2]
    db.close()
    with closing(connect(w.col, w.cat)):
        pass


def test_done_when_2_a_rebuild_from_scratch_seeded_by_the_collection_keeps_the_ids(tmp_path):
    w = World(tmp_path)
    reference(w)
    before = referenced(w)
    w.close()
    w.cat.unlink()
    (tmp_path / 'catalogue.db.prev').unlink(missing_ok=True)
    t = tables()
    t['sets'], t['parts'] = list(reversed(t['sets'])), list(reversed(t['parts']))
    report, _ = make(tmp_path, 'd2', collection=w.col, **t)
    assert report['seeded_from'] == 'collection'
    db = connect(w.col, w.cat)
    a, r = activate(db), reconcile(db)
    assert a['builds'] == [2] and not a['bound']                        # build 1 is the collection's, the rebuild is build 2
    assert referenced_ids(db) == before['item_ids'] and ids(w.cat)['6081-1'] == w.id['6081-1']
    for table, key in (('copy', 'copy'), ('stock', 'stock'), ('wish', 'wish')):
        assert [dict(x) for x in db.execute(f'SELECT * FROM {table}')] == before[key]
    assert r['inventory_changes'] == []                                 # same dump: the copy's list is the one it was built from
    assert not r['changes'].get('retirement_set') and r['adopted'] == []
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    db.close()


def referenced_ids(db):
    return [dict(x) for x in db.execute('SELECT id, born_key FROM item ORDER BY id')]


# ---------- adoption (A4) ----------

def local_item(db, id_, key, ns='sets', kind='set'):
    db.execute("INSERT INTO item(id, origin, kind, kind_source, name, born_provider, born_namespace, born_key, created_at, updated_at)"
               " VALUES(?, 'local', ?, 'namespace', 'Fetched Set', 'rebrickable', ?, ?, ?, ?)", (id_, kind, ns, key, STAMP, STAMP))


def test_a4_an_adopted_local_item_is_flipped_by_reconcile_and_a_merged_one_is_listed(tmp_path):
    t = tables()
    t['sets'] = [s for s in t['sets'] if s[0] not in ('9999-1', '5004-1')]
    t['inventories'] = [i for i in t['inventories'] if i[2] != '9999-1']
    t['inventory_sets'] = []
    w = World(tmp_path, keys=('6081-1',), **t)
    local_item(w.db, 1_000_000_003, '9999-1')
    local_item(w.db, 1_000_000_004, '5004-1')
    w.db.execute("UPDATE item SET merged_into=? WHERE id=1000000004", (w.id['6081-1'],))
    w.db.commit()
    w.close()
    report, _ = make(tmp_path, 'd2', collection=w.col)                  # the full dump now has both keys
    assert report['counts']['adopted'] == 1
    w.db = connect(w.col, w.cat)
    activate(w.db)
    r = w.reconcile()
    assert r['adopted'] == [1_000_000_003] and r['changes']['adopted'] == 1
    row = w.sql("SELECT origin, catalogue_build_id, digest, name FROM item WHERE id=1000000003")[0]
    assert row['origin'] == 'catalogue' and row['catalogue_build_id'] == 2 and row['digest'] and row['name'] == 'Plain Set 8 x 8'   # then names refreshed
    assert w.sql('SELECT origin FROM item WHERE id=1000000004') == [{'origin': 'local'}]                  # merged: not flipped
    assert r['adoption_skipped_merged'] == [dict(item_id=1_000_000_004, namespace='sets', born_key='5004-1', merged_into=w.id['6081-1'])]
    assert r['merged_local'] == [dict(namespace='sets', born_key='5004-1', local_id=1_000_000_004, catalogue_id=ids(w.cat)['5004-1'])]
    assert any(e['entity_kind'] == 'item' and e['field'] == 'origin' and e['entity_id'] == '1000000003' for e in w.events())
    again = w.reconcile()                                               # a flipped item is an ordinary catalogue item from now on
    assert again['adopted'] == [] and again['events'] == 0
    w.close()


# ---------- names, properties, kinds, retirement ----------

def test_names_and_properties_are_refreshed_with_an_event_per_field(world):
    world.edit_cat(("UPDATE item SET name='Renamed Plate', year=1999, size_key='2x2', digest='new-digest', build_id=1 WHERE born_key='3023'",))
    r = world.reconcile(actor='ulf')
    row = world.sql("SELECT name, year, size_key, digest FROM item WHERE born_key='3023'")[0]
    assert row == dict(name='Renamed Plate', year=1999, size_key='2x2', digest='new-digest')
    ev = {e['field']: e for e in world.events() if e['entity_kind'] == 'item' and e['entity_id'] == str(world.id['3023'])}
    assert (ev['name']['old_value'], ev['name']['new_value'], ev['year']['new_value'], ev['name']['actor']) == ('Plate 1 x 2', 'Renamed Plate', '1999', 'ulf')
    assert len({e['operation_key'] for e in world.events() if e['field'] != 'activated'}) == 1
    assert r['changes']['items_refreshed'] == 1
    assert world.sql("SELECT name FROM item WHERE born_key='3001'") == [{'name': 'Brick 2 x 4'}]               # others untouched


def test_a_renamed_theme_refreshes_the_projected_name_even_with_the_same_digest(world):
    world.edit_cat(("UPDATE theme SET name='Castles' WHERE id=186",))
    world.reconcile()
    assert world.sql("SELECT theme_name FROM item WHERE born_key='6081-1'") == [{'theme_name': 'Castles'}]


def test_an_unreferenced_kind_change_is_applied(world):
    identity.project(world.db, world.id['5002-1'])
    world.db.commit()
    assert world.sql("SELECT kind, kind_source FROM item WHERE born_key='5002-1'") == [{'kind': 'gear', 'kind_source': 'theme'}]
    world.edit_cat(("UPDATE item SET kind='set', kind_source='bricklink' WHERE born_key='5002-1'",))
    r = world.reconcile()
    assert world.sql("SELECT kind, kind_source FROM item WHERE born_key='5002-1'") == [{'kind': 'set', 'kind_source': 'bricklink'}]
    assert r['changes']['kinds_changed'] == 1 and world.sql('SELECT * FROM item_provider_status') == []
    assert any(e['field'] == 'kind' and (e['old_value'], e['new_value']) == ('gear', 'set') for e in world.events())


def test_a_referenced_kind_is_kept_and_recorded_as_kind_differs_then_cleared(tmp_path):
    w = World(tmp_path, keys=('6081-1', '5001-1'))
    w.db.execute("INSERT INTO stock(id, kind, item_id, quantity, created_at, updated_at) VALUES('s1', 'gear', ?, 1, ?, ?)", (w.id['5001-1'], STAMP, STAMP))
    w.db.commit()
    w.edit_cat(("UPDATE item SET kind='catalog', kind_source='bricklink' WHERE born_key='5001-1'",))
    r = w.reconcile()
    assert w.sql("SELECT kind, kind_source FROM item WHERE born_key='5001-1'") == [{'kind': 'gear', 'kind_source': 'theme'}]    # the guard refused
    status = w.sql('SELECT * FROM item_provider_status')
    assert [(s['item_id'], s['provider'], s['status'], s['reason']) for s in status] == [(w.id['5001-1'], 'bricklink', 'to_check', 'kind_differs')]
    assert json.loads(status[0]['evidence_json']) == {'from': 'gear', 'to': 'catalog'}
    assert r['changes']['kind_differs'] == 1 and r['not_applied']['kind_differs'][0]['catalogue_kind'] == 'catalog'
    again = w.reconcile()                                               # still differs: reported again, nothing written
    assert again['events'] == 0 and again['not_applied']['kind_differs']
    w.edit_cat(("UPDATE item SET kind='gear', kind_source='theme' WHERE born_key='5001-1'",))       # the catalogue agrees again
    r = w.reconcile()
    assert w.sql('SELECT * FROM item_provider_status') == [] and r['changes']['kind_differs_cleared'] == 1
    w.close()


def test_a_manual_kind_is_never_touched(tmp_path):
    w = World(tmp_path, keys=('6081-1', '5002-1'))
    w.db.execute("UPDATE item SET kind='book', kind_source='manual' WHERE born_key='5002-1'")
    w.db.commit()
    w.reconcile()
    assert w.sql("SELECT kind, kind_source FROM item WHERE born_key='5002-1'") == [{'kind': 'book', 'kind_source': 'manual'}]
    assert w.sql('SELECT * FROM item_provider_status') == []
    w.close()


def test_retirement_is_mirrored_set_and_cleared(world):
    world.edit_cat(("UPDATE item SET retired_at=? WHERE born_key='3001'", '2026-10-30T00:00:00.000Z'))
    world.reconcile()
    assert world.sql("SELECT catalogue_retired_at FROM item WHERE born_key='3001'") == [{'catalogue_retired_at': '2026-10-30T00:00:00.000Z'}]
    world.edit_cat(("UPDATE item SET retired_at=NULL WHERE born_key='3001'",))
    r = world.reconcile()
    assert world.sql("SELECT catalogue_retired_at FROM item WHERE born_key='3001'") == [{'catalogue_retired_at': None}] and r['changes']['retirement_cleared'] == 1


# ---------- links ----------

def test_a_link_the_collection_lacks_is_inserted(world):
    world.edit_cat(("INSERT INTO item_link(item_id, color_id, provider, provider_kind, provider_key, status, method, origin, preferred, evidence_digest, build_id)"
                    " VALUES(?, NULL, 'bricklink', 'P', '3023b', 'inferred', 'external_ids', 'shipped', 0, 'e', 1)", world.id['3023']))
    r = world.reconcile()
    row = world.link('3023b')
    assert (row['status'], row['origin'], row['catalogue_build_id']) == ('inferred', 'shipped', 1) and r['changes']['links_inserted'] == 1
    assert any(e['entity_kind'] == 'item_link' and e['entity_id'] == str(row['id']) and e['field'] == 'inserted' for e in world.events())


def test_inferred_is_upgraded_to_matched_in_place_with_evidence(world):
    before = world.link('3023')
    assert before['status'] == 'inferred'
    world.edit_cat(("UPDATE item_link SET status='matched', method='bricklink_list', origin='bricklink_list', evidence_digest='new' WHERE provider_key='3023'",))
    r = world.reconcile()
    after = world.link('3023')
    assert after['id'] == before['id'] and (after['status'], after['method'], after['origin'], after['evidence_digest']) == ('matched', 'bricklink_list', 'bricklink_list', 'new')
    assert json.loads(after['evidence_json'])['was'] == 'inferred' and r['changes']['links_upgraded'] == 1
    assert any(e['entity_id'] == str(before['id']) and (e['old_value'], e['new_value']) == ('inferred', 'matched') for e in world.events())


def test_matched_replaces_a_to_check_link_and_a_no_match_status(tmp_path):
    w = World(tmp_path, keys=('6081-1', '3626'))                       # 3626 is projected with a to_check candidate
    item = w.id['3626']
    assert w.link('x', item_key='3626')['status'] == 'to_check'
    w.sql("INSERT INTO item_provider_status(item_id, provider, status, reason, checked_at) VALUES(?, 'bricklink', 'unmatched', 'no_match', ?)", item, STAMP)
    w.sql("INSERT INTO item_provider_status(item_id, provider, status, reason, checked_at) VALUES(?, 'brickset', 'unmatched', 'no_match', ?)", item, STAMP)
    w.edit_cat(("UPDATE item_link SET status='matched' WHERE provider_key='x'",))
    r = w.reconcile()
    assert w.link('x', item_key='3626')['status'] == 'matched' and r['changes']['links_replaced'] == 1
    assert [x['provider'] for x in w.sql('SELECT * FROM item_provider_status')] == ['brickset']       # only that provider's row is replaced
    assert r['changes']['provider_status_replaced'] == 1
    w.close()


def test_manual_and_matched_links_are_never_changed_only_reported(world):
    manual = world.link('3023')
    world.sql("UPDATE item_link SET status='manual', origin='user' WHERE id=?", manual['id'])
    world.edit_cat(
        ("UPDATE item_link SET provider_key='3023-other' WHERE provider_key='3023'",),                  # a different key beside the manual one
        ("UPDATE item_link SET status='inferred' WHERE provider_key='3001'",),                          # a downgrade of matched
    )
    held = world.sql('SELECT * FROM item_link WHERE item_id=? AND provider_key IN (?, ?)', world.id['3001'], '3001', '3023')
    r = world.reconcile()
    assert world.sql('SELECT * FROM item_link WHERE item_id=? AND provider_key IN (?, ?)', world.id['3001'], '3001', '3023') == held   # byte for byte
    assert [(x['reason'], x['item_id']) for x in r['not_applied']['links']] == [('downgrade', world.id['3001'])]
    assert world.link('3023-other')['status'] == 'inferred'            # the manual link still answers, so the newcomer is just a candidate
    assert identity.resolve(world.db, world.id['3023'], 4)[1] == '3023'


def test_a_vanished_link_is_reported_never_deleted(world):
    world.edit_cat(("DELETE FROM item_link WHERE provider_key IN ('3023', '3001')",))             # an inferred and a matched one
    r = world.reconcile()
    assert sorted((x['reason'], x['provider_key'], x['collection_status']) for x in r['not_applied']['links']) == [
        ('vanished', '3001', 'matched'), ('vanished', '3023', 'inferred')]
    assert world.link('3023')['status'] == 'inferred' and world.link('3001', item_key='3001')['status'] == 'matched'


def test_colour_links_follow_the_same_rules(world):
    world.edit_cat(("UPDATE color SET name='Bright Red' WHERE born_key='4'",),
                   ("UPDATE color_link SET status='inferred' WHERE provider_key='5'",),              # a downgrade of a matched colour link
                   ("INSERT INTO color_link(color_id, provider, provider_key, provider_name, status, method, origin, inverse_preferred, build_id)"
                    " VALUES(5, 'lego', '1', 'White', 'matched', 'external_ids', 'shipped', 0, 1)", ))
    r = world.reconcile()
    assert world.sql('SELECT name FROM color WHERE id=4') == [{'name': 'Bright Red'}] and r['changes']['colours_refreshed'] == 1
    assert world.sql("SELECT status FROM color_link WHERE provider_key='5'") == [{'status': 'matched'}]
    assert [x['reason'] for x in r['not_applied']['colour_links']] == ['downgrade']
    assert world.sql("SELECT provider FROM color_link WHERE color_id=5 ORDER BY provider") == [{'provider': 'bricklink'}, {'provider': 'lego'}]
    assert r['changes']['colour_links_inserted'] == 1


def test_several_matched_candidates_the_catalogue_adds_together_are_all_inserted(tmp_path):
    w = World(tmp_path, keys=('6081-1', '3626'))                       # 3626 holds only a to_check candidate: no rival
    item = w.id['3626']
    stmts = [("INSERT INTO item_link(item_id, color_id, provider, provider_kind, provider_key, status, method, origin, preferred, evidence_digest, build_id)"
              " VALUES(?, NULL, 'bricklink', 'P', ?, 'matched', 'external_ids', 'shipped', ?, 'e', 1)", item, k, int(k == 's1')) for k in ('s1', 's2', 's3')]
    w.edit_cat(*stmts)
    w.sql("UPDATE item_link SET preferred=1, origin='user' WHERE provider_key='x'")                 # the user already prefers one
    r = w.reconcile()
    assert [x['reason'] for x in r['not_applied']['links']] == ['preferred_differs'] and r['changes']['links_inserted'] == 3
    assert w.sql('SELECT provider_key FROM item_link WHERE item_id=? AND preferred=1', item) == [{'provider_key': 'x'}]
    w.close()


# ---------- part lists, merges, coverage, reconciled ----------

def test_copies_and_figure_lines_whose_list_changed_are_listed(world):
    reference(world)
    figure = ids(world.cat)['fig-000001']                              # reference() gave the copy this figure line (version 1)
    digest = world.db.execute('SELECT digest FROM catalogue.inventory WHERE item_id=?', (figure,)).fetchone()[0]
    world.db.execute("INSERT INTO stock(id, kind, item_id, quantity, inventory_source, inventory_version, inventory_digest, created_at, updated_at)"
                     " VALUES('loose', 'minifigure', ?, 1, 'rebrickable', 1, ?, ?, ?)", (figure, digest, STAMP, STAMP))
    world.db.commit()
    assert world.reconcile()['inventory_changes'] == []
    world.edit_cat(("UPDATE inventory SET digest='changed' WHERE item_id=? AND version=1", figure),
                   ("UPDATE inventory SET retired_at=? WHERE item_id=? AND version=1", STAMP, world.id['6081-1']))
    got = world.reconcile()['inventory_changes']
    assert sorted((x['table'], x['id'], tuple(x['reasons'])) for x in got) == sorted([
        ('copy', 'copy-1', ('version_retired',)), ('copy_figure', 1, ('digest_changed',)), ('stock', 'loose', ('digest_changed',))])
    world.sql("UPDATE copy SET archived_at=? WHERE id='copy-1'", STAMP)    # an archived copy is not listed
    assert [x['table'] for x in world.reconcile()['inventory_changes']] == ['stock']       # nor are its figure lines


def test_the_report_lists_shadowed_and_merged_returning_items(tmp_path):
    w = World(tmp_path, keys=('6081-1', '9999-1', '3023'))
    gone = w.id['9999-1']
    w.db.execute("DELETE FROM item_link WHERE item_id=?", (gone,))
    w.db.execute("UPDATE item SET catalogue_retired_at=? WHERE id=?", (STAMP, gone))
    w.db.execute("UPDATE item SET merged_into=? WHERE id=?", (w.id['6081-1'], gone))
    local_item(w.db, 1_000_000_003, '5003-1')                             # fetched locally; the catalogue already numbers it
    w.db.commit()
    w.close()
    t = tables()                                                         # 9999-1 left the dump and comes back below
    t['sets'] = [s for s in t['sets'] if s[0] != '9999-1']
    t['inventories'] = [i for i in t['inventories'] if i[2] != '9999-1']
    t['inventory_sets'] = []
    make(tmp_path, 'd2', collection=w.col, **t)
    make(tmp_path, 'd3', collection=w.col)                                # the merged key returns under a fresh id
    w.db = connect(w.col, w.cat)
    activate(w.db)
    r = w.reconcile()
    assert r['shadowed_local'] == [dict(namespace='sets', born_key='5003-1', local_id=1_000_000_003, catalogue_id=ids(w.cat)['5003-1'])]
    assert len(r['merged_returning']) == 1 and r['merged_returning'][0]['merged_id'] == gone and r['merged_returning'][0]['merged_into'] == w.id['6081-1']
    assert r['merged_live_in_catalogue'] == []
    assert w.sql('SELECT origin FROM item WHERE id=1000000003') == [{'origin': 'local'}]              # reported, not flipped or merged
    w.close()


def test_a_live_catalogue_row_naming_a_merged_collection_id_is_reported(tmp_path):
    w = World(tmp_path, keys=('6081-1', '9999-1'))
    gone = w.id['9999-1']
    w.db.execute("DELETE FROM item_link WHERE item_id=?", (gone,))
    w.db.execute("UPDATE item SET catalogue_retired_at=? WHERE id=?", (STAMP, gone))                  # as a merge requires
    w.db.execute("UPDATE item SET merged_into=? WHERE id=?", (w.id['6081-1'], gone))
    w.db.commit()
    r = w.reconcile()                                                  # the catalogue (built before the merge) still has 9999-1 live
    assert r['merged_live_in_catalogue'] == [dict(item_id=gone, born_key='9999-1', merged_into=w.id['6081-1'])]
    assert w.sql('SELECT catalogue_retired_at FROM item WHERE id=?', gone) == [{'catalogue_retired_at': STAMP}]     # reported, not "fixed"
    w.close()


def test_coverage_counts_projected_items_by_their_best_bricklink_link(tmp_path):
    w = World(tmp_path, keys=('6081-1', '3023', '3001', '3626', '5001-1', '5002-1'))
    r = w.reconcile()
    # 6081-1: the set-number rule's inferred link; 3023 inferred; 3001 matched; 3626 to_check; the gear items have none
    assert r['coverage']['set'] == dict(manual=0, matched=0, inferred=1, to_check=0, none=0)
    assert r['coverage']['part'] == dict(manual=0, matched=1, inferred=1, to_check=1, none=0)
    assert r['coverage']['gear'] == dict(manual=0, matched=0, inferred=0, to_check=0, none=2)
    w.sql("UPDATE item_link SET status='manual', origin='user' WHERE provider_key='3023'")
    assert w.reconcile()['coverage']['part'] == dict(manual=1, matched=1, inferred=0, to_check=1, none=0)
    stored = json.loads(w.sql('SELECT counts_json FROM catalogue_build')[0]['counts_json'])['reconcile']
    assert stored['coverage'] == w.reconcile()['coverage'] and stored['operation_key']
    w.close()


def test_reconciled_at_is_set_and_a_second_run_changes_nothing(world):
    world.edit_cat(("UPDATE item SET name='Renamed', digest='x' WHERE born_key='3023'",),
                   ("UPDATE item_link SET status='matched' WHERE provider_key='3023'",))
    assert world.sql('SELECT reconciled_at FROM catalogue_build') == [{'reconciled_at': None}]
    first = world.reconcile()
    assert first['events'] == 2 and world.sql('SELECT reconciled_at FROM catalogue_build')[0]['reconciled_at']
    snapshot = {t: world.sql(f'SELECT * FROM {t} ORDER BY 1, 2') for t in ('item', 'item_link', 'color', 'color_link', 'event', 'item_provider_status')}
    second = world.reconcile()
    assert second['events'] == 0 and second['changes'] == {}
    assert {t: world.sql(f'SELECT * FROM {t} ORDER BY 1, 2') for t in snapshot} == snapshot
    assert json.loads(world.sql('SELECT counts_json FROM catalogue_build')[0]['counts_json'])['reconcile']['events'] == 0


def test_a_failure_rolls_everything_back(world, monkeypatch):
    world.edit_cat(("UPDATE item SET name='Renamed', digest='x' WHERE born_key='3023'",))
    import brickwork.store4.reconcile as mod
    monkeypatch.setattr(mod, '_coverage', lambda db: 1 / 0)
    n = len(world.events())
    with pytest.raises(ZeroDivisionError):
        world.reconcile()
    assert world.sql("SELECT name FROM item WHERE born_key='3023'") == [{'name': 'Plate 1 x 2'}] and len(world.events()) == n
    assert world.sql('SELECT reconciled_at FROM catalogue_build') == [{'reconciled_at': None}] and not world.db.in_transaction


def test_a_manual_link_is_not_upgraded_over_by_the_same_key_arriving_as_matched(world):
    link = world.link('3023')
    world.sql("UPDATE item_link SET status='manual', origin='user' WHERE id=?", link['id'])
    world.edit_cat(("UPDATE item_link SET status='matched' WHERE provider_key='3023'",))
    r = world.reconcile()
    assert world.link('3023') == dict(link, status='manual', origin='user') and not r['changes'].get('links_upgraded')


# ---------- review fixes ----------

def test_a_stale_connection_is_refused_after_another_moved_the_pair_on(tmp_path):
    w = World(tmp_path)
    stale = connect(w.col, w.cat)
    stale.execute('SELECT count(*) FROM catalogue.item').fetchone()       # the old file is open now
    w.close()
    make(tmp_path, 'd2', collection=w.col)                                # a rebuild replaces catalogue.db
    fresh = connect(w.col, w.cat)
    activate(fresh)
    reconcile(fresh)
    fresh.close()
    state = lambda: ([tuple(r) for r in stale.execute('SELECT * FROM main.catalogue_build')], stale.execute('SELECT count(*) FROM main.event').fetchone()[0])
    before = state()
    for call in (reconcile, activate):
        with pytest.raises(CatalogueMismatch, match=r'activated catalogue builds \[2\]'):
            call(stale)
        assert state() == before and not stale.in_transaction
    stale.close()


def test_an_inverse_preference_that_moves_to_a_new_colour_is_reported_not_applied(tmp_path):
    extra = [('1051', 'Pastel Blue', '', 'False'), ('313', 'Maersk Blue', '', 'False')]
    first = COLORS + [('1051', 'Pastel Blue', 'bricklink', '72', 'Pastel Blue', 1, 9)]
    moved = COLORS + [('1051', 'Pastel Blue', 'bricklink', '72', 'Pastel Blue', 0, 9), ('313', 'Maersk Blue', 'bricklink', '72', 'Maersk Blue', 1, 9)]
    base = tables()['colors']
    _, cat = make(tmp_path, colours=first, colors=base + extra[:1])
    db = connect(tmp_path / 'brickwork.db', cat)
    activate(db)
    db.close()
    make(tmp_path, 'd2', colours=moved, colors=base + extra, collection=tmp_path / 'brickwork.db')
    db = connect(tmp_path / 'brickwork.db', cat)
    activate(db)                                                          # used to roll back on color_link_inverse
    flags = {r['born_key']: r['inverse_preferred'] for r in db.execute(
        "SELECT c.born_key, l.inverse_preferred FROM color_link l JOIN color c ON c.id=l.color_id WHERE l.provider_key='72'")}
    assert flags == {'1051': 1}                                           # the holder keeps it; the newcomer's link is not taken over
    r = reconcile(db)
    assert {x['born_key']: x['inverse_preferred'] for x in db.execute(
        "SELECT c.born_key, l.inverse_preferred FROM color_link l JOIN color c ON c.id=l.color_id WHERE l.provider_key='72'")} == {'1051': 1, '313': 0}
    moves = sorted((x['color_id'], x['collection'], x['catalogue']) for x in r['not_applied']['colour_links'] if x['reason'] == 'inverse_preferred_differs')
    assert len(moves) == 2 and {m[1:] for m in moves} == {(1, 0), (0, 1)}
    assert {x[0] for x in db.execute("SELECT color_id FROM color_link WHERE inverse_preferred=1 AND provider_key='72'")} == {ids(cat, 'color')['1051']}
    db.close()


def test_a_new_scoped_link_does_not_override_a_manual_unscoped_one(world):
    item = world.id['3001']
    world.sql("UPDATE item_link SET status='manual', origin='user', preferred=1 WHERE item_id=?", item)
    assert identity.resolve(world.db, item, 4) == ('P', '3001', '5')
    world.edit_cat(("INSERT INTO item_link(item_id, color_id, provider, provider_kind, provider_key, status, method, origin, preferred, evidence_digest, build_id)"
                    " VALUES(?, 4, 'bricklink', 'P', 'B', 'matched', 'external_ids', 'shipped', 0, 'e', 1)", item))
    r = world.reconcile()
    assert [(x['reason'], x['catalogue_key'], x['before'][1], x['after'][1]) for x in r['not_applied']['links']] == [
        ('would_change_resolution', 'B', '3001', 'B')]
    assert world.sql("SELECT * FROM item_link WHERE provider_key='B'") == [] and identity.resolve(world.db, item, 4) == ('P', '3001', '5')


def test_a_new_unscoped_link_beside_a_manual_scoped_one_is_inserted(world):
    item = world.id['3001']
    world.sql("UPDATE item_link SET color_id=4, status='manual', origin='user' WHERE item_id=?", item)
    world.edit_cat(("INSERT INTO item_link(item_id, color_id, provider, provider_kind, provider_key, status, method, origin, preferred, evidence_digest, build_id)"
                    " VALUES(?, NULL, 'bricklink', 'P', 'U', 'inferred', 'external_ids', 'shipped', 0, 'e', 1)", item))
    r = world.reconcile()
    assert world.link('U', item_key='3001')['color_id'] is None and 'links' not in {k for k, v in r['not_applied'].items() if any(x['reason'] == 'would_change_resolution' for x in v)}
    assert identity.resolve(world.db, item, 4) == ('P', '3001', '5')


def test_an_existing_scoped_to_check_upgraded_to_matched_beside_a_manual_unscoped_one_is_refused(world):
    item = world.id['3001']
    world.sql("UPDATE item_link SET status='manual', origin='user', preferred=1 WHERE item_id=?", item)
    world.sql("INSERT INTO item_link(item_id, color_id, provider, provider_kind, provider_key, status, method, origin, decided_at) "
              "VALUES(?, 4, 'bricklink', 'P', 'B', 'to_check', 'x', 'shipped', ?)", item, STAMP)
    world.edit_cat(("INSERT INTO item_link(item_id, color_id, provider, provider_kind, provider_key, status, method, origin, preferred, evidence_digest, build_id)"
                    " VALUES(?, 4, 'bricklink', 'P', 'B', 'matched', 'external_ids', 'shipped', 0, 'e', 1)", item))
    r = world.reconcile()
    assert world.link('B', item_key='3001')['status'] == 'to_check' and identity.resolve(world.db, item, 4)[1] == '3001'
    assert [(x['reason'], x['action']) for x in r['not_applied']['links']] == [('would_change_resolution', 'upgrade')]


def test_the_full_identity_is_kind_and_key(world):
    item = world.id['3001']
    world.sql("UPDATE item_link SET provider_kind='G', provider_key='5001-1', status='manual', origin='user', preferred=0 WHERE item_id=?", item)
    world.edit_cat(("INSERT INTO item_link(item_id, color_id, provider, provider_kind, provider_key, status, method, origin, preferred, evidence_digest, build_id)"
                    " VALUES(?, NULL, 'bricklink', 'S', '5001-1', 'matched', 'external_ids', 'shipped', 1, 'e', 1)", item))
    r = world.reconcile()
    assert world.sql("SELECT provider_kind, preferred FROM item_link WHERE item_id=? AND provider_key='5001-1' ORDER BY provider_kind", item) == [
        {'provider_kind': 'G', 'preferred': 0}, {'provider_kind': 'S', 'preferred': 0}]                  # S is a candidate; moving the preference to it is refused
    assert [x['reason'] for x in r['not_applied']['links']].count('would_change_resolution') == 1
    assert identity.resolve(world.db, item, 4)[:2] == ('G', '5001-1')


def test_a_colour_link_upgrade_that_changes_the_exported_colour_is_refused(tmp_path):
    both = [('4', 'Red', 'bricklink', '5', 'Red', 0, 9), ('4', 'Red', 'bricklink', '1', 'Red alias', 0, 9)]
    _, cat = make(tmp_path, colours=both)                                 # the catalogue says matched for both keys
    db = connect(tmp_path / 'brickwork.db', cat)
    activate(db)
    red = ids(cat, 'color')['4']
    db.execute("UPDATE color_link SET status='inferred' WHERE color_id=? AND provider_key='1'", (red,))   # the collection holds '1' as inferred
    db.commit()
    r = reconcile(db)                                                     # '1' -> matched would make the lexically smaller key '1' win
    assert db.execute("SELECT status FROM color_link WHERE color_id=? AND provider_key='1'", (red,)).fetchone()[0] == 'inferred'
    assert [(x['reason'], x['action']) for x in r['not_applied']['colour_links']] == [('would_change_resolution', 'upgrade')]
    assert identity.best_color_link(identity.confirmed_color_links(db, red, 'bricklink'))['provider_key'] == '5'
    db.close()


def test_protection_comes_only_from_the_state_before_the_run(tmp_path):
    w = World(tmp_path, keys=('6081-1', '3626'))                       # 3626 holds only a to_check candidate
    item = w.id['3626']
    ins = ("INSERT INTO item_link(item_id, color_id, provider, provider_kind, provider_key, status, method, origin, preferred, evidence_digest, build_id)"
           " VALUES(?, NULL, 'bricklink', 'P', ?, 'matched', 'external_ids', 'shipped', ?, 'e', 1)")
    w.edit_cat((ins, item, 'Z', 0), (ins, item, 'A', 1))                  # Z comes first; the catalogue prefers A
    r = w.reconcile()
    assert identity.resolve(w.db, item, 4)[:2] == ('P', 'A') and 'links' not in r['not_applied'] and r['changes']['links_inserted'] == 2
    again = w.reconcile()
    assert again['events'] == 0 and again['changes'] == {} and identity.resolve(w.db, item, 4)[:2] == ('P', 'A')
    w.close()


def test_a_baseline_inverse_answer_is_protected(world):
    x, y = world.id['3023'], world.id['3001']
    world.sql("UPDATE item_link SET status='manual', origin='user' WHERE item_id=?", x)
    assert identity.resolve_inverse(world.db, 'P', '3023', '5') == (x, 4)
    world.edit_cat(("INSERT INTO item_link(item_id, color_id, provider, provider_kind, provider_key, status, method, origin, preferred, evidence_digest, build_id)"
                    " VALUES(?, NULL, 'bricklink', 'P', '3023', 'matched', 'external_ids', 'shipped', 0, 'e', 1)", y))
    r = world.reconcile()
    assert [(e['reason'], e['direction'], e['item_id']) for e in r['not_applied']['links']] == [('would_change_resolution', 'inverse', y)]
    assert world.sql("SELECT * FROM item_link WHERE item_id=? AND provider_key='3023'", y) == []
    assert identity.resolve_inverse(world.db, 'P', '3023', '5') == (x, 4)


def test_parts_sharing_a_key_are_fine_when_the_baseline_answer_was_not_certain(world):
    y = world.id['3001']                                              # 3023's link is only inferred: nothing to protect
    world.edit_cat(("INSERT INTO item_link(item_id, color_id, provider, provider_kind, provider_key, status, method, origin, preferred, evidence_digest, build_id)"
                    " VALUES(?, NULL, 'bricklink', 'P', '3023', 'matched', 'external_ids', 'shipped', 0, 'e', 1)", y))
    r = world.reconcile()
    assert 'links' not in r['not_applied'] and r['changes']['links_inserted'] == 1


def test_equal_rank_ties_break_by_key_before_kind_in_the_resolver_and_the_digest(tmp_path):
    from brickwork.store4.bldigest import bl_digest
    links = [part('3001', '100', kind='S'), part('3001', '900', kind='G')]
    w = World(tmp_path, links=links, keys=('9999-1', '3001'))
    assert identity.resolve(w.db, w.id['3001'], 3)[:2] == ('S', '100')
    digest = q(w.cat, 'SELECT bl_digest FROM inventory WHERE item_id=?', w.id['9999-1'])[0]['bl_digest']
    assert digest == bl_digest([('S', '100', '11', 0, 1), ('S', '6081-1', None, 0, 1)])
    w.close()


def test_a_scoped_row_cannot_break_the_inverse_answer_of_an_unscoped_manual_link_under_another_key(world):
    item = world.id['3001']
    world.sql("UPDATE item_link SET status='manual', origin='user' WHERE item_id=?", item)            # unscoped manual A = 3001
    world.sql("INSERT INTO item_link(item_id, color_id, provider, provider_kind, provider_key, status, method, origin, preferred, decided_at) "
              "VALUES(?, NULL, 'bricklink', 'P', 'C', 'inferred', 'x', 'shipped', 1, ?)", item, STAMP)   # preferred inferred C
    assert identity.resolve_inverse(world.db, 'P', '3001', '5') == (item, 4)
    world.edit_cat(("INSERT INTO item_link(item_id, color_id, provider, provider_kind, provider_key, status, method, origin, preferred, evidence_digest, build_id)"
                    " VALUES(?, 4, 'bricklink', 'P', 'B', 'matched', 'external_ids', 'shipped', 0, 'e', 1)", item))
    r = world.reconcile()
    assert [(x['reason'], x['direction'], x['catalogue_key']) for x in r['not_applied']['links']] == [('would_change_resolution', 'inverse', 'B')]
    assert world.sql("SELECT * FROM item_link WHERE provider_key='B'") == [] and identity.resolve_inverse(world.db, 'P', '3001', '5') == (item, 4)


def test_projecting_a_colour_does_not_take_over_a_key_another_colour_holds(tmp_path):
    a = COLORS + [('1051', 'Pastel Blue', 'bricklink', '72', 'Pastel Blue', 0, 9)]
    b = a + [('313', 'Maersk Blue', 'bricklink', '72', 'Maersk Blue', 0, 9)]
    extra = [('1051', 'Pastel Blue', '', 'False'), ('313', 'Maersk Blue', '', 'False')]
    base = tables()['colors']
    _, cat = make(tmp_path, colours=a, colors=base + extra[:1])
    col = tmp_path / 'brickwork.db'
    db = connect(col, cat)
    activate(db)
    db.close()
    make(tmp_path, 'd2', colours=b, colors=base + extra, collection=col)
    db = connect(col, cat)
    activate(db)
    pastel, maersk = ids(cat, 'color')['1051'], ids(cat, 'color')['313']
    assert db.execute('SELECT count(*) FROM color WHERE id=?', (maersk,)).fetchone()[0] == 1           # the colour row is projected
    assert db.execute('SELECT count(*) FROM color_link WHERE color_id=?', (maersk,)).fetchone()[0] == 0     # its link to 72 is not
    assert identity._inverse_color(db, 'bricklink', '72') == pastel
    r = reconcile(db)
    assert [(x['reason'], x['direction'], x['catalogue_key']) for x in r['not_applied']['colour_links']] == [('would_change_resolution', 'inverse', '72')]
    assert identity._inverse_color(db, 'bricklink', '72') == pastel and db.execute('SELECT count(*) FROM color_link WHERE color_id=?', (maersk,)).fetchone()[0] == 0
    db.close()


class FailingCommit:
    """A connection that fails its next commit, as a full disk or a lock timeout would."""

    def __init__(self, db):
        self._db, self.fail = db, True

    def commit(self):
        if self.fail:
            self.fail = False
            raise sqlite3.OperationalError('disk full')
        return self._db.commit()

    def __getattr__(self, name):
        return getattr(self._db, name)


def test_a_failing_commit_rolls_back_and_leaves_no_open_transaction(tmp_path):
    _, cat = make(tmp_path)
    db = FailingCommit(connect(tmp_path / 'brickwork.db', cat))
    with pytest.raises(sqlite3.OperationalError, match='disk full'):
        activate(db)
    assert not db.in_transaction
    assert db.execute('SELECT count(*) FROM catalogue_build').fetchone()[0] == 0 and db.execute('SELECT count(*) FROM event').fetchone()[0] == 0
    activate(db)                                                       # and the connection is usable again
    assert db.execute('SELECT count(*) FROM catalogue_build').fetchone()[0] == 1
    db.close()


def test_activation_with_the_shipped_colour_mappings_keeps_both_colours_links_to_72(tmp_path):
    """Maersk Blue (313) is projected before Pastel Blue (1051); both are BrickLink 72, Pastel Blue is the inverse-preferred one."""
    colours = default()['colors'] + [('313', 'Maersk Blue', '0033B2', 'False'), ('1051', 'Pastel Blue', 'ABD9FF', 'False')]
    cat = tmp_path / 'catalogue.db'
    build(write_dump(tmp_path / 'd', colors=colours), cat, app_version='t', now=STAMP)                    # the repo's own mappings
    with closing(connect(tmp_path / 'brickwork.db', cat)) as db:
        activate(db)
        by_key = ids(cat, 'color')
        links = {r['color_id']: r['inverse_preferred'] for r in db.execute("SELECT color_id, inverse_preferred FROM color_link WHERE provider='bricklink' AND provider_key='72'")}
        assert links == {by_key['313']: 0, by_key['1051']: 1}
        assert identity._inverse_color(db, 'bricklink', '72') == by_key['1051']
        r = reconcile(db)
        assert 'colour_links' not in r['not_applied'] and not r['changes'].get('colour_links_inserted')


def test_the_fallback_colour_is_not_colour_1(world):
    x, y = world.id['3023'], world.id['3001']
    world.sql("UPDATE item_link SET status='manual', origin='user' WHERE item_id=?", x)                 # unscoped manual A = 3023
    world.sql("INSERT INTO item_link(item_id, color_id, provider, provider_kind, provider_key, status, method, origin, decided_at) "
              "VALUES(?, 1, 'bricklink', 'P', 'S1', 'inferred', 'x', 'shipped', ?)", x, STAMP)         # and a key scoped to colour 1
    assert identity.resolve_inverse(world.db, 'P', '3023', '5') == (x, 4)
    world.edit_cat(("INSERT INTO item_link(item_id, color_id, provider, provider_kind, provider_key, status, method, origin, preferred, evidence_digest, build_id)"
                    " VALUES(?, NULL, 'bricklink', 'P', '3023', 'matched', 'external_ids', 'shipped', 0, 'e', 1)", y))
    r = world.reconcile()
    assert [(e['reason'], e['direction'], e['item_id']) for e in r['not_applied']['links']] == [('would_change_resolution', 'inverse', y)]
    assert identity.resolve_inverse(world.db, 'P', '3023', '5') == (x, 4)


def prefer(world, key='3023', item_key='3023', origin='shipped'):
    """The collection's inferred link `key` is preferred (set by `origin`); the catalogue moves the preference to a new matched B."""
    item = world.id[item_key]
    world.sql("UPDATE item_link SET preferred=1, origin=? WHERE item_id=? AND provider_key=?", origin, item, key)
    world.edit_cat(("UPDATE item_link SET preferred=0 WHERE item_id=? AND provider_key=?", item, key),
                   ("INSERT INTO item_link(item_id, color_id, provider, provider_kind, provider_key, status, method, origin, preferred, evidence_digest, build_id)"
                    " VALUES(?, NULL, 'bricklink', 'P', 'B', 'matched', 'set_exception', 'shipped', 1, 'e', 1)", item))
    return item


def test_an_automatic_preferred_flag_follows_the_catalogue(world):
    item = prefer(world)
    assert identity.resolve(world.db, item, 4)[1] == '3023'
    r = world.reconcile()
    assert world.link('B')['preferred'] == 1 and world.link('3023')['preferred'] == 0 and identity.resolve(world.db, item, 4)[1] == 'B'
    assert r['changes']['preferred_moved'] == 1 and any(e['field'] == 'preferred' and e['new_value'] == '1' for e in world.events())
    again = world.reconcile()
    assert again['events'] == 0 and again['changes'] == {}


def test_a_preferred_flag_the_user_set_is_reported_not_moved(world):
    item = prefer(world, origin='user')
    r = world.reconcile()
    assert world.link('3023')['preferred'] == 1 and world.link('B')['preferred'] == 0 and identity.resolve(world.db, item, 4)[1] == '3023'
    assert [(x['reason'], x['collection_key'], x['catalogue_key']) for x in r['not_applied']['links']] == [('preferred_differs', '3023', 'B')]


def test_a_preferred_move_that_would_change_a_matched_baseline_answer_is_refused(world):
    item = world.id['3001']                                           # 3001 is matched; make it the preferred one
    world.sql("UPDATE item_link SET preferred=1 WHERE item_id=? AND provider_key='3001'", item)
    world.edit_cat(("UPDATE item_link SET preferred=0 WHERE item_id=? AND provider_key='3001'", item),
                   ("INSERT INTO item_link(item_id, color_id, provider, provider_kind, provider_key, status, method, origin, preferred, evidence_digest, build_id)"
                    " VALUES(?, NULL, 'bricklink', 'P', 'M2', 'matched', 'set_exception', 'shipped', 1, 'e', 1)", item))
    r = world.reconcile()
    assert world.link('3001', item_key='3001')['preferred'] == 1 and world.link('M2', item_key='3001')['preferred'] == 0
    assert [(x['reason'], x['action']) for x in r['not_applied']['links']] == [('would_change_resolution', 'prefer')]
    assert identity.resolve(world.db, item, 4)[1] == '3001'
