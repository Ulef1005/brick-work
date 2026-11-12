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
    # The world: 1000-1 has an incomplete and a sealed copy; 2070-1 a complete one, and the unchecked copy added above.
    assert sorted((p['text'], p['state']) for p in cards['1000-1']) == [('Incomplete', 'incomplete'), ('Sealed', 'sealed')], cards
    assert sorted((p['text'], p['state']) for p in cards['2070-1']) == [('Complete', 'complete'), ('Not checked', 'unknown')], cards
