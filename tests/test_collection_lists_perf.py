"""Speed fixes of the collection lists, each checked against the unoptimised result (M.8b): property scoping and the wish listing's reads.

The other tests of the old `test_bw_perf.py` are not collection reads and stay with their pieces (see the report)."""
import pytest

from tests.app4 import world, coll, pair, read, app4, client  # noqa: F401  (fixtures)
from brickwork.core import collection


@pytest.fixture
def props(coll, world):
    for item, theme in ((world.keep, 'Castle'), (world.gate, 'Castle'), (world.brick, 'Basic'), (world.figure, 'Knights')):
        coll.prop(item, 'theme', theme)
        coll.prop(item, 'year', '1990', source='bricklink')
    coll.prop(world.keep, 'theme', 'Other', source='rebrickable')            # a second source for the same key: an alternative
    return world


def test_detail_properties_scope_equals_whole_store(props, read):
    w = props
    with read() as db:
        every = [r[0] for r in db.execute('SELECT id FROM main.item')]
        whole = collection.properties(db, every)
        assert set(whole) >= {w.keep, w.gate, w.brick, w.figure}
        for item in (w.keep, w.gate, w.brick, w.figure):
            assert collection.properties(db, [item])[item] == whole[item]
        assert set(collection.properties(db, [w.keep])) == {w.keep}
        assert set(collection.properties(db, {w.gate, w.brick})) == {w.gate, w.brick}
        assert collection.properties(db, []) == {} and collection.properties(db, [w.mystery]) == {}
        assert {a['source'] for a in whole[w.keep]['theme']['alternatives']} | {whole[w.keep]['theme']['source']} == {'brickset', 'rebrickable'}


def test_wish_listing_reads_only_wish_identities_with_identical_output(coll, props, read):
    w = props
    coll.price(w.gate, '20.00', condition='used', sold=4)
    coll.price(w.plate, '0.30', colour=w.white, condition='new', sold=4)
    with read() as db:
        rows = collection.listing(db, 'S', wishes=True)
        assert {(r['item_id'], r['color_id']) for r in rows} == {(w.gate, None), (w.plate, w.white)}
        pairs = [(r['item_id'], r['color_id']) for r in rows]
        every = [(r[0], None) for r in db.execute('SELECT id FROM main.item')]
        whole_prices, whole_props = collection.prices(db, pairs=every), collection.properties(db, [i for i, _ in every])
        assert len(whole_prices) >= 4 and all(row['prices'] for row in rows)
        for row in rows:
            assert row['prices'] == whole_prices[row['item_id'], row['color_id']]
            assert row['properties'] == whole_props.get(row['item_id'], {})
        assert set(collection.prices(db, pairs=pairs)) <= {(w.gate, None), (w.plate, w.white)}
        statements = []
        db.set_trace_callback(statements.append)
        collection.listing(db, 'S', wishes=True)
        db.set_trace_callback(None)
        flat = [' '.join(statement.split()) for statement in statements]
        reads = [q for q in flat if 'FROM item_property' in q or 'FROM price_current p' in q]
        assert len(reads) == 2 and all('json_each' in q for q in reads)
