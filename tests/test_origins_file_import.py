"""Provenance (`added_via`) for Add file imports, paste/search adds, and wishlist copy transfers."""
import io
import json
import uuid

import pytest

from brickwork.core import add, wishlists
from brickwork.core.sources.base import audit_origin
from brickwork.core.transaction import transaction
from brickwork.store4.connect import now
from brickwork.store4.errors import Store4Error
from brickwork.web import views
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401

BL_SET_XML = b'<INVENTORY><ITEM><ITEMTYPE>S</ITEMTYPE><ITEMID>1000-1</ITEMID><MINQTY>1</MINQTY></ITEM></INVENTORY>'
BL_PART_XML = b'<INVENTORY><ITEM><ITEMTYPE>P</ITEMTYPE><ITEMID>3001</ITEMID><COLOR>5</COLOR><MINQTY>2</MINQTY></ITEM></INVENTORY>'
RB_SET_CSV = b'set_num,quantity\n1000-1,1\n'
RB_PART_CSV = b'part_num,color_id,quantity\n3023,15,4\n'
RB_FIG_CSV = b'minifig_num,quantity\nfig-000004,2\n'
BS_SET_OWNED_CSV = b'SetID,Number,Variant,Own,QtyOwned,QtyOwnedNew,QtyOwnedUsed,Want,QtyWanted\n1,1000,1,X,1,1,0,,0\n'
BS_SET_WANT_CSV = b'SetID,Number,Variant,Own,QtyOwned,QtyOwnedNew,QtyOwnedUsed,Want,QtyWanted\n1,1000,1,,0,0,0,X,1\n'
BS_FIG_CSV = b'MinifigNumber,Own,QtyOwned,QtyOwnedLoose,Want\nsyn0001,X,2,2,\n'


@pytest.fixture
def csrf(client):
    assert client.get('/manage/add').status_code == 200
    with client.session_transaction() as session:
        return session['bw_add_csrf']


def _review_and_confirm(client, csrf, review_response):
    assert review_response.status_code == 200, review_response.get_json()
    body = review_response.get_json()
    assert len(body['items']) == 1, body
    items = json.loads(json.dumps(body['items']))
    for item in items:
        item['decision'] = 'another'
    confirm = client.post(
        '/manage/add/confirm',
        json={'csrf_token': csrf, 'token': body['token'], 'items': items},
    )
    assert confirm.status_code == 200, confirm.get_json()
    return body, confirm.get_json()


@pytest.mark.parametrize('data,filename,expected', [
    (BL_SET_XML, 'wanted.xml', 'bricklink_xml'),
    (b'<WANTEDLIST><ITEM><ITEMTYPE>S</ITEMTYPE><ITEMID>75192-1</ITEMID></ITEM></WANTEDLIST>', 'LIST.XML', 'bricklink_xml'),
    (b'\xef\xbb\xbf' + RB_SET_CSV, 'sets.csv', 'rebrickable_csv'),
    (b'Part,Color,Quantity\n3001,0,4\n', 'parts.csv', 'rebrickable_csv'),
    (b'Set Number,Quantity\n75192-1,1\n', 'sets.csv', 'rebrickable_csv'),
    (RB_FIG_CSV, 'figs.csv', 'rebrickable_csv'),
    (BS_SET_OWNED_CSV, 'mysets.csv', 'brickset_csv'),
    (BS_FIG_CSV, 'minifigs.csv', 'brickset_csv'),
    (b'<OTHER/>', 'other.xml', None),
    (b'<!DOCTYPE foo><INVENTORY/>', 'dtd.xml', None),
    (b'<INVENTORY', 'broken.xml', None),
    (b'foo,bar\n1,2\n', 'unknown.csv', None),
    (b'75192-1\n', 'list.txt', None),
    (b'\xff\xfe', 'bad.csv', None),
])
def test_file_origin_detection(data, filename, expected):
    assert add.file_origin(data, filename) == expected


@pytest.mark.parametrize('expected_origin,filename,owned_data,loose_kind,loose_data,wish_data', [
    ('bricklink_xml', 'wanted.xml', BL_SET_XML, 'part', BL_PART_XML, BL_SET_XML),
    ('rebrickable_csv', 'import.csv', RB_SET_CSV, 'part', RB_PART_CSV, RB_SET_CSV),
    ('brickset_csv', 'brickset.csv', BS_SET_OWNED_CSV, 'minifigure', BS_FIG_CSV, BS_SET_WANT_CSV),
])
def test_file_import_sets_origin_on_copy_stock_and_wish(
    app4, client, csrf, coll, read, expected_origin, filename, owned_data, loose_kind, loose_data, wish_data,
):
    coll.link(coll.item('minifigs', 'fig-000004'), 'syn0001', kind='M')

    for kind, where, payload in (
        ('set', 'owned', owned_data),
        (loose_kind, 'loose', loose_data),
        ('set', 'wishlist', wish_data),
    ):
        resp = client.post(
            '/manage/add/review',
            data={
                'csrf_token': csrf,
                'mode': 'file',
                'type': kind,
                'where': where,
                'list_id': 'default',
                'file': (io.BytesIO(payload), filename),
            },
            content_type='multipart/form-data',
        )
        review, confirmed = _review_and_confirm(client, csrf, resp)
        with app4.app_context():
            decoded = views.bw_add_signer().loads(review['token'])
        assert decoded['origin'] == expected_origin
        receipt = confirmed['receipts'][0]
        with read() as db:
            if where == 'owned':
                row = db.execute('SELECT added_via FROM main.copy WHERE id=?', (receipt['copies'][0],)).fetchone()
            elif where == 'loose':
                row = db.execute('SELECT added_via FROM main.stock WHERE id=?', (receipt['stock'],)).fetchone()
            else:
                row = db.execute('SELECT added_via FROM main.wish WHERE id=?', (receipt['wish'],)).fetchone()
            assert row['added_via'] == expected_origin


@pytest.mark.parametrize('mode', ['paste', 'search'])
def test_paste_and_search_keep_hand_origin(app4, client, csrf, coll, read, mode):
    set_id = coll.item('sets', '1000-1')
    fig_id = coll.item('minifigs', 'fig-000004')

    cases = (
        ('set', 'owned', '1000-1', set_id),
        ('minifigure', 'loose', 'fig-000004', fig_id),
        ('set', 'wishlist', '1000-1', set_id),
    )
    for kind, where, text, item_id in cases:
        payload = {'csrf_token': csrf, 'mode': mode, 'type': kind, 'where': where}
        if mode == 'paste':
            payload['text'] = text
        else:
            payload['items'] = [{'item_id': item_id, 'quantity': 1}]
        review, confirmed = _review_and_confirm(client, csrf, client.post('/manage/add/review', json=payload))
        with app4.app_context():
            decoded = views.bw_add_signer().loads(review['token'])
        assert 'origin' not in decoded
        receipt = confirmed['receipts'][0]
        with read() as db:
            if where == 'owned':
                row = db.execute('SELECT added_via FROM main.copy WHERE id=?', (receipt['copies'][0],)).fetchone()
            elif where == 'loose':
                row = db.execute('SELECT added_via FROM main.stock WHERE id=?', (receipt['stock'],)).fetchone()
            else:
                row = db.execute('SELECT added_via FROM main.wish WHERE id=?', (receipt['wish'],)).fetchone()
            assert row['added_via'] == 'hand'


def test_tampered_token_and_unknown_origin_refused(client, csrf, coll, read):
    set_id = coll.item('sets', '1000-1')

    resp = client.post(
        '/manage/add/review',
        data={
            'csrf_token': csrf,
            'mode': 'file',
            'type': 'set',
            'where': 'owned',
            'file': (io.BytesIO(BL_SET_XML), 'wanted.xml'),
        },
        content_type='multipart/form-data',
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    bad = client.post(
        '/manage/add/confirm',
        json={'csrf_token': csrf, 'token': body['token'] + 'tampered', 'items': body['items']},
    )
    assert bad.status_code == 400
    with read() as db:
        assert db.execute('SELECT count(*) FROM main.copy').fetchone()[0] == 0
    with pytest.raises(Store4Error, match='unknown origin'):
        add.confirm(
            coll.db,
            [{'item_id': set_id, 'kind': 'set', 'where': 'owned', 'quantity': 1, 'color_id': None,
              'condition': 'used', 'completeness': '', 'decision': ''}],
            batch=uuid.uuid4().hex,
            origin='not_a_real_origin',
        )
    with read() as db:
        assert db.execute('SELECT count(*) FROM main.copy').fetchone()[0] == 0


def test_transfer_copy_sets_current_origin_and_preserves_source(coll):
    db = coll.db
    with audit_origin('app'):
        source_list, _ = wishlists.save(db, data={'name': 'Source'})
        target_list, _ = wishlists.save(db, data={'name': 'Target'})
        stamp = now()
        for set_key, source_origin in zip(('1000-1', '1000-2', '2070-1'), (None, 'rebrickable', 'hand')):
            item_id = coll.project(coll.item('sets', set_key))
            wish_id = uuid.uuid4().hex
            with transaction(db):
                db.execute(
                    '''INSERT INTO main.wish(id, wishlist_id, kind, item_id, color_id, quantity, condition,
                       max_price, max_price_currency, qty_filled_manual, note, added_at, updated_at, added_via)
                       VALUES(?, ?, 'set', ?, NULL, 1, 'any', NULL, NULL, NULL, NULL, ?, ?, ?)''',
                    (wish_id, source_list, item_id, stamp, stamp, source_origin),
                )
            wishlists.transfer(db, [wish_id], target_list, copy=True)
            original = db.execute('SELECT added_via FROM main.wish WHERE id=?', (wish_id,)).fetchone()
            copied = db.execute(
                'SELECT added_via FROM main.wish WHERE wishlist_id=? AND item_id=? AND archived_at IS NULL',
                (target_list, item_id),
            ).fetchone()
            assert original['added_via'] == source_origin
            assert copied['added_via'] == 'hand'


def test_file_import_fetch_keeps_file_origin_when_settled(client, csrf, coll, read, monkeypatch):
    from brickwork.store4 import jobs

    monkeypatch.setattr(jobs, '_configured', lambda *a, **kw: True)
    unknown_xml = b'<INVENTORY><ITEM><ITEMTYPE>S</ITEMTYPE><ITEMID>99999-1</ITEMID><MINQTY>1</MINQTY></ITEM></INVENTORY>'
    resp = client.post(
        '/manage/add/review',
        data={
            'csrf_token': csrf,
            'mode': 'file',
            'type': 'set',
            'where': 'owned',
            'list_id': 'default',
            'file': (io.BytesIO(unknown_xml), 'wanted.xml'),
        },
        content_type='multipart/form-data',
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert len(body['items']) == 1 and body['items'][0]['unknown'] is True
    assert body['items'][0]['offers']['fetch']['available'] is True
    items = json.loads(json.dumps(body['items']))
    items[0]['decision'] = 'fetch'
    confirm = client.post(
        '/manage/add/confirm',
        json={'csrf_token': csrf, 'token': body['token'], 'items': items},
    )
    assert confirm.status_code == 200, confirm.get_json()
    with read() as db:
        assert db.execute('SELECT count(*) FROM main.copy').fetchone()[0] == 0
        event = db.execute("SELECT new_value FROM main.event WHERE entity_kind='add' AND field='receipt' ORDER BY id DESC LIMIT 1").fetchone()
    receipt = json.loads(event['new_value'])
    assert receipt['ask']['origin'] == 'bricklink_xml'
    assert receipt['fetch_job'] is not None
    fetched_set = coll.project(coll.item('sets', '1000-1'))
    with transaction(coll.db):
        coll.db.execute("UPDATE main.job SET state='done', item_id=? WHERE id=?", (fetched_set, receipt['fetch_job']))
    assert add.settle_fetches(coll.db) == 1
    with read() as db:
        rows = db.execute('SELECT added_via FROM main.copy WHERE item_id=? AND archived_at IS NULL', (fetched_set,)).fetchall()
    assert [r['added_via'] for r in rows] == ['bricklink_xml']

    other_set = coll.project(coll.item('sets', '1000-2'))
    with transaction(coll.db):
        made = add._create_fetched(
            coll.db,
            {'id': 0},
            {'batch': uuid.uuid4().hex, 'index': 0, 'fetch_job': receipt['fetch_job'],
             'ask': {'where': 'owned', 'quantity': 1, 'condition': 'used', 'completeness': '', 'origin': 'not_a_real_origin'}},
            other_set,
            'app',
            None,
        )
    with read() as db:
        assert db.execute('SELECT added_via FROM main.copy WHERE id=?', (made[0],)).fetchone()['added_via'] == 'hand'
