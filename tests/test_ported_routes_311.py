"""A browser route that is not listed in `ported.PORTED` answers 503 "Not on the 4.0 store yet" (#311): fail when a registered route is missing."""
from brickwork.web import ported
from tests.app4 import app4, pair  # noqa: F401 (fixtures)

# Endpoints that are meant to stay out of PORTED (none today). Add one here only with its reason.
UNPORTED_ON_PURPOSE = {}


def test_every_registered_browser_route_is_listed_in_ported(app4):
    browser = {rule.endpoint for rule in app4.url_map.iter_rules() if rule.endpoint.startswith('web.') or rule.endpoint == 'index.index'}
    missing = sorted(browser - ported.PORTED - set(UNPORTED_ON_PURPOSE))
    assert not missing, f'add these endpoints to PORTED in brickwork/web/ported.py (or to UNPORTED_ON_PURPOSE with a reason): {missing}'


def test_ported_names_only_registered_endpoints(app4):
    registered = {rule.endpoint for rule in app4.url_map.iter_rules()}
    assert not sorted(ported.PORTED - registered), 'PORTED lists endpoints that no longer exist'
