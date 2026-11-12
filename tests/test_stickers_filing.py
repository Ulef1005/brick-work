"""The Sticker flag at filing (#201): `part_inventory.save` with a piece whose switch is on flags the stock line, and Undo takes only that link back."""
import pytest

from brickwork.core import part_inventory
from tests.app4 import app4, client, coll, csrf, pair, read, world  # noqa: F401 (fixtures)


def piece(world_, name, *, sticker=None, quantity=1, colour=None):
    chosen = dict(item_id=world_.brick, color_id=world_.red if colour is None else colour, quantity=quantity)
    if sticker is not None:
        chosen['sticker'] = sticker
    return dict(id='piece-' + name, candidates=[dict(item_id=world_.brick, score=.9)], chosen=chosen)


def flags_of(db, stock_id):
    return [r[0] for r in db.execute('SELECT f.name FROM stock_flag x JOIN flag f ON f.id=x.flag_id WHERE x.stock_id=?', (stock_id,))]


def test_filing_a_piece_with_the_switch_on_flags_the_stock_line_and_undo_takes_the_link_back(world, coll):
    db = coll.db
    assert db.execute("SELECT count(*) FROM flag WHERE lower(name)='sticker'").fetchone()[0] == 0
    event = part_inventory.save(db, [piece(world, 'a', sticker=True)], batch='stk-a', keep_photos=False)
    stock_id = db.execute("SELECT json_extract(new_value,'$.stock[0].id') FROM event WHERE id=?", (event,)).fetchone()[0]
    flag = db.execute("SELECT kind,shown_on_grid,system FROM flag WHERE name='Sticker'").fetchone()
    assert tuple(flag) == ('tag', 1, 0) and flags_of(db, stock_id) == ['Sticker']
    part_inventory.undo(db, event)
    assert flags_of(db, stock_id) == []


def test_filing_with_the_switch_off_or_absent_adds_no_flag_and_a_second_piece_reuses_the_flag(world, coll):
    db = coll.db
    event = part_inventory.save(db, [piece(world, 'a'), piece(world, 'b', sticker=False, colour=world.red + 0)], batch='stk-b', keep_photos=False)
    stock_id = db.execute("SELECT json_extract(new_value,'$.stock[0].id') FROM event WHERE id=?", (event,)).fetchone()[0]
    assert flags_of(db, stock_id) == []
    part_inventory.save(db, [piece(world, 'c', sticker=True)], batch='stk-c', keep_photos=False)
    part_inventory.save(db, [piece(world, 'd', sticker=True)], batch='stk-d', keep_photos=False)
    assert db.execute("SELECT count(*) FROM flag WHERE lower(name)='sticker'").fetchone()[0] == 1


def test_the_switch_must_be_a_boolean(world, coll):
    with pytest.raises(ValueError, match='sticker'):
        part_inventory.save(coll.db, [piece(world, 'x', sticker='yes')], batch='stk-x', keep_photos=False)


def test_a_figure_is_never_flagged(world, coll):
    db = coll.db
    figure = coll.item('minifigs', next(r[0] for r in db.execute("SELECT born_key FROM catalogue.item WHERE kind='minifigure' LIMIT 1")))
    one = dict(id='fig', candidates=[dict(item_id=figure, score=.9)], chosen=dict(item_id=figure, quantity=1, sticker=True))
    event = part_inventory.save(db, [one], batch='stk-fig', keep_photos=False)
    assert db.execute("SELECT count(*) FROM stock_flag").fetchone()[0] == 0 and event


