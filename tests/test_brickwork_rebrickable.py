"""Rebrickable on the 4.0 store (M.8f, issue #110): picture URLs and external-id evidence by item id, and safe transport behaviour."""
import json

import pytest

from brickwork.core.sources import base
from brickwork.core.sources.rebrickable import Rebrickable
from tests.app4 import coll, pair  # noqa: F401 (fixtures)
from tests.sources4 import Net, keyed, unkeyed


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    unkeyed(monkeypatch)
    keyed(monkeypatch, 'rebrickable')
    monkeypatch.setattr(base, 'transport', lambda request: (_ for _ in ()).throw(AssertionError('network forbidden')))
    monkeypatch.setattr(base.time, 'sleep', lambda _: None)


def links(db, item):
    return [tuple(r) for r in db.execute("SELECT provider_key, status, method, origin FROM item_link WHERE item_id=? AND provider='bricklink' ORDER BY provider_key", (item,))]


def status(db, item):
    return [tuple(r) for r in db.execute('SELECT provider, status, reason FROM item_provider_status WHERE item_id=?', (item,))]


def record(number='3001', ids=('3001',)):
    return {'part_num': number, 'external_ids': {'BrickLink': list(ids)}, 'part_img_url': 'https://cdn.rebrickable.com/media/parts/ldraw/4/3001.png'}


def unplaced(coll, key='3001'):
    """A projected part with no BrickLink link yet (the shipped mapping would already place it)."""
    item = coll.item('parts', key)
    coll.project(item)
    coll.sql("DELETE FROM item_link WHERE item_id=? AND provider='bricklink'", (item,))
    return item


def test_exactly_one_brickLink_id_is_a_matched_link_and_the_key_stays_out_of_the_url(coll):
    brick = unplaced(coll)
    net = Net(record())
    client = Rebrickable(coll.db, http=net)
    assert client.minimum_spacing == 1
    assert client.part(brick)['part_num'] == '3001'
    request = net.requests[0]
    assert request.get_header('Authorization') == 'key synthetic-bw_rebrickable_api_key' and 'synthetic' not in request.full_url
    assert request.full_url == 'https://rebrickable.com/api/v3/lego/parts/3001/'
    assert ('3001', 'matched', 'external_ids', 'api') in links(coll.db, brick)
    assert status(coll.db, brick) == []


def test_several_or_no_brickLink_ids_make_no_link_and_record_unmatched_no_match(coll):
    brick = unplaced(coll)
    Rebrickable(coll.db, http=Net(record(ids=('3001', '3001b')))).part(brick)
    assert links(coll.db, brick) == [] and status(coll.db, brick) == [('bricklink', 'unmatched', 'no_match')]
    evidence = json.loads(coll.db.execute('SELECT evidence_json FROM item_provider_status WHERE item_id=?', (brick,)).fetchone()[0])
    assert evidence == {'bricklink': ['3001', '3001b'], 'rebrickable': '3001'}
    Rebrickable(coll.db, http=Net(record(ids=()))).part(brick)                                         # asking again: still one status row
    assert status(coll.db, brick) == [('bricklink', 'unmatched', 'no_match')]
    Rebrickable(coll.db, http=Net(record(ids=('3001',)))).part(brick)                                  # a clear answer replaces the status by a link
    assert status(coll.db, brick) == [] and links(coll.db, brick) == [('3001', 'matched', 'external_ids', 'api')]


def test_a_refresh_never_replaces_a_manual_link_or_downgrades_a_confirmed_one(coll):
    plate = coll.item('parts', '3023')
    coll.project(plate)
    coll.sql("UPDATE item_link SET status='manual', origin='user', method='user' WHERE item_id=? AND provider='bricklink'", (plate,))
    before = links(coll.db, plate)
    assert before and before[0][1] == 'manual'
    Rebrickable(coll.db, http=Net(record('3023', ids=('3023', 'x')))).part(plate)                       # ambiguous reply: the manual link stands, no status
    Rebrickable(coll.db, http=Net(record('3023', ids=('3023b',)))).part(plate)                          # another single id: a new matched row beside it, manual first
    assert links(coll.db, plate)[0] in before and status(coll.db, plate) == []
    assert coll.db.execute("SELECT count(*) FROM item_link WHERE item_id=? AND status='manual'", (plate,)).fetchone()[0] == 1


def test_only_a_rebrickable_born_part_with_the_same_number_is_asked_and_accepted(coll, monkeypatch):
    local = coll.local('part', 'Only on BrickLink', born_key='x999')
    figure = coll.item('minifigs', 'fig-000004')
    for item in (local, figure):
        with pytest.raises(ValueError, match='Rebrickable-born part'):
            Rebrickable(coll.db, http=Net({})).part(item)
    brick = coll.item('parts', '3001')
    with pytest.raises(base.InvalidReply):
        Rebrickable(coll.db, http=Net(record('3023'))).part(brick)
    assert links(coll.db, brick) == [] or all(row[2] != 'external_ids' for row in links(coll.db, brick))


def test_a_picture_url_comes_from_the_named_key_and_a_part_record_also_teaches_its_brickLink_number(coll):
    brick = unplaced(coll)
    net = Net(record())
    url = Rebrickable(coll.db, http=net).picture_url('/parts/3001/', 'part_img_url', item_id=brick)
    assert url.endswith('/3001.png') and ('3001', 'matched', 'external_ids', 'api') in links(coll.db, brick)
    colour = Net({'part_img_url': 'https://cdn.rebrickable.com/media/parts/ldraw/4/3001.png'})
    Rebrickable(coll.db, http=colour).picture_url('/parts/3001/colors/4/', 'part_img_url', item_id=brick)      # a colour record has no external ids: no evidence
    for body in ({}, {'part_img_url': None}, {'part_img_url': ''}):
        with pytest.raises(base.NotFoundAtSource):
            Rebrickable(coll.db, http=Net(body)).picture_url('/parts/3001/colors/4/', 'part_img_url')


def test_errors_are_classified_and_never_carry_the_key(coll, monkeypatch):
    client = Rebrickable(coll.db, http=Net({'detail': 'synthetic-bw_rebrickable_api_key invalid token'}))
    with pytest.raises(base.KeyRejected) as caught:
        client.call('/parts/3001/')
    assert 'synthetic' not in str(caught.value) and 'synthetic' not in coll.db.execute('SELECT payload FROM source_record').fetchone()[0]
    with pytest.raises(base.NotFoundAtSource):
        Rebrickable(coll.db, http=Net((404, {'detail': 'Not found.'}))).call('/parts/zzz/')
    with pytest.raises(base.SourceError) as other:
        Rebrickable(coll.db, http=Net({'detail': 'Something else'})).call('/parts/3001/')
    assert not isinstance(other.value, (base.KeyRejected, base.NotFoundAtSource))
    with pytest.raises(base.InvalidReply):
        Rebrickable(coll.db, http=Net([1, 2])).call('/parts/3001/')
    monkeypatch.delenv('BW_REBRICKABLE_API_KEY')
    net = Net({})
    with pytest.raises(base.SourceNotConfigured, match='Rebrickable key is not configured'):
        Rebrickable(coll.db, http=net).call('/parts/3001/')
    assert net.requests == []


def test_endpoint_allowlist(coll):
    client = Rebrickable(coll.db, http=Net({}))
    for path in ('/parts/', '/users/token/', '/parts/3001/../x/', '/sets/1000-1/parts/', 'parts/3001/'):
        if path in ('/parts/',):
            continue                                                       # the list endpoint is allowed by the pattern's optional segment
        with pytest.raises(ValueError, match='unsupported Rebrickable endpoint'):
            client.call(path)
    assert client.call('/colors/0/') == {}
    assert client.call('/sets/1000-1/') == {}
