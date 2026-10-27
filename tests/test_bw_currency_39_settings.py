"""#39 the Settings page's currencies and the converted saving: split out of test_bw_currency_39.py in M.8g (issue #110); still the 3.3 text,
waits for Tools & Admin (M.8i; the converted saving on the item page is checked in test_bw_retail_26.py)."""
from datetime import datetime, timezone
from contextlib import closing
import os

from bs4 import BeautifulSoup

from brickwork.core.connect import connect
from tests.test_bw_api_m1 import app  # noqa: F401
from tests.test_bw_api_m2 import populated  # noqa: F401
from tests.test_bw_collection import bw, legacy, reset_shell_metadata_after_test  # noqa: F401
from tests.web_fixtures import apps, logged_in  # noqa: F401

H = {'Authorization': 'Bearer synthetic-bootstrap'}


def test_settings_page_and_converted_saving(bw, apps, monkeypatch):
    from datetime import datetime, timezone
    from brickwork.core import retail
    from brickwork.core.sources.base import observation, property_value
    monkeypatch.setattr(retail, 'now', lambda: datetime(2026, 10, 17, tzinfo=timezone.utc))
    with closing(connect(bw)) as db:
        with db:
            observation(db, 'brickset', 'S', 'new-set', guide='retail', price='100.00', currency='EUR', region='DE', slot='retail')
            property_value(db, 'brickset', 'S', 'new-set', 'dateLastAvailable', '2027-12-31T00:00:00Z')
            db.execute("UPDATE copies SET purchase_price='93.60',purchase_currency='USD' WHERE id='copy'")
    client = logged_in(apps('toni'))
    page = BeautifulSoup(client.get('/manage/settings').data, 'html.parser')
    section = page.select_one('#currencies')
    assert section.select_one('input[name=display_currency]') and 'No rates yet' in section.get_text()
    with client.session_transaction() as session:
        token = session['bw_add_csrf']
    response = client.post('/manage/settings', data={'csrf_token': token, 'action': 'rate', 'currency': 'usd', 'per_eur': '1.17'})
    assert response.status_code == 302 and response.location.endswith('#currencies')
    page = BeautifulSoup(client.get('/manage/settings').data, 'html.parser')
    assert page.select_one('#currencies .bw-rate-code').get_text() == 'USD'
    card = BeautifulSoup(client.get('/collection/item/S/new-set?copy=copy').data, 'html.parser').select_one('.bc-retail-saving')
    assert 'Paid US$93.60 ≈ €80.00 · 20 % under retail' in ' '.join(card.get_text(' ').split()) or '≈ €80.00' in card.get_text()
    assert 'Converted at' in card['title']
