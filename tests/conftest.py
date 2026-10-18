"""Shared test setup: failed-login counters are per process, so each test starts clean."""
import pytest


@pytest.fixture(autouse=True)
def _fresh_login_throttle():
    from brickwork.core import throttle
    throttle.LOGIN.clients.clear()
    throttle.API.clients.clear()
    yield
