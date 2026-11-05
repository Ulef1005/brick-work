"""D4 (#153): Gear, Books and Catalogs in the sidebar and their lists: own icons, the part-only filters left out, the top strip scrolls to the active entry."""
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
import pytest

from tests import rendered
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import brand_assets  # noqa: E402

KINDS = {'G': ('Gear', 'gear'), 'B': ('Books', 'book'), 'C': ('Catalogs', 'catalog')}


@pytest.fixture
def all_kinds(coll, world):
    """The fixture world plus one book and one catalog, so all three kinds have a sidebar entry."""
    coll.add_stock('book', coll.local('book', 'Syn book', born_key='9780000000001'), quantity=1, condition='used')
    coll.add_stock('catalog', coll.local('catalog', 'Syn catalog', born_key='cat-1976'), quantity=1, condition='used')
    return world


def page(client, route):
    response = client.get(route)
    assert response.status_code == 200, route
    return BeautifulSoup(response.data, 'html.parser')


def icon_paths(name):
    return re.findall(r' d="([^"]+)"', (ROOT / 'static/brickwork/icons-ui' / f'{name}.svg').read_text())


# --- Q2: icons

@pytest.mark.parametrize('name', ['gear', 'book', 'catalog'])
def test_the_new_icons_exist_in_design_sprite_and_served_folder(name):
    source = ROOT / 'design/components/icons' / f'{name}.svg'
    served = ROOT / 'static/brickwork/icons-ui' / f'{name}.svg'
    assert source.is_file() and served.read_bytes() == source.read_bytes()
    text = source.read_text()
    assert 'viewBox="0 0 24 24"' in text and 'stroke-width="1.6"' in text and 'stroke="currentColor"' in text
    assert 'stroke-linecap="round"' in text and 'stroke-linejoin="round"' in text
    assert f'<symbol id="bw-{name}"' in (ROOT / 'design/components/icons/sprite.svg').read_text()
    assert f'icons-ui/{name}.svg' in (ROOT / 'design/components/icons/README.md').read_text()
    assert f'"/static/brickwork/icons-ui/{name}.svg"' in (ROOT / 'static/web/toni/sw.js').read_text()
    assert brand_assets.problems() == []


def test_the_three_icons_differ_from_parts_and_from_each_other():
    shapes = {name: icon_paths(name) for name in ('parts', 'gear', 'book', 'catalog')}
    assert all(shapes.values()) and len({tuple(v) for v in shapes.values()}) == 4


def test_the_sidebar_entries_use_their_own_icons(client, all_kinds):
    soup = page(client, '/collection/G')
    for letter, (title, icon) in KINDS.items():
        link = soup.select_one(f'.rail a[href$="/collection/{letter}"]')
        assert link and title in link.get_text(), title
        assert [p.get('d') for p in link.select('svg path')] == icon_paths(icon), title
        strip = soup.select_one(f'.group-items a[href$="/collection/{letter}"]')
        assert strip and strip.get('title') == title
    parts = soup.select_one('.rail a[href$="/collection/P"]')
    assert [p.get('d') for p in parts.select('svg path')] == icon_paths('parts')


def test_navigation_keys_the_three_entries_to_their_icons(app4, client, all_kinds):
    from brickwork.web.ui import navigation
    with app4.test_request_context('/collection/G'):
        from flask import session
        from brickwork.web.auth import SESSION_PASSWORD, password_mark
        session['_user_id'] = 'admin'
        session['_fresh'] = True
        session[SESSION_PASSWORD] = password_mark(app4.config['AUTHENTICATION_PASSWORD'])
        app4.preprocess_request()
        links = {link['title']: link['icon'] for link in dict(navigation())['Collection']}
    assert links == {'Sets': 'sets', 'Minifigures': 'minifig', 'Parts': 'parts', 'Instructions': 'instr', 'Boxes': 'box',
                     'Gear': 'gear', 'Books': 'book', 'Catalogs': 'catalog'}


# --- Q4: filter panel

@pytest.mark.parametrize('kind', ['G', 'B', 'C'])
def test_gear_books_catalogs_lack_the_part_only_filters(client, all_kinds, kind):
    panel = page(client, '/collection/' + kind).select_one('[data-bc-panel]')
    assert not panel.select('[data-bc-pick=problem], [data-bc-pick=stock]')
    assert not panel.select('select[data-bc-filter=theme], select[data-bc-filter=problem], select[data-bc-filter=stock]')
    headings = [h.get_text() for h in panel.select('h4')]
    assert 'Problems' not in headings and 'Stock' not in headings
    assert 'In sets only' not in panel.get_text() and 'Theme' not in [r.get_text(' ', strip=True).split(' ')[0] for r in panel.select('.bc-theme-row')]
    # What stays: storage, year, condition, copies, tags area, grouping.
    assert {'storage', 'year'} <= {s['data-bc-filter'] for s in panel.select('.bc-theme-row select')}
    assert panel.select('[data-bc-pick=condition]') and panel.select('[data-bc-pick=duplicates]') and panel.select_one('.bc-view-group')


def test_parts_keep_every_part_filter(client, all_kinds):
    panel = page(client, '/collection/P').select_one('[data-bc-panel]')
    assert [b['data-value'] for b in panel.select('[data-bc-pick=problem]')] == ['damaged', 'missing']
    assert [b['data-value'] for b in panel.select('[data-bc-pick=stock]')] == ['loose', 'sets']
    assert panel.select_one('.bc-theme-row select[data-bc-filter=theme]')



# --- Round 2, Q6 and Q7 (maintainer, 2026-11-05: "(a) Remove it", "(a) 'Name or number'")

@pytest.mark.parametrize('kind', ['G', 'B', 'C'])
def test_gear_books_catalogs_group_without_theme_and_search_by_name_or_number(client, all_kinds, kind):
    soup = page(client, '/collection/' + kind)
    assert [b['data-bc-group-pick'] for b in soup.select('[data-bc-group-pick]')] == ['', 'storage', 'year', 'place', 'lot']
    assert soup.select_one('input[data-bc-search]')['placeholder'] == 'Name or number'


def test_parts_and_sets_keep_their_grouping_and_search_words(client, all_kinds):
    parts = page(client, '/collection/P')
    assert 'theme' in [b['data-bc-group-pick'] for b in parts.select('[data-bc-group-pick]')]
    assert parts.select_one('input[data-bc-search]')['placeholder'] == 'Name, number or colour'
    assert page(client, '/collection/S').select_one('input[data-bc-search]')['placeholder'] == 'Number or name'


# --- Q5: the phone strip scrolls to the active entry

def test_the_strip_script_reveals_the_active_entry_without_motion():
    js = (ROOT / 'static/web/toni/shell.js').read_text()
    block = js[js.index('revealActive'):]
    assert "a[aria-current=page]" in block and "behavior: 'auto'" in block and 'smooth' not in js


def test_phone_strip_shows_the_active_entry_at_390(client, all_kinds, tmp_path):
    chrome = rendered.chrome()
    soup = page(client, '/collection/C')
    for link in soup.select('link[rel=stylesheet]'):
        style = soup.new_tag('style')
        style.string = (ROOT / urlsplit(link['href']).path.lstrip('/')).read_text()
        link.replace_with(style)
    for script in soup.select('script'):
        script.decompose()
    script = soup.new_tag('script')
    script.string = "window.adminTheme={mode:'light'};\n" + (ROOT / 'static/web/toni/shell.js').read_text()
    soup.body.append(script)
    (tmp_path / 'shell.html').write_text(str(soup))
    result = subprocess.run(['node', 'tests/toni_strip_scroll.cjs', chrome, str(tmp_path)], capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'strip ok' in result.stdout
