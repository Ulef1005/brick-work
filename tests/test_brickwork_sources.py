"""Source transport mocks: durable reservations, atomic writes and API shapes."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs
from urllib.request import Request
from unittest.mock import Mock

import pytest

from brickwork.core.connect import connect
from brickwork.core.sources import base, bricklink_catalogue as catalogue
from brickwork.core.sources.bricklink import BrickLink, signed_request
from brickwork.core.sources.brickset import Brickset

FIXTURES = Path(__file__).parent / 'fixtures/brickwork'


@pytest.fixture
def db(tmp_path):
    with closing(connect(tmp_path / 'brickwork.db')) as connection:
        yield connection


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(base, 'transport', Mock(side_effect=AssertionError('network forbidden')))
    monkeypatch.setattr(base.time, 'sleep', lambda _: None)
    for key in (*BrickLink.credentials, *Brickset.credentials):
        monkeypatch.setenv(key, 'secret-' + key)


def reply(data):
    return {'meta': {'code': 200}, 'data': data}


def test_oauth_reference():
    # Reference case from the Web API snapshot.
    request = signed_request('/items/SET/6081-1/price', {'guide_type': 'sold', 'new_or_used': 'N'},
                             ['ck', 'cs', 'tv', 'ts'], timestamp=123, nonce='abc')
    import base64
    import hashlib
    import hmac
    from urllib.parse import quote, unquote
    header = request.get_header('Authorization')
    fields = dict(pair.strip().split('=', 1) for pair in header[6:].split(','))
    signature = unquote(fields.pop('oauth_signature').strip('"'))
    oauth = {k: unquote(v.strip('"')) for k, v in fields.items()}
    params = {'guide_type': 'sold', 'new_or_used': 'N', **oauth}
    q = lambda v: quote(str(v), safe='~')
    normalized = '&'.join(f'{q(k)}={q(v)}' for k, v in sorted(params.items()))
    value = '&'.join(['GET', q('https://api.bricklink.com/api/store/v1/items/SET/6081-1/price'), q(normalized)])
    assert signature == base64.b64encode(hmac.new(b'cs&ts', value.encode(), hashlib.sha1).digest()).decode()


def test_catalogue_all_types_and_previous(db, tmp_path):
    target = tmp_path / 'bricklink-catalog.db'
    result = catalogue.load(FIXTURES, target, db)
    assert result['counts'] == dict.fromkeys('SPMGBCIO', 1)
    with sqlite3.connect(target) as index:
        assert index.execute("SELECT name FROM items WHERE item_type='B'").fetchone()[0] == 'Test (B)'
    previous = target.read_bytes()
    catalogue.load(FIXTURES, target, db)
    assert target.with_name('bricklink-catalog.prev.db').read_bytes() == previous
    bad = tmp_path / 'bad'
    bad.mkdir()
    (bad / 'Sets.xml').write_text('<CATALOG><ITEM><ITEMTYPE>S</ITEMTYPE><ITEMID>1</ITEMID><ITEMNAME>X</ITEMNAME></ITEM></CATALOG>')
    current = target.read_bytes()
    with pytest.raises(ValueError):
        catalogue.load(bad, target, db)
    assert target.read_bytes() == current
    assert db.execute('SELECT count(*) FROM source_records').fetchone()[0] == 16
    assert db.execute("SELECT count(*) FROM events WHERE via!='import'").fetchone()[0] == 0


def test_atomic_replace_failure(db, tmp_path, monkeypatch):
    target = tmp_path / 'bricklink-catalog.db'
    catalogue.load(FIXTURES, target, db)
    catalogue.load(FIXTURES, target, db)
    current, previous = target.read_bytes(), target.with_name('bricklink-catalog.prev.db').read_bytes()
    replace = catalogue.os.replace
    def fail(source, dest):
        if Path(dest) == target:
            raise OSError('install failed')
        return replace(source, dest)
    monkeypatch.setattr(catalogue.os, 'replace', fail)
    with pytest.raises(OSError):
        catalogue.load(FIXTURES, target, db)
    assert target.read_bytes() == current
    assert target.with_name('bricklink-catalog.prev.db').read_bytes() == previous


def test_budget_restart_failure_reset_and_resume(db, monkeypatch):
    monkeypatch.setenv('BW_BRICKLINK_DAILY_BUDGET', '1')
    clock = [datetime(2026, 10, 12, 23, 59, 59, tzinfo=timezone.utc)]
    monkeypatch.setattr(base, 'now', lambda: clock[0])
    http = Mock(side_effect=OSError('secret-BW_BRICKLINK_TOKEN_VALUE'))
    client = BrickLink(db, http=http)
    with pytest.raises(base.SourceError, match='could not be reached'):
        client.call('/colors')
    assert client.status()['used_today'] == 1
    client = BrickLink(db, http=Mock(return_value=reply([])))
    with pytest.raises(base.WaitingForBudget) as waiting:
        client.call('/colors')
    client.http.assert_not_called()
    job = db.execute('SELECT * FROM jobs WHERE id=?', (waiting.value.job_id,)).fetchone()
    assert job['state'] == 'waiting_for_budget' and job['attempts'] == 0
    clock[0] = datetime(2026, 10, 13, tzinfo=timezone.utc)
    assert client.call('/colors', job_id=job['id']) == []
    assert client.status()['used_today'] == 1
    assert db.execute('SELECT state FROM jobs WHERE id=?', (job['id'],)).fetchone()[0] == 'done'
    assert 'secret-' not in str([tuple(r) for r in db.execute('SELECT * FROM events')])


@pytest.mark.parametrize('value', ['0', '-1', 'abc', '1.5'])
def test_invalid_budget(db, monkeypatch, value):
    monkeypatch.setenv('BW_BRICKLINK_DAILY_BUDGET', value)
    with pytest.raises(base.SourceError):
        BrickLink(db)


def test_pacing_crosses_midnight(db, monkeypatch):
    clock = [datetime(2026, 10, 12, 23, 59, 59, 500000, tzinfo=timezone.utc)]
    monkeypatch.setattr(base, 'now', lambda: clock[0])
    client = BrickLink(db, http=lambda _: reply([]))
    client.call('/colors')
    def sleep(delay):
        from datetime import timedelta
        clock[0] += timedelta(seconds=delay)
    monkeypatch.setattr(base.time, 'sleep', sleep)
    client.call('/colors')
    assert [r[0] for r in db.execute('SELECT budget_day FROM jobs ORDER BY id')] == ['2026-10-12', '2026-10-13']


def test_price_precision_fallback_and_parameters(db):
    responses = iter([reply({'total_quantity': 0}), reply({'total_quantity': 3,
        'qty_avg_price': '0.1234567890123456789', 'min_price': '0.1', 'max_price': '0.2'})])
    requests = []
    def http(request):
        requests.append(request)
        return next(responses)
    result = BrickLink(db, http=http).price('P', '3001', 4, 'U')
    assert result['price'] == '0.1234567890123456789' and result['guide'] == 'stock'
    assert 'color_id=4' in requests[0].full_url
    assert 'guide_type=stock' in requests[1].full_url
    assert db.execute('SELECT count(*) FROM price_observations').fetchone()[0] == 2
    assert db.execute('SELECT count(*) FROM source_records').fetchone()[0] == 2
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []


@pytest.mark.parametrize('guide', [None, [], {}, {'total_quantity': -1},
    {'total_quantity': 1, 'qty_avg_price': 'NaN', 'min_price': 1, 'max_price': 2}])
def test_invalid_price_rolls_back_but_keeps_reply(db, guide):
    with pytest.raises(base.SourceError):
        BrickLink(db, http=lambda _: reply(guide)).price('S', '123-1')
    assert db.execute('SELECT count(*) FROM items').fetchone()[0] == 0
    assert db.execute('SELECT count(*) FROM price_observations').fetchone()[0] == 0
    assert db.execute('SELECT status FROM source_records').fetchone()[0] == 'failed'
    assert db.execute('SELECT state FROM jobs').fetchone()[0] == 'failed'


def test_inventory_all_children_extras_and_replace(db):
    entries = [dict(item={'type': kind, 'no': no}, quantity=qty, extra_quantity=extra, color_id=4)
               for kind, no, qty, extra in [('PART', '3001', 3, 1), ('PART', '3001', 2, 0), ('MINIFIG', 'abc', 1, 0)]]
    entries += [dict(entries[0], is_alternate=True), dict(entries[0], is_counterpart=True)]
    client = BrickLink(db, http=lambda _: reply([{'entries': entries}]))
    client.subsets('S', '123-1')
    client.subsets('S', '123-1')
    rows = db.execute('SELECT child_item_type,quantity,extra_quantity FROM inventory_lines ORDER BY child_item_type').fetchall()
    assert [tuple(row) for row in rows] == [('M', 1, 0), ('P', 5, 1)]


def test_item_colors_and_orders(db):
    client = BrickLink(db, http=lambda _: reply({'type': 'SET', 'no': '123-1', 'name': 'Test', 'category_id': 1, 'year_released': 1990}))
    client.item_info('S', '123-1')
    assert db.execute('SELECT name,year FROM items').fetchone()['year'] == 1990
    client.http = lambda _: reply([{'color_id': 4, 'color_name': 'Red', 'color_type': 'Solid'}])
    assert client.sync_colors() == 1
    client.http = Mock(return_value=reply([]))
    client.list_orders(False)
    assert 'filed=false' in client.http.call_args[0][0].full_url
    client.order_items(42)
    assert client.http.call_args[0][0].full_url.endswith('/orders/42/items')
    with pytest.raises(ValueError):
        client.order_items(True)


def test_endpoint_allowlist_and_keys(db, monkeypatch):
    client = BrickLink(db, http=Mock())
    for path in ['/items/SET/../secret', '/orders/abc/items', 'https://evil/colors']:
        with pytest.raises(ValueError):
            client.call(path)
    monkeypatch.delenv(BrickLink.credentials[0])
    with pytest.raises(base.SourceNotConfigured, match='BrickLink key is not configured'):
        client.call('/colors')
    client.http.assert_not_called()


def test_brickset_alias_country_and_checks(db):
    response = json.loads((FIXTURES / 'brickset.json').read_text())
    http = Mock(return_value=response)
    client = Brickset(db, http=http)
    assert client.refresh(['123']) == ['123']
    params = parse_qs(http.call_args[0][0].data.decode())
    assert json.loads(params['params'][0]) == {'setNumber': '123-1', 'pageSize': 500}
    assert tuple(db.execute('SELECT item_no,source_id FROM id_match').fetchone()) == ('123', '123-1')
    assert tuple(db.execute('SELECT guide,price,currency,region FROM price_observations').fetchone()) == ('retail', '49.99', 'EUR', 'DE')
    assert db.execute("SELECT value FROM item_properties WHERE key='setID'").fetchone()[0] == '42'
    with db:
        db.execute("INSERT INTO settings VALUES('retail_country','US')")
    assert client.refresh(['123']) == ['123']
    assert db.execute('SELECT currency FROM price_observations ORDER BY id DESC').fetchone()[0] == 'USD'
    http.return_value = {'status': 'success', 'matches': 1, 'apiKeyUsage': []}
    client.check_key()
    client.key_usage_stats()
    assert client.status()['used_today'] == 2


def test_brickset_batching(db):
    requests = []
    def http(request):
        requests.append(json.loads(parse_qs(request.data.decode())['params'][0]))
        return {'status': 'success', 'matches': 0, 'sets': []}
    Brickset(db, http=http).refresh([f'{n}-1' for n in range(501)])
    assert [len(r['setNumber'].split(',')) for r in requests] == [500, 1]


def test_brickset_unmatched_and_remote_budget(db):
    response = json.loads((FIXTURES / 'brickset.json').read_text())
    client = Brickset(db, http=lambda _: response)
    assert client.refresh(['999-1']) == []
    assert db.execute('SELECT status FROM id_match').fetchone()[0] == 'unmatched'
    assert db.execute('SELECT count(*) FROM items').fetchone()[0] == 0
    client.http = lambda _: {'status': 'error', 'message': 'API limit exceeded'}
    with pytest.raises(base.WaitingForBudget):
        client.refresh(['999-1'])
    assert db.execute('SELECT state FROM jobs ORDER BY id DESC').fetchone()[0] == 'waiting_for_budget'


def test_raw_credentials_redacted(db):
    secret = 'secret-BW_BRICKSET_API_KEY'
    client = Brickset(db, http=lambda _: {'status': 'error', 'message': secret})
    with pytest.raises(base.SourceError) as error:
        client.check_key()
    assert secret not in str(error.value)
    assert secret not in db.execute('SELECT payload FROM source_records').fetchone()[0]


def test_remote_budget_blocks_calls_and_resumes_next_day(db, monkeypatch):
    clock = [datetime(2026, 10, 12, tzinfo=timezone.utc)]
    monkeypatch.setattr(base, 'now', lambda: clock[0])
    http = Mock(return_value={'status': 'error', 'message': 'API limit exceeded'})
    client = Brickset(db, http=http)
    with pytest.raises(base.WaitingForBudget) as first:
        client.refresh(['123-1'])
    with pytest.raises(base.WaitingForBudget):
        client.refresh(['456-1'])
    assert http.call_count == 1
    assert client.status()['used_today'] == 1
    clock[0] = datetime(2026, 10, 13, tzinfo=timezone.utc)
    http.return_value = json.loads((FIXTURES / 'brickset.json').read_text())
    assert client.refresh(['123-1'], job_id=first.value.job_id) == ['123-1']
    assert client.status()['used_today'] == 1
    assert base.budget_used(db, 'brickset', '2026-10-12') == 1


def test_price_stock_budget_resume(db, monkeypatch):
    monkeypatch.setenv('BW_BRICKLINK_DAILY_BUDGET', '1')
    clock = [datetime(2026, 10, 12, tzinfo=timezone.utc)]
    monkeypatch.setattr(base, 'now', lambda: clock[0])
    client = BrickLink(db, http=lambda _: reply({'total_quantity': 0}))
    with pytest.raises(base.WaitingForBudget) as waiting:
        client.price('P', '3001', 4, 'N')
    clock[0] = datetime(2026, 10, 13, tzinfo=timezone.utc)
    client.http = Mock(return_value=reply({'total_quantity': 1, 'qty_avg_price': '0.25', 'min_price': '0.2', 'max_price': '0.3'}))
    assert client.price('P', '3001', 4, 'N', job_id=waiting.value.job_id)['guide'] == 'stock'
    assert 'guide_type=stock' in client.http.call_args[0][0].full_url
    assert client.status()['used_today'] == 1


def test_ip_mismatch_safe_and_raw_kept(db):
    client = BrickLink(db, http=lambda _: {'meta': {'code': 401, 'description': 'TOKEN_IP_MISMATCHED'}, 'data': None})
    with pytest.raises(base.SourceError, match='IP mismatch'):
        client.call('/colors')
    assert db.execute('SELECT count(*) FROM source_records').fetchone()[0] == 1


def test_budget_corruption_fails_closed(db):
    client = BrickLink(db, http=Mock(return_value=reply([])))
    with db:
        db.execute("INSERT INTO settings VALUES('source:used:bricklink:' || ?, 'broken')", (base.now().date().isoformat(),))
    with pytest.raises(ValueError):
        client.call('/colors')
    client.http.assert_not_called()


def test_worldwide_omits_region(db):
    with db:
        db.execute("INSERT INTO settings VALUES('bricklink_region','all')")
    client = BrickLink(db, http=Mock(return_value=reply({'total_quantity': 1, 'qty_avg_price': '1', 'min_price': '1', 'max_price': '1'})))
    client.price('S', '123-1')
    assert 'region=' not in client.http.call_args[0][0].full_url


def test_normalization_transaction_failure_keeps_original_rows(db):
    client = BrickLink(db, http=lambda _: reply([{'color_id': 4, 'color_name': 'Red', 'color_type': 'Solid'}]))
    client.sync_colors()
    client.http = lambda _: reply([{'color_id': 4, 'color_name': 'Changed', 'color_type': 'Solid'}, {'color_id': 5}])
    with pytest.raises(base.SourceError):
        client.sync_colors()
    assert db.execute('SELECT name FROM colors WHERE color_id=4').fetchone()[0] == 'Red'
    assert db.execute('SELECT count(*) FROM source_records').fetchone()[0] == 2


def test_extensible_source_without_schema_change(db):
    class AdditionalSource(base.Source):
        source = 'synthetic'
        daily_budget = 5
        freshness = {'identity': 7}
    client = AdditionalSource(db, http=lambda _: {'name': 'Additional'})
    client.request('identity', {'item': '123-1'}, Request('https://example.test/item'), lambda reply: base.item(db, 'S', '123-1', reply['name']))
    assert db.execute("SELECT name FROM items").fetchone()[0] == 'Additional'
    assert db.execute('SELECT version FROM schema_meta').fetchone()[0] == '3.3'


@pytest.mark.parametrize('raw', [None, {}, {'meta': {'code': 200}}, 'invalid JSON'])
def test_invalid_reply_retained(db, raw):
    client = BrickLink(db, http=lambda _: raw)
    with pytest.raises(base.SourceError):
        client.call('/colors')
    assert db.execute('SELECT status FROM source_records').fetchone()[0] == 'failed'
    assert client.status()['used_today'] == 1


def test_part_key_validation_and_inventory_filter(db):
    client = BrickLink(db, http=Mock())
    for number in (False, 123, 'bad/no'):
        with pytest.raises(ValueError):
            client.part_price('P', number, 4, 'N')
    client.http.assert_not_called()
    client.http = lambda _: reply([{'entries': [
        {'item': {'type': 'SET', 'no': '999-1'}, 'quantity': 1},
        {'item': {'type': 'PART', 'no': '3001'}, 'quantity': 2, 'color_id': 4}]}])
    assert client.subsets('MINIFIG', 'abc') == [dict(item_type='P', item_no='3001', color_id=4, quantity=2, extra_quantity=0)]


def test_source_preserves_explicit_user_agent(db):
    request = Request('https://brickset.com/api/v3.asmx/checkKey', headers={'User-Agent': 'custom-agent'})
    http = Mock(return_value={'status': 'success'})
    Brickset(db, http=http).request('checkKey', {}, request, lambda reply: reply, charged=False)
    assert http.call_args.args[0].get_header('User-agent') == 'custom-agent'


@pytest.mark.parametrize('retail', [{}, {'retailPrice': None}])
def test_brickset_documented_absent_retail_price(db, retail):
    # API v3 LEGOCom.DE is a LEGOComDetails object; retailPrice is nullable.
    response = json.loads((FIXTURES / 'brickset.json').read_text())
    row = response['sets'][0]
    row.update(number='6080', numberVariant=1, year=1984, LEGOCom={'DE': retail})
    assert Brickset(db, http=Mock(return_value=response)).refresh(['6080-1']) == ['6080-1']
    assert db.execute('SELECT count(*) FROM price_observations').fetchone()[0] == 0


def test_colour_codes_validated_atomically(db):
    rows = [dict(color_id=11,color_name='Blue',color_type='Solid',color_code='aBcDeF')]
    client = BrickLink(db, http=lambda _: reply(rows))
    assert client.sync_colors() == 1
    assert db.execute('SELECT rgb FROM colors WHERE color_id=11').fetchone()[0] == 'ABCDEF'
    for code in ['#ABCDEF','12345','GG0000',123456]:
        rows[:] = [dict(color_id=11,color_name='Changed',color_type='Solid',color_code='000000'),
                   dict(color_id=12,color_name='Bad',color_type='Solid',color_code=code)]
        with pytest.raises(base.ColourCodeError, match='Invalid BrickLink colour code'):
            client.sync_colors()
        assert tuple(db.execute('SELECT name,rgb FROM colors WHERE color_id=11').fetchone()) == ('Blue','ABCDEF')
        assert db.execute('SELECT 1 FROM colors WHERE color_id=12').fetchone() is None


def test_catalogue_loader_updates_held_names_with_provenance(db,tmp_path):
    with db:
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('P','123-1','Fallback')")
    catalogue.load(FIXTURES,tmp_path/'bricklink-catalog.db',db)
    assert db.execute("SELECT name FROM items WHERE item_type='P'").fetchone()[0]=='Test (P)'
    assert tuple(db.execute("SELECT value,source FROM item_properties WHERE key='name'").fetchone())==('Test (P)','bricklink')


def test_colour_load_one_request_and_bounded_reads(db):
    rows=[dict(color_id=i,color_name=f'Colour {i}',color_type='Solid',color_code='aBcDeF') for i in range(300)]
    http=Mock(return_value=reply(rows))
    queries=[]
    db.set_trace_callback(queries.append)
    try:
        assert BrickLink(db,http=http).sync_colors()==300
    finally:
        db.set_trace_callback(None)
    assert http.call_count==1
    assert len(queries)<5000
    assert len([q for q in queries if q.lstrip().upper().startswith('SELECT')])<20
    assert db.execute('SELECT count(*) FROM colors WHERE rgb=?',('ABCDEF',)).fetchone()[0]==300
