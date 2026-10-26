"""Review 5 frame contracts on a 4.0 collection (ported from test_ui_47b, M.8b).

Only the shell frames port: the Add, instruction-upload and long-list tests need `/manage/add` and `/manage/instructions`, which answer 503."""
from pathlib import Path
from bs4 import BeautifulSoup
from tests.app4 import app4, client, coll, pair, read, world

ROOT = Path(__file__).resolve().parents[1]


def test_shell_review_frames(client, world):
    soup = BeautifulSoup(client.get('/').data, 'html.parser')
    assert soup.select_one('[data-nav-scrim][hidden]')
    for sheet in soup.select('[data-nav-sheet]'):
        assert not sheet.select('[data-close]')
    jump = soup.select_one('#global-jump')
    assert not jump.select('h2, label')
    assert jump.select_one('#jump-query')['aria-label'] == 'Set number, name or item ID'
    assert jump.select_one('.jump-search-row [data-close]').text == 'Cancel'
    manage = soup.select_one('[data-nav-group=Manage] svg')
    assert manage.select_one('rect')['width'] == '16'
    assert manage.select_one('path')['d'].endswith('M4 13h16')
    css = (ROOT / 'static/web/toni/shell.css').read_text()
    for rule in ['inset:auto 0 var(--bw-bottom)', 'z-index:23', 'gap:12px',
                 'min-height:96px', 'text-transform:uppercase', 'font:500 11px/14px',
                 'font:500 15px', 'background:var(--tw-surface-2)']:
        assert rule in css
