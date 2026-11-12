"""Value and gain per copy, the Statistics figures and the insurance report (#57): `core/valuation.py`. Invented data on the rich fixture catalogue.

Sets: `1000-1` "Syn Castle Keep" (Castle, 1990), `1000-2` and `2070-1` (Duplo). Quotes are sold averages recorded with `coll.price`."""
import csv
from datetime import datetime, timezone
import io
import json

import pytest

from brickwork.core import collection, valuation
from tests.app4 import STAMP, app4, coll, pair, world  # noqa: F401  (the fixtures)

TODAY = datetime(2026, 10, 27, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(collection, 'now', lambda: TODAY)
    monkeypatch.setattr(valuation, 'now', lambda: TODAY)


def rate(coll, currency, per_eur, day='2026-10-20'):
    coll.sql('INSERT OR REPLACE INTO exchange_rate(currency, per_eur, as_of, source) VALUES(?,?,?,?)', (currency, per_eur, day, 'manual'))


def one(coll, copy_id):
    return next(r for r in valuation.copies(coll.db) if r['id'] == copy_id)


def test_paid_worth_and_gain_of_a_used_copy(coll):
    coll.price(coll.item('sets', '1000-1'), '61.00', condition='used', sold=14, observed='2026-10-09T08:00:00.000Z')
    copy = coll.add_copy('1000-1', condition='used', completeness='complete', price='24.00', currency='EUR', date='2025-03-09')
    r = one(coll, copy)
    assert (r['number'], r['name'], r['year'], r['theme']) == ('1000-1', 'Syn Castle Keep', 1990, 'Castle')
    assert r['paid']['amount'] == 24 and str(r['paid']['amount']) == '24.00' and r['paid']['currency'] == 'EUR' and not r['paid']['converted']
    assert str(r['worth']['amount']) == '61.00' and r['worth_source'] == 'used' and r['worth_date'] == '2026-10-09'
    assert (r['worth_sales'], r['worth_stale'], r['worth_price_source'], r['worth_discount_pct']) == (14, False, 'bricklink', None)
    assert (str(r['gain']['amount']), r['gain']['percent'], r['gain']['currency']) == ('37.00', 154, 'EUR')
    assert (r['paid_reason'], r['worth_reason']) == (None, None)


def test_a_loss_is_a_negative_gain(coll):
    coll.price(coll.item('sets', '1000-1'), '790.00', condition='new', sold=3)
    copy = coll.add_copy('1000-1', condition='new', completeness='sealed', price='849.99', currency='EUR')
    gain = one(coll, copy)['gain']
    assert (str(gain['amount']), gain['percent']) == ('-59.99', -7)


def test_a_sealed_or_new_copy_is_valued_on_the_new_average_and_other_copies_on_the_used_one(coll):
    keep = coll.item('sets', '1000-1')
    coll.price(keep, '30.00', condition='used', sold=4)
    coll.price(keep, '90.00', condition='new', sold=2)
    sealed = coll.add_copy('1000-1', condition='used', completeness='sealed', price='10', currency='EUR')
    new = coll.add_copy('1000-1', condition='new', completeness='complete', price='10', currency='EUR')
    used = coll.add_copy('1000-1', condition='used', completeness='complete', price='10', currency='EUR')
    unknown = coll.add_copy('1000-1', price='10', currency='EUR')
    assert [(one(coll, c)['worth_source'], str(one(coll, c)['worth']['amount'])) for c in (sealed, new, used, unknown)] == [
        ('new', '90.00'), ('new', '90.00'), ('used', '30.00'), ('used', '30.00')]


def test_an_incomplete_copy_has_the_incomplete_set_discount_of_prices(coll):
    coll.price(coll.item('sets', '1000-1'), '100.00', condition='used', sold=5)
    coll.sql("INSERT OR REPLACE INTO setting(key,value) VALUES('incomplete_discount_pct','25')")
    copy = coll.add_copy('1000-1', condition='used', completeness='incomplete', price='50', currency='EUR')
    r = one(coll, copy)
    assert str(r['worth']['amount']) == '75.00' and r['worth_discount_pct'] == 25 and (str(r['gain']['amount']), r['gain']['percent']) == ('25.00', 50)


def test_the_copys_own_value_wins_and_is_marked_override(coll):
    coll.price(coll.item('sets', '1000-1'), '61.00', condition='used', sold=14)
    copy = coll.add_copy('1000-1', condition='used', completeness='complete', price='24.00', currency='EUR', current_value='70.00', current_value_currency='EUR')
    r = one(coll, copy)
    assert (r['worth_source'], str(r['worth']['amount']), r['worth_date'], r['worth_stale'], r['worth_sales']) == ('override', '70.00', None, False, None)


def test_no_price_paid_means_no_paid_and_no_gain_for_none_and_for_zero(coll):
    coll.price(coll.item('sets', '1000-1'), '61.00', condition='used', sold=2)
    none = coll.add_copy('1000-1', condition='used', completeness='complete')
    zero = coll.add_copy('1000-1', condition='used', completeness='complete', price='0.00', currency='EUR')
    for copy in (none, zero):
        r = one(coll, copy)
        assert (r['paid'], r['paid_original'], r['paid_reason'], r['gain']) == (None, None, 'no_price_paid', None)
        assert str(r['worth']['amount']) == '61.00'


def test_no_quote_means_no_worth_and_no_gain(coll):
    copy = coll.add_copy('1000-2', condition='used', completeness='complete', price='20', currency='EUR')
    r = one(coll, copy)
    assert (r['worth'], r['worth_reason'], r['worth_source'], r['gain']) == (None, 'no_quote', None, None) and str(r['paid']['amount']) == '20.00'


def test_only_a_sold_average_for_the_copys_condition_counts(coll):
    keep = coll.item('sets', '1000-1')
    coll.price(keep, '55.00', condition='used', guide='stock', qty=3)                        # listings are no sold average
    coll.price(keep, '99.00', condition='new', sold=2)                                       # another condition
    coll.price(keep, '5.00', condition='used', sold=2, slot='boxed', region='DE')            # with box
    coll.price(keep, '7.00', condition='used', sold=2, region='EU', currency='EUR', error='x')
    copy = coll.add_copy('1000-1', condition='used', completeness='complete', price='20', currency='EUR')
    assert one(coll, copy)['worth'] is None


def test_a_stale_quote_still_counts_and_is_marked_by_the_prices_rule(coll):
    coll.sql("INSERT OR REPLACE INTO source_freshness(source,kind,max_age_days) VALUES('bricklink','prices',7)")
    keep = coll.item('sets', '1000-1')
    coll.price(keep, '61.00', condition='used', sold=14, observed='2026-10-01T00:00:00.000Z')              # 26 days
    copy = coll.add_copy('1000-1', condition='used', completeness='complete', price='24.00', currency='EUR')
    r = one(coll, copy)
    assert r['worth_stale'] is True and str(r['worth']['amount']) == '61.00' and r['worth_date'] == '2026-10-01'
    coll.price(keep, '62.00', condition='used', sold=14, observed='2026-10-25T00:00:00.000Z')
    assert one(coll, copy)['worth_stale'] is False


def test_a_price_paid_in_another_currency_is_converted_with_its_rate_and_date(coll):
    coll.price(coll.item('sets', '1000-1'), '61.00', condition='used', sold=2)
    rate(coll, 'USD', '1.08')
    copy = coll.add_copy('1000-1', condition='used', completeness='complete', price='50.00', currency='USD')
    r = one(coll, copy)
    assert (str(r['paid']['amount']), r['paid']['currency'], r['paid']['converted'], str(r['paid']['rate']), r['paid']['rate_as_of']) == ('46.30', 'EUR', True, '0.9259', '2026-10-20')
    assert r['paid']['original'] == {'amount': r['paid']['original']['amount'], 'currency': 'USD'} and str(r['paid']['original']['amount']) == '50.00'
    assert str(r['gain']['amount']) == '14.70' and r['gain']['currency'] == 'EUR'
    assert (r['paid_original']['currency'], str(r['paid_original']['amount'])) == ('USD', '50.00')


def test_a_missing_rate_leaves_the_figure_empty_with_a_reason_never_a_guess(coll):
    coll.price(coll.item('sets', '1000-1'), '61.00', condition='used', sold=2)
    copy = coll.add_copy('1000-1', condition='used', completeness='complete', price='50.00', currency='USD')
    r = one(coll, copy)
    assert (r['paid'], r['paid_reason'], r['gain']) == (None, 'no_rate', None)
    assert (r['paid_original']['currency'], str(r['worth']['amount'])) == ('USD', '61.00')
    # an override in a currency with no rate, and a quote in one
    other = coll.add_copy('1000-2', condition='used', completeness='complete', price='5', currency='EUR', current_value='9.00', current_value_currency='GBP')
    r = one(coll, other)
    assert (r['worth'], r['worth_reason'], r['worth_source'], r['gain']) == (None, 'no_rate', 'override', None)


def test_a_quote_in_another_currency_is_converted_into_the_display_currency(coll):
    coll.price(coll.item('sets', '1000-1'), '100.00', condition='used', sold=2, currency='USD', region='US')
    rate(coll, 'USD', '1.25')
    copy = coll.add_copy('1000-1', condition='used', completeness='complete', price='40', currency='EUR')
    r = one(coll, copy)
    assert (str(r['worth']['amount']), r['worth']['converted'], str(r['worth']['original']['amount']), r['worth']['original']['currency']) == ('80.00', True, '100.00', 'USD')
    assert str(r['gain']['amount']) == '40.00'
    coll.sql("INSERT OR REPLACE INTO setting(key,value) VALUES('display_currency','USD')")
    r = one(coll, copy)
    assert (r['currency'], str(r['paid']['amount']), str(r['worth']['amount']), r['worth']['converted']) == ('USD', '50.00', '100.00', False)


def test_an_archived_copy_is_not_valued(coll):
    coll.price(coll.item('sets', '1000-1'), '61.00', condition='used', sold=2)
    keep = coll.add_copy('1000-1', condition='used', completeness='complete', price='24', currency='EUR')
    gone = coll.add_copy('1000-1', condition='used', completeness='complete', price='24', currency='EUR')
    coll.sql("UPDATE copy SET archived_at=? WHERE id=?", (STAMP, gone))
    assert [r['id'] for r in valuation.copies(coll.db)] == [keep]
    assert valuation.paid_vs_value(coll.db)['copies'] == 1 and len(valuation.report(coll.db)['rows']) == 1


def test_copies_come_in_set_number_order_by_number_not_by_text(coll):
    coll.price(coll.item('sets', '1000-1'), '1.00', condition='used', sold=1)
    a, b, c = (coll.add_copy(n) for n in ('2070-1', '1000-2', '1000-1'))
    assert [r['number'] for r in valuation.copies(coll.db)] == ['1000-1', '1000-2', '2070-1'] and valuation.copies(coll.db)[0]['id'] == c
    assert valuation._natural('7286-1') < valuation._natural('10000-1')


def seeded(coll):
    """Four paid copies with a worth (two themes, two years, one date missing), one paid in USD, one without a price paid, one without a quote."""
    keep, gate, duplo = (coll.item('sets', n) for n in ('1000-1', '1000-2', '2070-1'))
    coll.price(keep, '60.00', condition='used', sold=5)
    coll.price(gate, '40.00', condition='used', sold=5)
    coll.price(duplo, '10.00', condition='used', sold=5)
    rate(coll, 'USD', '1.25')
    ids = dict(
        a=coll.add_copy('1000-1', condition='used', completeness='complete', price='20', currency='EUR', date='2024-05-01'),
        b=coll.add_copy('1000-1', condition='used', completeness='complete', price='80', currency='EUR', date='2025-02-01'),
        c=coll.add_copy('1000-2', condition='used', completeness='complete', price='25', currency='EUR'),
        d=coll.add_copy('2070-1', condition='used', completeness='complete', price='25', currency='USD', date='2025-06-01'),
        unpaid=coll.add_copy('2070-1', condition='used', completeness='complete'),
        quoteless=coll.add_copy('1000-2', condition='new', completeness='sealed', price='99', currency='EUR', date='2025-07-01'),
    )
    return ids


def test_the_worth_total_counts_only_copies_with_a_price_paid_and_a_worth(coll):
    seeded(coll)
    s = valuation.paid_vs_value(coll.db)
    # a 20 -> 60, b 80 -> 60, c 25 -> 40, d 25 USD = 20.00 EUR -> 10; the unpaid copy's 10 and the quoteless copy's 99 stay out
    assert (s['currency'], s['copies'], s['comparable_copies'], s['enough']) == ('EUR', 6, 4, True)
    assert (s['paid'], s['worth'], s['gain'], s['percent']) == ('145.00', '170.00', '25.00', 17)
    assert (s['without_price_paid'], s['without_quote'], s['without_rate'], s['worth_without_price_paid']) == (1, 1, 0, '10.00')
    assert s['converted'] is True and s['rates_as_of'] == '2026-10-20'


def test_by_theme_and_by_purchase_year(coll):
    seeded(coll)
    s = valuation.paid_vs_value(coll.db)
    assert [(g['label'], g['paid'], g['worth'], g['gain'], g['percent'], g['copies']) for g in s['by_theme']] == [
        ('Castle', '125.00', '160.00', '35.00', 28, 3), ('Rattles', '20.00', '10.00', '-10.00', -50, 1)]
    assert [(g['label'], g['paid'], g['worth'], g['copies']) for g in s['by_year']] == [
        ('2024', '20.00', '60.00', 1), ('2025', '100.00', '70.00', 2), ('Not recorded', '25.00', '40.00', 1)]
    assert [g['gain'] for g in s['by_year']] == ['40.00', '-30.00', '15.00'] and [g['percent'] for g in s['by_year']] == [200, -30, 60]


def test_a_missing_rate_takes_the_copy_out_of_the_totals_and_is_counted(coll):
    ids = seeded(coll)
    coll.sql('DELETE FROM exchange_rate')
    s = valuation.paid_vs_value(coll.db)
    assert (s['comparable_copies'], s['without_rate'], s['paid'], s['converted']) == (3, 1, '125.00', False)
    assert one(coll, ids['d'])['paid_reason'] == 'no_rate'


def test_too_few_comparable_copies_and_nothing_to_compare(coll):
    assert valuation.paid_vs_value(coll.db) == dict(valuation.paid_vs_value(coll.db), copies=0, comparable_copies=0, enough=False, paid=None, worth=None, gain=None,
                                                    percent=None, by_theme=[], by_year=[], converted=False, rates_as_of=None, worth_without_price_paid=None)
    coll.price(coll.item('sets', '1000-1'), '60.00', condition='used', sold=5)
    coll.add_copy('1000-1', condition='used', completeness='complete')                                    # worth only
    s = valuation.paid_vs_value(coll.db)
    assert (s['paid'], s['worth'], s['without_price_paid'], s['worth_without_price_paid'], s['enough']) == (None, None, 1, '60.00', False)
    coll.add_copy('1000-1', condition='used', completeness='complete', price='10', currency='EUR')
    assert valuation.paid_vs_value(coll.db)['comparable_copies'] == 1 and not valuation.paid_vs_value(coll.db)['enough']


def test_the_report_has_every_live_copy_in_set_number_order_with_its_own_photos(coll):
    ids = seeded(coll)
    keep = coll.item('sets', '1000-1')
    for n, (photo, copy) in enumerate([('p-b', ids['b']), ('p-a', ids['a']), ('p-a2', ids['a']), ('p-stock', None)]):
        coll.sql('''INSERT INTO photo(id,item_id,copy_id,local_path,created_at,archived_at) VALUES(?,?,?,?,?,?)''',
                 (photo, keep, copy, f'data/images/own/{photo}.jpg', f'2026-10-0{n + 1}T00:00:00.000Z', None))
    coll.sql("INSERT INTO photo(id,item_id,copy_id,local_path,created_at,archived_at) VALUES('p-gone',?,?, 'data/images/own/gone.jpg','2026-10-09T00:00:00.000Z',?)", (keep, ids['a'], STAMP))
    data = valuation.report(coll.db)
    assert len(data['rows']) == 6 and [r['number'] for r in data['rows']] == ['1000-1', '1000-1', '1000-2', '1000-2', '2070-1', '2070-1']
    own = {r['id']: r['photo_ids'] for r in data['rows']}
    assert own[ids['a']] == ['p-a', 'p-a2'] and own[ids['b']] == ['p-b'] and own[ids['c']] == [] and 'p-stock' not in sum(own.values(), [])
    h = data['header']
    assert (h['generated'], h['copies'], h['paid'], h['worth'], h['without_price_paid'], h['without_quote'], h['currency']) == ('2026-10-27', 6, '145.00', '170.00', 1, 1, 'EUR')
    unpaid = next(r for r in data['rows'] if r['id'] == ids['unpaid'])
    assert unpaid['paid'] is None and unpaid['worth']['amount'] == '10.00' and unpaid['worth_source'] == 'used'


def test_the_report_totals_equal_the_statistics_totals(coll):
    seeded(coll)
    stats, head = valuation.paid_vs_value(coll.db), valuation.report(coll.db)['header']
    assert all(stats[k] == head[k] for k in ('paid', 'worth', 'gain', 'percent', 'comparable_copies', 'without_price_paid', 'without_quote', 'without_rate', 'converted'))


def test_the_csv_has_the_report_columns_one_row_per_copy_and_is_safe_for_a_spreadsheet(coll):
    ids = seeded(coll)
    coll.sql("UPDATE item SET name='=HYPERLINK(\"http://x\")' WHERE id=?", (coll.item('sets', '2070-1'),))
    coll.sql("UPDATE copy SET condition='new', completeness='sealed' WHERE id=?", (ids['unpaid'],))
    text = valuation.report_csv(coll.db)
    table = list(csv.reader(io.StringIO(text)))
    assert table[0] == valuation.COLUMNS and len(table) == 7
    by = {(r[0], r[5], r[6]): r for r in table[1:]}
    loss = by[('1000-1', '2025-02-01', '80.00')]
    assert loss[8] == '60.00' and loss[10] == 'Used sold average' and loss[11] == '2026-10-26' and loss[12] == '0'
    formula = [r for r in table[1:] if r[0] == '2070-1']
    assert all(r[1].startswith("'=HYPERLINK") for r in formula)
    converted = next(r for r in formula if r[6] == '20.00')
    assert converted[7] == 'EUR' and 'Paid USD 25.00, converted at 0.8000 (2026-10-20)' in converted[13]
    assert any(r[6] == '' and r[13].startswith('No price paid') for r in table[1:])
    assert any(r[8] == '' and 'No sales' in r[13] for r in table[1:])
    assert 'Sealed' in {r[4] for r in table[1:]}


def test_text_that_starts_with_a_minus_or_an_at_sign_is_neutralised_in_the_csv(coll):
    coll.add_copy('1000-1', condition='used', completeness='complete', price='5', currency='EUR')
    coll.sql("UPDATE item SET name='-risky' WHERE id=?", (coll.item('sets', '1000-1'),))
    assert list(csv.reader(io.StringIO(valuation.report_csv(coll.db))))[1][1] == "'-risky"
    coll.sql("UPDATE item SET name='@sum' WHERE id=?", (coll.item('sets', '1000-1'),))
    assert list(csv.reader(io.StringIO(valuation.report_csv(coll.db))))[1][1] == "'@sum"


def queries(coll, function):
    seen = []
    coll.db.set_trace_callback(seen.append)
    try:
        function(coll.db)
    finally:
        coll.db.set_trace_callback(None)
    return len([q for q in seen if q.lstrip().upper().startswith(('SELECT', 'WITH'))])


def test_the_number_of_queries_does_not_grow_with_the_number_of_copies(coll):
    coll.price(coll.item('sets', '1000-1'), '61.00', condition='used', sold=2)
    rate(coll, 'USD', '1.25')
    for n in range(2):
        coll.add_copy('1000-1', condition='used', completeness='complete', price='24', currency='USD')
    few = [queries(coll, f) for f in (valuation.copies, valuation.paid_vs_value, valuation.report, valuation.report_csv)]
    for n in range(8):
        coll.add_copy('1000-1' if n % 2 else '1000-2', condition='used', completeness='incomplete', price='24', currency='USD' if n % 3 else 'EUR')
    many = [queries(coll, f) for f in (valuation.copies, valuation.paid_vs_value, valuation.report, valuation.report_csv)]
    assert few == many and all(n < 40 for n in many), (few, many)


def test_the_json_bodies_carry_strings_for_money(coll):
    seeded(coll)
    body = json.loads(json.dumps(valuation.valuation(coll.db)))
    first = body['copies'][0]
    assert isinstance(first['paid']['amount'], str) and isinstance(first['gain']['amount'], str) and isinstance(body['statistics']['paid'], str)
