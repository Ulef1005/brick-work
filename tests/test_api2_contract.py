"""The v2 contract against itself, the code and v1 (M.11a, issue #113). Ported from test_bw_api_m0's contract tests: the error table and
the decisions the OpenAPI file records."""
from pathlib import Path
import re

from scripts.check_api_contract import check_v2, load_yaml
from brickwork import api2
from brickwork.api import transport
from brickwork.core import errors
from tests.api2 import PREFIX, call, v2  # noqa: F401
from tests.api2 import app4, coll, pair  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
V2 = load_yaml((ROOT / 'docs/brickwork/openapi-v2.yaml').read_text())
V1 = load_yaml((ROOT / 'docs/brickwork/openapi-v1.yaml').read_text())
OPERATIONS = {(m.upper(), p): o for p, ms in V2['paths'].items() for m, o in ms.items() if isinstance(o, dict)}


def test_error_codes_match_the_contract():
    text = (ROOT / 'docs/brickwork/api-v2.md').read_text().split('## Appendix A: error codes')[1]
    assert dict((code, int(status)) for code, status in re.findall(r'\| `([a-z_]+)` \| (\d+) \|', text)) == errors.HTTP_STATUS
    assert V2['x-error-status'] == errors.HTTP_STATUS
    for code, status in errors.HTTP_STATUS.items():
        cls = getattr(errors, 'NotImplementedYet' if code == 'not_implemented' else ''.join(w.capitalize() for w in code.split('_')))
        assert cls().code == code and cls().status == status
    assert {'ambiguous': 409, 'merged': 409, 'unidentified': 422, 'moved': 307} == {c: errors.HTTP_STATUS[c] for c in ('ambiguous', 'merged', 'unidentified', 'moved')}


def test_the_contract_records_the_v2_decisions():
    text = (ROOT / 'docs/brickwork/openapi-v2.yaml').read_text()
    assert V2['servers'][0]['url'] == '/api/v2' and V2['openapi'].startswith('3.1')
    assert 'actor=token name' in text and 'writeOnly: true' in text
    assert {'origin', 'saved_at', 'configured'} <= set(V2['components']['schemas']['KeyState']['properties'])      # a key's status, never its value
    for path in ('/items/{id}', '/sets/by-number/{no}', '/parts/by-number/{no}', '/minifigures/by-number/{no}', '/lookup', '/items/{id}/links',
                 '/items/{id}/provider-status', '/items/{id}/merge', '/items/{id}/unmerge', '/copies/{id}/inventory', '/copies/{id}/inventory/pending',
                 '/catalogue/status', '/settings', '/links'):
        assert path in V2['paths'], path
    assert OPERATIONS[('DELETE', '/copies/{id}/inventory/pending')] and OPERATIONS[('POST', '/copies/{id}/inventory')]
    assert not any(p.startswith('/items/{type}') for p in V2['paths'])


def test_no_body_names_an_item_by_type_and_number_any_more():
    banned = {'item_type', 'item_no', 'child_item_type', 'child_item_no', 'minifig_no', 'parent_minifig_type'}
    left = {name: sorted(banned & set(sc.get('properties', {}))) for name, sc in V2['components']['schemas'].items() if banned & set(sc.get('properties', {}))}
    assert not left, left
    assert 'ItemTypeLetter' not in V2['components']['schemas'] and 'Unresolved' not in V2['components']['schemas'] and 'IdMatch' not in V2['components']['schemas']
    assert '"?"' not in (ROOT / 'docs/brickwork/openapi-v2.yaml').read_text()


def test_the_item_and_colour_schemas_are_design_7():
    item, color = V2['components']['schemas']['Item'], V2['components']['schemas']['Color']
    assert item['required'] == ['id', 'kind', 'name', 'unidentified', 'bricklink', 'rebrickable']
    assert set(item['properties']) == {'id', 'kind', 'name', 'unidentified', 'bricklink', 'rebrickable', 'color'}
    assert V2['components']['schemas']['ItemBrickLink']['required'] == ['type', 'no', 'color_id', 'preferred']
    assert color['required'] == ['id', 'name', 'rgb', 'bricklink_id', 'rebrickable_id'] and set(color['properties']) == set(color['required'])
    assert V2['components']['schemas']['Wish']['properties']['id']['type'] == 'string'
    assert 'inventory' in V2['components']['schemas']['Copy']['properties']
    assert set(V2['components']['schemas']['CopyInventory']['properties']) == {'source', 'version', 'ordinal', 'of', 'pending', 'changed_since_build'}
    assert 'prefer_bricklink_inventory' in V2['components']['schemas']['Settings']['properties']
    assert V2['components']['responses']['Moved']['headers']['Cache-Control']


def test_every_v1_operation_is_carried_or_dropped_with_a_reason():
    v1_ids = {o['operationId'] for ms in V1['paths'].values() for o in ms.values() if isinstance(o, dict)}
    carried = {o['x-v1'] for o in OPERATIONS.values() if 'x-v1' in o}
    dropped = v1_ids - carried
    assert carried <= v1_ids and len(carried) == len([o for o in OPERATIONS.values() if 'x-v1' in o])
    assert dropped == {'get_unresolved', 'post_unresolved_resolve', 'get_id_matches'}
    doc = (ROOT / 'docs/brickwork/api-v2.md').read_text().split('### 3.3 Dropped v1 operations')[1].split('## 4.')[0]
    for path in ('/unresolved`', '/unresolved/resolve`', '/id-matches`'):
        assert path in doc
    assert (len(v1_ids), len(OPERATIONS), len(carried)) == (179, 189, 176)


def test_every_operation_names_a_piece_a_scope_and_a_unique_id():
    ids = [o['operationId'] for o in OPERATIONS.values()]
    assert len(ids) == len(set(ids))
    assert {o['x-piece'] for o in OPERATIONS.values()} == {'M.11a', 'M.11b', 'M.11c', 'M.11d'}
    for (method, path), op in OPERATIONS.items():
        scope = op['security'][0]['bearerAuth'][0] if op.get('security') else None
        assert scope in (None, 'read', 'write', 'admin'), (method, path)
        if method == 'GET':
            assert scope in (None, 'read', 'admin'), (method, path)
        else:
            assert scope in ('write', 'admin'), (method, path)
    assert {p for (m, p), o in OPERATIONS.items() if o['x-piece'] == 'M.11a'} == {
        '/health', '/version', '/openapi.yaml', '/me', '/items/{id}', '/sets/by-number/{no}', '/parts/by-number/{no}', '/minifigures/by-number/{no}', '/lookup'}


def test_admin_scopes_are_v1s():
    from brickwork.api import ADMIN
    admin_v1 = {x.split('.', 1)[1] for x in ADMIN}
    admin_v2 = {o['x-v1'] for o in OPERATIONS.values() if 'x-v1' in o and o['security'] and o['security'][0]['bearerAuth'][0] == 'admin'}
    assert admin_v1 == admin_v2


def test_the_check_script_agrees_with_the_routes_and_the_doc(capsys):
    assert check_v2(False) == 0
    assert 'API v2: 9 operations implemented, 180 answer 501' in capsys.readouterr().out


def test_the_audit_origin_of_a_request_is_api_and_the_token_name(v2, monkeypatch, coll):
    from brickwork.core.sources.base import AUDIT_ACTOR, AUDIT_ORIGIN
    seen = []
    real = api2.items.serializers.item

    def spy(db, item_id, secrets=None):
        seen.append((AUDIT_ORIGIN.get(), AUDIT_ACTOR.get()))
        return real(db, item_id, secrets)
    monkeypatch.setattr(api2.items.serializers, 'item', spy)
    assert call(v2, f"/items/{coll.item('sets', '2070-1')}").status_code == 200
    assert seen == [('api', 'bootstrap')]
    assert AUDIT_ORIGIN.get() == 'import' and AUDIT_ACTOR.get() is None               # and the request leaves nothing behind


def test_v2_shares_v1s_transport_helpers():
    assert api2.transport is transport
    from brickwork import api
    assert api.problem is transport.problem and api.read_only is transport.read_only
