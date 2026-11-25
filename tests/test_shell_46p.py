"""Every group tab is a plain link to the group's first entry; the active group's entries are in the sub row (on the 4.0 store: M.8i part 1)."""
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401  (the fixtures)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('path,active', [
    ('/workbench/storage', 'Workbench'),
    ('/planning/wishlist', 'Planning'),
    ('/manage/tools', 'Manage'),
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


def test_the_appearance_choices_are_labelled_buttons(client, world):
    """#674: each theme choice says its name next to its icon (an icon alone does not name the choice) and wires to data-theme-mode."""
    soup = BeautifulSoup(client.get('/manage/appearance').get_data(as_text=True), 'html.parser')
    buttons = soup.select('#content .theme-segments > button[data-theme-mode]')
    assert [(b['data-theme-mode'], b.get_text(strip=True)) for b in buttons] == [('system', 'Automatic'), ('light', 'Light'), ('dark', 'Dark')]
    assert all(b['type'] == 'button' and b.select_one('svg') and not b.has_attr('aria-label') for b in buttons)
