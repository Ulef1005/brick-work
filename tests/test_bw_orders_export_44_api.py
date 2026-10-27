"""The order export through the API, waiting for API v2 (split out of `test_bw_orders_export_44.py` by M.8h, issue #110).

The CSV itself is ported (`tests/test_bw_orders_export_44.py`); this is the `/api/v1/orders/export.csv` route, M.11's. The 3.3 text, untouched."""
from contextlib import closing
import csv
import io

from brickwork.core.connect import connect
from tests.test_bw_orders_storage import app, apps, bw, legacy, saved, client_token  # noqa: F401


def table(text):
    return list(csv.reader(io.StringIO(text)))


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
