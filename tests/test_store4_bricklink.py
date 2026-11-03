"""The BrickLink item lists (M.2d, design 3.3, 3.5, 6.2, 6.4, 6.6, decisions 3 and 8): import as a seeded rebuild, the upgrade of
inferred set links, the same_number pass, kind corrections, the carry through a re-download and reconcile's mirror. Invented
XML and dumps only; nothing of BrickLink's is in the repo."""
import fcntl
import html
import json
import sqlite3
from contextlib import closing

import pytest

from brickwork.store4 import identity
from brickwork.store4.activate import activate
from brickwork.store4.bricklink_list import import_bricklink
from brickwork.store4.builder import build
from brickwork.store4.connect import connect
from brickwork.store4.errors import BrickLinkListError, BuildBusy, CatalogueError
from brickwork.store4.reconcile import reconcile
from tests.store4_dump import SETS, write_dump, write_mappings
from tests.test_store4_reconcile import COLORS, PARTS, STAMP, ids, make, q, tables

# 3023 is linked (inferred) by parts.csv; 3001 has no link; 970c03 has none either unless the leg rule gives one
LINKS = [('3023', '', 'bricklink', 'P', '3023', 'inferred', 'external_ids', 0)]
EXTRA_SETS = SETS + [('5005-1', 'Second Gear Bag', '2014', '501', '0', '')]       # theme 501 is gear: a theme-guessed zero-part set


def xml_item(kind, number, name, **extra):
    fields = ''.join(f'<{k.upper()}>{v}</{k.upper()}>' for k, v in extra.items())
    return f'<ITEM><ITEMTYPE>{kind}</ITEMTYPE><ITEMID>{number}</ITEMID><ITEMNAME>{html.escape(name)}</ITEMNAME>{fields}</ITEM>'


# one entry of each of the eight types; BrickLink numbers gear and books without the -1 suffix: B 5001 and B 5005 disagree with the gear
# guess of 5001-1 and 5005-1, G 5002 agrees with the guess for 5002-1
ITEMS = [('S', '6081-1', 'King Leo Castle'), ('P', '3023', 'Plate 1 x 2'), ('P', '3001', 'Brick 2 x 4'), ('M', 'sw0001', 'A Trooper'),
         ('G', '5002', 'Child Keychain'), ('B', '5001', 'Not a Bag but a Book'), ('B', '5005', 'Another Book'), ('G', '7777', 'A fetched gear item'), ('C', 'cat-1', 'A Catalog'),
         ('I', 'ins-1', 'Instructions'), ('O', 'box-1', 'Original Box')]


def write_xml(directory, items=ITEMS, *, colours=None, split=True):
    """The eight-type list as catalogue XML files; one file per type, as BrickLink's download is."""
    directory.mkdir(parents=True, exist_ok=True)
    for old in directory.glob('*.xml'):
        old.unlink()
    groups = {}
    for kind, number, name in items:
        groups.setdefault(kind if split else 'All', []).append(xml_item(kind, number, name, itemweight='1.5', **({'yearreleased': '1993'} if kind == 'S' else {})))
    for kind, entries in groups.items():
        (directory / f'catalog-{kind}.xml').write_text(f"<?xml version='1.0' encoding='utf-8'?>\n<CATALOG>{''.join(entries)}</CATALOG>")
    if colours:
        rows = ''.join(f'<ITEM><COLOR>{i}</COLOR><COLORNAME>{n}</COLORNAME><COLORRGB>{rgb}</COLORRGB><COLORTYPE>Solid</COLORTYPE></ITEM>' for i, n, rgb in colours)
        (directory / 'colors.xml').write_text(f'<CATALOG>{rows}</CATALOG>')
    return directory


def catalogue(tmp_path, name='d1', **kw):
    maps = write_mappings(tmp_path / 'maps', colors=COLORS, parts=LINKS)
    dump = write_dump(tmp_path / name, **{**tables(), 'sets': EXTRA_SETS, **kw})
    target = tmp_path / 'catalogue.db'
    return build(dump, target, app_version='t', now=STAMP, mappings_dir=maps), target


def load(tmp_path, target, items=ITEMS, **kw):
    return import_bricklink(target, write_xml(tmp_path / 'bl', items, **{k: v for k, v in kw.items() if k in ('colours', 'split')}),
                            app_version='t', now=STAMP, **{k: v for k, v in kw.items() if k == 'collection'})


def links(path, key, namespace='sets'):
    return q(path, """SELECT l.provider_kind, l.provider_key, l.status, l.method, l.origin FROM item_link l JOIN item i ON i.id=l.item_id
                      WHERE i.born_namespace=? AND i.born_key=? ORDER BY l.provider_kind, l.provider_key""", namespace, key)


def kind(path, key, namespace='sets'):
    r = q(path, 'SELECT id, kind, kind_source FROM item WHERE born_namespace=? AND born_key=?', namespace, key)[0]
    return r['id'], r['kind'], r['kind_source']


def state(path):
    """Everything a list changes, in terms that survive a rebuild: links and kinds by born key."""
    return (q(path, """SELECT i.born_namespace, i.born_key, i.kind, i.kind_source, l.provider_kind, l.provider_key, l.status, l.method, l.origin, l.preferred
                       FROM item i LEFT JOIN item_link l ON l.item_id=i.id ORDER BY 1, 2, 5, 6"""),
            q(path, 'SELECT * FROM bricklink_item ORDER BY item_type, item_no'), q(path, 'SELECT * FROM bricklink_color ORDER BY id'))


# ---------- the files ----------

def test_a_partial_list_is_refused_and_nothing_is_touched(tmp_path):
    _, cat = catalogue(tmp_path)
    before = cat.read_bytes()
    with pytest.raises(BrickLinkListError, match='all eight item types'):
        load(tmp_path, cat, [i for i in ITEMS if i[0] != 'O'])
    assert cat.read_bytes() == before and sorted(p.name for p in tmp_path.glob('catalogue.db*')) == ['catalogue.db', 'catalogue.db.lock']


@pytest.mark.parametrize('bad', ['<CATALOG><ITEM><ITEMTYPE>X</ITEMTYPE><ITEMID>1</ITEMID><ITEMNAME>n</ITEMNAME></ITEM></CATALOG>',
                                 '<CATALOG><ITEM><ITEMTYPE>S</ITEMTYPE><ITEMID>1</ITEMID><ITEMNAME></ITEMNAME></ITEM></CATALOG>',
                                 '<CATALOG><ITEM><ITEMTYPE>S</ITEMTYPE><ITEMID>1</ITEMID><ITEMNAME>n</ITEMNAME><YEAR>93</YEAR></ITEM></CATALOG>',
                                 '<LIST/>', '<CATALOG><ITEM', '<CATALOG></CATALOG>'])
def test_malformed_files_are_refused(tmp_path, bad):
    _, cat = catalogue(tmp_path)
    write_xml(tmp_path / 'bl')
    (tmp_path / 'bl' / 'zz.xml').write_text(bad)
    with pytest.raises(BrickLinkListError):
        import_bricklink(cat, tmp_path / 'bl', app_version='t', now=STAMP)


def test_a_duplicate_item_and_an_empty_directory_are_refused(tmp_path):
    _, cat = catalogue(tmp_path)
    with pytest.raises(BrickLinkListError, match='more than once'):
        load(tmp_path, cat, ITEMS + [('S', '6081-1', 'again')])
    (tmp_path / 'empty').mkdir()
    with pytest.raises(BrickLinkListError, match='no BrickLink catalogue XML'):
        import_bricklink(cat, tmp_path / 'empty', app_version='t', now=STAMP)
    with pytest.raises(CatalogueError, match='does not exist'):
        import_bricklink(tmp_path / 'none.db', tmp_path / 'bl', app_version='t', now=STAMP)


def test_the_lists_are_stored_with_the_bytes_that_were_parsed_in_the_build_row(tmp_path):
    _, cat = catalogue(tmp_path)
    r = load(tmp_path, cat, colours=[(11, 'Black', '05131D'), (5, 'Red', 'C91A09')])
    items = q(cat, "SELECT * FROM bricklink_item WHERE item_type='S'")
    assert [(x['item_no'], x['name'], x['year'], x['weight'], x['name_key']) for x in items] == [('6081-1', 'King Leo Castle', 1993, '1.5', 'king leo castle')]
    assert q(cat, 'SELECT id, name, rgb, type FROM bricklink_color ORDER BY id') == [dict(id=5, name='Red', rgb='C91A09', type='Solid'),
                                                                                    dict(id=11, name='Black', rgb='05131D', type='Solid')]
    builds = q(cat, "SELECT id, kind, seeded_from, files_json, counts_json FROM build WHERE kind LIKE 'bricklink_%' ORDER BY id")
    assert [b['kind'] for b in builds] == ['bricklink_list', 'bricklink_colors'] and {b['seeded_from'] for b in builds} == {'catalogue'}
    files = json.loads(builds[0]['files_json'])
    import hashlib
    assert [f['name'] for f in files] == sorted(f'catalog-{t}.xml' for t in 'SPMGBCIO')
    for f in files:
        data = (tmp_path / 'bl' / f['name']).read_bytes()
        assert (f['bytes'], f['sha256']) == (len(data), hashlib.sha256(data).hexdigest()) and f['rows'] == data.decode().count('<ITEM>')
    assert json.loads(builds[1]['files_json'])[0]['rows'] == 2 and r['build_id'] == builds[0]['id']
    assert q(cat, 'SELECT count(*) AS n FROM bricklink_item')[0]['n'] == len(ITEMS)
    assert (tmp_path / 'catalogue.db.prev').exists() and not (tmp_path / 'catalogue.db.new').exists()


def test_a_second_load_replaces_the_list_and_keeps_colours_when_none_come(tmp_path):
    _, cat = catalogue(tmp_path)
    load(tmp_path, cat, colours=[(5, 'Red', 'C91A09')])
    load(tmp_path, cat, ITEMS + [('P', 'new-1', 'New Part')])
    assert q(cat, 'SELECT count(*) AS n FROM bricklink_item')[0]['n'] == len(ITEMS) + 1
    assert [r['name'] for r in q(cat, 'SELECT name FROM bricklink_color')] == ['Red']
    load(tmp_path, cat)
    assert q(cat, "SELECT count(*) AS n FROM bricklink_item WHERE item_no='new-1'")[0]['n'] == 0
    assert [r['kind'] for r in q(cat, 'SELECT kind FROM build ORDER BY id')].count('bricklink_list') == 3        # the history stays


# ---------- links and kinds ----------

def test_a_set_link_is_upgraded_only_where_the_bricklink_item_exists(tmp_path):
    _, cat = catalogue(tmp_path)
    assert links(cat, '6081-1') == [dict(provider_kind='S', provider_key='6081-1', status='inferred', method='set_number', origin='rule')]
    load(tmp_path, cat)
    assert links(cat, '6081-1') == [dict(provider_kind='S', provider_key='6081-1', status='matched', method='bricklink_list', origin='bricklink_list')]
    assert links(cat, '9999-1') == [dict(provider_kind='S', provider_key='9999-1', status='inferred', method='set_number', origin='rule')]
    assert q(cat, "SELECT preferred FROM item_link WHERE provider_key='6081-1'") == [dict(preferred=1)]


def test_only_inferred_set_number_links_are_upgraded(tmp_path):
    _, cat = catalogue(tmp_path)
    load(tmp_path, cat)
    assert links(cat, '3023', 'parts') == [dict(provider_kind='P', provider_key='3023', status='inferred', method='external_ids', origin='shipped')]


def test_same_number_candidates_are_to_check_and_never_matched(tmp_path):
    _, cat = catalogue(tmp_path)
    assert links(cat, '3001', 'parts') == []
    load(tmp_path, cat)
    assert links(cat, '3001', 'parts') == [dict(provider_kind='P', provider_key='3001', status='to_check', method='same_number', origin='bricklink_list')]
    assert links(cat, '5002-1') == [dict(provider_kind='G', provider_key='5002', status='to_check', method='same_number', origin='bricklink_list')]
    assert links(cat, '970c03', 'parts') == [r for r in links(cat, '970c03', 'parts') if r['method'] != 'same_number']      # not in the list: no candidate
    assert q(cat, "SELECT count(*) AS n FROM item_link WHERE method='same_number' AND (status!='to_check' OR preferred!=0)")[0]['n'] == 0
    assert q(cat, "SELECT count(*) AS n FROM item_link WHERE status='matched' AND method='same_number'")[0]['n'] == 0
    # the item that already has a link (3023, inferred) and a set that has none of the list's type get no candidate
    assert [r['method'] for r in links(cat, '3023', 'parts')] == ['external_ids'] and links(cat, '5003-1')[0]['method'] == 'set_number'


def test_a_theme_guessed_gear_set_listed_as_a_book_is_corrected_with_the_same_id(tmp_path):
    _, cat = catalogue(tmp_path)
    before = kind(cat, '5001-1')
    assert before[1:] == ('gear', 'theme')
    load(tmp_path, cat)
    assert kind(cat, '5001-1') == (before[0], 'book', 'bricklink')                         # same id, new kind
    assert kind(cat, '5005-1')[1:] == ('book', 'bricklink')
    assert kind(cat, '5002-1')[1:] == ('gear', 'theme')                                   # BrickLink agrees: still a guess, untouched
    assert kind(cat, '5004-1')[1:] == ('book', 'theme')                                   # not listed
    assert links(cat, '5001-1') == [dict(provider_kind='B', provider_key='5001', status='to_check', method='same_number', origin='bricklink_list')]
    assert [r['id'] for r in q(cat, "SELECT id FROM item WHERE born_key='5001-1'")] == [before[0]]
    assert q(cat, "SELECT kind FROM item_fts WHERE item_id=?", before[0]) == [dict(kind='book')]


def test_a_correction_to_set_gives_the_candidate_never_a_matched_link(tmp_path):
    _, cat = catalogue(tmp_path)
    load(tmp_path, cat, [i for i in ITEMS if i[1] != '5005'] + [('S', '5005-1', 'A set after all'), ('O', '5005-1', 'and its box')])
    assert kind(cat, '5005-1')[1:] == ('set', 'bricklink')                                  # S and O are one match: the box never competes
    assert links(cat, '5005-1') == [dict(provider_kind='S', provider_key='5005-1', status='to_check', method='same_number', origin='bricklink_list')]


def test_a_number_under_several_types_is_ambiguous_and_left_alone(tmp_path):
    _, cat = catalogue(tmp_path)
    r = load(tmp_path, cat, ITEMS + [('C', '5001', 'Also a catalog'), ('B', '5002', 'Also a book')])
    assert kind(cat, '5001-1')[1:] == ('gear', 'theme')                                              # B and C, the guess is gear
    assert kind(cat, '5002-1')[1:] == ('gear', 'theme') and r['counts']['kinds_ambiguous'] == 2     # G and B: the guess and another type disagree
    assert links(cat, '5001-1') == []                                                                 # ambiguous: no candidate either
    assert links(cat, '5002-1') == [dict(provider_kind='G', provider_key='5002', status='to_check', method='same_number', origin='bricklink_list')]


def test_only_a_trailing_dash_one_is_stripped_and_parts_and_figures_never_match_a_set(tmp_path):
    from brickwork.store4.bricklink_list import same_number_key, zero_part_matches
    assert same_number_key('G', 'sets', '852706-1') == '852706' and same_number_key('G', 'sets', '852706-2') is None
    assert same_number_key('S', 'sets', '852706-2') == '852706-2' and same_number_key('P', 'parts', '3001') == '3001'
    listed = {('G', '852706'), ('S', '852706-1'), ('O', '852706-1'), ('P', '852706'), ('M', '852706'), ('B', '852706-1')}
    assert zero_part_matches('852706-1', listed) == {('G', '852706'), ('S', '852706-1')}
    assert zero_part_matches('852706-2', listed) == set()


def test_a_rebrickable_gear_set_matches_the_bricklink_number_without_the_suffix(tmp_path):
    sets = EXTRA_SETS + [('852706-1', 'Gear Item', '2014', '9001', '0', '')]
    _, cat = catalogue(tmp_path, sets=sets)
    load(tmp_path, cat, ITEMS + [('G', '852706', 'The gear item'), ('P', '852706', 'a spurious part'), ('M', '852706', 'a spurious figure')])
    assert kind(cat, '852706-1')[1:] == ('gear', 'theme')
    assert links(cat, '852706-1') == [dict(provider_kind='G', provider_key='852706', status='to_check', method='same_number', origin='bricklink_list')]


def test_loading_the_lists_never_creates_an_item(tmp_path):
    _, cat = catalogue(tmp_path)
    before = (q(cat, 'SELECT id, born_key FROM item ORDER BY id'), q(cat, "SELECT key, value FROM meta WHERE key LIKE '%high_water' ORDER BY key"))
    load(tmp_path, cat, ITEMS + [('P', 'only-at-bricklink', 'No Rebrickable twin'), ('S', '99999-1', 'Nor this set')])
    assert (q(cat, 'SELECT id, born_key FROM item ORDER BY id'), q(cat, "SELECT key, value FROM meta WHERE key LIKE '%high_water' ORDER BY key")) == before
    assert q(cat, "SELECT count(*) AS n FROM item_link WHERE provider_key IN ('only-at-bricklink', '99999-1')")[0]['n'] == 0


def test_a_new_list_undoes_what_the_old_one_established(tmp_path):
    _, cat = catalogue(tmp_path)
    load(tmp_path, cat)
    load(tmp_path, cat, [i for i in ITEMS if i[1] not in ('6081-1', '3001')] + [('S', 'other-1', 'x'), ('P', 'other-2', 'y')])
    assert links(cat, '6081-1')[0]['status'] == 'inferred' and links(cat, '6081-1')[0]['method'] == 'set_number'
    assert links(cat, '3001', 'parts') == []                                              # the candidate is gone with its list entry
    assert kind(cat, '5001-1')[1:] == ('book', 'bricklink')                                  # a correction is kept: the kind is not part of any list


def test_ids_the_catalogue_id_and_the_rest_of_the_file_are_carried(tmp_path):
    _, cat = catalogue(tmp_path)
    keep = lambda: (q(cat, 'SELECT * FROM item_link WHERE method NOT IN (?, ?, ?) ORDER BY id', 'bricklink_list', 'set_number', 'same_number'),
                    q(cat, "SELECT * FROM meta WHERE key != 'created_at'"), q(cat, 'SELECT * FROM inventory ORDER BY id'),
                    q(cat, 'SELECT * FROM inventory_part ORDER BY 1, 2, 3, 4'), q(cat, 'SELECT * FROM color ORDER BY id'))
    before = keep()
    load(tmp_path, cat)
    assert keep() == before
    assert {r['kind'] for r in q(cat, 'SELECT kind FROM build')} >= {'rebrickable_dump', 'bricklink_list'}
    with closing(sqlite3.connect(cat)) as db:
        assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'delete' and db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_the_fts_rows_of_changed_items_are_refreshed(tmp_path):
    _, cat = catalogue(tmp_path)
    load(tmp_path, cat)
    item = kind(cat, '3001', 'parts')[0]
    assert q(cat, 'SELECT keys FROM item_fts WHERE item_id=?', item) == [dict(keys='3001 3001')]        # the born key and the candidate's key
    assert len(q(cat, 'SELECT rowid FROM item_fts')) == q(cat, 'SELECT count(*) AS n FROM item WHERE retired_at IS NULL')[0]['n']
    assert q(cat, "SELECT count(*) AS n FROM item_fts WHERE item_fts MATCH 'keys:5001'")[0]['n'] == 1


# ---------- swap and lock ----------

def test_a_concurrent_build_is_refused_and_touches_nothing(tmp_path):
    _, cat = catalogue(tmp_path)
    before = cat.read_bytes()
    write_xml(tmp_path / 'bl')
    (tmp_path / 'catalogue.db.new').write_bytes(b'someone elses build')
    with open(tmp_path / 'catalogue.db.lock', 'a') as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BuildBusy, match='another catalogue build'):
            import_bricklink(cat, tmp_path / 'bl', app_version='t', now=STAMP)
    assert cat.read_bytes() == before and (tmp_path / 'catalogue.db.new').read_bytes() == b'someone elses build'
    (tmp_path / 'catalogue.db.new').unlink()
    load(tmp_path, cat)                                                                    # the lock is released after the import


def test_the_old_file_stays_as_prev_and_a_failure_leaves_the_pair_untouched(tmp_path, monkeypatch):
    _, cat = catalogue(tmp_path)
    old = cat.read_bytes()
    load(tmp_path, cat)
    assert (tmp_path / 'catalogue.db.prev').read_bytes() == old and cat.read_bytes() != old
    published = cat.read_bytes()
    import brickwork.store4.bricklink_list as mod
    monkeypatch.setattr(mod, 'apply_list', lambda *a, **k: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        load(tmp_path, cat)
    assert cat.read_bytes() == published and (tmp_path / 'catalogue.db.prev').read_bytes() == old
    assert sorted(p.name for p in tmp_path.glob('catalogue.db*')) == ['catalogue.db', 'catalogue.db.lock', 'catalogue.db.prev']


def test_a_merge_that_committed_meanwhile_stops_the_swap(tmp_path):
    from brickwork.store4.errors import CatalogueMismatch
    _, cat = catalogue(tmp_path)
    col = tmp_path / 'brickwork.db'
    with closing(connect(col, cat)) as db:
        activate(db)
        for key in ('3001', '3023'):
            identity.project(db, ids(cat)[key])
        db.execute("UPDATE item SET catalogue_retired_at=? WHERE born_key='3001'", (STAMP,))
        db.execute("UPDATE item SET merged_into=(SELECT id FROM item WHERE born_key='3023') WHERE born_key='3001'")     # the catalogue holds 3001 live
        db.commit()
    before = cat.read_bytes()
    with pytest.raises(CatalogueMismatch, match='merged in the collection'):
        load(tmp_path, cat, collection=col)
    assert cat.read_bytes() == before and not (tmp_path / 'catalogue.db.new').exists()


# ---------- re-download ----------

def test_a_redownload_keeps_the_list_tables_the_upgrades_the_corrections_and_the_candidates(tmp_path):
    _, cat = catalogue(tmp_path)
    load(tmp_path, cat, colours=[(5, 'Red', 'C91A09')])
    first = state(cat)
    ids_before = ids(cat)
    maps = tmp_path / 'maps'
    build(write_dump(tmp_path / 'd2', **{**tables(), 'sets': EXTRA_SETS}), cat, app_version='t', now=STAMP, mappings_dir=maps)
    assert ids(cat) == ids_before
    assert links(cat, '6081-1')[0]['status'] == 'matched' and links(cat, '6081-1')[0]['method'] == 'bricklink_list'
    assert kind(cat, '5001-1')[1:] == ('book', 'bricklink') and links(cat, '3001', 'parts')[0]['method'] == 'same_number'
    assert q(cat, 'SELECT count(*) AS n FROM bricklink_item')[0]['n'] == len(ITEMS) and q(cat, 'SELECT name FROM bricklink_color') == [dict(name='Red')]
    assert [b['kind'] for b in q(cat, "SELECT kind FROM build WHERE kind LIKE 'bricklink%' ORDER BY id")] == ['bricklink_list', 'bricklink_colors']
    assert state(cat) == first                                                             # the same result as the import produced
    report = json.loads(q(cat, 'SELECT counts_json FROM build ORDER BY id DESC LIMIT 1')[0]['counts_json'])['bricklink_list']
    assert report['links_upgraded'] == 1 and report['same_number'] >= 2 and report['kinds_corrected'] == 0       # the corrections came with the kinds
    assert q(cat, "SELECT keys FROM item_fts WHERE item_id=?", kind(cat, '3001', 'parts')[0]) == [dict(keys='3001 3001')]


def test_a_redownload_corrects_a_set_the_new_dump_makes_theme_guessed(tmp_path):
    _, cat = catalogue(tmp_path)
    load(tmp_path, cat, colours=[(5, 'Red', 'C91A09')])
    new_set = EXTRA_SETS + [('5006-1', 'Third Gear Bag', '2015', '501', '0', '')]
    build(write_dump(tmp_path / 'd2', **{**tables(), 'sets': new_set}), cat, app_version='t', now=STAMP, mappings_dir=tmp_path / 'maps')
    assert kind(cat, '5006-1')[1:] == ('gear', 'theme')                                    # B 5006 is not listed: no change
    write_xml(tmp_path / 'bl2', ITEMS + [('B', '5006', 'Late Book')])
    import_bricklink(cat, tmp_path / 'bl2', app_version='t', now=STAMP)
    assert kind(cat, '5006-1')[1:] == ('book', 'bricklink')


def test_a_redownload_without_a_list_adds_none(tmp_path):
    _, cat = catalogue(tmp_path)
    build(write_dump(tmp_path / 'd2', **{**tables(), 'sets': EXTRA_SETS}), cat, app_version='t', now=STAMP, mappings_dir=tmp_path / 'maps')
    assert q(cat, 'SELECT count(*) AS n FROM bricklink_item')[0]['n'] == 0 and 'bricklink_list' not in json.loads(
        q(cat, 'SELECT counts_json FROM build ORDER BY id DESC LIMIT 1')[0]['counts_json'])


# ---------- reconcile ----------

class Pair:
    """A catalogue without the list, a collection that activated it and projected `keys` (a gear stock row on 5001-1), then the
    list imported into the catalogue and the collection attached to the new file but not yet activated against it."""

    def __init__(self, tmp_path, keys=('6081-1', '3001', '5001-1', '5005-1', '6081-1')):
        self.tmp = tmp_path
        _, self.cat = catalogue(tmp_path)
        self.col = tmp_path / 'brickwork.db'
        self.id = ids(self.cat)
        with closing(connect(self.col, self.cat)) as db:
            activate(db)
            for k in keys:
                identity.project(db, self.id[k])
            db.execute("INSERT INTO stock(id, kind, item_id, quantity, created_at, updated_at) VALUES('s1', 'gear', ?, 1, ?, ?)", (self.id['5001-1'], STAMP, STAMP))
            db.commit()
        load(tmp_path, self.cat, colours=[(5, 'Red', 'C91A09')])
        self.db = connect(self.col, self.cat)
        activate(self.db)

    def sql(self, sql, *args):
        rows = [dict(r) for r in self.db.execute(sql, args).fetchall()]
        self.db.commit()
        return rows


@pytest.fixture
def pair(tmp_path):
    p = Pair(tmp_path)
    yield p
    p.db.close()


def test_reconcile_mirrors_the_upgrade_the_kind_the_kind_differs_row_and_the_names(pair):
    r = reconcile(pair.db)
    link = pair.sql("SELECT status, method, origin FROM item_link WHERE provider_key='6081-1'")
    assert link == [dict(status='matched', method='bricklink_list', origin='bricklink_list')] and r['changes']['links_upgraded'] == 1
    assert pair.sql("SELECT kind, kind_source FROM item WHERE born_key='5005-1'") == [dict(kind='book', kind_source='bricklink')]        # unreferenced: applied
    assert pair.sql("SELECT kind, kind_source FROM item WHERE born_key='5001-1'") == [dict(kind='gear', kind_source='theme')]            # held as gear stock
    status = pair.sql('SELECT item_id, status, reason, evidence_json FROM item_provider_status')
    assert [(s['item_id'], s['status'], s['reason'], json.loads(s['evidence_json'])) for s in status] == [
        (pair.id['5001-1'], 'to_check', 'kind_differs', {'from': 'gear', 'to': 'book'})]
    assert r['not_applied']['kind_differs'][0]['born_key'] == '5001-1'
    assert pair.sql("SELECT item_id, value, unit FROM item_property WHERE key='name' AND source='bricklink' ORDER BY item_id") == [
        dict(item_id=pair.id['6081-1'], value='King Leo Castle', unit=None)]                      # only items that resolve to a list entry
    assert r['changes']['bricklink_names_added'] == 1
    events = pair.sql('SELECT entity_kind, entity_id, field, new_value FROM event')
    assert ('item', str(pair.id['6081-1']), 'property.name.bricklink', 'King Leo Castle') in [tuple(e.values()) for e in events]
    assert any(e['field'] == 'kind' and e['entity_id'] == str(pair.id['5005-1']) for e in events)


def test_reconcile_mirrors_same_number_candidates_as_to_check(pair):
    r = reconcile(pair.db)
    assert pair.sql("SELECT provider_kind, status, method, origin FROM item_link WHERE item_id=? AND provider='bricklink'", pair.id['3001']) == [
        dict(provider_kind='P', status='to_check', method='same_number', origin='bricklink_list')]
    assert pair.sql("SELECT count(*) AS n FROM item_link WHERE method='same_number' AND status!='to_check'")[0]['n'] == 0
    assert r['same_number']['list_build'] == pair.sql('SELECT max(id) AS m FROM catalogue_build WHERE kind="bricklink_list"')[0]['m']
    assert not any(n['name'] for n in pair.sql("SELECT 1 AS name FROM item_property WHERE item_id=?", pair.id['3001']))      # a to_check link names nothing


def test_the_pass_reaches_a_local_item_the_catalogue_does_not_number(pair):
    pair.db.execute("INSERT INTO item(id, origin, kind, kind_source, name, born_provider, born_namespace, born_key, created_at, updated_at)"
                    " VALUES(1000000007, 'local', 'part', 'namespace', 'Fetched Part', 'rebrickable', 'parts', '3023', ?, ?)", (STAMP, STAMP))
    pair.db.execute("INSERT INTO item(id, origin, kind, kind_source, name, born_provider, born_namespace, born_key, created_at, updated_at)"
                    " VALUES(1000000008, 'local', 'part', 'namespace', 'Fetched Brick', 'rebrickable', 'parts', 'sw0001', ?, ?)", (STAMP, STAMP))
    pair.db.execute("INSERT INTO item(id, origin, kind, kind_source, name, born_provider, born_namespace, born_key, created_at, updated_at)"
                    " VALUES(1000000009, 'local', 'gear', 'bricklink', 'Fetched Gear', 'rebrickable', 'sets', '7777-1', ?, ?)", (STAMP, STAMP))
    pair.db.commit()
    r = reconcile(pair.db)
    assert pair.sql('SELECT provider_kind, provider_key, status, method FROM item_link WHERE item_id=1000000009') == [      # -1 stripped, as the catalogue pass does
        dict(provider_kind='G', provider_key='7777', status='to_check', method='same_number')]
    assert pair.sql('SELECT status, method, origin, provider_kind FROM item_link WHERE item_id=1000000007') == [
        dict(status='to_check', method='same_number', origin='bricklink_list', provider_kind='P')]
    assert pair.sql('SELECT count(*) AS n FROM item_link WHERE item_id=1000000008')[0]['n'] == 0                 # sw0001 is listed as an M, not a P
    assert 1000000007 in r['same_number']['added'] and r['changes']['same_number_added'] == len(r['same_number']['added'])


def test_reconcile_without_a_list_reports_none_and_writes_no_names(tmp_path):
    _, cat = catalogue(tmp_path)
    with closing(connect(tmp_path / 'brickwork.db', cat)) as db:
        activate(db)
        r = reconcile(db)
        assert r['same_number'] is None and r['bricklink_names'] is None
        assert db.execute('SELECT count(*) FROM item_property').fetchone()[0] == 0


def test_a_second_reconcile_changes_nothing_and_a_renamed_list_entry_is_refreshed(pair, tmp_path):
    reconcile(pair.db)
    snapshot = {t: pair.sql(f'SELECT * FROM {t} ORDER BY 1, 2') for t in ('item', 'item_link', 'item_property', 'event', 'item_provider_status')}
    second = reconcile(pair.db)
    assert second['events'] == 0 and second['changes'] == {}
    assert {t: pair.sql(f'SELECT * FROM {t} ORDER BY 1, 2') for t in snapshot} == snapshot
    pair.db.close()
    renamed = [(k, n, 'Castle, renamed' if n == '6081-1' else m) for k, n, m in ITEMS]
    load(tmp_path, pair.cat, renamed)
    pair.db = connect(pair.col, pair.cat)
    activate(pair.db)
    third = reconcile(pair.db)
    assert third['changes'] == {'bricklink_names_refreshed': 1}
    assert pair.sql("SELECT value FROM item_property WHERE key='name' AND source='bricklink'") == [dict(value='Castle, renamed')]


def test_a_manual_or_matched_answer_is_not_changed_by_the_list(tmp_path):
    """The M.2c guard holds for the list's upgrades: a manual link keeps its answer, and the upgrade is applied to the inferred one only."""
    p = Pair(tmp_path)
    p.db.execute("UPDATE item_link SET preferred=0 WHERE provider_key='6081-1'")
    p.db.execute("INSERT INTO item_link(item_id, provider, provider_kind, provider_key, status, method, origin, preferred, decided_at)"
                 " VALUES(?, 'bricklink', 'S', 'mine-1', 'manual', 'user', 'user', 1, ?)", (p.id['6081-1'], STAMP))
    p.db.commit()
    r = reconcile(p.db)
    assert p.sql("SELECT status FROM item_link WHERE provider_key='mine-1'") == [dict(status='manual')]
    assert identity.resolve(p.db, p.id['6081-1'], None)[:2] == ('S', 'mine-1')
    assert p.sql("SELECT status FROM item_link WHERE provider_key='6081-1'") == [dict(status='matched')] 
    assert [x['reason'] for x in r['not_applied']['links']] == ['preferred_differs']                  # the user's preferred row stays; nothing else is reported
    p.db.close()


def test_the_downloads_real_shape_parses_and_is_refused_as_partial():
    """tests/fixtures/bricklink-catalog holds three of the eight types in BrickLink's own shape (escaped names, empty tags)."""
    from pathlib import Path
    from brickwork.store4.bricklink_list import Lists
    with pytest.raises(BrickLinkListError, match='found MPS'):
        Lists(Path(__file__).parent / 'fixtures' / 'bricklink-catalog')
    from brickwork.store4.bricklink_list import _parse
    kind, rows = _parse('catalog-Parts.xml', (Path(__file__).parent / 'fixtures' / 'bricklink-catalog' / 'catalog-Parts.xml').read_bytes())
    assert kind == 'items' and rows[0]['name'] == 'Sticker (Unsorted, Generic Entry)' and rows[0]['weight'] is None and rows[2]['alt_item_ids'] == '71185'


def test_a_redownload_after_a_correction_to_set_gives_what_the_import_gave(tmp_path):
    _, cat = catalogue(tmp_path)
    load(tmp_path, cat, [i for i in ITEMS if i[1] != '5005'] + [('S', '5005-1', 'A set after all')])
    first = state(cat)
    build(write_dump(tmp_path / 'd2', **{**tables(), 'sets': EXTRA_SETS}), cat, app_version='t', now=STAMP, mappings_dir=tmp_path / 'maps')
    assert state(cat) == first and links(cat, '5005-1')[0]['status'] == 'to_check'


# ---------- zero-part sets with no theme row: the guess is `set` ----------

def test_a_zero_part_set_matching_only_a_gear_number_is_corrected_and_loses_its_set_link(tmp_path):
    _, cat = catalogue(tmp_path)
    assert kind(cat, '5003-1')[1:] == ('set', 'namespace') and links(cat, '5003-1')[0]['method'] == 'set_number'
    r = load(tmp_path, cat, ITEMS + [('G', '5003', 'It is gear')])
    assert kind(cat, '5003-1')[1:] == ('gear', 'bricklink') and r['counts']['kinds_corrected'] == 3
    assert links(cat, '5003-1') == [dict(provider_kind='G', provider_key='5003', status='to_check', method='same_number', origin='bricklink_list')]
    first = state(cat)
    build(write_dump(tmp_path / 'd2', **{**tables(), 'sets': EXTRA_SETS}), cat, app_version='t', now=STAMP, mappings_dir=tmp_path / 'maps')
    assert state(cat) == first                                                             # a re-download agrees: no inferred S link comes back


def test_a_zero_part_set_matching_only_s_stays_a_set_with_its_upgraded_link(tmp_path):
    _, cat = catalogue(tmp_path)
    r = load(tmp_path, cat, ITEMS + [('S', '5003-1', 'A real set'), ('O', '5003-1', 'its box')])
    assert kind(cat, '5003-1')[1:] == ('set', 'namespace')
    assert links(cat, '5003-1') == [dict(provider_kind='S', provider_key='5003-1', status='matched', method='bricklink_list', origin='bricklink_list')]
    assert r['counts']['kinds_ambiguous'] == 0


def test_a_zero_part_set_matching_s_and_gear_is_ambiguous_and_untouched(tmp_path):
    _, cat = catalogue(tmp_path)
    r = load(tmp_path, cat, ITEMS + [('S', '5003-1', 'A real set'), ('G', '5003', 'and gear')])
    assert kind(cat, '5003-1')[1:] == ('set', 'namespace') and r['counts']['kinds_ambiguous'] == 1
    assert [x['status'] for x in links(cat, '5003-1')] == ['matched']                      # the set link is upgraded as for any set


def test_a_bundle_holding_a_set_the_list_corrects_loses_its_bl_digest_on_import_and_on_re_download(tmp_path):
    inv = dict(inventories=[(3, 1, '9999-1')], inventory_parts=[(3, '3023', 4, 1, 'False', '')], inventory_minifigs=[],
               inventory_sets=[(3, '5003-1', 1)])               # 5003-1 is a zero-part set with the default kind: its S link counts
    _, cat = catalogue(tmp_path, **inv)
    digest = lambda: q(cat, "SELECT i.born_key, v.bl_digest FROM inventory v JOIN item i ON i.id=v.item_id ORDER BY i.born_key")
    before = digest()
    assert before == [dict(born_key='9999-1', bl_digest=before[0]['bl_digest'])] and before[0]['bl_digest']
    r = load(tmp_path, cat, ITEMS + [('G', '5003', 'It is gear')])
    assert kind(cat, '5003-1')[1:] == ('gear', 'bricklink') and digest() == [dict(born_key='9999-1', bl_digest=None)]
    assert r['counts']['bl_digest']['with_digest_before'] == 1 and r['counts']['bl_digest']['null'] == 1
    build(write_dump(tmp_path / 'd2', **{**tables(), 'sets': EXTRA_SETS, **inv}), cat, app_version='t', now=STAMP, mappings_dir=tmp_path / 'maps')
    assert digest() == [dict(born_key='9999-1', bl_digest=None)]                           # the same NULL a rebuild gives


def test_a_digest_that_was_null_stays_null_and_an_untouched_one_is_unchanged(tmp_path):
    _, cat = catalogue(tmp_path)
    before = q(cat, 'SELECT id, bl_digest FROM inventory ORDER BY id')
    assert any(r['bl_digest'] is None for r in before)
    load(tmp_path, cat)
    assert q(cat, 'SELECT id, bl_digest FROM inventory ORDER BY id') == before
