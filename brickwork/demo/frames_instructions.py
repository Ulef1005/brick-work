"""Frame 03 (Find instructions) booklet staging for the 'frames-instructions' gate world."""

from ..core.admin import database
from ..core.transaction import transaction
from . import dataset

WITH_BOOKLET = ('10254-1', '21028-1', '31120-1')   # the frame lists the four other sets of the Sets frame's collection as having no booklet


def stage_instructions(store):
    """Give three sets of the collection a PDF, so the frame's list (7213-1, 7938-1, 8043-1, 10210-1) is what the page shows."""
    with database(store) as db:
        with transaction(db):
            for number in WITH_BOOKLET:
                row = db.execute("SELECT id FROM item WHERE kind='set' AND born_key=?", (number,)).fetchone()
                if row is None:
                    raise ValueError(f'frames-instructions: no set {number}')
                db.execute('INSERT INTO instruction_file(item_id, path, label, added_at) VALUES (?,?,?,?)',
                           (row[0], f'data/instructions/frames-{number}.pdf', 'Instructions', dataset.STAMP))
