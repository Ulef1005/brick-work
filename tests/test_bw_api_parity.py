"""#47: every operation in the served contract has a route, and every /api/v1 route is in the contract."""
import re

import yaml

from brickwork.core.contract import contract_path
from tests.test_bw_api_m1 import app  # noqa: F401


def spec_operations():
    spec = yaml.safe_load(contract_path().read_text())
    return {(method.upper(), path) for path, methods in spec['paths'].items()
            for method, op in methods.items() if isinstance(op, dict) and 'operationId' in op}


def routed(app):
    found = set()
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith('/api/v1/'):
            continue
        path = re.sub(r'<(?:[a-z]+:)?([a-z_]+)>', r'{\1}', rule.rule.removeprefix('/api/v1'))
        found |= {(m, path) for m in rule.methods - {'HEAD', 'OPTIONS'}}
    return found


def normal(pairs):
    # Path parameter names may differ between spec and route ({no} vs {number}); compare the shape.
    return {(m, re.sub(r'\{[^}]+\}', '{}', p)) for m, p in pairs}


def test_contract_and_routes_agree(app):
    spec, routes = normal(spec_operations()), normal(routed(app))
    assert sorted(spec - routes) == [], 'in the contract without a route'
    assert sorted(routes - spec) == [], 'routed but not in the contract'
