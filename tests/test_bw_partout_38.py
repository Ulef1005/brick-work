"""#38 part-out value: present parts and whole figures at the used quote, with coverage. Invented data."""
from contextlib import closing
import os

from bs4 import BeautifulSoup

from brickwork.core import partout, planning
from brickwork.core.connect import connect
from brickwork.core.sources.base import observation
from tests.test_bw_api_m1 import app  # noqa: F401
from tests.test_bw_api_m2 import populated  # noqa: F401
from tests.test_bw_collection import bw, legacy, reset_shell_metadata_after_test  # noqa: F401
from tests.web_fixtures import apps, logged_in  # noqa: F401

H = {'Authorization': 'Bearer synthetic-bootstrap'}


def store():
    return closing(connect(os.environ['BW_DB_PATH']))


def test_value_coverage_and_hint(populated):
    with store() as db:
        config = planning.configuration(db)
        with db:
            # c1: 3001 red needs 4, 2 missing → 2 present at 2.50; fig1 1 needed, 1 missing → 0 present.
            from brickwork.core.sources.base import now
            db.execute("UPDATE price_observations SET currency=?,region=?,observed_at=? WHERE item_no='3001'",
                       (config['bricklink_currency'], config['bricklink_region'], now().isoformat()))
            db.execute("UPDATE price_current SET currency=?,region=? WHERE item_no='3001'", (config['bricklink_currency'], config['bricklink_region']))
        result = partout.values(db, ['c1'])['c1']
        assert (result['value'], result['lines'], result['priced'], result['unpriced_count']) == ('5.00', 1, 1, 0)
        with db:
            db.execute("UPDATE copy_minifigs SET missing=0 WHERE copy_id='c1'")
        result = partout.values(db, ['c1'])['c1']
        assert (result['lines'], result['priced'], result['unpriced'][0]['item_no']) == (2, 1, 'fig1')
        # One of two lines priced is not enough for a total: no value, the unpriced items for a refresh.
        assert result['value'] is None and not result['enough'] and result['unpriced_items'] == [['M', 'fig1']]
        compared = partout.compare(dict(complete_quote={'price': '30'}, current_value='2.00'), result)
        assert compared['partout'] is None and compared['hint'] is None and compared['unpriced_items'] == [['M', 'fig1']]
        full = dict(result, value='5.00', enough=True)
        compared = partout.compare(dict(complete_quote={'price': '30'}, current_value='2.00'), full)
        assert compared['partout'] == '5.00' and compared['as_is'] == '2.00' and compared['complete'] == '30.00'
        assert partout.compare(dict(complete_quote=None, current_value='4.50'), full)['hint'] is None
        assert partout.values(db, []) == {}


def test_api_copy_read_has_partout(populated):
    data = populated.test_client().get('/api/v1/copies/c1', headers=H).json['data']
    assert set(data['partout']) >= {'value', 'currency', 'lines', 'priced', 'unpriced_count'}



def test_partout_on_set_detail_and_complete_sets(bw, apps, monkeypatch):
    from brickwork.core import partout as module
    monkeypatch.setattr(module, 'values', lambda db, ids: {i: dict(value='141.00', currency='EUR', lines=340, priced=312,
                                                                    unpriced=[], unpriced_count=28) for i in ids})
    monkeypatch.setattr(module, 'compare', lambda copy, value: dict(partout='141.00', currency='EUR', lines=340, priced=312,
                                                                     complete='120.00', as_is='84.00', hint='57.00'))
    client = logged_in(apps('toni'))
    card = BeautifulSoup(client.get('/collection/item/S/new-set?copy=copy').data, 'html.parser').select_one('[data-bc-partout]')
    text = ' '.join(card.get_text(' ').split())
    assert '≈ €141.00' in text and 'Complete €120.00 · as is €84.00 · prices for 312 of 340 lines' in text
    assert 'Parting out is worth €57.00 more' in text
    page = BeautifulSoup(client.get('/planning/complete-sets').data, 'html.parser')
    assert page.select_one('[data-bp-sort] option[value=partout]').get_text() == 'Part-out value'


def test_coverage_threshold():
    from brickwork.core.partout import COVERAGE
    assert COVERAGE == 0.9


def test_pending_card_offers_fetch_part_prices(bw, apps, monkeypatch):
    from brickwork.core import partout as module
    monkeypatch.setattr(module, 'compare', lambda copy, value: dict(partout=None, currency='EUR', lines=54, priced=4, hint=None,
        complete=None, as_is=None, unpriced_items=[['P', '3001'], ['P', '3004']]))
    app = apps('toni')
    app.jinja_env.globals['bw_key_missing'] = lambda source: False  # fetching prices needs a BrickLink key
    client = logged_in(app)
    card = BeautifulSoup(client.get('/collection/item/S/new-set?copy=copy').data, 'html.parser').select_one('[data-bc-partout]')
    text = ' '.join(card.get_text(' ').split())
    assert 'Not enough prices yet' in text and 'prices for 4 of 54 lines' in text and '≈' not in text
    button = card.select_one('[data-bc-fetch-prices]')
    assert button.get_text() == 'Fetch part prices' and '3004' in button['data-bc-fetch-prices']
    assert button['data-refresh-url'] == '/planning/action/refresh'
