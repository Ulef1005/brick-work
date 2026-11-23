"""Every group tab is a plain link to the group's first entry; the active group's entries are in the sub row (ported from test_shell_46p, M.8b).

One ported screen stands for each group: home (Collection), the purchase places (Workbench, current "Storage") and the wish list
(Planning, current "Wishlist"). The Manage group (`/manage/tools`, M.8i) stays in `test_shell_46p.py`."""
from pathlib import Path
import subprocess

from bs4 import BeautifulSoup
import pytest

from tests.app4 import app4, client, coll, pair, read, world

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('path,active', [
    ('/', 'Collection'),
    ('/collection/purchase-places', 'Workbench'),
    ('/collection/wishes', 'Planning'),
])
def test_group_links_in_migrated_shell(client, world, path, active):
    response = client.get(path)
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, 'html.parser')
    tabs = soup.select('.bp-tabbar a[data-nav-group]')
    assert [tab['data-nav-group'] for tab in tabs] == ['Collection', 'Workbench', 'Planning', 'Manage']
    assert len({tag['id'] for tag in soup.select('[id]')}) == len(soup.select('[id]'))
    assert [tab['data-nav-group'] for tab in tabs if tab.get('aria-current') == 'true'] == [active]
    assert [tab.text.strip() for tab in soup.select('nav.tabs a.tab[aria-current="true"]')] == [active]
    assert len(soup.select('[autofocus]')) <= 1
    assert soup.select_one('#jump-query[autofocus]')
    # Plain links, no sheet and no script behind them: the tab bar and the top bar point at the first entry of each group, and the active group's
    # entries are in the desktop sub row and the phone strip alike.
    assert [a['href'] for a in tabs] == [a['href'] for a in soup.select('nav.tabs a.tab')]
    assert not soup.select('dialog[data-nav-sheet], [data-open=appearance]')
    desktop, phone = (soup.select(f'{row} a') for row in ('nav.sub', 'nav.psub'))
    assert desktop and [(a['href'], a.text, a.get('aria-current')) for a in desktop] == [(a['href'], a.text, a.get('aria-current')) for a in phone]
    assert tabs[['Collection', 'Workbench', 'Planning', 'Manage'].index(active)]['href'] == desktop[0]['href']
    assert soup.select_one('nav.sub a[aria-current="page"]')


def test_shell_runtime():
    from tests import rendered
    rendered.need_node()
    subprocess.run(['node', str(ROOT / 'tests/toni_shell_runtime.cjs')], check=True, cwd=ROOT)
