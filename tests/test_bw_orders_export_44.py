"""#44 order export: lines and per-order summary CSV with date and store filters. Invented data."""
from contextlib import closing
import csv
import io

from bs4 import BeautifulSoup

from brickwork.core import order_exports
from brickwork.core.connect import connect
from tests.test_bw_orders_storage import app, apps, bw, legacy, saved, client_token  # noqa: F401


def table(text):
    return list(csv.reader(io.StringIO(text)))


def test_lines_summary_filters_and_page(app, bw):
    with closing(connect(bw)) as db:
        oid, _, _ = saved(db)
        with db:
            db.execute("UPDATE orders SET store='Synthetic store',date_ordered='2026-09-21T10:00:00',cost='20.00',currency='EUR' WHERE id=?", (oid,))
        lines = order_exports.rows(db, 'lines')
        summary = order_exports.rows(db, 'summary')
        assert lines and all(r['order_id'] == oid for r in lines)
        s = summary[0]
        assert s['lines'] == len(lines) and s['grand'] is not None
        assert s['other'] is None or s['other'] == s['grand'] - s['new'] - s['used']
        assert order_exports.rows(db, 'lines', date_from='2026-10-01') == []
        assert order_exports.rows(db, 'summary', store='synthetic STORE')[0]['order_id'] == oid
        try:
            order_exports.rows(db, 'lines', date_from='21.09.2026')
            raise AssertionError('bad date accepted')
        except ValueError:
            pass
    client, _, _ = client_token(app)
    page = BeautifulSoup(client.get('/workbench/orders').text, 'html.parser')
    form = page.select_one('.order-export form')
    assert form['action'] == '/workbench/orders/export.csv'
    assert [o.get_text() for o in form.select('select[name=store] option')] == ['All stores', 'Synthetic store']
    got = client.get('/workbench/orders/export.csv?kind=summary&from=2026-09-01&to=2026-09-30')
    assert got.mimetype == 'text/csv'
    rows = table(got.get_data(as_text=True))
    assert rows[0] == list(order_exports.SUMMARY) and rows[1][2] == 'Synthetic store' and rows[1][-1] == 'EUR'
    lines_csv = table(client.get('/workbench/orders/export.csv').get_data(as_text=True))
    assert lines_csv[0] == list(order_exports.LINES) and len(lines_csv) == len(lines) + 1
    assert client.get('/workbench/orders/export.csv?kind=bogus').status_code == 400


def test_api_orders_export(bw, monkeypatch):
    from flask import Flask
    from brickwork.api import register
    with closing(connect(bw)) as db:
        saved(db)
    monkeypatch.setenv('BW_API_TOKEN', 'synthetic-bootstrap')
    monkeypatch.setenv('BW_DB_PATH', str(bw))
    api = Flask(__name__)
    api.config.update(TESTING=True)
    register(api)
    c = api.test_client()
    h = {'Authorization': 'Bearer synthetic-bootstrap'}
    got = c.get('/api/v1/orders/export.csv?kind=summary', headers=h)
    assert got.status_code == 200 and got.mimetype == 'text/csv' and table(got.get_data(as_text=True))[0][0] == 'Order'
    assert c.get('/api/v1/orders/export.csv?from=bad', headers=h).status_code == 422
    assert c.get('/api/v1/orders/export.csv?page=2', headers=h).status_code == 400
