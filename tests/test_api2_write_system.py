"""API v2 tokens, exchange rates and the database (M.11d, issue #113). Ported from test_bw_api_m1 (the token cases), test_bw_currency_39_api and
test_bw_api_m5 (export) onto the 4.0 store; every answer is validated against `openapi-v2.yaml`. Invented data, no network."""
from contextlib import closing
import json
import sqlite3

import pytest

from tests.api2 import call, events, fake, row, rows, stored_token, v2, validate, write  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401


def created(v2, name='synthetic-client', scopes=('read',), **extra):
    return write(v2, '/tokens', body=dict(name=name, scopes=list(scopes), **extra))


# ---------- tokens ----------

def test_a_token_is_created_listed_revoked_and_never_shows_its_secret_again(v2, pair):
    made = created(v2, scopes=('read', 'write'))
    validate(made, 'post_tokens', '201')
    secret, token = made.json['data']['secret'], made.json['data']['token']
    assert token['scopes'] == ['read', 'write'] and 'hash' not in token and made.json['undo_url'] == f"/api/v2/events/{made.json['event_id']}/undo"
    assert call(v2, '/me', token=secret).json['data']['name'] == 'synthetic-client'
    listed = call(v2, '/tokens')
    validate(listed, 'get_tokens')
    assert [t['name'] for t in listed.json['data']] == ['synthetic-client'] and secret not in listed.text
    revoked = write(v2, f"/tokens/{token['id']}", 'delete')
    validate(revoked, 'delete_tokens_by_id')
    assert revoked.json['data']['revoked_at'] and call(v2, '/me', token=secret).status_code == 401
    again = write(v2, f"/tokens/{token['id']}", 'delete')
    assert again.status_code == 409 and write(v2, '/tokens/nope', 'delete').status_code == 404


def test_undo_of_a_creation_revokes_and_undo_of_a_revocation_restores(v2, pair):
    made = created(v2)
    secret, identifier = made.json['data']['secret'], made.json['data']['token']['id']
    revoked = write(v2, f'/tokens/{identifier}', 'delete')
    assert write(v2, f"/events/{revoked.json['event_id']}/undo").status_code == 200
    assert call(v2, '/me', token=secret).status_code == 200
    assert write(v2, f"/events/{made.json['event_id']}/undo").status_code == 200
    assert call(v2, '/me', token=secret).status_code == 401
    blocked = created(v2, 'second')
    write(v2, f"/tokens/{blocked.json['data']['token']['id']}", 'delete')
    assert write(v2, f"/events/{blocked.json['event_id']}/undo").json['code'] == 'undo_blocked'


def test_token_input_is_checked_and_a_name_is_taken_once(v2):
    assert created(v2, 'bootstrap').status_code == 422
    assert write(v2, '/tokens', body={'name': 'x', 'scopes': ['root']}).status_code == 422
    assert write(v2, '/tokens', body={'name': 'x', 'scopes': []}).status_code == 422
    assert write(v2, '/tokens', body={'name': 'x', 'scopes': ['read'], 'expires_at': '2001-01-01T00:00:00+00:00'}).status_code == 422
    assert write(v2, '/tokens', body={'name': 'x', 'scopes': ['read'], 'extra': 1}).status_code == 422
    assert created(v2, 'twin').status_code == 201 and created(v2, 'twin').status_code == 409


def test_tokens_need_admin_and_a_listing_pages(v2, pair):
    writer = stored_token(pair, ['read', 'write'], 'writer')
    assert call(v2, '/tokens', token=writer).status_code == 403
    assert write(v2, '/tokens', body={'name': 'x', 'scopes': ['read']}, token=writer).status_code == 403
    for n in range(5):
        created(v2, f'client-{n}')
    first = call(v2, '/tokens?limit=3')
    validate(first, 'get_tokens')
    assert len(first.json['data']) == 3 and first.json['page']['next_cursor']
    second = call(v2, '/tokens?limit=3&cursor=' + first.json['page']['next_cursor'])
    assert len(second.json['data']) == 3 and not set(t['id'] for t in first.json['data']) & set(t['id'] for t in second.json['data'])
    assert [t['name'] for t in call(v2, '/tokens?direction=desc').json['data']][0] == 'writer'
    assert call(v2, '/tokens?sort=name').status_code == 400


def test_a_created_token_replays_with_its_key_and_the_secret_is_stored_nowhere(v2, pair):
    first = write(v2, '/tokens', body={'name': 'replayed', 'scopes': ['read']}, key='tok-1')
    again = write(v2, '/tokens', body={'name': 'replayed', 'scopes': ['read']}, key='tok-1')
    assert again.json['idempotent_replay'] is True and again.status_code == 201
    secret = first.json['data']['secret']
    assert secret and again.json['data']['secret'] is None and again.json['data']['token'] == first.json['data']['token']          # shown once
    with closing(sqlite3.connect(str(pair))) as raw:
        assert not any(secret in str(each) for table in ('event', 'api_token') for r in raw.execute(f'SELECT * FROM {table}') for each in r)
    assert write(v2, '/tokens', body={'name': 'other', 'scopes': ['read']}, key='tok-1').json['code'] == 'idempotency_conflict'


# ---------- exchange rates ----------

def test_a_rate_is_entered_listed_and_removed(v2, world, pair):
    put = write(v2, '/exchange-rates/usd', 'put', {'per_eur': '1.17'})
    validate(put, 'put_exchange_rates_by_code')
    assert put.json['data'][0]['currency'] == 'USD' and put.json['data'][0]['source'] == 'manual'
    listed = call(v2, '/exchange-rates')
    validate(listed, 'get_exchange_rates')
    assert listed.json['display_currency'] == 'EUR' and [r['per_eur'] for r in listed.json['data']] == ['1.17']
    assert write(v2, '/exchange-rates/USD', 'put', {'per_eur': None}).json['data'] == []
    for body, code in (({'per_eur': '1'}, 'EUR'), ({'per_eur': '0'}, 'USD'), ({'per_eur': 'x'}, 'USD'), ({'per_eur': '-2'}, 'USD')):
        assert write(v2, f'/exchange-rates/{code}', 'put', body).status_code == 422, (body, code)
    assert write(v2, '/exchange-rates/USDX', 'put', {'per_eur': '1'}).status_code == 422
    assert call(v2, '/exchange-rates', token=stored_token(pair, ['read'])).status_code == 200
    assert write(v2, '/exchange-rates/USD', 'put', {'per_eur': '1'}, token=stored_token(pair, ['read', 'write'], 'w')).status_code == 403


ECB = '''<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
<Cube><Cube time="2026-10-27"><Cube currency="USD" rate="1.1700"/><Cube currency="GBP" rate="0.8600"/></Cube></Cube></gesmes:Envelope>'''


def test_the_ecb_feed_is_loaded_outside_a_transaction_and_keeps_a_hand_entered_rate(v2, world, monkeypatch):
    from brickwork.core.sources import base
    seen = []
    monkeypatch.setattr(base, 'transport', lambda request: seen.append(request.full_url) or ECB)
    write(v2, '/exchange-rates/USD', 'put', {'per_eur': '1.20'})
    loaded = write(v2, '/exchange-rates/ecb', key='ecb-1')
    validate(loaded, 'post_exchange_rates_ecb')
    assert loaded.json['data'] == {'as_of': '2026-10-27', 'updated': 1, 'kept_manual': 1} and len(seen) == 1
    again = write(v2, '/exchange-rates/ecb', key='ecb-1')
    assert again.json['idempotent_replay'] is True and len(seen) == 1
    rates = {r['currency']: r for r in call(v2, '/exchange-rates').json['data']}
    assert rates['USD']['source'] == 'manual' and rates['GBP']['source'] == 'ecb'
    monkeypatch.setattr(base, 'transport', lambda request: 'not xml')
    failed = write(v2, '/exchange-rates/ecb', key='ecb-2')
    assert failed.status_code >= 400 and failed.json['code'] == 'source_error'
    monkeypatch.setattr(base, 'transport', lambda request: ECB)
    assert write(v2, '/exchange-rates/ecb', key='ecb-2').status_code == 200                # a failed call stores no receipt: the key can be sent again


# ---------- the database ----------

def test_the_database_check_reports_integrity_and_counts(v2, world, pair):
    checked = call(v2, '/database/check')
    validate(checked, 'get_database_check')
    data = checked.json['data']
    assert data['integrity_check'] == ['ok'] and data['foreign_key_check'] == [] and data['row_counts']['copy'] == 3
    assert call(v2, '/database/check', token=stored_token(pair, ['read', 'write'], 'w')).status_code == 403


def test_the_export_is_a_snapshot_without_stored_keys(v2, world, pair, monkeypatch, tmp_path):
    from cryptography.fernet import Fernet
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    value = fake()
    assert write(v2, '/sources/rebrickable/key', 'put', {'key': value}).status_code == 200
    exported = call(v2, '/database/export')
    assert exported.status_code == 200 and exported.mimetype == 'application/vnd.sqlite3'
    assert exported.headers['Content-Disposition'] == 'attachment; filename=brickwork.db' and value.encode() not in exported.data
    target = tmp_path / 'export.db'
    target.write_bytes(exported.data)
    with closing(sqlite3.connect(str(target))) as copy:
        assert copy.execute('SELECT count(*) FROM copy').fetchone()[0] == 3 and copy.execute('SELECT count(*) FROM source_key').fetchone()[0] == 0
        assert copy.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name='event_no_update'").fetchone()[0] == 1
    assert call(v2, '/database/export', token=stored_token(pair, ['read', 'write'], 'w')).status_code == 403


# ---------- the rest of the token cases of test_bw_api_m1 ----------

@pytest.mark.parametrize('scope', ['read', 'write', 'admin'])
def test_the_scope_matrix_of_a_new_token(v2, scope):
    secret = created(v2, scopes=(scope,)).json['data']['secret']
    assert call(v2, '/version', token=secret).status_code == 200
    assert call(v2, '/tokens', token=secret).status_code == (200 if scope == 'admin' else 403)


def test_use_is_recorded_once_a_minute_and_the_bootstrap_token_cannot_be_managed(v2, pair):
    secret = created(v2).json['data']['secret']
    assert call(v2, '/tokens').json['data'][0]['last_used_at'] is None
    call(v2, '/me', token=secret)
    first = row(pair, 'SELECT last_used_at FROM api_token')['last_used_at']
    assert first and call(v2, '/tokens').json['data'][0]['last_used_at'] == first
    call(v2, '/me', token=secret)
    assert row(pair, 'SELECT last_used_at FROM api_token')['last_used_at'] == first                 # a second use inside the minute writes nothing
    assert write(v2, '/tokens/bootstrap', 'delete').status_code == 404
    assert call(v2, '/me').json['data']['name'] == 'bootstrap'


def test_stored_tokens_work_without_the_bootstrap_token_and_a_wrong_one_does_not(v2, monkeypatch):
    secret = created(v2).json['data']['secret']
    monkeypatch.delenv('BW_API_TOKEN')
    assert call(v2, '/me', token=secret).status_code == 200
    assert call(v2, '/me', token='wrong').json['code'] == 'unauthorized'


def test_a_token_is_compared_in_constant_time_and_an_expired_one_is_refused(v2, pair, monkeypatch):
    from datetime import timedelta
    from brickwork.core import tokens
    from brickwork.core.sources.base import now
    secret = created(v2).json['data']['secret']
    with closing(sqlite3.connect(str(pair))) as raw, raw:
        raw.execute('UPDATE api_token SET expires_at=?', ((now() - timedelta(seconds=1)).isoformat(),))
    calls = []
    original = tokens.hmac.compare_digest
    monkeypatch.setattr(tokens.hmac, 'compare_digest', lambda a, b: calls.append((a, b)) or original(a, b))
    assert call(v2, '/me', token=secret).status_code == 401 and call(v2, '/me', token='wrong').status_code == 401 and call(v2, '/me').status_code == 200
    assert calls and all(len(a) == len(b) == 64 for a, b in calls)


def test_the_token_commands_of_the_cli_create_list_and_revoke(v2, pair, capsys):
    from brickwork.web.cli import main
    assert main(['token', 'create', '--name', 'synthetic-cli', '--scope', 'read,write', '--expires', '90d']) == 0
    value = json.loads(capsys.readouterr().out)
    assert main(['token', 'list']) == 0 and value['secret'] not in capsys.readouterr().out
    assert call(v2, '/me', token=value['secret']).status_code == 200
    assert main(['token', 'revoke', value['token']['id']]) == 0
    capsys.readouterr()
    assert call(v2, '/me', token=value['secret']).status_code == 401
    assert main(['token', 'create', '--name', 'bootstrap', '--scope', 'admin']) == 1 and 'Token error:' in capsys.readouterr().err


def test_a_token_write_that_fails_in_its_audit_leaves_no_token(v2, monkeypatch):
    from brickwork.core import tokens

    def fail(*args, **kwargs):
        raise RuntimeError('Synthetic audit failure')
    real = tokens.audit
    monkeypatch.setattr(tokens, 'audit', fail)
    assert created(v2).status_code == 500
    monkeypatch.setattr(tokens, 'audit', real)
    assert call(v2, '/tokens').json['data'] == []


def test_the_export_keeps_every_trigger_so_the_events_stay_append_only(v2, world, pair, monkeypatch, tmp_path):
    from cryptography.fernet import Fernet
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    write(v2, '/sources/rebrickable/key', 'put', {'key': fake()})
    exported = call(v2, '/database/export')
    triggers = lambda connection: {r[0]: r[1] for r in connection.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'")}
    with closing(sqlite3.connect(str(pair))) as live, closing(sqlite3.connect(':memory:')) as copy:
        copy.deserialize(exported.data)
        assert triggers(copy) == triggers(live) and 'event_no_update' in triggers(copy)
        with pytest.raises(sqlite3.DatabaseError, match='append-only'):
            copy.execute('UPDATE event SET old_value=NULL')
        with pytest.raises(sqlite3.DatabaseError, match='append-only'):
            copy.execute('DELETE FROM event')
