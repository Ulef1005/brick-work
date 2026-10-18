"""#51: Take for whole minifigures over /api/v1 (and MCP through the same operation). Invented data."""
from contextlib import closing
import os

from tests.test_bw_api_m1 import app, call  # noqa: F401
from tests.test_bw_api_m2 import populated  # noqa: F401
from brickwork.core.connect import connect


HEADERS = {'Authorization': 'Bearer synthetic-bootstrap'}


def take(app, body, key):
    return app.test_client().post('/api/v1/copies/c1/take', json=body, headers=dict(HEADERS, **{'Idempotency-Key': key}))


def figure_state():
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        return (db.execute("SELECT missing FROM copy_minifigs WHERE copy_id='c1' AND minifig_no='fig1'").fetchone()[0],
                db.execute("SELECT quantity,archived_at FROM loose_stock WHERE id='m1'").fetchone()[:])


def usable_figure():
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.execute("UPDATE loose_minifig_parts SET missing=0 WHERE stock_id='m1'")


def test_take_whole_figure_and_undo(populated):
    usable_figure()
    before = figure_state()
    made = take(populated, {'item_type': 'M', 'item_no': 'fig1', 'quantity': 1}, 'take-fig-1')
    assert made.status_code == 200, made.json
    assert figure_state()[0] == 0
    undone = populated.test_client().post(f"/api/v1/events/{made.json['event_id']}/undo",
                                          headers=dict(HEADERS, **{'Idempotency-Key': 'take-fig-undo'}))
    assert undone.status_code == 200, undone.json
    assert figure_state() == before


def test_figure_with_colour_null_colour_part_and_over_take(populated):
    usable_figure()
    assert take(populated, {'item_type': 'M', 'item_no': 'fig1', 'color_id': None, 'quantity': 1}, 'k1').status_code == 200
    refused = take(populated, {'item_type': 'M', 'item_no': 'fig1', 'color_id': 4, 'quantity': 1}, 'k2')
    assert refused.status_code == 422 and 'colour' in refused.json['detail']
    part = take(populated, {'item_type': 'P', 'item_no': '3001', 'quantity': 1}, 'k3')
    assert part.status_code == 422 and 'colour' in part.json['detail']
    over = take(populated, {'item_type': 'M', 'item_no': 'fig1', 'quantity': 1}, 'k4')
    assert over.status_code == 422 and over.json['detail'] == 'Nothing is left in loose stock'
