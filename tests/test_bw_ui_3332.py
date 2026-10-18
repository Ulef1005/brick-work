"""#33 present parts inline (1d) and #32 price line and single-point state. Invented data."""
from bs4 import BeautifulSoup

from brickwork.core import admin
from tests.test_bw_collection import bw, legacy, reset_shell_metadata_after_test  # noqa: F401
from tests.web_fixtures import app, apps, logged_in  # noqa: F401


def test_inline_present_container_sits_between_missing_and_disclosure(app, bw):
    soup = BeautifulSoup(logged_in(app).get('/collection/item/S/new-set?copy=copy').data, 'html.parser')
    rows = soup.select_one('[data-bc-inventory-rows]')
    order = [c.get('data-bc-missing') is not None and 'missing' or c.get('data-bc-present-inline') is not None and 'inline'
             or c.get('data-bc-present') is not None and 'present' for c in rows.find_all(recursive=False)[:3]]
    assert order == ['missing', 'inline', 'present']


def test_sold_line_reads_count_window_age(app, bw, monkeypatch):
    from datetime import datetime, timezone
    from brickwork.core import collection_prices
    monkeypatch.setattr(collection_prices, 'now', lambda: datetime(2026, 10, 14, tzinfo=timezone.utc))
    with admin.database(bw) as db, db:
        db.execute("DELETE FROM price_current WHERE item_type='S' AND item_no='new-set'")
        db.execute("DELETE FROM price_observations WHERE item_type='S' AND item_no='new-set'")
        db.execute("""INSERT INTO price_observations(item_type,item_no,condition,guide,currency,price,min,max,sold,source,observed_at)
            VALUES('S','new-set','U','sold','EUR','8.53','6.15','11.00',7,'bricklink','2026-10-08'),
                  ('S','new-set','N','sold','EUR','35.95','35.95','35.95',1,'bricklink','2026-10-08')""")
    soup = BeautifulSoup(logged_in(app).get('/collection/item/S/new-set?copy=copy').data, 'html.parser')
    lines = [p.get_text(' ', strip=True) for p in soup.select('[data-bc-condition-prices] .bc-price p.secondary')]
    assert lines[0].startswith('7 sold · 6 months · ') and lines[1].startswith('1 sold · single price point · ')
    single = soup.select_one('[data-bc-price-single]')
    assert single and 'Single price point' in single.get_text()
