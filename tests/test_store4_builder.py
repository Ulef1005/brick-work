"""The catalogue builder: ids across a re-download, a lost catalogue, another install and adoption (design 3.1, 12: A1-A4),
kinds, refusals and the swap, all with invented dumps."""
from contextlib import closing
import fcntl
import hashlib
import json
import random
import sqlite3
import uuid

import pytest

from brickwork.store4 import identity
from brickwork.store4.builder import build
from brickwork.store4.connect import connect, now
from brickwork.store4.dump import HEADERS
from brickwork.store4.errors import BuildBusy, CatalogueMismatch, DumpError
from tests.store4_dump import INVENTORIES, default, write_dump

STAMP = '2026-10-23T12:00:00.000Z'


def run(tmp_path, name='d1', *, collection=None, target=None, **tables):
    dump = write_dump(tmp_path / name, **tables)
    target = target or tmp_path / 'catalogue.db'
    return build(dump, target, collection=collection, app_version='4.0.test', now=STAMP), target


def leftovers(tmp_path):
    """Files beside the catalogue other than the catalogue and its lock file: .new, .prev, journals."""
    return sorted(p.name for p in tmp_path.glob('catalogue.db*') if p.name not in ('catalogue.db', 'catalogue.db.lock'))


def rows(path, sql, *args):
    with closing(sqlite3.connect(f'file:{path}?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute(sql, args)]


def ids(path, table='item', key='born_key'):
    return {r[key]: r['id'] for r in rows(path, f'SELECT id, {key} FROM {table}')}


def shuffled(tables, seed=7):
    rng = random.Random(seed)
    return {k: rng.sample(v, len(v)) for k, v in tables.items()}


def activated(tmp_path, cat, ref_keys=('6081-1', '3023')):
    """A collection that activated build 1 of `cat`, projected `ref_keys` and bound the catalogue as activation would."""
    col = tmp_path / 'brickwork.db'
    with closing(connect(col, cat)) as db:
        meta = dict(db.execute('SELECT key, value FROM catalogue.meta').fetchall())
        for b in rows(cat, 'SELECT id, kind, mapping_version FROM build'):
            db.execute("INSERT INTO catalogue_build VALUES(?, ?, ?, ?, NULL, '{}')", (b['id'], b['kind'], b['mapping_version'], now()))
        for key in ref_keys:
            identity.project(db, ids(cat)[key])
        db.executemany('INSERT OR REPLACE INTO meta VALUES(?, ?)', [('catalogue_id', meta['catalogue_id']),
                       ('catalogue_item_high_water', meta['item_high_water']), ('catalogue_color_high_water', meta['color_high_water'])])
        db.commit()
    return col


# ---------- the first build ----------

def test_first_build_is_reproducible_and_shaped(tmp_path):
    report, cat = run(tmp_path)
    assert report['seeded_from'] == 'none' and report['build_id'] == 1
    (tmp_path / 'other').mkdir()
    _, cat2 = run(tmp_path, 'd1b', target=tmp_path / 'other' / 'catalogue.db')
    assert ids(cat) == ids(cat2)                                   # same dump, same ids (A3, ids half)
    assert ids(cat, 'color') == {'9999': 1, '-1': 2, '0': 3, '4': 4, '15': 5, '43': 6}
    # sets, then parts, then minifigures, each sorted by born key
    order = [r['born_key'] for r in rows(cat, 'SELECT born_key FROM item ORDER BY id')]
    assert order == ['5001-1', '5002-1', '5003-1', '5004-1', '6081-1', '9999-1', '3001', '3023', '970c03', 'fig-000001', 'fig-000002']
    meta = {r['key']: r['value'] for r in rows(cat, 'SELECT key, value FROM meta')}
    assert meta['schema_version'] == 'catalogue-4.0' and meta['item_high_water'] == '11' and meta['color_high_water'] == '6'
    assert str(uuid.UUID(meta['catalogue_id'])) == meta['catalogue_id'] and meta['created_at'] == STAMP
    b = rows(cat, 'SELECT * FROM build')[0]
    assert (b['kind'], b['seeded_from'], b['mapping_version'], b['app_version']) == ('rebrickable_dump', 'none', None, '4.0.test')
    files = json.loads(b['files_json'])
    assert [f['name'] for f in files] == [f'{n}.csv.gz' for n in HEADERS]
    assert all(len(f['sha256']) == 64 and f['bytes'] > 0 for f in files)
    assert {f['name']: f['rows'] for f in files}['sets.csv.gz'] == 6 and {f['name']: f['rows'] for f in files}['colors.csv.gz'] == 6
    counts = json.loads(b['counts_json'])
    assert (counts['items'], counts['sets'], counts['parts'], counts['minifigs'], counts['colours']) == (11, 6, 3, 2, 6)
    assert (counts['retired'], counts['adopted'], counts['new']) == (0, 0, 11)
    # lines: duplicate key summed, the line of an unknown part and the inventory of an unknown set skipped
    assert rows(cat, 'SELECT quantity FROM inventory_part WHERE inventory_id=1 AND item_id=?', ids(cat)['3023'])[0]['quantity'] == 3
    assert rows(cat, 'SELECT count(*) AS n FROM inventory')[0]['n'] == 4
    assert counts['skipped'] == {'inventory_parts': 1, 'elements': 1, 'part_relationships': 1}
    inv = rows(cat, 'SELECT * FROM inventory WHERE item_id=? ORDER BY version', ids(cat)['6081-1'])
    assert [(i['version'], i['ordinal'], i['is_latest']) for i in inv] == [(1, 1, 0), (2, 2, 1)]
    assert (inv[0]['part_lines'], inv[0]['figure_lines'], inv[0]['set_lines'], inv[0]['bl_digest']) == (2, 2, 0, None)
    assert rows(cat, 'SELECT url FROM picture_url')[0]['url'] == 'https://img/3023-red.jpg'
    assert rows(cat, "SELECT count(*) AS n FROM item_fts WHERE item_fts MATCH 'castle'")[0]['n'] == 1
    assert rows(cat, "SELECT count(*) AS n FROM item_fts WHERE item_fts MATCH '3023'")[0]['n'] == 1
    item = rows(cat, "SELECT * FROM item WHERE born_key='6081-1'")[0]
    assert (item['name_key'], item['size_key'], item['adopted'], item['build_id']) == ('king leo castle 12 x 4', '4x12', 0, 1)
    assert rows(cat, 'PRAGMA journal_mode')[0]['journal_mode'] == 'delete'
    assert not leftovers(tmp_path)                # no .new, no .prev on a first build


def test_kinds_by_namespace_and_theme(tmp_path):
    _, cat = run(tmp_path)
    kinds = {r['born_key']: (r['kind'], r['kind_source']) for r in rows(cat, 'SELECT * FROM item')}
    assert kinds['6081-1'] == ('set', 'namespace')
    assert kinds['5001-1'] == ('gear', 'theme')                     # theme 501 directly
    assert kinds['5002-1'] == ('gear', 'theme')                     # theme 9001 inherits 501
    assert kinds['5004-1'] == ('book', 'theme')
    assert kinds['5003-1'] == ('set', 'namespace')                  # no row in its ancestry
    assert kinds['3023'] == ('part', 'namespace') and kinds['fig-000001'] == ('minifigure', 'namespace')
    assert {r['id']: r['item_kind'] for r in rows(cat, 'SELECT id, item_kind FROM theme')} == {186: None, 501: 'gear', 9001: None, 9002: None, 497: 'book'}


def test_bricklink_corrected_kind_is_kept(tmp_path):
    _, cat = run(tmp_path)
    with closing(sqlite3.connect(cat)) as db:
        db.execute("UPDATE item SET kind='catalog', kind_source='bricklink' WHERE born_key='5001-1'")
        db.commit()
    run(tmp_path, 'd2')
    assert rows(cat, "SELECT kind, kind_source FROM item WHERE born_key='5001-1'") == [{'kind': 'catalog', 'kind_source': 'bricklink'}]


def test_a_kind_correction_only_the_collection_holds_survives_a_rebuild_against_an_older_catalogue(tmp_path):
    _, cat = run(tmp_path)                                               # the restored catalogue still has the theme guess
    col = activated(tmp_path, cat, ref_keys=('6081-1', '3023', '5001-1'))
    with closing(sqlite3.connect(col)) as db:
        db.execute("UPDATE item SET kind='catalog', kind_source='bricklink' WHERE born_key='5001-1'")
        db.commit()
    run(tmp_path, 'd2', collection=col)
    assert rows(cat, "SELECT kind, kind_source FROM item WHERE born_key='5001-1'") == [{'kind': 'catalog', 'kind_source': 'bricklink'}]


def test_incomplete_or_malformed_dump_names_the_file(tmp_path):
    dump = write_dump(tmp_path / 'd')
    (dump / 'themes.csv.gz').unlink()
    with pytest.raises(DumpError, match='themes.csv.gz'):
        build(dump, tmp_path / 'catalogue.db', app_version='x')
    write_dump(tmp_path / 'e', sets=[('only', 'one')])
    with pytest.raises(DumpError):
        build(tmp_path / 'e', tmp_path / 'catalogue.db', app_version='x')       # padded to width: a set row without a year
    assert not [n for n in leftovers(tmp_path) if n != 'catalogue.db']


# ---------- A1: re-download ----------

def test_a1_redownload_keeps_ids_retires_and_revives(tmp_path):
    first, cat = run(tmp_path)
    ids1, colours1 = ids(cat), ids(cat, 'color')
    t = default()
    t['sets'] = [s for s in t['sets'] if s[0] != '9999-1']                              # one key vanishes
    t['inventories'] = [i for i in t['inventories'] if i[2] != '9999-1']
    t['inventory_sets'] = []
    t['sets'].append(('7000-1', 'New Set 4 x 4', '2020', '186', '9', ''))               # one is new
    t['parts'] = [p for p in t['parts'] if p[0] != '3001']                              # a part vanishes, its lines are skipped
    t['inventory_parts'] = [p for p in t['inventory_parts'] if p[1] != '3001']
    t['elements'] = [e for e in t['elements'] if e[1] != '3001']
    t['part_relationships'] = []
    t['themes'] = [x for x in t['themes'] if x[0] != '9002']
    t['sets'] = [s if s[0] != '5003-1' else ('5003-1', s[1], s[2], '186', s[4], s[5]) for s in t['sets']]
    second, _ = run(tmp_path, 'd2', **shuffled(t))
    ids2 = ids(cat)
    assert all(ids2[k] == v for k, v in ids1.items())                                   # every key keeps its id
    assert ids2['7000-1'] == first['item_high_water'] + 1 == 12
    assert second['item_high_water'] == 12
    old = {r['born_key']: r for r in rows(cat, 'SELECT * FROM item')}
    assert old['9999-1']['retired_at'] == STAMP and old['9999-1']['build_id'] == 1      # retired, last known fields, its old build
    assert old['3001']['retired_at'] and old['6081-1']['retired_at'] is None and old['6081-1']['build_id'] == 2
    assert rows(cat, 'SELECT retired_at FROM theme WHERE id=9002')[0]['retired_at'] == STAMP
    meta = {r['key']: r['value'] for r in rows(cat, 'SELECT key, value FROM meta')}
    assert meta['catalogue_id'] == first['catalogue_id']
    builds = rows(cat, 'SELECT id, seeded_from FROM build ORDER BY id')
    assert builds == [{'id': 1, 'seeded_from': 'none'}, {'id': 2, 'seeded_from': 'catalogue'}]
    assert (tmp_path / 'catalogue.db.prev').exists()
    assert ids(tmp_path / 'catalogue.db.prev') == ids1 and not (tmp_path / 'catalogue.db.new').exists()
    # the vanished set's inventory is carried with its lines and marked retired; its parent is retired, not deleted
    gone = rows(cat, 'SELECT * FROM inventory WHERE item_id=?', ids1['9999-1'])
    assert len(gone) == 1 and gone[0]['retired_at'] == STAMP and gone[0]['build_id'] == 1
    assert rows(cat, 'SELECT count(*) AS n FROM inventory_part WHERE inventory_id=?', gone[0]['id'])[0]['n'] == 1
    assert rows(cat, 'SELECT count(*) AS n FROM inventory_set WHERE inventory_id=?', gone[0]['id'])[0]['n'] == 1
    # a vanished colour: drop Red, then bring the sets back
    t3 = default()
    t3['colors'] = [c for c in t3['colors'] if c[0] != '4']
    t3['inventory_parts'] = [p for p in t3['inventory_parts'] if p[2] != 4]
    t3['elements'] = [e for e in t3['elements'] if e[2] != 4]
    run(tmp_path, 'd3', **t3)
    assert rows(cat, "SELECT retired_at FROM color WHERE born_key='4'")[0]['retired_at'] == STAMP
    third, _ = run(tmp_path, 'd4')                                                       # the original dump again: everything returns
    back = ids(cat)
    assert back['9999-1'] == ids1['9999-1'] and back['3001'] == ids1['3001'] and ids(cat, 'color') == colours1
    assert [r['born_key'] for r in rows(cat, 'SELECT born_key FROM item WHERE retired_at IS NOT NULL')] == ['7000-1']
    assert rows(cat, 'SELECT count(*) AS n FROM color WHERE retired_at IS NOT NULL')[0]['n'] == 0
    assert third['item_high_water'] == 12                                                # never decreases; 7000-1 is retired now
    assert rows(cat, "SELECT retired_at FROM item WHERE born_key='7000-1'")[0]['retired_at'] == STAMP
    assert rows(cat, 'PRAGMA foreign_key_check') == [] and len(rows(cat, 'SELECT id FROM build')) == 4


def test_a_retired_row_keeps_its_first_retired_at(tmp_path):
    _, cat = run(tmp_path)
    t = default()
    t['sets'] = [s for s in t['sets'] if s[0] != '9999-1']
    t['inventories'] = [i for i in t['inventories'] if i[2] != '9999-1']
    t['inventory_sets'] = []
    build(write_dump(tmp_path / 'd2', **t), cat, app_version='x', now='2026-10-24T00:00:00.000Z')
    build(write_dump(tmp_path / 'd3', **t), cat, app_version='x', now='2026-10-25T00:00:00.000Z')
    assert rows(cat, "SELECT retired_at FROM item WHERE born_key='9999-1'")[0]['retired_at'] == '2026-10-24T00:00:00.000Z'


def test_a_vanished_inventory_version_is_carried_and_latest_stays_unique(tmp_path):
    _, cat = run(tmp_path)
    t = default()
    t['inventories'] = [i for i in t['inventories'] if i[:2] != (2, 2)]       # version 2 of 6081-1 vanishes
    t['inventory_parts'] = [p for p in t['inventory_parts'] if p[0] != 2]
    run(tmp_path, 'd2', **t)
    inv = rows(cat, 'SELECT * FROM inventory WHERE item_id=? ORDER BY version', ids(cat)['6081-1'])
    assert [(i['version'], i['is_latest'], i['retired_at'] is not None) for i in inv] == [(1, 1, False), (2, 0, True)]
    assert rows(cat, 'SELECT count(*) AS n FROM inventory_part WHERE inventory_id=?', inv[1]['id'])[0]['n'] == 2


# ---------- A2: the catalogue is lost ----------

def test_a2_catalogue_lost_rebuild_from_the_collection(tmp_path):
    _, cat = run(tmp_path)
    col = activated(tmp_path, cat)
    kept = ids(cat)
    with closing(connect(col, cat)) as db:
        meta = dict(db.execute('SELECT key, value FROM meta').fetchall())
        referenced = {r[0]: r[1] for r in db.execute('SELECT born_key, id FROM item')}
    assert set(referenced) == {'6081-1', '3023'}
    cat.unlink()
    (tmp_path / 'catalogue.db.prev').unlink(missing_ok=True)
    t = shuffled(default(), 3)
    report, _ = run(tmp_path, 'd2', collection=col, **t)
    assert report['seeded_from'] == 'collection'
    after = ids(cat)
    assert all(after[k] == v for k, v in referenced.items())
    assert {after[k] for k in after if k not in referenced}.isdisjoint(referenced.values())
    unreferenced = [v for k, v in after.items() if k not in referenced]
    assert all(v > int(meta['catalogue_item_high_water']) for v in unreferenced)
    assert rows(cat, "SELECT value FROM meta WHERE key='catalogue_id'")[0]['value'] == meta['catalogue_id']
    placeholders = rows(cat, 'SELECT * FROM build ORDER BY id')
    assert [b['id'] for b in placeholders] == [1, 2] and 'placeholder' in placeholders[0]['note'] and placeholders[1]['seeded_from'] == 'collection'
    with closing(connect(col, cat)):                              # attaches: id, builds and high-water marks agree
        pass
    assert rows(cat, 'PRAGMA foreign_key_check') == []


# ---------- A3: another install ----------

def test_a3_another_install_has_a_new_catalogue_id_and_the_same_ids(tmp_path):
    (tmp_path / 'b').mkdir()
    first, cat = run(tmp_path)
    second, other = run(tmp_path, 'd2', target=tmp_path / 'b' / 'catalogue.db')
    assert first['catalogue_id'] != second['catalogue_id']
    assert ids(cat) == ids(other) and ids(cat, 'color') == ids(other, 'color')


# ---------- A4: adoption ----------

def local_item(db, id_, key, ns='sets', kind='set'):
    db.execute("INSERT INTO item(id, origin, kind, kind_source, name, born_provider, born_namespace, born_key, created_at, updated_at)"
               " VALUES(?, 'local', ?, 'namespace', 'Fetched Set', 'rebrickable', ?, ?, ?, ?)", (id_, kind, ns, key, STAMP, STAMP))


def test_a4_a_local_item_is_adopted_by_the_next_build(tmp_path):
    t = default()
    t['sets'] = [s for s in t['sets'] if s[0] != '9999-1']
    t['inventories'] = [i for i in t['inventories'] if i[2] != '9999-1']
    t['inventory_sets'] = []
    first, cat = run(tmp_path, **t)
    col = activated(tmp_path, cat)
    with closing(connect(col, cat)) as db:
        local_item(db, 1_000_000_003, '9999-1')
        db.commit()
    hw = first['item_high_water']
    report, _ = run(tmp_path, 'd2', collection=col)                  # the new dump has 9999-1
    row = rows(cat, "SELECT id, adopted, kind_source FROM item WHERE born_key='9999-1'")[0]
    assert (row['id'], row['adopted']) == (1_000_000_003, 1)
    assert report['counts']['adopted'] == 1 and report['item_high_water'] == hw      # not counted in the high-water mark
    run(tmp_path, 'd3')                                                    # and it stays adopted on a later rebuild
    assert rows(cat, "SELECT id, adopted FROM item WHERE born_key='9999-1'")[0] == {'id': 1_000_000_003, 'adopted': 1}
    with closing(connect(col, cat)):
        pass


def test_a_local_item_the_dump_lacks_stays_local(tmp_path):
    _, cat = run(tmp_path)
    col = activated(tmp_path, cat)
    with closing(connect(col, cat)) as db:
        local_item(db, 1_000_000_001, '1111-1')
        db.commit()
    run(tmp_path, 'd2', collection=col)
    assert rows(cat, "SELECT count(*) AS n FROM item WHERE born_key='1111-1'")[0]['n'] == 0


def test_a_local_item_the_catalogue_already_numbers_is_reported(tmp_path):
    _, cat = run(tmp_path)                                               # the catalogue has 9999-1 already
    col = activated(tmp_path, cat)
    catalogue_id = rows(cat, "SELECT id FROM item WHERE born_key='9999-1'")[0]['id']
    with closing(connect(col, cat)) as db:                               # fetched locally without projecting it
        local_item(db, 1_000_000_003, '9999-1')
        db.commit()
    report, _ = run(tmp_path, 'd2', collection=col)
    assert rows(cat, "SELECT id, adopted FROM item WHERE born_key='9999-1'")[0] == {'id': catalogue_id, 'adopted': 0}
    assert report['counts']['adopted'] == 0
    assert report['counts']['shadowed_local'] == [dict(namespace='sets', born_key='9999-1', local_id=1_000_000_003,
                                                       catalogue_id=catalogue_id)]


# ---------- refusals and the swap ----------

def test_refuses_conflicting_seeds(tmp_path):
    _, cat = run(tmp_path)
    col = activated(tmp_path, cat)
    with closing(sqlite3.connect(col)) as db:                       # the same key under another id
        db.execute("UPDATE item SET id=900 WHERE born_key='3023'")
        db.execute("UPDATE meta SET value='1000' WHERE key='catalogue_item_high_water'")
        db.commit()
    before = cat.read_bytes()
    with pytest.raises(CatalogueMismatch, match='3023'):
        run(tmp_path, 'd2', collection=col)
    assert cat.read_bytes() == before and not leftovers(tmp_path)


def test_refuses_one_id_for_two_keys(tmp_path):
    _, cat = run(tmp_path)
    col = activated(tmp_path, cat)
    with closing(sqlite3.connect(col)) as db:
        other = ids(cat)['3001']
        db.execute("UPDATE item SET id=? WHERE born_key='3023'", (other,))
        db.commit()
    with pytest.raises(CatalogueMismatch, match='id'):
        run(tmp_path, 'd2', collection=col)


def test_refuses_another_catalogue_id(tmp_path):
    _, cat = run(tmp_path)
    col = activated(tmp_path, cat)
    with closing(sqlite3.connect(col)) as db:
        db.execute("UPDATE meta SET value='someone-else' WHERE key='catalogue_id'")
        db.commit()
    with pytest.raises(CatalogueMismatch, match='another catalogue'):
        run(tmp_path, 'd2', collection=col)


def test_refuses_an_id_above_the_high_water_mark(tmp_path):
    _, cat = run(tmp_path)
    col = activated(tmp_path, cat)
    with closing(sqlite3.connect(col)) as db:
        db.execute("UPDATE meta SET value='3' WHERE key='catalogue_item_high_water'")
        db.commit()
    with pytest.raises(CatalogueMismatch, match='high'):
        run(tmp_path, 'd2', collection=col)
    with closing(sqlite3.connect(cat)) as db:
        db.execute("UPDATE meta SET value='3' WHERE key='item_high_water'")
        db.commit()
    with pytest.raises(CatalogueMismatch, match='old catalogue'):
        run(tmp_path, 'd3')


def test_a_failure_before_the_swap_leaves_the_old_file_and_no_new(tmp_path, monkeypatch):
    _, cat = run(tmp_path)
    before = cat.read_bytes()
    (tmp_path / 'catalogue.db.new').write_bytes(b'stale')
    monkeypatch.setattr('brickwork.store4.builder.LAYERS', [lambda db, ctx: 1 / 0])
    with pytest.raises(ZeroDivisionError):
        run(tmp_path, 'd2')
    assert cat.read_bytes() == before and not leftovers(tmp_path)
    # a broken foreign key is refused after the load, before the swap
    t = default()
    t['sets'] = [s if s[0] != '6081-1' else ('6081-1', s[1], s[2], '12345', s[4], s[5]) for s in t['sets']]
    monkeypatch.setattr('brickwork.store4.builder.LAYERS', [])
    with pytest.raises(CatalogueMismatch, match='foreign keys'):
        run(tmp_path, 'd3', **t)
    assert cat.read_bytes() == before and not leftovers(tmp_path)


def test_the_build_never_writes_the_collection(tmp_path):
    _, cat = run(tmp_path)
    col = activated(tmp_path, cat)
    with closing(sqlite3.connect(col)) as db:
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    before = col.read_bytes()
    run(tmp_path, 'd2', collection=col)
    assert col.read_bytes() == before


def test_the_built_file_is_clean_and_attachable(tmp_path):
    _, cat = run(tmp_path)
    assert rows(cat, 'PRAGMA foreign_key_check') == [] and rows(cat, 'PRAGMA integrity_check') == [{'integrity_check': 'ok'}]
    col = activated(tmp_path, cat)
    with closing(connect(col, cat, read_only=True)) as db:
        assert db.execute('SELECT count(*) FROM catalogue.item').fetchone()[0] == 11


# ---------- review fixes ----------

def test_a_second_builder_is_refused_and_touches_nothing(tmp_path):
    _, cat = run(tmp_path)
    before = cat.read_bytes()
    (tmp_path / 'catalogue.db.new').write_bytes(b'someone elses build')
    with open(tmp_path / 'catalogue.db.lock', 'a') as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BuildBusy, match='another catalogue build'):
            run(tmp_path, 'd2')
    assert cat.read_bytes() == before and (tmp_path / 'catalogue.db.new').read_bytes() == b'someone elses build'
    (tmp_path / 'catalogue.db.new').unlink()
    run(tmp_path, 'd3')                                              # the lock is released after a build


def test_the_target_never_disappears_during_the_swap(tmp_path, monkeypatch):
    _, cat = run(tmp_path)
    old = cat.read_bytes()
    seen = []
    real = __import__('os').replace

    def watching(src, dst):
        seen.append((cat.exists(), cat.read_bytes() == old))
        return real(src, dst)

    monkeypatch.setattr('brickwork.store4.builder.os.replace', watching)
    run(tmp_path, 'd2')
    assert seen and all(present for present, _ in seen) and seen[-1][1]      # present at every step, old until the last rename
    assert (tmp_path / 'catalogue.db.prev').read_bytes() == old and cat.read_bytes() != old
    assert leftovers(tmp_path) == ['catalogue.db.prev']


def test_a_merged_local_item_is_never_adopted(tmp_path):
    t = default()
    t['sets'] = [s for s in t['sets'] if s[0] != '9999-1']
    t['inventories'] = [i for i in t['inventories'] if i[2] != '9999-1']
    t['inventory_sets'] = []
    _, cat = run(tmp_path, **t)
    col = activated(tmp_path, cat)
    with closing(connect(col, cat)) as db:
        local_item(db, 1_000_000_003, '9999-1')
        local_item(db, 1_000_000_004, '8888-1')
        db.execute("UPDATE item SET merged_into=(SELECT id FROM item WHERE born_key='6081-1') WHERE id IN (1000000003, 1000000004)")
        db.commit()
    t2 = default()
    t2['sets'].append(('8888-1', 'Other 1 x 1', '2000', '186', '1', ''))
    report, _ = run(tmp_path, 'd2', collection=col, **t2)
    got = rows(cat, "SELECT id, adopted FROM item WHERE born_key IN ('9999-1', '8888-1') ORDER BY born_key")
    assert all(r['id'] < 1_000_000_000 and r['adopted'] == 0 for r in got) and len(got) == 2
    assert report['counts']['adopted'] == 0
    assert sorted((m['born_key'], m['local_id']) for m in report['counts']['merged_local']) == [('8888-1', 1_000_000_004), ('9999-1', 1_000_000_003)]
    assert all(m['catalogue_id'] < 1_000_000_000 for m in report['counts']['merged_local'])


def merge_away(col, cat, key, into='6081-1'):
    with closing(connect(col, cat)) as db:
        db.execute("UPDATE item SET catalogue_retired_at=? WHERE born_key=?", (STAMP, key))
        db.execute("UPDATE item SET merged_into=(SELECT id FROM item WHERE born_key=?) WHERE born_key=?", (into, key))
        db.commit()


def test_an_adopted_local_item_merged_before_reconcile_is_numbered_afresh(tmp_path):
    t = default()
    t['sets'] = [s for s in t['sets'] if s[0] != '9999-1']
    t['inventories'] = [i for i in t['inventories'] if i[2] != '9999-1']
    t['inventory_sets'] = []
    _, cat = run(tmp_path, **t)
    col = activated(tmp_path, cat)
    with closing(connect(col, cat)) as db:
        local_item(db, 1_000_000_003, '9999-1')
        db.commit()
    run(tmp_path, 'd2', collection=col)                                # adopted: the catalogue row has id 1,000,000,003
    assert ids(cat)['9999-1'] == 1_000_000_003
    with closing(connect(col, cat)) as db:                               # merged before reconcile flipped its origin
        db.execute("UPDATE item SET merged_into=(SELECT id FROM item WHERE born_key='6081-1') WHERE id=1000000003")
        db.commit()
    report, _ = run(tmp_path, 'd3', collection=col)
    assert ids(cat)['9999-1'] < 1_000_000_000
    assert rows(cat, 'SELECT count(*) AS n FROM item WHERE id=1000000003')[0]['n'] == 0
    assert [m['local_id'] for m in report['counts']['merged_local']] == [1_000_000_003]
    assert rows(cat, 'PRAGMA foreign_key_check') == []


def test_an_adopted_item_merged_before_reconcile_whose_key_vanishes_is_carried_retired(tmp_path):
    t = default()
    t['sets'] = [s for s in t['sets'] if s[0] != '9999-1']
    t['inventories'] = [i for i in t['inventories'] if i[2] != '9999-1']
    t['inventory_sets'] = []
    _, cat = run(tmp_path, **t)
    col = activated(tmp_path, cat)
    with closing(connect(col, cat)) as db:
        local_item(db, 1_000_000_003, '9999-1')
        db.commit()
    run(tmp_path, 'd2', collection=col)                                # adopted, with its inventory
    with closing(connect(col, cat)) as db:
        db.execute("UPDATE item SET merged_into=(SELECT id FROM item WHERE born_key='6081-1') WHERE id=1000000003")
        db.commit()
    run(tmp_path, 'd3', collection=col, **t)                           # and its key leaves the dump
    assert rows(cat, "SELECT id, retired_at FROM item WHERE born_key='9999-1'") == [{'id': 1_000_000_003, 'retired_at': STAMP}]
    assert rows(cat, 'SELECT retired_at FROM inventory WHERE item_id=1000000003') == [{'retired_at': STAMP}]
    assert rows(cat, 'PRAGMA foreign_key_check') == []
    run(tmp_path, 'd4', collection=col, **t)                           # and the next build still works
    assert rows(cat, 'PRAGMA foreign_key_check') == []


def test_a_merge_committed_during_the_build_stops_the_swap(tmp_path, monkeypatch):
    from brickwork.store4 import builder
    _, cat = run(tmp_path)
    col = activated(tmp_path, cat, ref_keys=('6081-1', '3023', '3001'))
    before = cat.read_bytes()
    real = builder._build_new

    def merge_meanwhile(*args, **kwargs):
        report = real(*args, **kwargs)
        with closing(sqlite3.connect(col)) as db:                       # another writer merges 3023 while the build runs
            db.execute("UPDATE item SET catalogue_retired_at=? WHERE born_key='3023'", (STAMP,))
            db.execute("UPDATE item SET merged_into=(SELECT id FROM item WHERE born_key='3001') WHERE born_key='3023'")
            db.commit()
        return report

    monkeypatch.setattr(builder, '_build_new', merge_meanwhile)
    with pytest.raises(CatalogueMismatch, match='merged in the collection while'):
        run(tmp_path, 'd2', collection=col)
    assert cat.read_bytes() == before and leftovers(tmp_path) == []


def test_a_merged_catalogue_item_keeps_its_retired_row_but_gets_a_fresh_id_when_it_returns(tmp_path):
    _, cat = run(tmp_path)
    col = activated(tmp_path, cat, ref_keys=('6081-1', '3023', '9999-1'))
    gone = ids(cat)['9999-1']
    merge_away(col, cat, '9999-1')
    t = default()
    t['sets'] = [s for s in t['sets'] if s[0] != '9999-1']
    t['inventories'] = [i for i in t['inventories'] if i[2] != '9999-1']
    t['inventory_sets'] = []
    kept, _ = run(tmp_path, 'd2', collection=col, **t)
    assert kept['counts']['merged_returning'] == []
    assert rows(cat, "SELECT id, retired_at FROM item WHERE born_key='9999-1'") == [{'id': gone, 'retired_at': STAMP}]
    back, _ = run(tmp_path, 'd3', collection=col)
    row = rows(cat, "SELECT id, retired_at FROM item WHERE born_key='9999-1'")[0]
    assert row['id'] > back['counts']['items'] and row['id'] != gone and row['retired_at'] is None
    assert back['counts']['merged_returning'] == [dict(namespace='sets', born_key='9999-1', merged_id=gone,
                                                       merged_into=ids(cat)['6081-1'], new_id=row['id'])]
    assert back['item_high_water'] >= row['id'] and rows(cat, 'PRAGMA foreign_key_check') == []
    assert rows(cat, 'SELECT count(*) AS n FROM item WHERE id=?', gone)[0]['n'] == 0     # no row names the merged id
    assert rows(cat, 'SELECT count(*) AS n FROM inventory WHERE item_id=?', gone)[0]['n'] == 0
    again, _ = run(tmp_path, 'd4', collection=col)                     # the next build keeps the replacement id
    assert ids(cat)['9999-1'] == row['id'] and again['counts']['new_items'] == 0
    assert rows(cat, 'PRAGMA foreign_key_check') == []


def stored_digests_match(cat):
    """Every inventory's digest is the sha256 of its lines in Brick Work ids, as the builder computes it."""
    for inv in rows(cat, 'SELECT id, digest FROM inventory'):
        lines = ([('p', *tuple(r.values())) for r in rows(cat, 'SELECT item_id, color_id, is_spare, quantity FROM inventory_part WHERE inventory_id=?', inv['id'])]
                 + [('f', r['item_id'], 0, 0, r['quantity']) for r in rows(cat, 'SELECT item_id, quantity FROM inventory_figure WHERE inventory_id=?', inv['id'])]
                 + [('s', r['item_id'], 0, 0, r['quantity']) for r in rows(cat, 'SELECT item_id, quantity FROM inventory_set WHERE inventory_id=?', inv['id'])])
        assert inv['digest'] == hashlib.sha256(repr(sorted(lines)).encode()).hexdigest(), inv['id']


def test_a_carried_inventory_naming_a_returned_merged_part_is_repointed_and_rehashed(tmp_path):
    _, cat = run(tmp_path)
    col = activated(tmp_path, cat, ref_keys=('6081-1', '3023', '3001'))
    gone = ids(cat)['3001']
    without_inv3 = dict(inventories=[i for i in INVENTORIES if i[0] != 3], inventory_sets=[])
    t = default()
    t.update(without_inv3, parts=[p for p in t['parts'] if p[0] != '3001'], part_relationships=[],
             inventory_parts=[p for p in t['inventory_parts'] if p[1] != '3001' and p[0] != 3],
             elements=[e for e in t['elements'] if e[1] != '3001'])
    run(tmp_path, 'd2', **t)                                            # 3001 retires; 9999-1 v1 (which uses it) is carried
    merge_away(col, cat, '3001', into='3023')
    t = default()
    t.update(without_inv3, inventory_parts=[p for p in t['inventory_parts'] if p[0] != 3])
    run(tmp_path, 'd3', collection=col, **t)                            # 3001 returns; 9999-1 v1 is still carried
    new = ids(cat)['3001']
    carried = rows(cat, 'SELECT id FROM inventory WHERE item_id=? AND retired_at IS NOT NULL', ids(cat)['9999-1'])
    assert len(carried) == 1 and new != gone
    assert rows(cat, 'SELECT item_id FROM inventory_part WHERE inventory_id=?', carried[0]['id']) == [{'item_id': new}]
    stored_digests_match(cat)
    assert rows(cat, 'PRAGMA foreign_key_check') == []


def test_a_merged_part_that_returns_in_an_inventory_is_numbered_afresh(tmp_path):
    _, cat = run(tmp_path)
    col = activated(tmp_path, cat, ref_keys=('6081-1', '3023', '3001'))
    gone = ids(cat)['3001']
    t = default()
    t['parts'] = [p for p in t['parts'] if p[0] != '3001']
    t['inventory_parts'] = [p for p in t['inventory_parts'] if p[1] != '3001']
    t['elements'] = [e for e in t['elements'] if e[1] != '3001']
    t['part_relationships'] = []
    run(tmp_path, 'd2', **t)                                            # 3001 retires (the collection learns of it)
    with closing(connect(col, cat)) as db:
        db.execute("UPDATE item SET catalogue_retired_at=? WHERE born_key='3001'", (STAMP,))
        db.execute("UPDATE item SET merged_into=(SELECT id FROM item WHERE born_key='3023') WHERE born_key='3001'")
        db.commit()
    report, _ = run(tmp_path, 'd3', collection=col)                     # the full dump again: 3001 is used in inventories
    new = ids(cat)['3001']
    assert new != gone and report['counts']['merged_returning'][0]['merged_id'] == gone
    assert rows(cat, 'SELECT count(*) AS n FROM inventory_part WHERE item_id=?', gone)[0]['n'] == 0
    assert rows(cat, 'SELECT count(*) AS n FROM inventory_part WHERE item_id=?', new)[0]['n'] >= 1
    assert rows(cat, 'SELECT count(*) AS n FROM item WHERE id=?', gone)[0]['n'] == 0
    assert rows(cat, 'PRAGMA foreign_key_check') == []


def test_inventory_ordinals_are_unique_over_live_and_carried_versions(tmp_path):
    t = default()
    t['inventories'] = t['inventories'] + [(6, 3, '6081-1')]
    _, cat = run(tmp_path, **t)
    t2 = default()
    t2['inventories'] = [i for i in t2['inventories'] if i[:2] != (2, 2)] + [(6, 3, '6081-1')]     # version 2 vanishes
    run(tmp_path, 'd2', **t2)
    inv = rows(cat, 'SELECT version, ordinal, is_latest, retired_at FROM inventory WHERE item_id=? ORDER BY version', ids(cat)['6081-1'])
    assert [(i['version'], i['ordinal'], i['is_latest'], i['retired_at'] is not None) for i in inv] == [
        (1, 1, 0, False), (2, 2, 0, True), (3, 3, 1, False)]


def test_build_ids_account_for_builds_the_old_catalogue_lacks(tmp_path):
    _, cat = run(tmp_path)
    col = activated(tmp_path, cat)
    with closing(sqlite3.connect(col)) as db:                      # the collection activated builds 2 and 3 of a newer catalogue
        db.executemany("INSERT INTO catalogue_build VALUES(?, 'mapping', 'm2', ?, NULL, '{}')", [(2, STAMP), (3, STAMP)])
        db.commit()
    report, _ = run(tmp_path, 'd2', collection=col)
    assert report['build_id'] == 4 and report['seeded_from'] == 'catalogue'
    builds = rows(cat, 'SELECT id, kind, mapping_version, note FROM build ORDER BY id')
    assert [b['id'] for b in builds] == [1, 2, 3, 4]
    assert [(b['kind'], b['mapping_version']) for b in builds[1:3]] == [('mapping', 'm2')] * 2
    assert all('placeholder' in b['note'] for b in builds[1:3]) and builds[0]['note'] is None
    with closing(connect(col, cat)):
        pass


def test_the_collection_is_read_in_one_snapshot(tmp_path, monkeypatch):
    _, cat = run(tmp_path)
    col = activated(tmp_path, cat)
    from brickwork.store4 import seeds as seeds_module
    real = seeds_module._rows
    calls = []

    def activating_between_reads(db, sql, *args):
        out = real(db, sql, *args)
        if not calls:                                    # an activation commits after the items were read
            calls.append(sql)
            with closing(sqlite3.connect(col)) as other:
                other.execute("INSERT INTO catalogue_build VALUES(99, 'mapping', NULL, ?, NULL, '{}')", (STAMP,))
                other.commit()
        return out

    monkeypatch.setattr(seeds_module, '_rows', activating_between_reads)
    seed = seeds_module.CollectionSeed(col)
    assert calls and 99 not in [b['id'] for b in seed.builds]
    assert 99 in [r['id'] for r in rows(col, 'SELECT id FROM catalogue_build')]


def test_the_fingerprints_describe_the_bytes_that_are_loaded(tmp_path):
    from brickwork.store4.dump import Dump
    dump = Dump(write_dump(tmp_path / 'd'))
    recorded = {f['name']: f['sha256'] for f in dump.files()}
    other = write_dump(tmp_path / 'e', sets=[('0000-1', 'Replaced', '2000', '186', '1', '')])
    (tmp_path / 'd' / 'sets.csv.gz').write_bytes((other / 'sets.csv.gz').read_bytes())     # replaced after Dump() was constructed
    loaded = list(dump.rows('sets'))
    assert [r[0] for r in loaded][0] == '6081-1' and len(loaded) == 6
    assert dump.files()[[f['name'] for f in dump.files()].index('sets.csv.gz')]['sha256'] == recorded['sets.csv.gz']
    assert recorded['sets.csv.gz'] != __import__('hashlib').sha256((tmp_path / 'd' / 'sets.csv.gz').read_bytes()).hexdigest()
