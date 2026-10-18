"""Put a few demo copies into a running set check, through the app's own checker.

The demo cannot save, so its Start button only opens an exported page. These checks are made at build
time with the same core calls the app's checker makes, so the exported running pages show real states:
a check at its first part, one half done, one at the end with gaps, one at the end with nothing missing.
"""
import uuid

from ..core import checker
from ..core.admin import database

# copy id: (share of the required steps to answer, whether the test data's missing counts are kept)
PLAN = {
    '56325b99-16bc-549b-bb98-f7be2ab38829': (0.0, True),   # 7286-1: started, first part
    'eaacf51c-1b63-58ff-b1a9-a2ea287565fc': (0.4, True),   # 1592-1: about 40 % answered, resume
    '4fcedaaf-0c28-5203-9058-7044daabce23': (1.0, True),   # 40567-1: all answered, 6 missing
    'ff25ae37-7a6c-5804-92aa-bb3a03e64cac': (1.0, False),  # 6085-1: all answered, nothing missing
}


def call(db, copy_id, root, **payload):
    return checker.write(db, copy_id, dict(operation=str(uuid.uuid4()), **payload), root)


def stage(store, root):
    """Start and answer the planned checks; returns {copy id: (cursor, steps)}."""
    result = {}
    with database(store) as db:
        for copy_id, (share, keep_missing) in PLAN.items():
            if not db.execute('SELECT 1 FROM copies WHERE id=?', (copy_id,)).fetchone():
                continue
            # The test data's missing counts, read before the check overwrites them.
            missing = {r['token']: r['missing'] or 0 for r in checker.rows(db, copy_id, root, images=False, decorate=False)}
            call(db, copy_id, root, action='start', order='inventory')
            state = checker.view(db, copy_id, root)
            session = state['session']
            rows = {r['token']: r for r in state['rows']}
            required = [t for t in session['order'] if rows[t]['kind'] != 'spare']
            for token in required[:round(len(required) * share)]:
                quantity = rows[token]['quantity'] or 0
                found = max(0, quantity - (missing.get(token, 0) if keep_missing else 0))
                call(db, copy_id, root, action='answer', session=session['id'], token=token, found=found)
            if share >= 1 and any(r['kind'] == 'spare' for r in rows.values()):
                try:
                    call(db, copy_id, root, action='spares', session=session['id'], include=False)
                except ValueError:
                    pass  # no spare question at this point
            final = checker.session(db, copy_id)
            result[copy_id] = (final['cursor'], len(final['order']))
    return result
