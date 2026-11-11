"""The screenshot gate (D3, #160; ADR 0022): renders the built app per screen state and compares it with the approved baseline captures.

    python3 scripts/screen_gate.py capture [SCREEN ...]   write CANDIDATE baselines for the built states into
                                                          design/screens/approval/baselines/<NN-Screen>/ (all of them, or the named screens)
    python3 scripts/screen_gate.py agree                  render every approved state on one Chrome process and on four, compare the two renders (#267)
    python3 scripts/screen_gate.py compare                render every built state with `approved: true`, compare it with its baseline, write
                                                          the diffs of the failures; print the gate summary; exit 1 on any difference
    python3 scripts/screen_gate.py summary                the summary only (no rendering)

The states are listed in design/screens/states.json (hand-kept; the maintainer sets `approved`, nobody else). A state is a screen section of
design/screens/manifest.json reached in the built app by a path in an invented fixture world, at 1440 / 1024 / 390, light and dark. The
baselines are captures of the BUILT APP, never the design frames, which stay the design record. The app runs on invented data only
(brickwork/demo/dataset.py on design/sources/test-data/; never anything under data/), with the clock fixed, animations off and the bundled
fonts, rendered by the pinned Chrome for Testing (scripts/chrome.py). Run it from the app's venv (it imports the app)."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import datetime as dt
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from brickwork.demo.clock import FIXED_NOW, FrozenDatetime, freeze_clock, thaw_clock  # noqa: E402,F401  (the demo dataset's own "now")
STATES = ROOT / 'design' / 'screens' / 'states.json'
MANIFEST = ROOT / 'design' / 'screens' / 'manifest.json'
BASELINES = ROOT / 'design' / 'screens' / 'approval' / 'baselines'
DIFFS = ROOT / 'build' / 'screen-diffs'
WIDTHS = (1440, 1024, 390)
THEMES = ('light', 'dark')
MAX_HEIGHT = 1600   # CSS px: a longer page is clipped to its first 1600 px (keeps the baselines small; a state may set its own `max`)
TOLERANCE = {'channel': 3, 'pixels': 0.0005}   # a pixel differs when a channel is off by more than 3/255; a capture differs when more than 0.05 % do


def load() -> dict:
    return json.loads(STATES.read_text(encoding='utf-8'))


def filename(screen: str, state: str, width: int, theme: str) -> str:
    return f'{screen}{"-" + state if state else ""}-{width}-{theme}.png'


def variants(entry: dict):
    """(width, theme, baseline path) of every capture of a state."""
    for width in WIDTHS:
        for theme in THEMES:
            yield width, theme, BASELINES / entry['screen'] / filename(entry['screen'], entry['state'], width, theme)


def label(entry: dict) -> str:
    return entry['screen'] + (f' [{entry["state"]}]' if entry['state'] else '')


# ---------- the app on the invented world ----------

@contextmanager
def world_folder():
    """The world's data folder, always at the same path: pages show it (Catalogues & keys prints the database and media paths), so a random
    temporary name made that state differ on every render. One run at a time holds it, through a lock beside it; without fcntl (Windows) a
    temporary folder stands in, whose pages are then not comparable."""
    try:
        import fcntl
    except ImportError:
        with tempfile.TemporaryDirectory(prefix='bw-gate-') as scratch:
            yield scratch
        return
    base = Path(tempfile.gettempdir())
    folder = base / 'bw-gate-world'
    with open(base / 'bw-gate-world.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir()
            yield str(folder)
        finally:
            shutil.rmtree(folder, ignore_errors=True)
            fcntl.flock(lock, fcntl.LOCK_UN)


# The version the footer shows in the gate's world. The baselines were rendered when the footer said 1.0.0; the constant keeps that text for good.
GATE_VERSION = '1.0.0'


@contextmanager
def world(name: str, warm_up: list[str] = ()):
    """Serve the invented world `name` on 127.0.0.1 ('demo', the gate's; 'showcase', the same plus the richer layer of the exported demo and the site's pictures); yields its base URL. The `warm_up` paths are requested once before the clock is frozen,
    so that every module a page imports lazily has been imported by then."""
    from brickwork.demo import checks, dataset, showcase
    saved = {k: os.environ.get(k) for k in ('BW_DB_PATH', 'BW_EMBEDDED_WORKER', 'BW_ALLOW_NO_LOGIN', 'BW_AUTHENTICATION_PASSWORD')}
    with world_folder() as scratch:
        if name not in ('demo', 'showcase'):
            raise ValueError(f'unknown world {name}')
        store = Path(scratch) / 'brickwork.db'
        dataset.build(store, layer=showcase.layer() if name == 'showcase' else None)
        checks.stage(store, showcase.CHECKS if name == 'showcase' else None)
        from brickwork.demo.export import make_app
        app = make_app(store)
        app.config['GATE_SHOWN_VERSION'] = GATE_VERSION   # the footer shows a constant, so a release never changes a baseline (#257)
        client = app.test_client()
        for path in warm_up:
            client.get(path)
        patched = freeze_clock()
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        from werkzeug.serving import make_server
        server = make_server('127.0.0.1', 0, app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            yield f'http://127.0.0.1:{server.server_port}'
        finally:
            thaw_clock(patched)
            server.shutdown()
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def workers() -> int:
    """How many Chrome processes render at once: 1 unless BW_GATE_WORKERS asks for more. The approved baselines were rendered in ONE Chrome session,
    and state a session carries from page to page (storage, cached fonts and styles) shows in some captures: rendered in fresh sessions of 12 jobs,
    52-Place's drop-down text sat 1 px lower on Linux and failed the gate (PR #261; ADR 0024). So the gate and the baselines render in one session;
    BW_GATE_WORKERS > 1 is for quick local review images only, never for a baseline or a deciding run."""
    try:
        wanted = int(os.environ.get('BW_GATE_WORKERS', ''))
    except ValueError:
        wanted = 0
    return max(1, wanted or 1)


def run_jobs(jobs: list[dict], scratch: str, chrome: str) -> None:
    """Run the capture jobs on `workers()` Chrome processes at once. Each job is independent (its own viewport, theme and navigation; the clock, fonts and
    animation settings are set per process by capture_screens.cjs), so the captures do not depend on which process takes them. The jobs go out in
    batches of consecutive jobs (a state's variants stay together) that idle processes pick up, so one slow batch does not hold the others back."""
    batch = 12 if workers() > 1 else max(1, len(jobs))   # one worker: every job in one Chrome session, as the baselines were made
    chunks = [jobs[i:i + batch] for i in range(0, len(jobs), batch)]
    clock = FIXED_NOW.isoformat().replace('+00:00', 'Z')

    def run(item):
        number, chunk = item
        spec = Path(scratch) / f'jobs-{number}.json'
        spec.write_text(json.dumps({'deterministic': True, 'now': clock, 'jobs': chunk}))
        result = subprocess.run(['node', str(ROOT / 'scripts' / 'capture_screens.cjs'), chrome, str(spec)], cwd=ROOT,
                                capture_output=True, text=True, timeout=1800)
        if result.returncode:
            raise RuntimeError('capture_screens.cjs failed:\n' + result.stdout[-2000:] + result.stderr[-2000:])

    with ThreadPoolExecutor(max_workers=min(workers(), len(chunks) or 1)) as pool:
        list(pool.map(run, enumerate(chunks)))   # map re-raises the first failure; the rest of the pool finishes its batches first


def render(entries: list[dict], out_for, chrome: str) -> list[Path]:
    """Render every variant of the given states with scripts/capture_screens.cjs; `out_for(entry, width, theme)` is the target path."""
    written = []
    by_world: dict[str, list[dict]] = {}
    for entry in entries:
        by_world.setdefault(entry['world'], []).append(entry)
    for name, group in by_world.items():
        with world(name, sorted({e['path'] for e in group})) as base, tempfile.TemporaryDirectory(prefix='bw-jobs-') as scratch:
            jobs = []
            for entry in group:
                for width in WIDTHS:
                    for theme in THEMES:
                        target = out_for(entry, width, theme)
                        written.append(target)
                        jobs.append({'url': base + entry['path'], 'out': str(target), 'width': width, 'theme': theme,
                                     'max': MAX_HEIGHT, **{k: entry[k] for k in ('wait', 'script', 'max') if k in entry}})
            run_jobs(jobs, scratch, chrome)
    return written


# ---------- comparing ----------

def compare_images(expected: Path, actual: Path, diff: Path | None = None) -> dict:
    """{'size_differs', 'differing', 'total', 'share'} of two PNGs; writes `diff` (the actual, differing pixels in red) when they differ."""
    from PIL import Image, ImageChops
    with Image.open(expected) as a, Image.open(actual) as b:
        a, b = a.convert('RGB'), b.convert('RGB')
        if a.size != b.size:
            return {'size_differs': True, 'differing': None, 'total': None, 'share': 1.0, 'sizes': (a.size, b.size)}
        r, g, bl = ImageChops.difference(a, b).split()
        delta = ImageChops.lighter(ImageChops.lighter(r, g), bl)          # the largest channel difference per pixel, not a weighted grey
        mask = delta.point(lambda v: 255 if v > TOLERANCE['channel'] else 0)
        differing = mask.histogram()[255]
        total = a.size[0] * a.size[1]
        share = differing / total
        if share > TOLERANCE['pixels'] and diff is not None:
            diff.parent.mkdir(parents=True, exist_ok=True)
            red = Image.new('RGB', a.size, (220, 30, 30))
            Image.composite(red, Image.blend(b, Image.new('RGB', b.size, (255, 255, 255)), 0.6), mask).save(diff)
        return {'size_differs': False, 'differing': differing, 'total': total, 'share': share}


def counts(states: dict) -> dict:
    entries = states['states']
    built = [e for e in entries if e['built']]
    return {'states': len(entries), 'built': len(built), 'approved': [e for e in built if e['approved']],
            'pending': [e for e in built if not e['approved']], 'not_built': [e for e in entries if not e['built']]}


def summary_lines(states: dict, checked: int, differ: list[str]) -> list[str]:
    c = counts(states)
    lines = [f'Screenshot gate: {checked} approved states checked, {len(differ)} differ, {len(c["pending"])} candidates pending approval, '
             f'{len(c["not_built"])} states not built']
    lines += [f'  differs: {item}' for item in differ]
    if not c['approved']:
        lines.append(f'  0 approved states, {len(c["pending"])} candidates pending approval (approval is the maintainer\'s, through a review artifact)')
    return lines


def run_compare(chrome: str) -> tuple[list[str], int, list[str]]:
    """(summary lines, states checked, differing variants). Renders the approved states into a scratch folder and compares them."""
    states = load()
    approved = counts(states)['approved']
    differ = []
    if approved:
        shutil.rmtree(DIFFS, ignore_errors=True)
        with tempfile.TemporaryDirectory(prefix='bw-gate-shots-') as scratch:
            def out_for(entry, width, theme):
                return Path(scratch) / entry['screen'] / filename(entry['screen'], entry['state'], width, theme)
            render(approved, out_for, chrome)
            for entry in approved:
                for width, theme, baseline in variants(entry):
                    actual = out_for(entry, width, theme)
                    if not baseline.is_file():
                        differ.append(f'{label(entry)} {width} {theme}: baseline {baseline.relative_to(ROOT)} is missing')
                        continue
                    diff = DIFFS / entry['screen'] / ('diff-' + baseline.name)
                    if os.environ.get('BW_GATE_KEEP'):   # keep the captures for inspection (a folder; nothing else reads them)
                        keep = Path(os.environ['BW_GATE_KEEP']) / entry['screen'] / actual.name
                        keep.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(actual, keep)
                    result = compare_images(baseline, actual, diff)
                    if result['size_differs']:
                        differ.append(f'{label(entry)} {width} {theme}: size {result["sizes"][1]} instead of {result["sizes"][0]}')
                    elif result['share'] > TOLERANCE['pixels']:
                        differ.append(f'{label(entry)} {width} {theme}: {result["differing"]} of {result["total"]} pixels differ '
                                      f'({result["share"]:.2%}); diff image {diff.relative_to(ROOT)}')
    return summary_lines(states, len(approved), differ), len(approved), differ


def run_agree(chrome: str, parallel: int = 4) -> tuple[list[str], int]:
    """(summary lines, captures compared): renders every approved state twice, on one Chrome process and on `parallel` of them, and lists each capture
    whose two renders differ by more than the gate's tolerance. The proof that a capture does not depend on the session (#267); CI runs it by hand
    (the `gate-agree` workflow), and BW_GATE_KEEP keeps both renders."""
    approved = counts(load())['approved']
    differ, total = [], 0
    saved = os.environ.get('BW_GATE_WORKERS')
    with tempfile.TemporaryDirectory(prefix='bw-agree-') as scratch:
        renders = {}
        try:
            for mode, count in (('serial', 1), ('parallel', parallel)):
                os.environ['BW_GATE_WORKERS'] = str(count)
                renders[mode] = render(approved, lambda e, w, t, m=mode: Path(scratch) / m / e['screen'] / filename(e['screen'], e['state'], w, t), chrome)
        finally:
            if saved is None:
                os.environ.pop('BW_GATE_WORKERS', None)
            else:
                os.environ['BW_GATE_WORKERS'] = saved
        for one, two in zip(renders.get('serial', []), renders.get('parallel', [])):
            total += 1
            result = compare_images(one, two)
            if os.environ.get('BW_GATE_KEEP'):
                for tag, path in (('serial', one), ('parallel', two)):
                    keep = Path(os.environ['BW_GATE_KEEP']) / tag / path.parent.name / path.name
                    keep.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, keep)
            if result['size_differs'] or result['share'] > TOLERANCE['pixels']:
                differ.append(f'{one.name}: ' + ('size differs' if result['size_differs'] else f'{result["differing"]} of {result["total"]} pixels ({result["share"]:.2%})'))
    return [f'Serial against {parallel}-process render: {total} captures compared, {len(differ)} differ'] + [f'  differs: {d}' for d in differ], total


def capture(selected: list[str], chrome: str) -> int:
    states = load()
    todo = [e for e in states['states'] if e['built'] and (not selected or e['screen'] in selected or e['screen'].split('-')[0] in selected)]
    for entry in todo:
        if entry['approved']:
            print(f'SKIP {label(entry)}: approved baselines are replaced only by the maintainer (set approved to false first)')
    todo = [e for e in todo if not e['approved']]
    written = render(todo, lambda entry, width, theme: BASELINES / entry['screen'] / filename(entry['screen'], entry['state'], width, theme), chrome)
    print(f'Wrote {len(written)} candidate captures for {len(todo)} states')
    return 0


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else 'summary'
    if mode == 'summary':
        print('\n'.join(summary_lines(load(), 0, [])))
        return 0
    chrome = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'chrome.py'), 'pinned'], capture_output=True, text=True)
    if chrome.returncode:
        print(chrome.stderr.strip())
        return 1
    chrome = chrome.stdout.strip()
    if mode == 'capture':
        return capture(argv[1:], chrome)
    if mode == 'agree':
        lines, total = run_agree(chrome)
        print('\n'.join(lines))
        return 1 if len(lines) > 1 or not total else 0
    if mode == 'compare':
        lines, _, differ = run_compare(chrome)
        print('\n'.join(lines))
        return 1 if differ else 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
