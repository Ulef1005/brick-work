"""#524 own import apply and undo tests. Invented data."""
from contextlib import closing
import json

import pytest

from brickwork.core import errors, own_export, own_import, undo
from brickwork.core.connect import connect
from tests.app4 import app4, coll, make_pair, pair, world  # noqa: F401


def _fresh_db(tmp_path):
    empty_dir = tmp_path / 'empty'
    empty_dir.mkdir()
    return make_pair(empty_dir, rich=True)


def _receipt(db, event_id):
    row = db.execute('SELECT new_value FROM main.event WHERE id=?', (event_id,)).fetchone()
    return json.loads(row[0])


def _live_counts(db):
    return {
        t: db.execute(f'SELECT count(*) FROM main.{t} WHERE archived_at IS NULL').fetchone()[0]
        for t in own_import.WRITE_ORDER
    }


def test_apply_into_fresh_install_keeps_marks_and_origin(coll, world, tmp_path):
    part = coll.db.execute(
        'SELECT id FROM main.copy_part WHERE copy_id=? AND copy_figure_id IS NULL AND retired_at IS NULL ORDER BY id LIMIT 1',
        (world.copy_a,),
    ).fetchone()
    assert part is not None
    coll.sql('UPDATE copy_part SET checked=1, missing=1 WHERE id=?', (part['id'],))
    coll.sql("UPDATE copy SET checked_by='rebrickable' WHERE id=?", (world.copy_a,))
    content = own_export.build(coll.db)['content']

    with closing(connect(_fresh_db(tmp_path))) as db:
        planned = own_import.plan(db, content)
        applied = own_import.apply(db, planned['id'], queue=False)
        assert applied['already_applied'] is False
        assert applied['event_id'] > 0
        counts = applied['counts']
        assert counts['storages'] == planned['counts']['storage']['new'] == 1
        assert counts['places'] == planned['counts']['place']['new'] == 1
        assert counts['lots'] == planned['counts']['lot']['new'] == 1
        assert counts['copies'] == planned['counts']['copy']['new'] == 3
        assert counts['stock_lines'] == planned['counts']['stock']['new'] == 4
        assert counts['wishes'] == planned['counts']['wish']['new'] == 2
        assert counts['differences'] == 0
        assert counts['unresolved'] == sum(c['unresolved'] for c in planned['counts'].values())

        copies = db.execute('SELECT * FROM main.copy WHERE archived_at IS NULL').fetchall()
        stocks = db.execute('SELECT * FROM main.stock WHERE archived_at IS NULL').fetchall()
        wishes = db.execute('SELECT * FROM main.wish WHERE archived_at IS NULL').fetchall()
        assert len(copies) == 3
        assert len(stocks) == 4
        assert len(wishes) == 2
        assert all(r['added_via'] == 'brickwork_export' for r in copies)
        assert all(r['added_via'] == 'brickwork_export' for r in stocks)
        assert all(r['added_via'] == 'brickwork_export' for r in wishes)

        receipt = _receipt(db, applied['event_id'])
        assert receipt['source'] == 'brickwork_export'
        new_copy_a = receipt['origin'][world.copy_a]
        copy_a_row = db.execute('SELECT * FROM main.copy WHERE id=?', (new_copy_a,)).fetchone()
        assert copy_a_row['checked_by'] == 'rebrickable'
        marked = db.execute(
            'SELECT count(*) FROM main.copy_part WHERE copy_id=? AND checked=1 AND missing=1 AND retired_at IS NULL',
            (new_copy_a,),
        ).fetchone()[0]
        assert marked == 1


def test_second_apply_returns_already_applied(coll, world, tmp_path):
    content = own_export.build(coll.db)['content']
    with closing(connect(_fresh_db(tmp_path))) as db:
        planned = own_import.plan(db, content)
        first = own_import.apply(db, planned['id'], queue=False)
        before = _live_counts(db)
        events_before = db.execute('SELECT count(*) FROM main.event').fetchone()[0]

        second = own_import.apply(db, planned['id'], queue=False)
        assert second['already_applied'] is True
        assert second['event_id'] == first['event_id']
        assert second['counts'] == first['counts']
        assert _live_counts(db) == before
        assert db.execute('SELECT count(*) FROM main.event').fetchone()[0] == events_before


def test_import_same_file_into_same_install_writes_nothing(coll, world):
    content = own_export.build(coll.db)['content']
    before = _live_counts(coll.db)
    planned = own_import.plan(coll.db, content)
    applied = own_import.apply(coll.db, planned['id'], queue=False)

    assert applied['already_applied'] is False
    counts = applied['counts']
    for key in ('storages', 'places', 'flags', 'lots', 'wishlists', 'copies', 'stock_lines', 'stock', 'wishes', 'differences', 'unresolved'):
        assert counts[key] == 0
    assert counts['skipped'] == sum(c['here'] for c in planned['counts'].values())
    assert counts['skipped'] > 0
    assert _live_counts(coll.db) == before


def test_undo_reverses_only_imported_rows_and_refuses_after_edit(coll, world, tmp_path):
    coll.sql(
        "INSERT INTO main.wishlist(id, name, note, sort, created_at) VALUES('wl-extra', 'Holiday', 'Gifts', 1, '2026-10-26T12:00:00Z')"
    )
    content = own_export.build(coll.db)['content']

    with closing(connect(_fresh_db(tmp_path))) as db:
        db.execute("INSERT INTO main.storage(id, name, created_at) VALUES('keep-storage', 'Keep Shelf', '2026-10-26T12:00:00Z')")
        db.execute("INSERT INTO main.place(id, name, created_at) VALUES('keep-place', 'Keep Shop', '2026-10-26T12:00:00Z')")
        db.execute("INSERT INTO main.wishlist(id, name, created_at) VALUES('keep-wl', 'Keep List', '2026-10-26T12:00:00Z')")
        db.commit()
        before = _live_counts(db)

        planned = own_import.plan(db, content)
        applied = own_import.apply(db, planned['id'], queue=False)
        assert applied['counts']['wishlists'] == 1
        receipt = _receipt(db, applied['event_id'])
        copy_id = receipt['copies'][0]
        original_note = db.execute('SELECT note FROM main.copy WHERE id=?', (copy_id,)).fetchone()[0]

        db.execute("UPDATE main.copy SET note='Edited later' WHERE id=?", (copy_id,))
        db.commit()
        after_import = _live_counts(db)
        with pytest.raises(ValueError, match='Something from this import has changed since · undo the later change first'):
            undo.undo_event(db, applied['event_id'])
        assert _live_counts(db) == after_import
        assert db.execute('SELECT 1 FROM main.event_undo WHERE event_id=?', (applied['event_id'],)).fetchone() is None

        db.execute('UPDATE main.copy SET note=? WHERE id=?', (original_note, copy_id))
        db.commit()
        undo.undo_event(db, applied['event_id'])
        assert _live_counts(db) == before
        assert db.execute("SELECT archived_at FROM main.storage WHERE id='keep-storage'").fetchone()[0] is None
        assert db.execute("SELECT archived_at FROM main.place WHERE id='keep-place'").fetchone()[0] is None
        assert db.execute("SELECT archived_at FROM main.wishlist WHERE id='keep-wl'").fetchone()[0] is None
        assert db.execute("SELECT archived_at FROM main.wishlist WHERE id='wl-extra'").fetchone()[0] is not None
        assert db.execute('SELECT 1 FROM main.event_undo WHERE event_id=?', (applied['event_id'],)).fetchone() is not None


def test_apply_skips_id_created_meanwhile(coll, world, tmp_path):
    content = own_export.build(coll.db)['content']
    with closing(connect(_fresh_db(tmp_path))) as db:
        planned = own_import.plan(db, content)
        place_row = planned['tables']['place'][0]
        storage_row = planned['tables']['storage'][0]
        db.execute(
            'INSERT INTO main.place(id, name, kind, created_at) VALUES(?, ?, ?, ?)',
            (place_row['id'], place_row['name'], place_row['kind'], '2026-10-26T12:00:00Z'),
        )
        db.execute(
            'INSERT INTO main.storage(id, name, type, parent_id, note, created_at) VALUES(?, ?, ?, ?, ?, ?)',
            (storage_row['id'], 'Renamed meanwhile', storage_row['type'], storage_row['parent_id'], storage_row['note'], '2026-10-26T12:00:00Z'),
        )
        db.commit()

        applied = own_import.apply(db, planned['id'], queue=False)
        counts = applied['counts']
        assert counts['places'] == 0
        assert counts['storages'] == 0
        assert counts['skipped'] >= 2
        assert counts['differences'] == 1
        assert counts['copies'] == 3
        assert db.execute('SELECT name FROM main.storage WHERE id=?', (storage_row['id'],)).fetchone()[0] == 'Renamed meanwhile'

        with pytest.raises(errors.ValidationFailed):
            own_import.apply(db, '0' * 32, queue=False)


def test_cli_import_file_apply_adds_the_new_copy_and_prints_the_undo(app4, coll, world, pair, tmp_path, capsys):
    from brickwork.web.cli import main
    from tests.test_own_import import _repack

    def mutate(name, data):
        if name != 'data/copy.jsonl':
            return data
        lines = data.splitlines()
        lines[0] = json.dumps(dict(json.loads(lines[0]), id='ffffffff-0000-4000-8000-000000000002')).encode()
        return b'\n'.join(lines) + b'\n'
    target = tmp_path / 'export.zip'
    target.write_bytes(_repack(own_export.build(coll.db)['content'], mutate=mutate))
    before = coll.db.execute('SELECT count(*) FROM main.copy WHERE archived_at IS NULL').fetchone()[0]

    assert main(['import-file', str(target), '--apply', '--json']) == 0
    done = json.loads(capsys.readouterr().out)
    assert done['counts']['copies'] == 1 and done['event_id']
    assert coll.db.execute('SELECT count(*) FROM main.copy WHERE archived_at IS NULL').fetchone()[0] == before + 1

    assert main(['import-file', str(target), '--apply']) == 0
    assert 'copies' not in capsys.readouterr().out


def test_a_zero_stock_row_is_unresolved_and_a_wish_already_wished_is_skipped(coll, world, tmp_path):
    from tests.test_own_import import _repack
    content = own_export.build(coll.db)['content']
    assert own_import._value_problem('stock', {'kind': 'part', 'quantity': 0, 'color': {'key': 1}}) == 'Quantity must be a whole number'

    def fresh_ids(name, data):
        if name != 'data/wish.jsonl':
            return data
        return b'\n'.join(json.dumps(dict(json.loads(l), id=f'ffffffff-0000-4000-8000-0000000000{i:02d}')).encode()
                          for i, l in enumerate(data.splitlines())) + b'\n'
    again = _repack(content, mutate=fresh_ids)
    before = coll.db.execute('SELECT count(*), sum(quantity) FROM main.wish WHERE archived_at IS NULL').fetchone()
    assert before[0] > 0
    planned = own_import.plan(coll.db, again)
    done = own_import.apply(coll.db, planned['id'], via='cli', actor='test')
    after = coll.db.execute('SELECT count(*), sum(quantity) FROM main.wish WHERE archived_at IS NULL').fetchone()
    assert tuple(after) == tuple(before) and done['counts']['wishes'] == 0
