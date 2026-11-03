"""#50 Manage and Workbench leftovers and #49 12i desktop Options menu: rendering contracts, on the 4.0 store (M.8i part 1). Invented data.

The Catalogues page's "Load catalogue" busy state went with that button (the catalogue is loaded with `python -m brickwork.store4`, see
test_bw_admin.py)."""
from pathlib import Path

from bs4 import BeautifulSoup

from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401  (the fixtures)

ROOT = Path(__file__).resolve().parents[1]
KEYS = ('BW_BRICKLINK_CONSUMER_KEY', 'BW_BRICKLINK_CONSUMER_SECRET', 'BW_BRICKLINK_TOKEN_VALUE', 'BW_BRICKLINK_TOKEN_SECRET')


def test_options_menu_on_the_sets_toolbar(client, world):
    soup = BeautifulSoup(client.get('/collection/sets').data, 'html.parser')
    toolbar = soup.select_one('.bc-toolbar')
    button = toolbar.select_one('[data-bc-options-open]')
    assert button.get_text(strip=True) == 'Options' and button['aria-haspopup'] == 'menu'
    assert toolbar.select_one('[data-bc-options-menu]').has_attr('hidden')
    # The View block (Group by, Select) still exists for the phone sheet; the menu drives it.
    assert soup.select('.bc-view-group [data-bc-group-pick]') and soup.select_one('[data-bc-select][role=switch]')
    assert soup.find('script', src=lambda s: s and 'bw-options-menu.js' in s)
    css = (ROOT / 'static/web/toni/bw-collection.css').read_text()
    assert '@media(min-width:1024px){ .bc-options { display:block; } .bc-filter-panel .bc-view-group { display:none; } }' in css


def test_placed_orders_need_a_bricklink_key(client, world, monkeypatch):
    for name in KEYS:
        monkeypatch.delenv(name, raising=False)
    soup = BeautifulSoup(client.get('/workbench/orders').data, 'html.parser')
    card = soup.select_one('.order-import-card')
    assert card.select_one('[data-load-orders]').has_attr('disabled')
    assert card.select_one('[data-needs-key=bricklink]').strong.text == 'Needs a BrickLink key'
    assert 'Needs a BrickLink key.' not in card.get_text()


def test_placed_orders_enabled_with_a_key(client, world, monkeypatch):
    for name in KEYS:
        monkeypatch.setenv(name, 'synthetic-value-123')
    soup = BeautifulSoup(client.get('/workbench/orders').data, 'html.parser')
    assert not soup.select_one('[data-load-orders]').has_attr('disabled')
    assert not soup.select_one('.order-import-card [data-needs-key]')


def test_the_catalogues_page_has_no_load_button_to_keep_busy(client, world):
    soup = BeautifulSoup(client.get('/manage/catalogues').data, 'html.parser')
    assert not soup.select('form[data-busy-form]') and not soup.find('button', string='Load catalogue') and not soup.find('button', string='Load colours')


def test_storage_set_pill_says_not_checked():
    text = (ROOT / 'templates/web/toni/web/bw_storage.html').read_text()
    assert ".get(row.completeness,'Not checked')" in text and ".get(row.completeness,'Unknown')" not in text


def test_no_dead_breadcrumb_overrides():
    for path in (ROOT / 'templates/web/toni/web').glob('*.html'):
        assert '{% block breadcrumb %}' not in path.read_text(), path.name
