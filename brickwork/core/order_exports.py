"""Order export (#44): one row per saved order line, or one summary row per order, as CSV.

Totals are never summed across currencies. BrickLink's shipping, insurance and fees are not stored
separately (only the order's grand total in `orders.cost`), so the summary shows the grand total and
the difference to the line totals as "Other costs" rather than inventing a split.
"""
import csv

from . import csv_safe
from decimal import Decimal, InvalidOperation
import io
import re

LINES = ('Order', 'Date', 'Store', 'Seller', 'Item type', 'Item number', 'Name', 'Colour', 'Colour id',
         'Condition', 'Quantity', 'Unit price', 'Line total', 'Currency')
SUMMARY = ('Order', 'Date', 'Store', 'Seller', 'Status', 'Lines', 'Items', 'New total', 'Used total',
           'Other costs', 'Grand total', 'Currency')
DATE = re.compile(r'\d{4}-\d{2}-\d{2}')


def _money(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount if amount.is_finite() else None


def _filters(date_from=None, date_to=None, store=None):
    for value in (date_from, date_to):
        if value and not DATE.fullmatch(value):
            raise ValueError('Use dates as yyyy-mm-dd')
    clauses, params = [], []
    if date_from:
        clauses.append("substr(coalesce(o.date_ordered,o.created_at),1,10)>=?"); params.append(date_from)
    if date_to:
        clauses.append("substr(coalesce(o.date_ordered,o.created_at),1,10)<=?"); params.append(date_to)
    if store:
        clauses.append("lower(trim(o.store))=lower(trim(?))"); params.append(store)
    return (' AND ' + ' AND '.join(clauses)) if clauses else '', params


def rows(db, kind='lines', date_from=None, date_to=None, store=None):
    if kind not in ('lines', 'summary'):
        raise ValueError('Choose lines or summary')
    where, params = _filters(date_from, date_to, store)
    lines = [dict(r) for r in db.execute(f'''SELECT o.id AS order_id,coalesce(o.bricklink_order_id,'O-'||o.id) AS label,
            substr(coalesce(o.date_ordered,o.created_at),1,10) AS date,o.store,o.seller,o.status,o.cost,o.currency,
            l.item_type,l.item_no,coalesce(i.name,l.name) AS name,coalesce(c.name,l.colour_name) AS colour,l.color_id,
            l.condition,l.qty,l.unit_price,l.line_total
        FROM orders o JOIN order_lines l ON l.order_id=o.id JOIN order_documents d ON d.id=l.document_id
        LEFT JOIN items i ON i.item_type=l.item_type AND i.item_no=l.item_no LEFT JOIN colors c ON c.color_id=l.color_id
        WHERE d.phase='saved' AND l.paired_line_id IS NULL{where}
        ORDER BY date,o.id,l.document_id,l.line_no''', params)]
    if kind == 'lines':
        return lines
    orders = {}
    for o in db.execute(f'''SELECT o.id AS order_id,coalesce(o.bricklink_order_id,'O-'||o.id) AS label,
            substr(coalesce(o.date_ordered,o.created_at),1,10) AS date,o.store,o.seller,o.status,o.cost,o.currency
            FROM orders o WHERE 1=1{where} ORDER BY date,o.id''', params):
        orders[o['order_id']] = dict(o, lines=0, items=0, new=Decimal(0), used=Decimal(0), priced=True)
    for line in lines:
        o = orders[line['order_id']]
        o['lines'] += 1
        o['items'] += line['qty'] or 0
        total = _money(line['line_total'])
        if total is None:
            unit = _money(line['unit_price'])
            total = unit * (line['qty'] or 0) if unit is not None else None
        if total is None:
            o['priced'] = False
        elif line['condition'] == 'N':
            o['new'] += total
        else:
            o['used'] += total
    for o in orders.values():
        grand = _money(o['cost'])
        o['other'] = (grand - o['new'] - o['used']) if grand is not None and o['priced'] else None
        o['grand'] = grand
    return list(orders.values())


def to_csv(kind, data):
    stream = io.StringIO(newline='')
    out = csv_safe.writer(stream)
    money = lambda v: '' if v is None else format(v, 'f')
    if kind == 'lines':
        out.writerow(LINES)
        out.writerows([r['label'], r['date'], r['store'] or '', r['seller'] or '', r['item_type'] or '', r['item_no'] or '',
                       r['name'] or '', r['colour'] or '', '' if r['color_id'] is None else r['color_id'],
                       {'N': 'New', 'U': 'Used'}.get(r['condition'], r['condition'] or ''), r['qty'] or 0,
                       r['unit_price'] or '', r['line_total'] or '', r['currency'] or ''] for r in data)
    else:
        out.writerow(SUMMARY)
        out.writerows([o['label'], o['date'], o['store'] or '', o['seller'] or '', o['status'] or '', o['lines'], o['items'],
                       money(o['new']), money(o['used']), money(o['other']), money(o['grand']), o['currency'] or ''] for o in data)
    return stream.getvalue()


def stores(db):
    return [r[0] for r in db.execute("SELECT DISTINCT store FROM orders WHERE store IS NOT NULL AND trim(store)!='' ORDER BY lower(store)")]
