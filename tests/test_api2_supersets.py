from tests.api2 import app4, coll, pair, world, v2, call, validate  # noqa: F401
from brickwork.core.mcp import Adapter


def test_supersets_contract_and_validation(v2, coll):
    part, colour = coll.item('parts', '970c03'), coll.colour('0')
    response = validate(call(v2, f'/items/{part}/supersets?color={colour}'), 'get_items_by_id_supersets')
    assert response.json['limit'] == 15
    assert response.json['color']['id'] == colour
    for query, status in [('', 400), ('?color=no', 400), (f'?color={colour}&limit=101', 422),
                          (f'?color={colour}&type=parts', 422), (f'?color={colour}&bogus=1', 400)]:
        assert call(v2, f'/items/{part}/supersets{query}').status_code == status
    assert call(v2, f'/items/{part}/supersets?color={colour}', token=None).status_code == 401


def test_generated_mcp_tool():
    adapter = Adapter(None)
    method, path, operation = adapter.tools['get_part_supersets']
    assert (method, path) == ('GET', '/items/{id}/supersets')
    assert next(p for p in operation['parameters'] if p['name'] == 'color')['required']


def test_mcp_colour_schema_keeps_provider_numbers_separate_from_rest_ids():
    adapter = Adapter(None)
    operation = adapter.tools['get_part_supersets'][2]
    assert adapter.schema(operation)['properties']['color'] == {'type': 'integer'}
    assert next(p for p in operation['parameters'] if p['name'] == 'color')['schema']['minimum'] == 1
