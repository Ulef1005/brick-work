"""API v2 `POST /items/{id}/change-variant` (issue #151): the happy path with its receipt and Undo through `/events/{id}/undo`, and the refusal codes.
Invented data, no network."""
from contextlib import closing

import pytest

from brickwork.core.connect import connect
from tests.api2 import call, events, rows, v2, validate, write  # noqa: F401
from tests.api2 import app4, coll, world  # noqa: F401
from tests.app4 import RICH, make_pair, table_digest

NUMBER = 'syn-fig-0004'


@pytest.fixture
def pair(tmp_path):
    """The rich fixture catalogue plus a reissue of the figure, `fig-000005`."""
    extra = {'minifigs': [['fig-000005', 'Syn Reissue Figure', 1, '']], 'inventories': [*RICH['inventories'], [99001, 1, 'fig-000005']],
             'inventory_parts': [*RICH['inventory_parts'], [99001, '3023', 15, 1, 'False', '']]}
    return make_pair(tmp_path, rich=True, extra_dump=extra)


def digest(pair):
    with closing(connect(pair)) as db:
        return table_digest(db, skip=('event', 'event_undo', 'item_merge', 'stock_transfer'))


@pytest.fixture
def variant(coll, world):
    new = coll.project(coll.item('minifigs', 'fig-000005'))
    coll.link(new, NUMBER, kind='M', status='to_check')
    return new


def change(v2, old, body, **kwargs):
    return write(v2, f'/items/{old}/change-variant', body=body, **kwargs)


def test_a_change_moves_the_rows_prefers_the_number_and_undo_puts_everything_back(v2, world, variant, pair):
    before = digest(pair)
    done = change(v2, world.figure, {'to': {'id': variant}})
    validate(done, 'post_items_by_id_change_variant')
    data = done.json['data']
    assert (data['from']['id'], data['to']['id'], data['number'], data['receipt']['event_id']) == (world.figure, variant, NUMBER, done.json['event_id'])
    assert data['receipt']['counts']['stock'] == {'changed': 1} and done.json['undo_url'] == f"/api/v2/events/{done.json['event_id']}/undo"
    assert rows(pair, 'SELECT item_id FROM main.stock WHERE id=?', (world.stock_figure,))[0]['item_id'] == variant
    links = {(r['item_id'], r['status'], r['preferred']) for r in rows(pair, "SELECT * FROM main.item_link WHERE provider='bricklink' AND provider_key=?", (NUMBER,))}
    assert links == {(variant, 'manual', 1), (world.figure, 'to_check', 0)}
    assert call(v2, f'/minifigures/by-number/{NUMBER}').json['data']['id'] == variant
    event = events(pair, 'id=?', (done.json['event_id'],))[0]
    assert (event['entity_kind'], event['field'], event['via'], event['actor']) == ('item', 'change_variant', 'api', 'bootstrap')
    assert call(v2, f'/items/{world.figure}').status_code == 200                                              # the old variant stays a plain item
    undone = write(v2, f"/events/{done.json['event_id']}/undo")
    assert undone.status_code == 200 and digest(pair) == before


def test_a_change_the_rules_refuse_is_409_and_one_that_names_nothing_is_422(v2, coll, world, variant, pair):
    assert change(v2, world.figure, {'to': {'id': world.brick}}).status_code == 409                          # another kind
    assert change(v2, world.figure, {'to': {'id': world.figure}}).status_code == 409                        # itself
    merged = coll.local('minifigure', 'Gone', born_key='gone')
    assert write(v2, f'/items/{merged}/merge', body={'survivor': {'id': variant}}).status_code == 200
    refused = change(v2, world.figure, {'to': {'id': merged}})                                              # the merged item: 409 merged, as every write
    assert refused.status_code == 409 and refused.json['code'] == 'merged' and refused.json['survivor'] == variant
    again = change(v2, merged, {'to': {'id': variant}})
    assert again.status_code == 409 and again.json['code'] == 'merged'
    stamp = '2026-10-26T12:00:00.000Z'
    coll.sql("INSERT INTO job(source,kind,item_id,state,via,created_at,updated_at) VALUES('bricklink','item',?,'queued','app',?,?)", (variant, stamp, stamp))
    before = digest(pair)
    busy = change(v2, world.figure, {'to': {'id': variant}})
    assert busy.status_code == 409 and 'still in flight' in busy.json['detail'] and digest(pair) == before
    assert change(v2, world.figure, {'to': {'id': 987654321}}).status_code == 422
    assert change(v2, world.figure, {}).status_code == 422
    assert change(v2, world.figure, {'to': {'id': variant}, 'extra': 1}).status_code == 422
    assert change(v2, 987654321, {'to': {'id': variant}}).status_code == 404
    assert change(v2, world.figure, {'to': {'id': variant}}, key=False).status_code == 428
