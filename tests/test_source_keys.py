"""The encrypted source-key store on the 4.0 store (M.8f, issue #110): `source_key`, its events and Undo, the provider the fetchers read.

The Catalogues & keys screen that drives it is M.8i's (test_bw_ui_12l.py, test_bw_api_m5_web.py). Invented keys only."""
import json
import sqlite3

from cryptography.fernet import Fernet
import pytest

from brickwork.core import errors, keys, secrets, source_ops, undo
from brickwork.store4 import keys as store_keys
from brickwork.core.sources import base
from brickwork.core.sources.brickset import Brickset
from tests.app4 import coll, pair  # noqa: F401 (fixtures)
from tests.sources4 import Net, keyed, unkeyed

KEY = 'synthetic-key-0001'
BRICKLINK = dict(consumer_key='ck-123456', consumer_secret='cs-123456', token_value='tv-123456', token_secret='ts-123456')


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    unkeyed(monkeypatch)
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    secrets.forget()
    yield
    secrets.forget()
    store_keys.set_key_provider(None)


def rows(coll):
    return [tuple(r) for r in coll.db.execute('SELECT source, archived_at IS NOT NULL FROM source_key ORDER BY source')]


def events(coll):
    return [tuple(r) for r in coll.db.execute("SELECT entity_id, field FROM event WHERE entity_kind='source_key' ORDER BY id")]


def test_a_saved_key_is_encrypted_and_only_its_state_is_ever_returned(coll):
    state = keys.save(coll.db, 'rebrickable', {'key': KEY})
    assert state['configured'] and state['origin'] == 'stored' and set(state) == {'configured', 'origin', 'saved_at'}
    cipher = coll.db.execute('SELECT ciphertext FROM source_key').fetchone()[0]
    assert KEY not in cipher and secrets.decrypt(cipher)
    assert keys.credentials(coll.db, 'rebrickable', ('BW_REBRICKABLE_API_KEY',)) == (KEY,)
    assert keys.state(coll.db, 'rebrickable', ('BW_REBRICKABLE_API_KEY',))['origin'] == 'stored'
    assert KEY not in json.dumps([dict(r) for r in coll.db.execute('SELECT * FROM event')])             # an event holds metadata, never the value
    bundle = {**BRICKLINK, 'consumer_key': 'ck-123456'}
    keys.save(coll.db, 'bricklink', bundle)
    assert keys.credentials(coll.db, 'bricklink', keys.ENV['bricklink']) == ('ck-123456', 'cs-123456', 'tv-123456', 'ts-123456')


def test_the_environment_wins_over_the_store_and_a_partial_environment_does_not_count(coll, monkeypatch):
    keys.save(coll.db, 'rebrickable', {'key': KEY})
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', 'environment-key-9')
    assert keys.credentials(coll.db, 'rebrickable', ('BW_REBRICKABLE_API_KEY',)) == ('environment-key-9',)
    assert keys.state(coll.db, 'rebrickable', ('BW_REBRICKABLE_API_KEY',))['origin'] == 'env'
    monkeypatch.delenv('BW_REBRICKABLE_API_KEY')
    monkeypatch.setenv('BW_BRICKLINK_CONSUMER_KEY', 'only-one-of-four')
    assert not keys.state(coll.db, 'bricklink', keys.ENV['bricklink'])['configured']
    with pytest.raises(base.SourceNotConfigured, match='BrickLink key is not configured'):
        keys.credentials(coll.db, 'bricklink', keys.ENV['bricklink'])


def test_the_provider_the_fetchers_read_follows_the_environment_then_the_store(coll, pair, monkeypatch):
    keys.save(coll.db, 'rebrickable', {'key': KEY})
    keys.save(coll.db, 'bricklink', BRICKLINK)
    keys.install(pair)
    assert store_keys.get('BW_REBRICKABLE_API_KEY') == KEY and store_keys.get('BW_BRICKLINK_TOKEN_SECRET') == 'ts-123456' and store_keys.get('BW_BRICKSET_API_KEY') is None
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', 'environment-key-9')
    assert store_keys.get('BW_REBRICKABLE_API_KEY') == 'environment-key-9'
    keys.archive(coll.db, 'rebrickable')
    monkeypatch.delenv('BW_REBRICKABLE_API_KEY')
    assert store_keys.get('BW_REBRICKABLE_API_KEY') is None                       # an archived key stops being used
    assert KEY in secrets.secret_values({'BW_X_KEY': KEY}) and KEY in secrets.REMEMBERED


def test_input_is_validated_without_echoing_the_value(coll, monkeypatch):
    for source, payload in (('rebrickable', {'key': 'short'}), ('rebrickable', {'token': KEY}), ('bricklink', {'consumer_key': KEY}), ('rebrickable', 'x')):
        with pytest.raises(errors.ValidationFailed) as caught:
            keys.save(coll.db, source, payload)
        assert KEY not in str(caught.value) and 'short' not in str(caught.value)
    with pytest.raises(errors.NotFound):
        keys.save(coll.db, 'nowhere', {'key': KEY})
    with pytest.raises(errors.ValidationFailed, match='needs no key'):
        keys.save(coll.db, 'brickognize', {'key': KEY})
    assert rows(coll) == []
    monkeypatch.delenv('BW_SECRET_KEY')
    with pytest.raises(errors.SourceNotConfigured, match='disabled'):
        keys.save(coll.db, 'rebrickable', {'key': KEY})
    assert not secrets.entry_available()


def test_a_replacement_keeps_the_earlier_key_and_undo_restores_it(coll):
    keys.save(coll.db, 'rebrickable', {'key': KEY})
    first = coll.db.execute('SELECT ciphertext, saved_at FROM source_key').fetchone()
    keys.save(coll.db, 'rebrickable', {'key': 'second-key-0002'})
    assert keys.credentials(coll.db, 'rebrickable', ('BW_REBRICKABLE_API_KEY',)) == ('second-key-0002',)
    event = coll.db.execute("SELECT id FROM event WHERE entity_kind='source_key' AND field='save' ORDER BY id DESC").fetchone()[0]
    assert coll.db.execute('SELECT saved_at FROM source_key_previous').fetchone()[0] == first['saved_at']
    result = undo.undo_event(coll.db, event)
    assert result['already_undone'] is False and keys.credentials(coll.db, 'rebrickable', ('BW_REBRICKABLE_API_KEY',)) == (KEY,)
    assert coll.db.execute('SELECT count(*) FROM source_key_previous').fetchone()[0] == 0 and coll.db.execute('SELECT count(*) FROM event_undo').fetchone()[0] == 1
    assert undo.undo_event(coll.db, event)['already_undone'] is True


def test_undoing_the_first_save_archives_the_key_and_undoing_an_archive_brings_it_back(coll):
    keys.save(coll.db, 'rebrickable', {'key': KEY})
    save = coll.db.execute("SELECT id FROM event WHERE field='save'").fetchone()[0]
    undo.undo_event(coll.db, save)
    assert rows(coll) == [('rebrickable', 1)] and not keys.state(coll.db, 'rebrickable', ('BW_REBRICKABLE_API_KEY',))['configured']
    keys.save(coll.db, 'rebrickable', {'key': KEY})                              # saving again replaces the archived one
    keys.archive(coll.db, 'rebrickable')
    archive = coll.db.execute("SELECT id FROM event WHERE field='archive'").fetchone()[0]
    assert rows(coll) == [('rebrickable', 1)]
    undo.undo_event(coll.db, archive)
    assert rows(coll) == [('rebrickable', 0)] and keys.credentials(coll.db, 'rebrickable', ('BW_REBRICKABLE_API_KEY',)) == (KEY,)
    assert events(coll)[-1] == ('rebrickable', 'undo')
    with pytest.raises(errors.NotFound):
        keys.archive(coll.db, 'nowhere')
    with pytest.raises(errors.NotFound, match='No stored key'):
        keys.archive(coll.db, 'brickset')


def test_a_later_change_blocks_the_undo_of_an_earlier_one(coll):
    keys.save(coll.db, 'rebrickable', {'key': KEY})
    first = coll.db.execute("SELECT id FROM event WHERE field='save'").fetchone()[0]
    keys.save(coll.db, 'rebrickable', {'key': 'second-key-0002'})
    with pytest.raises(errors.UndoBlocked, match='undo the later save first'):
        undo.undo_event(coll.db, first)
    assert keys.credentials(coll.db, 'rebrickable', ('BW_REBRICKABLE_API_KEY',)) == ('second-key-0002',)
    keys.archive(coll.db, 'rebrickable')
    second = coll.db.execute("SELECT id FROM event WHERE field='save' ORDER BY id DESC").fetchone()[0]
    with pytest.raises(errors.UndoBlocked):
        undo.undo_event(coll.db, second)


def test_a_key_can_be_proved_with_one_budgeted_call(coll):
    keys.save(coll.db, 'rebrickable', {'key': KEY})
    checked = keys.check(coll.db, 'rebrickable', http=Net({'id': 0, 'name': '[Unknown]'}))
    assert checked['ok'] is True and checked['source'] == 'rebrickable' and KEY not in json.dumps(checked)
    assert coll.db.execute("SELECT used FROM source_budget WHERE source='rebrickable'").fetchone()[0] == 1
    with pytest.raises(base.KeyRejected):
        keys.check(coll.db, 'rebrickable', http=Net({'detail': 'Invalid token.'}))
    with pytest.raises(errors.ValidationFailed):
        keys.check(coll.db, 'brickognize')


def test_an_export_copy_loses_every_key_and_the_event_values_about_them(coll, tmp_path):
    keys.save(coll.db, 'rebrickable', {'key': KEY})
    keys.save(coll.db, 'rebrickable', {'key': 'second-key-0002'})
    keys.archive(coll.db, 'rebrickable')
    target = tmp_path / 'copy.db'
    coll.db.execute('VACUUM main INTO ?', (str(target),))
    snapshot = sqlite3.connect(target)
    keys.strip(snapshot)
    assert [snapshot.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ('source_key', 'source_key_previous')] == [0, 0]
    assert snapshot.execute("SELECT count(*) FROM event WHERE entity_kind='source_key' AND (old_value IS NOT NULL OR new_value IS NOT NULL)").fetchone()[0] == 0
    assert snapshot.execute("SELECT count(*) FROM sqlite_master WHERE name='event_no_update'").fetchone()[0] == 1       # the append-only trigger is back
    assert b'second-key-0002' not in target.read_bytes() and KEY.encode() not in target.read_bytes()
    snapshot.close()


def test_the_source_switch_is_audited_and_undoable(coll, monkeypatch):
    source_ops.toggle(coll.db, 'brickset', False)
    assert coll.db.execute("SELECT enabled FROM source WHERE id='brickset'").fetchone()[0] == 0
    event = coll.db.execute("SELECT id, old_value, new_value FROM event WHERE entity_kind='source' AND field='enabled'").fetchone()
    assert (event['old_value'], event['new_value']) == ('1', '0')
    keyed(monkeypatch, 'brickset')
    with pytest.raises(base.SourceDisabled):
        Brickset(coll.db, http=Net({})).check_key()
    undo.undo_event(coll.db, event['id'])
    assert coll.db.execute("SELECT enabled FROM source WHERE id='brickset'").fetchone()[0] == 1
    for bad in ('yes', 1, None):
        with pytest.raises(errors.ValidationFailed):
            source_ops.toggle(coll.db, 'brickset', bad)
    with pytest.raises(errors.NotFound):
        source_ops.toggle(coll.db, 'nowhere', True)
    view = source_ops.view(coll.db, 'brickset')
    assert view['source'] == 'brickset' and view['enabled'] is True and view['key'] == 'set' and view['budget'] == 100 and view['used_today'] == 0
