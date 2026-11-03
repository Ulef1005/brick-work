"""Identify on the 4.0 store (M.8h, issue #110): recognition mapped to item ids, the detect route, Add's photo mode and the history.

No test reaches the network: Brickognize's transport is replaced (`base.transport`). Invented data."""
import io
import json

from PIL import Image
import pytest

from brickwork.core import identify, part_inventory
from brickwork.core.sources import base
from tests.app4 import app4, client, coll, csrf, pair, read, world  # noqa: F401 (fixtures)


def photo():
    output = io.BytesIO()
    Image.new('RGB', (24, 24), 'white').save(output, format='PNG')
    return output.getvalue()


@pytest.fixture
def brickognize(monkeypatch):
    """Replace the transport; the test sets `answer['items']` and reads the requests."""
    state = dict(items=[], requests=[])

    def http(request):
        state['requests'].append(request)
        return {'items': state['items']}
    monkeypatch.setattr(base, 'transport', http)
    return state


def guess(kind, number, score):
    return dict(type=kind, id=number, score=score)


# ---------- predictions → items ----------

def test_a_number_is_placed_by_the_born_key_then_a_bricklink_link_then_the_search(world, coll):
    db = coll.db
    coll.link(world.plate, '3023b', kind='P')
    choices, unresolved = identify.candidates(db, [dict(item_type='P', item_no='3001', score=.9), dict(item_type='P', item_no='3023b', score=.7),
                                                   dict(item_type='M', item_no='syn-fig-0004', score=.6), dict(item_type='P', item_no='nowhere', score=.2)])
    assert [(r['item_id'], r['score']) for r in choices] == [(world.brick, .9), (world.plate, .7), (world.figure, .6)]
    assert [(u['item_no'], u['reason']) for u in unresolved] == [('nowhere', 'Unknown catalogue identity')]
    assert choices[0]['owned_summary']['total'] == 5 and choices[2]['owned_summary']['text'].startswith('You have 1')


def test_a_number_that_names_two_items_is_listed_apart_never_guessed(world, coll):
    db = coll.db
    coll.link(world.brick, 'twin', kind='P')
    coll.link(world.plate, 'twin', kind='P')
    choices, unresolved = identify.candidates(db, [dict(item_type='P', item_no='twin', score=.8)])
    assert choices == [] and unresolved[0]['reason'] == 'Several catalogue items share this BrickLink number'


def test_part_inventory_takes_parts_and_figures_only_and_add_takes_sets_too(world, coll):
    db = coll.db
    predictions = [dict(item_type='S', item_no='1000-1', score=.9), dict(item_type='P', item_no='3001', score=.5)]
    assert [r['item_id'] for r in part_inventory.candidates(db, predictions)[0]] == [world.brick]
    assert [r['item_id'] for r in identify.candidates(db, predictions, kinds=('part', 'minifigure', 'set'))[0]] == [world.keep, world.brick]


# ---------- the detect route ----------

def detect(client, token, **fields):
    return client.post('/workbench/part-to-inventory/detect', data=dict(csrf_token=token, file=(io.BytesIO(photo()), 'piece.png'), **fields),
                       content_type='multipart/form-data')


def test_detect_maps_the_reply_counts_the_budget_and_keeps_the_raw_record(world, client, read, brickognize):
    token = csrf(client)
    brickognize['items'] = [guess('part', '3001', .91), guess('part', 'nowhere', .4), guess('minifig', 'syn-fig-0004', .3)]
    response = detect(client, token, endpoint='parts')
    assert response.status_code == 200, response.json
    assert [c['item_id'] for c in response.json['candidates']] == [world.brick, world.figure] and response.json['unresolved'][0]['item_no'] == 'nowhere'
    assert response.json['token'] and brickognize['requests'][0].full_url == 'https://api.brickognize.com/predict/parts/'
    with read() as db:
        assert db.execute("SELECT used FROM source_budget WHERE source='brickognize'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM source_record WHERE source='brickognize' AND kind='predict'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM event WHERE entity_kind='source_record' OR (via!='app' AND entity_kind IN ('item','stock'))").fetchone()[0] == 0
    figures = detect(client, token, endpoint='figs')
    assert figures.status_code == 200 and brickognize['requests'][1].full_url == 'https://api.brickognize.com/predict/figs/'


def test_detect_refuses_a_bad_request_and_says_when_nothing_is_identified(world, client, brickognize, monkeypatch):
    token = csrf(client)
    assert client.post('/workbench/part-to-inventory/detect', data=dict(file=(io.BytesIO(photo()), 'p.png')), content_type='multipart/form-data').status_code == 400   # no CSRF
    assert client.post('/workbench/part-to-inventory/detect', data=dict(csrf_token=token), content_type='multipart/form-data').json['error'] == 'Choose a photo'
    assert detect(client, token, endpoint='sets').status_code == 400
    assert client.post('/workbench/part-to-inventory/detect', data=dict(csrf_token=token, file=(io.BytesIO(b'not an image'), 'p.png')),
                       content_type='multipart/form-data').status_code == 400
    assert brickognize['requests'] == []
    brickognize['items'] = [guess('part', 'nowhere', .5)]
    nothing = detect(client, token)
    assert nothing.status_code == 400 and nothing.json['error'].startswith('Nothing identified') and nothing.json['unresolved']


def test_detect_stops_at_the_daily_budget(world, client, read, brickognize, monkeypatch):
    token = csrf(client)
    monkeypatch.setenv('BW_BRICKOGNIZE_DAILY_BUDGET', '1')
    brickognize['items'] = [guess('part', '3001', .9)]
    assert detect(client, token).status_code == 200
    again = detect(client, token)
    assert again.status_code == 400 and len(brickognize['requests']) == 1


def test_a_detected_piece_goes_through_the_batch_save_and_its_undo(world, coll, client, read, brickognize):
    token = csrf(client)
    brickognize['items'] = [guess('part', '3001', .91)]
    detected = detect(client, token).json
    saved = client.post('/workbench/part-to-inventory/save', json=dict(csrf_token=token, pieces=[dict(token=detected['token'], chosen=dict(item_id=world.brick, color_id=world.red, quantity=2))], keep_photos=True))
    assert saved.status_code == 200, saved.json
    with read() as db:
        assert db.execute('SELECT count(*) FROM photo WHERE item_id=? AND archived_at IS NULL', (world.brick,)).fetchone()[0] == 1
    assert client.post('/workbench/part-to-inventory/undo', json=dict(csrf_token=token, event=saved.json['event'])).status_code == 200
    with read() as db:
        assert db.execute('SELECT count(*) FROM photo WHERE item_id=? AND archived_at IS NULL', (world.brick,)).fetchone()[0] == 0


# ---------- Add's photo mode ----------

def review(client, token, **fields):
    data = dict(csrf_token=token, mode='photo', where='loose', type='set', file=(io.BytesIO(photo()), 'photo.png'))
    return client.post('/manage/add/review', data={**data, **fields}, content_type='multipart/form-data')


def confirm(client, token, proposal, **extra):
    items = [dict(r, decision='another') for r in proposal['items']]
    return client.post('/manage/add/confirm', json=dict(csrf_token=token, token=proposal['token'], items=items, **extra))


def test_photo_mode_offers_candidates_and_nothing_is_chosen_for_the_person(world, client, read, brickognize):
    token = csrf(client)
    brickognize['items'] = [guess('set', '1000-1', .9), guess('part', '3001', .6), guess('part', 'nowhere', .4)]
    response = review(client, token)
    assert response.status_code == 200, response.json
    proposal = response.json
    assert proposal['candidates'] is True and [(r['item_id'], r['score']) for r in proposal['items']] == [(world.keep, .9), (world.brick, .6)]
    assert [u['number'] for u in proposal['unresolved']] == ['nowhere']
    assert brickognize['requests'][0].full_url == 'https://api.brickognize.com/predict/'
    with read() as db:
        before = db.execute('SELECT count(*) FROM stock').fetchone()[0]
    assert confirm(client, token, proposal).status_code == 400                       # a candidate must be chosen first
    assert confirm(client, token, proposal, candidate=9).status_code == 400
    with read() as db:
        assert db.execute('SELECT count(*) FROM stock').fetchone()[0] == before


def test_photo_mode_keeps_the_photo_only_when_asked_and_undo_takes_it_back(world, client, read, brickognize):
    token = csrf(client)
    brickognize['items'] = [guess('part', '3001', .9)]
    proposal = review(client, token, type='part').json
    assert brickognize['requests'][0].full_url == 'https://api.brickognize.com/predict/parts/'
    result = client.post('/manage/add/confirm', json=dict(csrf_token=token, token=proposal['token'], candidate=0, keep_photo=True,
                                                          items=[dict(proposal['items'][0], color_id=world.white, decision='another', where='loose', condition='used')]))
    assert result.status_code == 200, result.json
    stock_id = result.json['receipts'][0]['stock']
    with read() as db:
        own = db.execute('SELECT * FROM photo WHERE stock_id=?', (stock_id,)).fetchone()
        assert own and own['item_id'] == world.brick and own['color_id'] == world.white and own['archived_at'] is None
    assert client.post('/manage/add/undo', json=dict(csrf_token=token, batch=result.json['batch'])).status_code == 200
    with read() as db:
        assert db.execute('SELECT archived_at IS NOT NULL FROM photo WHERE id=?', (own['id'],)).fetchone()[0] == 1
        assert db.execute('SELECT archived_at IS NOT NULL FROM stock WHERE id=?', (stock_id,)).fetchone()[0] == 1
    # without Keep photo nothing is saved
    proposal = review(client, token, type='part').json
    result = client.post('/manage/add/confirm', json=dict(csrf_token=token, token=proposal['token'], candidate=0, keep_photo=False,
                                                          items=[dict(proposal['items'][0], color_id=world.white, decision='another', where='loose', condition='used')]))
    assert result.status_code == 200, result.json
    with read() as db:
        assert db.execute('SELECT count(*) FROM photo WHERE archived_at IS NULL').fetchone()[0] == 0


def test_photo_mode_keeps_a_set_photo_on_the_new_copy(world, client, read, brickognize):
    token = csrf(client)
    brickognize['items'] = [guess('set', '1000-2', .9)]
    proposal = review(client, token, where='owned').json
    row = dict(proposal['items'][0], decision='another', where='owned', condition='used')
    result = client.post('/manage/add/confirm', json=dict(csrf_token=token, token=proposal['token'], candidate=0, keep_photo=True, items=[row]))
    assert result.status_code == 200, result.json
    copy_id = result.json['receipts'][0]['copies'][0]
    with read() as db:
        assert db.execute('SELECT count(*) FROM photo WHERE copy_id=? AND archived_at IS NULL', (copy_id,)).fetchone()[0] == 1
    assert client.post('/manage/add/undo', json=dict(csrf_token=token, batch=result.json['batch'])).status_code == 200      # the photo goes with the copy
    with read() as db:
        assert db.execute('SELECT archived_at IS NOT NULL FROM copy WHERE id=?', (copy_id,)).fetchone()[0] == 1


def test_photo_mode_says_when_nothing_is_identified(world, client, brickognize):
    token = csrf(client)
    brickognize['items'] = [guess('part', 'nowhere', .5)]
    response = review(client, token)
    assert response.status_code == 400 and response.json['error'].startswith('Nothing identified')
    assert client.post('/manage/add/review', data=dict(csrf_token=token, mode='photo', type='set'), content_type='multipart/form-data').json['error'] == 'Choose a photo'


# ---------- the history ----------

def test_a_stored_result_is_archived_restored_and_undone(world, coll, tmp_path):
    db = coll.db
    stored = identify.store(db, tmp_path, photo(), [dict(item_id=world.brick, item_type='P', item_no='3001', score=.9)])
    assert stored['has_thumb'] and (tmp_path / 'data/identifications' / (stored['id'] + '.jpg')).is_file()
    assert json.loads(db.execute('SELECT candidates FROM identification WHERE id=?', (stored['id'],)).fetchone()[0])[0]['name']
    identify.archive(db, stored['id'])
    assert db.execute('SELECT archived_at IS NOT NULL FROM identification WHERE id=?', (stored['id'],)).fetchone()[0] == 1
    archive = db.execute("SELECT id FROM event WHERE entity_kind='identification' AND field='archive'").fetchone()[0]
    assert identify.undo(db, archive)['already_undone'] is False
    assert db.execute('SELECT archived_at FROM identification WHERE id=?', (stored['id'],)).fetchone()[0] is None
    assert identify.undo(db, archive)['already_undone'] is True
    created = db.execute("SELECT id FROM event WHERE entity_kind='identification' AND field='create'").fetchone()[0]
    identify.undo(db, created)
    assert db.execute('SELECT archived_at IS NOT NULL FROM identification WHERE id=?', (stored['id'],)).fetchone()[0] == 1


def test_a_number_that_names_different_items_in_different_colours_is_ambiguous(world, coll):
    coll.link(world.plate, 'twin', kind='P')                                  # unscoped
    coll.link(world.brick, 'twin', kind='P', colour=world.red)                # red only
    choices, unresolved = identify.candidates(coll.db, [dict(item_type='P', item_no='twin', score=.8)])
    assert choices == [] and unresolved[0]['reason'] == 'Several catalogue items share this BrickLink number'
