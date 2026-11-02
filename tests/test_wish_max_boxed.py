"""A wish's max price with box (#131): the pair and its rules, the API round trip, which max a quote is held against, and the price
card footer on a wish and on an owned copy. Invented data, on the fixture pair of `tests.app4`."""
from decimal import Decimal
import sqlite3

from bs4 import BeautifulSoup
import pytest

from brickwork.core import collection, planning
from brickwork.store4 import merge
from tests.api2 import call, v2, validate, write  # noqa: F401
from tests.app4 import app4, client, coll, csrf, pair, post, read, world  # noqa: F401 (fixtures)


@pytest.fixture
def wish(coll):
    """Set 1000-2 wished used, at a max of 100 EUR."""
    return coll.add_wish(coll.item('sets', '1000-2'), condition='used', max_price='100', currency='EUR')


def boxed_pair(coll, wish):
    return tuple(coll.db.execute('SELECT max_price_boxed,max_price_boxed_currency FROM wish WHERE id=?', (wish,)).fetchone())


def quotes(coll, wish, *, used=None, boxed=None, currency='EUR'):
    """The set's used sold quote and its quote with box (slot boxed), each dated now."""
    item = coll.db.execute('SELECT item_id FROM wish WHERE id=?', (wish,)).fetchone()[0]
    stamp = planning.now().isoformat()
    if used is not None:
        coll.price(item, used, currency=currency, region='eu', observed=stamp)
    if boxed is not None:
        coll.price(item, boxed, guide='valuation', slot='boxed', currency=currency, source='brickset', observed=stamp)


# ---------- the data field ----------

def test_the_schema_stores_a_max_with_box_and_its_currency_together(coll, wish):
    assert boxed_pair(coll, wish) == (None, None)
    with pytest.raises(sqlite3.IntegrityError):
        coll.sql("UPDATE wish SET max_price_boxed='120' WHERE id=?", (wish,))
    with pytest.raises(sqlite3.IntegrityError):
        coll.sql("UPDATE wish SET max_price_boxed_currency='EUR' WHERE id=?", (wish,))


def test_a_max_with_box_follows_the_max_price_rules_and_undoes(coll, wish):
    collection.save(coll.db, 'wish', [wish], dict(max_price_boxed='120'))
    assert boxed_pair(coll, wish) == ('120', 'EUR')                          # no currency: the configured one
    collection.save(coll.db, 'wish', [wish], dict(max_price_boxed='130', max_price_boxed_currency=' usd '))
    collection.save(coll.db, 'wish', [wish], dict(max_price_boxed='135'))
    assert boxed_pair(coll, wish) == ('135', 'USD')                          # a new value keeps the currency it has
    with pytest.raises(ValueError, match='Enter a max price with box of zero or more'):
        collection.save(coll.db, 'wish', [wish], dict(max_price_boxed='-1'))
    with pytest.raises(ValueError, match='Enter a max price with box or clear the currency'):
        collection.save(coll.db, 'wish', [wish], dict(max_price_boxed='', max_price_boxed_currency='EUR'))
    collection.save(coll.db, 'wish', [wish], dict(max_price_boxed=''))
    assert boxed_pair(coll, wish) == (None, None)                            # clearing the price clears its currency
    with pytest.raises(ValueError, match='Enter a price before its currency'):
        collection.save(coll.db, 'wish', [wish], dict(max_price_boxed_currency='EUR'))
    assert coll.db.execute('SELECT max_price,max_price_currency FROM wish WHERE id=?', (wish,)).fetchone()[:] == ('100', 'EUR')
    latest = collection.save(coll.db, 'wish', [wish], dict(max_price_boxed='150', max_price_boxed_currency='EUR'))
    collection.undo(coll.db, latest)                                         # its receipt restores the pair
    assert boxed_pair(coll, wish) == (None, None)


def test_an_item_merge_keeps_the_survivors_max_with_box_else_takes_the_losers(coll):
    gate, keep = coll.item('sets', '1000-2'), coll.item('sets', '1000-1')
    survivor = coll.add_wish(keep, condition='used')
    loser = coll.add_wish(gate, condition='used')
    coll.sql("UPDATE wish SET max_price_boxed='70',max_price_boxed_currency='GBP' WHERE id=?", (loser,))
    local = coll.local('set', 'Syn duplicate')
    coll.sql('UPDATE wish SET item_id=? WHERE id=?', (local, loser))
    merge.merge(coll.db, local, keep)
    assert boxed_pair(coll, survivor) == ('70', 'GBP')


# ---------- the API ----------

def test_the_api_creates_reads_and_patches_a_max_with_box(v2, world):
    created = write(v2, '/wishes', body={'item': {'kind': 'set', 'key': '1000-1'}, 'decision': 'another', 'max_price': '50.00',
                                         'max_price_currency': 'EUR', 'max_price_boxed': '65.00', 'max_price_boxed_currency': 'USD'})
    validate(created, 'post_wishes', '201')
    identifier = created.json['data']['ids'][0]
    body = call(v2, f'/wishes/{identifier}')
    validate(body, 'get_wishes_by_id')
    wish = body.json['data']
    assert (wish['max_price'], wish['max_price_currency'], wish['max_price_boxed'], wish['max_price_boxed_currency']) == ('50.00', 'EUR', '65.00', 'USD')
    patched = write(v2, f'/wishes/{identifier}', 'patch', {'max_price_boxed': '70'})
    assert patched.status_code == 200, patched.get_data(as_text=True)
    wish = call(v2, f'/wishes/{identifier}').json['data']
    assert (wish['max_price_boxed'], wish['max_price_boxed_currency']) == ('70', 'USD')
    assert write(v2, f'/wishes/{identifier}', 'patch', {'max_price_boxed': None}).status_code == 200
    wish = call(v2, f'/wishes/{identifier}').json['data']
    assert (wish['max_price_boxed'], wish['max_price_boxed_currency'], wish['under_max_boxed']) == (None, None, None)
    assert write(v2, f'/wishes/{identifier}', 'patch', {'max_price_boxed': '1,5'}).status_code == 422
    before = len(call(v2, '/wishes?limit=200').json['data'])
    lone = write(v2, '/wishes', body={'item': {'kind': 'set', 'key': '2070-1'}, 'decision': 'another', 'max_price_boxed_currency': 'EUR'})
    assert lone.status_code == 422 and len(call(v2, '/wishes?limit=200').json['data']) == before   # a currency alone: nothing added


def test_the_api_gives_the_boxed_verdict(v2, coll, world):
    coll.sql("UPDATE wish SET condition='used',max_price='40',max_price_currency='EUR',max_price_boxed='60',max_price_boxed_currency='EUR' WHERE id=?",
             (world.wish_set,))
    quotes(coll, world.wish_set, used='35', boxed='55')
    wish = call(v2, f'/wishes/{world.wish_set}').json['data']
    assert (wish['under_max'], wish['under_max_boxed']) == (True, True)
    coll.sql("UPDATE wish SET max_price_boxed='50' WHERE id=?", (world.wish_set,))
    assert call(v2, f'/wishes/{world.wish_set}').json['data']['under_max_boxed'] is False


# ---------- which max a quote is held against ----------

def test_a_boxed_quote_is_held_against_the_max_with_box_when_set(coll, wish, read):
    coll.sql("UPDATE wish SET max_price_boxed='150',max_price_boxed_currency='EUR' WHERE id=?", (wish,))
    quotes(coll, wish, used='90', boxed='140')
    with read() as db:
        row = planning.wishes(db)[0]
    assert row['boxed_price']['slot'] == 'boxed' and row['display_price'].get('slot') != 'boxed'
    assert (row['max_state'], row['max_margin']) == ('under', Decimal('10'))                # the used quote, against the max
    assert (row['max_boxed_state'], row['max_boxed_margin']) == ('under', Decimal('10'))    # the boxed quote, against the max with box


def test_a_boxed_quote_is_held_against_the_max_when_no_max_with_box_is_set(coll, wish, read):
    quotes(coll, wish, used='90', boxed='140')
    with read() as db:
        row = planning.wishes(db)[0]
    assert (row['max_boxed_state'], row['max_boxed_margin']) == ('over', Decimal('-40'))     # 140 against the max of 100


def test_the_limit_follows_the_quotes_slot():
    row = dict(max_price='100', max_price_currency='EUR', max_price_boxed='150', max_price_boxed_currency='USD')
    assert planning.max_limit(row, dict(slot='boxed')) == ('150', 'USD')
    assert planning.max_limit(row, dict(slot=None)) == ('100', 'EUR') and planning.max_limit(row, None) == ('100', 'EUR')
    assert planning.max_limit(dict(row, max_price_boxed=None, max_price_boxed_currency=None), dict(slot='boxed')) == ('100', 'EUR')
    boxed = dict(slot='boxed', price='140', currency='USD')
    assert planning.max_comparison(row, None, boxed) == ('under', Decimal('10'))
    assert planning.max_comparison(dict(row, display_price=dict(price='90', currency='USD')))[0] == 'differs'   # a quote without box: the max


def test_without_a_quote_with_box_there_is_no_boxed_verdict(coll, wish, read):
    coll.sql("UPDATE wish SET max_price_boxed='150',max_price_boxed_currency='EUR' WHERE id=?", (wish,))
    quotes(coll, wish, used='90')
    with read() as db:
        row = planning.wishes(db)[0]
    assert row['boxed_price'] is None and (row['max_boxed_state'], row['max_boxed_margin']) == (None, None) and row['max_state'] == 'under'


# ---------- the price card ----------

def page(client, url):
    response = client.get(url)
    assert response.status_code == 200
    return BeautifulSoup(response.data, 'html.parser')


def test_a_wishs_card_offers_both_maxima_as_buttons(coll, wish, client):
    soup = page(client, f'/collection/wishes/{wish}')
    footer = soup.select_one('.bc-price-footer')
    limits = {s['data-bc-wish-limit']: s for s in footer.select('[data-bc-wish-limit]')}
    assert list(limits) == ['max_price', 'max_price_boxed']
    for field, label in (('max_price', 'Your max price'), ('max_price_boxed', 'Max with box')):
        button = limits[field].select_one('button[data-bw-open=bc-edit]')
        assert button.text == label and button['data-bc-focus'] == field
        assert soup.select_one(f'#bc-edit input[name={field}]') and soup.select_one(f'#bc-edit input[name={field}_currency]')
    assert '€100.00' in limits['max_price'].text and 'not set' in limits['max_price_boxed'].text
    assert 'Set estimate' not in footer.text and not footer.select('.bc-estimate > span:not(.mono):not(.bc-estimate-label)')
    labels = [l.contents[0].strip() for l in soup.select('#bc-edit label') if l.select_one('input[name^=max_price]')]
    assert labels == ['Your max price', 'Max price currency', 'Max price with box', 'Max with box currency']


def test_a_wishs_max_with_box_saves_from_the_sheet_and_shows_on_the_card(coll, wish, client):
    token = csrf(client)
    saved = post(client, token, 'save', entity='wish', ids=[wish], values=dict(max_price_boxed='120.5', max_price_boxed_currency='gbp'))
    assert saved.status_code == 200, saved.get_data(as_text=True)
    assert boxed_pair(coll, wish) == ('120.5', 'GBP')
    footer = page(client, f'/collection/wishes/{wish}').select_one('.bc-price-footer')
    assert '£120.50' in footer.select_one('[data-bc-wish-limit=max_price_boxed]').text


def test_an_owned_copys_card_keeps_its_estimate_button(coll, client):
    keep = coll.item('sets', '1000-1')
    copy = coll.add_copy('1000-1')
    footer = page(client, f'/collection/item/{keep}?copy={copy}').select_one('.bc-price-footer')
    assert footer.select_one('button[data-bw-open=bc-edit]')['data-bc-focus'] == 'current_value'
    assert not footer.select('[data-bc-wish-limit]') and 'not set' in footer.select_one('.bc-estimate').text


def test_without_edit_rights_no_footer_label_looks_like_an_action(coll, wish, client, monkeypatch):
    monkeypatch.setattr('brickwork.web.views.bw_collection_editable', lambda: False)
    keep = coll.item('sets', '1000-1')
    copy = coll.add_copy('1000-1')
    for url in (f'/collection/wishes/{wish}', f'/collection/item/{keep}?copy={copy}'):
        footer = page(client, url).select_one('.bc-price-footer')
        assert not footer.select('button') and 'Set estimate' not in footer.text
        assert footer.select('.bc-estimate-label')                           # plain text in the secondary colour (bw-collection.css)
