"""List price fetch (L5) and scoped detail matching (L6): same results as the whole-store reads, fewer rows read."""
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json

import pytest

from brickwork.core import admin, collection, collection_prices, workbench
from brickwork.core.connect import connect
from brickwork.core.sources import base


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / 'brickwork.db'
    monkeypatch.setenv('BW_DB_PATH', str(path))
    with closing(connect(path)) as db, db:
        for source in ('bricklink', 'rebrickable'):
            db.execute("INSERT OR IGNORE INTO sources VALUES(?,?,'api',1,NULL)", (source, source))
        db.execute("INSERT OR REPLACE INTO source_freshness VALUES('bricklink','prices',30)")
        for kind, number in (('S', '1'), ('S', '2'), ('P', '3001'), ('P', '3002'), ('P', '3003'), ('M', 'figA'), ('M', 'figB')):
            db.execute('INSERT INTO items(item_type,item_no,name) VALUES(?,?,?)', (kind, number, kind + number))
        for colour in (4, 5):
            db.execute('INSERT INTO colors(color_id,name) VALUES(?,?)', (colour, f'Colour {colour}'))
        db.execute("INSERT INTO flags(id,name,kind,shown_on_grid) VALUES('chk','Set is checked','status',1)")
        # Set 1: three live copies and an archived one (labels skip it); set 2: one copy.
        for identifier, number, archived in (('c0', '1', '2026-01-01'), ('c1', '1', None), ('c2', '1', None), ('c3', '1', None), ('c4', '2', None)):
            db.execute("INSERT INTO copies(id,set_no,completeness,archived_at) VALUES(?,?,'I',?)", (identifier, number, archived))
        db.execute("INSERT INTO item_flags VALUES('copy','c2','chk')")
        parts = [  # copy, part, colour, quantity, missing, damaged, parent figure
            ('c1', '3001', 4, 3, 2, 0, None), ('c1', '3001', 4, 1, 1, 0, None),  # two gap lines on one identity
            ('c1', '3002', 4, 2, 1, 0, None), ('c2', '3001', 4, 1, 1, 0, None),  # c2: its single gap, copy is "checked"
            ('c3', '3001', 4, 1, 0, 0, None), ('c4', '3003', 5, 2, 1, 1, None), ('c0', '3001', 4, 1, 1, 0, None),
            ('c1', '3003', 5, 1, 1, 0, 'figA')]  # a figure component: never a set gap
        for copy, number, colour, quantity, missing, damaged, parent in parts:
            db.execute('INSERT INTO copy_parts(copy_id,parent_minifig_type,parent_minifig,item_type,item_no,color_id,spare,quantity,missing,damaged) '
                       "VALUES(?,?,?,'P',?,?,0,?,?,?)", (copy, 'M' if parent else None, parent, number, colour, quantity, missing, damaged))
        db.execute("INSERT INTO copy_minifigs VALUES('c1','M','figA',1,1,NULL)")
        db.execute("INSERT INTO copy_minifigs VALUES('c4','M','figB',1,0,NULL)")
        stock = [('st1', 'P', '3001', 4, 5, 'U'), ('st2', 'P', '3001', 4, 1, 'N'), ('st3', 'P', '3003', 5, 2, 'U'),
                 ('st4', 'M', 'figA', None, 1, 'U'), ('st5', 'M', 'figB', None, 1, 'U'), ('st6', 'P', '3002', 4, 1, 'D'),
                 ('st7', 'P', '3002', 4, 1, 'U'), ('st8', 'P', '3002', 5, 9, 'U')]
        for identifier, kind, number, colour, quantity, condition in stock:
            db.execute('INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES(?,?,?,?,?,?)',
                       (identifier, kind, number, colour, quantity, condition))
        db.execute("INSERT INTO loose_minifig_parts VALUES('st4','P','3002',4,0,1,1,0,NULL,NULL,NULL)")
        db.execute("INSERT INTO loose_minifig_parts VALUES('st5','P','3003',5,0,1,0,0,NULL,NULL,NULL)")
        quotes = [  # item, colour, condition, guide, slot, source, observed_at, price, error
            ('S', '1', None, 'U', 'sold', None, 'bricklink', '2026-10-01T00:00:00Z', '10', None),
            ('S', '1', None, 'N', 'sold', None, 'bricklink', '2026-10-02T00:00:00+00:00', '30', None),
            ('S', '1', None, 'U', 'stock', None, 'bricklink', '2026-10-03T00:00:00+00:00', '12', None),
            ('S', '1', None, 'U', 'sold', 'boxed', 'bricklink', '2026-10-04T00:00:00+00:00', '99', None),
            ('S', '1', None, 'U', 'valuation', None, 'bricklink', '2026-10-05T00:00:00+00:00', '77', None),
            ('S', '2', None, 'U', 'sold', None, 'rebrickable', '2026-09-01T10:00:00', '20', None),
            ('S', '2', None, 'U', 'sold', 'alt', 'bricklink', '2025-01-01T00:00:00+00:00', '21', None),
            ('P', '3001', 4, 'U', 'sold', None, 'bricklink', 'not a date', '1', None),
            ('P', '3001', 4, 'N', 'sold', None, 'bricklink', '2026-10-01T00:00:00Z', '2', None),
            ('P', '3002', 4, 'U', 'sold', None, 'bricklink', None, '3', None),
            ('P', '3003', 5, 'U', 'sold', None, 'bricklink', '2026-10-01T00:00:00Z', '4', 'blocked')]
        for kind, number, colour, condition, guide, slot, source, stamp, price, error in quotes:
            db.execute("""INSERT INTO price_observations(item_type,item_no,color_id,condition,guide,slot,currency,price,source,observed_at,error,min,max,sold)
                VALUES(?,?,?,?,?,?,'EUR',?,?,?,?,'1','100',5)""", (kind, number, colour, condition, guide, slot, price, source, stamp, error))
            db.execute("""INSERT INTO price_current(item_type,item_no,color_id,condition,guide,slot,currency,observation_id)
                VALUES(?,?,?,?,?,?,'EUR',last_insert_rowid())""", (kind, number, colour, condition, guide, slot))
    return path


# ---- L5 -------------------------------------------------------------------------------------

def old_decorate_prices(rows):
    """The per-row version this replaced: parses and reads the clock for every row."""
    result = []
    for raw in rows:
        r = dict(raw)
        r['label'] = {'N': 'New', 'U': 'Used'}.get(r['condition'], 'Price')
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


def test_decorate_prices_equals_the_per_row_version(store):
    with admin.database(store) as db:
        rows = db.execute('''SELECT p.*,o.source,o.price,o.min,o.max,o.qty,o.sold,o.observed_at,o.error,f.max_age_days
            FROM price_current p JOIN price_observations o ON o.id=p.observation_id
            LEFT JOIN source_freshness f ON f.source=o.source AND f.kind='prices' ''').fetchall()
    assert len(rows) == 11
    new = collection.decorate_prices(rows)
    assert dump(new) == dump(old_decorate_prices(rows))
    assert {r['stale'] for r in new} == {True, False}  # the fixture exercises both outcomes
    assert [r['age'] for r in new if r['observed_at'] is None] == ['Age not recorded']


def test_decorate_prices_reads_the_clock_once_and_each_stamp_parse_is_shared(store, monkeypatch):
    with admin.database(store) as db:
        rows = db.execute('''SELECT p.*,o.source,o.price,o.min,o.max,o.qty,o.sold,o.observed_at,o.error,f.max_age_days
            FROM price_current p JOIN price_observations o ON o.id=p.observation_id
            LEFT JOIN source_freshness f ON f.source=o.source AND f.kind='prices' ''').fetchall()
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


@pytest.mark.parametrize('kind', ['S', 'M', 'P', 'I'])
def test_list_price_equals_the_choice_over_every_quote(store, kind):
    with admin.database(store) as db:
        rows = collection.listing(db, kind)
        identities = [(r['item_no'], r['color_id']) for r in rows]
        whole = collection.prices(db, listed_kind=kind, identities=identities) if rows else {}
        priority = collection_prices.priority(db)
        for row in rows:
            quotes = whole[row['item_type'], row['item_no'], row['color_id']]
            expected = collection_prices.choose([p for p in quotes if p['guide'] == 'sold' and p.get('slot') != 'boxed'], row['item_type'], priority, 'U')
            assert dump(row['price']) == dump(expected)
            # What a list row keeps is exactly the quotes its price is chosen from.
            assert all(p['guide'] == 'sold' and p['condition'] == 'U' and p.get('slot') != 'boxed' for p in row['prices'])
    if kind == 'S':
        by_item = {r['item_no']: r['price'] for r in rows}
        assert by_item['1']['price'] == '10' and by_item['2']['price'] == '21'  # not the boxed 99 or the N 30; BrickLink outranks Rebrickable


def test_list_fetches_only_the_quotes_it_uses(store, monkeypatch):
    seen = []
    real = collection.decorate_prices
    monkeypatch.setattr(collection, 'decorate_prices', lambda rows: seen.append(len(rows)) or real(rows))
    with admin.database(store) as db:
        collection.listing(db, 'S')
        collection.prices(db, listed_kind='S', identities=[('1', None), ('2', None)])
    assert seen == [3, 7]  # three used, sold, unboxed quotes of seven in all


def test_wishes_keep_every_quote(store):
    with admin.database(store) as db, db:
        db.execute("INSERT INTO wishlist(item_type,item_no,color_id,quantity) VALUES('S','1',NULL,1)")
    with admin.database(store) as db:
        row = collection.listing(db, 'S', wishes=True)[0]
        assert len(row['prices']) == 5


# ---- L6 -------------------------------------------------------------------------------------

def key(match):
    return tuple(match[k] for k in ('target', 'target_id', 'copy_id', 'source_id', 'have', 'suggested', 'completes', 'item_type', 'item_no', 'color_id'))


def reference_matches(db, kind, number, colour, selected):
    """The whole-store computation the detail page used before it was scoped."""
    every = workbench.gaps(db)
    found = workbench.matches(db, all_gaps=every)
    if selected and selected['entity'] == 'stock' and kind == 'M':
        found = [r for r in found if (r['target'] == 'stock-part' and r['copy_id'] == selected['id']) or (r['item_type'], r['item_no'], r['color_id']) == (kind, number, colour)]
    elif kind == 'S' and selected and selected['entity'] == 'copy':
        found = [r for r in found if r['copy_id'] == selected['id']]
    else:
        found = [r for r in found if (r['item_type'], r['item_no'], r['color_id']) == (kind, number, colour)]
    if kind in ('P', 'M'):
        left, _ = workbench.completion_context(db, every)
        found = sorted(found, key=lambda r: (not r['completes'], sum(left[r['copy_id']].values()) if r['copy_id'] in left else 0))
    return found


CASES = [('S', '1', None, dict(copy_id='c1')), ('S', '1', None, dict(copy_id='c2')), ('S', '1', None, dict(copy_id='c3')),
         ('S', '1', None, {}), ('S', '2', None, dict(copy_id='c4')),
         ('P', '3001', 4, {}), ('P', '3002', 4, {}), ('P', '3003', 5, {}), ('P', '3002', 5, {}),
         ('M', 'figA', None, {}), ('M', 'figA', None, dict(stock_id='st4')), ('M', 'figB', None, {}), ('M', 'figB', None, dict(stock_id='st5'))]


@pytest.mark.parametrize('kind,number,colour,which', CASES)
def test_detail_matches_equal_the_whole_store_computation(store, kind, number, colour, which):
    with admin.database(store) as db:
        detail = collection.detail(db, kind, number, colour=colour, **which)
        expected = reference_matches(db, kind, number, colour, detail['selected'])
        assert [key(m) for m in detail['matches']] == [key(m) for m in expected]
        assert detail['matching_headline'] == collection.matching_headline(expected) if kind == 'S' else True


def test_fixture_reaches_the_interesting_cases(store):
    with admin.database(store) as db:
        c1 = collection.detail(db, 'S', '1', copy_id='c1')['matches']
        c2 = collection.detail(db, 'S', '1', copy_id='c2')['matches']
        part = collection.detail(db, 'P', '3001', colour=4)['matches']
        figure = collection.detail(db, 'M', 'figA', stock_id='st4')
        assert {m['target'] for m in c1} >= {'part'} and not any(m['completes'] for m in c1)
        assert any(m['completes'] for m in c2)  # single gap, checked copy, enough stock
        assert len({m['source_id'] for m in part}) == 2 and any(m['completes'] for m in part)  # shared loose stock
        assert any(m['target'] == 'stock-part' for m in figure['matches']) or figure['matches'] == []
        assert any(m['can_take'] for m in collection.detail(db, 'S', '1', copy_id='c1')['consists'])


def test_scoped_gaps_are_the_whole_store_gaps_of_the_relevant_copies_in_order(store):
    with admin.database(store) as db:
        every = workbench.gaps(db)
        assert len(every) >= 6
        for kind, number, colour, copies, stocks in (
                ('P', '3001', 4, (), ()), ('P', '3002', 4, (), ()), ('S', '1', None, ('c1',), ()), ('M', 'figA', None, (), ('st4',)),
                ('M', 'figB', None, (), ('st5',)), ('S', '2', None, ('c4',), ())):
            copy_scope, stock_scope = workbench.relevant(db, kind, number, colour, copy_ids=copies, stock_ids=stocks)
            scoped = workbench.gaps(db, only=(copy_scope, stock_scope))
            expected = [g for g in every if (g['target'] == 'stock-part' and g['copy_id'] in stock_scope) or (g['target'] != 'stock-part' and g['copy_id'] in copy_scope)]
            assert dump(scoped) == dump(expected), (kind, number)
            assert len(scoped) < len(every) or (kind, number) == ('P', '3001')


def test_matches_ignore_stock_without_a_gap_but_otherwise_agree(store):
    with admin.database(store) as db:
        every = workbench.gaps(db)
        stock_ids = {m['source_id'] for m in workbench.matches(db, all_gaps=every)}
        assert 'st5' not in stock_ids and 'st6' not in stock_ids  # no gap on figB; condition D
        assert {'st1', 'st2', 'st3', 'st7'} <= stock_ids


def test_scoped_instances_and_copy_labels_equal_the_whole_kind(store):
    with admin.database(store) as db:
        for kind, number in (('S', '1'), ('S', '2'), ('P', '3001'), ('P', '3002'), ('M', 'figA')):
            whole = [r for r in collection.instances(db, kind) if r['item_no'] == number]
            assert dump(collection.instances(db, kind, number=number)) == dump(whole)
        labels = {r['id']: r['label'] for r in collection.instances(db, 'S') if r['entity'] == 'copy'}
        assert labels == {'c1': 'Set 1', 'c2': 'Set 2', 'c3': 'Set 3', 'c4': 'Set 1'}
        assert collection.copy_labels(db, ['c3', 'c4', 'c0', 'nope']) == {'c3': 'Set 3', 'c4': 'Set 1'}


def test_detail_never_reads_the_whole_collection(store, monkeypatch):
    calls = []
    real_instances, real_gaps, real_many = collection.instances, workbench.gaps, workbench.decorate_many
    monkeypatch.setattr(collection, 'instances', lambda db, *a, **k: calls.append(('instances', a, tuple(k))) or real_instances(db, *a, **k))
    monkeypatch.setattr(workbench, 'gaps', lambda db, only=None: calls.append(('gaps', only is not None)) or real_gaps(db, only))
    decorated = []
    monkeypatch.setattr(workbench, 'decorate_many', lambda db, rows: decorated.append(len(rows)) or real_many(db, rows))
    with admin.database(store) as db:
        every = len(real_gaps(db))
        for kind, number, colour, which in CASES:
            del calls[:], decorated[:]
            collection.detail(db, kind, number, colour=colour, **which)
            assert calls.count(('gaps', True)) == 1 and ('gaps', False) not in calls
            assert [c for c in calls if c[0] == 'instances'] == [('instances', (kind,), ('number',))]
            assert max(decorated) <= every
        del calls[:], decorated[:]
        collection.detail(db, 'P', '3002', colour=4)
        assert decorated and decorated[0] < every  # the gap decorate saw a fraction of the gaps


def test_detail_statement_count_does_not_grow_with_unrelated_copies(store):
    def statements(db, kind, number, colour):
        log = []
        db.set_trace_callback(log.append)
        collection.detail(db, kind, number, colour=colour)
        db.set_trace_callback(None)
        return log
    with admin.database(store) as db:
        before = len(statements(db, 'P', '3002', 4))
    with admin.database(store) as db, db:
        for n in range(30):
            db.execute("INSERT INTO items(item_type,item_no,name) VALUES('S',?,?)", (f'x{n}', 'x'))
            db.execute("INSERT INTO copies(id,set_no) VALUES(?,?)", (f'x{n}', f'x{n}'))
            db.execute("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,spare,quantity,missing) VALUES(?,'P','3003',5,0,1,1)", (f'x{n}',))
    with admin.database(store) as db:
        log = statements(db, 'P', '3002', 4)
        assert len(log) == before
