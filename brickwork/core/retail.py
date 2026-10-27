"""Retail price, availability and savings from the Brickset data (#26), on the 4.0 store (M.8f).

Brickset gives, per country, the LEGO retail price (a `price_observation(guide='retail', source='brickset')`) and the first and last dates a
set was available at LEGO (`item_property`). The retail country is the `retail_country` setting (DE by default). Status: Retired once
the last date has passed, Retiring within six months of it, otherwise Available. Savings compare a copy's price paid only when it is in the
retail currency, or when both rates exist (#39); anything else is "not comparable". Batched: two queries for any number of sets.
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import json

from .sources.base import now


def country(db):
    row = db.execute("SELECT value FROM setting WHERE key='retail_country'").fetchone()
    return row[0] if row and row[0] else 'DE'


def _day(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _amount(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount if amount.is_finite() else None


def lookup(db, item_ids):
    """{item id: dict(price, currency, country, first, last, status)} for the sets that have any of it."""
    item_ids = sorted({i for i in item_ids if i is not None})
    if not item_ids:
        return {}
    where = country(db)
    packed = json.dumps(item_ids)
    found = defaultdict(dict)
    for r in db.execute('''SELECT c.item_id, o.price, o.currency FROM price_current c JOIN price_observation o ON o.id=c.observation_id
            WHERE c.guide='retail' AND c.slot='retail' AND c.region=? AND o.voided_at IS NULL
            AND c.item_id IN (SELECT value FROM json_each(?))''', (where, packed)):
        found[r['item_id']].update(price=r['price'], currency=r['currency'])
    for r in db.execute('''SELECT item_id, key, value FROM item_property WHERE source='brickset'
            AND key IN ('dateFirstAvailable','dateLastAvailable') AND item_id IN (SELECT value FROM json_each(?))''', (packed,)):
        found[r['item_id']]['first' if r['key'] == 'dateFirstAvailable' else 'last'] = (r['value'] or '')[:10] or None
    today = now().date()
    for item_id, info in found.items():
        info['country'] = where
        last = _day(info.get('last'))
        info['status'] = (None if last is None else 'Retired' if last < today
                          else 'Retiring' if last <= today + timedelta(days=183) else 'Available')
    return dict(found)


def saving(paid, paid_currency, info, rates=None):
    """'20 % under retail' style comparison, or None when it cannot be compared honestly.
    #39: another currency is compared when both rates exist; the result then says converted."""
    price, amount = _amount((info or {}).get('price')), _amount(paid)
    if price is None or amount is None or price <= 0:
        return None
    converted = None
    if (paid_currency or '') != (info or {}).get('currency'):
        from .currency import convert
        converted = convert(amount, paid_currency, (info or {}).get('currency'), rates) if rates and paid_currency else None
        if converted is None:
            return None
        amount = converted['amount']
    pct = round((price - amount) / price * 100)
    result = dict(pct=abs(int(pct)), under=pct >= 0)
    if converted:
        result.update(converted=True, rate=str(converted['rate']), as_of=converted['as_of'], amount=str(converted['amount']))
    return result


def spent_vs_retail(db):
    """Statistics (5c): price paid against retail per currency, per purchase year and per theme."""
    copies = [dict(r) for r in db.execute('''SELECT c.item_id, c.purchase_price, c.purchase_currency, c.purchase_date,
            coalesce((SELECT value FROM item_property p WHERE p.item_id=c.item_id AND p.key='theme' AND p.source='brickset'
                      ORDER BY p.fetched_at DESC LIMIT 1), i.theme_name) AS theme
            FROM copy c JOIN item i ON i.id=c.item_id WHERE c.archived_at IS NULL AND c.purchase_price IS NOT NULL''')]
    from . import collection, currency as fx
    info = lookup(db, [c['item_id'] for c in copies])
    table = collection.exchange_rates(db)
    totals, years, themes, not_comparable, converted = {}, defaultdict(dict), defaultdict(dict), 0, 0
    for c in copies:
        retail = info.get(c['item_id']) or {}
        price, paid = _amount(retail.get('price')), _amount(c['purchase_price'])
        if price is not None and paid is not None and (c['purchase_currency'] or '') != retail.get('currency'):
            # #39: a price paid in another currency counts when both rates exist, converted and counted as such.
            change = fx.convert(paid, c['purchase_currency'], retail.get('currency'), table) if c['purchase_currency'] else None
            paid = change['amount'] if change else None
            converted += bool(change)
        if price is None or paid is None:
            not_comparable += 1
            continue
        currency = retail['currency']
        for bucket in (totals, years[(c['purchase_date'] or '')[:4] or 'Not recorded'], themes[c['theme'] or 'Not recorded']):
            entry = bucket.setdefault(currency, dict(paid=Decimal(0), retail=Decimal(0), copies=0))
            entry['paid'] += paid
            entry['retail'] += price
            entry['copies'] += 1
    def rows(groups):
        out = []
        for label, by_currency in groups.items():
            for currency, e in by_currency.items():
                out.append(dict(label=label, currency=currency, paid=str(e['paid']), retail=str(e['retail']), copies=e['copies'],
                                pct=int(round((e['retail'] - e['paid']) / e['retail'] * 100)) if e['retail'] else None))
        return sorted(out, key=lambda r: (r['label'], r['currency']))
    display, overall = display_currency(db), None
    if totals:
        parts = [(fx.convert(e['paid'], cur, display, table), fx.convert(e['retail'], cur, display, table)) for cur, e in totals.items()]
        if all(a and b for a, b in parts):
            paid_sum, retail_sum = sum(a['amount'] for a, _ in parts), sum(b['amount'] for _, b in parts)
            overall = dict(currency=display, paid=str(paid_sum), retail=str(retail_sum),
                           converted=any(a['converted'] for a, _ in parts),
                           pct=int(round((retail_sum - paid_sum) / retail_sum * 100)) if retail_sum else None)
    return dict(totals=rows({'All': totals}) if totals else [], years=rows(years), themes=rows(themes),
                not_comparable=not_comparable, converted=converted, overall=overall, country=country(db))


def display_currency(db):
    """The currency totals are shown in: `display_currency`, else the BrickLink currency, else EUR."""
    for key in ('display_currency', 'bricklink_currency'):
        row = db.execute('SELECT value FROM setting WHERE key=?', (key,)).fetchone()
        if row and row[0]:
            return row[0]
    return 'EUR'
