"""Frame 11 (Storage, #500) as the 'frames-storage' gate world: the frames collection cut down to the six storages the frame lists.

The frame draws six storages (S-0001 to S-0006: Shelf A1 – Castle, Shelf A2 – Town, Parts drawer unit, Display case, Technic crate, Bag 07), seven sets, no figures
and six part lots, all six in the Parts drawer unit. The `frames` world is the real collection with its other storages, loose stock and figures; where the data
disagrees with the frame the data follows the frame (brickwork/demo/frames.py), so this layer archives everything the frame does not show and stages the six lots."""
from ..core import stock
from ..core.transaction import transaction
from . import dataset, real
from .frames import CODES, Layer

TYPES = {'Shelf A1 – Castle': 'Shelf', 'Shelf A2 – Town': 'Shelf', 'Parts drawer unit': 'Drawer', 'Display case': 'Shelf', 'Technic crate': 'Box', 'Bag 07': 'Bag'}
DRAWER = 'Parts drawer unit'
LOTS = (('3010', 72), ('3009', 71), ('87619', 15), ('3633', 72), ('3004', 4), ('3005', 4))   # six loose parts, one line each: the frame's "6 part lots"


class StorageLayer(Layer):
    def fill(self, db, ids):
        super().fill(db, ids)
        keep = ['storage-' + dataset.slug(name) for name in CODES]
        marks = ','.join('?' * len(keep))
        with transaction(db):
            db.execute(f'UPDATE stock SET archived_at=? WHERE archived_at IS NULL', (dataset.STAMP,))
            db.execute(f'UPDATE lot SET archived_at=? WHERE archived_at IS NULL', (dataset.STAMP,))
            db.execute(f'UPDATE storage SET parent_id=NULL WHERE id IN ({marks})', keep)
            db.execute(f'UPDATE storage SET archived_at=? WHERE archived_at IS NULL AND id NOT IN ({marks})', (dataset.STAMP, *keep))
            for name, kind in TYPES.items():
                db.execute('UPDATE storage SET type=? WHERE id=?', (kind, 'storage-' + dataset.slug(name)))
            for part, colour in LOTS:
                item = dataset.item_by(db, 'parts', part)
                stock.add_loose(db, item_id=item, color_id=dataset.colour_by(db, colour), quantity=5, condition='used', storage_id='storage-' + dataset.slug(DRAWER), via='cli')


def storage_layer(folder=real.FOLDER, pictures=False):
    return StorageLayer(folder, pictures, runner=False)
