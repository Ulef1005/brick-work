"""Shared test setup: failed-login counters are per process, so each test starts clean."""
from pathlib import Path

import pytest

from tests.quarantine import QUARANTINE

ROOT = Path(__file__).resolve().parents[1]
# Tests that wait for their module's port to the 4.0 store are not collected (tests/quarantine.py; M.8a, issue #110).
collect_ignore = [str(ROOT / name) for name in QUARANTINE]


@pytest.fixture(autouse=True)
def _fresh_login_throttle():
    from brickwork.core import throttle
    throttle.LOGIN.clients.clear()
    throttle.API.clients.clear()
    yield
