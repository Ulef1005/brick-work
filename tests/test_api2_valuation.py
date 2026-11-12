"""API v2 value and gain (#57): `GET /valuation` and `GET /export/insurance.csv`, their scopes, contract and the MCP tool."""
import csv
import io

from brickwork.core import valuation
from tests.api2 import call, stored_token, v2, validate  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401


def seed(coll):
    keep = coll.item('sets', '1000-1')
    coll.price(keep, '61.00', condition='used', sold=14, observed='2026-10-09T08:00:00.000Z')
    return (coll.add_copy('1000-1', condition='used', completeness='complete', price='24.00', currency='EUR', date='2025-03-09'),
            coll.add_copy('1000-1', condition='used', completeness='complete'),
            coll.add_copy('1000-2', condition='used', completeness='complete', price='5', currency='EUR'))


def test_valuation_answers_the_copies_and_the_statistics_as_the_contract_says(v2, coll):
    paid, unpaid, quoteless = seed(coll)
    response = validate(call(v2, '/valuation'), 'get_valuation')
    data = response.json['data']
    rows = {r['id']: r for r in data['copies']}
    assert rows[paid]['paid']['amount'] == '24.00' and rows[paid]['gain'] == {'amount': '37.00', 'percent': 154, 'currency': 'EUR'}
    assert rows[paid]['worth_source'] == 'used' and rows[paid]['worth_date'] == '2026-10-09' and rows[paid]['worth_sales'] == 14
    assert rows[unpaid]['paid'] is None and rows[unpaid]['paid_reason'] == 'no_price_paid' and rows[unpaid]['gain'] is None
    assert rows[quoteless]['worth'] is None and rows[quoteless]['worth_reason'] == 'no_quote'
    stats = data['statistics']
    assert (stats['copies'], stats['comparable_copies'], stats['paid'], stats['worth'], stats['gain'], stats['percent']) == (3, 1, '24.00', '61.00', '37.00', 154)
    assert (stats['without_price_paid'], stats['without_quote'], stats['enough']) == (1, 1, False)
    assert stats['by_theme'][0]['label'] == 'Castle' and stats['by_year'][0]['label'] == '2025'


def test_valuation_with_nothing_in_the_collection_is_valid(v2):
    data = validate(call(v2, '/valuation'), 'get_valuation').json['data']
    assert data['copies'] == [] and data['statistics']['paid'] is None


def test_the_insurance_csv_is_an_attachment_with_every_copy(v2, coll):
    seed(coll)
    response = validate(call(v2, '/export/insurance.csv'), 'get_export_insurance_csv')
    assert response.headers['Content-Disposition'] == 'attachment; filename=brickwork-insurance-report.csv'
    table = list(csv.reader(io.StringIO(response.get_data(as_text=True))))
    assert table[0] == valuation.COLUMNS and len(table) == 4


def test_a_read_token_may_call_both_and_none_may_not(v2, pair, coll):
    seed(coll)
    token = stored_token(pair, ['read'])
    for path in ('/valuation', '/export/insurance.csv'):
        assert call(v2, path, token=token).status_code == 200
        assert call(v2, path, token='').status_code == 401
        assert call(v2, path + '?surprise=1', token=token).status_code == 400
