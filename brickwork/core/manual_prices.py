"""Manual observations and void Undo; history survives every reversal."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import re

from . import add, admin, errors
from .sources import base
from .transaction import transaction

KEY = ('item_type','item_no','color_id','condition','guide','slot','region','currency')
CLAUSE = ' AND '.join(k+' IS ?' for k in KEY)


def record(db, entries):
    if not 1 <= len(entries) <= 500:
        raise errors.ValidationFailed('Supply between 1 and 500 observations')
    ids = []
    with transaction(db):
        for entry in entries:
            data = dict(entry)
            kind, number = data.get('item_type'), data.get('item_no')
            if kind not in add.TYPES: raise errors.ValidationFailed('Choose an item type')
            if not db.execute('SELECT 1 FROM items WHERE item_type=? AND item_no=?',(kind,number)).fetchone():
                if not add.catalogue_path(db).is_file(): raise errors.CatalogueNotLoaded()
                item = add.lookup(db,kind,number)
                if not item: raise errors.NotFound('Catalogue item is unavailable')
                base.item(db,kind,number,item.get('name'))
            color = data.get('color_id')
            if (kind == 'P' and color is None) or (kind != 'P' and color is not None):
                raise errors.ValidationFailed('Parts require a colour; other items have none')
            if color is not None and not db.execute('SELECT 1 FROM colors WHERE color_id=?',(color,)).fetchone():
                raise errors.ValidationFailed('Unknown colour')
            try: price = Decimal(data['price'])
            except (InvalidOperation,TypeError): raise errors.ValidationFailed('Enter a valid price') from None
            if not price.is_finite() or price < 0 or not re.fullmatch(r'[0-9]+(\.[0-9]+)?',data['price']):
                raise errors.ValidationFailed('Enter a price of zero or more')
            stamp = data.get('observed_at') or base.now().isoformat()
            try:
                parsed = datetime.fromisoformat(stamp.replace('Z','+00:00'))
                if parsed.utcoffset() is None: raise ValueError()
            except (ValueError,TypeError): raise errors.ValidationFailed('Use a timestamp with a timezone') from None
            base.observation(db,'manual',kind,number,guide=data['guide'],price=format(price,'f'),currency=data['currency'],
                             color=color,condition={'new':'N','used':'U'}[data['condition']],slot=data.get('slot'),observed_at=stamp)
            identifier = db.execute('SELECT max(id) FROM price_observations').fetchone()[0]
            ids.append(identifier)
        admin.audit(db,'bw_manual_prices','receipt',new=dict(ids=ids))
    return ids


def undo(db, receipt):
    with transaction(db):
        for identifier in json.loads(receipt['new_value'])['ids']:
            row = db.execute("SELECT * FROM price_observations WHERE id=? AND source='manual'",(identifier,)).fetchone()
            if not row: raise errors.UndoBlocked('Observation is unavailable')
            db.execute("UPDATE price_observations SET error='undone' WHERE id=?",(identifier,))
            key = tuple(row[k] for k in KEY)
            db.execute('DELETE FROM price_current WHERE '+CLAUSE,key)
            previous = db.execute('SELECT id FROM price_observations WHERE '+CLAUSE+
                                  ' AND error IS NULL ORDER BY id DESC LIMIT 1',key).fetchone()
            if previous: db.execute('INSERT INTO price_current VALUES(?,?,?,?,?,?,?,?,?)',(*key,previous[0]))
        admin.audit(db,'bw_manual_prices','undo',new=json.loads(receipt['new_value']))
