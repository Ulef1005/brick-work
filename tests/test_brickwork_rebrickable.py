"""Rebrickable normalized identity and safe transport behavior."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from brickwork.core.connect import connect
from brickwork.core.sources import base
from brickwork.core.sources.rebrickable import Rebrickable


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', 'synthetic-key')
    monkeypatch.setattr(base, 'transport', Mock(side_effect=AssertionError('network forbidden')))
    monkeypatch.setattr(base.time, 'sleep', lambda _: None)
    with closing(connect(tmp_path / 'brickwork.db')) as db:
        with db:
            base.item(db, 'P', 'canonical-p')
            base.item(db, 'M', 'canonical-m')
        yield db


def test_external_ids_and_colour_are_only_matches(db):
    http = Mock(return_value=dict(part_num='rb-p', external_ids={'BrickLink': ['canonical-p']}))
    client = Rebrickable(db, http=http)
    assert client.minimum_spacing == 1
    client.part('rb-p', canonical='canonical-p')
    assert http.call_args.args[0].get_header('Authorization') == 'key synthetic-key'
    assert 'synthetic-key' not in http.call_args.args[0].full_url
    http.return_value = dict(id=77, external_ids={'BrickLink': {'ext_ids': [4]}})
    client.color(77, canonical=4)
    http.return_value = dict(set_num='fig-rb', external_ids={'BrickLink': ['canonical-m']})
    client.minifigure('fig-rb', canonical='canonical-m')
    assert [tuple(r) for r in db.execute('SELECT kind,item_no,color_id FROM id_match ORDER BY kind')] == [
        ('color', None, 4), ('minifigure', 'canonical-m', None), ('part', 'canonical-p', None)]
    assert [r[0] for r in db.execute('SELECT color_id FROM colors')] == [4]
    assert db.execute('SELECT count(*) FROM items').fetchone()[0] == 2


def test_ambiguity_retained_without_canonical_claim(db):
    client = Rebrickable(db, http=lambda _: dict(part_num='rb-other', external_ids={'BrickLink': ['canonical-p', 'other']}))
    client.part('rb-other', canonical='canonical-p')
    row = db.execute('SELECT * FROM id_match').fetchone()
    assert row['status'] == 'unmatched' and row['item_no'] is None
    assert 'other' in row['evidence_json']
    assert db.execute('SELECT count(*) FROM source_records').fetchone()[0] == 1


def test_manual_match_preserved(db):
    client = Rebrickable(db, http=lambda _: dict(part_num='rb-p', external_ids={}))
    with db:
        client.register()
        db.execute("INSERT INTO id_match(source,kind,source_id,item_type,item_no,status,evidence_json) VALUES('rebrickable','part','rb-p','P','canonical-p','manual','[]')")
    client.part('rb-p', canonical='canonical-p')
    assert db.execute('SELECT status FROM id_match').fetchone()[0] == 'manual'


def test_budget_and_remote_throttle_resume(db, monkeypatch):
    monkeypatch.setenv('BW_REBRICKABLE_DAILY_BUDGET', '1')
    clock = [datetime(2026, 10, 12, tzinfo=timezone.utc)]
    monkeypatch.setattr(base, 'now', lambda: clock[0])
    client = Rebrickable(db, http=Mock(return_value={'detail': 'Request was throttled. Expected available in 2 seconds.'}))
    with pytest.raises(base.WaitingForBudget) as waiting:
        client.call('/parts/rb-p/')
    with pytest.raises(base.WaitingForBudget):
        client.call('/parts/rb-p/')
    assert client.http.call_count == 1
    clock[0] += timedelta(days=1)
    client.http.return_value = dict(part_num='rb-p')
    client.call('/parts/rb-p/', job_id=waiting.value.job_id)
    assert client.status()['used_today'] == 1


def test_keys_and_raw_errors(db, monkeypatch):
    client = Rebrickable(db, http=Mock(return_value={'detail': 'synthetic-key invalid'}))
    with pytest.raises(base.SourceError):
        client.call('/parts/rb-p/')
    assert 'synthetic-key' not in db.execute('SELECT payload FROM source_records').fetchone()[0]
    monkeypatch.delenv('BW_REBRICKABLE_API_KEY')
    with pytest.raises(base.SourceNotConfigured, match='Rebrickable key is not configured'):
        client.call('/parts/rb-p/')
    assert client.http.call_count == 1


@pytest.mark.parametrize('budget', ['0', '-1', 'abc', '1.5'])
def test_invalid_budget(db, monkeypatch, budget):
    monkeypatch.setenv('BW_REBRICKABLE_DAILY_BUDGET', budget)
    with pytest.raises(base.SourceError):
        Rebrickable(db)


def test_throttle_short_wait_honored_across_clients(db, monkeypatch):
    clock = [datetime(2026, 10, 12, tzinfo=timezone.utc)]
    monkeypatch.setattr(base, 'now', lambda: clock[0])
    client = Rebrickable(db, http=Mock(return_value={'detail': 'Request was throttled. Expected available in 2 seconds.'}))
    with pytest.raises(base.WaitingForBudget) as waiting:
        client.call('/parts/rb-p/')
    assert db.execute('SELECT retry_at FROM jobs WHERE id=?', (waiting.value.job_id,)).fetchone()[0] == (clock[0] + timedelta(seconds=2)).isoformat()
    next_client = Rebrickable(db, http=Mock(return_value=dict(part_num='rb-p')))
    with pytest.raises(base.WaitingForBudget):
        next_client.call('/parts/rb-p/', job_id=waiting.value.job_id)
    next_client.http.assert_not_called()
    clock[0] += timedelta(seconds=2)
    next_client.call('/parts/rb-p/', job_id=waiting.value.job_id)
    assert next_client.status()['used_today'] == 2
