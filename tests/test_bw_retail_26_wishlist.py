"""#26 retail on the Wishlist screen: split out of test_bw_retail_26.py by M.8f, waiting for the planning screens (M.8g).

3.3 form; M.8g rewrites it on the 4.0 store when it ports the Wishlist (the retail core, `core.retail.lookup`, is tested in test_bw_retail_26.py)."""
from contextlib import closing
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from brickwork.core import admin, retail
from brickwork.core.connect import connect
from brickwork.core.sources.base import observation, property_value
from tests.test_bw_collection import bw, legacy, reset_shell_metadata_after_test  # noqa: F401
from tests.web_fixtures import app, apps, logged_in  # noqa: F401


def seed(db, last='2026-12-31', price='79.99', currency='EUR', paid='59.99', paid_currency='EUR'):
    with db:
        observation(db, 'brickset', 'S', 'new-set', guide='retail', price=price, currency=currency, region='DE', slot='retail')
        property_value(db, 'brickset', 'S', 'new-set', 'dateFirstAvailable', '2024-01-01T00:00:00Z')
        property_value(db, 'brickset', 'S', 'new-set', 'dateLastAvailable', last + 'T00:00:00Z')
        property_value(db, 'brickset', 'S', 'new-set', 'theme', 'Castle')
        db.execute("UPDATE copies SET purchase_price=?,purchase_currency=?,purchase_date='2025-03-01' WHERE id='copy'", (paid, paid_currency))


def test_wishlist_retail_line(app, bw, monkeypatch):
    monkeypatch.setattr(retail, 'now', lambda: datetime(2026, 10, 17, tzinfo=timezone.utc))
    with closing(connect(bw)) as db:
        seed(db)
        with db:
            db.execute("INSERT OR IGNORE INTO wishlist(item_type,item_no,quantity,condition,list_id) VALUES('S','new-set',1,'any','default')")
    client = logged_in(app)
    wish = BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser').select_one('.bp-retail')
    assert 'Retail DE' in wish.get_text() and 'Retiring' in wish.get_text()
