"""Review 5 frame contracts on a 4.0 collection (ported from test_ui_47b, M.8b).

Only the shell frames port: the Add, instruction-upload and long-list tests need `/manage/add` and `/manage/instructions`, which answer 503."""
from pathlib import Path
from bs4 import BeautifulSoup
from tests.app4 import app4, client, coll, pair, read, world

ROOT = Path(__file__).resolve().parents[1]


def test_shell_review_frames(client, world):
    soup = BeautifulSoup(client.get('/').data, 'html.parser')
    assert not soup.select('[data-nav-scrim], [data-nav-sheet]')    # no sheets, so no scrim, since #492
    jump = soup.select_one('#global-jump')
    assert not jump.select('h2, label')
    assert jump.select_one('#jump-query')['aria-label'] == 'Set number, name or item ID'
    assert jump.select_one('.jump-search-row [data-close]').text == 'Cancel'
    manage = soup.select_one('[data-nav-group=Manage] svg')      # the frames' wrench, in the phone tab bar
    assert manage.select_one('path')['d'] == 'M14 6a4 4 0 105 5l-8 8-3-3 8-8z'
    css = (ROOT / 'static/web/toni/shell.css').read_text().replace(':where(:not(.b-prime,.b-prime *))', '')
    for rule in ['text-transform:uppercase', 'font:500 11px/14px', 'font:500 15px']:     # the jump dialog's and the labels' own rules stay
        assert rule in css
