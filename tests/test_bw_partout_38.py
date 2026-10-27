"""#38 part-out value on the 4.0 store (M.8g, issue #110): present parts and whole figures at the used quote, with coverage. Invented data.

The API's copy read (M.11) is in test_bw_partout_38_api.py, which waits for it."""
from decimal import Decimal

from bs4 import BeautifulSoup

from brickwork.core import partout
from brickwork.core.sources.base import now
from tests.app4 import STAMP, app4, client, coll, pair, read, world  # noqa: F401 (fixtures)


def quote(coll, item, value, *, colour=None):
    coll.price(item, value, colour=colour, region='eu', currency='EUR', observed=now().isoformat())


def small_copy(coll):
    """A copy with one set line (3001 red: 4, 2 missing) and one figure line (1 of 1 missing), nothing else."""
    brick, red, figure = coll.item('parts', '3001'), coll.colour('4'), coll.item('minifigs', 'fig-000004')
    keep = coll.project(coll.item('sets', '1000-1'))
    coll.project(brick), coll.project(figure)
    coll.setting('bricklink_region', 'eu')
    coll.setting('bricklink_currency', 'EUR')
    coll.sql("INSERT INTO copy(id,item_id,inventory_source,inventory_digest,condition,created_at,updated_at) VALUES('c1',?,'migrated','d','used',?,?)",
             (keep, STAMP, STAMP))
    coll.sql('INSERT INTO copy_part(copy_id,item_id,color_id,quantity,missing) VALUES(?,?,?,4,2)', ('c1', brick, red))
    coll.sql("INSERT INTO copy_figure(copy_id,item_id,inventory_source,inventory_digest,quantity,missing,updated_at) VALUES('c1',?,'none','d',1,1,?)", (figure, STAMP))
    return brick, red, figure


def test_value_coverage_and_hint(coll, read):
    brick, red, figure = small_copy(coll)
    quote(coll, brick, '2.50', colour=red)
    with read() as db:
        # 3001 red needs 4, 2 missing -> 2 present at 2.50; the figure is needed once and missing: 0 present, so no line.
        result = partout.values(db, ['c1'])['c1']
    assert (result['value'], result['lines'], result['priced'], result['unpriced_count']) == ('5.00', 1, 1, 0)
    coll.sql('UPDATE copy_figure SET missing=0')
    with read() as db:
        result = partout.values(db, ['c1'])['c1']
        assert (result['lines'], result['priced'], result['unpriced'][0]) == (2, 1, dict(item_id=figure, color_id=None))
        # One of two lines priced is not enough for a total: no value, the unpriced items for a refresh.
        assert result['value'] is None and not result['enough'] and result['unpriced_items'] == [figure]
        compared = partout.compare(dict(complete_quote={'price': '30'}, current_value='2.00'), result)
        assert compared['partout'] is None and compared['hint'] is None and compared['unpriced_items'] == [figure]
        full = dict(result, value='5.00', enough=True)
        compared = partout.compare(dict(complete_quote={'price': '30'}, current_value='2.00'), full)
        assert compared['partout'] == '5.00' and compared['as_is'] == '2.00' and compared['complete'] == '30.00' and compared['hint'] is None     # 3.00 more is under the 5.00 floor
        assert partout.compare(dict(complete_quote={'price': '30'}, current_value='2.00'), dict(full, value='9.00'))['hint'] == '7.00'
        assert partout.compare(dict(complete_quote=None, current_value='4.50'), full)['hint'] is None
        assert partout.values(db, []) == {}


def test_a_total_when_every_line_is_priced_and_what_counts(coll, read):
    brick, red, figure = small_copy(coll)
    coll.sql('UPDATE copy_figure SET missing=0')
    plate, white = coll.item('parts', '3023'), coll.colour('15')
    coll.project(plate)
    coll.sql('INSERT INTO copy_part(copy_id,item_id,color_id,quantity,missing) VALUES(?,?,?,2,0)', ('c1', plate, white))
    coll.sql('INSERT INTO copy_part(copy_id,item_id,color_id,quantity,missing,is_spare) VALUES(?,?,?,9,0,1)', ('c1', plate, coll.colour('4')))      # a spare is no line
    coll.sql("UPDATE copy_part SET retired_at=? WHERE copy_id='c1' AND color_id=?", (STAMP, white))                                              # a retired line is no line
    coll.sql('INSERT INTO copy_part(copy_id,item_id,color_id,quantity,missing) VALUES(?,?,?,1,0)', ('c1', plate, coll.colour('14')))
    quote(coll, brick, '2.50', colour=red)
    quote(coll, figure, '8.00')
    quote(coll, plate, '0.10', colour=coll.colour('14'))
    with read() as db:
        result = partout.values(db, ['c1'])['c1']
    assert (result['lines'], result['priced'], result['enough']) == (3, 3, True)
    assert Decimal(result['value']) == Decimal('2.50') * 2 + Decimal('8.00') + Decimal('0.10')
    assert result['currency'] == 'EUR'


def test_a_stale_or_foreign_quote_does_not_price_a_line(coll, read):
    brick, red, figure = small_copy(coll)
    coll.sql('UPDATE copy_figure SET missing=0')
    coll.price(brick, '2.50', colour=red, region='eu', currency='USD', observed=now().isoformat())
    coll.price(figure, '8.00', region='eu', currency='EUR', observed='2026-01-01T00:00:00+00:00')
    with read() as db:
        result = partout.values(db, ['c1'])['c1']
    assert result['priced'] == 0 and result['unpriced_count'] == 2


def test_coverage_threshold():
    assert partout.COVERAGE == 0.9


def test_partout_on_set_detail_and_complete_sets(world, client, monkeypatch):
    monkeypatch.setattr(partout, 'values', lambda db, ids: {i: dict(value='141.00', currency='EUR', lines=340, priced=312,
                                                                     unpriced=[], unpriced_count=28) for i in ids})
    monkeypatch.setattr(partout, 'compare', lambda copy, value: dict(partout='141.00', currency='EUR', lines=340, priced=312,
                                                                      complete='120.00', as_is='84.00', hint='57.00'))
    card = BeautifulSoup(client.get(f'/collection/item/{world.keep}?copy={world.copy_a}').data, 'html.parser').select_one('[data-bc-partout]')
    text = ' '.join(card.get_text(' ').split())
    assert '≈ €141.00' in text and 'Complete €120.00 · as is €84.00 · prices for 312 of 340 lines' in text
    assert 'Parting out is worth €57.00 more' in text
    page = BeautifulSoup(client.get('/planning/complete-sets').data, 'html.parser')
    assert page.select_one('[data-bp-sort] option[value=partout]').get_text() == 'Part-out value'


def test_partout_card_from_the_stored_prices_on_the_item_page(coll, client):
    brick, red, figure = small_copy(coll)
    coll.sql('UPDATE copy_figure SET missing=0')
    quote(coll, brick, '2.50', colour=red)
    quote(coll, figure, '8.00')
    quote(coll, coll.item('sets', '1000-1'), '100.00')
    page = BeautifulSoup(client.get(f'/collection/item/{coll.item("sets", "1000-1")}?copy=c1').data, 'html.parser')
    text = ' '.join(page.select_one('[data-bc-partout]').get_text(' ').split())
    assert '≈ €13.00' in text and 'prices for 2 of 2 lines' in text and 'Complete €100.00' in text
    assert 'Parting out is worth' not in text                                               # 13 is far below the 70 the copy is worth as is


def test_pending_card_offers_fetch_part_prices(world, client, app4, monkeypatch):
    monkeypatch.setattr(partout, 'compare', lambda copy, value: dict(partout=None, currency='EUR', lines=54, priced=4, hint=None,
                                                                      complete=None, as_is=None, unpriced_items=[world.brick, world.plate]))
    app4.jinja_env.globals['bw_key_missing'] = lambda source: False  # fetching prices needs a BrickLink key
    card = BeautifulSoup(client.get(f'/collection/item/{world.keep}?copy={world.copy_a}').data, 'html.parser').select_one('[data-bc-partout]')
    text = ' '.join(card.get_text(' ').split())
    assert 'Not enough prices yet' in text and 'prices for 4 of 54 lines' in text and '≈' not in text
    button = card.select_one('[data-bc-fetch-prices]')
    assert button.get_text() == 'Fetch part prices' and button['data-bc-fetch-prices'] == f'[{world.brick}, {world.plate}]'
    assert button['data-refresh-url'] == '/planning/action/refresh'
