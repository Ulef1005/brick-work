"""BrickTracker import into a live store: any upstream version, plan, apply, Undo. All data invented."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3

import pytest

from brickwork.core.connect import connect
from brickwork.core.importer import bricktracker, bricktracker_upgrade
from brickwork.web import cli
from tests.importer.test_importer import insert, legacy  # noqa: F401  (fixture)

base_insert = insert

CATALOGUE = [('S', '100-1'), ('S', '200-1'), ('S', 'new-set'), ('M', 'bl-figure'), ('P', '3001'), ('P', 'bl-part'),
             ('P', 'other-part'), ('P', 'uncolored-part'), ('P', 'resolution-only')]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def catalogue(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE items(item_type TEXT,item_no TEXT,name TEXT,normalized_name TEXT,category TEXT)')
        db.executemany('INSERT INTO items VALUES(?,?,?,NULL,NULL)', [(t, n, 'Invented ' + n) for t, n in CATALOGUE])


@pytest.fixture
def store(tmp_path):
    root = tmp_path / 'store'
    root.mkdir()
    catalogue(root / 'bricklink-catalog.db')
    with closing(connect(root / 'brickwork.db')):
        pass
    return root / 'brickwork.db'


def upstream(path, version, *, custom=False):
    """A synthetic upstream app.db at `version`: one set with parts, a wish, a storage."""
    db = sqlite3.connect(path)
    bricktracker_upgrade.apply(db, 0, version)

    def insert(db, table, **row):
        # Older schemas lack later columns (e.g. BrickLink ids on parts arrived after 0015).
        have = {r[1] for r in db.execute(f'PRAGMA table_info("{table}")')}
        base_insert(db, table, **{k: v for k, v in row.items() if k in have})
    insert(db, 'rebrickable_sets', set='100-1', number='100', version=1, name='Invented set', year=2020, theme_id=1,
           number_of_parts=2)
    insert(db, 'bricktracker_metadata_storages', id='shelf', name='Shelf A')
    insert(db, 'bricktracker_sets', id='copy-1', set='100-1', description='Invented note', storage='shelf')
    insert(db, 'rebrickable_parts', part='3001', color_id=4, color_name='Invented red', name='Invented brick',
           bricklink_color_id=5, bricklink_part_num='3001')
    insert(db, 'bricktracker_parts', id='copy-1', part='3001', color=4, spare=0, quantity=2, rebrickable_inventory=1,
           missing=1, damaged=0)
    insert(db, 'bricktracker_wishes', set='200-1', name='Invented wish', year=2021, theme_id=1, number_of_parts=3)
    if custom:
        insert(db, 'bricktracker_metadata_custom_fields', id='box', name='Box shelf', type='text')
        db.execute('ALTER TABLE bricktracker_set_custom_fields ADD COLUMN custom_field_box TEXT')
        insert(db, 'bricktracker_set_custom_fields', id='copy-1', custom_field_box='Attic 3')
    db.commit()
    db.close()
    return path


def counts(db):
    return {t: db.execute(f'SELECT count(*) FROM {t} WHERE archived_at IS NULL').fetchone()[0]
            for t in ('copies', 'loose_stock', 'wishlist', 'lots')}


@pytest.mark.parametrize('version', [15, 21, 27, 30])
def test_any_version_upgrades_and_imports(tmp_path, store, version):
    source = upstream(tmp_path / f'app-{version}.db', version, custom=version == 30)
    before = digest(source)
    with closing(connect(store)) as db:
        plan = bricktracker.plan(db, source)
        assert plan['schema'] == dict(found=version, upgraded_to=bricktracker_upgrade.NEWEST) and plan['fresh']
        assert {r['key'] for r in plan['rows'] if r['action'] == 'add'} >= {'copy:copy-1'}
        result = bricktracker.apply(db, plan['id'])
        copy = db.execute("SELECT * FROM copies WHERE id='copy-1'").fetchone()
        assert copy['set_no'] == '100-1' and copy['storage_id']
        assert 'Invented note' in copy['note']
        if version == 30:
            assert 'Box shelf: Attic 3' in copy['note']
        part = db.execute("SELECT item_type,item_no,color_id,missing FROM copy_parts WHERE copy_id='copy-1'").fetchone()
        # Without an extras file the colour comes from upstream's own BrickLink colour evidence (absent before 0016).
        assert part['missing'] == 1 and (tuple(part)[:3] == ('P', '3001', 5) or version < 16 and part['item_type'] == '?')
        assert result['counts']['copies'] == 1 and result['event_id']
    assert digest(source) == before


def test_refuses_newer_and_foreign_databases(tmp_path, store):
    newer = upstream(tmp_path / 'new.db', 30)
    with closing(sqlite3.connect(newer)) as db:
        db.execute(f'PRAGMA user_version={bricktracker_upgrade.NEWEST + 1}')
    other = tmp_path / 'other.db'
    with closing(sqlite3.connect(other)) as db:
        db.execute('CREATE TABLE notes(x)')
    with closing(connect(store)) as db:
        with pytest.raises(ValueError, match='newer'):
            bricktracker.plan(db, newer)
        with pytest.raises(ValueError, match='not a BrickTracker database'):
            bricktracker.plan(db, other)
    assert not list((store.parent / 'data' / 'imports').iterdir())


def legacy_store(legacy, store):
    """The importer's legacy collection fixture, stamped as upstream 0027."""
    with closing(sqlite3.connect(legacy['app_db'])) as db:
        db.execute('PRAGMA user_version=27')
    shutil.copy(legacy['catalogues'] / 'blcat.db', store.with_name('bricklink-catalog.db'))
    return legacy['app_db']


def test_fresh_import_one_event_and_exact_undo(legacy, store):
    source = legacy_store(legacy, store)
    before = digest(source)
    with closing(connect(store)) as db:
        empty = counts(db)
        plan = bricktracker.plan(db, source)
        assert plan['unresolved'] and all(r['item_type'] == '?' for r in plan['unresolved'])
        result = bricktracker.apply(db, plan['id'])
        # One receipt; a fresh store also gets the default source settings once, as on a first Add.
        assert db.execute("SELECT count(*) FROM events WHERE entity NOT LIKE 'source:%'").fetchone()[0] == 1
        assert db.execute('SELECT via FROM events WHERE id=?', (result['event_id'],)).fetchone()[0] == 'import'
        loaded = counts(db)
        assert loaded['copies'] == 1 and loaded['loose_stock'] >= 2 and loaded['wishlist'] == 1
        assert db.execute("SELECT count(*) FROM item_flags WHERE entity_type='copy' AND entity_id='copy'").fetchone()[0] == 3
        # Applying again is a no-op that returns the same receipt.
        assert bricktracker.apply(db, plan['id'])['already_applied']
        assert bricktracker.undo(db, result['event_id'])['already_undone'] is False
        assert counts(db) == empty
        assert bricktracker.undo(db, result['event_id'])['already_undone'] is True
        assert not db.execute('SELECT 1 FROM flags UNION ALL SELECT 1 FROM purchase_locations').fetchone()
    assert digest(source) == before


def test_merge_duplicates_reimport_and_stock_merge(legacy, store):
    source = legacy_store(legacy, store)
    with closing(connect(store)) as db:
        first = bricktracker.apply(db, bricktracker.plan(db, source)['id'])
        pile = db.execute("SELECT id,quantity FROM loose_stock WHERE item_type='P' AND archived_at IS NULL").fetchone()
        again = bricktracker.plan(db, source)
        assert not again['fresh']
        states = {r['key']: (r['state'], r['action'], r['locked']) for r in again['rows']}
        assert states['copy:copy'] == ('imported', 'skip', True)
        assert all(v[0] in ('imported', 'duplicate') for v in states.values())
        wish = next(k for k, v in states.items() if k.startswith('wish:'))
        assert states[wish] == ('duplicate', 'skip', True)
        # A locked row cannot be forced; an imported stock UUID stays skipped.
        result = bricktracker.apply(db, again['id'], {'copy:copy': 'add', wish: 'add'})
        assert result['counts']['copies'] == 0 and result['counts']['wishes'] == 0
        bricktracker.undo(db, result['event_id'])
        # A different collection with the same part merges into the existing pile on "add".
        db.execute("UPDATE loose_stock SET id='renamed' WHERE id=?", (pile['id'],))
        db.commit()
        merge = bricktracker.plan(db, source)
        key = next(r['key'] for r in merge['rows'] if r['kind'] == 'stock' and r['state'] == 'duplicate'
                   and r['item_type'] == 'P')
        merged = bricktracker.apply(db, merge['id'], {key: 'add'})
        assert db.execute("SELECT quantity FROM loose_stock WHERE id='renamed'").fetchone()[0] == pile['quantity'] * 2
        bricktracker.undo(db, merged['event_id'])
        assert db.execute("SELECT quantity FROM loose_stock WHERE id='renamed'").fetchone()[0] == pile['quantity']
        assert first['event_id']


def test_undo_refused_after_a_later_edit(legacy, store):
    source = legacy_store(legacy, store)
    with closing(connect(store)) as db:
        result = bricktracker.apply(db, bricktracker.plan(db, source)['id'])
        db.execute("UPDATE copies SET note='Changed later' WHERE id='copy'")
        db.commit()
        with pytest.raises(ValueError, match='changed since'):
            bricktracker.undo(db, result['event_id'])
        assert counts(db)['copies'] == 1


def test_plans_expire_and_ids_are_checked(legacy, store):
    source = legacy_store(legacy, store)
    with closing(connect(store)) as db:
        plan = bricktracker.plan(db, source)
        meta = store.parent / 'data' / 'imports' / plan['id'] / 'plan.json'
        stored = json.loads(meta.read_text())
        meta.write_text(json.dumps(dict(stored, created_at='2020-01-01T00:00:00+00:00')))
        with pytest.raises(ValueError, match='expired'):
            bricktracker.apply(db, plan['id'])
        with pytest.raises(ValueError, match='Unknown'):
            bricktracker.apply(db, '../etc')
        fresh = bricktracker.plan(db, source)
        assert not meta.parent.exists()  # the expired plan was cleaned up by the next plan
        with pytest.raises(ValueError, match='Unknown import rows'):
            bricktracker.apply(db, fresh['id'], {'copy:nope': 'add'})
        with pytest.raises(ValueError, match='add or skip'):
            bricktracker.apply(db, fresh['id'], {'copy:copy': 'keep'})


def test_apply_query_count_is_flat(tmp_path, store):
    """Statements grow with rows written, not with rows × rows."""
    def run(n, name):
        source = upstream(tmp_path / f'{name}.db', 30)
        with closing(sqlite3.connect(source)) as db, db:
            for i in range(n):
                insert(db, 'bricktracker_sets', id=f'extra-{i}', set='100-1')
                insert(db, 'bricktracker_parts', id=f'extra-{i}', part='3001', color=4, spare=0, quantity=1,
                       rebrickable_inventory=1, missing=0, damaged=0)
        path = store.parent.parent / name / 'brickwork.db'
        path.parent.mkdir()
        with closing(connect(path)):
            pass
        shutil.copy(store.with_name('bricklink-catalog.db'), path.with_name('bricklink-catalog.db'))
        with closing(connect(path)) as db:
            plan = bricktracker.plan(db, source)
            statements = []
            db.set_trace_callback(statements.append)
            bricktracker.apply(db, plan['id'], queue=False)
            db.set_trace_callback(None)
            return len(statements)
    small, large = run(5, 'small'), run(50, 'large')
    # Each extra copy writes a copy row and a part row; nothing scans per row.
    assert large - small <= 45 * 2 + 10


def test_cli_plan_then_apply(legacy, store, monkeypatch, capsys):
    source = legacy_store(legacy, store)
    monkeypatch.setenv('BW_DB_PATH', str(store))
    assert cli.main(['import-bricktracker', str(source), '--plan-only', '--json']) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan['summary']['copy']['new'] == 1 and 'rows' not in plan
    decisions = store.with_name('decisions.json')
    decisions.write_text(json.dumps({'copy:copy': 'skip'}))
    assert cli.main(['import-bricktracker', '--apply', plan['id'], '--decisions', str(decisions), '--json']) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied['counts']['copies'] == 0 and applied['counts']['wishes'] == 1
    with closing(connect(store)) as db:
        assert db.execute('SELECT via FROM events WHERE id=?', (applied['event_id'],)).fetchone()[0] == 'import'
    with pytest.raises(SystemExit):
        cli.main(['import-bricktracker'])


def test_api_upload_plan_apply_undo(legacy, store, monkeypatch):
    from flask import Flask
    from brickwork.api import register
    source = legacy_store(legacy, store)
    monkeypatch.delenv('BW_READ_ONLY', raising=False)
    monkeypatch.setenv('BW_API_TOKEN', 'synthetic-bootstrap')
    monkeypatch.setenv('BW_DB_PATH', str(store))
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    app = Flask(__name__)
    app.config.update(TESTING=True)
    register(app)
    client = app.test_client()
    admin = {'Authorization': 'Bearer synthetic-bootstrap'}
    writer = client.post('/api/v1/tokens', headers=admin, json={'name': 'w', 'scopes': ['write']}).json['data']['secret']
    with open(source, 'rb') as handle:
        refused = client.post('/api/v1/imports/bricktracker', headers={'Authorization': 'Bearer ' + writer},
                              data={'file': (handle, 'app.db')}, content_type='multipart/form-data')
    assert refused.status_code == 403
    with open(source, 'rb') as handle:
        made = client.post('/api/v1/imports/bricktracker', headers=admin, data={'file': (handle, 'app.db')},
                           content_type='multipart/form-data')
    assert made.status_code == 201, made.json
    plan = made.json['data']
    assert plan['source'] == 'app.db' and plan['summary']['copy']['new'] == 1
    assert not list((store.parent / 'data' / 'imports' / 'uploads').iterdir())
    bad = client.post('/api/v1/imports/bricktracker', headers=admin, data={'file': (__import__('io').BytesIO(b'nope'), 'x.db')},
                      content_type='multipart/form-data')
    assert bad.status_code == 422
    applied = client.post(f"/api/v1/imports/{plan['id']}/apply", headers=dict(admin, **{'Idempotency-Key': 'imp-1'}),
                          json={'decisions': {}})
    assert applied.status_code == 200, applied.json
    event = applied.json['event_id']
    replay = client.post(f"/api/v1/imports/{plan['id']}/apply", headers=dict(admin, **{'Idempotency-Key': 'imp-1'}),
                         json={'decisions': {}})
    assert replay.json['idempotent_replay'] and replay.json['event_id'] == event
    with closing(connect(store)) as db:
        assert counts(db)['copies'] == 1
    undone = client.post(f'/api/v1/events/{event}/undo', headers=dict(admin, **{'Idempotency-Key': 'imp-undo'}))
    assert undone.status_code in (200, 201), undone.json
    with closing(connect(store)) as db:
        assert counts(db)['copies'] == 0


def test_import_applies_once_even_when_the_plan_file_is_stale(legacy, store):
    """#64: the plan file not marked applied (a second submit, or a crash before the write)."""
    source = legacy_store(legacy, store)
    with closing(connect(store)) as db:
        plan = bricktracker.plan(db, source)
        first = bricktracker.apply(db, plan['id'])
        work, meta = bricktracker.load_plan(db, plan['id'])
        meta.pop('applied')
        (work / 'plan.json').write_text(json.dumps(meta))
        before = counts(db)
        again = bricktracker.apply(db, plan['id'])
        assert again['already_applied'] and again['event_id'] == first['event_id']
        assert counts(db) == before
