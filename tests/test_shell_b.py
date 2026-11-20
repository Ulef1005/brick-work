"""The B′ shell (#492): top bar with four group tabs and a sub row on a desktop, lockup bar, sub row and tab bar on a phone, all plain links."""
import ast
from pathlib import Path
import re
import sys

from bs4 import BeautifulSoup
import pytest

from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401  (the fixtures)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import b_prime_css  # noqa: E402

GROUPS = ['Collection', 'Workbench', 'Planning', 'Manage']


def shell(client, path):
    response = client.get(path)
    assert response.status_code == 200, path
    return BeautifulSoup(response.get_data(as_text=True), 'html.parser')


@pytest.mark.parametrize('path,active', [('/collection/sets', 'Collection'), ('/workbench/orders', 'Workbench'),
                                         ('/planning/prices', 'Planning'), ('/manage/tools', 'Manage')])
def test_four_tabs_and_four_tabbar_links_mark_the_active_group(client, world, path, active):
    page = shell(client, path)
    tabs = page.select('header.top nav.tabs a.tab')
    assert [t.get_text(strip=True) for t in tabs] == GROUPS
    assert [t.get_text(strip=True) for t in tabs if t.has_attr('aria-current')] == [active]
    assert [t.get_text(strip=True) for t in tabs if 'on' in t.get('class', [])] == [active]
    bar = page.select('.bp-tabbar nav.tabbar a[data-nav-group]')
    assert [a['data-nav-group'] for a in bar] == GROUPS
    assert [a['data-nav-group'] for a in bar if a.get('aria-current') == 'true'] == [active]
    assert [a['data-nav-group'] for a in bar if 'on' in a.get('class', [])] == [active]
    assert all((a.find('b') is not None) == (a['data-nav-group'] == active) for a in bar)
    assert len(page.select('a.tab')) == 4
    # Each tab and tab-bar link points at the first entry of its group, which is a link of the sub row when the group is the active one.
    assert [t['href'] for t in tabs] == [a['href'] for a in bar]


def test_the_manage_sub_row_lists_add_tools_and_appearance(client, world):
    page = shell(client, '/manage/tools')
    for row in ('nav.sub', 'nav.psub'):
        assert [a.select_one('.nav-title').text for a in page.select(f'{row} a')] == ['Add', 'Tools & Admin', 'Appearance']
        assert [a.select_one('.nav-title').text for a in page.select(f'{row} a[aria-current="page"]')] == ['Tools & Admin']
    response = client.get('/manage/appearance')
    assert response.status_code == 200
    page = BeautifulSoup(response.get_data(as_text=True), 'html.parser')
    for row in ('nav.sub', 'nav.psub'):
        assert [a.select_one('.nav-title').text for a in page.select(f'{row} a[aria-current="page"]')] == ['Appearance']
        assert [a.select_one('.nav-title').text for a in page.select(f'{row} a.on')] == ['Appearance']
    assert page.select_one('a[data-nav-group="Manage"]')['aria-current'] == 'true'


@pytest.mark.parametrize('path', ['/', '/collection/sets', '/workbench/orders', '/planning/prices', '/manage/tools', '/manage/appearance', '/login'])
def test_no_rail_sheets_bottom_bar_or_group_strip_in_any_page(client, world, path):
    page = shell(client, path)
    for name in ('rail', 'workbench-sheet', 'mobile-bottom', 'group-items'):
        assert not page.select(f'.{name}'), (path, name)
    assert not page.select('#navbarSupportedContent, [data-nav-sheet], [data-nav-scrim], [data-group-panel], [data-rail-group]'), path


def test_shell_icon_paths_equal_the_frames_icons():
    template = (ROOT / 'templates/web/toni/shell-components.html').read_text()
    paths = ast.literal_eval(re.search(r'\{% set bp_paths = (\{.*?\}) %\}', template, re.S).group(1))
    frames = None
    for node in ast.parse((ROOT / 'design/sources/b/b_frames.py').read_text()).body:     # read with ast, never imported (design's file)
        if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', None) == 'IC':
            frames = ast.literal_eval(node.value)
    names = ['search', 'plus', 'sets', 'sliders', 'tag', 'wrench']
    assert frames and set(names) <= set(frames)
    assert {name: paths[name] for name in names} == {name: frames[name] for name in names}


def test_shell_css_heights_equal_the_frames_heights():
    frames = b_prime_css.shell_heights()
    css = (ROOT / 'static/web/toni/shell.css').read_text()
    root = re.search(r'^:root\{([^}]*)\}', css, re.M).group(1)
    phone = re.search(r'@media\(max-width:1023\.98px\)\{:root\{([^}]*)\}', css).group(1)

    def px(block, name):
        return int(re.search(re.escape(name) + r':(\d+)px', block).group(1))
    assert px(root, '--tw-topbar-h') == frames['top'] and px(root, '--bw-sub-h') == frames['sub']
    assert px(phone, '--tw-topbar-h') == frames['ptop'] and px(phone, '--bw-sub-h') == frames['psub']
    assert px(root, '--tw-tabbar-h') == frames['tabbar']


def test_phone_touch_targets_keep_44px():
    css = (ROOT / 'static/brickwork/brick-work.css').read_text().replace(':not(#_)', '')
    assert re.search(r'\.bp-tabbar\.b-prime \.tabbar a\{min-height:44px\}', css)
    assert re.search(r'\.jump-icon,\.bp-shell\.b-prime \.add-icon\{[^}]*min-width:41px;min-height:44px', css)


def test_sub_row_scrolls_inside_itself_and_the_tab_bar_is_phone_only():
    css = (ROOT / 'static/brickwork/brick-work.css').read_text().replace(':not(#_)', '')
    assert re.search(r'\.bp-shell\.b-prime \.sub\{[^}]*overflow-x:auto', css) and re.search(r'\.bp-shell\.b-prime \.psub\{[^}]*overflow-x:auto', css)
    assert re.search(r'\.bp-tabbar\.b-prime \.tabbar\{display:none\}', css)                  # off at a desktop width, fixed to the viewport below 1024 px
    phone = css[css.index('@media(max-width:1023.98px){', css.index('.bp-tabbar.b-prime .tabbar{display:none}')):]
    assert 'position:fixed' in phone.split('}\n}')[0] and '.top,.bp-shell.b-prime .sub{display:none}' in phone
