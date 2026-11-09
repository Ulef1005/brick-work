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
    # DIAGNOSTIC #254 (temporary): which environment variables differ from the worker's start, and which worker this is.
    from tests import conftest
    changed = sorted(k for k in set(os.environ) | set(conftest.START_ENV) if os.environ.get(k) != conftest.START_ENV.get(k))
    lines.append(f'  diagnostic: worker {os.environ.get("PYTEST_XDIST_WORKER")}, env changed since start: '
                 + ', '.join(f'{k}={os.environ.get(k)!r} (was {conftest.START_ENV.get(k)!r})' for k in changed if k not in ('PYTEST_CURRENT_TEST',)))
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
