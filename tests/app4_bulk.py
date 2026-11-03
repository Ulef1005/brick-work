"""Many rows at once on a 4.0 collection, for the tests that count queries or page sizes (M.8b, issue #110).

`bulk_owned` writes the items (BrickLink-born local ones) and what owns them with `executemany` and one commit, never row by row."""
import uuid

from tests.app4 import STAMP

BULK_BASE = 1_500_000_000
NAMESPACE = {'set': 'S', 'part': 'P', 'minifigure': 'M', 'instructions': 'I', 'box': 'O', 'gear': 'G', 'book': 'B', 'catalog': 'C'}


def bulk_owned(coll, kind, count, *, prefix='bulk', colour=None, condition='used', start=0):
    """`count` local items of `kind`, each owned once: a copy for a set, a stock line for anything else (a part in `colour`, default red).
    Returns the item ids."""
    db = coll.db
    ids = [BULK_BASE + start + n for n in range(count)]
    db.executemany('''INSERT INTO main.item(id,origin,kind,kind_source,name,born_provider,born_namespace,born_key,created_at,updated_at)
                      VALUES(?,'local',?,'bricklink',?,'bricklink',?,?,?,?)''',
                   [(i, kind, f'{prefix} {start + n}', NAMESPACE[kind], f'{prefix}-{start + n}', STAMP, STAMP) for n, i in enumerate(ids)])
    if kind == 'set':
        db.executemany('''INSERT INTO copy(id,item_id,inventory_source,inventory_digest,condition,created_at,updated_at) VALUES(?,?,'none','none',?,?,?)''',
                       [(uuid.uuid4().hex, i, condition if condition in ('new', 'used') else None, STAMP, STAMP) for i in ids])
    else:
        colour = (colour or coll.colour('4')) if kind == 'part' else None
        extra = kind == 'minifigure'
        db.executemany('''INSERT INTO stock(id,kind,item_id,color_id,quantity,condition,created_at,updated_at,inventory_source,inventory_digest)
                          VALUES(?,?,?,?,1,?,?,?,?,?)''',
                       [(uuid.uuid4().hex, kind, i, colour, condition, STAMP, STAMP, 'none' if extra else None, 'none' if extra else None) for i in ids])
    db.commit()
    return ids
