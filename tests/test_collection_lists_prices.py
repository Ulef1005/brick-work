"""List price fetch (L5) on the 4.0 store (M.8b): the same results as the whole-store reads, fewer rows read; and the scoped reads of the
item page. The matching/gaps tests of the old file (detail matches equal the whole-store computation, scoped gaps, matches ignore stock
without a gap, the fixture reaching the interesting cases, detail not calling `workbench.gaps` for the whole store) stay with M.8e."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json

import pytest

from brickwork.core import collection, collection_prices
from brickwork.core.sources import base
from tests.app4 import STAMP, world, coll, pair, read, app4, client  # noqa: F401  (fixtures)


def quotes(coll, w):
    """Eleven current quotes in the shapes the old fixture had: sold, stock, valuation and boxed, new and used, two sources, odd stamps,
    an error and a quote without a date."""
    coll.sql("INSERT OR REPLACE INTO source_freshness VALUES('bricklink','prices',30)")
    keep, gate, brick, plate = w.keep, w.gate, w.brick, w.plate
    red, white = w.red, w.white
    coll.sql('DELETE FROM price_current')                                  # the world's own used-sold prices: this test sets its own
    coll.sql('DELETE FROM price_observation')
    for item, colour, condition, guide, slot, source, stamp, price, error in [
            (keep, None, 'used', 'sold', None, 'bricklink', '2026-10-01T00:00:00Z', '10', None),
            (keep, None, 'new', 'sold', None, 'bricklink', '2026-10-02T00:00:00+00:00', '30', None),
            (keep, None, 'used', 'stock', None, 'bricklink', '2026-10-03T00:00:00+00:00', '12', None),
            (keep, None, 'used', 'sold', 'boxed', 'bricklink', '2026-10-04T00:00:00+00:00', '99', None),
            (keep, None, 'used', 'valuation', None, 'bricklink', '2026-10-05T00:00:00+00:00', '77', None),
            (gate, None, 'used', 'sold', None, 'rebrickable', '2026-09-01T10:00:00', '20', None),
            (gate, None, 'used', 'sold', 'alt', 'bricklink', '2025-01-01T00:00:00+00:00', '21', None),
            (brick, red, 'used', 'sold', None, 'bricklink', 'not a date', '1', None),
            (brick, red, 'new', 'sold', None, 'bricklink', '2026-10-01T00:00:00Z', '2', None),
            (plate, white, 'used', 'sold', None, 'bricklink', '', '3', None),
            (plate, red, 'used', 'sold', None, 'bricklink', '2026-10-01T00:00:00Z', '4', 'blocked')]:
        coll.price(keep if item is None else item, price, colour=colour, condition=condition, guide=guide, slot=slot, source=source, observed=stamp,
                   error=error, minimum='1', maximum='100', sold=5)


@pytest.fixture
def store(coll, world):
    """The rich world, its prices replaced by the eleven above, and what the four lists show: two sets, parts, a figure and a booklet."""
    quotes(coll, world)
    coll.add_copy('1000-2', condition='used', completeness='complete')
    coll.add_stock('part', world.plate, colour=world.red, quantity=1)
    coll.add_stock('part', world.plate, colour=world.white, quantity=1)
    coll.price(world.local_booklet, '5', condition='used')
    coll.price(world.figure, '2.00', condition='used', sold=3)
    coll.price(world.figure, '3.00', condition='new', sold=3)
    return world


# ---- L5 -------------------------------------------------------------------------------------

def old_decorate_prices(rows):
    """The per-row version this replaced: parses and reads the clock for every row (conditions are words now)."""
    result = []
    for raw in rows:
        r = dict(raw)
        r['item_type'] = collection.type_of(r.get('kind')) if r.get('kind') else r.get('item_type')
        r['label'] = {'new': 'New', 'used': 'Used'}.get(r['condition'], 'Price')
        if r['guide'] == 'stock':
            r['label'] += ' listings'
        if r['slot']:
            r['label'] = 'With box' if r['item_type'] == 'S' and r['slot'] == 'boxed' else r['label'] + ' · ' + r['slot'].replace('_', ' ')
        r['age'] = r['observed_at'][:10] if isinstance(r['observed_at'], str) and r['observed_at'] else 'Age not recorded'
        r['stale'] = False
        r['range'] = None
        try:
            if r['observed_at'] and r['max_age_days'] is not None:
                date = datetime.fromisoformat(r['observed_at'].replace('Z', '+00:00'))
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                r['stale'] = (base.now() - date).days > r['max_age_days']
        except (ValueError, TypeError, AttributeError):
            r['stale'] = False
        try:
            if r['guide'] == 'sold' and r['price'] is not None and r['min'] is not None and r['max'] is not None and (r['sold'] or 0) > 1:
                low, avg, high = map(Decimal, (r['min'], r['price'], r['max']))
                if low < high and low <= avg <= high:
                    r['range'] = float((avg-low)/(high-low)*100)
        except (InvalidOperation, ValueError, TypeError, AttributeError):
            r['range'] = None
        result.append(r)
    return result


def dump(value):
    return json.dumps(value, default=str, sort_keys=True)


CURRENT = '''SELECT p.*,i.kind,o.source,o.price,o.min,o.max,o.qty,o.sold,o.observed_at,o.error,f.max_age_days
    FROM price_current p JOIN price_observation o ON o.id=p.observation_id JOIN item i ON i.id=p.item_id
    LEFT JOIN source_freshness f ON f.source=o.source AND f.kind='prices' ORDER BY o.id'''


def test_decorate_prices_equals_the_per_row_version(store, read):
    with read() as db:
        rows = db.execute(CURRENT).fetchall()
    assert len(rows) == 11 + 3
    new = collection.decorate_prices(rows)
    assert dump(new) == dump(old_decorate_prices(rows))
    assert {r['stale'] for r in new} == {True, False}  # the fixture exercises both outcomes
    assert [r['age'] for r in new if not r['observed_at']] == ['Age not recorded']


def test_decorate_prices_reads_the_clock_once_and_each_stamp_parse_is_shared(store, read, monkeypatch):
    with read() as db:
        rows = db.execute(CURRENT).fetchall()
    reads = []
    monkeypatch.setattr(collection, 'now', lambda: reads.append(1) or datetime(2026, 10, 16, tzinfo=timezone.utc))
    collection.decorate_prices(rows)
    assert len(reads) == 1
    collection_prices._dated.cache_clear()
    collection.decorate_prices(rows)
    collection.decorate_prices(rows)
    info = collection_prices._dated.cache_info()
    dated_rows = [r['observed_at'] for r in rows if r['observed_at'] and r['max_age_days'] is not None]
    assert info.misses == len(set(dated_rows)) and info.hits + info.misses == 2 * len(dated_rows) and info.hits > 0


def test_dated_still_parses_like_before():
    assert collection_prices.dated('2026-10-01T00:00:00Z') == datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert collection_prices.dated('2026-10-01T00:00:00') == datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert collection_prices.dated('nonsense') is None and collection_prices.dated(None) is None and collection_prices.dated(5) is None
    assert collection_prices.dated(['x']) is None


@pytest.mark.parametrize('letter', ['S', 'M', 'P', 'I'])
def test_list_price_equals_the_choice_over_every_quote(store, read, letter):
    with read() as db:
        rows = collection.listing(db, letter)
        assert rows
        pairs = [(r['item_id'], r['color_id']) for r in rows]
        whole = collection.prices(db, pairs=pairs)
        priority = collection_prices.priority(db)
        for row in rows:
            every = whole[row['item_id'], row['color_id']]
            expected = collection_prices.choose([p for p in every if p['guide'] == 'sold' and p.get('slot') != 'boxed'], row['kind'], priority, 'used')
            assert dump(row['price']) == dump(expected)
            # What a list row keeps is exactly the quotes its price is chosen from.
            assert all(p['guide'] == 'sold' and p['condition'] == 'used' and p.get('slot') != 'boxed' for p in row['prices'])
    if letter == 'S':
        by_item = {r['item_id']: r['price'] for r in rows}
        assert by_item[store.keep]['price'] == '10' and by_item[store.gate]['price'] == '21'   # not the boxed 99 or the new 30; BrickLink outranks Rebrickable
    if letter == 'P':
        assert {r['price']['price'] if r['price'] else None for r in rows if r['item_id'] == store.plate} == {'3', None}   # the errored quote never prices a row


def test_list_fetches_only_the_quotes_it_uses(store, read, monkeypatch):
    seen = []
    real = collection.decorate_prices
    monkeypatch.setattr(collection, 'decorate_prices', lambda rows: seen.append(len(rows)) or real(rows))
    with read() as db:
        collection.listing(db, 'S')
        collection.prices(db, pairs=[(store.keep, None), (store.gate, None)])
    assert seen == [3, 7]  # three used, sold, unboxed quotes of seven in all


def test_wishes_keep_every_quote(coll, store, read):
    coll.add_wish(store.keep, quantity=1)
    with read() as db:
        rows = {r['item_id']: r for r in collection.listing(db, 'S', wishes=True)}
        assert len(rows[store.keep]['prices']) == 5 and len(rows[store.gate]['prices']) == 2


# ---- the item page reads only what it shows -------------------------------------------------

def test_scoped_instances_and_copy_labels_equal_the_whole_kind(coll, store, read):
    first = coll.add_copy('1000-1')
    coll.sql("UPDATE copy SET created_at=? WHERE id=?", ('2026-01-01T00:00:00.000Z', store.copy_a))
    coll.sql("UPDATE copy SET created_at=? WHERE id=?", ('2026-01-02T00:00:00.000Z', store.copy_b))
    coll.sql("UPDATE copy SET created_at=? WHERE id=?", ('2026-01-03T00:00:00.000Z', first))
    archived = coll.add_copy('1000-1')
    coll.sql("UPDATE copy SET archived_at=?, created_at=? WHERE id=?", (STAMP, '2025-12-31T00:00:00.000Z', archived))
    with read() as db:
        for kind, item in (('set', store.keep), ('set', store.gate), ('part', store.brick), ('minifigure', store.figure)):
            whole = [r for r in collection.instances(db, kind) if r['item_id'] == item]
            assert dump(collection.instances(db, kind, item_id=item)) == dump(whole)
        labels = {r['id']: r['label'] for r in collection.instances(db, 'set') if r['item_id'] == store.keep}
        assert labels == {store.copy_a: 'Set 1', store.copy_b: 'Set 2', first: 'Set 3'}
        assert collection.copy_labels(db, [first, store.copy_b, archived, 'nope']) == {first: 'Set 3', store.copy_b: 'Set 2'}


def test_detail_reads_only_its_item_from_the_instances(store, read, monkeypatch):
    calls = []
    real = collection.instances
    monkeypatch.setattr(collection, 'instances', lambda db, *a, **k: calls.append((a, k)) or real(db, *a, **k))
    with read() as db:
        for item, colour in ((store.keep, None), (store.gate, None), (store.brick, store.red), (store.plate, store.white), (store.figure, None)):
            del calls[:]
            collection.detail(db, item, colour=colour)
            assert len(calls) == 1 and calls[0][1].get('item_id') == item, (item, calls)


def test_detail_statement_count_does_not_grow_with_the_number_of_copies(coll, store, read):
    def statements(item, colour):
        log = []
        with read() as db:
            db.set_trace_callback(log.append)
            collection.detail(db, item, colour=colour)
            db.set_trace_callback(None)
        return len(log)
    before = {key: statements(*key) for key in ((store.brick, store.red), (store.keep, None), (store.figure, None))}
    for _ in range(12):
        coll.add_copy('1000-2')
        coll.add_copy('1000-1')
    assert {key: statements(*key) for key in before} == before
