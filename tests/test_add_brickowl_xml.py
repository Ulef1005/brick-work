"""Brick Owl inventory XML backup import (#36): parsing, origin detection and confirm provenance."""
import io

import pytest

from brickwork.core import add
from brickwork.web import views
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401
from tests.test_origins_file_import import _review_and_confirm, csrf  # noqa: F401


def _lot(
    *,
    lot_id='100001',
    item_id='200001',
    boid='300001',
    name='LEGO Castle Keep Set 1000',
    quantity='1',
    condition='newc',
    personal_note='',
):
    note = f'<personal_note>{personal_note}</personal_note>' if personal_note else '<personal_note/>'
    return (
        f'<lot><lot_id>{lot_id}</lot_id><brickowl_item_id>{item_id}</brickowl_item_id>'
        f'<boid>{boid}</boid><external_lot_id/><name>{name}</name><quantity>{quantity}</quantity>'
        f'<base_price>150.000</base_price><condition>{condition}</condition><tier_price/>'
        f'<bulk_qty>1</bulk_qty><sale_percent>0</sale_percent><for_sale>1</for_sale>'
        f'{note}<public_note/><my_weight/><weight>1765.000</weight><my_cost/><force_quote>0</force_quote></lot>'
    )


def _backup(*lots):
    return ('<?xml version="1.0"?><inventory>' + ''.join(lots) + '</inventory>').encode('utf-8')


def test_file_rows_reads_set_and_marks_non_set_unresolved():
    data = _backup(
        _lot(lot_id='100001', boid='300001', name='LEGO Castle Keep Set 1000', condition='newc'),
        _lot(lot_id='100002', boid='300002', name='LEGO Red Brick 2 x 4', condition='usedc'),
    )
    rows = add.file_rows(data, 'brickowl-inventory.xml', 'set')
    assert rows == [
        {
            'kind': 'set',
            'number': '1000-1',
            'quantity': 1,
            'condition': 'new',
            'note': None,
            'brickowl_boid': '300001',
        },
        {
            'unresolved': 'LEGO Red Brick 2 x 4',
            'reason': 'Brick Owl lot with no set number in its name',
        },
    ]
    # Non-set kind still returns the parsed rows so the caller reports the kind mismatch.
    assert add.file_rows(data, 'brickowl-inventory.xml', 'part') == rows


def test_file_rows_maps_conditions_variant_quantity_note_and_lot_id_fallback():
    data = _backup(
        _lot(
            lot_id='100010',
            boid='300010',
            name='LEGO Castle Gate Set 1000-2',
            quantity='3',
            condition='usedc',
            personal_note='Top shelf',
        ),
        _lot(
            lot_id='100011',
            boid='300011',
            name='LEGO Duplo Set 2070',
            quantity='',
            condition='other',
        ),
        _lot(lot_id='100012', boid='300012', name='', condition=''),
    )
    rows = add.file_rows(data, 'backup.xml', 'set')
    assert rows == [
        {
            'kind': 'set',
            'number': '1000-2',
            'quantity': 3,
            'condition': 'used',
            'note': 'Top shelf',
            'brickowl_boid': '300010',
        },
        {
            'kind': 'set',
            'number': '2070-1',
            'quantity': 1,
            'condition': 'any',
            'note': None,
            'brickowl_boid': '300011',
        },
        {
            'unresolved': '100012',
            'reason': 'Brick Owl lot with no set number in its name',
        },
    ]


def test_doctype_and_unknown_root_are_refused():
    doctype = b'<?xml version="1.0"?><!DOCTYPE inventory><inventory/>'
    with pytest.raises(ValueError, match='document declarations'):
        add.file_rows(doctype, 'dtd.xml', 'set')
    assert add.file_origin(doctype, 'dtd.xml') is None

    for unknown in (b'<?xml version="1.0"?><catalog/>', b'<?xml version="1.0"?><Inventory/>'):
        with pytest.raises(ValueError, match='Choose a BrickLink wanted list or inventory, or a Brick Owl inventory'):
            add.file_rows(unknown, 'other.xml', 'set')
        assert add.file_origin(unknown, 'other.xml') is None


def test_brickowl_origin_and_confirm_stamps_added_via(app4, client, csrf, read):
    payload = _backup(
        _lot(
            lot_id='100020',
            boid='300020',
            name='LEGO Castle Keep Set 1000',
            quantity='1',
            condition='newc',
            personal_note='Brick Owl backup',
        ),
    )
    assert add.file_origin(payload, 'brickowl-inventory.xml') == 'brickowl_xml'
    assert add.file_origin(payload, 'BACKUP.XML') == 'brickowl_xml'

    resp = client.post(
        '/manage/add/review',
        data={
            'csrf_token': csrf,
            'mode': 'file',
            'type': 'set',
            'where': 'owned',
            'list_id': 'default',
            'file': (io.BytesIO(payload), 'brickowl-inventory.xml'),
        },
        content_type='multipart/form-data',
    )
    review, confirmed = _review_and_confirm(client, csrf, resp)
    with app4.app_context():
        decoded = views.bw_add_signer().loads(review['token'])
    assert decoded['origin'] == 'brickowl_xml'
    receipt = confirmed['receipts'][0]
    with read() as db:
        row = db.execute(
            'SELECT added_via, condition, note FROM main.copy WHERE id=?',
            (receipt['copies'][0],),
        ).fetchone()
    assert row['added_via'] == 'brickowl_xml'
    assert row['condition'] == 'new'
    assert row['note'] == 'Brick Owl backup'
