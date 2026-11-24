"""Helpers the import of another app's database and the import of Brick Work's own file share."""
import json


def norm(text):
    return ' '.join(str(text or '').casefold().split())


def mark_lines(db, table, owner, marks):
    """Put BrickTracker's marks on the lines they name (a copy's, or a loose figure's). Returns the marks with no such line."""
    lost = []
    for m in marks:
        if table == 'copy_part':
            scope = 'AND copy_figure_id IS NULL' if m['figure'] is None else 'AND copy_figure_id=(SELECT id FROM main.copy_figure WHERE copy_id=? AND item_id=? AND retired_at IS NULL)'
            args = (owner, m['part'], m['colour'], m['spare']) + (() if m['figure'] is None else (owner, m['figure']))
            row = db.execute(f'SELECT id, quantity FROM main.copy_part WHERE copy_id=? AND item_id=? AND color_id=? AND is_spare=? AND retired_at IS NULL {scope}', args).fetchone()
        else:
            row = db.execute('SELECT id, quantity FROM main.stock_part WHERE stock_id=? AND item_id=? AND color_id=? AND is_spare=? AND retired_at IS NULL',
                             (owner, m['part'], m['colour'], m['spare'])).fetchone()
        if row is None:
            lost.append(m)
            continue
        db.execute(f'UPDATE main.{table} SET missing=?, damaged=?, checked=? WHERE id=?',
                   (min(m['missing'], row['quantity']), min(m['damaged'], row['quantity']), m['checked'], row['id']))
    return lost


def line_digest(db, copy_id):
    rows = [list(r) for r in db.execute('SELECT id, missing, damaged, checked, retired_at FROM main.copy_part WHERE copy_id=? ORDER BY id', (copy_id,))]
    rows += [list(r) for r in db.execute('SELECT id, missing, retired_at FROM main.copy_figure WHERE copy_id=? ORDER BY id', (copy_id,))]
    return json.dumps(rows)


def flag_ids(db, copy_id):
    return sorted(r[0] for r in db.execute('SELECT flag_id FROM main.copy_flag WHERE copy_id=?', (copy_id,)))


def used(db, sql, ident):
    return db.execute(sql, (ident,)).fetchone() is not None
