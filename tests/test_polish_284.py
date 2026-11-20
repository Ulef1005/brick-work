"""#284: Build Scout has its own icon, and the "No image" text fits a small thumbnail tile."""
import json
from pathlib import Path
import re
import sys

from bs4 import BeautifulSoup
import pytest

from tests import rendered
from tests.app4 import app4, client, coll, pair, world  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import brand_assets  # noqa: E402


def icon_paths(name):
    return re.findall(r' (?:d|x|cx)="([^"]+)"', (ROOT / 'static/brickwork/icons-ui' / f'{name}.svg').read_text())


def test_the_scout_icon_follows_the_icon_language_and_is_in_every_place_an_icon_lives():
    source = ROOT / 'design/components/icons/scout.svg'
    text = source.read_text()
    assert (ROOT / 'static/brickwork/icons-ui/scout.svg').read_bytes() == source.read_bytes()
    assert 'viewBox="0 0 24 24"' in text and 'stroke-width="1.6"' in text and 'stroke="currentColor"' in text
    assert 'stroke-linecap="round"' in text and 'stroke-linejoin="round"' in text and 'fill="none"' in text
    assert '<symbol id="bw-scout"' in (ROOT / 'design/components/icons/sprite.svg').read_text()
    assert 'icons-ui/scout.svg' in (ROOT / 'design/components/icons/README.md').read_text()
    assert '"/static/brickwork/icons-ui/scout.svg"' in (ROOT / 'static/web/toni/sw.js').read_text()
    assert brand_assets.problems() == []


def test_the_scout_icon_differs_from_sets_and_search():
    assert icon_paths('scout') and icon_paths('scout') != icon_paths('sets')
    assert (ROOT / 'static/brickwork/icons-ui/scout.svg').read_bytes() != (ROOT / 'static/brickwork/icons-ui/sets.svg').read_bytes()
    assert (ROOT / 'static/brickwork/icons-ui/scout.svg').read_bytes() != (ROOT / 'static/brickwork/icons-ui/search.svg').read_bytes()


def test_build_scout_keeps_its_own_icon_name(app4, client, world):
    """The shell draws no icon beside an entry since #492, but the entries still name theirs (the icons stay for the pages that draw them)."""
    with app4.test_request_context('/sets'):
        from brickwork.web.ui import navigation
        icons = {link['title']: link['icon'] for _, links in navigation() for link in links}
    assert icons['Build Scout'] == 'scout' and icons['Sets'] == 'sets'
    assert icon_paths(icons['Build Scout']) and icon_paths(icons['Build Scout']) != icon_paths(icons['Sets'])


def test_the_small_tile_rule_is_shared_in_the_global_stylesheet():
    shell = (ROOT / 'static/web/toni/shell.css').read_text().replace(':where(:not(.b-prime,.b-prime *))', '')
    assert '.bc-picture,.bw-picture,.check-picture,.scan-tile { container-type:inline-size; }' in shell
    assert '@container (max-width:80px)' in shell


@rendered.group
@pytest.mark.parametrize('wrap', ['{}', '<label class="bw-copy">{}</label>', '<div class="bw-copy-summary">{}</div>',
                                  '<div id="bw-check-choices"><a class="check-copy">{}</a></div>'])
@pytest.mark.parametrize('tile', ['bc-picture', 'bw-picture', 'check-picture', 'scan-tile'])
def test_a_56_px_no_image_tile_holds_the_number_on_one_line_and_the_note_inside(tile, wrap, tmp_path):
    """The shared tiles of the lists and the workbench, drawn with the shipped stylesheets, in the pinned Chrome."""
    chrome = rendered.chrome()
    css = ''.join((ROOT / 'static/web/toni' / name).read_text() for name in
                  ('tokens-v2.css', 'toni.css', 'bw-collection.css', 'bw-workbench.css', 'bw-checker.css', 'bw-inventory.css', 'bw-planning.css', 'shell.css'))
    numbers = ['1592-1', '40567-1', '75192-1']
    tiles = ''.join(f'<div class="{tile}" style="width:56px;height:56px"><span class="mono">{n}</span><span>No image</span></div>' for n in numbers)
    if tile == 'bc-picture':   # Complete sets draws it as the first cell of a row
        tiles = f'<div class="bp-complete-sets"><div class="bp-row">{tiles}</div></div>'
    tiles = ''.join(wrap.format(t) for t in re.findall(r'<div class="[^"]*" style=[^>]*>.*?</div>', tiles)) if tile != 'bc-picture' else wrap.format(tiles)   # the pages' own ancestors carry a 12 px `.mono` rule that the tile rule must beat (Codex review)
    script = ('<script>addEventListener("load",()=>{const out=[...document.querySelectorAll(".bc-picture,.bw-picture,.check-picture,.scan-tile")].map(t=>{const b=t.getBoundingClientRect();'
              'return [...t.children].map(s=>{const r=document.createRange();r.selectNodeContents(s);const rows=new Set([...r.getClientRects()].map(x=>Math.round(x.top)));'
              'const a=s.getBoundingClientRect();return {rows:rows.size,inside:a.left>=b.left-0.5&&a.right<=b.right+0.5&&a.top>=b.top-0.5&&a.bottom<=b.bottom+0.5,'
              'clipped:s.scrollWidth>s.clientWidth+1};});});document.body.setAttribute("data-out",JSON.stringify(out));});</script>')
    page = tmp_path / 'tile.html'
    page.write_text(f'<!doctype html><meta charset=utf-8><style>{css}</style><body class="tw-light">{tiles}{script}')
    dom = rendered.dump_dom(chrome, page.as_uri())      # retries a start that stalls or ends in the teardown watchdog (#293)
    out = json.loads(re.search(r'data-out="([^"]*)"', dom).group(1).replace('&quot;', '"'))
    assert len(out) == len(numbers)
    for number, (num, note) in zip(numbers, out):
        assert num['rows'] == 1 and num['inside'] and not num['clipped'], (number, num)
        assert note['rows'] == 1 and note['inside'], (number, note)
