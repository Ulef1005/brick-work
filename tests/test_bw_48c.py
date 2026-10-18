"""4.8c: the Take button on the missing-part card, built on the existing transfer."""
import json
import subprocess
from contextlib import closing
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from brickwork.core import collection, workbench as w
from brickwork.core.connect import connect
from tests.test_bw_add import bw, app, legacy, apps, client_token  # noqa: F401
from tests.test_bw_workbench import gaps  # noqa: F401
from tests.test_bw_collection import reset_shell_metadata_after_test  # noqa: F401

PART = ('P', 'bl-part', 11)
URL = '/collection/item/S/new-set?copy=copy'


def stock(db, part='copy'):
    return {r['id']: r['quantity'] for r in db.execute("SELECT id,quantity FROM loose_stock WHERE item_type='P' AND item_no='bl-part' AND color_id=11 ORDER BY id")}


def split_stock(path, first=2, second=2):
    """Two source rows for one identity; 'loose-part' keeps the biggest usable amount."""
    with closing(connect(path)) as db, db:
        db.execute("UPDATE loose_stock SET quantity=? WHERE id='loose-part'", (first,))
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES('loose-part-b','P','bl-part',11,?,'U')", (second,))


def part_missing(db, part):
    return db.execute('SELECT missing FROM copy_parts WHERE id=?', (part,)).fetchone()[0]


def test_take_single_source_events_completeness_and_undo(gaps):
    path, part = gaps
    with closing(connect(path)) as db:
        before = stock(db)
        assert before['loose-part'] == 3
        event = w.take_for_gap(db, 'copy', *PART, 2)
        assert part_missing(db, part) == 1 and stock(db)['loose-part'] == 1
        assert db.execute("SELECT completeness FROM copies WHERE id='copy'").fetchone()[0] == 'I'
        row = db.execute('SELECT via,entity,field FROM events WHERE id=?', (event,)).fetchone()
        assert tuple(row) == ('app', 'bw_workbench', 'receipt')
        w.undo(db, event)
        assert part_missing(db, part) == 3 and stock(db) == before


def test_take_all_recomputes_completeness_and_undo_restores_it(gaps):
    path, part = gaps
    with closing(connect(path)) as db:
        event = w.take_for_gap(db, 'copy', *PART, 3)
        assert part_missing(db, part) == 0
        assert db.execute("SELECT completeness FROM copies WHERE id='copy'").fetchone()[0] == 'C'
        w.undo(db, event)
        assert db.execute("SELECT completeness FROM copies WHERE id='copy'").fetchone()[0] == 'I'
        assert part_missing(db, part) == 3


def test_take_spans_two_source_rows_in_one_receipt(gaps):
    path, part = gaps
    split_stock(path, 2, 2)
    with closing(connect(path)) as db:
        before = stock(db)
        events = db.execute("SELECT count(*) FROM events WHERE entity='bw_workbench' AND field='receipt'").fetchone()[0]
        event = w.take_for_gap(db, 'copy', *PART, 3)
        assert db.execute("SELECT count(*) FROM events WHERE entity='bw_workbench' AND field='receipt'").fetchone()[0] == events + 1
        after = stock(db)
        assert sum(before.values()) - sum(after.values()) == 3 and part_missing(db, part) == 0
        # Matcher order: the larger usable amount first, then the stock id.
        assert after['loose-part'] == 0 and after['loose-part-b'] == 1
        assert db.execute('SELECT count(*) FROM match_history').fetchone()[0] == 2
        w.undo(db, event)
        assert stock(db) == before and part_missing(db, part) == 3


def test_take_more_than_available_or_missing_writes_nothing(gaps):
    path, part = gaps
    with closing(connect(path)) as db:
        with db:
            db.execute("UPDATE loose_stock SET quantity=2 WHERE id='loose-part'")
        tables = ('copies', 'copy_parts', 'loose_stock', 'match_history', 'events')
        snap = lambda: {t: [tuple(r) for r in db.execute('SELECT * FROM ' + t)] for t in tables}
        before = snap()
        with pytest.raises(ValueError, match='Only 2 are left in loose stock'):
            w.take_for_gap(db, 'copy', *PART, 3)
        assert snap() == before
        with db:
            db.execute("UPDATE loose_stock SET quantity=9 WHERE id='loose-part'")
            db.execute('UPDATE copy_parts SET missing=1 WHERE id=?', (part,))
        before = snap()
        with pytest.raises(ValueError, match='Only 1 are missing'):
            w.take_for_gap(db, 'copy', *PART, 2)
        assert snap() == before
        for bad in (0, -1, 'x'):
            with pytest.raises((ValueError, TypeError)):
                w.take_for_gap(db, 'copy', *PART, bad)
        assert snap() == before


def test_take_rolls_back_when_a_later_step_fails(gaps):
    path, part = gaps
    split_stock(path, 2, 2)
    with closing(connect(path)) as db:
        with db:
            db.execute("CREATE TRIGGER stop_second BEFORE INSERT ON match_history WHEN (SELECT count(*) FROM match_history)>=1 BEGIN SELECT RAISE(ABORT,'fixture'); END")
        before = (stock(db), part_missing(db, part))
        with pytest.raises(Exception):
            w.take_for_gap(db, 'copy', *PART, 3)
        assert (stock(db), part_missing(db, part)) == before


def test_take_spans_two_gap_rows_of_one_identity(gaps):
    path, part = gaps
    with closing(connect(path)) as db, db:
        db.execute("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing,checked,spare) VALUES('copy','P','bl-part',11,2,2,1,0)")
        db.execute("UPDATE loose_stock SET quantity=5 WHERE id='loose-part'")
    with closing(connect(path)) as db:
        event = w.take_for_gap(db, 'copy', *PART, 5)
        assert db.execute("SELECT sum(missing) FROM copy_parts WHERE copy_id='copy' AND item_no='bl-part'").fetchone()[0] == 0
        w.undo(db, event)
        assert db.execute("SELECT sum(missing) FROM copy_parts WHERE copy_id='copy' AND item_no='bl-part'").fetchone()[0] == 5


def test_transfer_and_take_share_the_stock_arithmetic(gaps):
    path, part = gaps
    with closing(connect(path)) as db:
        w.transfer(db, 'loose-part', 'copy', 'part', part, 1)
        w.take_for_gap(db, 'copy', *PART, 1)
        assert part_missing(db, part) == 1 and stock(db)['loose-part'] == 1


def test_take_route_csrf_message_and_undo(app, gaps):
    path, part = gaps
    client, csrf, _ = client_token(app)
    data = dict(copy_id='copy', item_type='P', item_no='bl-part', color_id=11, quantity=2)
    assert client.post('/collection/save/take', json=data).status_code in (400, 403)
    with closing(connect(path)) as db:
        assert part_missing(db, part) == 3
    ok = client.post('/collection/save/take', json=dict(data, csrf_token=csrf))
    assert ok.status_code == 200 and ok.json['message'] == 'Took 2'
    with closing(connect(path)) as db:
        assert part_missing(db, part) == 1
    short = client.post('/collection/save/take', json=dict(data, csrf_token=csrf, quantity=3))
    assert short.status_code == 400 and short.json['message'] == 'Only 1 are missing'
    undone = client.post('/collection/save/undo', json=dict(csrf_token=csrf, event_id=ok.json['event_id']))
    assert undone.json['message'] == 'Undone'
    with closing(connect(path)) as db:
        assert part_missing(db, part) == 3 and stock(db)['loose-part'] == 3


def test_take_route_requires_login(app, gaps):
    response = app.test_client().post('/collection/save/take', json=dict(copy_id='copy', item_type='P', item_no='bl-part', color_id=11, quantity=1))
    assert response.status_code in (302, 401, 403)


def cards(app, can_edit=True):
    client, _, _ = client_token(app)
    soup = BeautifulSoup(client.get(URL).data, 'html.parser')
    return soup


def test_card_renders_stepper_only_when_editable_and_stock_exists(app, gaps):
    path, part = gaps
    soup = cards(app)
    box = soup.select_one('.bc-missing-card [data-bc-take]')
    assert box and box['data-max'] == '3'
    assert json.loads(box['data-identity']) == dict(copy_id='copy', item_type='P', item_no='bl-part', color_id=11)
    assert box.select_one('[data-bc-take-value]').get_text() == '3'
    assert box.select_one('[data-bc-take-go]').get_text() == 'Take 3'
    assert box.select_one('.bc-loose-stock').get_text() == '3 in loose stock'
    assert len(box.select('[data-bc-step]')) == 2 and box.select('svg')
    assert not any(c in box.get_text() for c in '-−–—')
    card = box.find_parent(class_='bc-missing-card')
    assert len(card.select('.bc-loose-stock')) == 1
    # No loose stock: no stepper and no stock text.
    with closing(connect(path)) as db, db:
        db.execute("UPDATE loose_stock SET quantity=0 WHERE item_no='bl-part'")
    soup = cards(app)
    assert soup.select_one('.bc-missing-card') and not soup.select_one('[data-bc-take]') and not soup.select_one('.bc-loose-stock')


def test_card_read_only_has_no_stepper(app, gaps, monkeypatch):
    monkeypatch.setattr('brickwork.web.views.bw_collection_editable', lambda: False)
    client, _, _ = client_token(app)
    soup = BeautifulSoup(client.get(URL).data, 'html.parser')
    card = soup.select_one('.bc-missing-card')
    assert card and not soup.select_one('[data-bc-take]')
    assert card.select_one('.bc-loose-stock').get_text() == '3 in loose stock'


def test_card_max_is_the_smaller_of_missing_and_loose_stock(app, gaps):
    path, part = gaps
    with closing(connect(path)) as db, db:
        db.execute("UPDATE loose_stock SET quantity=2 WHERE id='loose-part'")
    soup = cards(app)
    assert soup.select_one('[data-bc-take]')['data-max'] == '2'
    assert soup.select_one('[data-bc-take-go]').get_text() == 'Take 2'


def test_page_agrees_after_take(app, gaps):
    path, part = gaps
    client, csrf, _ = client_token(app)
    client.post('/collection/save/take', json=dict(csrf_token=csrf, copy_id='copy', item_type='P', item_no='bl-part', color_id=11, quantity=2))
    soup = BeautifulSoup(client.get(URL).data, 'html.parser')
    box = soup.select_one('[data-bc-take]')
    assert box['data-max'] == '1' and box.select_one('.bc-loose-stock').get_text() == '1 in loose stock'
    assert soup.select_one('[aria-label="Copy progress"] h3').get_text() == '1 parts missing, 1 in loose stock'
    client.post('/collection/save/take', json=dict(csrf_token=csrf, copy_id='copy', item_type='P', item_no='bl-part', color_id=11, quantity=1))
    soup = BeautifulSoup(client.get(URL).data, 'html.parser')
    assert not soup.select_one('[data-bc-take]') and not soup.select_one('.bc-missing-card')


def test_take_statement_count_does_not_grow_with_unused_sources(gaps):
    path, part = gaps

    runs = iter(range(100))

    def count(unused, wanted):
        tag = next(runs)
        with closing(connect(path)) as db:
            with db:
                db.execute("UPDATE loose_stock SET archived_at='2026-01-01' WHERE id!='loose-part'")
                db.execute("UPDATE loose_stock SET quantity=0 WHERE id='loose-part'")
                db.execute("UPDATE copy_parts SET missing=10,quantity=10 WHERE id=?", (part,))
                db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES(?,'P','bl-part',11,5,'U')", (f'aa-big-{tag}',))
                db.executemany("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES(?,'P','bl-part',11,1,'U')", [(f'cost-{tag}-{i}',) for i in range(unused)])
            statements = []
            db.set_trace_callback(statements.append)
            event = w.take_for_gap(db, 'copy', *PART, wanted)
            db.set_trace_callback(None)
            w.undo(db, event)
            return len(statements)
    for wanted in (1, 5):
        small, large = count(30, wanted), count(300, wanted)
        # 270 more unused source rows: the same statements (usable amounts are computed in memory).
        assert abs(large - small) <= 3, (wanted, small, large)
    one, five = count(300, 1), count(300, 5)
    assert abs(five - one) < 40  # same single source touched: no growth with quantity
    # Rows touched drive the rest: 5 of 1-unit rows is a handful of writes each.
    spread = count(300, 10)
    assert spread - one < 12 * 40


def test_take_runtime_harness():
    import shutil
    if not shutil.which('node'):
        pytest.skip('node is not installed')
    subprocess.run(['node', str(Path(__file__).with_name('toni_bw_take_runtime.cjs'))], check=True, capture_output=True, text=True)


def figure_gap(path, missing=1, rows=1):
    """The fixture copy misses its whole figure; 'loose-figure' plus extra rows of one figure each."""
    with closing(connect(path)) as db, db:
        db.execute("UPDATE copy_minifigs SET missing=? WHERE item_type='M' AND minifig_no='bl-figure'", (missing,))
        db.execute("UPDATE loose_stock SET quantity=1 WHERE id='loose-figure'")
        for n in range(rows - 1):
            db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity,condition) VALUES(?,'M','bl-figure',1,'U')", (f'loose-figure-{n}',))


def figure_box(app):
    soup = cards(app)
    card = next(c for c in soup.select('.bc-figure-row') if 'bl-figure' in c.get_text())
    return card, card.select_one('[data-bc-take]')


def figure_stock(path):
    with closing(connect(path)) as db:
        return {r[0]: r[1] for r in db.execute("SELECT id,quantity FROM loose_stock WHERE item_type='M' AND item_no='bl-figure' ORDER BY id")}


def figure_missing(path):
    with closing(connect(path)) as db:
        return db.execute("SELECT missing FROM copy_minifigs WHERE minifig_no='bl-figure'").fetchone()[0]


def test_whole_missing_figure_card_offers_take_spanning_loose_rows(app, gaps):
    path, _ = gaps
    figure_gap(path, missing=2, rows=2)
    card, box = figure_box(app)
    assert box and box['data-max'] == '2' and 'data-action' not in box.attrs
    assert json.loads(box['data-identity']) == dict(copy_id='copy', item_type='M', item_no='bl-figure', color_id=None)
    assert box.select_one('[data-bc-take-go]').get_text() == 'Take 2'
    assert box.select_one('.bc-loose-stock').get_text() == '2 in loose stock'
    assert card.select_one('.bc-check-figure').get_text() == 'Check figure parts'
    assert not any(c in box.get_text() for c in '-\u2212\u2013\u2014')


def test_figure_take_fills_both_rows_one_undo_restores_all(app, gaps):
    path, _ = gaps
    figure_gap(path, missing=2, rows=2)
    before = figure_stock(path)
    client, csrf, _ = client_token(app)
    _, box = figure_box(app)
    response = client.post('/collection/save/take', json=dict(json.loads(box['data-identity']), quantity=2, csrf_token=csrf))
    assert response.status_code == 200
    event = response.get_json()['event_id']
    assert figure_missing(path) == 0 and sorted(figure_stock(path).values()) == [0, 0]
    assert figure_box(app)[1] is None
    assert client.post('/collection/save/undo', json=dict(csrf_token=csrf, event_id=event)).status_code == 200
    assert figure_missing(path) == 2 and figure_stock(path) == before
    assert figure_box(app)[1]['data-max'] == '2'


def test_figure_take_more_than_usable_is_rejected(app, gaps):
    path, _ = gaps
    figure_gap(path, missing=2, rows=1)
    before = figure_stock(path)
    client, csrf, _ = client_token(app)
    ident = dict(copy_id='copy', item_type='M', item_no='bl-figure', color_id=None, csrf_token=csrf)
    assert client.post('/collection/save/take', json=dict(ident, quantity=2)).status_code == 400
    assert client.post('/collection/save/take', json=dict(ident, quantity=3)).status_code == 400
    assert figure_missing(path) == 2 and figure_stock(path) == before


def test_figure_take_ignores_pending_identity(app, gaps):
    path, _ = gaps
    figure_gap(path)
    with closing(connect(path)) as db, db:
        db.execute("INSERT INTO id_match(source,kind,source_id,item_type,item_no,status,evidence_json) VALUES('brickset','minifig','uncertain','M','bl-figure','to_check','{}')")
    client, csrf, _ = client_token(app)
    response = client.post('/collection/save/take', json=dict(copy_id='copy', item_type='M', item_no='bl-figure', color_id=None, quantity=1, csrf_token=csrf))
    assert response.status_code == 400 and figure_missing(path) == 1


def test_figure_card_without_loose_figure_has_no_take(app, gaps):
    path, _ = gaps
    figure_gap(path)
    with closing(connect(path)) as db, db:
        db.execute("UPDATE loose_stock SET quantity=0 WHERE id='loose-figure'")
    card, box = figure_box(app)
    assert box is None and not card.select_one('.bc-loose-stock')
    assert card.select_one('.bc-check-figure')


def test_figure_card_read_only_shows_stock_text_only(app, gaps, monkeypatch):
    path, _ = gaps
    figure_gap(path)
    monkeypatch.setattr('brickwork.web.views.bw_collection_editable', lambda: False)
    card, box = figure_box(app)
    assert box is None and card.select_one('.bc-loose-stock').get_text() == '1 in loose stock'
