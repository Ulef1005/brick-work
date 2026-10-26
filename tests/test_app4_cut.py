"""The cut to the 4.0 store (M.8a, issue #110): the connect wrapper, the audit adapter, undo on `event_undo`, the key provider, the
drainer's poll and the identity facade `core.items`, on the fixture catalogue of `store4_mint_fixtures`. Invented data, no network."""
from contextlib import closing
import json
from pathlib import Path
import re
import shutil
import sqlite3

from cryptography.fernet import Fernet
import pytest

from brickwork.core import admin, drainer, errors, items, keys, undo
from brickwork.core.connect import NoCatalogue, OldStore, catalogue_path, connect
from brickwork.core.sources.base import audit_origin
from brickwork.store4.activate import activate
from brickwork.store4 import keys as store4_keys
from brickwork.store4.connect import has_catalogue
from tests.legacy33 import create_33
from tests.store4_mint_fixtures import build_catalogue, colour_id, item_id


@pytest.fixture
def pair(tmp_path):
    (tmp_path / 'cat').mkdir()
    shutil.copy(build_catalogue(tmp_path / 'cat'), tmp_path / 'catalogue.db')
    return tmp_path / 'brickwork.db'


@pytest.fixture
def db(pair):
    """The collection with the catalogue attached and nothing activated: items are read from the catalogue."""
    with closing(connect(pair)) as db:
        yield db


@pytest.fixture
def live(db):
    """The same, after activation (as `catalogue import` leaves a collection): items can be projected."""
    activate(db)
    return db


# ---------- the connect wrapper ----------

def test_connect_creates_a_4_0_collection_with_the_catalogue_beside_it(pair):
    assert not pair.exists()
    with closing(connect(pair)) as db:
        assert db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == '4.0'
        assert has_catalogue(db) and db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    assert catalogue_path(pair) == pair.with_name('catalogue.db')


def test_a_missing_catalogue_is_a_first_run_error_naming_the_way_to_get_one(tmp_path):
    with pytest.raises(NoCatalogue, match=r'catalogue\.db.*catalogue download.*catalogue import'):
        connect(tmp_path / 'brickwork.db')
    assert not (tmp_path / 'brickwork.db').exists()                                  # refused before anything is created
    with closing(connect(tmp_path / 'brickwork.db', require_catalogue=False)) as db:   # setup and the first-run page
        assert not has_catalogue(db)
    assert issubclass(NoCatalogue, errors.CatalogueNotLoaded) and NoCatalogue('x').status == 424


@pytest.mark.parametrize('read_only', [False, True])
def test_a_3_3_file_is_refused_untouched_and_the_fix_is_named(pair, read_only):
    create_33(pair).close()
    before = pair.read_bytes()
    with pytest.raises(OldStore) as refused:
        connect(pair, read_only=read_only)
    assert 'python -m brickwork.store4 migrate' in str(refused.value) and '3.2/3.3' in str(refused.value)
    assert pair.read_bytes() == before


def test_a_read_only_open_cannot_write_and_a_catalogue_that_does_not_belong_is_refused(pair):
    connect(pair).close()
    with closing(connect(pair, read_only=True)) as db:
        with pytest.raises(sqlite3.OperationalError):
            db.execute("INSERT INTO setting(key, value) VALUES('a', 'b')")
    with closing(sqlite3.connect(pair.with_name('catalogue.db'))) as cat:
        cat.execute("UPDATE meta SET value='another' WHERE key='schema_version'")
        cat.commit()
    with pytest.raises(NoCatalogue, match='not a Brick Work catalogue'):
        connect(pair)


# ---------- the audit adapter ----------

def events(db):
    return [dict(r) for r in db.execute('SELECT * FROM event ORDER BY id')]


def test_audit_splits_the_entity_at_the_first_colon(db):
    admin.audit(db, 'copy:abc', 'note', 'a', {'b': 1})
    admin.audit(db, 'bw_api', 'receipt', new={'x': 1})
    admin.audit(db, 'source_key:bricklink:extra', 'save')
    admin.audit(db, 'checker:', 'x')
    rows = events(db)
    assert [(r['entity_kind'], r['entity_id']) for r in rows] == [('copy', 'abc'), ('bw_api', None), ('source_key', 'bricklink:extra'), ('checker', None)]
    assert (rows[0]['old_value'], rows[0]['new_value'], rows[0]['via'], rows[0]['actor']) == ('a', '{"b": 1}', 'app', None)     # store4.audit.value_text: a string as it is, a dict as JSON
    assert (rows[1]['old_value'], rows[1]['new_value'].replace(' ', '')) == (None, '{"x":1}')       # None is NULL, as in native 4.0 events
    assert re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z', rows[0]['at'])


def test_audit_origin_actor_and_the_operation_key(db):
    admin.audit(db, 'copy:1', 'f')
    with audit_origin('api', actor='token-a'):
        key = admin.begin_operation()
        admin.audit(db, 'copy:1', 'f')
        admin.audit(db, 'copy:2', 'f')
        admin.end_operation()
    with audit_origin('cli', actor='ignored'):
        admin.audit(db, 'copy:3', 'f')
    with admin.operation('fixed') as inner:
        assert inner == 'fixed'
        admin.audit(db, 'copy:4', 'f', via='import')
    admin.audit(db, 'copy:5', 'f')
    rows = events(db)
    assert [(r['via'], r['actor'], r['operation_key']) for r in rows] == [
        ('app', None, None), ('api', 'token-a', key), ('api', 'token-a', key), ('cli', None, None), ('import', None, 'fixed'), ('app', None, None)]
    with pytest.raises(ValueError, match='invalid audit origin'):
        admin.audit(db, 'copy:1', 'f', via='web')


def test_audit_redacts_secrets_and_a_captured_bundle_passes_through(db, monkeypatch):
    monkeypatch.setenv('BW_SOME_SECRET', 'sensitive-value-123')
    admin.audit(db, 'copy:1', 'f', new='x sensitive-value-123 y')
    assert 'sensitive-value-123' not in events(db)[0]['new_value'] and '[set]' in events(db)[0]['new_value']
    from brickwork.core.audit_bundle import capture
    with capture() as captured:
        admin.audit(db, 'copy:1', 'g', new=1)
    assert [c['field'] for c in captured] == ['g'] and len(events(db)) == 1


def test_events_stay_append_only_through_the_adapter(db):
    admin.audit(db, 'copy:1', 'f')
    with pytest.raises(sqlite3.IntegrityError, match='append-only'):
        db.execute("UPDATE event SET field='x'")


# ---------- undo ----------

def test_the_predicates_read_event_undo(db):
    admin.audit(db, 'copy:1', 'part_list_switch', new={})
    admin.audit(db, 'copy:1', 'note', new={})
    admin.audit(db, 'copy:1', 'part_list_switch_undo', new={})
    db.execute('INSERT INTO event_undo(event_id, undo_event_id) VALUES(1, 3)')
    got = db.execute(f'SELECT e.id, {undo.undone_sql()} u, {undo.undoable_sql()} a FROM event e ORDER BY e.id').fetchall()
    assert [(r['id'], r['u'], r['a']) for r in got] == [(1, 1, 1), (2, 0, 0), (3, 0, 0)]


def test_undo_event_refuses_what_it_cannot_undo(db):
    with pytest.raises(errors.NotFound):
        undo.undo_event(db, 99)
    admin.audit(db, 'copy:1', 'note', new={})
    with pytest.raises(errors.NotUndoable):
        undo.undo_event(db, 1)


def test_a_registered_undoer_runs_once_and_a_repeat_says_so(db, monkeypatch):
    monkeypatch.setitem(undo.REGISTRY, ('thing', 'made'), undo.Undoer(handler=lambda db, event, via, actor: _undo_thing(db, event, via, actor)))
    admin.audit(db, 'thing:7', 'made', new={'n': 1})

    def _undo_thing(db, event, via, actor):
        admin.audit(db, 'thing:7', 'made_undo', new={'undoes': event['id']}, via=via, actor=actor)
        undone = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.execute('INSERT INTO event_undo(event_id, undo_event_id) VALUES(?, ?)', (event['id'], undone))
        return {'event_id': undone}
    first = undo.undo_event(db, 1, via='cli')
    assert first == {'undone_event_id': 1, 'already_undone': False, 'undo_event_id': 2}
    assert undo.undo_event(db, 1) == {'undone_event_id': 1, 'already_undone': True, 'undo_event_id': None}
    assert db.execute('SELECT count(*) FROM event_undo').fetchone()[0] == 1 and undo.is_undone(db, 1)


def test_a_refusing_undoer_becomes_undo_blocked_and_leaves_nothing(db, monkeypatch):
    def refuse(db, event, via, actor):
        db.execute("INSERT INTO setting(key, value) VALUES('half', 'done')")
        raise ValueError('Item changed · undo the later save first')
    monkeypatch.setitem(undo.REGISTRY, ('thing', 'made'), undo.Undoer(handler=refuse))
    admin.audit(db, 'thing:7', 'made', new={})
    db.commit()
    with pytest.raises(errors.UndoBlocked, match='Item changed'):
        undo.undo_event(db, 1)
    assert db.execute("SELECT count(*) FROM setting WHERE key='half'").fetchone()[0] == 0


def test_the_admin_flag_asks_for_the_admin_scope(db, monkeypatch):
    monkeypatch.setitem(undo.REGISTRY, ('thing', 'made'), undo.Undoer(handler=lambda *a: {}, admin=True))
    admin.audit(db, 'thing:7', 'made', new={})
    with pytest.raises(errors.Forbidden):
        undo.undo_event(db, 1, identity={'scopes': ['write']})
    assert undo.undo_event(db, 1, identity={'scopes': ['admin']})['already_undone'] is False


def test_register_refuses_a_second_undoer_and_odd_names():
    with pytest.raises(ValueError, match='already has'):
        undo.register('copy', 'part_list_switch', lambda *a: {})
    with pytest.raises(ValueError):
        undo.register('Copy', "x'; DROP", lambda *a: {})


# ---------- the key provider ----------

BL = ('BW_BRICKLINK_CONSUMER_KEY', 'BW_BRICKLINK_CONSUMER_SECRET', 'BW_BRICKLINK_TOKEN_VALUE', 'BW_BRICKLINK_TOKEN_SECRET')


@pytest.fixture
def clean_env(monkeypatch):
    import os
    for name in list(os.environ):
        if name.startswith('BW_'):
            monkeypatch.delenv(name)
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    yield monkeypatch
    store4_keys.set_key_provider(None)


def test_the_provider_reads_the_environment_first_then_the_encrypted_table(pair, clean_env):
    keys.install(pair)
    assert store4_keys.get('BW_REBRICKABLE_API_KEY') is None
    with closing(connect(pair)) as db:
        keys.save(db, 'rebrickable', {'key': 'stored-rebrickable-key'})
        keys.save(db, 'bricklink', dict(zip(('consumer_key', 'consumer_secret', 'token_value', 'token_secret'), ('ck-123456', 'cs-123456', 'tv-123456', 'ts-123456'))))
    assert store4_keys.get('BW_REBRICKABLE_API_KEY') == 'stored-rebrickable-key'
    assert [store4_keys.get(n) for n in BL] == ['ck-123456', 'cs-123456', 'tv-123456', 'ts-123456']
    clean_env.setenv('BW_REBRICKABLE_API_KEY', 'env-rebrickable-key')
    assert store4_keys.get('BW_REBRICKABLE_API_KEY') == 'env-rebrickable-key'
    clean_env.setenv('BW_BRICKLINK_CONSUMER_KEY', 'env-only-one')                         # a partial environment is not a configured source
    assert store4_keys.get('BW_BRICKLINK_CONSUMER_KEY') == 'ck-123456'
    for name in BL[1:]:
        clean_env.setenv(name, 'env-' + name[-6:])
    assert [store4_keys.get(n) for n in BL][0] == 'env-only-one'
    assert keys.state(closing(connect(pair, require_catalogue=False)).thing, 'rebrickable')['origin'] == 'env'


def test_an_archived_wrong_secret_or_unreadable_key_is_simply_not_configured(pair, clean_env):
    keys.install(lambda: pair)
    with closing(connect(pair)) as db:
        keys.save(db, 'rebrickable', {'key': 'stored-rebrickable-key'})
        keys.archive(db, 'rebrickable')
    assert store4_keys.get('BW_REBRICKABLE_API_KEY') is None
    with closing(connect(pair)) as db:
        db.execute('UPDATE source_key SET archived_at=NULL')
        db.commit()
    assert store4_keys.get('BW_REBRICKABLE_API_KEY') == 'stored-rebrickable-key'
    clean_env.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())                   # another secret cannot decrypt it
    assert store4_keys.get('BW_REBRICKABLE_API_KEY') is None
    keys.install(pair.with_name('missing.db'))
    assert store4_keys.get('BW_REBRICKABLE_API_KEY') is None
    assert store4_keys.get('NOT_A_KEY') is None


def test_the_export_strip_clears_keys_and_their_events(pair, clean_env):
    with closing(connect(pair)) as db:
        keys.save(db, 'rebrickable', {'key': 'stored-rebrickable-key'})
        admin.audit(db, 'copy:1', 'f', new='kept')
        assert db.execute("SELECT count(*) FROM event WHERE entity_kind='source_key' AND new_value IS NOT NULL").fetchone()[0] == 1
        db.commit()                                                                        # a backup waits for an open write forever
        with closing(sqlite3.connect(':memory:')) as snapshot:
            db.backup(snapshot)
            keys.strip(snapshot)
            assert snapshot.execute('SELECT count(*) FROM source_key').fetchone()[0] == 0
            assert snapshot.execute("SELECT count(*) FROM event WHERE entity_kind='source_key' AND new_value IS NOT NULL").fetchone()[0] == 0
            assert snapshot.execute("SELECT new_value FROM event WHERE entity_kind='copy'").fetchone()[0] == 'kept'
            assert snapshot.execute("SELECT count(*) FROM sqlite_master WHERE name='event_no_update'").fetchone()[0] == 1


# ---------- the drainer ----------

def test_the_drainer_polls_only_the_4_0_job_kinds(db):
    assert drainer.poll_delay(db) is None and not drainer.pending(db)
    db.execute("INSERT INTO source(id, name, kind) VALUES('bricklink', 'BrickLink', 'api') ON CONFLICT DO NOTHING")
    insert = ("INSERT INTO job(source, kind, state, retry_at, via, created_at, updated_at) VALUES('bricklink', ?, ?, ?, 'app', 't', 't')")
    db.execute(insert, ('import', 'queued', None))                                       # the 3.3 pipeline's kind is not this runner's
    assert drainer.poll_delay(db) is None
    db.execute(insert, ('bricklink_subsets', 'waiting_for_budget', '2999-01-01T00:00:00.000Z'))
    assert drainer.pending(db) and drainer.poll_delay(db) == 60
    db.execute(insert, ('bricklink_subsets', 'queued', None))
    assert drainer.poll_delay(db) == 1


# ---------- core.items ----------

def part(db, key):
    return item_id(db, 'parts', key)


def test_the_kind_vocabulary_and_the_type_letters_are_a_bijection():
    assert items.KINDS == ('set', 'part', 'minifigure', 'instructions', 'box', 'gear', 'book', 'catalog')
    for kind in items.KINDS:
        assert items.kind_of_type(items.type_of_kind(kind)) == kind
    assert items.type_of_kind('minifigure') == 'M' and items.kind_of_type('O') == 'box'
    with pytest.raises(errors.ValidationFailed):
        items.type_of_kind('part number')
    with pytest.raises(errors.ValidationFailed):
        items.kind_of_type('X')


def test_label_shows_the_rebrickable_number_first_and_the_bricklink_one_where_it_differs(db):
    brick = items.label(db, part(db, '3001'))
    assert (brick.number, brick.source, brick.also, brick.kind, brick.unidentified) == ('3001', 'rebrickable', None, 'part', False)
    assert brick.bricklink == ('P', '3001', None) and brick.text == '3001' and brick.name == 'Brick 2 x 4'
    legs = items.label(db, part(db, '970c03'))
    assert (legs.number, legs.also, legs.bricklink) == ('970c03', '970c11', ('P', '970c11', None))
    assert legs.text == '970c03 · BrickLink 970c11'
    black = items.label(db, part(db, '970c03'), colour_id(db, '0'))
    scoped = items.label(db, part(db, '970c03'), colour_id(db, '15'))
    assert {black.also, scoped.also} <= {'970c00', '970c11'}
    figure = items.label(db, item_id(db, 'minifigs', 'fig-000004'))
    assert (figure.number, figure.also, figure.kind) == ('fig-000004', 'syn-fig-0004', 'minifigure')
    assert items.label(db, item_id(db, 'sets', '2070-1')).text == '2070-1'
    assert figure.as_dict()['text'] == figure.text


def test_label_reads_a_projected_item_from_the_collection_and_marks_a_local_bricklink_born_item(live):
    db = live
    legs = part(db, '970c03')
    items.ensure(db, legs)
    db.commit()
    assert db.execute('SELECT 1 FROM main.item WHERE id=?', (legs,)).fetchone()
    assert items.label(db, legs).bricklink == ('P', '970c11', None)
    stamp = '2026-10-26T00:00:00.000Z'
    db.execute("INSERT INTO item(id, origin, kind, kind_source, name, born_provider, born_namespace, born_key, created_at, updated_at)"
               " VALUES(1000000001, 'local', 'part', 'bricklink', 'Only on BrickLink', 'bricklink', 'P', 'x999', ?, ?)", (stamp, stamp))
    db.execute("INSERT INTO item(id, origin, kind, kind_source, name, created_at, updated_at) VALUES(1000000002, 'local', 'gear', 'manual', 'Mystery', ?, ?)", (stamp, stamp))
    local, mystery = items.label(db, 1000000001), items.label(db, 1000000002)
    assert (local.number, local.source, local.also, local.bricklink) == ('x999', 'bricklink', None, ('P', 'x999', None))
    assert local.text == 'x999 (BrickLink)'
    assert (mystery.number, mystery.unidentified, mystery.bricklink, mystery.text) == (None, True, None, 'Mystery')
    with pytest.raises(items.Unidentified):
        items.bricklink_key(db, 1000000002)
    assert issubclass(items.Unidentified, errors.BrickWorkError) and items.Unidentified('x').status == 422
    with pytest.raises(errors.NotFound):
        items.label(db, 999999)


def test_bricklink_key_goes_through_the_links_and_raises_when_none_names_the_item(db):
    assert items.bricklink_key(db, part(db, '3023')) == ('P', '3023', None)
    assert items.bricklink_key(db, item_id(db, 'sets', '2070-1'), None)[:2] == ('S', '2070-1')
    coloured = items.bricklink_key(db, part(db, '3023'), colour_id(db, '15'))
    assert coloured[:2] == ('P', '3023') and coloured[2] is not None                     # the BrickLink colour number of that colour
    with pytest.raises(items.Unidentified, match='no BrickLink number'):
        items.bricklink_key(db, item_id(db, 'sets', '10018247-1'))                       # the gear has no BrickLink link in the fixture
    with pytest.raises(errors.NotFound):
        items.bricklink_key(db, 424242)


def test_find_takes_both_numbers_born_key_first(db):
    by_born = items.find(db, 'part', '970c03')
    assert [(r['item_id'], r['matched_by']) for r in by_born][:1] == [(part(db, '970c03'), 'born')]
    by_bricklink = items.find(db, 'part', '970c11')
    assert part(db, '970c03') in [r['item_id'] for r in by_bricklink] and by_bricklink[0]['matched_by'] in ('search', 'bricklink')
    assert [r['item_id'] for r in items.find(db, None, '3001')] == [part(db, '3001')]
    assert items.find(db, 'set', '3001') == []                                           # the kind filters
    assert items.find(db, 'minifigure', 'SYN-FIG-0004')[0]['item_id'] == item_id(db, 'minifigs', 'fig-000004')
    assert items.find(db, 'part', '') == [] and items.find(db, 'part', '  ') == [] and items.find(db, None, '"-"') == []
    assert len(items.find(db, None, '3001', limit=0)) == 0
    with pytest.raises(errors.ValidationFailed):
        items.find(db, 'S', '3001')


def test_find_sees_the_collections_own_items_and_follows_a_merge(live):
    db = live
    stamp = '2026-10-26T00:00:00.000Z'
    legs = part(db, '970c03')
    items.ensure(db, legs)
    db.execute("INSERT INTO item(id, origin, kind, kind_source, name, born_provider, born_namespace, born_key, created_at, updated_at)"
               " VALUES(1000000001, 'local', 'part', 'bricklink', 'Only on BrickLink', 'bricklink', 'P', 'x999', ?, ?)", (stamp, stamp))
    assert [r['item_id'] for r in items.find(db, 'part', 'X999')] == [1000000001]
    assert items.find(db, 'part', 'x999')[0]['matched_by'] == 'born'
    db.execute("INSERT INTO item_link(item_id, provider, provider_kind, provider_key, status, method, origin, decided_at)"
               " VALUES(?, 'bricklink', 'P', 'zzz1', 'manual', 'user', 'user', ?)", (legs, stamp))
    assert [(r['item_id'], r['matched_by']) for r in items.find(db, 'part', 'zzz1')] == [(legs, 'bricklink')]
    db.execute('UPDATE item SET merged_into=? WHERE id=1000000001', (legs,))
    assert [r['item_id'] for r in items.find(db, 'part', 'x999')] == [legs]


def test_ensure_projects_inside_the_callers_transaction_and_rolls_back_with_it(live):
    db = live
    brick = part(db, '3001')
    db.execute('BEGIN IMMEDIATE')
    assert items.ensure(db, brick) == brick
    assert db.execute('SELECT count(*) FROM main.item_link WHERE item_id=?', (brick,)).fetchone()[0] == 1
    db.rollback()
    assert db.execute('SELECT 1 FROM main.item WHERE id=?', (brick,)).fetchone() is None
    assert items.ensure(db, brick) == brick
    db.commit()
    assert db.execute('SELECT 1 FROM main.item WHERE id=?', (brick,)).fetchone()


# ---------- guards ----------

def test_store4_does_not_import_core():
    for path in sorted((Path(__file__).resolve().parents[1] / 'brickwork' / 'store4').glob('*.py')):
        text = path.read_text()
        assert not re.search(r'^\s*(from|import)\s+(brickwork\.core|\.\.core|\.\.\s+import\s+core)', text, re.M), path.name



def test_the_adapter_and_store4_events_store_values_by_the_same_rule(db):
    from brickwork.store4.audit import Events
    values = ('a', {'b': 1, 'a': 2}, [1, 2], 3, None)
    with db:
        for v in values:
            admin.audit(db, 'copy:x', 'app', None, v)
            Events(db, 'app', None).write('copy', 'x', 'store4', None, v)
    rows = db.execute("SELECT field, new_value FROM event WHERE entity_id='x' ORDER BY id").fetchall()
    assert [r[1] for r in rows if r[0] == 'app'] == [r[1] for r in rows if r[0] == 'store4'] == ['a', '{"a": 2, "b": 1}', '[1, 2]', '3', None]


def test_start_up_checks_the_collection_the_app_config_names(tmp_path, monkeypatch):
    """Codex on M.8a: the start-up check resolved the path outside the app context, so a path from the app's config was not the
    one checked (an unrelated data/brickwork.db was, or nothing)."""
    from flask import Flask
    from brickwork.app import setup_app
    root = Path(__file__).resolve().parents[1]
    monkeypatch.delenv('BW_DB_PATH', raising=False)
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    monkeypatch.chdir(tmp_path)                                                   # no data/brickwork.db here
    legacy = tmp_path / 'elsewhere' / 'brickwork.db'
    legacy.parent.mkdir()
    create_33(legacy).close()
    app = Flask('config-path', template_folder=str(root / 'templates'), static_folder=str(root / 'static'))
    app.config['BRICKWORK_DB_PATH'] = str(legacy)
    with pytest.raises(OldStore):
        setup_app(app)
