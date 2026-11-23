"""Rebrickable Lost Parts client calls for sending (#469 part A): parsed ids, POST and DELETE."""
import json
from urllib.parse import parse_qs, urlparse

import pytest

from brickwork.core.sources.base import KeyRejected, WaitingForBudget
from brickwork.core.sync import adapters
from tests.test_bw_sync import TOKEN, pair, rebrickable_ready, store  # noqa: F401
from tests.test_bw_sync_lost_parts import Remote, raw


class WriteRemote(Remote):
    """`Remote` plus POST `/lost_parts/` and DELETE `/lost_parts/<id>/`."""

    def __init__(self, lost=(), *, reply=None):
        super().__init__(lost)
        self.reply = reply
        self.writes = []

    def __call__(self, request):
        url = urlparse(request.full_url)
        if '/lost_parts/' in url.path and request.get_method() in ('POST', 'DELETE'):
            body = parse_qs(request.data.decode()) if request.data else {}
            self.writes.append((request.get_method(), url.path, body))
            if self.reply is not None:
                return self.reply
            return {'lost_part_id': 99, 'lost_quantity': int(body.get('lost_quantity', ['1'])[0])} if request.get_method() == 'POST' else ''
        return super().__call__(request)


def test_parse_lost_part_keeps_lost_part_id_and_inv_part_id():
    row = adapters.parse_lost_part(raw('1000-1', '3001', 4, 2, number=17))
    assert row['lost_part_id'] == 17 and row['inv_part_id'] == 17
    fallback = raw('1000-1', '3001', 4, 2, number=17)
    del fallback['inv_part']['inv_part_id']
    fallback['inv_part']['id'] = '42'
    parsed = adapters.parse_lost_part(fallback)
    assert parsed['lost_part_id'] == 17 and parsed['inv_part_id'] == 42
    without = raw('1000-1', '3001', 4, 2)
    without['lost_part_id'] = None
    without['inv_part']['inv_part_id'] = None
    without['inv_part']['id'] = None
    parsed_none = adapters.parse_lost_part(without)
    assert parsed_none is not None and parsed_none['lost_part_id'] is None and parsed_none['inv_part_id'] is None


def test_lost_parts_merges_ids_and_inv_part_id(store):
    rebrickable_ready(store)
    first = raw('1000-1', '3001', 4, 1, number=11)
    second = raw('1000-1', '3001', 4, 2, number=12)
    second['inv_part']['inv_part_id'] = 500
    first['inv_part']['inv_part_id'] = None
    first['inv_part']['id'] = None
    found = adapters.RebrickableUser(store, http=Remote([first, second])).lost_parts()
    assert len(found['rows']) == 1
    row = found['rows'][0]
    assert row['quantity'] == 3 and row['ids'] == [11, 12] and row['inv_part_id'] == 500


def test_lost_part_add_and_remove_record_templates_without_token(store):
    remote = rebrickable_ready(store, WriteRemote())
    client = adapters.RebrickableUser(store, http=remote)
    client.lost_part_add(501, 3)
    assert client.lost_part_remove(77) is True
    assert remote.writes == [
        ('POST', f'/api/v3/users/{TOKEN}/lost_parts/', {'inv_part_id': ['501'], 'lost_quantity': ['3']}),
        ('DELETE', f'/api/v3/users/{TOKEN}/lost_parts/77/', {}),
    ]
    records = [tuple(r) for r in store.execute('SELECT kind, key FROM source_record ORDER BY id')]
    assert ('user:post:/lost_parts/', json.dumps({'form': {'inv_part_id': 501, 'lost_quantity': 3}}, sort_keys=True)) in records
    assert ('user:delete:/lost_parts/N/', '{}') in records
    assert TOKEN not in json.dumps(records)


@pytest.mark.parametrize('kind,reply,expected', [
    ('add', {'detail': 'Request was throttled. Expected available in 45 seconds.'}, WaitingForBudget),
    ('remove', {'detail': 'Invalid token.'}, KeyRejected),
])
def test_throttled_and_rejected_replies_on_writes(store, kind, reply, expected):
    remote = rebrickable_ready(store, WriteRemote(reply=reply))
    client = adapters.RebrickableUser(store, http=remote)
    with pytest.raises(expected):
        if kind == 'add':
            client.lost_part_add(501, 1)
        else:
            client.lost_part_remove(77)
    assert len(remote.writes) == 1


def test_lost_parts_tracks_ids_complete_across_merged_rows(store):
    rebrickable_ready(store)
    complete = raw('1000-1', '3001', 4, 1, number=11)
    missing_id = raw('1000-1', '3001', 4, 2, number=12)
    missing_id['lost_part_id'] = None
    other = raw('1000-1', '3023', 15, 1, number=13)
    found = adapters.RebrickableUser(store, http=Remote([complete, missing_id, other])).lost_parts()
    by_part = {r['part_no']: r for r in found['rows']}
    assert by_part['3001']['ids'] == [11] and by_part['3001']['ids_complete'] is False
    assert by_part['3023']['ids'] == [13] and by_part['3023']['ids_complete'] is True


@pytest.mark.parametrize('kind,reply', [
    ('add', {'inv_part_id': ['Invalid pk']}),
    ('add', {'lost_part_id': '99'}),
    ('add', {}),
    ('remove', {'non_field_errors': ['nope']}),
    ('remove', []),
])
def test_lost_part_add_and_remove_reject_error_bodies(store, kind, reply):
    remote = rebrickable_ready(store, WriteRemote(reply=reply))
    client = adapters.RebrickableUser(store, http=remote)
    with pytest.raises(adapters.SourceError) as exc:
        if kind == 'add':
            client.lost_part_add(501, 1)
        else:
            client.lost_part_remove(77)
    if kind == 'add':
        assert str(exc.value) == 'Rebrickable refused the Lost Part'
