"""#44 order export: lines and per-order summary CSV with date and store filters, on the 4.0 store (M.8h, issue #110). Invented data.

The API route of the 3.3 file (`/api/v1/orders/export.csv`) is M.11's."""
import csv
import io

from bs4 import BeautifulSoup
import pytest

from brickwork.core import order_exports
from tests.app4 import app4, client, coll, csrf, pair, read, world  # noqa: F401 (fixtures)
from tests.test_bw_orders_storage import XML, inventory, line_of, saved


def table(text):
    return list(csv.reader(io.StringIO(text)))


def test_lines_summary_filters_and_page(world, client, coll):
    db = coll.db
    oid, _, _ = saved(db, inventory(line_of('P', '3001', colour=5, qty=3, price='0.12'), line_of('M', 'syn-fig-0004', qty=1, condition='N', price='2.00')))
    coll.sql("UPDATE purchase_order SET store='Synthetic store',date_ordered='2026-09-21T10:00:00',cost='20.00',currency='EUR' WHERE id=?", (oid,))
    lines = order_exports.rows(db, 'lines')
    summary = order_exports.rows(db, 'summary')
    assert [(r['item_type'], r['item_no'], r['color_key'], r['colour'], r['condition']) for r in lines] == [('P', '3001', '5', 'Red', 'used'), ('M', 'syn-fig-0004', None, None, 'new')]
    assert all(r['order_id'] == oid for r in lines)
    s = summary[0]
    assert s['lines'] == len(lines) and s['grand'] is not None
    assert str(s['used']) == '0.36' and str(s['new']) == '2.00' and str(s['other']) == '17.64'
    assert order_exports.rows(db, 'lines', date_from='2026-10-01') == []
    assert order_exports.rows(db, 'summary', store='synthetic STORE')[0]['order_id'] == oid
    with pytest.raises(ValueError):
        order_exports.rows(db, 'lines', date_from='21.09.2026')
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
    assert lines_csv[1][4:10] == ['P', '3001', lines_csv[1][6], 'Red', '5', 'Used'] and lines_csv[2][9] == 'New'
    assert client.get('/workbench/orders/export.csv?kind=bogus').status_code == 400


def test_a_total_without_prices_leaves_other_costs_empty(world, coll):
    db = coll.db
    oid, _, _ = saved(db, XML.replace('<PRICE>0.12</PRICE>', ''))
    coll.sql("UPDATE purchase_order SET cost='5.00',currency='EUR' WHERE id=?", (oid,))
    s = order_exports.rows(db, 'summary')[0]
    assert s['other'] is None and str(s['grand']) == '5.00'
    assert table(order_exports.to_csv('summary', [s]))[1][9] == ''
