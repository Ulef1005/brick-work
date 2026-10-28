"""API v2 reads of M.11d (issue #113): every GET of orders, jobs, sources, sync, exchange rates, the database, identifications and tokens against
the contract, and what they share with the other reads (a wrong token is 401, an unknown filter 400, a read token may read what is read, admin
stays admin). Ported from the all-GETs part of test_bw_api_m2 and the secret sweep of test_bw_api_m5. Invented data, no network."""
from contextlib import closing
import json

from cryptography.fernet import Fernet
import pytest

from brickwork.core import identify
from brickwork.core.connect import connect
from brickwork.core.media import media_root
from tests.api2 import CONTRACT, OPERATION_BY_ID, PREFIX, call, events, fake, png, stored_token, v2, validate, wire, write  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401
from tests.test_api2_write_orders import saved
from tests.test_bw_sync import Rebrickable, TOKEN

READS = sorted(op for op, o in OPERATION_BY_ID.items() if o['x-piece'] == 'M.11d' and any(m == 'get' for p in CONTRACT['paths'].values() for m, d in p.items()
                                                                                        if isinstance(d, dict) and d['operationId'] == op))
ADMIN = {'get_tokens', 'get_database_check', 'get_database_export'}


@pytest.fixture
def full(v2, world, pair, coll, wire, monkeypatch):
    from brickwork.core.sync import adapters
    monkeypatch.setattr(adapters.RebrickableUser, 'minimum_spacing', 0)
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    monkeypatch.setattr(adapters, 'transport', Rebrickable())
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', 'synthetic-rebrickable-key')
    assert write(v2, '/sources/rebrickable/user', 'put', {'value': TOKEN}).status_code == 200
    order, document, line = saved(v2)
    with closing(connect(pair)) as db:
        stored = identify.store(db, media_root(db), png(), [{'item_id': world.brick, 'score': 0.9, 'name': 'Brick'}])
    write(v2, '/items/%d/prices/refresh' % world.keep, body={})
    return dict(order=order, ident=stored['id'])


def paths(w, f):
    return {'get_orders': '/orders', 'get_orders_export_csv': '/orders/export.csv', 'get_orders_by_id': f"/orders/{f['order']}",
            'get_orders_by_id_short_xml': f"/orders/{f['order']}/short.xml", 'get_orders_by_id_allocation_review': f"/orders/{f['order']}/allocation-review",
            'get_orders_by_id_allocations': f"/orders/{f['order']}/allocations", 'get_orders_by_id_history': f"/orders/{f['order']}/history",
            'get_jobs': '/jobs', 'get_jobs_by_id': '/jobs/1', 'get_sources': '/sources', 'get_sync_by_source': '/sync/rebrickable',
            'get_sync_by_source_lists': '/sync/rebrickable/lists', 'get_exchange_rates': '/exchange-rates', 'get_database_check': '/database/check',
            'get_database_export': '/database/export', 'get_identifications': '/identifications', 'get_identifications_by_id': f"/identifications/{f['ident']}",
            'get_identifications_by_id_thumb': f"/identifications/{f['ident']}/thumb", 'get_tokens': '/tokens'}


def test_every_read_of_the_piece_has_a_case(world):
    assert len(READS) == 19 and set(paths(world, {'order': 1, 'ident': 'x'})) == set(READS)


@pytest.mark.parametrize('operation', READS)
def test_the_answer_is_what_the_contract_says(v2, world, full, operation):
    response = call(v2, paths(world, full)[operation])
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    validate(response, operation)
    assert response.headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('operation', READS)
def test_a_wrong_token_is_401_and_an_unknown_filter_400(v2, world, full, operation):
    url = paths(world, full)[operation]
    assert call(v2, url, token='invalid').status_code == 401
    refused = call(v2, url + ('&' if '?' in url else '?') + 'synthetic_unknown=x')
    assert refused.status_code == 400 and refused.json['code'] == 'unknown_filter', refused.get_data(as_text=True)


@pytest.mark.parametrize('operation', READS)
def test_the_scope_is_the_contracts_and_a_read_only_instance_still_reads(v2, world, full, pair, operation, monkeypatch):
    reader = stored_token(pair, ['read'])
    expected = 403 if operation in ADMIN else 200
    assert call(v2, paths(world, full)[operation], token=reader).status_code == expected
    assert OPERATION_BY_ID[operation]['security'][0]['bearerAuth'][0] == ('admin' if operation in ADMIN else 'read')
    monkeypatch.setenv('BW_READ_ONLY', 'true')
    assert call(v2, paths(world, full)[operation]).status_code == 200


def test_no_secret_leaves_through_any_answer_log_event_or_file(v2, world, full, wire, pair, monkeypatch, caplog):
    import logging
    from tests.api2 import upload, BL_ENV
    caplog.set_level(logging.DEBUG)
    old, new = fake(32), fake(32)
    for name in (*BL_ENV, 'BW_BRICKSET_API_KEY'):
        monkeypatch.setenv(name, fake(32))
    wire.replies['rebrickable.com'] = lambda request: json.dumps({'id': 0, 'detail': 'Invalid token ' + request.headers['Authorization']})
    wire.replies['brickset.com'] = lambda request: json.dumps({'status': 'error', 'message': 'bad ' + request.data.decode()})
    wire.replies['api.brickognize.com'] = json.dumps({'items': []})
    collected = []

    def keep(response):
        collected.append((response.status_code, '\n'.join(f'{k}: {v}' for k, v in response.headers.items()),
                          '' if response.mimetype.startswith(('image/', 'application/vnd')) else response.get_data(as_text=True)))
        return response
    key = lambda body, **kw: keep(write(v2, '/sources/rebrickable/key', 'put', body, **kw))
    key({'key': old})
    key({'key': new}, key='k1')
    key({'key': new}, key='k1')
    key({'key': 'short'})
    keep(write(v2, '/sources/rebrickable/key/test'))                                 # rebrickable echoes the header in its error
    keep(write(v2, '/sources/brickset/key/test'))                                    # brickset echoes the form body
    keep(write(v2, '/jobs/drain'))
    keep(upload(v2, '/identifications', png()))
    keep(write(v2, '/sources/rebrickable/key', 'delete'))
    for path in paths(world, full).values():
        keep(call(v2, path))
    for path in ('/events?limit=200', '/settings', '/me', '/version', '/health'):
        keep(call(v2, path))
    secret_text = [new, old, *[__import__('os').environ[n] for n in (*BL_ENV, 'BW_BRICKSET_API_KEY')]]
    for status, headers, body in collected:
        for needle in secret_text:
            assert needle not in body + headers, needle[:4]
    for needle in secret_text:
        assert needle not in caplog.text
        assert not [e for e in events(pair) if needle in json.dumps(e)]
    import pathlib
    for path in pathlib.Path(pair).parent.rglob('*'):
        if path.is_file():
            data = path.read_bytes()
            for needle in (old, new):
                assert needle.encode() not in data, path.name
    assert any(status >= 400 for status, _, _ in collected)
