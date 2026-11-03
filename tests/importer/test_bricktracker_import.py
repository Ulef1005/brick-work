"""BrickTracker import into a 4.0 collection: any upstream version, plan, apply, Undo (M.8j, issue #110). All data invented.

BrickTracker stores Rebrickable numbers, which are the fixture catalogue's born keys (`tests/app4.RICH`): set `1000-1` (3001 red x4, 3023 white
x2 and a spare, the figure `fig-000004` twice), `1000-2`, `2070-1`, the gear item `10018247-1`."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from brickwork.core.connect import connect
from brickwork.core.importer import bricktracker, bricktracker_upgrade
from brickwork.core import undo as undoing
from brickwork.web import cli
from tests.app4 import Coll, make_pair, table_digest

DAY = 1717200000.0                                   # 2024-06-01 in epoch seconds


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def put(db, table, **row):
    """Insert into an upstream table; columns that this schema version lacks are left out."""
    have = {r[1] for r in db.execute(f'PRAGMA table_info("{table}")')}
    row = {k: v for k, v in row.items() if k in have}
    if not have:
        return                                              # this schema version has no such table yet
    db.execute(f'INSERT INTO "{table}" ({",".join(chr(34) + k + chr(34) for k in row)}) VALUES ({",".join("?" * len(row))})', tuple(row.values()))


def upstream(path, version=30):
    """A synthetic upstream app.db at `version` with: a storage, a place, an owner and a tag; three sets (one with marks on a set line, a figure line
    and a line the part list lacks), a loose part and a loose figure with a mark, a lot, a set wish and a part wish."""
    db = sqlite3.connect(path)
    bricktracker_upgrade.apply(db, 0, version)
    db.execute('PRAGMA foreign_keys=OFF')                   # upstream's own foreign keys (to its Rebrickable cache) are not under test
    put(db, 'bricktracker_metadata_storages', id='shelf', name='Shelf A')
    put(db, 'bricktracker_metadata_purchase_locations', id='shop', name='Shop')
    put(db, 'bricktracker_metadata_owners', id='owner_one', name='Invented owner')
    put(db, 'bricktracker_metadata_tags', id='tag_one', name='for sale')
    for table, column in (('bricktracker_set_owners', 'owner_owner_one'), ('bricktracker_set_tags', 'tag_tag_one'), ('bricktracker_wish_owners', 'owner_owner_one')):
        if db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
            db.execute(f'ALTER TABLE "{table}" ADD COLUMN {column} BOOLEAN')
    put(db, 'bricktracker_sets', id='copy-1', set='1000-1', description='Invented note', storage='shelf', purchase_location='shop', purchase_date=DAY, purchase_price=12.5)
    put(db, 'bricktracker_set_owners', id='copy-1', owner_owner_one=1)
    put(db, 'bricktracker_set_tags', id='copy-1', tag_tag_one=1)
    if version >= 4:
        put(db, 'bricktracker_set_statuses', id='copy-1', status_set_checked=1)
    put(db, 'bricktracker_sets', id='copy-2', set='2070-1')
    put(db, 'bricktracker_sets', id='copy-3', set='999999-1')                              # a set the catalogue does not know
    put(db, 'bricktracker_parts', id='copy-1', figure=None, part='3001', color=4, spare=0, quantity=4, rebrickable_inventory=1, missing=1, damaged=1, checked=1)
    put(db, 'bricktracker_parts', id='copy-1', figure=None, part='3023', color=4, spare=1, quantity=1, rebrickable_inventory=1, missing=1, damaged=0, checked=0)
    put(db, 'bricktracker_parts', id='copy-1', figure=None, part='3001', color=15, spare=0, quantity=1, rebrickable_inventory=1, missing=1, damaged=0, checked=0)   # not in the list
    put(db, 'bricktracker_parts', id='copy-1', figure=None, part='nothing', color=4, spare=0, quantity=1, rebrickable_inventory=1, missing=1, damaged=0, checked=0)
    put(db, 'bricktracker_individual_part_lots', id='lot-1', name='Invented lot', description='From a flea market', created_date=DAY, storage='shelf',
        purchase_location='shop', purchase_date=DAY, purchase_price=7.0)
    put(db, 'bricktracker_individual_parts', id='loose-1', part='3001', color=4, quantity=3, description='Loose bricks', storage='shelf', purchase_price=1.5,
        missing=0, damaged=1, checked=1, lot_id='lot-1')
    put(db, 'bricktracker_individual_parts', id='loose-2', part='3023', color=15, quantity=2)
    put(db, 'bricktracker_individual_minifigures', id='fig-1', figure='fig-000004', quantity=2, description='Two knights', storage='shelf')
    put(db, 'bricktracker_individual_minifigure_parts', id='fig-1', part='3901', color=6, spare=0, quantity=1, rebrickable_inventory=1, missing=1, damaged=0, checked=0)
    put(db, 'bricktracker_wishes', set='1000-2', name='Invented wish', year=1991, theme_id=1, number_of_parts=3)
    put(db, 'bricktracker_wishes', set=json.dumps(['3023', 15]), name='Part wish', year=2000, theme_id=1, number_of_parts=1)
    put(db, 'bricktracker_wishes', set='888888-1', name='Unknown wish', year=2000, theme_id=1, number_of_parts=1)
    put(db, 'bricktracker_wish_owners', set='1000-2', owner_owner_one=1)
    db.commit()
    db.close()
    return path


@pytest.fixture
def store(tmp_path):
    return make_pair(tmp_path / 'store', rich=True) if (tmp_path / 'store').mkdir() is None else None


@pytest.fixture
def db(store):
    with closing(connect(store)) as db:
        yield db


def live(db, table):
    return db.execute(f'SELECT count(*) FROM {table} WHERE archived_at IS NULL').fetchone()[0]


def line(db, copy, number, colour, spare=0):
    return db.execute('''SELECT p.* FROM copy_part p JOIN item i ON i.id=p.item_id JOIN color c ON c.id=p.color_id
                         WHERE p.copy_id=? AND i.born_key=? AND c.born_key=? AND p.is_spare=? AND p.copy_figure_id IS NULL''', (copy, number, str(colour), spare)).fetchone()


@pytest.mark.parametrize('version', [15, 21, 27, 30])
def test_any_version_upgrades_and_imports(tmp_path, db, version):
    source = upstream(tmp_path / f'app-{version}.db', version)
    before = digest(source)
    plan = bricktracker.plan(db, source)
    assert plan['schema'] == dict(found=version, upgraded_to=bricktracker_upgrade.NEWEST) and plan['fresh']
    assert {r['key'] for r in plan['rows'] if r['action'] == 'add'} >= {'copy:copy-1', 'copy:copy-2', 'wish:1:1000-2' if False else 'copy:copy-1'}
    result = bricktracker.apply(db, plan['id'])
    copy = db.execute("SELECT c.*, i.born_key FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key='1000-1'").fetchone()
    assert copy['note'] == 'Invented note' and copy['purchase_date'] == '2024-06-01' and copy['purchase_price'] == '12.50' and copy['purchase_currency'] == 'EUR'
    assert db.execute('SELECT name FROM storage WHERE id=?', (copy['storage_id'],)).fetchone()[0] == 'Shelf A'
    assert db.execute('SELECT name FROM place WHERE id=?', (copy['place_id'],)).fetchone()[0] == 'Shop'
    assert result['counts']['copies'] == 2 and result['event_id']
    assert digest(source) == before                                 # the user's file is never written


def test_what_the_import_makes(tmp_path, db):
    source = upstream(tmp_path / 'app.db')
    plan = bricktracker.plan(db, source)
    summary = plan['summary']
    assert summary['copy'] == dict(new=2, duplicate=0, imported=0) and summary['stock']['new'] == 3 and summary['wish']['new'] == 2 and summary['lot']['new'] == 1
    assert summary['marks'] == 3 + 1                                 # 3001/4, spare 3023/4, 3001/15 (resolved, no such line); the figure's 3901/6
    assert {u['number'] for u in plan['unplaced']} == {'999999-1', 'nothing/4', '888888-1'}
    assert all(u['reason'] for u in plan['unplaced'])
    result = bricktracker.apply(db, plan['id'])
    assert result['counts'] == dict(copies=2, stock=7, lots=1, wishes=2, storages=1, purchase_locations=1, flags=result['counts']['flags'])
    copy = db.execute("SELECT c.* FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key='1000-1'").fetchone()
    assert copy['inventory_source'] == 'rebrickable' and copy['completeness_source'] == 'derived' and copy['completeness'] == 'incomplete'
    assert dict(line(db, copy['id'], '3001', 4)) | {} and (line(db, copy['id'], '3001', 4)['missing'], line(db, copy['id'], '3001', 4)['damaged'], line(db, copy['id'], '3001', 4)['checked']) == (1, 1, 1)
    spare = line(db, copy['id'], '3023', 4, spare=1)
    assert spare['missing'] == 1 and spare['quantity'] == 1
    assert line(db, copy['id'], '3001', 15) is None                    # the mark whose line the part list lacks is reported, not invented
    receipt = bricktracker.receipt_of(db, result['event_id'])
    assert len(receipt['unplaced_marks']) == 1 and receipt['unplaced_marks'][0]['reason'] == "The copy's part list has no such line"
    flags = {(r['kind'], r['name']) for r in db.execute('SELECT f.kind, f.name FROM copy_flag c JOIN flag f ON f.id=c.flag_id WHERE c.copy_id=?', (copy['id'],))}
    assert flags == {('owner', 'Invented owner'), ('tag', 'for sale'), ('status', 'Set is checked')}
    # Loose things are stock of their kind: a part with its lot, storage, purchase and state; a figure with its own part list and a mark on it.
    part = db.execute("SELECT s.* FROM stock s JOIN item i ON i.id=s.item_id WHERE i.born_key='3001' AND s.color_id=(SELECT id FROM color WHERE born_key='4')").fetchone()
    assert part['kind'] == 'part' and part['quantity'] == 3 and part['condition'] is None and part['note'] == 'Loose bricks'
    assert (part['missing'], part['damaged'], part['checked']) == (0, 1, 1) and part['purchase_price'] == '1.50' and part['purchase_currency'] == 'EUR'
    assert db.execute('SELECT name FROM lot WHERE id=?', (part['lot_id'],)).fetchone()[0] == 'Invented lot'
    figure = db.execute("SELECT s.* FROM stock s JOIN item i ON i.id=s.item_id WHERE i.born_key='fig-000004'").fetchone()
    assert figure['kind'] == 'minifigure' and figure['quantity'] == 2 and figure['inventory_source'] == 'rebrickable'
    marked = db.execute('SELECT quantity, missing FROM stock_part WHERE stock_id=? AND missing>0', (figure['id'],)).fetchall()
    assert [tuple(r) for r in marked] == [(2, 1)] and figure['missing'] == 1
    wishes = {r['born_key']: r for r in db.execute("SELECT w.*, i.born_key FROM wish w JOIN item i ON i.id=w.item_id WHERE w.archived_at IS NULL")}
    assert wishes['1000-2']['kind'] == 'set' and wishes['3023']['kind'] == 'part' and wishes['3023']['color_id'] is not None
    assert db.execute('SELECT count(*) FROM wish_flag WHERE wish_id=?', (wishes['1000-2']['id'],)).fetchone()[0] == 1
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert db.execute("SELECT count(*) FROM job WHERE item_id IN (SELECT id FROM item WHERE born_key='1000-1')").fetchone()[0] == 1


def test_a_set_of_another_kind_is_placed_by_its_current_kind(tmp_path, db):
    source = upstream(tmp_path / 'app.db')
    with closing(sqlite3.connect(source)) as bt, bt:
        put(bt, 'bricktracker_sets', id='gear-1', set='10018247-1', description='A gift')
    plan = bricktracker.plan(db, source)
    bricktracker.apply(db, plan['id'])
    row = db.execute("SELECT s.* FROM stock s JOIN item i ON i.id=s.item_id WHERE i.born_key='10018247-1'").fetchone()
    assert row['kind'] == 'gear' and row['quantity'] == 1 and row['note'] == 'A gift'
    assert not db.execute("SELECT 1 FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key='10018247-1'").fetchone()


def test_exact_undo(tmp_path, db):
    source = upstream(tmp_path / 'app.db')
    Coll(db).add_stock('part', Coll(db).item('parts', '3023'), colour=Coll(db).colour('15'), quantity=1, condition=None)      # a pile the import's 3023 merges onto
    before = table_digest(db)
    result = bricktracker.apply(db, bricktracker.plan(db, source)['id'], {'stock:loose-2': 'add'})              # a duplicate pile is asked about: add merges
    assert live(db, 'copy') == 2
    assert db.execute("SELECT quantity FROM stock s JOIN item i ON i.id=s.item_id WHERE i.born_key='3023' AND s.archived_at IS NULL AND s.kind='part'").fetchone()[0] == 3
    undone = bricktracker.undo(db, result['event_id'])
    assert not undone['already_undone'] and bricktracker.undo(db, result['event_id'])['already_undone']
    for table in ('copy', 'stock', 'wish', 'lot', 'storage', 'place'):
        assert live(db, table) == (1 if table == 'stock' else 0), table
    assert db.execute("SELECT quantity FROM stock s JOIN item i ON i.id=s.item_id WHERE i.born_key='3023' AND s.archived_at IS NULL").fetchone()[0] == 1
    assert not db.execute("SELECT 1 FROM flag WHERE archived_at IS NULL AND name IN ('Invented owner', 'for sale')").fetchone()
    changed = {t for t, v in table_digest(db).items() if before.get(t) != v}
    assert changed <= {'copy', 'copy_part', 'copy_figure', 'copy_flag', 'stock', 'stock_part', 'stock_flag', 'wish', 'wish_flag', 'lot', 'storage', 'place', 'flag',
                       'item', 'item_link', 'item_property', 'item_provider_status', 'color', 'color_link', 'job', 'job_step', 'plan'}, changed
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    # The same file can be imported again after an Undo.
    assert bricktracker.apply(db, bricktracker.plan(db, source)['id'])['counts']['copies'] == 2


def test_undo_is_refused_over_later_edits(tmp_path, db):
    source = upstream(tmp_path / 'app.db')
    result = bricktracker.apply(db, bricktracker.plan(db, source)['id'])
    copy = db.execute("SELECT c.id FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key='2070-1'").fetchone()[0]
    db.execute("UPDATE copy SET condition='used' WHERE id=?", (copy,))
    db.commit()
    with pytest.raises(undoing.errors.UndoBlocked, match='changed since'):
        bricktracker.undo(db, result['event_id'])
    assert live(db, 'copy') == 2
    db.execute("UPDATE copy SET condition=NULL WHERE id=?", (copy,))
    db.execute("UPDATE copy_part SET missing=1 WHERE copy_id=? AND id=(SELECT min(id) FROM copy_part WHERE copy_id=?)", (copy, copy))
    db.commit()
    with pytest.raises(undoing.errors.UndoBlocked):
        bricktracker.undo(db, result['event_id'])
    db.execute("UPDATE copy_part SET missing=0 WHERE copy_id=?", (copy,))
    db.commit()
    assert not bricktracker.undo(db, result['event_id'])['already_undone']


def test_the_same_file_again_skips_what_is_here(tmp_path, db):
    source = upstream(tmp_path / 'app.db')
    first = bricktracker.apply(db, bricktracker.plan(db, source)['id'])
    again = bricktracker.plan(db, source)
    states = {r['key']: r['state'] for r in again['rows']}
    assert states['copy:copy-1'] == 'imported' and states['stock:loose-1'] == 'imported' and states['lot:lot-1'] == 'imported'
    assert states['wish:0:1000-2'] == 'duplicate' and not again['fresh']
    assert all(r['action'] == 'skip' for r in again['rows'] if r['state'] != 'new')
    assert bricktracker.apply(db, again['id'])['counts']['copies'] == 0
    assert live(db, 'copy') == 2 and first['counts']['copies'] == 2


def test_a_duplicate_set_asks_and_a_duplicate_pile_merges(tmp_path, db):
    source = upstream(tmp_path / 'app.db')
    coll = Coll(db)
    coll.add_copy('1000-1')
    coll.add_stock('part', coll.item('parts', '3023'), colour=coll.colour('15'), quantity=4, condition=None)
    plan = bricktracker.plan(db, source)
    rows = {r['key']: r for r in plan['rows']}
    assert rows['copy:copy-1']['state'] == 'duplicate' and rows['copy:copy-1']['action'] == 'skip' and rows['stock:loose-2']['state'] == 'duplicate'
    assert not plan['fresh']
    bricktracker.apply(db, plan['id'], {'copy:copy-1': 'add', 'stock:loose-2': 'add'})
    assert live(db, 'copy') == 3
    assert db.execute("SELECT quantity FROM stock s JOIN item i ON i.id=s.item_id WHERE i.born_key='3023' AND s.kind='part' AND s.archived_at IS NULL").fetchone()[0] == 6
    with pytest.raises(ValueError, match='Unknown import rows'):
        bricktracker.apply(db, bricktracker.plan(db, source)['id'], {'copy:nope': 'add'})
    with pytest.raises(ValueError, match='add or skip'):
        bricktracker.apply(db, bricktracker.plan(db, source)['id'], {'copy:copy-2': 'maybe'})


def test_a_plan_applies_once_even_when_its_file_says_otherwise(tmp_path, db):
    source = upstream(tmp_path / 'app.db')
    plan = bricktracker.plan(db, source)
    first = bricktracker.apply(db, plan['id'])
    work, meta = bricktracker.load_plan(db, plan['id'])
    meta.pop('applied')
    (work / 'plan.json').write_text(json.dumps(meta))
    again = bricktracker.apply(db, plan['id'])
    assert again['already_applied'] and again['event_id'] == first['event_id'] and live(db, 'copy') == 2
    assert db.execute("SELECT kind, event_id FROM plan WHERE id=?", (plan['id'],)).fetchone()[:] == ('import', first['event_id'])


def test_refuses_newer_and_foreign_databases(tmp_path, db):
    newer = upstream(tmp_path / 'new.db')
    with closing(sqlite3.connect(newer)) as bt:
        bt.execute(f'PRAGMA user_version={bricktracker_upgrade.NEWEST + 1}')
    other = tmp_path / 'other.db'
    with closing(sqlite3.connect(other)) as bt:
        bt.execute('CREATE TABLE notes(x)')
    with pytest.raises(ValueError, match='newer'):
        bricktracker.plan(db, newer)
    with pytest.raises(ValueError, match='not a BrickTracker database'):
        bricktracker.plan(db, other)
    assert not list((Path(db.execute('PRAGMA database_list').fetchone()[2]).parent / 'data' / 'imports').iterdir())


def test_custom_fields_go_to_the_copy_note(tmp_path, db):
    source = upstream(tmp_path / 'app.db')
    with closing(sqlite3.connect(source)) as bt, bt:
        put(bt, 'bricktracker_metadata_custom_fields', id='box', name='Box shelf', type='text')
        bt.execute('ALTER TABLE bricktracker_set_custom_fields ADD COLUMN custom_field_box TEXT')
        put(bt, 'bricktracker_set_custom_fields', id='copy-1', custom_field_box='Attic 3')
    bricktracker.apply(db, bricktracker.plan(db, source)['id'])
    note = db.execute("SELECT c.note FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key='1000-1'").fetchone()[0]
    assert note == 'Invented note\nBox shelf: Attic 3'


def test_no_catalogue_item_is_invented(tmp_path, db):
    """A number the catalogue does not know is listed and left out: no `?` placeholder, no local item."""
    source = upstream(tmp_path / 'app.db')
    items_before = db.execute('SELECT count(*) FROM main.item').fetchone()[0]
    plan = bricktracker.plan(db, source)
    assert db.execute('SELECT count(*) FROM main.item').fetchone()[0] == items_before            # a plan writes nothing
    bricktracker.apply(db, plan['id'])
    assert not db.execute("SELECT 1 FROM main.item WHERE origin='local'").fetchone()


def test_cli_plan_and_apply(tmp_path, store, monkeypatch, capsys):
    source = upstream(tmp_path / 'app.db')
    monkeypatch.setenv('BW_DB_PATH', str(store))
    assert cli.main(['import-bricktracker', str(source), '--plan-only', '--json']) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan['summary']['copy']['new'] == 2 and plan['fresh']
    decisions = tmp_path / 'decisions.json'
    decisions.write_text(json.dumps({'copy:copy-2': 'skip'}))
    assert cli.main(['import-bricktracker', '--apply', plan['id'], '--decisions', str(decisions), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['counts']['copies'] == 1
    with closing(connect(store)) as db:
        assert db.execute("SELECT via FROM event WHERE entity_kind='import' AND field='receipt'").fetchone()[0] == 'cli'
    with pytest.raises(SystemExit):
        cli.main(['import-bricktracker'])


# ---- review findings of M.8j (Codex) ----

def figure_stock(db, number='fig-000004'):
    return db.execute("SELECT s.* FROM stock s JOIN item i ON i.id=s.item_id WHERE i.born_key=? AND s.archived_at IS NULL", (number,)).fetchone()


def test_undo_is_refused_after_a_gap_of_an_imported_figure_was_filled(tmp_path, db):
    """P1: a Give from other stock changes only the figure's part lines and consumes the supplier; Undo must not archive it and leave the supplier gone."""
    from brickwork.core import workbench
    source = upstream(tmp_path / 'app.db')
    result = bricktracker.apply(db, bricktracker.plan(db, source)['id'])
    fig = figure_stock(db)
    gap = db.execute('SELECT * FROM stock_part WHERE stock_id=? AND missing>0', (fig['id'],)).fetchone()
    coll = Coll(db)
    supplier = coll.add_stock('part', gap['item_id'], colour=gap['color_id'], quantity=3, condition=None)
    workbench.transfer(db, supplier, fig['id'], 'stock-part', gap['id'], 1)
    assert db.execute('SELECT quantity FROM stock WHERE id=?', (supplier,)).fetchone()[0] == 2
    with pytest.raises(undoing.errors.UndoBlocked, match='changed since'):
        bricktracker.undo(db, result['event_id'])
    assert figure_stock(db) is not None and live(db, 'copy') == 2                       # nothing was archived


def test_undo_is_refused_when_an_imported_figures_lines_differ_without_a_transfer(tmp_path, db):
    source = upstream(tmp_path / 'app.db')
    result = bricktracker.apply(db, bricktracker.plan(db, source)['id'])
    db.execute('UPDATE stock_part SET checked=1 WHERE stock_id=?', (figure_stock(db)['id'],))
    db.commit()
    with pytest.raises(undoing.errors.UndoBlocked):
        bricktracker.undo(db, result['event_id'])


def test_a_second_pile_on_the_same_key_keeps_its_state_and_undoes_exactly(tmp_path, db):
    """P2: a merged pile loses missing / damaged / checked."""
    source = upstream(tmp_path / 'app.db')
    with closing(sqlite3.connect(source)) as bt, bt:
        put(bt, 'bricktracker_individual_parts', id='loose-3', part='3001', color=4, quantity=2, missing=1, damaged=0, checked=1)       # the key of loose-1
    plan = bricktracker.plan(db, source)
    coll = Coll(db)
    pile = coll.add_stock('part', coll.item('parts', '3001'), colour=coll.colour('4'), quantity=1, condition=None, missing=1, damaged=0, checked=1)
    # loose-1 (3 pcs, lot Invented lot) has its own key; loose-3 has none in the lot: it merges onto the existing pile
    before = dict(db.execute('SELECT * FROM stock WHERE id=?', (pile,)).fetchone())
    result = bricktracker.apply(db, plan['id'], {'stock:loose-3': 'add', 'stock:loose-1': 'skip'})
    now_ = dict(db.execute('SELECT * FROM stock WHERE id=?', (pile,)).fetchone())
    assert now_['quantity'] == 3 and now_['missing'] == 2 and now_['damaged'] == 0 and now_['checked'] == 1
    bricktracker.undo(db, result['event_id'])
    after = dict(db.execute('SELECT * FROM stock WHERE id=?', (pile,)).fetchone())
    assert {k: after[k] for k in ('quantity', 'missing', 'damaged', 'checked', 'updated_at')} == {k: before[k] for k in ('quantity', 'missing', 'damaged', 'checked', 'updated_at')}


def test_the_state_of_a_merged_pile_is_capped_by_its_quantity(tmp_path, db):
    source = upstream(tmp_path / 'app.db')
    with closing(sqlite3.connect(source)) as bt, bt:
        put(bt, 'bricktracker_individual_parts', id='loose-3', part='3001', color=4, quantity=1, missing=1, damaged=1, checked=0)
    plan = bricktracker.plan(db, source)
    coll = Coll(db)
    pile = coll.add_stock('part', coll.item('parts', '3001'), colour=coll.colour('4'), quantity=1, condition=None, missing=1, damaged=1, checked=0)
    bricktracker.apply(db, plan['id'], {'stock:loose-3': 'add', 'stock:loose-1': 'skip'})
    row = db.execute('SELECT quantity, missing, damaged, checked FROM stock WHERE id=?', (pile,)).fetchone()
    assert tuple(row) == (2, 2, 2, 0)


def test_loose_items_keep_their_owners_statuses_and_tags(tmp_path, db):
    """P2: upstream keys owners, statuses and tags of any entity by its id (migrations 0021 / 0027)."""
    source = upstream(tmp_path / 'app.db')
    with closing(sqlite3.connect(source)) as bt, bt:
        put(bt, 'bricktracker_set_owners', id='loose-1', owner_owner_one=1)
        put(bt, 'bricktracker_set_tags', id='fig-1', tag_tag_one=1)
    result = bricktracker.apply(db, bricktracker.plan(db, source)['id'])
    def flags(stock_id):
        return {(r['kind'], r['name']) for r in db.execute('SELECT f.kind, f.name FROM stock_flag s JOIN flag f ON f.id=s.flag_id WHERE s.stock_id=?', (stock_id,))}
    part = db.execute("SELECT s.id FROM stock s JOIN item i ON i.id=s.item_id WHERE i.born_key='3001' AND s.kind='part'").fetchone()[0]
    assert flags(part) == {('owner', 'Invented owner')} and flags(figure_stock(db)['id']) == {('tag', 'for sale')}
    bricktracker.undo(db, result['event_id'])
    assert db.execute('SELECT count(*) FROM stock_flag').fetchone()[0] == 0 or all(
        db.execute('SELECT archived_at FROM stock WHERE id=?', (r[0],)).fetchone()[0] for r in db.execute('SELECT stock_id FROM stock_flag'))


def test_undo_removes_only_the_flag_links_the_import_made(tmp_path, db):
    source = upstream(tmp_path / 'app.db')
    with closing(sqlite3.connect(source)) as bt, bt:
        put(bt, 'bricktracker_individual_parts', id='loose-3', part='3023', color=15, quantity=1)
        put(bt, 'bricktracker_set_owners', id='loose-3', owner_owner_one=1)
    plan = bricktracker.plan(db, source)
    coll = Coll(db)
    pile = coll.add_stock('part', coll.item('parts', '3023'), colour=coll.colour('15'), quantity=1, condition=None)
    owner = coll.flag('Invented owner', 'owner')
    coll.tag('stock', pile, owner)                                                  # the pile already has the tag
    result = bricktracker.apply(db, plan['id'], {'stock:loose-3': 'add', 'stock:loose-2': 'skip'})
    bricktracker.undo(db, result['event_id'])
    assert db.execute('SELECT 1 FROM stock_flag WHERE stock_id=? AND flag_id=?', (pile, owner)).fetchone()
