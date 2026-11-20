"""#258: a set card shows each copy's own status pill (Complete, Incomplete, Sealed, Not checked), rendered in real Chromium.

The list payload sends completeness as words since 4.0 (`core.list_records`); the card used to map the old letters and showed
Not checked for every copy."""
import json
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from tests import rendered
from tests.app4 import app4, client, coll, pair, world  # noqa: F401  (the fixtures)

ROOT = Path(__file__).resolve().parents[1]


@rendered.group
def test_set_cards_show_each_copys_status(world, coll, client, tmp_path):
    executable = rendered.chrome()
    coll.add_copy('2070-1', condition='used')                     # a copy nobody has checked: no completeness
    response = client.get('/collection/S')
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, 'html.parser')
    for link in soup.select('link[rel=stylesheet]'):
        style = soup.new_tag('style')
        style.string = (ROOT / urlsplit(link['href']).path.lstrip('/')).read_text()
        link.replace_with(style)
    for script in soup.select('script'):
        if script.get('type') == 'application/json':
            continue
        name = Path(urlsplit(script.get('src', '')).path).name
        if name in ('formatting.js', 'bw-collection.js'):
            script.attrs.clear()
            script.string = (ROOT / 'static/web/toni' / name).read_text()
            soup.body.append(script.extract())
        else:
            script.decompose()
    page = tmp_path / 'sets.html'
    page.write_text(str(soup))
    result = subprocess.run(['node', 'tests/toni_bw_set_status_pills.cjs', executable, str(page)], capture_output=True, text=True, timeout=180, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    cards = {card["number"]: card["pills"] for card in json.loads(result.stdout.splitlines()[0])}
    # The world: 1000-1 has an incomplete and a sealed copy; 2070-1 a complete one, and the unchecked copy added above (a bar for each, the Sealed tag for the sealed one).
    assert [(p['text'], p['state']) for p in cards['1000-1'] if p['text'] != 'collection'] == [('#1 5/6 · 1 missing', 'bar'), ('Sealed', 'sealed')], cards
    texts = sorted(p['text'] for p in cards['2070-1'])
    assert texts == ['#1 4/4 · complete', 'Not checked#2 0/4'] or texts == ['#2 4/4 · complete', 'Not checked#1 0/4'], cards


def test_a_copy_line_over_21_characters_wraps_on_a_phone_drawers_tile_and_keeps_its_dot_in_the_text():
    """#494 (design, 2026-11-20): the line under a tile's bar is copy and pieces, the dot, the missing count as three spans; only the phone Drawers tile hides the dot and
    breaks the line (frame_check proves the pixels), so the text a person copies, finds or reads aloud keeps "365/375 · 10 missing", and a Ledger row stays one line."""
    js = (ROOT / 'static/web/toni/bw-collection.js').read_text()
    assert "line.length>21" in js and "el('span','sep',' · ')" in js
    css = (ROOT / 'static/web/toni/bw-collection.css').read_text()
    phone = css[css.index('a line over 21 characters'):]
    phone = phone[:phone.index('\n}\n')]
    assert '.bp-groups:not([data-view=list]) .bartxt.two > .sep { display:none; }' in phone
    assert '.bp-groups:not([data-view=list]) .bartxt.two > span { display:block;line-height:16px;white-space:normal; }' in phone
