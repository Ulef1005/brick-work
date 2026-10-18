"""One-off rule migration for 4.8a: recompute stored derived completeness.

``derived_state`` ignores figure component rows and spares since 4.8a, but
``copies.completeness`` is stored and normally recomputed only on write paths.
Run this once on every existing brickwork.db after deploying 4.8a.

Only copies with ``completeness_source='derived'`` are examined; manual and
unstated-source copies are never touched. It writes no ``events`` rows: it
applies a changed rule to derived data, it is not a user edit.
Usage: python -m brickwork.core.recompute <path-to-brickwork.db>
"""
import sys
from collections import Counter

from .completeness import derived_state
from .connect import connect


def recompute_completeness(db):
    """Recompute derived copies in one transaction; idempotent. Returns counts."""
    changes = Counter()
    examined = 0
    with db:
        db.execute('BEGIN IMMEDIATE')
        for row in db.execute("SELECT id,completeness FROM copies WHERE completeness_source='derived'").fetchall():
            examined += 1
            state = derived_state(db, row['id'])
            if state is not None and state != row['completeness']:
                db.execute('UPDATE copies SET completeness=? WHERE id=?', (state, row['id']))
                changes[(row['completeness'], state)] += 1
    return dict(examined=examined, changed=sum(changes.values()),
                transitions={f'{old or "none"}->{new}': n for (old, new), n in sorted(changes.items(), key=str)})


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print('usage: python -m brickwork.core.recompute <path>', file=sys.stderr)
        return 2
    db = connect(argv[0])
    try:
        result = recompute_completeness(db)
    finally:
        db.close()
    print(f"examined {result['examined']}, changed {result['changed']}")
    for transition, n in result['transitions'].items():
        print(f'  {transition}: {n}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
