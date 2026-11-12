"""Value and gain per copy, the Statistics figures and the insurance report (#57), on the 4.0 store.

A copy's **price paid** is its `purchase_price`; a null or zero price is "no price paid". Its **worth** is the copy's own `current_value`
(source `override`, "Your value") or else the current used or new sold average of the set for the copy's condition and completeness: new for a
new or sealed copy, used for any other, with the discount for an incomplete set that Prices applies (`incomplete_discount_pct`). The quote
is the one the Prices card shows (`collection.prices`, then `collection_prices.choose` by source priority and freshness) and is stale by the
same rule (`decorate_prices`: older than the source's `max_age_days`). A stale quote still counts, marked.

Everything is in the display currency with the rate and its date when a conversion happened (#39). A missing rate makes that figure None
with a reason, never a guess, and never two currencies in one figure. **Gain** is worth minus price paid, in data a negative number for a
loss, and the percent of the price paid as a whole number. The totals count only the copies that have both a price paid and a worth, so the
gain compares like with like; the others are counted apart.

Batched: a fixed number of queries for any number of copies (labels, copies, prices, rates, settings and, for the report, photos).
"""
from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import io
import json
import re

from . import collection, collection_prices, csv_safe, items, planning
from . import currency as fx
from .retail import display_currency
from .sources.base import now

CENT = Decimal('0.01')
NATURAL = re.compile(r'(\d+)')
SOURCE_WORDS = {'override': 'Your value', 'used': 'Used sold average', 'new': 'New sold average'}
MIN_COMPARABLE = 3                                                     # "Charts need more data" under this many comparable copies
NOT_RECORDED = 'Not recorded'


def _decimal(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount if amount.is_finite() else None


def _cents(amount):
    return amount.quantize(CENT, ROUND_HALF_UP)


def _text(amount):
    return format(amount, 'f')


def _percent(gain, paid):
    """Whole percent of the price paid, half away from zero (so a gain and a loss of the same size round alike)."""
    share = abs(gain) / paid * 100
    whole = int(share.quantize(Decimal(1), ROUND_HALF_UP))
    return -whole if gain < 0 else whole


def _natural(number):
    return tuple(int(p) if p.isdigit() else p for p in NATURAL.split(number or ''))


def _money(amount, currency, display, table):
    """`(money body, error)` of an amount recorded in `currency`, as the display currency. The body carries the amount as shown, its currency,
    whether it was converted, the rate and its date, and the amount as recorded; the error is `no_rate` when there is no rate for it."""
    shown = fx.convert(amount, currency, display, table)
    if shown is None:
        return None, 'no_rate'
    converted = shown['converted']
    return dict(amount=_cents(shown['amount']), currency=display, converted=converted, rate=shown['rate'] if converted else None,
                rate_as_of=shown['as_of'] if converted else None,
                original=dict(amount=_cents(amount), currency=currency.upper()) if converted else None), None


def _body(money):
    """The JSON shape of a money body: strings for the numbers."""
    if money is None:
        return None
    return dict(money, amount=_text(money['amount']), rate=None if money['rate'] is None else _text(money['rate']),
                original=None if money['original'] is None else dict(money['original'], amount=_text(money['original']['amount'])))


def _quotes(db, copies):
    """`{(item id, wanted condition): choice}` of the sold averages the Prices card would pick for these copies' sets, one query for all."""
    pairs = {(c['item_id'], None) for c in copies}
    if not pairs:
        return {}
    by_item = collection.prices(db, pairs=pairs)
    priority = collection_prices.priority(db)
    found = {}
    for item_id, condition in {(c['item_id'], c['condition_wanted']) for c in copies}:
        rows = []
        for q in by_item.get((item_id, None), []):
            price = _decimal(q['price'])
            if q['guide'] == 'sold' and q.get('slot') != 'boxed' and not q.get('error') and q.get('currency') and price is not None and price > 0:
                rows.append(dict(q, amount=price))
        found[item_id, condition] = collection_prices.choose(rows, 'set', priority, condition)
    return found


def copies(db):
    """One row per live copy, in set-number order (numbers compared as numbers, then the copy's creation), as a list of dicts:

    `id`, `item_id`, `number` (the set number, e.g. `7286-1`), `name`, `year`, `theme`, `condition`, `completeness`, `purchase_date`,
    `currency` (the display currency),
    `paid_original` (`{amount, currency}` as recorded, or None), `paid` (a money body, below, or None) and `paid_reason`
    (None, `no_price_paid` or `no_rate`),
    `worth` (a money body or None) and `worth_reason` (None, `no_quote` or `no_rate`), `worth_source` (`override`, `used`, `new` or None),
    `worth_date` (the quote's day `YYYY-MM-DD`; None for an override), `worth_stale` (bool; never for an override), `worth_sales` (the
    number of sales behind the quote, or None), `worth_price_source` (the price source, e.g. `bricklink`, or None) and `worth_discount_pct`
    (the incomplete-set discount applied to the quote, or None),
    `gain` (`{amount, percent, currency}`, worth minus paid, negative for a loss, or None when either is None).

    A money body is `{amount: Decimal (2 places), currency: display currency, converted: bool, rate: Decimal or None, rate_as_of: day or
    None, original: {amount, currency} as recorded, or None unless converted}`."""
    rows = [dict(r) for r in db.execute('''SELECT c.id, c.item_id, c.condition, c.completeness, c.purchase_date, c.purchase_price, c.purchase_currency,
            c.current_value, c.current_value_currency, c.created_at, i.year,
            coalesce((SELECT value FROM item_property p WHERE p.item_id=c.item_id AND p.key='theme' AND p.source='brickset'
                      ORDER BY p.fetched_at DESC LIMIT 1), i.theme_name) AS theme
            FROM copy c JOIN item i ON i.id=c.item_id WHERE c.archived_at IS NULL''')]
    if not rows:
        return []
    labels = items.labels(db, {(c['item_id'], None) for c in rows})
    display, table, config = display_currency(db), collection.exchange_rates(db), planning.configuration(db)
    discount = config['incomplete_discount_pct']
    for c in rows:
        c['condition_wanted'] = 'new' if c['condition'] == 'new' or c['completeness'] == 'sealed' else 'used'
    quotes = _quotes(db, rows)
    out = []
    for c in rows:
        label = labels.get((c['item_id'], None))
        number = (label.number if label else None) or str(c['item_id'])
        paid_amount = _decimal(c['purchase_price'])
        has_paid = paid_amount is not None and paid_amount != 0 and bool(c['purchase_currency'])
        paid, paid_reason = None, 'no_price_paid'
        if has_paid:
            paid, paid_reason = _money(paid_amount, c['purchase_currency'], display, table)
        worth, worth_reason, source, date, stale, sales, price_source, applied = None, 'no_quote', None, None, False, None, None, None
        override = _decimal(c['current_value'])
        if override is not None and c['current_value_currency']:
            worth, worth_reason = _money(override, c['current_value_currency'], display, table)
            source = 'override'
        else:
            quote = quotes.get((c['item_id'], c['condition_wanted']))
            if quote:
                amount = quote['amount']
                if c['completeness'] == 'incomplete' and discount:
                    amount, applied = amount * (100 - discount) / 100, int(discount) if discount == int(discount) else float(discount)
                worth, worth_reason = _money(amount, quote['currency'], display, table)
                source, date, stale, sales, price_source = c['condition_wanted'], (quote['observed_at'] or '')[:10] or None, bool(quote['stale']), quote.get('sold'), quote['source']
        gain = None
        if paid is not None and worth is not None:
            difference = worth['amount'] - paid['amount']
            gain = dict(amount=difference, percent=_percent(difference, paid['amount']), currency=display)
        out.append(dict(
            id=c['id'], item_id=c['item_id'], number=number, name=(label.name if label else None) or '', year=c['year'], theme=c['theme'] or '',
            condition=c['condition'], completeness=c['completeness'], purchase_date=c['purchase_date'], currency=display,
            paid_original=dict(amount=_cents(paid_amount), currency=c['purchase_currency'].upper()) if has_paid else None, paid=paid, paid_reason=paid_reason,
            worth=worth, worth_reason=worth_reason, worth_source=source, worth_date=date,
            worth_stale=stale, worth_sales=sales, worth_price_source=price_source, worth_discount_pct=applied, gain=gain,
            _order=(_natural(number), c['created_at'] or '', c['id'])))
    out.sort(key=lambda r: r.pop('_order'))
    return out


def _comparable(rows):
    return [r for r in rows if r['paid'] is not None and r['worth'] is not None]


def _sum(rows):
    paid = sum((r['paid']['amount'] for r in rows), Decimal(0))
    worth = sum((r['worth']['amount'] for r in rows), Decimal(0))
    gain = worth - paid
    return dict(paid=paid, worth=worth, gain=gain, percent=_percent(gain, paid) if paid else None, copies=len(rows))


def _counts(rows):
    return dict(without_price_paid=sum(r['paid_reason'] == 'no_price_paid' for r in rows),
                without_quote=sum(r['worth_reason'] == 'no_quote' for r in rows),
                without_rate=sum('no_rate' in (r['paid_reason'], r['worth_reason']) for r in rows))


def _conversion(rows):
    """`(converted, rates_as_of)`: whether any figure behind the totals was converted, and the oldest rate date among them."""
    figures = [m for r in rows for m in (r['paid'], r['worth']) if m is not None and m['converted']]
    dates = [m['rate_as_of'] for m in figures if m['rate_as_of']]
    return bool(figures), min(dates) if dates else None


def _group(rows, label_of):
    groups = defaultdict(list)
    for r in rows:
        groups[label_of(r)].append(r)
    return [dict(label=label, **_sum(group)) for label, group in groups.items()]


def _row_body(row):
    return dict(row, paid=_body(row['paid']), worth=_body(row['worth']),
                paid_original=None if row['paid_original'] is None else dict(row['paid_original'], amount=_text(row['paid_original']['amount'])),
                gain=None if row['gain'] is None else dict(row['gain'], amount=_text(row['gain']['amount'])))


def _total_body(total):
    return dict(label=total.get('label'), paid=_text(total['paid']), worth=_text(total['worth']), gain=_text(total['gain']), percent=total['percent'], copies=total['copies'])


def paid_vs_value(db, rows=None):
    """The Statistics figures (5c), in the display currency, as strings for money. `rows` are `copies(db)` when the caller has them.

    `currency`; `copies` (live copies); `comparable_copies` (price paid and a worth: the only copies in the totals; the frames say "Charts
    need more data" when it is under 3, `enough` says so); `paid`, `worth`, `gain` (negative for a loss), `percent` (of the price paid), all
    over the comparable copies and None when there are none; `without_price_paid`, `without_quote` and `without_rate` (copies counted apart:
    no price paid, no quote at all, a figure that needs a missing rate); `worth_without_price_paid` (the worth of the copies with a worth
    and no price paid, never in the totals); `converted` and `rates_as_of` (any figure converted, and the oldest rate date used);
    `by_theme` and `by_year`: lists of `{label, paid, worth, gain, percent, copies}` over the comparable copies, themes by price paid
    (largest first), years ascending with `Not recorded` last."""
    rows = copies(db) if rows is None else rows
    comparable = _comparable(rows)
    total = _sum(comparable) if comparable else None
    unpaid = [r for r in rows if r['paid_reason'] == 'no_price_paid' and r['worth'] is not None]
    converted, as_of = _conversion(rows)
    themes = sorted(_group(comparable, lambda r: r['theme'] or NOT_RECORDED), key=lambda g: (-g['paid'], g['label']))
    years = sorted(_group(comparable, lambda r: (r['purchase_date'] or '')[:4] or NOT_RECORDED), key=lambda g: (g['label'] == NOT_RECORDED, g['label']))
    return dict(currency=display_currency(db), copies=len(rows), comparable_copies=len(comparable), enough=len(comparable) >= MIN_COMPARABLE,
                paid=None if total is None else _text(total['paid']), worth=None if total is None else _text(total['worth']),
                gain=None if total is None else _text(total['gain']), percent=None if total is None else total['percent'],
                **_counts(rows), worth_without_price_paid=_text(sum((r['worth']['amount'] for r in unpaid), Decimal(0))) if unpaid else None,
                converted=converted, rates_as_of=as_of,
                by_theme=[_total_body(g) for g in themes], by_year=[_total_body(g) for g in years])


def valuation(db):
    """`{'copies': [copy rows as JSON bodies], 'statistics': paid_vs_value}`, both from one read of the copies."""
    rows = copies(db)
    return dict(copies=[_row_body(r) for r in rows], statistics=paid_vs_value(db, rows))


def photos(db, copy_ids):
    """`{copy id: [photo ids]}` of the copies' own live photos in creation order (never the set's cover), one query."""
    found = defaultdict(list)
    ids = list(copy_ids)
    if ids:
        for r in db.execute('SELECT id, copy_id FROM photo WHERE archived_at IS NULL AND copy_id IN (SELECT value FROM json_each(?)) ORDER BY created_at, id', (json.dumps(ids),)):
            found[r['copy_id']].append(r['id'])
    return found


def report(db):
    """The insurance report: `{'header': {...}, 'rows': [...]}`. Rows are every live copy in set-number order, as `copies(db)` (money as strings,
    see `valuation`) plus `photo_ids` (the copy's own photos).

    The header: `generated` (today, `YYYY-MM-DD`), `currency`, `copies` (all live copies), `paid` and `worth` (over the copies with a price
    paid and a worth, the same figures as `paid_vs_value`), `gain`, `percent`, `comparable_copies`, the counts `without_price_paid`,
    `without_quote` and `without_rate` (for the footnote), `converted` and `rates_as_of`."""
    rows = copies(db)
    own = photos(db, [r['id'] for r in rows])
    stats = paid_vs_value(db, rows)
    header = dict(generated=now().date().isoformat(), currency=stats['currency'], copies=stats['copies'], paid=stats['paid'], worth=stats['worth'],
                  gain=stats['gain'], percent=stats['percent'], comparable_copies=stats['comparable_copies'], without_price_paid=stats['without_price_paid'],
                  without_quote=stats['without_quote'], without_rate=stats['without_rate'], converted=stats['converted'], rates_as_of=stats['rates_as_of'])
    return dict(header=header, rows=[dict(_row_body(r), photo_ids=own.get(r['id'], [])) for r in rows])


COLUMNS = ['Set number', 'Name', 'Year', 'Condition', 'Completeness', 'Purchase date', 'Price paid', 'Price paid currency', 'Current value',
           'Current value currency', 'Value source', 'Value date', 'Photos', 'Remarks']


def _remarks(r):
    """The Remarks cell of a report row (a body of `report`): why a figure is missing, what was converted, an old quote, a discount."""
    notes = []

    def converted(label, money):
        return (f"{label} {money['original']['currency']} {money['original']['amount']}, converted at {money['rate']}"
                + (f" ({money['rate_as_of']})" if money['rate_as_of'] else ''))
    if r['paid_reason'] == 'no_price_paid':
        notes.append('No price paid')
    elif r['paid_reason'] == 'no_rate':
        notes.append(f"No rate for the price paid ({r['paid_original']['currency']} {r['paid_original']['amount']})")
    elif r['paid']['converted']:
        notes.append(converted('Paid', r['paid']))
    if r['worth_reason'] == 'no_quote':
        notes.append('No sales')
    elif r['worth_reason'] == 'no_rate':
        notes.append('No rate for the value')
    elif r['worth']['converted']:
        notes.append(converted('Value', r['worth']))
    if r['worth_stale']:
        notes.append('Old quote')
    if r['worth_discount_pct']:
        notes.append(f"Incomplete set, {r['worth_discount_pct']} % off the complete quote")
    return '; '.join(notes)


def report_csv(db, data=None):
    """The report as CSV text, one row per live copy (the same rows and order as `report`), made safe for a spreadsheet (`csv_safe`). Money is in
    the display currency; a figure that could not be given is empty and the Remarks column says why. `data` is `report(db)` when the caller has it."""
    data = report(db) if data is None else data
    stream = io.StringIO(newline='')
    out = csv_safe.writer(stream)
    out.writerow(COLUMNS)
    for r in data['rows']:
        paid, worth = r['paid'], r['worth']
        out.writerow([r['number'], r['name'], '' if r['year'] is None else r['year'], (r['condition'] or '').capitalize(), (r['completeness'] or '').capitalize(),
                      r['purchase_date'] or '', paid['amount'] if paid else '', paid['currency'] if paid else '', worth['amount'] if worth else '',
                      worth['currency'] if worth else '', SOURCE_WORDS.get(r['worth_source'], '') if worth else '', r['worth_date'] or '',
                      len(r['photo_ids']), _remarks(r)])
    return stream.getvalue()
