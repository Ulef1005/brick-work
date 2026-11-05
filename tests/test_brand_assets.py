"""The brand assets moved to design/ (#159, D2): every /static/brickwork/ URL that `main` served before the move still answers with the
same bytes, the served files are generated from their sources, and a path-like parameter reaches no file outside the static folder."""
import subprocess
import sys
from pathlib import Path

import pytest

from tests.app4 import app4, pair  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
BEFORE = 'd97bf65'   # main before D2
GROWN = {'/static/brickwork/icons-ui/sprite.svg', '/static/brickwork/icons-ui/README.md'}
sys.path.insert(0, str(ROOT / 'scripts'))
import brand_assets  # noqa: E402


def served_before():
    """`{url path: bytes}` of every file under static/brickwork at the commit before the move."""
    git = lambda *args: subprocess.run(['git', *args], cwd=ROOT, capture_output=True, check=True).stdout  # noqa: E731
    names = git('ls-tree', '-r', '--name-only', '-z', BEFORE, 'static/brickwork').decode().split('\0')
    return {'/' + name: git('show', f'{BEFORE}:{name}') for name in names if name}


def test_every_url_served_before_the_move_answers_with_the_same_bytes(app4):
    before = served_before()
    assert len(before) == 70 and '/static/brickwork/mark.svg' in before and '/static/brickwork/icons-ui/sprite.svg' in before
    client = app4.test_client()
    for url, content in before.items():
        response = client.get(url)
        assert response.status_code == 200, url
        if url in GROWN:   # the icon set has grown since (#153: gear, book, catalog): every line served before is still there
            assert set(content.decode().splitlines()) <= set(response.get_data().decode().splitlines()), url
        else:
            assert response.get_data() == content, url
        response.close()


def test_the_served_files_are_generated_from_design():
    assert brand_assets.problems() == []
    on_disk = {p.relative_to(brand_assets.SERVED).as_posix() for p in brand_assets.SERVED.rglob('*') if p.is_file()}
    assert on_disk == set(brand_assets.mapping()) | brand_assets.APP_OWNED   # 68 generated + brick-work.css + manifest.webmanifest


def test_check_finds_a_drifted_a_stray_and_a_missing_file(tmp_path, monkeypatch):
    served = tmp_path / 'static' / 'brickwork'
    for name, path in brand_assets.mapping().items():
        (served / name).parent.mkdir(parents=True, exist_ok=True)
        (served / name).write_bytes(path.read_bytes())
    monkeypatch.setattr(brand_assets, 'SERVED', served)
    assert brand_assets.problems() == []
    (served / 'mark.svg').write_bytes(b'edited')
    (served / 'stray.png').write_bytes(b'no source')
    (served / 'splash').joinpath('splash-iphone16-1179x2556-dark.png').unlink()
    (served / 'brick-work.css').write_text('app-owned, ignored')
    found = brand_assets.problems()
    assert len(found) == 3 and any('mark.svg differs' in line for line in found)
    assert any('stray.png has no source' in line for line in found) and any('is missing' in line for line in found)


@pytest.mark.parametrize('path', [
    '/static/brickwork/../../app.py', '/static/brickwork/%2e%2e/%2e%2e/app.py', '/static/brickwork/%2e%2e%2f%2e%2e%2fapp.py',
    '/static/brickwork/..%2f..%2fapp.py', '/static/brickwork//app.py', '/static/brickwork/%2fetc%2fpasswd',
    '/static/brickwork/icons/../../../app.py', '/static/brickwork/..\\..\\app.py', '/static/%2e%2e/app.py', '/static/../app.py',
    '/static//etc/passwd', '/static/brickwork/mark.svg/../../../app.py',
    '/static/brickwork/?file=../../app.py',
    '/static/design/logo/mark.svg', '/static/brickwork/../design/logo/mark.svg'])
def test_a_path_like_parameter_reaches_no_file_outside(app4, path):
    response = app4.test_client().get(path)
    assert response.status_code in (301, 302, 303, 307, 308, 404), (path, response.status_code)
    assert b'setup_app' not in response.get_data() and b'root:' not in response.get_data()
    response.close()


def test_a_query_parameter_never_changes_which_file_is_served(app4):
    response = app4.test_client().get('/static/brickwork/mark.svg?path=/etc/passwd&file=../../app.py')
    assert response.status_code == 200 and response.get_data() == (ROOT / 'design/logo/mark.svg').read_bytes()
    response.close()


def test_no_handler_with_a_path_argument_serves_the_brand_files(app4):
    """Only Flask's own static route (the one that served these files before the move) and the collection's item-number route take a path."""
    rules = {rule.rule for rule in app4.url_map.iter_rules() if '<path:' in rule.rule or '<filename' in rule.rule}
    assert rules == {'/static/<path:filename>', '/collection/item/<kind>/<path:number>'}
