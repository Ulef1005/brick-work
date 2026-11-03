"""Manual observations on the 4.0 store (M.8g, issue #110): a price a person records, and its Undo.

An entry names an item by id (`core.items`); the observation is written by `sources.base.observation` as source `manual`, so it becomes
the current one of its key (item, colour, condition, guide, slot, region, currency) like any other. Undo **voids** the observation
(`voided_at`) and, when it was the current one of its key, makes the latest remaining observation current again: history survives every
reversal, and a voided observation is never shown (design 5, `price_*`)."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import re

from . import errors, items
from . import undo as undoing
from .admin import audit, origin
from .sources import base
from .transaction import transaction
from ..store4.connect import has_catalogue

GUIDES = ('sold', 'stock', 'retail', 'manual', 'valuation')
CONDITIONS = ('new', 'used')
ENTITY = 'manual_prices'
KEY = ('item_id', 'color_id', 'condition', 'guide', 'slot', 'region', 'currency')
# The key as `price_current_key` and `sources.base.observation` compare it: a NULL and an empty value are the same key.
CURRENT = ("item_id=? AND color_key=coalesce(?,0) AND condition_key=coalesce(?,'') AND guide=? AND slot_key=coalesce(?,'')"
           " AND region_key=coalesce(?,'') AND currency_key=coalesce(?,'')")
OBSERVED = ("item_id=? AND coalesce(color_id,0)=coalesce(?,0) AND coalesce(condition,'')=coalesce(?,'') AND guide=?"
            " AND coalesce(slot,'')=coalesce(?,'') AND coalesce(region,'')=coalesce(?,'') AND coalesce(currency,'')=coalesce(?,'')")


def _item(db, item_id):
    """The item in the collection (projected from the catalogue when it is not there yet), or a validation error."""
    if type(item_id) is not int or item_id < 1:
        raise errors.ValidationFailed('Choose an item')
    row = db.execute('SELECT id, kind FROM main.item WHERE id=? AND merged_into IS NULL', (item_id,)).fetchone()
    if row is None:
        if not has_catalogue(db):
            raise errors.CatalogueNotLoaded()
        if db.execute('SELECT 1 FROM catalogue.item WHERE id=? AND retired_at IS NULL', (item_id,)).fetchone() is None:
            raise errors.NotFound('Catalogue item is unavailable')
        items.ensure(db, item_id)
        row = db.execute('SELECT id, kind FROM main.item WHERE id=?', (item_id,)).fetchone()
    return row


def record(db, entries):
    """Record 1 to 500 observations under one receipt; returns their ids."""
    if not isinstance(entries, list) or not 1 <= len(entries) <= 500:
        raise errors.ValidationFailed('Supply between 1 and 500 observations')
    ids = []
    with transaction(db):
        for entry in entries:
            data = dict(entry)
            item = _item(db, data.get('item_id'))
            color = data.get('color_id')
            if (item['kind'] == 'part') != (color is not None):
                raise errors.ValidationFailed('Parts require a colour; other items have none')
            if color is not None and not db.execute('SELECT 1 FROM main.color WHERE id=?', (color,)).fetchone():
                raise errors.ValidationFailed('Unknown colour')
            if data.get('guide') not in GUIDES:
                raise errors.ValidationFailed('Choose a price guide')
            if data.get('condition') not in CONDITIONS:
                raise errors.ValidationFailed('Choose new or used')
            text = data.get('price')
            try:
                price = Decimal(text)
            except (InvalidOperation, TypeError):
                raise errors.ValidationFailed('Enter a valid price') from None
            if not price.is_finite() or price < 0 or not re.fullmatch(r'[0-9]+(\.[0-9]+)?', text):
                raise errors.ValidationFailed('Enter a price of zero or more')
            currency = data.get('currency')
            if not isinstance(currency, str) or not re.fullmatch(r'[A-Z]{3}', currency):
                raise errors.ValidationFailed('Currency must be three uppercase ISO 4217 letters')
            stamp = data.get('observed_at') or base.now().isoformat()
            try:
                parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
                if parsed.utcoffset() is None:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise errors.ValidationFailed('Use a timestamp with a timezone') from None
            ids.append(base.observation(db, 'manual', item['id'], guide=data['guide'], price=format(price, 'f'), currency=currency, color_id=color,
                                        condition=data['condition'], slot=data.get('slot'), observed_at=stamp))
        audit(db, ENTITY, 'receipt', new=dict(ids=ids))
    return ids


def _undo_receipt(db, event, via, actor):
    ids = json.loads(event['new_value'])['ids']
    stamp = base.store_now()
    for identifier in ids:
        row = db.execute("SELECT * FROM price_observation WHERE id=? AND source='manual'", (identifier,)).fetchone()
        if row is None or row['voided_at'] is not None:
            raise errors.UndoBlocked('Observation is unavailable')
        db.execute('UPDATE price_observation SET voided_at=? WHERE id=?', (stamp, identifier))
        key = tuple(row[k] for k in KEY)
        current = db.execute('SELECT observation_id FROM price_current WHERE ' + CURRENT, key).fetchone()
        if current is not None and current[0] == identifier:
            db.execute('DELETE FROM price_current WHERE ' + CURRENT, key)
            previous = db.execute('SELECT * FROM price_observation WHERE ' + OBSERVED + ' AND error IS NULL AND voided_at IS NULL AND price IS NOT NULL ORDER BY id DESC LIMIT 1', key).fetchone()
            if previous:
                db.execute('INSERT INTO price_current(item_id,color_id,condition,guide,slot,region,currency,observation_id) VALUES(?,?,?,?,?,?,?,?)',
                           (*(previous[k] for k in KEY), previous['id']))
    audit(db, ENTITY, 'undo', None, dict(undoes=event['id']), via=via, actor=actor)
    undo_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.execute('INSERT INTO event_undo(event_id, undo_event_id) VALUES(?, ?)', (event['id'], undo_id))
    return {'event_id': undo_id}


undoing.register(ENTITY, 'receipt', _undo_receipt)


def undo(db, event_id):
    """Undo a manual-price receipt by its event id; a second Undo of the same event does nothing."""
    via, actor = origin()
    return undoing.undo_event(db, int(event_id), via=via, actor=actor)
