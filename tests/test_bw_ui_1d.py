"""#33 present parts inline (1d) and #32 price line and single-point state. Invented data, on a 4.0 collection (M.8b, issue #110)."""
from bs4 import BeautifulSoup

from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401  (fixtures)


def test_inline_present_container_sits_between_missing_and_disclosure(coll, client):
    copy = coll.add_copy('1000-1')
    soup = BeautifulSoup(client.get(f'/collection/item/{coll.item("sets", "1000-1")}?copy={copy}').data, 'html.parser')
    rows = soup.select_one('[data-bc-inventory-rows]')
    order = [c.get('data-bc-missing') is not None and 'missing' or c.get('data-bc-present-inline') is not None and 'inline'
             or c.get('data-bc-present') is not None and 'present' for c in rows.find_all(recursive=False)[:3]]
    assert order == ['missing', 'inline', 'present']


def test_sold_line_reads_count_window_age(coll, client, monkeypatch):
    from datetime import datetime, timezone
    from brickwork.core import collection_prices
    monkeypatch.setattr(collection_prices, 'now', lambda: datetime(2026, 10, 14, tzinfo=timezone.utc))
    copy = coll.add_copy('1000-1')
    keep = coll.item('sets', '1000-1')
    coll.price(keep, '8.53', condition='used', guide='sold', minimum='6.15', maximum='11.00', sold=7, observed='2026-10-08')
    coll.price(keep, '35.95', condition='new', guide='sold', minimum='35.95', maximum='35.95', sold=1, observed='2026-10-08')
    soup = BeautifulSoup(client.get(f'/collection/item/{keep}?copy={copy}').data, 'html.parser')
    lines = [p.get_text(' ', strip=True) for p in soup.select('[data-bc-condition-prices] .bc-price p.secondary')]
    assert lines[0].startswith('7 sold · 6 months · ') and lines[1].startswith('1 sold · single price point · ')
    single = soup.select_one('[data-bc-price-single]')
    assert single and 'Single price point' in single.get_text()
