"""4.9f: phone bottom bar (kit frame 1b: 83px, 12px label line) and the Jump sheet without helper copy."""
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
import pytest

from tests.app4 import app4, client, coll, pair, read, world

ROOT = Path(__file__).resolve().parents[1]


def test_jump_has_no_helper_copy_keyboard_line_or_add(client):
    soup = BeautifulSoup(client.get('/').data, 'html.parser')
    jump = soup.select_one('#global-jump')
    assert jump and not jump.has_attr('data-add-url')
    assert jump.select_one('#jump-message').text.strip() == ''
    assert not jump.select('#jump-add, a.button')
    for text in ('Search owned and wanted', 'Enter opens copy', 'Esc closes'):
        assert text not in jump.text
    assert jump.select_one('#jump-query[placeholder]') and jump.select_one('.jump-cancel')


def test_bottom_bar_and_jump_sheet_css():
    css = (ROOT / 'static/web/toni/shell.css').read_text()
    region = css[css.index('4.9f'):]
    assert '--bw-bottom-inset:max(34px,var(--tw-safe-bottom))' in region
    assert '--bw-bottom:calc(49px + var(--bw-bottom-inset))' in region
    assert 'font:500 11px/12px var(--tw-font)' in region
    assert 'height:var(--bw-bottom)' in region and 'padding-bottom:var(--bw-bottom-inset)' in region
    sheet = re.search(r'#global-jump\{([^}]+)\}', region).group(1)
    for value in ('position:fixed', 'inset:0', 'width:100%', 'height:100dvh', 'max-width:none',
                  'max-height:none', 'border-radius:0'):
        assert value in sheet


def test_shell_chromium_geometry(client, tmp_path):
    chrome = os.environ.get('BW_COLLECTION_CHROME')
    if not chrome:
        pytest.skip('Set BW_COLLECTION_CHROME for opt-in browser geometry verification')
    soup = BeautifulSoup(client.get('/').data, 'html.parser')
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
    result = subprocess.run(['node', 'tests/toni_shell_geometry.cjs', chrome, str(tmp_path)],
                            capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


def test_fixed_clearances_follow_bottom_bar_variable():
    css = {n: (ROOT / 'static/web/toni' / n).read_text() for n in
           ('toni.css', 'shell.css', 'bw-collection.css')}
    assert '.savebar{bottom:var(--bw-bottom)}.toast-live{bottom:calc(var(--bw-bottom) + var(--tw-s-4))}' in css['toni.css']
    assert 'calc(var(--bw-bottom) + 35px)' in css['bw-collection.css']
    assert 'calc(84px' not in css['bw-collection.css']
    # Outside the phone/iPad media query --bw-bottom keeps its original definition.
    assert re.search(r'^:root\{[^}]*--bw-bottom:calc\(var\(--tw-tabbar-h\) \+ var\(--tw-safe-bottom\)\)', css['shell.css'], re.M)
    assert '@media(max-width:1023.98px){:root{--bw-bottom:calc(49px + var(--bw-bottom-inset))}}' in css['shell.css']
