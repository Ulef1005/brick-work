"""#551: Added via and Last synced from (schema 4.8, ADR 0039). Every route that makes a copy, a loose-stock row or a wish records how it
arrived and the value never changes; a pull records the rows it matched and its Undo takes that back; a 4.7 file upgrades with every row
NULL ("Before this release"); a kind move keeps both; the API serves both read only. Invented data against the fake sites of test_bw_sync."""
from contextlib import closing
import json
import re
import sqlite3
from pathlib import Path

import pytest

from brickwork.core import collection, stock, sync
from brickwork.core.transaction import transaction
from brickwork.store4 import origins
from brickwork.store4.connect import HERE, SCHEMA_VERSION, connect, upgrade
from brickwork.store4.errors import Store4Error
from tests.test_bw_sync import GEAR, Brickset, HASH, live_copies, rebrickable_ready, store  # noqa: F401
from tests.test_bw_sync import pair  # noqa: F401

ROOT = Path(__file__).parent.parent


def added_via(db, table):
    return {r[0]: r[1] for r in db.execute(f'SELECT id, added_via FROM {table}')}


def synced(db):
    return sorted(tuple(r) for r in db.execute(
        "SELECT CASE WHEN copy_id IS NOT NULL THEN 'copy' WHEN stock_id IS NOT NULL THEN 'stock' ELSE 'wish' END, site, list_key FROM synced_from"))


# --- the schema ---------------------------------------------------------------------------------

def test_the_origin_table_holds_exactly_the_origins_the_code_knows(store):
    assert dict(store.execute('SELECT id, kind FROM origin').fetchall()) == origins.ORIGINS
    assert set(origins.LABELS) == set(origins.ORIGINS) | {None}


def test_a_47_store_upgrades_with_every_row_null_and_matches_a_fresh_one(tmp_path):
    old = tmp_path / 'old.db'
    with closing(sqlite3.connect(old)) as db:
        db.executescript((HERE / 'brickwork.sql').read_text().split('-- Where a row came from, schema 4.8')[0])
        db.execute("INSERT INTO meta(key,value) VALUES('schema_version','4.7')")
        db.execute("INSERT INTO item(id, origin, kind, kind_source, born_provider, born_namespace, born_key, name, created_at, updated_at) "
                   "VALUES(1, 'catalogue', 'set', 'namespace', 'rebrickable', 'sets', '1-1', 'Old set', 'x', 'x')")
        db.execute("INSERT INTO copy(id, item_id, inventory_source, created_at, updated_at) VALUES('old', 1, 'none', 'x', 'x')")
        db.commit()
    assert upgrade(old) == upgrade(old) == SCHEMA_VERSION == '4.8'
    with closing(connect(old, tmp_path / 'catalogue.db')) as upgraded, closing(connect(tmp_path / 'new.db', tmp_path / 'catalogue.db')) as fresh:
        assert dict(upgraded.execute('SELECT key,value FROM meta'))['upgraded_to_4.8'].endswith('Z')
        for name in ('copy', 'stock', 'wish', 'origin', 'synced_from', 'copy_added_via_fixed', 'synced_from_key'):
            defs = [db.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()[0] for db in (upgraded, fresh)]
            assert defs[0] == defs[1], name
        assert upgraded.execute("SELECT added_via FROM copy WHERE id='old'").fetchone()[0] is None
        assert origins.label(None) == 'Before this release'


def test_added_via_never_changes(store):
    copy_id = live_copies(store, '2070-1')[0]['id']
    assert store.execute('SELECT added_via FROM copy WHERE id=?', (copy_id,)).fetchone()[0] == 'hand'
    for value in ('rebrickable', None):
        with pytest.raises(sqlite3.IntegrityError, match='added_via never changes'):
            store.execute('UPDATE copy SET added_via=? WHERE id=?', (value, copy_id))
    store.execute("UPDATE copy SET note='still fine' WHERE id=?", (copy_id,))            # any other change passes the trigger
    with pytest.raises(sqlite3.IntegrityError):
        store.execute("INSERT INTO copy(id, item_id, inventory_source, created_at, updated_at, added_via) "
                      "SELECT 'x', item_id, 'none', 'x', 'x', 'nowhere' FROM copy LIMIT 1")        # only a known origin


def test_a_synced_from_row_names_exactly_one_row(store):
    copy_id = live_copies(store, '2070-1')[0]['id']
    with pytest.raises(sqlite3.IntegrityError):
        store.execute("INSERT INTO synced_from(site, synced_at) VALUES('rebrickable', 'x')")
    with pytest.raises(sqlite3.IntegrityError):
        store.execute("INSERT INTO synced_from(copy_id, wish_id, site, synced_at) VALUES(?, ?, 'rebrickable', 'x')", (copy_id, copy_id))
    store.execute("INSERT INTO synced_from(copy_id, site, synced_at) VALUES(?, 'rebrickable', 'x')", (copy_id,))
    with pytest.raises(sqlite3.IntegrityError):                                          # one row per site and list
        store.execute("INSERT INTO synced_from(copy_id, site, synced_at) VALUES(?, 'rebrickable', 'y')", (copy_id,))


# --- the write routes ---------------------------------------------------------------------------

def test_rows_made_by_hand_read_hand_and_rows_made_inside_adding_read_that_origin(store):
    gear = store.execute('SELECT id FROM main.item WHERE born_key=? UNION SELECT id FROM catalogue.item WHERE born_key=?', (GEAR, GEAR)).fetchone()[0]
    with transaction(store):
        by_hand = stock.add_loose(store, item_id=gear, quantity=1, condition='new')
        with origins.adding('bricklink_xml'):
            from_file = stock.add_loose(store, item_id=gear, quantity=1, condition='used')
        after = stock.add_loose(store, item_id=gear, quantity=2, condition='new')          # merges onto the row by hand: it keeps "hand"
    rows = added_via(store, 'stock')
    assert rows[by_hand['id']] == 'hand' and rows[from_file['id']] == 'bricklink_xml' and after['id'] == by_hand['id']
    assert origins.current() == 'hand'
    with pytest.raises(Store4Error):
        with origins.adding('somewhere'):
            pass


def test_every_insert_of_a_copy_stock_row_or_wish_writes_added_via():
    """A route added later that makes one of these rows without Added via fails here. The migration from 3.3 leaves NULL on purpose (those
    rows are older than 4.8); the demo worlds are fixtures; a kind move copies the row's columns, added_via among them."""
    pattern = re.compile(r"""INSERT INTO (?:main\.)?(copy|stock|wish)\b[^_]|\.insert\(['"](copy|stock|wish)['"]""")
    missing = []
    for path in sorted((ROOT / 'brickwork').rglob('*.py')):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith('brickwork/demo/') or rel == 'brickwork/store4/migrate.py':
            continue
        text = path.read_text()
        for match in pattern.finditer(text):
            statement = text[max(0, match.start() - 700):match.start() + 900]     # a column dict is built just before its INSERT
            if 'added_via' not in statement and 'log.cols(' not in statement and 'for k, v in r.items()' not in text[match.start() - 400:match.start()]:
                missing.append(f'{rel}:{text.count(chr(10), 0, match.start()) + 1}')
    assert not missing, missing


# --- the pull -----------------------------------------------------------------------------------

def test_a_pull_adds_via_the_site_records_what_it_matched_and_undo_takes_both_back(store):
    remote = rebrickable_ready(store)
    plan = sync.plan_pull(store, 'rebrickable', http=remote)
    old_copies = {c['id'] for c in live_copies(store, '2070-1')}
    result = sync.apply_pull(store, plan['id'])
    copies = added_via(store, 'copy')
    new = {c['id'] for n in ('1000-1', '1000-2') for c in live_copies(store, n)}
    assert {copies[c] for c in new} == {'rebrickable'} and {copies[c] for c in old_copies} == {'hand'}
    assert set(added_via(store, 'stock').values()) == {'rebrickable'} and set(added_via(store, 'wish').values()) == {'rebrickable'}
    matched = {r[0] for r in store.execute('SELECT copy_id FROM synced_from WHERE copy_id IS NOT NULL')}
    assert matched == new | old_copies                                                   # 2070-1 was here by hand and is on the site too
    assert synced(store).count(('stock', 'rebrickable', '')) == 1 and synced(store).count(('wish', 'rebrickable', '')) == 1
    receipt = json.loads(store.execute('SELECT new_value FROM event WHERE id=?', (result['event_id'],)).fetchone()[0])
    assert sum(len(v) for v in receipt['synced'].values()) == len(synced(store))
    sync.undo(store, result['event_id'])
    assert synced(store) == []


def test_a_second_pull_refreshes_the_date_and_undoing_it_restores_the_first(store):
    remote = rebrickable_ready(store)
    first = sync.apply_pull(store, sync.plan_pull(store, 'rebrickable', http=remote)['id'])
    dates = dict(store.execute('SELECT id, synced_at FROM synced_from').fetchall())
    second = sync.apply_pull(store, sync.plan_pull(store, 'rebrickable', http=remote)['id'])
    assert set(dict(store.execute('SELECT id, synced_at FROM synced_from').fetchall())) == set(dates)
    sync.undo(store, second['event_id'])
    assert dict(store.execute('SELECT id, synced_at FROM synced_from').fetchall()) == dates
    assert first['event_id'] != second['event_id']


def test_a_row_left_unticked_is_not_marked_as_synced(store):
    remote = rebrickable_ready(store)
    plan = sync.plan_pull(store, 'rebrickable', http=remote)
    keep = [r['key'] for r in plan['rows'] if r['tickable'] and r['number'] != '1000-1']
    sync.apply_pull(store, plan['id'], keep)
    assert not live_copies(store, '1000-1')
    item = store.execute("SELECT id FROM catalogue.item WHERE born_key='1000-1'").fetchone()[0]
    assert not store.execute('SELECT 1 FROM synced_from f JOIN copy c ON c.id=f.copy_id WHERE c.item_id=?', (item,)).fetchone()
    assert store.execute('SELECT count(*) FROM synced_from WHERE copy_id IS NOT NULL').fetchone()[0] == len(live_copies(store, '1000-2')) + 2


def test_untouch_leaves_a_row_a_later_run_changed(store):
    copy_id = live_copies(store, '2070-1')[0]['id']
    with transaction(store):
        entry = origins.touch(store, 'copy', copy_id, 'rebrickable', at='2026-11-22T10:00:00.000Z')
        origins.touch(store, 'copy', copy_id, 'rebrickable', at='2026-11-22T11:00:00.000Z')
        assert origins.untouch(store, entry) is False
        later = origins.touch(store, 'copy', copy_id, 'rebrickable', at='2026-11-22T12:00:00.000Z', list_name='Main')
        renamed = origins.rename_list(store, 'rebrickable', '', 'Main collection')
        assert origins.untouch(store, renamed[0]) and origins.untouch(store, later)
    assert store.execute('SELECT synced_at, list_name FROM synced_from').fetchone()[:] == ('2026-11-22T11:00:00.000Z', None)
    with pytest.raises(Store4Error):
        origins.touch(store, 'copy', copy_id, 'bricklink_xml', at='x')                   # a file is no sync site


def test_a_brickset_pull_reads_brickset(store):
    bs = Brickset()
    sync.paste(store, 'brickset', HASH)
    sync.apply_pull(store, sync.plan_pull(store, 'brickset', http=bs)['id'])
    assert {r[0] for r in store.execute("SELECT added_via FROM copy WHERE added_via!='hand'")} == {'brickset'}
    assert {r[0] for r in store.execute('SELECT site FROM synced_from')} == {'brickset'}


# --- the kind move and the API ------------------------------------------------------------------

def test_a_kind_move_keeps_added_via_and_last_synced_from(store):
    from brickwork.store4 import merge
    gear = store.execute('SELECT id FROM catalogue.item WHERE born_key=?', (GEAR,)).fetchone()[0]
    with transaction(store), origins.adding('brickset'):
        row = stock.add_loose(store, item_id=gear, quantity=1, condition='new')
        origins.touch(store, 'stock', row['id'], 'brickset', at='2026-11-22T10:00:00.000Z', list_key='7', list_name='Shelf')
    with transaction(store):
        merge.move_kind_in(store, gear, 'set', via='app')
    (made,) = store.execute('SELECT id, added_via FROM copy WHERE item_id=? AND archived_at IS NULL', (gear,)).fetchall()
    assert made['added_via'] == 'brickset'
    assert store.execute('SELECT site, list_key, list_name FROM synced_from WHERE copy_id=?', (made['id'],)).fetchone()[:] == ('brickset', '7', 'Shelf')
    assert not store.execute('SELECT 1 FROM synced_from WHERE stock_id IS NOT NULL').fetchone()
    with transaction(store):
        merge.move_kind_in(store, gear, 'gear', via='app')                                # and back: the stock row carries both again
    (back,) = store.execute('SELECT id, added_via FROM stock WHERE item_id=? AND archived_at IS NULL', (gear,)).fetchall()
    assert back['added_via'] == 'brickset' and store.execute('SELECT site FROM synced_from WHERE stock_id=?', (back['id'],)).fetchone()[0] == 'brickset'
