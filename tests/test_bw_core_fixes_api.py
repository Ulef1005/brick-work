"""Core review fixes about the API reads (M.11): the undone predicate and the keyed entity reads. Moved out of test_bw_core_fixes.py in M.8d;
still the 3.3 text, rewritten with the v2 API. (The keyed-read and flag-order ideas are ported to `collection.instance` in test_bw_core_fixes.py.)"""
from contextlib import closing
import json
import os

import pytest

from brickwork.core import add, api_reads, checker, collection, completeness, errors, upgrade, upgrade_api, workbench
from brickwork.core.connect import connect


@pytest.fixture
def db(tmp_path):
    with closing(connect(tmp_path / 'bw.db')) as handle:
        yield handle


def test_m3_undone_predicate_uses_the_api_undone_index(db):
    with db:
        for number in range(300):
            db.execute("INSERT INTO events(entity,field,new_value,at,via) VALUES('bw_api','x',?,'t','app')", (json.dumps(dict(undone_event_id=number)),))
    plan = ' '.join(r[3] for r in db.execute(f'EXPLAIN QUERY PLAN SELECT e.*,{api_reads.undone_sql()} undone FROM events e WHERE e.id=?', (1,)))
    # Which index SQLite picks depends on its version (CI's differs from the Pi's); the point is that the
    # undone lookup never scans the events table.
    assert 'SCAN' not in plan and 'INDEX events_' in plan, plan


def test_m3_undone_predicate_semantics_unchanged(db):
    with db:
        db.execute("INSERT INTO events(entity,field,new_value,at,via) VALUES('x','y','{}','t','app')")
        db.execute("INSERT INTO events(entity,field,new_value,at,via) VALUES('bw_api','undo',?,'t','app')", (json.dumps(dict(undone_event_id=1)),))
        db.execute("INSERT INTO events(entity,field,new_value,at,via) VALUES('x','y','plain text','t','app')")
    undone = {r[0]: r[1] for r in db.execute(f'SELECT e.id,{api_reads.undone_sql()} FROM events e')}
    assert undone[1] == 1 and undone[2] == 0 and undone[3] == 0


def seed_collection(db):
    with db:
        db.execute("INSERT INTO colors VALUES(4,'Red','Solid','FF0000')")
        db.executemany('INSERT INTO items(item_type,item_no,name,year) VALUES(?,?,?,?)',
                       [('S', '100-1', 'Set', 2024), ('P', '3001', 'Brick', 2025), ('M', 'fig1', 'Figure', 2023)])
        db.execute("INSERT INTO storages(id,name) VALUES('s1','Box')")
        db.execute("INSERT INTO purchase_locations(id,name) VALUES('p1','Shop')")
        db.execute("INSERT INTO lots(id,name) VALUES('l1','Lot')")
        for identifier, archived in (('c1', None), ('c2', None), ('c0', '2026-01-01')):
            db.execute("INSERT INTO copies(id,set_no,condition,completeness,completeness_source,storage_id,purchase_location_id,archived_at) VALUES(?,'100-1','U','I','derived','s1','p1',?)", (identifier, archived))
        db.execute("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing,damaged,spare) VALUES('c1','P','3001',4,4,2,1,0)")
        db.execute("INSERT INTO copy_minifigs(copy_id,item_type,minifig_no,quantity,missing) VALUES('c1','M','fig1',1,1)")
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition,storage_id,lot_id) VALUES('t1','P','3001',4,9,'U','s1','l1')")
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES('t2','P','3001',4,1,'N')")
        db.execute("INSERT INTO wishlist(id,item_type,item_no,color_id,quantity,condition,max_price,max_price_currency) VALUES(1,'P','3001',4,2,'used','9.00','EUR')")
        db.execute("INSERT INTO wishlist(id,item_type,item_no,quantity,condition) VALUES(2,'S','100-1',1,'any')")
        db.execute("INSERT INTO item_properties(item_type,item_no,key,source,value) VALUES('S','100-1','theme','bricklink','City')")
        db.execute("INSERT INTO flags(id,name,kind,shown_on_grid) VALUES('f1','Tag','tag',1)")
        for kind, identifier in (('copy', 'c1'), ('stock', 't1'), ('wishlist', '1')):
            db.execute('INSERT INTO item_flags VALUES(?,?,?)', (kind, identifier, 'f1'))
        db.execute("INSERT INTO price_observations(item_type,item_no,color_id,condition,guide,currency,price,source,observed_at) VALUES('P','3001',4,'U','sold','EUR','2.50','bricklink','2026-10-01T00:00:00+00:00')")
        db.execute("INSERT INTO price_current(item_type,item_no,color_id,condition,guide,currency,observation_id) VALUES('P','3001',4,'U','sold','EUR',1)")
        db.execute("INSERT INTO price_observations(item_type,item_no,condition,guide,currency,price,source,observed_at) VALUES('S','100-1','U','sold','EUR','50','bricklink','2026-10-01T00:00:00+00:00')")
        db.execute("INSERT INTO price_current(item_type,item_no,condition,guide,currency,observation_id) VALUES('S','100-1','U','sold','EUR',2)")


@pytest.mark.parametrize('name,identifier', [('copy', 'c1'), ('copy', 'c2'), ('copy', 'c0'), ('stock', 't1'), ('stock', 't2'), ('wish', 1), ('wish', 2)])
def test_m4_keyed_entity_equals_the_full_collection_row(db, name, identifier):
    seed_collection(db)
    full = next(r for r in api_reads.entities(db, name) if str(r['id']) == str(identifier))
    keyed = api_reads.entities(db, name, identifier)
    assert keyed == [full]
    assert api_reads.entity(db, name, identifier) == full


def test_m4_unknown_entity_is_not_found_and_reads_stay_keyed(db):
    seed_collection(db)
    with pytest.raises(errors.NotFound):
        api_reads.entity(db, 'copy', 'nope')
    with pytest.raises(errors.NotFound):
        api_reads.entity(db, 'wish', 99)
    statements = []
    db.set_trace_callback(statements.append)
    api_reads.entity(db, 'copy', 'c1')
    db.set_trace_callback(None)
    # No query reads the whole collection: every statement mentioning copies is keyed.
    assert not any('FROM copies c JOIN items' in s and 'WHERE c.id' not in s for s in statements)


def test_flag_order_is_stable_between_keyed_and_bulk_reads(db):
    seed_collection(db)
    with db:
        for identifier in ('zz', 'aa', 'mm'):
            db.execute("INSERT INTO flags(id,name,kind,shown_on_grid) VALUES(?,?,'tag',1)", (identifier, identifier.upper()))
        for kind, owner in (('copy', 'c2'), ('stock', 't2'), ('wishlist', '2')):
            for identifier in ('zz', 'aa', 'mm'):
                db.execute('INSERT INTO item_flags VALUES(?,?,?)', (kind, owner, identifier))
    for name, identifier in (('copy', 'c2'), ('stock', 't2'), ('wish', 2)):
        full = next(r for r in api_reads.entities(db, name) if str(r['id']) == str(identifier))
        keyed = api_reads.entities(db, name, identifier)[0]
        assert [f['id'] for f in keyed['flags']] == [f['id'] for f in full['flags']] == ['aa', 'mm', 'zz']
        assert keyed == full
