"""#39 exchange rates and display currency through the API: split out of test_bw_currency_39.py in M.8g (issue #110); still the 3.3 text,
waits for API v2 (M.11)."""
from contextlib import closing
import os

from bs4 import BeautifulSoup

from brickwork.core.connect import connect
from tests.test_bw_api_m1 import app  # noqa: F401
from tests.test_bw_api_m2 import populated  # noqa: F401
from tests.test_bw_collection import bw, legacy, reset_shell_metadata_after_test  # noqa: F401
from tests.web_fixtures import apps, logged_in  # noqa: F401

H = {'Authorization': 'Bearer synthetic-bootstrap'}


def test_api_rates_and_settings(populated):
    c = populated.test_client()
    put = c.put('/api/v1/exchange-rates/usd', json={'per_eur': '1.17'}, headers=dict(H, **{'Idempotency-Key': 'fx-1'}))
    assert put.status_code == 200, put.json
    listed = c.get('/api/v1/exchange-rates', headers=H).json
    assert listed['data'][0]['currency'] == 'USD' and listed['display_currency']
    patched = c.patch('/api/v1/settings', json={'display_currency': 'USD'}, headers=dict(H, **{'Idempotency-Key': 'fx-2'}))
    assert patched.status_code == 200 and patched.json['data']['display_currency'] == 'USD'
    assert c.put('/api/v1/exchange-rates/EUR', json={'per_eur': '1'}, headers=dict(H, **{'Idempotency-Key': 'fx-3'})).status_code == 422
