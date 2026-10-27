"""Every bottom tab opens its server-rendered group sheet (on the 4.0 store: M.8i part 1)."""
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
def test_group_sheets_in_migrated_shell(client, world, path, active):
    response = client.get(path)
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, 'html.parser')
    tabs = soup.select('.mobile-bottom [data-nav-group]')
    sheets = soup.select('dialog[data-nav-sheet]')
    assert [tab['data-nav-group'] for tab in tabs] == [
        'Collection', 'Workbench', 'Planning', 'Manage']
    assert len(sheets) == len(tabs)
    assert len({tag['id'] for tag in soup.select('[id]')}) == len(soup.select('[id]'))
    assert [tab['data-nav-group'] for tab in tabs if tab['aria-current'] == 'true'] == [active]
    assert [row['data-group-panel'] for row in soup.select('[data-group-panel]') if not row.has_attr('hidden')] == [active]
    assert len(soup.select('[autofocus]')) <= 1
    assert soup.select_one('#jump-query[autofocus]')
    assert soup.select_one('[data-nav-sheet=Manage] .workbench-grid [data-open=appearance]')
    for tab, sheet in zip(tabs, sheets):
        group = tab['data-nav-group']
        assert sheet['id'] == tab['aria-controls']
        assert sheet['data-nav-sheet'] == group
        assert sheet['tabindex'] == '-1'
        assert soup.select_one(f'.rail nav [data-rail-group="{group}"] a')
        assert sheet.select_one('h2').text == group
        assert sheet['aria-labelledby'] == sheet.select_one('h2')['id']
        assert not sheet.select_one('[data-close]')
        assert not sheet.select('[autofocus]')
        assert tab['aria-haspopup'] == 'dialog' and tab['aria-expanded'] == 'false'
        links = sheet.select('.workbench-grid a, .workbench-grid button')
        row = soup.select_one(f'[data-group-panel="{group}"]')
        assert [(a.get('href'), a.get('data-open'), a.text, a.get('aria-current')) for a in links] == [
            (a.get('href'), a.get('data-open'), a.text, a.get('aria-current')) for a in row.select('a, button')]
        assert all(a.select_one('svg') for a in links)
        assert tab['href'] == links[0]['href']
    assert soup.select_one(f'[data-nav-sheet="{active}"] a[aria-current="page"]')
