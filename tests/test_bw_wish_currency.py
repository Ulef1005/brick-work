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
    assert row.select_one('.bp-wl-max strong').text == '€100.00'
    assert row.select_one('.bp-gap').text == '€20.00 under your max'
    record = json.loads(row['data-record'])
    assert record['under'] == 'under' and record['undermax'] == '-20' and record['max'] == '100'
    assert 'no recorded currency' not in soup.get_text()
    assert [o['value'] for o in soup.select('[data-bp-filter=under] option')] == ['', 'under', 'over', 'nomax', 'differs', 'noprice']
    assert [(b['data-value'], b.get_text(strip=True)) for b in soup.select('.bp-price-filter [data-bp-pick=under]')] == [
        ('', 'All1'), ('under', 'Buy now1'), ('over', 'Wait0'), ('nomax', 'No max0'), ('differs', 'Not comparable0'), ('noprice', 'No price0')]
    assert soup.select_one('.bp-price-filter-label').text == 'State'
    assert row.select_one('.bp-wish-number .bp-state-under').text == 'Buy now'
    assert ('undermax', 'Gap to max') in [(o['value'], o.text) for o in soup.select('[data-bp-sort] option')]
    assert soup.select_one('[data-bp-sort] option').get('value') == 'state'                      # the default sort: buy now first


def test_wishlist_card_over_and_differing_currency(coll, wish, client):
    priced(coll, wish, 'EUR', '130', 'EUR')
    row = wish_page(client).select_one('[data-bp-row]')
    assert row.select_one('.bp-gap').text == '€30.00 over your max'
    assert row.select_one('.bp-state-over').text == 'Wait' and 'bp-state-under' not in row.select_one('.bp-state')['class']
    assert json.loads(row['data-record'])['under'] == 'over'
    priced(coll, wish, 'EUR', '130', 'USD')
    row = wish_page(client).select_one('[data-bp-row]')
    assert row.select_one('.bp-wl-max strong').text == '$100.00'
    assert row.select_one('.bp-gap').text == 'Max in USD, price in EUR'
    record = json.loads(row['data-record'])
    assert record['under'] == 'differs' and record['undermax'] is None
    assert row.select_one('.bp-state-differs').text == 'Not comparable'


def test_wishlist_no_max_has_the_no_max_tag(coll, wish, client):
    priced(coll, wish, 'EUR', '80', 'EUR', maximum=None)
    row = wish_page(client).select_one('[data-bp-row]')
    assert row.select_one('.bp-state-nomax').text == 'No max'
    assert row.select_one('.bp-wl-max .bp-max-none').text == 'No max set' and row.select_one('.bp-wl-max a').text == 'Set max'
    assert row.select_one('.bp-gap').text == 'No max to compare with'
    assert json.loads(row['data-record'])['under'] == 'nomax'


def test_wishlist_max_without_a_price_is_its_own_state(coll, wish, client):
    coll.sql('DELETE FROM price_current')
    coll.sql('UPDATE wish SET max_price=?,max_price_currency=?,condition=? WHERE id=?', ('100', 'EUR', 'used', wish))
    soup = wish_page(client)
    row = soup.select_one('[data-bp-row]')
    assert row.select_one('.bp-state-noprice').text == 'No price'
    assert row.select_one('.bp-wl-price').text.startswith('No sales yet') and row.select_one('.bp-gap').text == 'No sales recorded yet'
    assert json.loads(row['data-record'])['under'] == 'noprice'
    assert 'noprice' in [b['data-value'] for b in soup.select('.bp-price-filter [data-bp-pick=under]')]
    assert soup.select_one('[data-bp-pick=under][data-value=noprice] .bp-chip-count').text == '1'


def test_noprice_is_a_state_of_the_planning_row_and_not_of_the_api(coll, wish, read, client):
    """#654: a wish with a max and no price has its own state (it was None, the same as no max); the API still says nothing about it."""
    coll.sql('DELETE FROM price_current')
    coll.sql('UPDATE wish SET max_price=?,max_price_currency=? WHERE id=?', ('100', 'EUR', wish))
    with read() as db:
        row = planning.wishes(db)[0]
        assert (row['max_state'], row['max_margin'], row['wish_state']) == ('noprice', None, 'noprice')
        assert planning.max_comparison(dict(row, display_price=dict(price='5', currency=None)))[0] == 'differs'      # a price without a currency cannot be compared
        assert planning.max_comparison(dict(row, max_price=None))[0] is None                                          # no max: no state
        from brickwork.api2 import shapes
        api_rows = shapes.wish_rows(db)
        assert api_rows[0]['max_state'] == 'noprice'
        with client.application.app_context():
            assert shapes.wish_bodies(db, api_rows)[0]['under_max'] is None                                   # the API's under_max: still null, as for no max


def test_the_wishlist_lists_buy_now_first(coll, wish, client):
    """The wish added first has a max and no price (No price); the one added second is Buy now and leads the list."""
    coll.sql("UPDATE wish SET max_price=?,max_price_currency=?,condition=? WHERE id=?", ('100', 'EUR', 'used', wish))
    other = coll.add_wish(coll.local('set', 'Second', born_key='second-wish'), quantity=1, condition='used', max_price='100', currency='EUR')
    coll.price(coll.db.execute('SELECT item_id FROM wish WHERE id=?', (other,)).fetchone()[0], '80', currency='EUR', region='eu', observed=planning.now().isoformat())
    rows = wish_page(client).select('[data-bp-row]')
    assert [json.loads(r['data-record'])['id'] for r in rows] == [other, wish]
    assert [r.select_one('.bp-state').text for r in rows] == ['Buy now', 'No price']


def test_wanted_card_and_edit_form_carry_currency(coll, wish, client):
    priced(coll, wish, 'EUR', '80', 'USD')
    soup = BeautifulSoup(client.get(f'/collection/wishes/{wish}').data, 'html.parser')
    assert soup.select_one('[data-module=wanted] [data-bc-wish-limit=max_price] strong').text == '$100.00'
    assert soup.select_one('input[name=max_price_currency]')['value'] == 'USD'
    assert soup.select_one('input[name=max_price_currency]')['maxlength'] == '8'
    assert 'Currency is not stored' not in soup.get_text()
    assert 'Max in USD' in soup.select_one('.bc-wish-facts').text
    token = csrf(client)
    response = post(client, token, 'save', entity='wish', ids=[wish], values=dict(max_price='101', max_price_currency='gbp'))
    assert response.status_code == 200
    soup = BeautifulSoup(client.get(f'/collection/wishes/{wish}').data, 'html.parser')
    assert soup.select_one('[data-module=wanted] [data-bc-wish-limit=max_price] strong').text == '£101.00'
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


def test_the_wish_page_opens_with_the_answer(coll, wish, client):
    """#655, frame 62: the answer first, its state beside the condition in the hero, then Your wish and the Prices card."""
    priced(coll, wish, 'EUR', '80', 'EUR')
    soup = BeautifulSoup(client.get(f'/collection/wishes/{wish}').data, 'html.parser')
    answer = soup.select_one('[data-wish-answer]')
    assert answer.h2.text == '€20.00 under your max'
    assert answer.p.text.startswith('Used avg €80.00 · ') and answer.p.text.endswith(' · your max €100.00')
    assert answer.find_next(class_='bc-detail-layout') and answer.find_previous(class_='bc-hero-status')
    assert [t.text for t in soup.select('.bc-hero-status .bc-status')] == ['Wants used', 'Buy now']
    assert soup.select_one('.bc-hero-status .bp-state-under')
    card = soup.select_one('[data-module=wanted]')
    assert card.h2.text == 'Your wish' and not card.select('.bc-wanted-segments')
    assert card.select_one('details.bc-wish-facts summary').text == 'Wish details'               # inside the card, not a card of its own
    assert not soup.select('[data-module=prices] .bc-price-footer, [data-module=prices] [data-bc-wish-limit]')    # the max lives on Your wish only


def test_the_wish_page_states_the_gap_for_every_state(coll, wish, client):
    gaps = {}
    for state, args in {'over': ('130', 'EUR', 'EUR'), 'differs': ('130', 'EUR', 'USD')}.items():
        priced(coll, wish, args[1], args[0], args[2])
        soup = BeautifulSoup(client.get(f'/collection/wishes/{wish}').data, 'html.parser')
        gaps[state] = (soup.select_one('[data-wish-answer] h2').text, soup.select_one('.bc-hero-status .bp-state').text)
    assert gaps == {'over': ('€30.00 over your max', 'Wait'), 'differs': ('Max in USD, price in EUR', 'Not comparable')}
    priced(coll, wish, 'EUR', '80', 'EUR', maximum=None)
    soup = BeautifulSoup(client.get(f'/collection/wishes/{wish}').data, 'html.parser')
    assert soup.select_one('[data-wish-answer] h2').text == 'No max to compare with' and soup.select_one('.bc-hero-status .bp-state').text == 'No max'
    assert soup.select_one('[data-wish-answer] p').text.endswith('no max set')
    coll.sql('DELETE FROM price_current')
    coll.sql('DELETE FROM price_observation')
    coll.sql('UPDATE wish SET max_price=?,max_price_currency=? WHERE id=?', ('100', 'EUR', wish))
    soup = BeautifulSoup(client.get(f'/collection/wishes/{wish}').data, 'html.parser')
    assert soup.select_one('[data-wish-answer] h2').text == 'No sales recorded yet' and soup.select_one('.bc-hero-status .bp-state').text == 'No price'


def test_the_wish_prices_card_says_no_sales_and_one_price_in_words(coll, wish, client):
    priced(coll, wish, 'EUR', '80', 'EUR')
    soup = BeautifulSoup(client.get(f'/collection/wishes/{wish}').data, 'html.parser')
    sales = soup.select('[data-module=prices] .bc-no-sales')
    assert [s.get_text(' ', strip=True) for s in sales] == ['New No sales']                       # the condition without a price, in small type
    single = soup.select_one('[data-bc-price-single]')
    assert single and single.text.startswith('One price so far') and 'Single price point' not in soup.text and not single.select('svg')
    assert '€80.00' not in single.text                              # the amount is on the card above: the sentence does not repeat it


def test_a_list_of_sets_and_parts_counts_wishes_not_pieces(coll, world, client):
    """The heading counts wishes (rows), never pieces: five of a part is one wish."""
    coll.sql('UPDATE wish SET quantity=5')
    soup = BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser')
    rows = soup.select('[data-bp-row]')
    assert len(rows) > 1 and soup.select_one('.bp-subtitle').text.startswith(f'{len(rows)} wanted · ')
    coll.sql("UPDATE wish SET archived_at=? WHERE kind=?", ('2026-10-27T00:00:00.000Z', 'part'))
    soup = BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser')
    assert soup.select_one('.bp-subtitle').text.startswith('1 set wanted · ')


def test_an_empty_wishlist_says_so_and_drops_the_controls(coll, wish, client):
    """Frame 61: nothing on the wishlist is one sentence of what to do, not a toolbar over "Nothing here yet"."""
    coll.sql('UPDATE wish SET archived_at=? WHERE id=?', ('2026-10-27T00:00:00.000Z', wish))
    soup = wish_page(client)
    assert soup.h1.text == 'Nothing is on your wishlist yet'
    assert soup.select_one('.bp-subtitle').text.endswith('work as before.')
    assert not soup.select('[data-bp-search], .bp-price-filter, [data-bp-row]') and soup.select_one('[data-bp-empty]').has_attr('hidden')
    assert soup.select_one('.wl-lists')                                                          # the lists stay: a list can still be made


def test_a_converted_price_is_shown_marked_on_the_tile_and_the_wish_page(coll, wish, client):
    """currency.py's rule: a converted figure is always shown with the sign, the rate and its date (review of #654)."""
    from brickwork.core import currency
    coll.sql('UPDATE wish SET max_price=?,max_price_currency=?,condition=? WHERE id=?', ('5.00', 'USD', 'used', wish))
    coll.price(coll.db.execute('SELECT item_id FROM wish WHERE id=?', (wish,)).fetchone()[0], '4.00', region='eu', currency='EUR', observed=planning.now().isoformat())
    currency.set_rate(coll.db, 'USD', '1.17')
    tile = wish_page(client).select_one('[data-bp-row] .bp-gap')
    assert tile.select_one('.bp-conversion').text.startswith('Price ≈ $4.68 at 1.17')
    assert tile.text.startswith('$0.32 under your max')
    page = BeautifulSoup(client.get(f'/collection/wishes/{wish}').data, 'html.parser')
    assert page.select_one('[data-wish-answer] .bc-wish-conversion').text.startswith('Price ≈ $4.68 at 1.17')


def test_only_a_set_wish_has_a_max_with_box_and_a_figure_wish_has_the_wish_card(coll, client):
    figure = coll.item('minifigs', 'fig-000004')
    wish = coll.add_wish(figure, condition='used', max_price='9.00', currency='EUR')
    soup = BeautifulSoup(client.get(f'/collection/wishes/{wish}').data, 'html.parser')
    card = soup.select_one('[data-module=wanted]')
    assert card.h2.text == 'Your wish' and card.select_one('.bc-wanted-edit').text.strip() == 'Edit'
    assert [dt.text for dt in card.select('dl.bc-wish-kv dt')] == ['Wants', 'Filled', 'List', 'Your max'] and 'Max with box' not in soup.select_one('#bc-edit').text
    assert [t.text for t in soup.select('.bc-hero-status .bc-status')] == ['Wants used', 'No price'] and soup.select_one('[data-wish-answer]')
    assert 'Not recorded' not in card.select_one('dl.bc-wish-kv').text and 'On the wishlist' not in soup.text
    set_wish = coll.add_wish(coll.item('sets', '1000-1'), condition='used')
    assert 'Max with box' in BeautifulSoup(client.get(f'/collection/wishes/{set_wish}').data, 'html.parser').select_one('[data-module=wanted]').text


def test_the_error_state_shows_only_the_error(coll, wish, client, monkeypatch):
    monkeypatch.setattr(planning, 'wishes', lambda db: (_ for _ in ()).throw(ValueError('boom')))
    soup = wish_page(client)
    assert soup.h1.text == 'Wishlist' and 'Nothing is on your wishlist' not in soup.text and soup.select_one('[role=alert]')
    assert not soup.select_one('.bp-subtitle').text


def test_the_list_view_heads_hide_with_no_rows_and_the_tag_is_in_the_flow_on_a_phone():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    css = (root / 'static/web/toni/bw-planning-b.css').read_text()
    scope = '#bw-planning:not(#_):not(#_):not(#_)'
    assert f'{scope} .bp-wishlist[data-view=list] .bp-list-head[hidden] {{display:none}}' in css
    assert 'minmax(120px,1.1fr) minmax(96px,.8fr) minmax(88px,.8fr)' in css and 'white-space:nowrap}' not in css.split('.bp-wl-want {')[1].split('\n')[0]
    phone = css.split('@media(max-width:767.98px) {')[-1]
    assert f'{scope} .bp-wishlist[data-view=list] .bp-state {{position:static;transform:none}}' in phone and 'padding-right:112px' not in phone
    assert "head.hidden=visible.length===0" in (root / 'static/web/toni/bw-planning.js').read_text()
    assert wish_page_head_is_hidden_without_rows(root)


def wish_page_head_is_hidden_without_rows(root):
    template = (root / 'templates/web/toni/web/bw_planning.html').read_text()
    return '<div class="bp-list-head" aria-hidden="true"{% if not total %} hidden{% endif %}>' in template


def test_a_figure_wish_page_has_the_answer_then_your_wish_then_prices_and_no_wish_edit_in_status(coll, client):
    figure = coll.item('minifigs', 'fig-000004')
    wish = coll.add_wish(figure, condition='used', max_price='9.00', currency='EUR')
    soup = BeautifulSoup(client.get(f'/collection/wishes/{wish}').data, 'html.parser')
    answer, card, prices = (soup.select_one(s) for s in ('[data-wish-answer]', '[data-module=wanted]', '[data-module=prices]'))
    order = [str(n) for n in soup.find_all(True)]                                     # document order of the three blocks
    positions = [order.index(str(n)) for n in (answer, card, prices)]
    assert positions == sorted(positions) and card.find_previous_sibling(attrs={'data-module': True}) is None
    status = soup.select_one('[data-module=status]')
    assert status and not status.select('button[data-bw-open=bc-edit]')               # Status → Edit would open the wish's sheet
    assert len(soup.select('[data-module=wanted] button.bc-wanted-edit')) == 1


def test_the_phone_list_view_identity_is_a_row_of_wrapped_items():
    from pathlib import Path
    css = (Path(__file__).resolve().parents[1] / 'static/web/toni/bw-planning-b.css').read_text()
    assert '.bp-wishlist[data-view=list] .bc-identity {display:flex;flex-direction:row;flex-wrap:wrap;align-items:baseline;gap:2px 8px}' in css


def test_a_figure_wish_page_offers_no_edit_in_status_when_the_figure_is_also_in_a_set(world, coll, client):
    """Round 3 (#654): fig-000004 is owned loose and in set 1000-1 (world). On its wish page the Status card shows what is owned and offers no
    Edit at all: neither the wish's sheet nor a jump to the set copy."""
    figure = coll.item('minifigs', 'fig-000004')
    wish = coll.add_wish(figure, condition='used', max_price='9.00', currency='EUR')
    status = BeautifulSoup(client.get(f'/collection/wishes/{wish}').data, 'html.parser').select_one('[data-module=status]')
    assert status and 'in sets' in status.get_text()
    assert not status.select('button[data-bw-open=bc-edit]') and not status.select('a[title="Edit in set copy"]')


def test_edit_wish_hides_the_currency_status_and_owners_and_keeps_their_values(coll, wish, client):
    """#670: the currency fields show only for a wish stored in another currency than Settings; Status and Owners are not on Edit wish,
    and the wish's status and owner flags ride along hidden, so a save keeps them; Tags stay."""
    coll.setting('bricklink_currency', 'EUR')
    owner, status, tag = coll.flag('Alex', 'owner'), coll.flag('Sell', 'status'), coll.flag('Gift', 'tag')
    for f in (owner, status):
        coll.sql('INSERT INTO wish_flag(wish_id, flag_id) VALUES (?, ?)', (wish, f))
    soup = BeautifulSoup(client.get(f'/collection/wishes/{wish}').data, 'html.parser')
    form = soup.select_one('#bc-edit-form')
    assert form.select_one('input[name=max_price_currency]') is None and form.select_one('input[name=max_price_boxed_currency]') is None
    assert form.select_one('#bc-owners') is None and form.select_one('#bc-status-flags') is None and form.select_one('#bc-tags-label')
    assert sorted(i['value'] for i in form.select('input[type=hidden][name=flags]')) == sorted([owner, status])
    coll.sql("UPDATE wish SET max_price_currency='USD' WHERE id=?", (wish,))
    soup = BeautifulSoup(client.get(f'/collection/wishes/{wish}').data, 'html.parser')
    assert soup.select_one('#bc-edit-form input[name=max_price_currency]')['value'] == 'USD'      # another currency shows, so Not comparable is explainable
