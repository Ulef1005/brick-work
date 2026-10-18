"""#26 retail price, availability and savings from the Brickset data. Invented data."""
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


def test_status_rules_and_saving(bw, monkeypatch):
    monkeypatch.setattr(retail, 'now', lambda: datetime(2026, 10, 17, tzinfo=timezone.utc))
    with closing(connect(bw)) as db:
        seed(db)
        info = retail.lookup(db, ['new-set'])['new-set']
        assert (info['price'], info['currency'], info['country'], info['first'], info['status']) == ('79.99', 'EUR', 'DE', '2024-01-01', 'Retiring')
        with db:
            property_value(db, 'brickset', 'S', 'new-set', 'dateLastAvailable', '2026-01-01T00:00:00Z')
        assert retail.lookup(db, ['new-set'])['new-set']['status'] == 'Retired'
        with db:
            property_value(db, 'brickset', 'S', 'new-set', 'dateLastAvailable', '2028-01-01T00:00:00Z')
        assert retail.lookup(db, ['new-set'])['new-set']['status'] == 'Available'
    assert retail.saving('59.99', 'EUR', info) == dict(pct=25, under=True)
    assert retail.saving('89.99', 'EUR', info) == dict(pct=13, under=False)  # 12.5 % over
    assert retail.saving('59.99', 'USD', info) is None and retail.saving(None, 'EUR', info) is None


def test_detail_wishlist_and_statistics(app, bw, monkeypatch):
    monkeypatch.setattr(retail, 'now', lambda: datetime(2026, 10, 17, tzinfo=timezone.utc))
    with closing(connect(bw)) as db:
        seed(db)
        with db:
            db.execute("INSERT INTO copies(id,item_type,set_no,purchase_price,purchase_currency) VALUES('other','S','new-set','50','USD')")
            db.execute("INSERT OR IGNORE INTO wishlist(item_type,item_no,quantity,condition,list_id) VALUES('S','new-set',1,'any','default')")
        stats = admin.statistics(db)['spent_vs_retail']
    assert stats['totals'][0]['pct'] == 25 and stats['not_comparable'] == 1
    assert [r['label'] for r in stats['themes']] == ['Castle'] and stats['years'][0]['label'] == '2025'
    client = logged_in(app)
    card = BeautifulSoup(client.get('/collection/item/S/new-set?copy=copy').data, 'html.parser').select_one('[data-bc-retail]')
    text = ' '.join(card.get_text(' ').split())
    assert 'Retail · DE' in text and '€79.99' in text and 'Available at LEGO 2024-01 to 2026-12' in text
    assert card.select_one('[data-retail-status=retiring]') and 'Paid €59.99 · 25 % under retail' in text
    other = BeautifulSoup(client.get('/collection/item/S/new-set?copy=other').data, 'html.parser').select_one('[data-bc-retail]')
    assert 'not comparable' in other.get_text()
    wish = BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser').select_one('.bp-retail')
    assert 'Retail DE' in wish.get_text() and 'Retiring' in wish.get_text()
    stats_page = BeautifulSoup(client.get('/manage/statistics').data, 'html.parser').select_one('.bw-retail-stats')
    assert 'under' in stats_page.h2.get_text() and '1 not comparable' in stats_page.get_text()
