"""4.8b on the 4.0 store (M.8g, issue #110): a wish maximum carries a currency; Under max compares only equal currencies.

4.0 stores the pair as one CHECK (a price has a currency and the other way round), so the 3.3 upgrade tests (a missing column, a backfill,
a concurrent upgrader, a failed read-only upgrade) and "a limit with no currency is filled on the next open" have no premise left: the
migration to 4.0 carries the pairs (`tests/test_store4_migrate.py`) and the schema refuses a lone price (the first test here)."""
from decimal import Decimal
import json
import sqlite3

from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin, collection, planning
from tests.app4 import app4, client, coll, csrf, pair, read, world, post  # noqa: F401 (fixtures)


@pytest.fixture
def wish(coll):
    """The one wish: set 1000-2 at a maximum of 0.125 EUR, priced nowhere yet."""
    return coll.add_wish(coll.item('sets', '1000-2'), condition='any', max_price='0.125', currency='EUR')


def pair_of(coll, wish):
    return tuple(coll.db.execute('SELECT max_price,max_price_currency FROM wish WHERE id=?', (wish,)).fetchone())


def test_the_schema_stores_a_price_and_its_currency_together(coll, wish):
    with pytest.raises(sqlite3.IntegrityError):
        coll.sql('UPDATE wish SET max_price=NULL WHERE id=?', (wish,))
    with pytest.raises(sqlite3.IntegrityError):
        coll.sql('UPDATE wish SET max_price_currency=NULL WHERE id=?', (wish,))


def test_save_both_fields_undo_and_audit(coll, wish):
    event = collection.save(coll.db, 'wish', [wish], dict(max_price='20', max_price_currency=' usd '))
    assert pair_of(coll, wish) == ('20', 'USD')
    ev = coll.db.execute('SELECT * FROM event WHERE id=?', (event,)).fetchone()
    old, new = json.loads(ev['old_value'])[0]['rows'][0], json.loads(ev['new_value'])[0]['rows'][0]
    assert (old['max_price'], old['max_price_currency']) == ('0.125', 'EUR')
    assert (new['max_price'], new['max_price_currency']) == ('20', 'USD') and ev['via'] == 'app'
    collection.undo(coll.db, event)
    assert pair_of(coll, wish) == ('0.125', 'EUR')


def test_max_without_currency_keeps_existing_or_configured(coll, wish):
    collection.save(coll.db, 'wish', [wish], dict(max_price='9'))
    assert pair_of(coll, wish) == ('9', 'EUR')
    coll.sql('UPDATE wish SET max_price=NULL,max_price_currency=NULL')
    coll.setting('bricklink_currency', 'GBP')
    collection.save(coll.db, 'wish', [wish], dict(max_price='9'))
    assert pair_of(coll, wish)[1] == 'GBP'
    collection.save(coll.db, 'wish', [wish], dict(max_price='10', max_price_currency='usd'))
    collection.save(coll.db, 'wish', [wish], dict(max_price='11'))
    assert pair_of(coll, wish) == ('11', 'USD')


def test_clearing_max_clears_currency_and_undo_restores(coll, wish):
    event = collection.save(coll.db, 'wish', [wish], dict(max_price='', max_price_currency=''))
    assert pair_of(coll, wish) == (None, None)
    collection.undo(coll.db, event)
    assert pair_of(coll, wish) == ('0.125', 'EUR')


@pytest.mark.parametrize('values,message', [
    (dict(max_price='5', max_price_currency='E'), '3 to 8 letters'),
    (dict(max_price='5', max_price_currency='EU1'), '3 to 8 letters'),
    (dict(max_price='5', max_price_currency='EUROPEANS'), '3 to 8 letters'),
    (dict(max_price='', max_price_currency='EUR'), 'clear the currency'),
])
def test_currency_validation(coll, wish, values, message):
    before = pair_of(coll, wish)
    with pytest.raises(ValueError, match=message):
        collection.save(coll.db, 'wish', [wish], values)
    assert pair_of(coll, wish) == before


def test_currency_alone_needs_a_max(coll, wish):
    collection.save(coll.db, 'wish', [wish], dict(max_price='', max_price_currency=''))
    with pytest.raises(ValueError, match='price before its currency'):
        collection.save(coll.db, 'wish', [wish], dict(max_price_currency='USD'))
    collection.save(coll.db, 'wish', [wish], dict(max_price='4'))
    collection.save(coll.db, 'wish', [wish], dict(max_price_currency='chf'))
    assert pair_of(coll, wish)[1] == 'CHF'


def test_clearing_only_the_currency_is_rejected_before_any_write(coll, wish):
    before = tuple(coll.db.execute('SELECT max_price,max_price_currency,updated_at FROM wish WHERE id=?', (wish,)).fetchone())
    events = coll.db.execute('SELECT count(*) FROM event').fetchone()[0]
    with pytest.raises(ValueError, match='price or clear the currency'):
        collection.save(coll.db, 'wish', [wish], {'max_price_currency': ''})
    assert tuple(coll.db.execute('SELECT max_price,max_price_currency,updated_at FROM wish WHERE id=?', (wish,)).fetchone()) == before
    assert coll.db.execute('SELECT count(*) FROM event').fetchone()[0] == events


def priced(coll, wish, currency, price, wish_currency, maximum='100'):
    """The wish at `maximum` in `wish_currency` (used), and the set's used quote of `price` in `currency`."""
    coll.sql('UPDATE wish SET max_price=?,max_price_currency=?,condition=? WHERE id=?', (maximum, wish_currency if maximum is not None else None, 'used', wish))
    item = coll.db.execute('SELECT item_id FROM wish WHERE id=?', (wish,)).fetchone()[0]
    coll.price(item, price, currency=currency, region='eu', observed=planning.now().isoformat())
    return wish


@pytest.mark.parametrize('price,state,margin', [('80', 'under', '20'), ('100', 'under', '0'), ('130', 'over', '-30')])
def test_under_max_equal_currency(coll, wish, read, price, state, margin):
    priced(coll, wish, 'EUR', price, 'EUR')
    with read() as db:
        row = planning.wishes(db)[0]
    assert row['max_state'] == state and row['max_margin'] == Decimal(margin)


@pytest.mark.parametrize('price_currency,max_currency', [('EUR', 'USD'), ('USD', 'EUR')])
def test_under_max_not_compared_across_currencies(coll, wish, read, price_currency, max_currency):
    priced(coll, wish, price_currency, '5', max_currency)
    with read() as db:
        row = planning.wishes(db)[0]
    assert row['max_state'] == 'differs' and row['max_margin'] is None


def test_under_max_none_without_max_price(coll, wish, read):
    priced(coll, wish, 'EUR', '5', 'EUR', maximum=None)
    with read() as db:
        assert planning.wishes(db)[0]['max_state'] is None


def wish_page(client, screen='wishlist'):
    return BeautifulSoup(client.get('/planning/' + screen).data, 'html.parser')


def test_wishlist_card_shows_currency_and_under_max(coll, wish, client):
    priced(coll, wish, 'EUR', '80', 'EUR')
    soup = wish_page(client)
    row = soup.select_one('[data-bp-row]')
    assert row.select_one('.bp-max strong').text == '€100.00'
    assert '€20.00 under max' in row.select_one('.bp-max-diff').text
    record = json.loads(row['data-record'])
    assert record['under'] == 'under' and record['undermax'] == '-20' and record['max'] == '100'
    assert not row.select('.bp-max-note')
    assert 'no recorded currency' not in soup.get_text()
    assert [o['value'] for o in soup.select('[data-bp-filter=under] option')] == ['', 'under', 'over', 'nomax', 'differs']
    assert [(b['data-value'], b.text) for b in soup.select('.bp-price-filter [data-bp-pick=under]')] == [('under', 'Under max'), ('over', 'Over max'), ('nomax', 'No max set'), ('differs', 'Not comparable')]
    assert soup.select_one('.bp-price-filter-label').text == 'Price filter'
    assert not soup.select('.bp-price-note')
    assert row.select_one('.bp-verdict').text == 'Under max'
    assert ('undermax', 'Under max') in [(o['value'], o.text) for o in soup.select('[data-bp-sort] option')]


def test_wishlist_card_over_and_differing_currency(coll, wish, client):
    priced(coll, wish, 'EUR', '130', 'EUR')
    row = wish_page(client).select_one('[data-bp-row]')
    assert '€30.00 over max' in row.select_one('.bp-max-diff').text
    assert row.select_one('.bp-verdict.over').text == 'Over max'
    assert json.loads(row['data-record'])['under'] == 'over'
    priced(coll, wish, 'EUR', '130', 'USD')
    row = wish_page(client).select_one('[data-bp-row]')
    assert row.select_one('.bp-max strong').text == '$100.00'
    assert row.select_one('.bp-max-note').text == 'Max in USD, price in EUR'
    assert not row.select('.bp-max-diff')
    record = json.loads(row['data-record'])
    assert record['under'] == 'differs' and record['undermax'] is None
    assert row.select_one('.bp-verdict.differs').text == 'Not comparable'
    assert 'No verdict is given' in wish_page(client).select_one('.bp-price-note').text


def test_wishlist_no_max_has_no_verdict(coll, wish, client):
    priced(coll, wish, 'EUR', '80', 'EUR', maximum=None)
    row = wish_page(client).select_one('[data-bp-row]')
    assert not row.select('.bp-verdict')
    assert json.loads(row['data-record'])['under'] == 'nomax'


def test_wishlist_max_without_comparable_price_has_no_verdict(coll, wish, client):
    coll.sql('DELETE FROM price_current')
    coll.sql('UPDATE wish SET max_price=?,max_price_currency=?,condition=? WHERE id=?', ('100', 'EUR', 'used', wish))
    soup = wish_page(client)
    row = soup.select_one('[data-bp-row]')
    assert not row.select('.bp-verdict')
    assert not row.select('.bp-max-note')
    assert json.loads(row['data-record'])['under'] == 'noprice'
    assert 'noprice' not in [b['data-value'] for b in soup.select('.bp-price-filter [data-bp-pick=under]')]
    assert not soup.select('.bp-price-note')


def test_wanted_card_and_edit_form_carry_currency(coll, wish, client):
    priced(coll, wish, 'EUR', '80', 'USD')
    soup = BeautifulSoup(client.get(f'/collection/wishes/{wish}').data, 'html.parser')
    assert soup.select_one('.bc-wanted-max strong').text == '$100.00'
    assert soup.select_one('input[name=max_price_currency]')['value'] == 'USD'
    assert soup.select_one('input[name=max_price_currency]')['maxlength'] == '8'
    assert 'Currency is not stored' not in soup.get_text()
    assert 'Max in USD' in soup.select_one('.bc-wish-facts').text
    token = csrf(client)
    response = post(client, token, 'save', entity='wish', ids=[wish], values=dict(max_price='101', max_price_currency='gbp'))
    assert response.status_code == 200
    soup = BeautifulSoup(client.get(f'/collection/wishes/{wish}').data, 'html.parser')
    assert soup.select_one('.bc-wanted-max strong').text == '£101.00'
    bad = post(client, token, 'save', entity='wish', ids=[wish], values=dict(max_price='5', max_price_currency='1'))
    assert bad.status_code == 400 and '3 to 8 letters' in bad.json['message']
    assert post(client, token, 'undo', event_id=response.json['event_id']).status_code == 200
    assert pair_of(coll, wish) == ('100', 'USD')


def test_wishlist_queries_constant(coll, wish, client, monkeypatch):
    priced(coll, wish, 'EUR', '80', 'EUR')
    original = admin.connect
    statements = []

    def traced(*args, **kwargs):
        db = original(*args, **kwargs)
        db.set_trace_callback(statements.append)
        return db
    monkeypatch.setattr(admin, 'connect', traced)

    def count():
        statements.clear()
        assert client.get('/planning/wishlist').status_code == 200
        return len([s for s in statements if s.lstrip().upper().startswith('SELECT')])

    def bulk(start, stop):
        for i in range(start, stop):
            item = coll.local('set', f'Bulk {i}', born_key=f'cur-bulk-{i}')
            coll.add_wish(item, max_price='50', currency='USD' if i % 2 else 'EUR')
            coll.price(item, '40', currency='EUR', region='eu', observed=planning.now().isoformat())
    bulk(0, 5)
    small = count()
    bulk(5, 45)
    assert count() <= small + 2
