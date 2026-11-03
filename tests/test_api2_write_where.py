"""API v2 writes on where things are and where they came from (M.11c, issue #113): storages, lots, purchase places, flags, the PDFs of sets and the
photos of copies and stock. Ported from test_bw_api_m3 (the location and upload cases), test_bw_media_27 and the lot and storage cases of test_bw_api_m4
onto the 4.0 fixtures. Every answer is validated against `openapi-v2.yaml`. Invented data."""
from contextlib import closing
import io
import json
from pathlib import Path

import pytest

from brickwork.core.connect import connect
from tests.api2 import call, events, row, rows, v2, validate, write  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401
from tests.app4 import table_digest

PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n'


def digest(pair):
    with closing(connect(pair)) as db:
        return table_digest(db, skip=('event', 'event_undo', 'item_merge', 'stock_transfer'))


def upload(v2, path, fields, content=PDF, name='x.pdf', mimetype='application/pdf', **kwargs):
    data = dict(fields, file=(io.BytesIO(content), name, mimetype))
    return write(v2, path, data=data, content_type='multipart/form-data', **kwargs)


def png():
    """A tiny readable picture."""
    from PIL import Image
    out = io.BytesIO()
    Image.new('RGB', (4, 3), (200, 10, 10)).save(out, 'PNG')
    return out.getvalue()


# ---------- every edit is one event, replays, and is undone exactly ----------

def test_every_edit_of_a_place_is_one_event_replays_and_is_undone_exactly(v2, world, pair):
    cases = [
        ('patch_storages_by_id', 'patch', f'/storages/{world.shelf}', {'name': 'Shelf B', 'type': 'Box', 'note': 'Top'}),
        ('post_storages_by_id_contents', 'post', f'/storages/{world.shelf}/contents', {'selections': [{'entity': 'copy', 'id': world.copy_b}]}),
        ('patch_lots_by_id', 'patch', f'/lots/{world.bag}', {'name': 'Big bag', 'note': 'Mixed', 'purchase_price': '2.00', 'purchase_currency': 'EUR'}),
        ('delete_lots_by_id', 'delete', f'/lots/{world.bag}', None),
        ('patch_places_by_id', 'patch', f'/places/{world.shop}', {'name': 'Big shop'}),
        ('delete_places_by_id', 'delete', f'/places/{world.shop}', None),
        ('patch_flags_by_id', 'patch', f'/flags/{world.tag}', {'name': 'collected'}),
        ('delete_flags_by_id', 'delete', f'/flags/{world.tag}', None),
    ]
    for operation, method, path, body in cases:
        before, count = digest(pair), len(events(pair))
        response = write(v2, path, method, body, key='edit-' + operation.replace('_', '-'))
        validate(response, operation)
        made = [e for e in events(pair, 'id>?', (count,)) if e['entity_kind'] != 'bw_api']
        assert made and all((e['via'], e['actor']) == ('api', 'bootstrap') for e in made), operation
        replay = write(v2, path, method, body, key='edit-' + operation.replace('_', '-'))
        assert replay.json['idempotent_replay'] is True and replay.json['data'] == response.json['data'] and replay.json['event_id'] == response.json['event_id']
        undone = write(v2, f"/events/{response.json['event_id']}/undo")
        assert undone.status_code == 200 and undone.json['data']['already_undone'] is False, operation
        assert digest(pair) == before, operation


# ---------- storages ----------

def test_a_storage_is_created_with_a_type_a_parent_and_a_note_and_renamed_keeping_the_rest(v2, world):
    made = write(v2, '/storages', body={'name': 'Cellar', 'type': 'Room'})
    validate(made, 'post_storages', '201')
    cellar = made.json['data']['id']
    child = write(v2, '/storages', body={'name': 'Crate', 'type': 'Box', 'parent_id': cellar, 'note': 'Blue'})
    validate(child, 'post_storages', '201')
    assert (child.json['data']['parent_id'], child.json['data']['parent_name'], child.json['data']['note']) == (cellar, 'Cellar', 'Blue')
    renamed = write(v2, f"/storages/{child.json['data']['id']}", 'patch', {'name': 'Crate 2'})
    validate(renamed, 'patch_storages_by_id')
    assert (renamed.json['data']['name'], renamed.json['data']['type'], renamed.json['data']['parent_id'], renamed.json['data']['note']) == ('Crate 2', 'Box', cellar, 'Blue')
    cleared = write(v2, f"/storages/{child.json['data']['id']}", 'patch', {'name': 'Crate 2', 'parent_id': None, 'note': None, 'type': None})
    assert (cleared.json['data']['parent_id'], cleared.json['data']['note'], cleared.json['data']['type']) == (None, None, None)
    assert write(v2, f'/storages/{cellar}', 'patch', {'name': 'Cellar', 'parent_id': cellar}).status_code == 422          # not inside itself
    assert write(v2, '/storages', body={'name': 'x', 'type': 'Hangar'}).status_code == 422
    assert write(v2, '/storages', body={'name': ' '}).status_code == 422
    assert write(v2, '/storages/unstored', 'patch', {'name': 'x'}).status_code == 404
    assert write(v2, '/storages/nope', 'patch', {'name': 'x'}).status_code == 404


def test_a_storage_with_things_in_it_is_archived_only_with_move_to_unstored(v2, world, pair):
    path = f'/storages/{world.shelf}'
    refused = write(v2, path, 'delete')
    assert refused.status_code == 409 and refused.json['code'] == 'conflict'
    assert write(v2, path + '?move_to_unstored=maybe', 'delete').status_code == 400
    assert write(v2, path + '?other=1', 'delete').status_code == 400
    before = digest(pair)
    archived = write(v2, path + '?move_to_unstored=true', 'delete')
    validate(archived, 'delete_storages_by_id')
    assert archived.json['data']['archived_at'] and row(pair, 'SELECT storage_id FROM main.copy WHERE id=?', (world.copy_a,))['storage_id'] is None
    assert write(v2, path, 'patch', {'name': 'x'}).json['code'] == 'archived'
    assert write(v2, f"/events/{archived.json['event_id']}/undo").status_code == 200
    assert digest(pair) == before
    again = write(v2, path + '?move_to_unstored=true', 'delete')
    restored = write(v2, path + '/restore')
    validate(restored, 'post_storages_by_id_restore')
    assert restored.json['data']['archived_at'] is None
    assert write(v2, path + '/restore').status_code == 409 and again.status_code == 200


def test_a_storage_with_a_storage_inside_is_not_archived(v2, world):
    inner = write(v2, '/storages', body={'name': 'Inner', 'parent_id': world.shelf}).json['data']['id']
    refused = write(v2, f'/storages/{world.shelf}?move_to_unstored=true', 'delete')
    assert refused.status_code == 409 and 'inside' in refused.json['detail']
    empty = write(v2, f'/storages/{inner}', 'delete')
    assert empty.status_code == 200 and empty.json['data']['archived_at']


def test_things_move_into_a_storage_and_out_of_it(v2, world, pair):
    box = write(v2, '/storages', body={'name': 'Box'}).json['data']['id']
    moved = write(v2, f'/storages/{box}/contents', body={'selections': [{'entity': 'copy', 'id': world.copy_b}, {'entity': 'stock', 'id': world.stock_plate},
                                                                     {'entity': 'lot', 'id': world.bag}]})
    validate(moved, 'post_storages_by_id_contents')
    assert row(pair, 'SELECT storage_id FROM main.copy WHERE id=?', (world.copy_b,))['storage_id'] == box
    assert row(pair, 'SELECT storage_id FROM main.lot WHERE id=?', (world.bag,))['storage_id'] == box
    assert row(pair, 'SELECT storage_id FROM main.stock WHERE id=?', (world.stock_brick,))['storage_id'] == box                 # the lot carries its parts
    out = write(v2, '/storages/unstored/contents', body={'selections': [{'entity': 'copy', 'id': world.copy_b}]})
    assert out.status_code == 200 and row(pair, 'SELECT storage_id FROM main.copy WHERE id=?', (world.copy_b,))['storage_id'] is None
    blocked = write(v2, f"/events/{moved.json['event_id']}/undo")                       # the copy moved again meanwhile: undo that first
    assert blocked.status_code == 409 and blocked.json['code'] == 'undo_blocked'
    assert write(v2, f"/events/{out.json['event_id']}/undo").status_code == 200
    assert write(v2, f"/events/{moved.json['event_id']}/undo").status_code == 200
    assert row(pair, 'SELECT storage_id FROM main.stock WHERE id=?', (world.stock_brick,))['storage_id'] == world.shelf
    for body in ({'selections': [{'entity': 'copy', 'id': 'nope'}]}, {'selections': [{'entity': 'wish', 'id': world.wish_set}]}, {'selections': []}):
        assert write(v2, f'/storages/{box}/contents', body=body).status_code == 422
    assert write(v2, '/storages/nope/contents', body={'selections': [{'entity': 'copy', 'id': world.copy_a}]}).status_code == 404
    assert write(v2, f'/storages/{box}/contents', body={'selections': [{'entity': 'copy', 'id': world.copy_a}]}, key=False).status_code == 428


# ---------- lots ----------

def test_a_lot_is_made_from_stock_lines_and_undone_by_archiving(v2, world, pair):
    made = write(v2, '/lots', body={'name': 'Fresh lot', 'stock_ids': [world.stock_plate, world.stock_brick_new], 'note': 'From the fair', 'storage_id': world.shelf})
    validate(made, 'post_lots', '201')
    lot = made.json['data']
    assert (lot['name'], lot['note'], lot['storage_id'], lot['entries'], lot['quantity']) == ('Fresh lot', 'From the fair', world.shelf, 2, 4)
    assert call(v2, f"/stock/{world.stock_plate}").json['data']['lot_id'] == lot['id']
    assert write(v2, f"/events/{made.json['event_id']}/undo").status_code == 200
    assert call(v2, f"/stock/{world.stock_plate}").json['data']['lot_id'] is None
    assert call(v2, f"/lots/{lot['id']}").json['data']['lot']['archived_at']
    assert write(v2, '/lots', body={'name': 'x', 'stock_ids': []}).status_code == 422
    assert write(v2, '/lots', body={'name': 'x', 'stock_ids': ['nope']}).status_code == 422
    assert write(v2, '/lots', body={'name': ' ', 'stock_ids': [world.stock_plate]}).status_code == 422
    assert write(v2, '/lots', body={'name': 'x', 'stock_ids': [world.stock_plate]}, key=False).status_code == 428


def test_a_lot_is_edited_archived_and_restored(v2, world):
    path = f'/lots/{world.bag}'
    edited = write(v2, path, 'patch', {'purchase_location_id': world.shop, 'purchase_date': '2026-01-02', 'storage_id': None})
    validate(edited, 'patch_lots_by_id')
    assert (edited.json['data']['purchase_location_id'], edited.json['data']['storage_id']) == (world.shop, None)
    assert write(v2, path, 'patch', {'name': ''}).status_code == 422
    assert write(v2, path, 'patch', {'purchase_location_id': 'nowhere'}).status_code == 422
    archived = write(v2, path, 'delete')
    validate(archived, 'delete_lots_by_id')
    assert write(v2, path, 'patch', {'name': 'x'}).json['code'] == 'archived'
    restored = write(v2, path + '/restore')
    validate(restored, 'post_lots_by_id_restore')
    assert restored.json['data']['archived_at'] is None and write(v2, path + '/restore').status_code == 409
    assert write(v2, '/lots/nope', 'delete').status_code == 404


# ---------- places and flags ----------

def test_a_purchase_place_is_created_renamed_archived_and_restored(v2, world):
    made = write(v2, '/places', body={'name': 'Fair'})
    validate(made, 'post_places', '201')
    place = made.json['data']['id']
    renamed = write(v2, f'/places/{place}', 'patch', {'name': 'Big fair'})
    validate(renamed, 'patch_places_by_id')
    assert renamed.json['data']['name'] == 'Big fair'
    deleted = write(v2, f'/places/{place}', 'delete')
    validate(deleted, 'delete_places_by_id')
    assert deleted.json['data'] == {'id': place, 'archived': True}
    assert write(v2, f'/places/{place}', 'patch', {'name': 'x'}).json['code'] == 'archived'
    restored = write(v2, f'/places/{place}/restore')
    validate(restored, 'post_places_by_id_restore')
    assert restored.json['data']['archived_at'] is None and restored.json['data']['name'] == 'Big fair'
    assert write(v2, f'/places/{world.shop}', 'delete').status_code == 200
    assert call(v2, f'/copies/{world.copy_a}').json['data']['purchase_location_id'] == world.shop                    # archived, references kept
    assert write(v2, '/places', body={'name': ''}).status_code == 422


def test_a_flag_is_created_by_kind_renamed_and_archived_keeping_its_links(v2, coll, world):
    for kind in ('owner', 'status', 'tag'):
        made = write(v2, '/flags', body={'name': f'New {kind}', 'kind': kind})
        validate(made, 'post_flags', '201')
        assert made.json['data']['kind'] == kind and made.json['data']['count'] == 0
    assert write(v2, '/flags', body={'name': 'x', 'kind': 'colour'}).status_code == 422
    renamed = write(v2, f'/flags/{world.tag}', 'patch', {'name': 'kept'})
    validate(renamed, 'patch_flags_by_id')
    assert renamed.json['data']['name'] == 'kept' and renamed.json['data']['count'] == 1
    deleted = write(v2, f'/flags/{world.tag}', 'delete')
    validate(deleted, 'delete_flags_by_id')
    assert deleted.json['data']['archived'] is True
    assert world.tag not in call(v2, f'/copies/{world.copy_a}').json['data']['flags']                                # an archived flag is not shown
    restored = write(v2, f'/flags/{world.tag}/restore')
    validate(restored, 'post_flags_by_id_restore')
    assert world.tag in call(v2, f'/copies/{world.copy_a}').json['data']['flags']                                    # its links were kept
    coll.sql('UPDATE flag SET system=1 WHERE id=?', (world.checked,))
    assert write(v2, f'/flags/{world.checked}', 'patch', {'name': 'x'}).status_code == 409                          # the app's own flag
    assert write(v2, f'/flags/{world.checked}', 'delete').status_code == 409


# ---------- the PDFs of sets ----------

def test_a_pdf_is_attached_by_number_renamed_archived_and_restored(v2, world, pair):
    item = json.dumps({'kind': 'set', 'key': '1000-1'})
    made = upload(v2, '/instruction-files', {'item': item, 'label': 'Booklet 1'})
    validate(made, 'post_instruction_files', '201')
    identifier = made.json['data']['id']
    assert (made.json['data']['item']['id'], made.json['data']['label'], made.json['data']['content_url']) == (world.keep, 'Booklet 1', f'/api/v2/instruction-files/{identifier}/content')
    served = call(v2, made.json['data']['content_url'].removeprefix('/api/v2'))
    assert served.status_code == 200 and served.data == PDF
    assert any((Path(pair).parent / 'data/instructions').glob('*.pdf'))
    renamed = write(v2, f'/instruction-files/{identifier}', 'patch', {'label': 'Booklet one'})
    validate(renamed, 'patch_instruction_files_by_id')
    assert renamed.json['data']['label'] == 'Booklet one'
    archived = write(v2, f'/instruction-files/{identifier}', 'delete')
    validate(archived, 'delete_instruction_files_by_id')
    assert archived.json['data'] == {'id': identifier, 'archived': True}
    assert write(v2, f'/instruction-files/{identifier}', 'patch', {'label': 'x'}).json['code'] == 'archived'
    restored = write(v2, f'/instruction-files/{identifier}/restore')
    validate(restored, 'post_instruction_files_by_id_restore')
    assert restored.json['data']['archived_at'] is None
    assert write(v2, f'/instruction-files/{identifier}/restore').status_code == 409
    assert write(v2, f"/events/{made.json['event_id']}/undo").status_code == 409                                        # later changes to the file record come first
    assert write(v2, '/instruction-files/999/restore').status_code == 404


def test_a_pdf_is_named_by_id_or_through_its_booklet_and_only_a_set_can_hold_it(v2, world):
    by_id = upload(v2, '/instruction-files', {'item': json.dumps({'id': world.keep}), 'label': 'By id'}, content=PDF + b'1')
    assert by_id.status_code == 201 and by_id.json['data']['item']['id'] == world.keep
    booklet = upload(v2, '/instruction-files', {'item': json.dumps({'id': world.local_booklet}), 'label': 'Through the booklet'}, content=PDF + b'2')
    assert booklet.status_code == 201 and booklet.json['data']['item']['id'] == world.keep                       # the booklet 1000-1 names the set 1000-1
    assert upload(v2, '/instruction-files', {'item': json.dumps({'id': world.brick}), 'label': 'x'}).status_code == 422
    assert upload(v2, '/instruction-files', {'item': json.dumps({'kind': 'set', 'key': '99999-1'}), 'label': 'x'}).json['code'] == 'unidentified'


def test_a_pdf_upload_is_checked_before_anything_is_written(v2, world, pair):
    item = json.dumps({'id': world.keep})
    before = digest(pair)
    assert upload(v2, '/instruction-files', {'item': item, 'label': 'x'}, content=b'not a pdf').status_code == 422
    assert upload(v2, '/instruction-files', {'item': item, 'label': ''}).status_code == 422
    assert upload(v2, '/instruction-files', {'item': 'not json', 'label': 'x'}).status_code == 422
    assert upload(v2, '/instruction-files', {'item': item}).status_code == 422
    big = upload(v2, '/instruction-files', {'item': item, 'label': 'x'}, content=b'%PDF-' + b'0' * (20 * 1024 * 1024))
    assert big.status_code == 413 and big.json['code'] == 'payload_too_large'
    assert write(v2, '/instruction-files', body={'item': {'id': world.keep}, 'label': 'x'}).status_code == 415       # JSON where multipart is the contract
    assert digest(pair) == before and not list((Path(pair).parent / 'data/instructions').glob('*.pdf'))


def test_a_failed_upload_leaves_no_file_behind(v2, world, pair, monkeypatch):
    from brickwork.core import admin
    real = admin.audit

    def failing(db, entity, *args, **kwargs):
        if entity.startswith('bw_api'):
            raise RuntimeError('Injected failure')
        return real(db, entity, *args, **kwargs)
    monkeypatch.setattr(admin, 'audit', failing)
    before = digest(pair)
    assert upload(v2, '/instruction-files', {'item': json.dumps({'id': world.keep}), 'label': 'x'}).status_code == 500
    assert digest(pair) == before and not list((Path(pair).parent / 'data/instructions').glob('*.pdf'))


# ---------- photos ----------

@pytest.mark.parametrize('kind', ['copies', 'stock'])
def test_an_own_photo_is_kept_with_its_caption_and_undone_by_archiving(v2, world, pair, kind):
    identifier = world.copy_a if kind == 'copies' else world.stock_brick
    made = upload(v2, f'/{kind}/{identifier}/photos', {'caption': 'Front'}, content=png(), name='x.png', mimetype='image/png')
    validate(made, 'post_copies_by_id_photos' if kind == 'copies' else 'post_stock_by_id_photos')
    photo = row(pair, 'SELECT * FROM main.photo WHERE %s=?' % ('copy_id' if kind == 'copies' else 'stock_id'), (identifier,))
    assert photo['caption'] == 'Front' and (Path(pair).parent / photo['local_path']).is_file()
    assert photo['id'] in [i['id'] for i in call(v2, f"/items/{photo['item_id']}/images").json['data']]
    assert call(v2, f"/images/{photo['id']}/content").status_code == 200
    assert write(v2, f"/events/{made.json['event_id']}/undo").status_code == 200
    assert row(pair, 'SELECT archived_at FROM main.photo WHERE id=?', (photo['id'],))['archived_at']
    assert upload(v2, f'/{kind}/{identifier}/photos', {}, content=b'not a picture', mimetype='image/png').status_code == 422
    assert upload(v2, f'/{kind}/{identifier}/photos', {}, content=png(), mimetype='application/pdf').status_code == 415
    assert upload(v2, f'/{kind}/nope/photos', {}, content=png(), mimetype='image/png').status_code == 404
    assert write(v2, f'/{kind}/{identifier}/photos', body={'caption': 'x'}).status_code == 415


@pytest.mark.parametrize('path,body,table', [('/storages', {'name': 'Cellar'}, 'storage'), ('/places', {'name': 'Fair'}, 'place'), ('/flags', {'name': 'Loved', 'kind': 'tag'}, 'flag')])
def test_a_created_place_is_undone_by_archiving_it(v2, world, pair, path, body, table):
    made = write(v2, path, body=body)
    assert made.status_code == 201
    identifier = made.json['data']['id']
    assert write(v2, f"/events/{made.json['event_id']}/undo").status_code == 200
    assert row(pair, f'SELECT archived_at FROM main.{table} WHERE id=?', (identifier,))['archived_at']


def test_a_photo_a_pdf_and_their_thumbnails_go_to_the_media_folder_and_the_database_stays(v2, coll, world, pair, monkeypatch, tmp_path):
    """#27: BW_MEDIA_PATH moves pictures, thumbnails and PDFs. (The reads of the test this was ported from are in test_api2_read_catalogue.)"""
    target = tmp_path / 'nas'
    monkeypatch.setenv('BW_MEDIA_PATH', str(target))
    big = io.BytesIO()
    from PIL import Image
    Image.new('RGB', (1200, 900), (200, 30, 30)).save(big, 'PNG')
    photo = upload(v2, f'/copies/{world.copy_a}/photos', {}, content=big.getvalue(), name='x.png', mimetype='image/png')
    assert photo.status_code == 200, photo.get_data(as_text=True)
    stored = row(pair, 'SELECT id, local_path FROM main.photo WHERE copy_id=?', (world.copy_a,))
    assert (target / stored['local_path']).is_file() and not (Path(pair).parent / stored['local_path']).exists()
    content = call(v2, f"/images/{stored['id']}/content")
    assert content.status_code == 200 and content.data[:2] == b'\xff\xd8'
    pdf = upload(v2, '/instruction-files', {'item': json.dumps({'kind': 'set', 'key': '1000-1'}), 'label': 'Synthetic PDF'})
    assert pdf.status_code == 201
    pdfs = list((target / 'data/instructions').glob('*.pdf'))
    assert len(pdfs) == 1 and not (Path(pair).parent / 'data/instructions' / pdfs[0].name).exists()
    from brickwork.core import thumbnails
    (target / 'data/images').mkdir(parents=True, exist_ok=True)
    (target / 'data/images/cached.png').write_bytes(big.getvalue())                                     # a provider picture, cached in the media folder
    coll.sql("INSERT INTO picture(item_id,color_id,source,kind,local_path,width,height,fetched_at) VALUES(?,NULL,'bricklink','photo','data/images/cached.png',1200,900,'2026-10-26T12:00:00.000Z')",
             (world.keep,))
    assert thumbnails.pregenerate(Path(pair)) >= 1 and list((target / 'data/thumbs').glob('*'))
