"""#648: on a touch screen every text field is 16px, so iOS Safari does not zoom the page in when a field takes focus."""
import re
from pathlib import Path

from bs4 import BeautifulSoup

from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401 (fixtures)

ROOT = Path(__file__).resolve().parents[1]
SHEET = ROOT / 'static' / 'web' / 'toni' / 'bw-touch-fields.css'


def test_text_fields_are_16px_on_a_touch_screen_only():
    css = re.sub(r'/\*.*?\*/', '', SHEET.read_text(), flags=re.S)
    media = re.findall(r'@media\s*([^{]+)\{(.*)\}\s*$', css.strip(), flags=re.S)
    assert len(media) == 1
    query, body = media[0]
    assert query.replace(' ', '') == '(hover:none)and(pointer:coarse)'   # a mouse and a desktop keep the frames' 14px
    selector, rule = body.strip().rstrip('}').split('{')
    assert rule.strip() == 'font-size:16px!important'                    # iOS zooms below 16px; beats the B′ and legacy field rules
    parts = [p.strip() for p in re.split(r',(?![^(]*\))', selector)]
    assert parts[1:] == ['select', 'textarea']
    assert ':not(.inv-qty *,.order-stepper *)' in parts[0]                    # the 18px steppers keep their size
    for kind in ('checkbox', 'radio', 'range', 'color', 'file', 'hidden', 'button', 'submit', 'reset', 'image'):
        assert f'[type={kind}]' in parts[0]                               # text-like fields only


def test_every_page_loads_it_and_the_worker_precaches_it(world, app4, client):
    page = BeautifulSoup(client.get('/workbench/storage').data, 'html.parser')
    assert any('/static/web/toni/bw-touch-fields.css' in link['href'] for link in page.select('link[rel=stylesheet]'))
    assert '"/static/web/toni/bw-touch-fields.css"' in (ROOT / 'static' / 'web' / 'toni' / 'sw.js').read_text()

