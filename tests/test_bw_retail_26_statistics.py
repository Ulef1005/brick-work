"""#26 retail on the Statistics screen: split out of test_bw_retail_26.py by M.8f, waiting for the maintenance screens (M.8i).

3.3 form; M.8i rewrites it on the 4.0 store when it ports Statistics (the figures themselves, `core.retail.spent_vs_retail`, are tested in
test_bw_retail_26.py)."""
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


def test_statistics_page(app, bw, monkeypatch):
    monkeypatch.setattr(retail, 'now', lambda: datetime(2026, 10, 17, tzinfo=timezone.utc))
    with closing(connect(bw)) as db:
        seed(db)
        with db:
            db.execute("INSERT INTO copies(id,item_type,set_no,purchase_price,purchase_currency) VALUES('other','S','new-set','50','USD')")
        stats = admin.statistics(db)['spent_vs_retail']
    assert stats['totals'][0]['pct'] == 25 and stats['not_comparable'] == 1
    client = logged_in(app)
    stats_page = BeautifulSoup(client.get('/manage/statistics').data, 'html.parser').select_one('.bw-retail-stats')
    assert 'under' in stats_page.h2.get_text() and '1 not comparable' in stats_page.get_text()
