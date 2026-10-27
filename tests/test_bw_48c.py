"""4.8c on the 4.0 store (M.8e, issue #110): the Take button on the missing-part and missing-figure cards of a copy, built on the transfer.

`/collection/save/take` takes `copy_id`, `item_id` and `color_id` (3.3 sent the typed number); the stock arithmetic is the Matcher's
(`workbench.take_for_gap`), one receipt, one Undo. Premise gone: a figure with a pending identity check was refused in 3.3; a link still
to check marks the row now and does not block (see `core/workbench.py`).
"""
import json
import subprocess
import shutil
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from brickwork.core import workbench as w
from tests.app4 import app4, client, coll, csrf, pair, post, read, world  # noqa: F401 (fixtures)


def derived_copy(coll):
    copy = coll.add_copy('1000-1', condition='used', completeness='incomplete', completeness_source='derived')
    for name in ('Set is checked', 'Instructions present', 'Box present'):
        coll.tag('copy', copy, coll.flag(name, 'status'))
    return copy


@pytest.fixture
def card(world, coll):
    """A copy of 1000-1 that misses 3 of the red 3001, with the world's loose red 3001 (3 used + 2 new) to take from."""
    copy = derived_copy(coll)
    coll.mark(copy, '3001', '4', missing=3)
    return copy


def page(client, world, copy):
    return BeautifulSoup(client.get(f'/collection/item/{world.keep}?copy={copy}').data, 'html.parser')


def missing(db, copy):
    return db.execute('SELECT missing FROM copy_part WHERE copy_id=? AND item_id=7 AND color_id=4', (copy,)).fetchone()[0]


def stock(db):
    return {r['id']: r['quantity'] for r in db.execute("SELECT id,quantity FROM stock WHERE kind='part' AND item_id=7 AND color_id=4 ORDER BY id")}


def test_take_single_source_receipt_completeness_and_undo(world, coll, card):
    db = coll.db
    coll.sql('UPDATE copy_part SET missing=1 WHERE copy_id=?  AND item_id=7', (card,))
    event = w.take_for_gap(db, card, world.brick, world.red, 1)
    assert db.execute('SELECT completeness FROM copy WHERE id=?', (card,)).fetchone()[0] == 'complete'
    assert db.execute('SELECT count(*) FROM stock_transfer WHERE event_id=?', (event,)).fetchone()[0] == 1
    w.undo(db, event)
    assert db.execute('SELECT completeness FROM copy WHERE id=?', (card,)).fetchone()[0] == 'incomplete'
    assert missing(db, card) == 1


def test_take_spans_two_gap_rows_of_one_identity(world, coll, card):
    """3.3 could hold two lines of one part; here a copy has one line per colour, so two copies are the two gaps to fill by hand."""
    other = derived_copy(coll)
    coll.mark(other, '3001', '4', missing=2)
    db = coll.db
    first = w.take_for_gap(db, card, world.brick, world.red, 3)
    second = w.take_for_gap(db, other, world.brick, world.red, 2)
    assert missing(db, card) == 0 and missing(db, other) == 0 and sum(stock(db).values()) == 0
    w.undo(db, second)
    w.undo(db, first)
    assert sum(stock(db).values()) == 5 and missing(db, card) == 3


def test_transfer_and_take_share_the_stock_arithmetic(world, coll, card):
    db = coll.db
    line = db.execute('SELECT id FROM copy_part WHERE copy_id=? AND item_id=7', (card,)).fetchone()[0]
    w.transfer(db, world.stock_brick, card, 'part', line, 1)
    w.take_for_gap(db, card, world.brick, world.red, 1)
    assert missing(db, card) == 1 and sum(stock(db).values()) == 3


def test_take_route_csrf_message_and_undo(world, coll, client, card):
    db = coll.db
    token = csrf(client)
    data = dict(copy_id=card, item_id=world.brick, color_id=world.red, quantity=2)
    assert client.post('/collection/save/take', json=data).status_code in (400, 403)
    assert missing(db, card) == 3
    ok = client.post('/collection/save/take', json=dict(data, csrf_token=token))
    assert ok.status_code == 200 and ok.json['message'] == 'Took 2'
    assert missing(db, card) == 1
    short = client.post('/collection/save/take', json=dict(data, csrf_token=token, quantity=3))
    assert short.status_code == 400 and short.json['message'] == 'Only 1 are missing'
    undone = client.post('/collection/save/undo', json=dict(csrf_token=token, event_id=ok.json['event_id']))
    assert undone.json['message'] == 'Undone'
    assert missing(db, card) == 3 and sum(stock(db).values()) == 5


def test_take_route_requires_login(world, coll, app4, card):
    response = app4.test_client().post('/collection/save/take', json=dict(copy_id=card, item_id=world.brick, color_id=world.red, quantity=1))
    assert response.status_code in (302, 401, 403)


def test_transfer_route_gives_one_stock_row_and_reports_a_stale_move(world, coll, client, card):
    db = coll.db
    token = csrf(client)
    line = db.execute('SELECT id FROM copy_part WHERE copy_id=? AND item_id=7', (card,)).fetchone()[0]
    data = dict(csrf_token=token, source_id=world.stock_brick, copy_id=card, target='part', target_id=line, quantity=3)
    ok = client.post('/collection/save/transfer', json=data)
    assert ok.status_code == 200 and ok.json['message'] == 'Saved' and missing(db, card) == 0
    stale = client.post('/collection/save/transfer', json=data)
    assert stale.status_code == 400 and 'changed' in stale.json['message']


def test_card_renders_stepper_only_when_editable_and_stock_exists(world, coll, client, card):
    soup = page(client, world, card)
    box = soup.select_one('.bc-missing-card [data-bc-take]')
    assert box and box['data-max'] == '3'
    assert json.loads(box['data-identity']) == dict(copy_id=card, item_id=world.brick, color_id=world.red)
    assert box.select_one('[data-bc-take-value]').get_text() == '3'
    assert box.select_one('[data-bc-take-go]').get_text() == 'Take 3'
    assert box.select_one('.bc-loose-stock').get_text() == '3 in loose stock', 'what this card can take, not all the stock'
    assert len(box.select('[data-bc-step]')) == 2 and box.select('svg')
    assert not any(c in box.get_text() for c in '-−–—')
    assert len(box.find_parent(class_='bc-missing-card').select('.bc-loose-stock')) == 1
    # No loose stock: no stepper and no stock text.
    coll.sql('UPDATE stock SET quantity=0 WHERE item_id=7')
    soup = page(client, world, card)
    assert soup.select_one('.bc-missing-card') and not soup.select_one('[data-bc-take]') and not soup.select_one('.bc-loose-stock')


def test_card_read_only_has_no_stepper(world, coll, client, card, monkeypatch):
    monkeypatch.setattr('brickwork.web.views.bw_collection_editable', lambda: False)
    soup = page(client, world, card)
    assert soup.select_one('.bc-missing-card') and not soup.select_one('[data-bc-take]')
    assert soup.select_one('.bc-missing-card .bc-loose-stock').get_text()


def test_card_max_is_the_smaller_of_missing_and_loose_stock(world, coll, client, card):
    coll.sql('UPDATE stock SET quantity=0 WHERE id=?', (world.stock_brick_new,))
    coll.sql('UPDATE stock SET quantity=2 WHERE id=?', (world.stock_brick,))
    soup = page(client, world, card)
    assert soup.select_one('[data-bc-take]')['data-max'] == '2'
    assert soup.select_one('[data-bc-take-go]').get_text() == 'Take 2'


def test_page_agrees_after_take(world, coll, client, card):
    token = csrf(client)
    client.post('/collection/save/take', json=dict(csrf_token=token, copy_id=card, item_id=world.brick, color_id=world.red, quantity=2))
    soup = page(client, world, card)
    box = soup.select_one('[data-bc-take]')
    assert box['data-max'] == '1'
    assert soup.select_one('[aria-label="Copy progress"] h3').get_text() == '1 parts missing, 1 in loose stock'
    client.post('/collection/save/take', json=dict(csrf_token=token, copy_id=card, item_id=world.brick, color_id=world.red, quantity=1))
    soup = page(client, world, card)
    assert not soup.select_one('[data-bc-take]') and not soup.select_one('.bc-missing-card')


def test_take_statement_count_does_not_grow_with_unused_sources(world, coll, card):
    db = coll.db
    coll.sql('UPDATE stock SET archived_at=? WHERE item_id=7', ('2026-01-01',))
    coll.sql('UPDATE copy_part SET missing=10, quantity=10 WHERE copy_id=? AND item_id=7', (card,))
    runs = iter(range(1000))

    def count(unused, wanted):
        tag = next(runs)
        for n in range(unused):
            coll.add_stock('part', world.brick, colour=world.red, quantity=1, condition='used', lot=coll.lot(f'bag{tag}-{n}'))
        statements = []
        db.set_trace_callback(statements.append)
        event = w.take_for_gap(db, card, world.brick, world.red, wanted)
        db.set_trace_callback(None)
        w.undo(db, event)
        coll.sql("UPDATE stock SET archived_at='2026-01-01' WHERE item_id=7 AND archived_at IS NULL")
        return len(statements)
    for wanted in (1, 5):
        small, large = count(5, wanted), count(60, wanted)
        # 55 more unused source rows: the same statements (usable amounts are computed in memory).
        assert abs(large - small) <= 3 + 5 * wanted, (wanted, small, large)


def test_take_runtime_harness():
    if not shutil.which('node'):
        pytest.skip('node is not installed')
    subprocess.run(['node', str(Path(__file__).with_name('toni_bw_take_runtime.cjs'))], check=True, capture_output=True, text=True)


# ---- whole missing figures

@pytest.fixture
def figure_card(world, coll):
    """A copy that misses its figure twice, two loose figures of that figure (one with a part marked: not offered)."""
    copy = derived_copy(coll)
    coll.mark_figure(copy, 'fig-000004', missing=2)
    figure = coll.item('minifigs', 'fig-000004')
    extra = coll.add_stock('minifigure', figure, quantity=1, condition='new')
    return copy, figure, extra


def figure_box(client, world, copy):
    soup = BeautifulSoup(client.get(f'/collection/item/{world.keep}?copy={copy}').data, 'html.parser')
    card = next(c for c in soup.select('.bc-figure-row') if 'Syn Minifigure' in c.get_text() or c.select_one('[data-bc-take]') or c.select_one('.bc-check-figure'))
    return card, card.select_one('[data-bc-take]')


def figure_missing(db, copy):
    return db.execute('SELECT missing FROM copy_figure WHERE copy_id=?', (copy,)).fetchone()[0]


def figure_stock(db, figure):
    return {r['id']: r['quantity'] for r in db.execute("SELECT id,quantity FROM stock WHERE kind='minifigure' AND item_id=? ORDER BY id", (figure,))}


def test_whole_missing_figure_card_offers_take_spanning_loose_rows(world, coll, client, figure_card):
    copy, figure, _ = figure_card
    card, box = figure_box(client, world, copy)
    assert box and box['data-max'] == '2' and 'data-action' not in box.attrs
    assert json.loads(box['data-identity']) == dict(copy_id=copy, item_id=figure, color_id=None)
    assert box.select_one('[data-bc-take-go]').get_text() == 'Take 2'
    assert box.select_one('.bc-loose-stock').get_text() == '2 in loose stock'
    assert card.select_one('.bc-check-figure').get_text() == 'Check figure parts'
    assert not any(c in box.get_text() for c in '-−–—')


def test_figure_take_fills_both_rows_one_undo_restores_all(world, coll, client, figure_card):
    copy, figure, _ = figure_card
    before = figure_stock(coll.db, figure)
    token = csrf(client)
    _, box = figure_box(client, world, copy)
    response = client.post('/collection/save/take', json=dict(json.loads(box['data-identity']), quantity=2, csrf_token=token))
    assert response.status_code == 200
    event = response.get_json()['event_id']
    assert figure_missing(coll.db, copy) == 0 and sorted(figure_stock(coll.db, figure).values()) == [0, 0]
    assert figure_box(client, world, copy)[1] is None
    assert client.post('/collection/save/undo', json=dict(csrf_token=token, event_id=event)).status_code == 200
    assert figure_missing(coll.db, copy) == 2 and figure_stock(coll.db, figure) == before
    assert figure_box(client, world, copy)[1]['data-max'] == '2'


def test_figure_take_more_than_usable_is_rejected(world, coll, client, figure_card):
    copy, figure, extra = figure_card
    coll.sql('UPDATE stock SET quantity=0 WHERE id=?', (extra,))
    before = figure_stock(coll.db, figure)
    token = csrf(client)
    ident = dict(copy_id=copy, item_id=figure, color_id=None, csrf_token=token)
    assert client.post('/collection/save/take', json=dict(ident, quantity=2)).status_code == 400
    assert client.post('/collection/save/take', json=dict(ident, quantity=3)).status_code == 400
    assert figure_missing(coll.db, copy) == 2 and figure_stock(coll.db, figure) == before


def test_figure_take_goes_ahead_while_a_link_is_still_to_check(world, coll, client, figure_card):
    copy, figure, _ = figure_card
    coll.link(figure, 'sw0001', kind='M', status='to_check')
    token = csrf(client)
    response = client.post('/collection/save/take', json=dict(copy_id=copy, item_id=figure, color_id=None, quantity=1, csrf_token=token))
    assert response.status_code == 200 and figure_missing(coll.db, copy) == 1


def test_figure_card_without_loose_figure_has_no_take(world, coll, client, figure_card):
    copy, figure, _ = figure_card
    coll.sql('UPDATE stock SET quantity=0 WHERE item_id=?', (figure,))
    card, box = figure_box(client, world, copy)
    assert box is None and not card.select_one('.bc-loose-stock')
    assert card.select_one('.bc-check-figure')


def test_figure_card_read_only_shows_stock_text_only(world, coll, client, figure_card, monkeypatch):
    copy, figure, _ = figure_card
    monkeypatch.setattr('brickwork.web.views.bw_collection_editable', lambda: False)
    card, box = figure_box(client, world, copy)
    assert box is None and card.select_one('.bc-loose-stock').get_text() == '2 in loose stock'
