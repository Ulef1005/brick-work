"""Currency conversion for display and totals (#39). Stored amounts never change currency.

Rates are kept per 1 EUR (the ECB reference format), so the display currency can change without
touching a rate: 1 EUR = rate × currency, EUR itself is 1. A rate is entered by hand or fetched from
the ECB's keyless daily reference rates. convert() returns None when a rate is missing; callers then
keep their per-currency behaviour. Converted figures are always shown marked (≈, with rate and date).
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from urllib.request import Request
from xml.etree import ElementTree as ET

from . import errors
from .sources.base import now
from .transaction import transaction

ECB_URL = 'https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml'
CODE = re.compile(r'[A-Z]{3}')
DDL = '''CREATE TABLE IF NOT EXISTS exchange_rates(currency TEXT PRIMARY KEY NOT NULL CHECK(length(currency)=3),
 per_eur TEXT NOT NULL, as_of TEXT NOT NULL, source TEXT NOT NULL CHECK(source IN ('manual','ecb')))'''


def pending(db):
    return not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='exchange_rates'").fetchone()


def upgrade(db):
    with db:
        db.execute('BEGIN IMMEDIATE')
        if not pending(db):
            return False
        db.execute(DDL)
    return True


def display_currency(db):
    row = db.execute("SELECT value FROM settings WHERE key='display_currency'").fetchone()
    if row and row[0]:
        return row[0]
    row = db.execute("SELECT value FROM settings WHERE key='bricklink_currency'").fetchone()
    return row[0] if row and row[0] else 'EUR'


def rates(db):
    """{currency: dict(per_eur=Decimal, as_of, source)} including EUR = 1."""
    out = {'EUR': dict(per_eur=Decimal(1), as_of=None, source='fixed')}
    try:
        for r in db.execute('SELECT currency,per_eur,as_of,source FROM exchange_rates'):
            out[r[0]] = dict(per_eur=Decimal(r[1]), as_of=r[2], source=r[3])
    except Exception:  # a store without the table converts nothing
        pass
    return out


def convert(amount, source, target, table):
    """amount in `source` as `target`, with the rate used; None without both rates."""
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        return None
    source, target = (source or '').upper(), (target or '').upper()
    if not value.is_finite() or not source or not target:
        return None
    if source == target:
        return dict(amount=value, rate=Decimal(1), as_of=None, converted=False)
    a, b = table.get(source), table.get(target)
    if not a or not b or not a['per_eur'] or not b['per_eur']:
        return None
    rate = b['per_eur'] / a['per_eur']
    dates = [d for d in (a.get('as_of'), b.get('as_of')) if d]
    return dict(amount=(value * rate).quantize(Decimal('0.01'), ROUND_HALF_UP), rate=rate.quantize(Decimal('0.0001'), ROUND_HALF_UP),
                as_of=min(dates) if dates else None, converted=True)


def set_rate(db, currency, per_eur):
    """Enter or clear (per_eur None) one rate by hand; one audited write."""
    from .admin import audit
    currency = (currency or '').strip().upper()
    if not CODE.fullmatch(currency) or currency == 'EUR':
        raise errors.ValidationFailed('Enter a three-letter currency other than EUR (EUR is the base, 1)')
    with transaction(db):
        before = db.execute('SELECT * FROM exchange_rates WHERE currency=?', (currency,)).fetchone()
        if per_eur in (None, ''):
            db.execute('DELETE FROM exchange_rates WHERE currency=?', (currency,))
        else:
            try:
                value = Decimal(str(per_eur))
            except (InvalidOperation, ValueError):
                raise errors.ValidationFailed('Enter the rate as a number') from None
            if not value.is_finite() or value <= 0:
                raise errors.ValidationFailed('Enter a rate above zero')
            db.execute('INSERT OR REPLACE INTO exchange_rates(currency,per_eur,as_of,source) VALUES(?,?,?,?)',
                       (currency, format(value, 'f'), now().date().isoformat(), 'manual'))
        audit(db, 'exchange_rate:' + currency, 'save', dict(before) if before else None,
              dict(currency=currency, per_eur=None if per_eur in (None, '') else str(per_eur)))
    return rates(db)


def set_display(db, currency):
    from .admin import audit
    currency = (currency or '').strip().upper()
    if not CODE.fullmatch(currency):
        raise errors.ValidationFailed('Enter a three-letter currency')
    with transaction(db):
        before = display_currency(db)
        db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('display_currency',?)", (currency,))
        audit(db, 'settings', 'display_currency', before, currency)
    return currency


def fetch_ecb(db, http=None):
    """Replace the ECB-sourced rates from the daily reference feed. Hand-entered rates stay."""
    from .admin import audit
    from .sources.base import transport, USER_AGENT
    request = Request(ECB_URL, headers={'User-Agent': USER_AGENT})
    try:
        text = (http or transport)(request)
        root = ET.fromstring(text if isinstance(text, (str, bytes)) else str(text))
    except Exception:
        raise errors.SourceError('The ECB reference rates could not be read') from None
    found, day = {}, None
    for cube in root.iter():
        if cube.tag.endswith('Cube') and cube.get('time'):
            day = cube.get('time')
        if cube.tag.endswith('Cube') and cube.get('currency') and cube.get('rate'):
            code, rate = cube.get('currency'), cube.get('rate')
            if CODE.fullmatch(code):
                try:
                    value = Decimal(rate)
                except InvalidOperation:
                    continue
                if value.is_finite() and value > 0:
                    found[code] = format(value, 'f')
    if not found or not day:
        raise errors.SourceError('The ECB reference rates were empty')
    with transaction(db):
        manual = {r[0] for r in db.execute("SELECT currency FROM exchange_rates WHERE source='manual'")}
        rows = [(c, v, day, 'ecb') for c, v in sorted(found.items()) if c not in manual]
        db.executemany('INSERT OR REPLACE INTO exchange_rates(currency,per_eur,as_of,source) VALUES(?,?,?,?)', rows)
        audit(db, 'exchange_rates', 'ecb', None, dict(as_of=day, currencies=len(rows), kept_manual=sorted(manual)))
    return dict(as_of=day, updated=len(rows), kept_manual=len(manual))


def listing(db):
    table = rates(db)
    return [dict(currency=c, per_eur=str(v['per_eur']), as_of=v['as_of'], source=v['source'])
            for c, v in sorted(table.items()) if c != 'EUR']
