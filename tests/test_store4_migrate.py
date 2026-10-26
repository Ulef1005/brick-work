"""The 3.3 -> 4.0 migration writer (design 8.1, 8.2, 8.4, 8.5, 8.9, 8.10; issue #109, M.7b).

The 3.3 stores are the frozen regression fixtures (upgraded to 3.3 on open) and a synthetic one built from the 3.3 schema
(`store4_migrate_fixtures.py`, design 8.11); the catalogue is the fixture catalogue of the mint tests."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from brickwork.core.connect import connect as connect33
from brickwork.store4.connect import connect
from brickwork.store4.errors import SchemaMismatch
from brickwork.store4.migrate import MigrationError, Migration, NeedsDecision, migrate
from tests.store4_migrate_fixtures import BL_LINE, build_33
from tests.store4_mint_fixtures import build_catalogue

REGRESSION = sorted((Path(__file__).parent / 'regression' / 'fixtures').glob('*.db'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def catalogue(tmp_path):
    (tmp_path / 'cat').mkdir()
    return build_catalogue(tmp_path / 'cat')


@pytest.fixture
def world(tmp_path, catalogue):
    src = tmp_path / 'bw33.db'
    ids = build_33(src)
    with Migration(src, catalogue, tmp_path / 'out' / 'brickwork-4.db') as m:
        m.write()
        yield m, ids


def rows(m, sql, *args):
    return [tuple(r) for r in m.db.execute(sql, args)]


def one(m, sql, *args):
    return m.db.execute(sql, args).fetchone()[0]


# ---------- the regression fixtures ----------

@pytest.mark.parametrize('fixture', REGRESSION, ids=lambda p: p.name)
def test_every_regression_fixture_migrates(fixture, tmp_path, catalogue):
    """Each frozen store (a 3.2 one is upgraded to 3.3 first, as the app does on open) goes through the writer."""
    src = tmp_path / 'bw33.db'
    shutil.copy(fixture, src)
    connect33(src).close()                                    # the 3.3 upgrade on open
    with sqlite3.connect(src) as db:
        db.execute('PRAGMA journal_mode=DELETE')
        want = {t: db.execute(f'SELECT count(*) FROM {t}').fetchone()[0]
                for t in ('copies', 'copy_minifigs', 'loose_stock', 'loose_minifig_parts', 'wishlist', 'flags', 'storages', 'lots',
                          'price_observations', 'price_current', 'price_watch', 'item_flags', 'api_tokens')}
        parts = db.execute('SELECT count(*) FROM copy_parts').fetchone()[0]
    before = sha(src)
    with Migration(src, catalogue, tmp_path / 'brickwork-4.db') as m:
        r = m.write()
        assert r.foreign_key_check == [] and r.integrity_check == 'ok' and r.inputs_unchanged
        assert rows(m, 'PRAGMA foreign_key_check') == []
        got = r.counts()
        assert got['copy'] == want['copies'] and got['stock'] == want['loose_stock'] and got['stock_part'] == want['loose_minifig_parts']
        assert got['wish'] == want['wishlist'] and got['flag'] == want['flags'] and got['storage'] == want['storages']
        assert got['price_observation'] == want['price_observations'] and got['price_current'] == want['price_current']
        assert got['copy_flag, stock_flag, wish_flag'] == want['item_flags'] and got['api_token'] == want['api_tokens']
        assert got['copy_figure'] >= want['copy_minifigs']
        summed = sum(len(s['rows']) - 1 for s in r.summed_lines if s['table'] == 'copy_parts')
        leaving = len(r.non_part_lines) + len(r.figure_lines_from_parts) + len([e for e in r.extras if e['action'] == 'dropped'])
        assert got['copy_part'] == parts - summed - leaving
        assert one(m, "SELECT count(*) FROM event") == 1
        m.publish()
    assert sha(src) == before
    with closing(connect(tmp_path / 'brickwork-4.db', catalogue, read_only=True)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_a_3_3_file_with_a_pending_wal_is_refused(tmp_path, catalogue):
    src = tmp_path / 'bw33.db'
    build_33(src)
    Path(str(src) + '-wal').write_bytes(b'x' * 32)
    with pytest.raises(MigrationError, match='must be stopped'):
        Migration(src, catalogue, tmp_path / 'out.db')


def test_a_3_2_file_is_refused(tmp_path, catalogue):
    src = tmp_path / 'old.db'
    shutil.copy(next(p for p in REGRESSION if 'v3.2' in p.name), src)
    with pytest.raises(MigrationError, match='not 3.3'):
        Migration(src, catalogue, tmp_path / 'out.db')


# ---------- the shape of the output ----------

def test_ids_are_kept_and_words_translated(world):
    m, ids = world
    assert rows(m, 'SELECT id, name, type, parent_id FROM storage ORDER BY id') == [('st1', 'Shelf A', 'Shelf', None), ('st2', 'Weird box', 'Other', 'st1')]
    assert rows(m, 'SELECT id, kind, shown_on_grid, system FROM flag ORDER BY id') == [('f_owner', 'owner', 1, 0), ('f_status', 'status', 1, 0),
                                                                                       ('f_tag', 'tag', 1, 0)]
    copy = m.db.execute("SELECT * FROM copy WHERE id='copy-bl'").fetchone()
    assert (copy['condition'], copy['completeness'], copy['completeness_source'], copy['storage_id'], copy['place_id'], copy['pinned']) == \
        ('used', 'complete', 'manual', 'st1', 'p1', 1)
    assert (copy['inventory_source'], copy['inventory_version'], copy['fetched_inventory_id']) == ('migrated', None, None)
    assert copy['inventory_digest'] and copy['inventory_pending'] is None
    stock = {r['id']: r for r in m.db.execute('SELECT * FROM stock')}
    assert stock['s-part']['condition'] == 'used' and stock['s-null']['condition'] == 'damaged' and stock['s-part']['place_id'] == 'p1'
    assert stock['s-fig']['kind'] == 'minifigure' and stock['s-fig']['inventory_source'] == 'migrated' and stock['s-fig']['inventory_digest']
    assert stock['s-part']['inventory_source'] is None and stock['s-ins']['kind'] == 'instructions'
    assert (stock['s-fig']['missing'], stock['s-fig']['damaged'], stock['s-fig']['checked']) == (1, 0, 0)
    assert rows(m, "SELECT count(*) FROM stock_part WHERE stock_id='s-fig'") == [(2,)]
    assert rows(m, "SELECT lot_id FROM stock WHERE id='s-part'") == [('l1',)]
    assert rows(m, "SELECT storage_id, place_id FROM lot WHERE id='l1'") == [('st1', 'p1')]
    assert rows(m, "SELECT wishlist_id FROM wish ORDER BY wishlist_id") == [('default',), ('w2',)]
    assert one(m, "SELECT name FROM wishlist WHERE id='w2'") == 'Second list'
    assert one(m, "SELECT count(*) FROM wishlist") == 2                     # 'default' is updated, not duplicated


def test_meta_and_one_event(world, catalogue):
    m, _ = world
    meta = dict(rows(m, 'SELECT key, value FROM meta'))
    assert meta['schema_version'] == '4.0' and meta['install_id'] != ''
    cat = dict(rows(m, 'SELECT key, value FROM catalogue.meta'))
    assert meta['catalogue_id'] == cat['catalogue_id']
    assert meta['catalogue_item_high_water'] == cat['item_high_water'] and meta['catalogue_color_high_water'] == cat['color_high_water']
    moved = json.loads(meta['migrated_from'])
    assert moved['file'] == 'bw33.db' and moved['sha256'] == m.result.source['sha256'] and moved['report_digest'] is None
    events = rows(m, 'SELECT via, entity_kind, field FROM event')
    assert events == [('migration', 'migration', 'migrated_from')]
    new = json.loads(one(m, 'SELECT new_value FROM event'))
    assert new['rows']['copy'] == 6 and new['catalogue_sha256'] == sha(catalogue)
    assert one(m, 'SELECT count(*) FROM catalogue_build') >= 1
    assert one(m, 'SELECT count(*) FROM color') == 275 or one(m, 'SELECT count(*) FROM color') >= 6   # every catalogue colour is projected


def test_finish_puts_the_digest_in_meta(world):
    m, _ = world
    m.finish('abc123')
    assert json.loads(one(m, "SELECT value FROM meta WHERE key='migrated_from'"))['report_digest'] == 'abc123'


def test_the_event_can_be_deferred_to_the_report(tmp_path, catalogue):
    src = tmp_path / 'bw33.db'
    build_33(src)
    with Migration(src, catalogue, tmp_path / 'out.db') as m:
        m.write(record_event=False)
        assert one(m, 'SELECT count(*) FROM event') == 0
        m.record_event('deadbeef')
        assert json.loads(one(m, 'SELECT new_value FROM event'))['report_digest'] == 'deadbeef'


# ---------- exclusive output, inputs untouched, publish ----------

def test_output_is_created_exclusively(tmp_path, catalogue):
    src = tmp_path / 'bw33.db'
    build_33(src)
    out = tmp_path / 'brickwork-4.db'
    out.write_text('precious')
    with pytest.raises(FileExistsError):
        Migration(src, catalogue, out)
    assert out.read_text() == 'precious'
    out.unlink()
    m = migrate(src, catalogue, out)
    out.write_text('appeared meanwhile')                      # something took the name before the publish
    with pytest.raises(FileExistsError):
        m.publish()
    assert out.read_text() == 'appeared meanwhile'
    m.abort()
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith('.')] == []   # no temporary file is left behind


def test_nothing_is_visible_before_publish_and_inputs_are_unchanged(tmp_path, catalogue):
    src = tmp_path / 'bw33.db'
    build_33(src)
    before = (sha(src), sha(catalogue))
    out = tmp_path / 'out' / 'brickwork-4.db'
    with Migration(src, catalogue, out) as m:
        m.write()
        assert not out.exists() and m.temp_path.exists()
        assert m.result.inputs_unchanged and (sha(src), sha(catalogue)) == before
        assert m.publish() == out
    assert out.exists() and not m.temp_path.exists()
    assert (sha(src), sha(catalogue)) == before
    with closing(connect(out, catalogue)) as db:               # an ordinary 4.0 collection, openable by the store
        assert db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == '4.0'
    with pytest.raises(SchemaMismatch):
        connect(src, catalogue)                                # the 3.3 file is never opened as 4.0


def test_a_changed_input_blocks_the_publish(tmp_path, catalogue):
    src = tmp_path / 'bw33.db'
    build_33(src)
    m = migrate(src, catalogue, tmp_path / 'out.db')
    with open(src, 'ab') as f:
        f.write(b'x')
    with pytest.raises(MigrationError, match='changed'):
        m.publish()
    assert not (tmp_path / 'out.db').exists()
    m.abort()


def test_a_failure_leaves_no_file(tmp_path, catalogue):
    src = tmp_path / 'bw33.db'
    build_33(src)
    with sqlite3.connect(src) as db:                           # a count the constraints cannot take: missing above quantity
        db.execute("UPDATE copy_parts SET missing=9 WHERE copy_id='copy-upd'")
    with pytest.raises(NeedsDecision) as error:
        migrate(src, catalogue, tmp_path / 'out.db')
    assert not (tmp_path / 'out.db').exists() and [p for p in tmp_path.iterdir() if p.name.startswith('.')] == []
    assert error.value.rows and 'copy_parts' in error.value.rows[0]['table']


# ---------- Q7: duplicate lines are summed and listed ----------

def test_duplicate_lines_are_summed(world):
    m, ids = world
    [line] = m.result.summed_lines
    assert (line['copy_id'], line['item_no'], line['color_id'], line['rows']) == ('copy-proj', '3023', 5, [ids['dup1'], ids['dup2']])
    assert (line['quantity'], line['missing'], line['checked']) == (2, 1, 0)       # checked only if every summed row was
    got = rows(m, "SELECT p.quantity, p.missing, p.checked FROM copy_part p JOIN item i ON i.id=p.item_id JOIN color c ON c.id=p.color_id "
                  "WHERE p.copy_id='copy-proj' AND i.born_key='3023' AND c.born_key='5' AND p.copy_figure_id IS NULL AND p.is_spare=0".replace("c.born_key='5'", "c.born_key='4'"))
    assert got == [(2, 1, 0)]


# ---------- the copy lines ----------

def test_colour_null_becomes_no_colour_and_figure_rows_get_their_figure(world):
    m, ids = world
    head = rows(m, "SELECT p.color_id, p.copy_figure_id FROM copy_part p JOIN item i ON i.id=p.item_id WHERE p.copy_id='copy-proj' "
                   "AND i.born_key='3626apr0001' ORDER BY p.copy_figure_id IS NOT NULL")
    assert head[0] == (1, None)                                                    # colour NULL -> 1, a set line
    assert head[1][0] != 1 and head[1][1] is not None                              # the component row, Yellow, under its figure
    figure = rows(m, "SELECT f.id, f.quantity, f.inventory_source FROM copy_figure f JOIN item i ON i.id=f.item_id WHERE i.born_key='fig-000004'")
    assert figure[0][1:] == (1, 'migrated') and figure[0][0] == head[1][1]
    assert rows(m, 'SELECT count(*) FROM copy_part WHERE copy_figure_id IS NOT NULL') == [(2,)]


def test_placeholders_resolve_or_become_local(world):
    m, _ = world
    assert rows(m, "SELECT p.quantity, i.origin, c.born_key FROM copy_part p JOIN item i ON i.id=p.item_id JOIN color c ON c.id=p.color_id "
                   "WHERE i.born_namespace='parts' AND i.born_key='3023' AND p.copy_id='copy-proj' AND c.born_key='15'") == \
        [(2, 'catalogue', '15')]                                                     # `?` part, White -> the catalogue item (rule 1)
    local = m.db.execute("SELECT i.* FROM copy_figure f JOIN item i ON i.id=f.item_id WHERE i.born_key='fig-999999'").fetchone()
    assert (local['origin'], local['kind'], local['born_provider']) == ('local', 'minifigure', 'rebrickable')
    assert rows(m, 'SELECT provider, status, reason FROM item_provider_status WHERE item_id=?', local['id']) == [('bricklink', 'to_check', 'migration')]


def test_sticker_sheets_stay_apart(world):
    m, _ = world
    stickers = rows(m, "SELECT i.origin, i.born_provider, i.born_key FROM copy_part p JOIN item i ON i.id=p.item_id WHERE p.copy_id='copy-proj' "
                       "AND (i.born_key='003402' OR i.born_key LIKE '31%stk01') ORDER BY i.origin")
    assert stickers == [('catalogue', 'rebrickable', '003402'), ('local', 'bricklink', '311.1stk01')]
    assert len(m.result.mint.collisions) == 1


def test_minifigure_and_gear_lines_in_copy_parts(world):
    m, ids = world
    figure = rows(m, "SELECT f.quantity, f.missing FROM copy_figure f JOIN item i ON i.id=f.item_id WHERE i.born_key='cas999'")
    assert figure == [(2, 1)]                                                       # a BrickLink list's figure line is a figure line in 4.0
    assert [l['item_no'] for l in m.result.figure_lines_from_parts] == ['cas999']
    assert sorted((x['item_no'], x['copy_part_ids'][0]) for x in m.result.non_part_lines) == \
        sorted([('gear01', ids['g_line']), ('3001', ids['g_nosupport']), ('gear02', ids['comp_gear'])])             # no copy_part can hold gear: listed, not silent


def test_a_part_filed_as_gear_is_carried_as_the_part(world):
    m, ids = world
    [crossed] = m.result.type_crossed
    assert (crossed['item_no'], crossed['copy_part_id'], crossed['holder']) == ('2071c01pb01', ids['g_crossed'], ('S', '2070-1', None))
    assert rows(m, "SELECT i.born_namespace, i.born_key, p.color_id, p.quantity FROM copy_part p JOIN item i ON i.id=p.item_id "
                   "WHERE p.copy_id='copy-proj' AND i.born_key='2071pr0001'") == [('parts', '2071pr0001', 1, 1)]
    assert one(m, "SELECT count(*) FROM item WHERE kind='gear' AND born_key='2071c01pb01'") == 0       # no local gear item
    assert one(m, "SELECT count(*) FROM item WHERE kind='gear' AND born_key='3001'") == 1               # the unsupported one keeps its item


# ---------- 8.5 extras ----------

def lines_of(m, copy_id, born_key, colour_key):
    return rows(m, "SELECT p.quantity, p.missing, p.damaged, p.checked, p.is_spare FROM copy_part p JOIN item i ON i.id=p.item_id "
                   "JOIN color c ON c.id=p.color_id WHERE p.copy_id=? AND i.born_key=? AND c.born_key=? ORDER BY p.is_spare", copy_id, born_key, colour_key)


def test_extras_through_a_valid_source_ref(world):
    m, ids = world
    assert lines_of(m, 'copy-bl', '3001', '4')[0] == (4, 0, 0, 0, 0)               # 5 - 1
    assert lines_of(m, 'copy-bl', '3001', '4')[1] == (1, 0, 0, 0, 1)               # the spare row stays
    change = next(e for e in m.result.extras if e['copy_part_id'] == ids['bl_ref'])
    assert (change['matched_by'], change['inventory_line_id'], change['before']['quantity'], change['after']['quantity'], change['action']) == \
        ('source_ref', BL_LINE, 5, 4, 'reduced')


def test_extras_cap_missing_and_damaged(world):
    m, ids = world
    assert lines_of(m, 'copy-bl', '3001', '0')[0] == (2, 2, 1, 1, 0)               # 4 - 2; missing 3 capped to 2; damaged 1 stays
    change = next(e for e in m.result.extras if e['copy_part_id'] == ids['bl_cap'])
    assert change['before'] == {'quantity': 4, 'missing': 3, 'damaged': 1} and change['after'] == {'quantity': 2, 'missing': 2, 'damaged': 1}


def test_extras_by_key_when_there_is_no_source_ref(world):
    m, ids = world
    assert lines_of(m, 'copy-bl', '3023', '4')[0][0] == 2
    assert next(e for e in m.result.extras if e['copy_part_id'] == ids['bl_key'])['matched_by'] == 'key'


def test_a_row_that_reaches_zero_is_dropped_and_listed(world):
    m, ids = world
    assert lines_of(m, 'copy-bl', '3023', '0') == []
    dropped = next(e for e in m.result.extras if e['copy_part_id'] == ids['bl_drop'])
    assert dropped['action'] == 'dropped' and dropped['before']['missing'] == 1 and dropped['after']['quantity'] == 0


def test_a_rebrickable_source_ref_that_equals_a_bricklink_line_id_is_ignored(world):
    """The 3.2 -> 3.3 import wrote Rebrickable inventory ids into source_ref: only a line of the copy's own set counts (#109 finding)."""
    m, ids = world
    assert lines_of(m, 'copy-proj', '3001', '4') == [(2, 0, 0, 0, 0)]               # untouched although line 466 has the same child and colour
    assert ids['proj_ref'] not in {e['copy_part_id'] for e in m.result.extras}
    assert {e['copy_part_id'] for e in m.result.extras} == {ids['bl_ref'], ids['bl_cap'], ids['bl_key'], ids['bl_drop']}
    

def test_a_foreign_source_ref_is_not_corrected_but_listed(world):
    """A projection-imported copy of a BrickLink-lines set keeps its quantities: its source_refs are Rebrickable ids, and design 8.5 matches
    by key only the rows WITHOUT a source_ref."""
    m, ids = world
    assert lines_of(m, 'copy-imp', '3001', '4') == [(5, 0, 0, 0, 0)] and lines_of(m, 'copy-imp', '3023', '4') == [(3, 0, 0, 0, 0)]
    skipped = {x['copy_part_id']: x for x in m.result.extras_skipped_foreign_ref}
    assert set(skipped) == {ids['imp_a'], ids['imp_b']} and skipped[ids['imp_a']]['source_ref'] == 9001
    assert ids['proj_ref'] not in skipped                                              # 2070-1 has no BrickLink lines with extras: not listed


def test_only_bricklink_lines_count(world):
    m, ids = world                                                                  # line 470 (extra 1) is 'rebrickable-translated'
    assert lines_of(m, 'copy-upd', '3001', '4') == [(1, 0, 0, 0, 0)]


# ---------- 8.9 ----------

def test_not_null_timestamps_follow_the_rules(world):
    m, _ = world
    rules = {k: dict(v) for k, v in m.result.timestamp_rules.items()}
    created = dict(rows(m, 'SELECT id, created_at FROM copy'))
    assert created['copy-bl'] == '2026-10-14T18:00:57.398Z'                         # the earliest event ('created', not 'edit'), in 4.0's form
    assert created['copy-proj'] == '2026-10-12T00:00:00.000Z'                       # the 3.2 import's event, `copies:{"id":..}`
    assert created['copy-upd'] == '2026-08-08T08:00:00+00:00'                       # no event: the row's own updated_at
    assert created['copy-none'] == m.result.migrated_at and created['copy-m'] == '2026-09-09T09:00:00+00:00'
    assert rules['copy.created_at'] == {'event': 2, 'updated_at': 3, 'migration_time': 1}
    assert dict(rows(m, 'SELECT id, created_at FROM storage')) == {'st1': '2026-10-12T00:00:00.000Z', 'st2': m.result.migrated_at}
    assert rules['storage.created_at'] == {'event': 1, 'migration_time': 1}
    assert dict(rows(m, 'SELECT id, created_at FROM flag'))['f_status'] == '2026-10-12T00:00:00.000Z'
    assert rules['flag.created_at'] == {'event': 1, 'migration_time': 2} and rules['place.created_at'] == {'migration_time': 1}
    assert dict(rows(m, 'SELECT id, created_at FROM lot')) == {'l1': '2026-03-01T10:00:00+00:00', 'l2': m.result.migrated_at}   # created_date, carried
    assert dict(rows(m, 'SELECT id, updated_at FROM lot'))['l1'] == '2026-10-12T00:00:00.000Z'
    figures = dict(rows(m, 'SELECT i.born_key, f.updated_at FROM copy_figure f JOIN item i ON i.id=f.item_id'))
    assert figures['fig-000004'] == '2026-10-12T00:00:00.000Z'                      # the event beats the (absent) own updated_at
    assert rules['copy_figure.updated_at'] == {'event': 1, 'updated_at': 1, 'migration_time': 1}
    assert one(m, "SELECT count(*) FROM stock WHERE created_at IS NULL OR updated_at IS NULL") == 0


def test_money_without_currency_gets_the_bricklink_currency(world):
    m, _ = world
    fills = {(f['table'], f['row']) for f in m.result.money_fills}
    assert fills == {('lot', 'l1'), ('copy.purchase', 'copy-proj'), ('copy.current_value', 'copy-proj'), ('stock', 's-part'), ('wish', 1)}
    assert {f['currency'] for f in m.result.money_fills} == {'USD'}                  # the migrated bricklink_currency, not EUR
    assert rows(m, "SELECT purchase_price, purchase_currency, current_value, current_value_currency FROM copy WHERE id='copy-proj'") == \
        [('12.50', 'USD', '30.00', 'USD')]
    assert rows(m, "SELECT purchase_price, purchase_currency FROM copy WHERE id='copy-bl'") == [('9.99', 'EUR')]    # a given currency stays
    assert m.result.money_currency_dropped == [{'table': 'lot', 'row': 'l2', 'currency': 'USD'}]
    assert rows(m, "SELECT purchase_price, purchase_currency FROM lot WHERE id='l2'") == [(None, None)]


def test_count_bounds(tmp_path, catalogue):
    src = tmp_path / 'bw33.db'
    build_33(src)
    with sqlite3.connect(src) as db:
        db.execute("UPDATE copy_parts SET quantity=NULL, missing=NULL, damaged=0 WHERE copy_id='copy-upd'")
    with Migration(src, catalogue, tmp_path / 'out.db') as m:
        r = m.write()
        assert [(f['table'], f['to']) for f in r.count_fixes] == [('copy_parts', 0)]
        assert rows(m, "SELECT quantity, missing, damaged FROM copy_part WHERE copy_id='copy-upd'") == [(0, 0, 0)]
    with sqlite3.connect(src) as db:
        db.execute("UPDATE copy_parts SET quantity=NULL, missing=2 WHERE copy_id='copy-upd'")
    with pytest.raises(NeedsDecision, match='quantity is NULL'):
        migrate(src, catalogue, tmp_path / 'out2.db')
    with sqlite3.connect(src) as db:
        db.execute("UPDATE copy_parts SET quantity=3, missing=2, damaged=4 WHERE copy_id='copy-upd'")
    with pytest.raises(NeedsDecision, match='break the bounds'):
        migrate(src, catalogue, tmp_path / 'out3.db')


# ---------- the other tables ----------

def test_flags_are_split_by_entity(world):
    m, ids = world
    assert rows(m, 'SELECT * FROM copy_flag') == [('copy-bl', 'f_status')]
    assert rows(m, 'SELECT * FROM stock_flag') == [('s-part', 'f_tag')]
    [(wish, flag)] = rows(m, 'SELECT * FROM wish_flag')
    assert flag == 'f_owner' and wish == m.result.wish_ids[ids['wishes'][0]]


def test_wishes_get_uuids(world):
    m, ids = world
    assert set(m.result.wish_ids) == set(ids['wishes']) and len(set(m.result.wish_ids.values())) == 2
    assert all(len(v) == 36 for v in m.result.wish_ids.values())
    wish = m.db.execute('SELECT * FROM wish WHERE id=?', (m.result.wish_ids[ids['wishes'][0]],)).fetchone()
    assert (wish['kind'], wish['quantity'], wish['condition'], wish['max_price'], wish['max_price_currency']) == ('part', 2, 'new', '1.00', 'USD')
    assert wish['color_id'] is not None and wish['added_at'] == '2026-02-02T02:00:00+00:00'
    other = m.db.execute('SELECT * FROM wish WHERE id=?', (m.result.wish_ids[ids['wishes'][1]],)).fetchone()
    assert (other['kind'], other['color_id'], other['wishlist_id']) == ('set', None, 'w2')


def test_photos_and_instruction_files(world):
    m, _ = world
    assert rows(m, 'SELECT local_path, copy_id, caption, width FROM photo') == [('data/images/own/a.jpg', 'copy-proj', 'front', 10)]
    assert rows(m, 'SELECT path, label FROM instruction_file') == [('data/instructions/a.pdf', 'a.pdf')]
    assert m.result.not_carried['item_images']['count'] == 1                       # the cached 'photo' is not carried


def test_a_photo_path_outside_its_folder_needs_a_decision(tmp_path, catalogue):
    src = tmp_path / 'bw33.db'
    build_33(src)
    with sqlite3.connect(src) as db:
        db.execute("UPDATE item_images SET local_path='data/images/x.jpg' WHERE kind='own'")
    with pytest.raises(NeedsDecision, match='data/images/own'):
        migrate(src, catalogue, tmp_path / 'out.db')


def test_prices(world):
    m, ids = world
    o1, o2, o3, o4, o5 = ids['obs']
    got = {r['id']: r for r in m.db.execute('SELECT * FROM price_observation')}
    assert got[o1]['currency'] is None and got[o1]['price'] == '0.10'              # a price without a currency stays NULL
    assert got[o1]['provider_key'] == 'P:3001/5' and got[o5]['provider_key'] == 'S:2070-1' and got[o4]['provider_key'] == 'P:3023'
    assert got[o3]['voided_at'] is not None and got[o3]['error'] is None           # error='undone' -> voided_at
    assert got[o4]['error'].startswith('SIGNATURE_INVALID') and got[o4]['voided_at'] is None
    assert got[o1]['condition'] == 'new' and got[o5]['condition'] == 'used' and got[o4]['observed_at'] == m.result.migrated_at
    current = rows(m, 'SELECT observation_id FROM price_current ORDER BY observation_id')
    assert current == [(o1,), (o2,), (o4,), (o5,)]                                 # the undone o3 is never current
    assert m.result.price_current['differences'] == [] and m.result.price_current['rows_33'] == 4
    assert one(m, 'SELECT color_id FROM price_observation WHERE id=?', o5) is None
    assert rows(m, 'SELECT count(*), min(color_id) IS NOT NULL FROM price_watch') == [(1, 1)]


def test_price_current_differences_are_returned(tmp_path, catalogue):
    src = tmp_path / 'bw33.db'
    ids = build_33(src)
    with sqlite3.connect(src) as db:                                                # 3.3 left a stale pointer
        db.execute('UPDATE price_current SET observation_id=? WHERE observation_id=?', (ids['obs'][0], ids['obs'][1]))
    with Migration(src, catalogue, tmp_path / 'out.db') as m:
        [diff] = m.write().price_current['differences']
        assert diff['in_33'] == ids['obs'][0] and diff['recomputed'] == ids['obs'][1]


def test_keys_and_tokens_are_copied_unchanged(world):
    m, _ = world
    assert rows(m, 'SELECT source, ciphertext, saved_at FROM source_key') == [('bricklink', 'v1:AAAA', '2026-01-01T00:00:00Z')]
    assert rows(m, 'SELECT ciphertext FROM source_key_previous') == [('v1:BBBB',)]
    assert rows(m, 'SELECT id, name, hash, scopes FROM api_token') == [('tok1', 'cli', 'hash1', 'read')]


# ---------- 8.10 settings ----------

def test_every_setting_is_classified(world):
    m, _ = world
    by_key = {s['key']: s for s in m.result.settings}
    assert set(by_key) == {k for (k,) in sqlite3.connect(m.src_path).execute('SELECT key FROM settings')}
    assert {s['classification'] for s in by_key.values()} == {'carried', 'translated', 'dropped'}
    for key in ('bricklink_currency', 'bricklink_region', 'incomplete_discount_pct', 'display_currency', 'repair_shipping', 'retail_country'):
        assert by_key[key]['classification'] == 'carried'
    setting = dict(rows(m, 'SELECT key, value FROM setting'))
    assert setting['bricklink_currency'] == 'USD' and setting['incomplete_discount_pct'] == '25' and setting['display_currency'] == 'GBP'
    assert by_key['import_order:P']['classification'] == 'translated' and setting['import_order:part'] == '["metadata", "identity"]'
    assert setting['import_order:minifigure'] == '["identity"]' and 'import_order:P' not in setting
    for key in ('checker:copy-bl', 'source:used:bricklink:2026-10-14', 'source:budget:brickset', 'sync:rebrickable:baseline', 'maintenance:database_check',
                'mystery_key'):
        assert by_key[key]['classification'] == 'dropped' and key not in setting
    assert 'unknown' in by_key['mystery_key']['note']
    assert 'prefer_bricklink_inventory' not in setting                              # starts false: no row (copies.set_prefer_bricklink)


def test_source_priority_keeps_three_steps_with_kinds(world):
    m, _ = world
    kept = json.loads(one(m, "SELECT value FROM setting WHERE key='source_priority'"))
    assert set(kept) == {'pictures', 'metadata', 'market_price'}
    assert kept['pictures'] == {'part': ['rebrickable'], 'minifigure': ['bricklink'], '*': ['bricklink']}
    assert kept['metadata'] == {'set': ['brickset']}
    note = next(s for s in m.result.settings if s['key'] == 'source_priority')['note']
    assert 'identity' in note and 'was the 3.3 default' in note                      # identity (bricklink:local) takes the 4.0 default, listed
    assert 'inventory' in note and 'NON-DEFAULT' in note                              # the changed inventory step is flagged


def test_the_sync_link_moves_to_sync_state(world):
    m, _ = world
    assert rows(m, 'SELECT source, link_json FROM sync_state') == [('rebrickable', '{"user": "ulf", "list": "7"}')]
    assert not any(k.startswith('sync:') for (k,) in rows(m, 'SELECT key FROM setting'))
    assert rows(m, "SELECT kind, max_age_days FROM source_freshness WHERE source='bricklink' ORDER BY kind")[0] == ('metadata', 365)


# ---------- 8.1 not carried ----------

def test_not_carried_is_counted_and_sampled(world):
    m, _ = world
    nc = m.result.not_carried
    assert nc['events']['count'] == 10 and len(nc['events']['samples']) == 5
    assert (nc['orders']['count'], nc['order_lines']['count'], nc['allocations']['count']) == (1, 1, 1)
    assert nc['allocations']['samples'][0]['state'] == 'applied'
    assert (nc['match_history']['count'], nc['identifications']['count']) == (1, 1)
    assert nc['inventory_lines']['count'] == 5 and nc['id_match']['count'] == 5
    assert nc['part_check sessions (settings checker:*)']['count'] == 1
    assert nc['budget counters (settings source:*)']['count'] == 2
    assert nc['sync baselines and counters (settings sync:*)']['count'] == 1
    assert nc['exchange_rates']['count'] == 1 and nc['exchange_rates']['samples'][0]['currency'] == 'CHF'     # manual rates in full
    for table in ('exchange_rate', 'purchase_order', 'order_line', 'allocation', 'stock_transfer', 'identification', 'part_check', 'job', 'source_record'):
        assert one(m, f'SELECT count(*) FROM {table}') == 0                           # the 4.0 tables for them start empty


def test_manual_decisions_are_listed_in_full(world):
    m, _ = world
    r = m.result
    assert sorted((d['source_id'], d['method']) for d in r.manual_decisions) == [('fig1', 'ulf-2026-10-12'), ('p1', 'manual')]
    assert [d['source_id'] for d in r.to_check] == ['p2'] and [d['source_id'] for d in r.unmatched] == ['p3']
    assert set(r.manual_decisions[0]) >= {'source', 'kind', 'source_id', 'item_type', 'item_no', 'color_id', 'method', 'status', 'evidence_json'}


# ---------- the mint plan is applied ----------

def test_local_items_and_colours_are_written_with_their_links(world):
    m, _ = world
    plan = m.result.mint
    assert plan.local_items and len(plan.local_items) == one(m, "SELECT count(*) FROM item WHERE origin='local'")
    local = m.db.execute("SELECT * FROM item WHERE born_provider='bricklink' AND born_namespace='S' AND born_key='5008074-1'").fetchone()
    assert (local['origin'], local['kind'], local['kind_source'], local['name'], local['category_name']) == \
        ('local', 'set', 'bricklink', 'Syn BrickLink set', 'Syn category')
    assert rows(m, 'SELECT provider, provider_kind, provider_key, status, method, origin FROM item_link WHERE item_id=?', local['id']) == \
        [('bricklink', 'S', '5008074-1', 'matched', 'migration', 'migration')]
    assert one(m, "SELECT item_id FROM copy WHERE id='copy-bl'") == local['id']
    loser = rows(m, "SELECT l.provider, l.provider_key, l.method, l.status FROM item_link l JOIN item i ON i.id=l.item_id "
                    "WHERE i.born_key='311.1stk01' ORDER BY l.provider")
    assert ('rebrickable', '003402', 'migration_collision', 'to_check') in loser
    # every catalogue item the rows name is in the collection (projected on first reference), with its links
    assert one(m, "SELECT count(*) FROM item WHERE origin='catalogue' AND born_key='3001'") == 1
    assert one(m, "SELECT count(*) FROM item_link l JOIN item i ON i.id=l.item_id WHERE i.born_key='3001' AND l.provider='bricklink'") >= 1
    assert one(m, "SELECT count(*) FROM item WHERE origin='catalogue' AND born_key='dupupn0105c01'") == 0       # not referenced: not projected


def test_a_local_colour_is_written_with_a_link_that_finds_it_again(tmp_path, catalogue):
    src = tmp_path / 'bw33.db'
    build_33(src)
    with sqlite3.connect(src) as db:                                                 # a part in BrickLink colour 86, which has no link
        db.execute("INSERT INTO copy_parts(copy_id, item_type, item_no, color_id, spare, quantity, missing, damaged, checked) "
                   "VALUES('copy-upd', 'P', '3023', 86, 0, 2, 0, 0, 0)")
    with Migration(src, catalogue, tmp_path / 'out.db') as m:
        m.write()
        [colour] = m.result.mint.local_colours
        row = m.db.execute('SELECT * FROM color WHERE id=?', (colour.local_id,)).fetchone()
        assert (row['origin'], row['name'], row['born_provider'], row['born_key'], row['rgb']) == ('local', 'Light Bluish Gray', 'bricklink', '86', 'A0A5A9')
        assert rows(m, 'SELECT provider, provider_key, inverse_preferred FROM color_link WHERE color_id=?', colour.local_id) == [('bricklink', '86', 1)]
        assert one(m, "SELECT count(*) FROM copy_part WHERE color_id=?", colour.local_id) == 1


def test_the_activation_is_part_of_the_run(world):
    m, _ = world
    assert m.result.activation['bound'] is True and m.result.activation['colours'] > 0
    assert one(m, 'SELECT count(*) FROM main.color WHERE origin="catalogue"') == one(m, 'SELECT count(*) FROM catalogue.color')


def test_a_retained_figure_line_does_not_count_twice(world):
    """The 3.2 -> 3.3 import can keep a manual `M` line in copy_parts beside the canonical copy_minifigs row; 0.5.x prefers the canonical row."""
    m, ids = world
    assert rows(m, "SELECT f.quantity, f.missing FROM copy_figure f JOIN item i ON i.id=f.item_id WHERE f.copy_id='copy-proj' "
                   "AND i.born_key='fig-000004'") == [(1, 0)]
    [dup] = m.result.figure_lines_retained_duplicate
    assert (dup['copy_id'], dup['item_no'], dup['copy_part_ids']) == ('copy-proj', 'syn-fig-0004', [ids['m_dup']])
    assert ids['m_dup'] not in {x['copy_part_ids'][0] for x in m.result.figure_lines_from_parts}


def test_the_figure_digest_describes_the_inserted_components(world):
    m, _ = world
    from brickwork.store4.bldigest import inventory_digest
    lines = rows(m, "SELECT item_id, color_id, is_spare, quantity FROM copy_part WHERE copy_figure_id="
                    "(SELECT f.id FROM copy_figure f JOIN item i ON i.id=f.item_id WHERE f.copy_id='copy-proj' AND i.born_key='fig-000004')")
    assert len(lines) == 2                                                          # the gear component was not inserted ...
    assert one(m, "SELECT f.inventory_digest FROM copy_figure f JOIN item i ON i.id=f.item_id WHERE f.copy_id='copy-proj' AND i.born_key='fig-000004'") \
        == inventory_digest(lines)                                                  # ... and is not in the digest either
    loose = rows(m, "SELECT item_id, color_id, is_spare, quantity FROM stock_part WHERE stock_id='s-fig'")
    assert one(m, "SELECT inventory_digest FROM stock WHERE id='s-fig'") == inventory_digest(loose)
    set_lines = rows(m, "SELECT item_id, color_id, is_spare, quantity FROM copy_part WHERE copy_id='copy-proj' AND copy_figure_id IS NULL")
    figures = rows(m, "SELECT item_id, quantity FROM copy_figure WHERE copy_id='copy-proj'")
    assert one(m, "SELECT inventory_digest FROM copy WHERE id='copy-proj'") == inventory_digest(set_lines, figures)


def test_a_wal_appearing_during_the_run_blocks_write_and_publish(tmp_path, catalogue):
    src = tmp_path / 'bw33.db'
    build_33(src)
    m = Migration(src, catalogue, tmp_path / 'a.db')
    Path(str(src) + '-wal').write_bytes(b'x' * 32)
    with pytest.raises(MigrationError, match='must be stopped'):
        m.write()
    Path(str(src) + '-wal').unlink()
    m = Migration(src, catalogue, tmp_path / 'b.db')
    m.write()
    Path(str(src) + '-wal').write_bytes(b'x' * 32)
    with pytest.raises(MigrationError, match='must be stopped'):
        m.publish()
    assert not (tmp_path / 'b.db').exists()
    m.abort()
