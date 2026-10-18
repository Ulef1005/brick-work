"""Core review fixes: shared check flag, guarded Add undo, keyed entity reads, cheap connect."""
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


def seed_sets(db, *copies):
    with db:
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('S','6081-1','Set')")
        for identifier in copies:
            db.execute("INSERT INTO copies(id,item_type,set_no,completeness,completeness_source) VALUES(?,'S','6081-1','I','derived')", (identifier,))


def last_receipt(db):
    return db.execute("SELECT max(id) FROM events WHERE entity='bw_workbench' AND field='receipt'").fetchone()[0]


def test_h1_undo_of_first_checked_mark_keeps_the_shared_flag(db):
    seed_sets(db, 'A', 'B')
    checker.mark(db, 'A', dict(action='checked', checked=True))
    first = last_receipt(db)
    checker.mark(db, 'B', dict(action='checked', checked=True))
    workbench.undo(db, first)
    assert not checker.checked(db, 'A')
    assert checker.checked(db, 'B')
    assert completeness.derived_state(db, 'B') == db.execute("SELECT completeness FROM copies WHERE id='B'").fetchone()[0]
    flags = db.execute("SELECT id,archived_at FROM flags WHERE name='Set is checked'").fetchall()
    assert len(flags) == 1 and flags[0]['archived_at'] is None
    # The flag is not part of the receipt: Undo can only ever remove A's association.
    receipt = json.loads(db.execute('SELECT new_value FROM events WHERE id=?', (first,)).fetchone()[0])
    assert 'flags' not in [c['table'] for c in receipt['changes']]


def wish_row(quantity=2):
    return dict(item_type='S', item_no='6081-1', name='x', where='wishlist', quantity=quantity, color_id=None,
                condition='U', completeness='', decision='another', note=None)


def wish_db(db):
    with db:
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('S','6081-1','x')")
        db.execute("INSERT INTO wishlist(item_type,item_no,quantity,condition) VALUES('S','6081-1',1,'any')")


def test_h2_confirm_always_records_guards_and_undo_refuses_after_later_edit(db):
    wish_db(db)
    receipt = add.confirm(db, [wish_row()], batch='b1')[0]
    assert receipt['guards']
    collection.save(db, 'wish', [1], {'quantity': 5, 'max_price': '40'})
    with pytest.raises(ValueError, match='undo the later save first'):
        add.undo(db, 'b1')
    assert dict(db.execute('SELECT quantity,max_price FROM wishlist').fetchone()) == dict(quantity=5, max_price='40')


def test_h2_created_copies_are_not_archived_over_later_edits(db):
    with db:
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('S','6081-1','x')")
    row = dict(wish_row(), where='owned', quantity=1, completeness='C')
    receipt = add.confirm(db, [row], batch='b2')[0]
    copy_id = receipt['copies'][0]
    with db:
        db.execute("UPDATE copies SET condition='N' WHERE id=?", (copy_id,))
    with pytest.raises(ValueError, match='undo the later save first'):
        add.undo(db, 'b2')
    assert db.execute('SELECT archived_at FROM copies WHERE id=?', (copy_id,)).fetchone()[0] is None


def test_h2_plain_undo_still_works_and_collision_is_a_clear_refusal(db):
    wish_db(db)
    add.confirm(db, [wish_row()], batch='b3')
    add.undo(db, 'b3')
    assert dict(db.execute('SELECT quantity,archived_at FROM wishlist').fetchone())['quantity'] == 1
    # Archived original wish plus a new live wish for the same item: undoing the add would
    # resurrect a second live wish.
    with db:
        db.execute("UPDATE wishlist SET archived_at='2026-10-01'")
    add.confirm(db, [dict(wish_row(), decision='another')], batch='b4')
    with db:
        db.execute("UPDATE wishlist SET archived_at='2026-10-02' WHERE id=1")
        db.execute("INSERT INTO wishlist(item_type,item_no,quantity,condition) VALUES('S','6081-1',3,'any')")
        saved = json.loads(db.execute("SELECT new_value FROM events WHERE entity='bw_add' AND field='receipt' ORDER BY id DESC").fetchone()[0])
    saved['guards'] = []  # a legacy receipt without guards must still never 500
    saved['wishlist'] = dict(db.execute('SELECT * FROM wishlist WHERE id=1').fetchone(), archived_at=None)
    saved['wishlist_id'] = 1
    with pytest.raises(errors.Conflict, match='Another live wish'):
        add.undo(db, 'b4', saved_receipts=[saved])


def test_l3_wish_restore_over_a_live_duplicate_is_a_conflict(db):
    wish_db(db)
    collection.save(db, 'wish', [1], {}, archive=True)
    with db:
        db.execute("INSERT INTO wishlist(item_type,item_no,quantity,condition) VALUES('S','6081-1',3,'any')")
    with pytest.raises(errors.Conflict):
        collection.restore(db, 'wishlist', 1)
    assert db.execute('SELECT archived_at FROM wishlist WHERE id=1').fetchone()[0] is not None


def test_l3_undo_of_wish_archive_over_a_live_duplicate_is_a_conflict(db):
    wish_db(db)
    collection.save(db, 'wish', [1], {}, archive=True)
    event = db.execute("SELECT max(id) FROM events WHERE entity='bw_collection' AND field='archive'").fetchone()[0]
    with db:
        db.execute("INSERT INTO wishlist(item_type,item_no,quantity,condition) VALUES('S','6081-1',3,'any')")
    with pytest.raises(errors.Conflict):
        collection.undo(db, event)


def test_m3_undone_predicate_uses_the_api_undone_index(db):
    with db:
        for number in range(300):
            db.execute("INSERT INTO events(entity,field,new_value,at,via) VALUES('bw_api','x',?,'t','app')", (json.dumps(dict(undone_event_id=number)),))
    plan = ' '.join(r[3] for r in db.execute(f'EXPLAIN QUERY PLAN SELECT e.*,{api_reads.undone_sql()} undone FROM events e WHERE e.id=?', (1,)))
    assert 'USING INDEX events_api_undone' in plan, plan


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


def test_l7_checker_rows_batches_matches_and_pictures(db, tmp_path):
    seed_collection(db)
    with db:
        for number in range(30):
            db.execute("INSERT INTO items(item_type,item_no,name) VALUES('P',?,'p')", (f'x{number}',))
            db.execute("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing,damaged,spare) VALUES('c1','P',?,4,1,0,0,0)", (f'x{number}',))
        db.execute("INSERT INTO id_match(source,kind,source_id,item_type,item_no,status,evidence_json) VALUES('rebrickable','part','s','P','x3','to_check','[]')")
    statements = []
    db.set_trace_callback(statements.append)
    result = checker.rows(db, 'c1', tmp_path)
    db.set_trace_callback(None)
    assert len(result) >= 31
    assert {r['item_no']: r['unresolved'] for r in result if r['kind'] == 'part'}['x3'] is True
    assert sum(r['unresolved'] for r in result) == 1
    assert all('image' in r for r in result)
    assert sum('FROM id_match' in s for s in statements) == 1
    assert sum('FROM item_images' in s for s in statements) == 1
    assert len(statements) < 15


def test_l10_connect_runs_pending_once_and_probes_are_index_backed(tmp_path, monkeypatch):
    path = tmp_path / 'bw.db'
    connect(path).close()
    calls = []
    original = upgrade.pending
    monkeypatch.setattr(upgrade, 'pending', lambda handle, **kw: calls.append(1) or original(handle, **kw))
    connect(path).close()
    connect(path, read_only=True).close()
    assert len(calls) == 2  # one per connect
    with closing(connect(path)) as handle:
        for sql in ('SELECT 1 FROM allocations WHERE ' + upgrade_api.ALLOCATION_TARGET + ' LIMIT 1',
                    'SELECT 1 FROM wishlist WHERE max_price IS NOT NULL AND max_price_currency IS NULL LIMIT 1'):
            plan = ' '.join(r[3] for r in handle.execute('EXPLAIN QUERY PLAN ' + sql))
            assert 'INDEX allocations_untargeted' in plan or 'INDEX wishlist_currency_pending' in plan, plan


def test_l10_existing_store_without_the_new_indexes_is_upgraded_once(tmp_path):
    path = tmp_path / 'bw.db'
    with closing(connect(path)) as handle, handle:
        handle.execute('DROP INDEX allocations_untargeted')
        handle.execute('DROP INDEX wishlist_currency_pending')
    with closing(connect(path)) as handle:
        assert not upgrade.pending(handle)


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


def one_piece_event(db, batch, monkeypatch):
    from brickwork.core import part_inventory
    monkeypatch.setattr(add, 'lookup', lambda handle, kind, number: dict(item_type=kind, item_no=number, name='Part'))
    with db:
        db.execute("INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES('P','pp','Part')")
        db.execute("INSERT OR IGNORE INTO colors VALUES(4,'Red','Solid','FF0000')")
    candidates = [dict(item_type='P', item_no='pp', name='Part', score=.9)]
    piece = dict(id='piece-' + batch, candidates=candidates, photo='', chosen=dict(item_type='P', item_no='pp', color_id=4, quantity=2))
    return part_inventory.save(db, [piece], batch=batch, keep_photos=False)


@pytest.mark.parametrize('how', ['web', 'api'])
def test_part_inventory_resave_after_either_undo_adds_and_new_receipt_is_live(db, how, monkeypatch):
    from brickwork.core import part_inventory, admin
    stock = lambda: db.execute("SELECT coalesce(sum(quantity),0) FROM loose_stock WHERE archived_at IS NULL AND item_no='pp'").fetchone()[0]
    first = one_piece_event(db, 'b', monkeypatch)
    assert stock() == 2
    if how == 'web':
        part_inventory.undo(db, first)
    else:
        # An API Undo persists only a bw_api event naming the receipt (the same-entity undo is bundled away).
        with db:
            pass
        from brickwork.core.audit_bundle import capture
        with capture():
            part_inventory.undo(db, first)
        with db:
            admin.audit(db, 'bw_api', 'undo', new=dict(undone_event_id=first))
        assert not db.execute("SELECT 1 FROM events WHERE entity='part_inventory:b' AND field='undo'").fetchone()
    assert stock() == 0
    second = one_piece_event(db, 'b', monkeypatch)
    assert second != first and stock() == 2
    live = db.execute(f'SELECT {api_reads.undone_sql()} FROM events e WHERE e.id=?', (second,)).fetchone()[0]
    assert live == 0  # the newer receipt is not read as undone by the older undo event
    assert db.execute(f'SELECT {api_reads.undone_sql()} FROM events e WHERE e.id=?', (first,)).fetchone()[0] == 1
    assert one_piece_event(db, 'b', monkeypatch) == second  # replay of the live save


def test_part_inventory_resave_after_api_only_undo_event(db, monkeypatch):
    """Only the bw_api event exists (no same-entity undo event): save must still add again."""
    from brickwork.core import admin
    from brickwork.core import part_inventory
    from brickwork.core.audit_bundle import capture
    first = one_piece_event(db, 'c', monkeypatch)
    with capture():
        part_inventory.undo(db, first)
    with db:
        admin.audit(db, 'bw_api', 'undo', new=dict(undone_event_id=first))
    assert one_piece_event(db, 'c', monkeypatch) != first


def test_m3_existing_store_without_statistics_gets_them_on_next_writable_connect(tmp_path):
    path = tmp_path / 'bw.db'
    with closing(connect(path)) as handle, handle:
        for number in range(300):
            handle.execute("INSERT INTO events(entity,field,new_value,at,via) VALUES('bw_api','x',?,'t','app')", (json.dumps(dict(undone_event_id=number)),))
        # Shape of a store opened by the previous release: indexes on events present, no statistics, no new partial indexes.
        handle.execute('DROP INDEX allocations_untargeted')
        handle.execute('DROP INDEX wishlist_currency_pending')
        handle.execute('DELETE FROM sqlite_stat1')
    with closing(connect(path)) as handle:
        plan = ' '.join(r[3] for r in handle.execute(f'EXPLAIN QUERY PLAN SELECT e.*,{api_reads.undone_sql()} undone FROM events e WHERE e.id=?', (1,)))
        assert 'USING INDEX events_api_undone' in plan, plan


def test_read_only_store_missing_performance_indexes_is_not_pending(tmp_path, monkeypatch):
    import sqlite3
    path = tmp_path / 'bw.db'
    connect(path).close()
    raw = sqlite3.connect(path)
    raw.execute('DROP INDEX allocations_untargeted')
    raw.execute('DROP INDEX wishlist_currency_pending')
    raw.commit()
    assert upgrade.pending(raw) and not upgrade.pending(raw, writable=False)
    raw.close()
    os.chmod(path, 0o444)
    try:
        if os.access(path, os.W_OK):
            pytest.skip('file permissions are not enforced here')
        monkeypatch.setattr(upgrade, 'upgrade', lambda *a: pytest.fail('a read-only store must not attempt the upgrade'))
        from brickwork.core import connect as module
        module._FAILED.clear()
        for _ in range(2):
            connect(path, read_only=True).close()
        assert not module._FAILED
    finally:
        os.chmod(path, 0o644)


def test_legacy_checker_receipt_never_archives_the_shared_flag(db):
    seed_sets(db, 'A', 'B')
    flag = checker.checked_flag(db, create=True)
    with db:
        db.execute('INSERT INTO item_flags VALUES(?,?,?)', ('copy', 'A', flag))
        db.execute('INSERT INTO item_flags VALUES(?,?,?)', ('copy', 'B', flag))
    flag_row = dict(db.execute('SELECT * FROM flags WHERE id=?', (flag,)).fetchone())
    link = lambda owner: dict(entity_type='copy', entity_id=owner, flag_id=flag)
    changes = [dict(table='flags', key=dict(id=flag), old=[], new=[flag_row]),
               dict(table='item_flags', key=link('A'), old=[], new=[link('A')])]
    with db:
        from brickwork.core.admin import audit
        audit(db, 'bw_workbench', 'receipt', None, dict(changes=changes))
    event = last_receipt(db)
    workbench.undo(db, event)
    assert db.execute('SELECT archived_at FROM flags WHERE id=?', (flag,)).fetchone()[0] is None
    assert checker.checked(db, 'B') and not checker.checked(db, 'A')


def test_add_undo_is_recorded_per_receipt_so_each_row_of_a_batch_can_be_undone(db):
    with db:
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('S','6081-1','x')")
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('S','6285-1','y')")
    rows = [dict(wish_row(), where='owned', quantity=1, completeness='C'),
            dict(wish_row(), item_no='6285-1', name='y', where='owned', quantity=1, completeness='C')]
    first, second = add.confirm(db, rows, batch='multi')
    ids = lambda r: r['copies'][0]
    archived = lambda r: db.execute('SELECT archived_at FROM copies WHERE id=?', (ids(r),)).fetchone()[0]
    add.undo(db, 'multi', saved_receipts=[second])
    assert archived(second) and archived(first) is None
    add.undo(db, 'multi', saved_receipts=[first])
    assert archived(first)
    add.undo(db, 'multi', saved_receipts=[first])  # repeat is a no-op
    events = {r['id']: r for r in db.execute("SELECT id,new_value FROM events WHERE entity='bw_add' AND field='receipt'")}
    assert [r[0] for r in db.execute(f"SELECT {api_reads.undone_sql()} FROM events e WHERE e.id IN ({','.join(map(str, events))}) ORDER BY e.id")] == [1, 1]
    # A web undo of the whole batch afterwards does nothing and does not fail.
    add.undo(db, 'multi')


def test_add_web_undo_of_a_batch_after_one_row_was_undone_finishes_the_rest(db):
    with db:
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('S','6081-1','x')")
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('S','6285-1','y')")
    rows = [dict(wish_row(), where='owned', quantity=1, completeness='C'),
            dict(wish_row(), item_no='6285-1', name='y', where='owned', quantity=1, completeness='C')]
    first, second = add.confirm(db, rows, batch='multi2')
    add.undo(db, 'multi2', saved_receipts=[second])
    add.undo(db, 'multi2')
    assert all(db.execute('SELECT archived_at FROM copies WHERE id=?', (r['copies'][0],)).fetchone()[0] for r in (first, second))
