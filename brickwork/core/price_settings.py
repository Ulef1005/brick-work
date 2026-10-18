"""Price preferences in the v3 store; no legacy connection or Flask dependency."""
from decimal import Decimal, InvalidOperation
import logging
import os
import re

from .errors import ValidationFailed, UnsupportedSetting, Conflict

DEFAULTS = dict(bricklink_region='eu', bricklink_currency='EUR', incomplete_discount_pct=30,
                repair_shipping='3.00', repair_fees='0.50', repair_min_order='0',
                repair_use_loose_stock=False, changed_at=None)
REGIONS = ('asia', 'africa', 'north_america', 'south_america', 'middle_east',
           'europe', 'eu', 'oceania', 'all')


def _stored_value(key, value):
    if value is None:
        if key == 'changed_at':
            return None
        raise ValueError('NULL preference')
    if key == 'bricklink_region' and (not isinstance(value, str) or value.lower() not in REGIONS):
        raise ValueError('Invalid region')
    if key == 'bricklink_currency' and (not isinstance(value, str) or not re.fullmatch('[A-Z]{3}', value)):
        raise ValueError('Invalid currency')
    if key in ('incomplete_discount_pct', 'repair_shipping', 'repair_fees', 'repair_min_order'):
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            raise ValueError('Invalid amount')
        if key == 'incomplete_discount_pct':
            if amount > 95:
                raise ValueError('Invalid discount')
            return int(amount) if amount == amount.to_integral_value() else float(amount)
        return format(amount, 'f')
    if key == 'repair_use_loose_stock':
        loose = str(value).lower()
        if loose in ('true', 'false'):
            return loose == 'true'
        amount = Decimal(loose)
        if not amount.is_finite() or amount < 0:
            raise ValueError('Invalid boolean')
        return bool(amount)
    return value


def _read(db):
    values = dict(db.execute('SELECT key,value FROM settings'))
    result, invalid = dict(DEFAULTS), set()
    for key in DEFAULTS.keys() & values.keys():
        try:
            result[key] = _stored_value(key, values[key])
        except (InvalidOperation, ValueError, OverflowError):
            invalid.add(key)
            logging.getLogger(__name__).warning('Invalid stored price setting %s; using default', key)
    return result, invalid


def read(db):
    return _read(db)[0]


def save(db, data):
    from .admin import audit
    from .sources.base import now
    if not isinstance(data, dict):
        raise ValidationFailed('Invalid settings fields')
    if data.keys() - (DEFAULTS.keys() - {'changed_at'}):
        raise UnsupportedSetting('Unsupported setting')
    from .transaction import transaction
    with transaction(db):  # a savepoint inside a larger write (PATCH /settings), else BEGIN IMMEDIATE
        old, invalid = _read(db)
        new = {**old, **data}
        if 'bricklink_region' in data and new['bricklink_region'] not in REGIONS:
            raise ValidationFailed('Invalid bricklink_region')
        if 'bricklink_currency' in data and (not isinstance(new['bricklink_currency'], str) or not re.fullmatch('[A-Z]{3}', new['bricklink_currency'])):
            raise ValidationFailed('Currency must be three uppercase ISO 4217 letters')
        if 'incomplete_discount_pct' in data and (type(new['incomplete_discount_pct']) is not int or not 0 <= new['incomplete_discount_pct'] <= 95):
            raise ValidationFailed('incomplete_discount_pct must be an integer from 0 to 95')
        if os.environ.get('BW_PRICE_SETTINGS_LOCK', '1') != '0' and any(
                new[k] != old[k] for k in ('bricklink_region', 'bricklink_currency')):
            raise Conflict('BrickLink region and currency are locked; set BW_PRICE_SETTINGS_LOCK=0 to unlock')
        for key in ('repair_shipping', 'repair_fees', 'repair_min_order'):
            try:
                value = new[key]
                if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
                    raise InvalidOperation
                amount = Decimal(str(value))
                if not amount.is_finite() or amount < 0:
                    raise InvalidOperation
                new[key] = format(amount, 'f')
            except (InvalidOperation, ValueError):
                raise ValidationFailed('Price must be a finite non-negative Decimal') from None
        if type(new['repair_use_loose_stock']) is not bool:
            raise ValidationFailed('repair_use_loose_stock must be true or false')
        if invalid.intersection(data) or any(new[k] != old[k] for k in data):
            new['changed_at'] = now().isoformat()
            db.executemany('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)',
                           [(k, str(int(v)) if isinstance(v, bool) else str(v) if v is not None else None)
                            for k, v in new.items()])
            audit(db, 'settings', 'price', old, new)
        return new
