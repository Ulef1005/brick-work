"""#50 Manage and Workbench leftovers and #49 12i desktop Options menu: rendering contracts. Invented data."""
from contextlib import closing
from pathlib import Path

from bs4 import BeautifulSoup

from brickwork.core.connect import connect
from tests.web_fixtures import app, apps, logged_in  # noqa: F401
from tests.test_bw_collection import bw, legacy, reset_shell_metadata_after_test  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
KEYS = ('BW_BRICKLINK_CONSUMER_KEY', 'BW_BRICKLINK_CONSUMER_SECRET', 'BW_BRICKLINK_TOKEN_VALUE', 'BW_BRICKLINK_TOKEN_SECRET')


def test_options_menu_on_the_sets_toolbar(app, bw):
    soup = BeautifulSoup(logged_in(app).get('/collection/sets').data, 'html.parser')
    toolbar = soup.select_one('.bc-toolbar')
    button = toolbar.select_one('[data-bc-options-open]')
    assert button.get_text(strip=True) == 'Options' and button['aria-haspopup'] == 'menu'
    assert toolbar.select_one('[data-bc-options-menu]').has_attr('hidden')
    # The View block (Group by, Select) still exists for the phone sheet; the menu drives it.
    assert soup.select('.bc-view-group [data-bc-group-pick]') and soup.select_one('[data-bc-select][role=switch]')
    assert soup.find('script', src=lambda s: s and 'bw-options-menu.js' in s)
    css = (ROOT / 'static/web/toni/bw-collection.css').read_text()
    assert '@media(min-width:1024px){ .bc-options { display:block; } .bc-filter-panel .bc-view-group { display:none; } }' in css


def test_placed_orders_need_a_bricklink_key(app, monkeypatch):
    for name in KEYS:
        monkeypatch.delenv(name, raising=False)
    soup = BeautifulSoup(logged_in(app).get('/workbench/orders').data, 'html.parser')
    card = soup.select_one('.order-import-card')
    assert card.select_one('[data-load-orders]').has_attr('disabled')
    assert card.select_one('[data-needs-key=bricklink]').strong.text == 'Needs a BrickLink key'
    assert 'Needs a BrickLink key.' not in card.get_text()


def test_placed_orders_enabled_with_a_key(app, bw, monkeypatch):
    for name in KEYS:
        monkeypatch.setenv(name, 'synthetic-value-123')
    soup = BeautifulSoup(logged_in(app).get('/workbench/orders').data, 'html.parser')
    assert not soup.select_one('[data-load-orders]').has_attr('disabled')
    assert not soup.select_one('.order-import-card [data-needs-key]')


def test_catalogue_load_has_a_busy_state(app, bw):
    soup = BeautifulSoup(logged_in(app).get('/manage/catalogues').data, 'html.parser')
    form = soup.select_one('form[data-busy-form]')
    assert form.select_one('button[data-busy-label="Loading catalogue"]')
    assert form.select_one('[data-busy-note][role=status]').has_attr('hidden')
    assert "querySelectorAll('form[data-busy-form]')" in (ROOT / 'static/web/toni/bw-admin.js').read_text()


def test_storage_set_pill_says_not_checked():
    text = (ROOT / 'templates/web/toni/web/bw_storage.html').read_text()
    assert ".get(row.completeness,'Not checked')" in text and ".get(row.completeness,'Unknown')" not in text


def test_no_dead_breadcrumb_overrides():
    for path in (ROOT / 'templates/web/toni/web').glob('*.html'):
        assert '{% block breadcrumb %}' not in path.read_text(), path.name
