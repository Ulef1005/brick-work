"""Manual prices on the 4.0 store: Undo restores the previous current price of the same key (M.8g review, issue #110)."""
from contextlib import closing

from brickwork.core import manual_prices
from brickwork.core.connect import connect

from tests.app4 import coll, pair, world  # noqa: F401  (fixtures)


def _receipt(db):
    return db.execute("SELECT max(id) FROM event WHERE entity_kind='manual_prices' AND field='receipt'").fetchone()[0]


def test_undo_restores_the_previous_price_when_an_empty_and_a_missing_slot_share_the_key(pair, world):
    # Codex review: the index treats slot '' and NULL as one key, so Undo must too, or the earlier price is lost.
    with closing(connect(pair)) as db:
        first, = manual_prices.record(db, [dict(item_id=world.gate, guide='manual', price='10', currency='EUR', condition='used', slot='')])
        manual_prices.record(db, [dict(item_id=world.gate, guide='manual', price='20', currency='EUR', condition='used')])
        assert db.execute('SELECT count(*) FROM price_current WHERE item_id=?', (world.gate,)).fetchone()[0] == 1
        manual_prices.undo(db, _receipt(db))
        current = db.execute('SELECT observation_id, slot FROM price_current WHERE item_id=?', (world.gate,)).fetchall()
    assert [tuple(r) for r in current] == [(first, '')]
