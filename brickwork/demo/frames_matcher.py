"""Frame 09 (the Matchmaker) loose stock staging for the 'frames-matcher' gate world."""

from ..core.admin import database
from ..core.stock import add_loose
from ..core.transaction import transaction
from . import clock, dataset
from .frames import INSPECTOR

COVER = (
    ('3660', 72, 4),
    ('2877', 71, 3),
    ('2412b', 70, 6),
    ('2431', 71, 5),
    ('2412b', 14, 2),
)


def stage_matcher(store):
    """Stage the loose stock frame 09 (the Matchmaker) draws on 'frames-matcher':
    copy 2 of 7213-1 (7 of 12 missing), 10210-1 (11 of 33), and 7938-1 (2 of 14),
    in that order, while copy 1 of 7213-1 gets none.
    """
    patched = clock.freeze_clock()
    try:
        with database(store) as db:
            with transaction(db):
                missing_parts = db.execute(
                    'SELECT DISTINCT p.item_id, p.color_id FROM copy_part p '
                    'WHERE p.missing>0 AND p.retired_at IS NULL AND p.copy_figure_id IS NULL'
                ).fetchall()
                for item_id, color_id in missing_parts:
                    db.execute(
                        "UPDATE stock SET archived_at=? WHERE kind='part' AND item_id=? AND color_id=? AND archived_at IS NULL",
                        (dataset.STAMP, item_id, color_id),
                    )
                for part, color, quantity in COVER:
                    row = db.execute(
                        'SELECT p.item_id,p.color_id FROM copy_part p JOIN item i ON i.id=p.item_id JOIN color c ON c.id=p.color_id '
                        'WHERE i.born_key=? AND c.born_key=? AND p.missing>0 AND p.retired_at IS NULL LIMIT 1',
                        (part, str(color)),
                    ).fetchone()
                    if row is None:
                        raise ValueError(f'frames-matcher: no missing line for {(part, color)}')
                    add_loose(db, item_id=row[0], color_id=row[1], quantity=quantity, condition='used', storage_id='storage-bag-07', via='cli')
                leaked = db.execute(
                    'SELECT DISTINCT i.born_key, c.born_key FROM copy_part p '
                    'JOIN copy cp ON cp.id=p.copy_id '
                    'JOIN item si ON si.id=cp.item_id '
                    'JOIN item i ON i.id=p.item_id '
                    'JOIN color c ON c.id=p.color_id '
                    "JOIN stock s ON s.kind='part' AND s.item_id=p.item_id AND s.color_id=p.color_id AND s.archived_at IS NULL "
                    "WHERE si.born_key='7213-1' AND p.copy_id!=? AND p.missing>0 AND p.retired_at IS NULL AND p.copy_figure_id IS NULL",
                    (INSPECTOR['copy'],),
                ).fetchone()
                if leaked is not None:
                    raise ValueError(f'frames-matcher: copy 1 of 7213-1 has live loose stock on {(leaked[0], leaked[1])}')
    finally:
        clock.thaw_clock(patched)
