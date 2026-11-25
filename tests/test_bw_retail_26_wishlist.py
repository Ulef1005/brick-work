"""#26 retail on the Wishlist screen, on the 4.0 store (M.8g, issue #110). The retail core, `core.retail.lookup`, is tested in
test_bw_retail_26.py. Invented data."""
from datetime import datetime, timezone

from bs4 import BeautifulSoup
import pytest

from brickwork.core import planning, retail
from brickwork.core.sources.base import observation, property_value
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401 (fixtures)


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(retail, 'now', lambda: datetime(2026, 10, 17, tzinfo=timezone.utc))


def seed(coll, last='2026-12-31', price='79.99'):
    keep = coll.project(coll.item('sets', '1000-1'))
    observation(coll.db, 'brickset', keep, guide='retail', price=price, currency='EUR', region='DE', slot='retail')
    property_value(coll.db, 'brickset', keep, 'dateFirstAvailable', '2024-01-01T00:00:00Z')
    property_value(coll.db, 'brickset', keep, 'dateLastAvailable', last + 'T00:00:00Z')
    coll.db.commit()
    return keep


def test_wishlist_tile_has_no_retail_line(coll, client):
    """#654: the Wishlist tile answers "can I buy this now at a price I accept"; the retail line left it (the set page keeps it)."""
    keep = seed(coll)
    wish = coll.add_wish(keep, quantity=1, condition='any')
    page = client.get('/planning/wishlist').data.decode()
    assert 'bp-retail' not in page and 'Retail DE' not in page
    detail = BeautifulSoup(client.get(f'/collection/wishes/{wish}').data, 'html.parser')
    assert 'Retail' in detail.select_one('[data-bc-retail]').text and 'Retiring' in detail.select_one('[data-bc-retail]').text


def test_only_a_set_has_a_retail_line_and_a_missing_price_says_so(coll, read):
    keep = seed(coll)
    coll.add_wish(keep, quantity=1)
    coll.add_wish(coll.item('parts', '3001'), colour=coll.colour('4'), quantity=1)
    with read() as db:
        rows = {r['kind']: r for r in planning.wishes(db)}
    assert rows['set']['retail']['status'] == 'Retiring' and rows['part']['retail'] is None
