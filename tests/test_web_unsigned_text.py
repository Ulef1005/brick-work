"""4.6r: every migrated screen uses words for visible numeric differences: the planning and prices tests that wait for M.8f/M.8g.

The ported screens are checked in `test_ported_screens_text.py` (M.8e moved the Workbench, Storage and printable-list routes there, and the
picker destination rows into test_bw_workbench_ui.py); each piece adds its routes there when it ports its screens. What is left here is the
3.3 text of the prices and planning tests; the file waits for M.8g (prices: M.8f)."""
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote

from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin
from brickwork.web.formatting import difference, money, nowrap_tail, ratio
from tests.test_bw_add import app, apps, bw, legacy, logged_in
from tests.test_bw_admin import reset_shell_metadata_after_test
from tests.test_bw_planning import evidence

SIGN = re.compile(r'(?:^|[\s(\[·])[-−–—]\d')


def assert_unsigned(html, route):
    soup = BeautifulSoup(html, 'html.parser')
    assert soup.select_one('[data-web-ui="toni"]'), route
    for node in soup.find_all(string=True):
        if node.parent.name in ('script', 'style'):
            continue
        assert not SIGN.search(str(node)), (route, str(node))
        assert not re.search(r'\d[–—−]\d', str(node)), (route, str(node))
    for node in soup.find_all(True):
        attributes = ['aria-label', 'title', 'alt', 'placeholder']
        if node.name == 'button' or (node.name == 'input' and node.get('type') in ('button', 'submit')):
            attributes.append('value')
        for attr in attributes:
            text = node.get(attr, '')
            assert not SIGN.search(text), (route, attr, text)
            assert not re.search(r'\d[–—−]\d', text), (route, attr, text)
    return soup


def test_prices_name_tail(app, bw):
    # Names are rendered by bw-prices.js from the records; the runtime harness asserts the non-breaking tail on its row markup.
    data = logged_in(app).get('/planning/prices/records').get_json()
    assert any(len(r[data['fields'].index('name')].split()) > 1 for r in data['rows'])


def test_planning_negative_ratio_and_gain_phrases(app, bw):
    with admin.database(bw) as db:
        evidence(db)
        with db:
            db.execute("UPDATE copies SET current_value='102',current_value_currency='EUR' WHERE id='copy'")
    soup = assert_unsigned(logged_in(app).get('/planning/complete-sets').text, 'negative ratio')
    row = soup.select_one('[data-bp-row]')
    assert '0.15 lost per 1 spent' in row.get_text()
    assert 'net gain €15.50 below' in row.select_one('summary').get_text()
    details = row.select_one('.bp-repair-details').get_text()
    assert 'repair €13.50 · net gain €15.50 below' in details

