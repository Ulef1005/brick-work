"""Shared test setup: failed-login counters are per process, so each test starts clean."""
import os
from pathlib import Path
import re

import pytest

from tests import rendered
from tests.quarantine import QUARANTINE
from tests.xdist_groups import pytest_collection_modifyitems  # noqa: F401  (hook: the xdist groups, tests/xdist_groups.py)

ROOT = Path(__file__).resolve().parents[1]
START_ENV = dict(os.environ)   # DIAGNOSTIC #254 (temporary): the worker's environment at start, compared by the screen gate test
# Tests that wait for their module's port to the 4.0 store are not collected (tests/quarantine.py; M.8a, issue #110).
collect_ignore = [str(ROOT / name) for name in QUARANTINE]


@pytest.fixture(autouse=True)
def _fresh_login_throttle():
    from brickwork.core import throttle
    throttle.LOGIN.clients.clear()
    throttle.API.clients.clear()
    yield


@pytest.fixture(autouse=True)
def _pipeline_handlers_restored():
    """Starting a drainer registers the source handlers process-wide (`core.source_ops.register_handlers`); a test must not leave them
    for the next one, whose pipeline would then call real sources."""
    from brickwork.core import pipeline
    saved = dict(pipeline.HANDLERS)
    yield
    pipeline.HANDLERS.clear()
    pipeline.HANDLERS.update(saved)


@pytest.fixture(autouse=True)
def _current_item(request):
    """Tell tests/rendered.py which test runs, so that rendered.chrome() can insist on the xdist group (tests/rendered.py)."""
    rendered.CURRENT = request.node
    yield
    rendered.CURRENT = None


def pytest_runtest_logreport(report):
    """Record the rendered tests skipped under BW_SKIP_RENDERED=1 (tests/rendered.py) in the file named by BW_RENDERED_SKIPS, one per line,
    so that scripts/check.sh can name every one of them in its summary. Under pytest-xdist the hook runs in each worker and again in the
    controller, which receives every worker's reports: only the controller writes, and an xdist group suffix (`@rendered`) is cut off the name."""
    target = os.environ.get('BW_RENDERED_SKIPS')
    if os.environ.get('PYTEST_XDIST_WORKER'):
        return
    if target and report.skipped and report.when in ("setup", "call") and rendered.MARK in str(report.longrepr):
        with open(target, 'a', encoding='utf-8') as out:
            out.write(re.sub(r'@[\w-]+$', '', report.nodeid) + '\n')
