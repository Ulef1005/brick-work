"""#521 slice A: BrickLink orders sync run (choices, filtering, picking, preview rows, apply, audit and Undo). Invented data, no network."""
from contextlib import closing
import json
import sqlite3

import pytest

from brickwork.core import errors, orders, price_settings, sync
from brickwork.core.connect import connect
from brickwork.core.sources.base import SourceError
from brickwork.core.sync import bricklink_run, run as sync_run
from tests.api2 import app4, coll, pair, world  # noqa: F401

RED = 5


def db_of(pair):
    return closing(connect(pair))


def _header(order_id, status='RECEIVED', date_ordered='2026-11-17T10:00:00.000Z', unique_count=14, total='38.20', currency='EUR'):
    header = dict(status=status, date_ordered=date_ordered, unique_count=unique_count, store_name='Synthetic store', seller_name='synthetic')
    if order_id is not None:
        header['order_id'] = order_id
    if total is not None or currency is not None:
        header['cost'] = {k: v for k, v in (('grand_total', total), ('currency_code', currency)) if v is not None}
    return header


def _items(qty=3, price='0.12', remarks=''):
    return [dict(item=dict(no='3001', type='PART', name='Synthetic brick'), color_id=RED, new_or_used='U', quantity=qty, unit_price=price, remarks=remarks)]


class FakeBrickLink:
    def __init__(self, headers=None, items_by_order=None, *, fail=None, status_info=None):
        self.headers = list(headers or ())
        self.items_by_order = {str(k): v for k, v in (items_by_order or {}).items()}
        self.fail = {str(k): v for k, v in (fail or {}).items()}
        self.status_info = status_info if status_info is not None else dict(used_today=7, budget=4400, last_success='2026-11-24T10:00:00+00:00', key_state='set')
        self.list_calls = 0
        self.item_calls = []

    def list_orders(self, filed=False):
        self.list_calls += 1
        return list(self.headers)

    def order_items(self, order_id):
        key = str(order_id)
        self.item_calls.append(key)
        if key in self.fail:
            raise self.fail[key]
        return list(self.items_by_order[key])

    def status(self):
        if isinstance(self.status_info, Exception):
            raise self.status_info
        return dict(self.status_info)


def test_choices_defaults_round_trip_and_rejects(pair, monkeypatch):
    monkeypatch.setenv('BW_PRICE_SETTINGS_LOCK', '0')
    with db_of(pair) as db:
        assert bricklink_run.choices(db) == dict(orders='into', since_on=False, since=None, status='received_paid')
        db.execute("INSERT OR REPLACE INTO main.setting(key, value) VALUES(?, ?)", (bricklink_run.CHOICES_KEY, '{"orders":"bogus","status":"x","since_on":"yes","since":"bad"}'))
        db.commit()
        assert bricklink_run.choices(db) == dict(orders='into', since_on=False, since=None, status='received_paid')
        saved = bricklink_run.save_choices(db, dict(orders_dir='into', since_on='1', since='2026-10-01', status='all', region='europe'))
        assert saved == dict(orders='into', since_on=True, since='2026-10-01', status='all')
        assert bricklink_run.choices(db) == saved
        assert price_settings.read(db)['bricklink_region'] == 'europe'
        row = db.execute("SELECT 1 FROM main.event WHERE entity_kind='sync' AND entity_id='bricklink' AND field='choices'").fetchone()
        assert row is not None
        for bad in (dict(orders_dir='into', since_on='1', since='2026-02-30', status='all', region='eu'),
                    dict(orders_dir='into', since_on='', since='not-a-date', status='all', region='eu'),
                    dict(orders_dir='into', since_on='1', since='', status='all', region='eu'),
                    dict(orders_dir='into', since_on='', since='', status='shipped_only', region='eu'),
                    dict(orders_dir='both', since_on='', since='', status='all', region='eu'),
                    dict(orders_dir='into', since_on='', since='', status='all', region='mars')):
            with pytest.raises(errors.ValidationFailed):
                bricklink_run.save_choices(db, bad)
        assert bricklink_run.choices(db) == saved
        assert price_settings.read(db)['bricklink_region'] == 'europe'


def test_what_syncs_and_budget(pair):
    with db_of(pair) as db:
        assert bricklink_run.what_syncs(db) == [
            dict(what='Orders', direction='Into Brick Work', linked='Pulled into Orders'),
            dict(what='Price guide', direction='Into Brick Work', linked='Used for prices and Complete sets'),
            dict(what='Wanted lists', direction='By file', linked='The page builds the XML; BrickLink has no wanted-list API'),
        ]
        bricklink_run.save_choices(db, dict(orders_dir='off', since_on='', since='', status='received_paid', region='eu'))
        assert [r['what'] for r in bricklink_run.what_syncs(db)] == ['Price guide', 'Wanted lists']
        assert bricklink_run.budget(db, client=FakeBrickLink()) == dict(used=7, budget=4400, last_success='2026-11-24T10:00:00+00:00', key='set')
        assert bricklink_run.budget(db, client=FakeBrickLink(status_info=SourceError('down'))) is None


def test_start_filters_by_status_and_since_marks_imported_and_refuses_when_off(pair, world):
    headers = [
        _header(1002, status='PAID', date_ordered='2026-11-05T09:00:00.000Z', unique_count=2, total='9.50'),
        _header(1001, status='RECEIVED', date_ordered='2026-11-17T10:00:00.000Z', unique_count=14, total='38.20'),
        _header(1003, status='PENDING', date_ordered='2026-11-20T12:00:00.000Z', unique_count=1, total='4.00'),
        _header(None, status='RECEIVED', date_ordered='2026-11-18T12:00:00.000Z'),
    ]
    fake = FakeBrickLink(headers, {'1001': _items(qty=3)})
    with db_of(pair) as db:
        prepared = orders.api_data(db, '1001', client=fake, headers=headers[:3])
        assert fake.list_calls == 0
        orders.import_document(db, 'api', number='1001', prepared=prepared)
        before = db.execute('SELECT count(*) FROM main.purchase_order').fetchone()[0]
        run = bricklink_run.start(db, client=fake)
        assert db.execute('SELECT count(*) FROM main.purchase_order').fetchone()[0] == before
        assert [c['id'] for c in run['candidates']] == ['1001', '1002']
        assert run['candidates'][0] == dict(id='1001', label='Order 1001', date='2026-11-17', status='RECEIVED', lots=14, total='38.20', currency='EUR', imported=True)
        assert run['candidates'][1]['imported'] is False and len(run['headers']) == 2
        bricklink_run.save_choices(db, dict(orders_dir='into', since_on='1', since='2026-11-10', status='all', region='eu'))
        filtered = bricklink_run.start(db, client=fake)
        assert [c['id'] for c in filtered['candidates']] == ['1003', '1001']
        bricklink_run.save_choices(db, dict(orders_dir='off', since_on='', since='', status='received_paid', region='eu'))
        calls = fake.list_calls
        with pytest.raises(errors.ValidationFailed, match='Orders are switched off'):
            bricklink_run.start(db, client=fake)
        assert fake.list_calls == calls


def test_save_pick_and_rows_states(pair, world):
    headers = [
        _header(1001, status='RECEIVED', date_ordered='2026-11-17T10:00:00.000Z', unique_count=14, total='38.20', currency='EUR'),
        _header(1002, status='PAID', date_ordered='2026-11-05T09:00:00.000Z', unique_count=0, total=None, currency=None),
    ]
    fake = FakeBrickLink(headers, {'1001': _items(qty=3)})
    with db_of(pair) as db:
        orders.import_document(db, 'api', number='1001', prepared=orders.api_data(db, '1001', client=fake, headers=headers))
        run = bricklink_run.start(db, client=fake)
        all_rows = bricklink_run.rows(db, run)
        assert [r['key'] for r in all_rows] == ['order:1001', 'order:1002']
        assert all_rows[0] == dict(key='order:1001', id='1001', label='Order 1001', detail='Received 17 Nov · 14 lots · 38.20 EUR', state='same', options=[], default=None)
        assert all_rows[1] == dict(key='order:1002', id='1002', label='Order 1002', detail='Paid 5 Nov', state='new',
                                   options=[dict(id='pull', label='Pull in', note=None)], default='pull')
        with pytest.raises(errors.ValidationFailed, match='Pick orders from the list'):
            bricklink_run.save_pick(db, run['id'], {'9999'})
        picked = bricklink_run.save_pick(db, run['id'], {'1002'})
        assert picked['picked'] == ['1002']
        assert [r['id'] for r in bricklink_run.rows(db, picked)] == ['1002']


def test_apply_imports_ticked_orders_audits_undoes_and_is_idempotent(pair, world):
    headers = [
        _header(1001, date_ordered='2026-11-17T10:00:00.000Z'),
        _header(1002, date_ordered='2026-11-16T10:00:00.000Z'),
        _header(1003, date_ordered='2026-11-15T10:00:00.000Z'),
    ]
    fake = FakeBrickLink(headers, {'1001': _items(qty=3), '1002': _items(qty=5), '1003': _items(qty=2)})
    with db_of(pair) as db:
        run = bricklink_run.start(db, client=fake)
        assert fake.list_calls == 1
        form = {'order:1001': 'pull', 'order:1002': 'pull'}
        applied = bricklink_run.apply(db, run['id'], form, client=fake, via='app', actor='tester')
        assert fake.list_calls == 1
        assert applied['applied'] is True
        assert set(applied['stages']) == {'1001', '1002'}
        for oid in ('1001', '1002'):
            stage = applied['stages'][oid]
            assert stage['status'] == 'done' and stage['placed'] == 1 and stage['unplaced'] == 0 and stage['event'] is not None
        imported_ids = {r[0] for r in db.execute('SELECT bricklink_order_id FROM main.purchase_order')}
        assert imported_ids == {'1001', '1002'}
        audit_row = db.execute("SELECT new_value, via, actor FROM main.event WHERE entity_kind='sync' AND entity_id='bricklink' AND field='run' ORDER BY id DESC LIMIT 1").fetchone()
        assert audit_row is not None and audit_row['via'] == 'app'
        expected_events = [applied['stages']['1001']['event'], applied['stages']['1002']['event']]
        assert json.loads(audit_row['new_value']) == dict(run=run['id'], events=expected_events)
        event_count = db.execute('SELECT count(*) FROM main.event').fetchone()[0]
        item_calls = list(fake.item_calls)
        again = bricklink_run.apply(db, run['id'], form, client=fake)
        assert again == applied and fake.item_calls == item_calls
        assert db.execute('SELECT count(*) FROM main.event').fetchone()[0] == event_count
        undone = sync_run.undo_run(db, expected_events[0])
        assert undone == expected_events
        phases = [r[0] for r in db.execute('SELECT phase FROM main.order_document ORDER BY id')]
        assert phases == ['undone', 'undone']


def test_apply_continues_when_one_order_fails(pair, world):
    headers = [
        _header(1001, date_ordered='2026-11-17T10:00:00.000Z'),
        _header(1002, date_ordered='2026-11-16T10:00:00.000Z'),
    ]
    fake = FakeBrickLink(headers, {'1002': _items(qty=4)}, fail={'1001': SourceError('BrickLink unavailable')})
    with db_of(pair) as db:
        run = bricklink_run.start(db, client=fake)
        applied = bricklink_run.apply(db, run['id'], {'order:1001': 'pull', 'order:1002': 'pull'}, client=fake)
        assert applied['applied'] is True
        assert applied['stages']['1001'] == dict(status='failed', message='BrickLink unavailable')
        assert applied['stages']['1002']['status'] == 'done'
        assert [r[0] for r in db.execute('SELECT bricklink_order_id FROM main.purchase_order')] == ['1002']
        audit_row = db.execute("SELECT new_value FROM main.event WHERE entity_kind='sync' AND entity_id='bricklink' AND field='run' ORDER BY id DESC LIMIT 1").fetchone()
        assert json.loads(audit_row['new_value']) == dict(run=run['id'], events=[applied['stages']['1002']['event']])


def test_load_refuses_run_of_another_source(pair):
    with db_of(pair) as db:
        other = sync._save_plan(db, dict(id='a' * 32, created_at='2026-11-24T12:00:00+00:00', direction='run', source='rebrickable',
                                         candidates=[], picked=None, stages={}))
        with pytest.raises(errors.ValidationFailed):
            bricklink_run.load(db, other['id'])


def test_save_choices_locked_region_behaviour(pair, monkeypatch):
    monkeypatch.delenv('BW_PRICE_SETTINGS_LOCK', raising=False)
    with db_of(pair) as db:
        initial_region = price_settings.read(db)['bricklink_region']
        other_region = next(r for r in price_settings.REGIONS if r != initial_region)
        saved = bricklink_run.save_choices(db, dict(orders_dir='into', since_on='1', since='2026-10-01', status='all', region=initial_region))
        assert saved == dict(orders='into', since_on=True, since='2026-10-01', status='all')
        with pytest.raises(errors.ValidationFailed, match='The price region is locked on this install'):
            bricklink_run.save_choices(db, dict(orders_dir='off', since_on='', since='', status='received_paid', region=other_region))
        assert bricklink_run.choices(db) == saved
        assert price_settings.read(db)['bricklink_region'] == initial_region


def test_apply_takes_run_claim_and_second_apply_is_noop(pair, world, monkeypatch):
    headers = [_header(1001, date_ordered='2026-11-17T10:00:00.000Z')]
    fake = FakeBrickLink(headers, {'1001': _items(qty=3)})
    claims = []
    active = []
    seen_active = []

    class RecordingClaim:
        def __init__(self, db, run_id):
            self.run_id = run_id

        def __enter__(self):
            claims.append(('enter', self.run_id))
            active.append(self.run_id)
            return self

        def __exit__(self, *exc):
            active.pop()
            claims.append(('exit', self.run_id))

    real_import = orders.import_document

    def wrapped_import(*args, **kwargs):
        seen_active.append(list(active))
        return real_import(*args, **kwargs)

    monkeypatch.setattr(sync_run, '_Claim', RecordingClaim)
    monkeypatch.setattr(orders, 'import_document', wrapped_import)
    with db_of(pair) as db:
        run = bricklink_run.start(db, client=fake)
        first = bricklink_run.apply(db, run['id'], {'order:1001': 'pull'}, client=fake)
        assert first['applied'] is True
        assert claims == [('enter', run['id']), ('exit', run['id'])]
        assert seen_active == [[run['id']]]
        event_count = db.execute('SELECT count(*) FROM main.event').fetchone()[0]
        item_calls = list(fake.item_calls)
        second = bricklink_run.apply(db, run['id'], {'order:1001': 'pull'}, client=fake)
        assert second == first
        assert fake.item_calls == item_calls
        assert db.execute('SELECT count(*) FROM main.event').fetchone()[0] == event_count
        assert claims == [('enter', run['id']), ('exit', run['id']), ('enter', run['id']), ('exit', run['id'])]


def test_apply_propagates_sqlite_error_without_marking_stage_failed(pair, world, monkeypatch):
    headers = [_header(1001, date_ordered='2026-11-17T10:00:00.000Z')]
    fake = FakeBrickLink(headers, {'1001': _items(qty=3)})
    monkeypatch.setattr(orders, 'import_document', lambda *a, **kw: (_ for _ in ()).throw(sqlite3.OperationalError('database is locked')))
    with db_of(pair) as db:
        run = bricklink_run.start(db, client=fake)
        with pytest.raises(sqlite3.OperationalError, match='database is locked'):
            bricklink_run.apply(db, run['id'], {'order:1001': 'pull'}, client=fake)
        stored = bricklink_run.load(db, run['id'])
        assert '1001' not in stored['stages']
        assert not stored.get('applied')
