"""#26 retail on the Statistics screen, on the 4.0 store (M.8i part 1, issue #110). Invented data.

Split out of test_bw_retail_26.py by M.8f; the figures themselves (`core.retail.spent_vs_retail`) are tested in test_bw_retail_26.py."""
from datetime import datetime, timezone

from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin, retail
from brickwork.core.sources.base import observation, property_value
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401  (the fixtures)

TODAY = datetime(2026, 10, 17, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(retail, 'now', lambda: TODAY)


def seed(coll, last='2026-12-31', price='79.99', currency='EUR', paid='59.99', paid_currency='EUR'):
    """Retail data for the fixture set `1000-1` and one copy of it with a price paid."""
    keep = coll.item('sets', '1000-1')
    coll.project(keep)
    observation(coll.db, 'brickset', keep, guide='retail', price=price, currency=currency, region='DE', slot='retail')
    property_value(coll.db, 'brickset', keep, 'dateFirstAvailable', '2024-01-01T00:00:00Z')
    property_value(coll.db, 'brickset', keep, 'dateLastAvailable', last + 'T00:00:00Z')
    property_value(coll.db, 'brickset', keep, 'theme', 'Castle')
    coll.db.commit()
    return keep, coll.add_copy('1000-1', condition='used', price=paid, currency=paid_currency, date='2025-03-01')


def test_statistics_page(coll, client):
    seed(coll)
    coll.add_copy('1000-1', condition='used', price='50', currency='USD')
    stats = admin.statistics(coll.db)['spent_vs_retail']
    assert stats['totals'][0]['pct'] == 25 and stats['not_comparable'] == 1
    stats_page = BeautifulSoup(client.get('/manage/statistics').data, 'html.parser').select_one('.bw-retail-stats')
    assert 'under' in stats_page.h2.get_text() and '1 not comparable' in stats_page.get_text()


def test_the_statistics_count_live_copies_by_completeness_theme_storage_and_place(coll, world, client):
    stats = admin.statistics(coll.db)
    assert {r['label']: r['count'] for r in stats['completeness']} == {'Complete': 1, 'Incomplete': 1, 'Sealed': 1}
    assert {r['label']: r['count'] for r in stats['theme']} == {'Castle': 2, 'Rattles': 1}              # the catalogue's theme, Brickset's when it has one
    coll.db.execute("INSERT INTO item_property(item_id,key,source,value,fetched_at) VALUES(?,'theme','brickset','Medieval','2026-10-01T00:00:00.000Z')", (world.keep,))
    coll.db.execute("UPDATE copy SET completeness=NULL WHERE id=?", (world.copy_c,))
    coll.db.execute("UPDATE copy SET archived_at='2026-10-02T00:00:00.000Z' WHERE id=?", (world.copy_b,))                # an archived copy is not counted
    coll.db.commit()
    stats = admin.statistics(coll.db)
    assert {r['label']: r['count'] for r in stats['theme']} == {'Medieval': 1, 'Rattles': 1}
    assert {r['label']: r['count'] for r in stats['completeness']} == {'Incomplete': 1, 'Not checked': 1}
    assert {r['label']: r['count'] for r in stats['storage']} == {'Shelf A': 1, 'Not recorded': 1}
    assert {r['label']: r['count'] for r in stats['purchase place']} == {'Shop': 1, 'Not recorded': 1}
    assert '1 of 2 copies are incomplete' in client.get('/manage/statistics').get_data(as_text=True)
