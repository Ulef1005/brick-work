"""What a rendered test needs (node, a browser) and what happens when it is missing (D3, #160; ADR 0022).

A test that runs JavaScript or draws a page calls `need_node()` or `chrome()` first. When the tool is missing the test FAILS, never skips
silently. Only `BW_SKIP_RENDERED=1` turns the failure into a skip, and `tests/conftest.py` records every such skip so that
`scripts/check.sh` can name it in its summary.

Under pytest-xdist (`pytest -n auto --dist loadgroup`, scripts/check.sh) a test that draws a page or renders the screen gate shares Chrome
and the gate's world folder (/tmp/bw-gate-world, one lock) with the others, so it carries `rendered.group` (`@rendered.group` on a test, or
`pytestmark = rendered.group` on a module): every marked test runs on one worker, one at a time. `chrome()` fails a test that lacks the mark."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
MARK = 'rendered test skipped (BW_SKIP_RENDERED=1):'
GROUP = 'rendered'
group = pytest.mark.xdist_group(GROUP)
CURRENT = None   # the running test item, set by tests/conftest.py, so that chrome() can check its mark


def skipping() -> bool:
    return os.environ.get('BW_SKIP_RENDERED') == '1'


def unavailable(reason: str):
    if skipping():
        pytest.skip(f'{MARK} {reason}')
    pytest.fail(f'{reason}. Rendered tests need it; install it, or set BW_SKIP_RENDERED=1 to skip them (check.sh then names each one).',
                pytrace=False)


def need_node() -> str:
    """The node binary; the test fails (or, with BW_SKIP_RENDERED=1, skips) when there is none."""
    if os.environ.get('BW_NO_CHROME') == '1':   # a pull request runs no Node and no Chrome test (the maintainer, 2026-11-13); check.sh names each skip
        pytest.skip(f'{MARK} Node is switched off (BW_NO_CHROME=1)')
    node = shutil.which('node')
    if not node:
        unavailable('node is not installed')
    return node


def chrome(*, pinned: bool = False) -> str:
    """The Chrome binary (scripts/chrome.py: CHROME, the pinned cache, a system Chrome, else the pinned download).
    `pinned`: the screenshot gate's browser, whose pixels the baselines were made with."""
    if os.environ.get('BW_NO_CHROME') == '1':   # CI switches every Chrome test off on a pull request (Ulf, 2026-11-13); check.sh names each skip
        pytest.skip(f'{MARK} Chrome is switched off (BW_NO_CHROME=1)')
    need_node()
    if CURRENT is not None and not any(m.args[:1] == (GROUP,) for m in CURRENT.iter_markers('xdist_group')):
        pytest.fail(f'{CURRENT.nodeid} uses Chrome but is not in the xdist group: put `@rendered.group` on it (tests/rendered.py), '
                    'so that it does not run beside the other Chrome tests and the gate\'s world folder', pytrace=False)
    env = os.environ.get('CHROME') or os.environ.get('BW_COLLECTION_CHROME')
    if env and Path(env).is_file():
        return env
    result = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'chrome.py'), 'pinned' if pinned else 'ensure'],
                            capture_output=True, text=True, timeout=600)
    if result.returncode:
        unavailable(result.stderr.strip().splitlines()[-1] if result.stderr.strip() else 'no Chrome found')
    return result.stdout.strip().splitlines()[-1]


def dump_dom(chrome_binary: str, url: str, **options) -> str:
    """`chrome --headless=new --dump-dom URL` with the bounded retry of scripts/chrome.py (#293); a run that failed every attempt fails the test
    with the reason and the last stderr lines. Use it instead of calling Chrome by hand: a start that stalls on macOS is run again."""
    from scripts import chrome as chrome_module
    try:
        return chrome_module.dump_dom(chrome_binary, url, **options)
    except RuntimeError as error:
        pytest.fail(str(error), pytrace=False)
