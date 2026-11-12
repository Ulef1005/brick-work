"""The screenshot gate (D3, #160; ADR 0022): the built app against the approved baseline captures, per screen state.

`test_approved_states_match_their_baselines` is the gate. With no approved state it still runs, says so and passes; it never skips. The summary
goes to the file named by BW_GATE_SUMMARY (scripts/check.sh prints it). Invented data only; the pinned Chrome (scripts/chrome.py) renders.

The baselines are rendered on Linux (ADR 0022), so only a Linux run decides. Elsewhere (a local macOS gate) the comparison still runs and its
differences are printed as advisory, because font rendering differs by a few per cent on every page; `BW_GATE_STRICT=1` makes them fail anyway."""
import json
import os
import tempfile
import sys
from pathlib import Path

from PIL import Image

from scripts import screen_gate as gate
from tests import rendered

pytestmark = rendered.group    # the gate's world folder and Chrome are shared: one worker runs this module's tests (tests/rendered.py)


def write_summary(lines):
    target = os.environ.get('BW_GATE_SUMMARY')
    if target:
        Path(target).write_text('\n'.join(lines) + '\n', encoding='utf-8')


def test_approved_states_match_their_baselines():
    states = gate.load()
    c = gate.counts(states)
    chrome = rendered.chrome(pinned=True) if c['approved'] else ''
    lines, checked, differ = gate.run_compare(chrome)
    authoritative = sys.platform.startswith('linux') or os.environ.get('BW_GATE_STRICT') == '1'
    if differ and not authoritative:
        lines.append(f'  advisory on {sys.platform}: the baselines are Linux renders, so only the Linux run (CI) decides (ADR 0022)')
    write_summary(lines)
    print('\n'.join(lines))
    assert checked == len(c['approved'])
    assert not differ or not authoritative, '\n'.join(lines)


def test_every_approved_state_is_built_and_has_its_baselines():
    for entry in gate.load()['states']:
        if entry['approved']:
            assert entry['built'], entry
            assert all(path.is_file() for _, _, path in gate.variants(entry)), entry


def test_the_comparison_sees_a_changed_pixel_block_and_ignores_noise(tmp_path):
    a, b, c = tmp_path / 'a.png', tmp_path / 'b.png', tmp_path / 'c.png'
    Image.new('RGB', (200, 100), (250, 250, 248)).save(a)
    image = Image.new('RGB', (200, 100), (251, 250, 248))                 # one channel off by 1: noise
    image.save(b)
    assert gate.compare_images(a, b)['share'] == 0
    for x in range(20):
        for y in range(20):
            image.putpixel((x, y), (10, 10, 10))
    image.save(c)
    diff = tmp_path / 'diff.png'
    result = gate.compare_images(a, c, diff)
    assert result['differing'] == 400 and result['share'] > gate.TOLERANCE['pixels'] and diff.is_file()
    assert gate.compare_images(a, Image.new('RGB', (10, 10)).save(tmp_path / 'd.png') or tmp_path / 'd.png')['size_differs']


def test_a_state_renders_the_same_twice(tmp_path, monkeypatch):
    """Deterministic rendering: the same state, rendered twice, differs by less than the gate's tolerance (fixed clock, no animation, bundled fonts)."""
    chrome = rendered.chrome(pinned=True)
    monkeypatch.setattr(gate, 'WIDTHS', (390, 1440))
    monkeypatch.setattr(gate, 'THEMES', ('dark',))
    entries = [e for e in gate.load()['states'] if e['built'] and e['screen'] in ('42-Prices', '09-Collection')]
    assert entries
    first = gate.render(entries, lambda e, w, t: tmp_path / '1' / gate.filename(e['screen'], e['state'], w, t), chrome)
    second = gate.render(entries, lambda e, w, t: tmp_path / '2' / gate.filename(e['screen'], e['state'], w, t), chrome)
    assert len(first) == len(second) == 4
    for one, two in zip(first, second):
        assert Image.open(one).size[0] in (390 * 2, 1440), one
        result = gate.compare_images(one, two)
        assert not result['size_differs'] and result['share'] <= gate.TOLERANCE['pixels'] / 5, (one.name, result)


def _check_states(tmp_path, monkeypatch, approved, files):
    """design_screens.state_problems() for one built state `09-Collection`, with the given `approved` flag and baseline files present."""
    from scripts import design_screens as ds
    states = {'sizes': [1440, 1024, 390], 'themes': ['light', 'dark'], 'states': [
        {'screen': '09-Collection', 'section': 'x', 'state': '', 'built': True, 'approved': approved, 'world': 'demo', 'path': '/collection'}]}
    (tmp_path / 'states.json').write_text(json.dumps(states), encoding='utf-8')
    folder = tmp_path / 'baselines' / '09-Collection'
    folder.mkdir(parents=True)
    for name in files:
        (folder / name).write_bytes(b'')
    monkeypatch.setattr(ds, 'STATES', tmp_path / 'states.json')
    monkeypatch.setattr(ds, 'BASELINES', tmp_path / 'baselines')
    return ds.state_problems({'09-Collection'})


ALL_SIX = [f'09-Collection-{w}-{t}.png' for w in (1440, 1024, 390) for t in ('light', 'dark')]


def test_a_built_state_that_is_not_approved_needs_no_baseline_file(tmp_path, monkeypatch):
    assert _check_states(tmp_path, monkeypatch, False, []) == []


def test_an_approved_state_needs_all_six_baselines(tmp_path, monkeypatch):
    (tmp_path / 'full').mkdir()
    assert _check_states(tmp_path / 'full', monkeypatch, True, ALL_SIX) == []
    (tmp_path / 'part').mkdir()
    found = _check_states(tmp_path / 'part', monkeypatch, True, ALL_SIX[:5])
    assert len(found) == 1 and 'is approved but has no baseline' in found[0] and ALL_SIX[5] in found[0]
    (tmp_path / 'none').mkdir()
    assert len(_check_states(tmp_path / 'none', monkeypatch, True, [])) == 6


def _check_sized(tmp_path, monkeypatch, sizes, files, approved=True):
    from scripts import design_screens as ds
    states = {'sizes': [1440, 1024, 390], 'themes': ['light', 'dark'], 'states': [
        {'screen': '09-Collection', 'section': 'x', 'state': 'menu', 'built': True, 'approved': approved, 'world': 'demo', 'path': '/collection', 'sizes': sizes}]}
    (tmp_path / 'states.json').write_text(json.dumps(states), encoding='utf-8')
    folder = tmp_path / 'baselines' / '09-Collection'
    folder.mkdir(parents=True)
    for name in files:
        (folder / name).write_bytes(b'')
    monkeypatch.setattr(ds, 'STATES', tmp_path / 'states.json')
    monkeypatch.setattr(ds, 'BASELINES', tmp_path / 'baselines')
    return ds.state_problems({'09-Collection'})


def test_a_state_with_sizes_needs_baselines_for_those_widths_only(tmp_path, monkeypatch):
    four = [f'09-Collection-menu-{w}-{t}.png' for w in (1440, 1024) for t in ('light', 'dark')]
    (tmp_path / 'ok').mkdir()
    assert _check_sized(tmp_path / 'ok', monkeypatch, [1440, 1024], four) == []
    (tmp_path / 'short').mkdir()
    found = _check_sized(tmp_path / 'short', monkeypatch, [1440, 1024], four[:3])
    assert len(found) == 1 and four[3] in found[0]
    (tmp_path / 'extra').mkdir()
    found = _check_sized(tmp_path / 'extra', monkeypatch, [1440, 1024], four + ['09-Collection-menu-390-light.png'])
    assert len(found) == 1 and 'belongs to no built state' in found[0]


def test_sizes_must_be_distinct_widths_of_the_file(tmp_path, monkeypatch):
    for n, sizes in enumerate(([], [777], [1440, 1440], 'all')):
        (tmp_path / str(n)).mkdir()
        found = _check_sized(tmp_path / str(n), monkeypatch, sizes, [], approved=False)
        assert len(found) == 1 and 'sizes' in found[0], (sizes, found)


def test_the_gate_captures_a_state_at_its_sizes_only(monkeypatch):
    entry = {'screen': 'x', 'state': 'menu', 'sizes': [1440, 1024]}
    assert gate.widths(entry) == [1440, 1024]
    assert [w for w, _, _ in gate.variants(entry)] == [1440, 1440, 1024, 1024]
    assert gate.widths({'screen': 'x', 'state': ''}) == list(gate.WIDTHS)
    monkeypatch.setattr(gate, 'WIDTHS', (390, 1440))
    assert gate.widths(entry) == [1440]


def test_the_states_file_names_its_sized_states_validly():
    from scripts import design_screens as ds
    states = gate.load()
    sized = [e for e in states['states'] if 'sizes' in e]
    assert sized and all(set(e['sizes']) <= set(states['sizes']) for e in sized)
    assert not [p for p in ds.state_problems({e['screen'] for e in states['states']}) if 'sizes' in p]


def test_a_baseline_file_of_no_built_state_is_still_reported(tmp_path, monkeypatch):
    found = _check_states(tmp_path, monkeypatch, False, ['09-Collection-777-light.png'])
    assert len(found) == 1 and 'belongs to no built state' in found[0]


def test_a_change_in_one_colour_channel_is_seen(tmp_path):
    """A pixel differs when ANY channel is off by more than the tolerance (Codex review): a blue shift of 30 weighs only ~3.4 in a grey
    conversion, so the gate must compare the largest channel difference."""
    a, b = tmp_path / 'a.png', tmp_path / 'b.png'
    Image.new('RGB', (40, 40), (100, 100, 100)).save(a)
    Image.new('RGB', (40, 40), (100, 100, 130)).save(b)
    result = gate.compare_images(a, b)
    assert result['differing'] == 1600 and result['share'] == 1.0


def test_chrome_prints_only_the_binary_path_on_stdout(tmp_path, monkeypatch, capsys):
    """check.sh and the gate read stdout as the path: download progress goes to stderr (Codex review)."""
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location('chrome_tool', Path(__file__).resolve().parents[1] / 'scripts' / 'chrome.py')
    chrome = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(chrome)
    monkeypatch.setattr(chrome, 'explicit', lambda: None)
    monkeypatch.setattr(chrome, 'pinned_cached', lambda: None)

    def fake_download():
        print('Downloading Chrome for Testing ...', file=sys.stderr)
        return '/opt/chrome/bin/chrome'
    monkeypatch.setattr(chrome, 'download', fake_download)
    assert chrome.main(['pinned']) == 0
    out = capsys.readouterr()
    assert out.out == '/opt/chrome/bin/chrome\n' and 'Downloading' in out.err
    source = (Path(__file__).resolve().parents[1] / 'scripts' / 'chrome.py').read_text()
    assert "Downloading Chrome for Testing" in source and "file=sys.stderr, flush=True)   # stdout is only the path" in source


def test_chrome_loads_and_honours_chrome_without_fcntl(tmp_path, monkeypatch, capsys):
    """On a platform without fcntl (Windows) the script still loads and an explicit CHROME works (Codex review round 2)."""
    import builtins, importlib.util
    real_import = builtins.__import__

    def no_fcntl(name, *args, **kwargs):
        if name == 'fcntl':
            raise ModuleNotFoundError("No module named 'fcntl'")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', no_fcntl)
    binary = tmp_path / 'chrome.exe'
    binary.write_text('')
    monkeypatch.setenv('CHROME', str(binary))
    spec = importlib.util.spec_from_file_location('chrome_nofcntl', Path(__file__).resolve().parents[1] / 'scripts' / 'chrome.py')
    chrome = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(chrome)
    assert chrome.main(['pinned']) == 0 and capsys.readouterr().out == f'{binary}\n'


def test_the_world_folder_has_the_same_path_every_time():
    """Pages print the data folder (Catalogues & keys), so its path must not change between renders (CI run of #179)."""
    with gate.world_folder() as first:
        assert Path(first).is_dir()
    with gate.world_folder() as second:
        assert Path(second).is_dir()
    try:
        import fcntl  # noqa: F401
    except ImportError:
        return                      # without fcntl (Windows) a temporary folder stands in, by design; nothing fixed to compare
    assert first == second == str(Path(tempfile.gettempdir()) / 'bw-gate-world')


def test_the_footer_shows_the_gate_version_whatever_the_release(monkeypatch):
    """#257: a release bump must not change a baseline, so the gate's world shows a constant in the footer."""
    import urllib.request
    import brickwork.app
    monkeypatch.setattr(brickwork.app, '__version__', '9.9.9')
    with gate.world('demo') as base:
        html = urllib.request.urlopen(base + '/').read().decode()
    assert f'Brick Work ({gate.GATE_VERSION})' in html
    assert '9.9.9' not in html


def test_the_extras_world_adds_to_the_showcase_and_the_demo_world_stays_as_it_was():
    """#268: the instruction, the boxes and the dollar wish live in the `extras` world only; the demo world, whose baselines are approved, holds none."""
    import sqlite3
    held = {}
    for name in ('demo', 'showcase', 'extras'):
        with gate.world(name):
            db = sqlite3.connect(Path(tempfile.gettempdir()) / 'bw-gate-world' / 'brickwork.db')
            held[name] = {
                'stock': db.execute("SELECT count(*) FROM stock WHERE kind IN ('instructions','box')").fetchone()[0],
                'usd': db.execute("SELECT count(*) FROM wish WHERE max_price_currency='USD'").fetchone()[0],
                'orders': db.execute('SELECT count(*) FROM purchase_order').fetchone()[0]}
            db.close()
    assert held['demo'] == {'stock': 0, 'usd': 0, 'orders': 0}
    assert held['showcase'] == {'stock': 0, 'usd': 0, 'orders': 3}
    assert held['extras'] == {'stock': 3, 'usd': 1, 'orders': 3}


def test_every_built_state_path_is_served_in_its_world():
    """#268: a state names a path in a world (ids of copies, lots, orders, stickers); a moved id would capture an error page, so each path must answer 200."""
    import urllib.error
    import urllib.request
    by_world = {}
    for entry in gate.load()['states']:
        if entry['built'] and entry['state'] != 'not-found':    # the 404 page is the state
            by_world.setdefault(entry['world'], []).append(entry)
    for name, entries in by_world.items():
        with gate.world(name) as base:
            for entry in entries:
                try:
                    status = urllib.request.urlopen(base + entry['path'].split('#')[0]).status
                except urllib.error.HTTPError as error:
                    status = error.code
                assert status == 200, f'{gate.label(entry)} in {name}: {entry["path"]} answers {status}'


def test_a_state_covered_by_another_names_a_built_state(tmp_path, monkeypatch):
    """#268: `covered_by` is the record that another built state shows the page; it must name one, and a built state has none."""
    from scripts import design_screens as ds
    states = {'sizes': [1440], 'themes': ['light'], 'states': [
        {'screen': '09-Collection', 'section': 'x', 'state': '', 'built': True, 'approved': False, 'world': 'demo', 'path': '/collection'},
        {'screen': '22-Minifigure-detail', 'section': 'y', 'state': '', 'built': False, 'approved': False, 'reason': 'same page', 'covered_by': '09-Collection'},
        {'screen': '08-Devices', 'section': 'z', 'state': '', 'built': False, 'approved': False, 'reason': 'same page', 'covered_by': '99-Nothing'}]}
    (tmp_path / 'states.json').write_text(json.dumps(states), encoding='utf-8')
    monkeypatch.setattr(ds, 'STATES', tmp_path / 'states.json')
    monkeypatch.setattr(ds, 'BASELINES', tmp_path / 'none')
    found = ds.state_problems({'09-Collection', '22-Minifigure-detail', '08-Devices'})
    assert any('08-Devices' in f and 'covered by 99-Nothing, which is not a built state' in f for f in found)
    assert not any('22-Minifigure' in f for f in found)
