"""The mapping layers of the catalogue builder (M.2b): colour and part links, the rules, the local layer, FTS link keys and
bl_digest, with invented dumps and mapping files only."""
from contextlib import closing
import json
import sqlite3

from brickwork.store4.bldigest import bl_digest
from brickwork.store4.builder import build
from tests.store4_dump import default, write_dump, write_mappings

STAMP = '2026-10-23T12:00:00.000Z'
EXTRA_COLORS = [('1051', 'Pastel Blue', '', 'False'), ('313', 'Maersk Blue', '', 'False')]
COLOR_LINKS = [('0', 'Black', 'bricklink', '11', 'Black', 0, 9), ('4', 'Red', 'bricklink', '5', 'Red', 0, 9),
               ('15', 'White', 'bricklink', '1', 'White', 0, 9), ('4', 'Red', 'lego', '21', 'Bright Red', 0, 9),
               ('1051', 'Pastel Blue', 'bricklink', '72', 'Pastel Blue', 1, 734), ('313', 'Maersk Blue', 'bricklink', '72', 'Maersk Blue', 0, 469),
               ('1051', 'Pastel Blue', 'lego', '300', 'Pastel Blue', 0, 9), ('313', 'Maersk Blue', 'lego', '300', 'Maersk Blue', 1, 9),
               ('777', 'Not In The Dump', 'bricklink', '999', 'Nope', 0, 1)]


def part(num, key, color='', status='matched', method='external_ids', preferred=0, kind='P'):
    return (num, color, 'bricklink', kind, key, status, method, preferred)


def make(tmp_path, *, parts=(), exceptions=(), local=None, colors=COLOR_LINKS, name='d', dump_parts=None, **tables):
    """Build one catalogue from the invented dump, the given mapping rows and optional local files {name: rows}."""
    maps = write_mappings(tmp_path / f'maps-{name}', colors=colors, parts=parts, exceptions=exceptions)
    local_dir = None
    if local is not None:
        local_dir = tmp_path / f'local-{name}'
        local_dir.mkdir()
        for fname, (rows, manifest) in local.items():
            (local_dir / fname).write_text('# mapping_version: L1\n# dump_date: 2099-01-01\n# source: private\n'
                                           'rb_part_num,rb_color_id,provider,provider_kind,provider_key,status,method,preferred\n'
                                           + ''.join(','.join(map(str, r)) + '\n' for r in rows))
            if manifest:
                (local_dir / (fname[:-4] + '.manifest.json')).write_text(json.dumps(manifest))
    if dump_parts is not None:
        tables['parts'] = dump_parts
    dump = write_dump(tmp_path / f'dump-{name}', **{'colors': default()['colors'] + EXTRA_COLORS, **tables})
    target = tmp_path / f'catalogue-{name}.db'
    report = build(dump, target, app_version='t', now=STAMP, mappings_dir=maps, local_dir=local_dir)
    return report, target


def q(path, sql, *args):
    with closing(sqlite3.connect(f'file:{path}?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute(sql, args)]


def item_id(cat, key):
    return q(cat, 'SELECT id FROM item WHERE born_key=?', key)[0]['id']


def resolve(cat, key, color_key=None):
    """The resolution function of design 3.2 over the catalogue's own links -> (kind, key) or None."""
    iid = item_id(cat, key)
    cid = q(cat, 'SELECT id FROM color WHERE born_key=?', color_key)[0]['id'] if color_key is not None else None
    rows = q(cat, "SELECT * FROM item_link WHERE item_id=? AND provider='bricklink' AND status IN ('matched','inferred')", iid)
    pool = [r for r in rows if cid is not None and r['color_id'] == cid] or [r for r in rows if r['color_id'] is None]
    if not pool:
        return None
    best = min(pool, key=lambda r: (-r['preferred'], {'matched': 0, 'inferred': 1}[r['status']], r['provider_key']))
    return best['provider_kind'], best['provider_key']


# ---------- colours ----------

def test_colour_links_inverse_preferred_and_the_unique_index(tmp_path):
    report, cat = make(tmp_path)
    links = q(cat, 'SELECT c.born_key, l.provider, l.provider_key, l.provider_name, l.status, l.method, l.origin, l.inverse_preferred, l.build_id'
                   ' FROM color_link l JOIN color c ON c.id=l.color_id ORDER BY c.born_key, l.provider')
    by = {(r['born_key'], r['provider']): r for r in links}
    assert by[('4', 'lego')] | {} == dict(born_key='4', provider='lego', provider_key='21', provider_name='Bright Red', status='matched',
                                          method='external_ids', origin='shipped', inverse_preferred=0, build_id=1)
    assert by[('1051', 'bricklink')]['inverse_preferred'] == 1 and by[('313', 'bricklink')]['inverse_preferred'] == 0     # BrickLink 72
    assert by[('313', 'lego')]['inverse_preferred'] == 1 and by[('1051', 'lego')]['inverse_preferred'] == 0               # a LEGO colour id
    assert ('777', 'bricklink') not in by and report['counts']['mapping_skipped']['colour_links_colour_not_in_file'] == 1
    assert report['counts']['colour_links'] == len(links)


def test_two_flagged_colours_for_one_provider_key_keep_the_lowest(tmp_path):
    rows = [('1051', 'Pastel Blue', 'bricklink', '72', 'P', 1, 1), ('313', 'Maersk Blue', 'bricklink', '72', 'M', 1, 1)]
    report, cat = make(tmp_path, colors=rows)
    got = q(cat, "SELECT c.born_key FROM color_link l JOIN color c ON c.id=l.color_id WHERE l.inverse_preferred=1")
    assert len(got) == 1 and report['counts']['mapping_skipped']['colour_inverse_preferred_dropped'] == 1


# ---------- parts and rules ----------

def test_leg_rule_part_gets_only_rule_rows(tmp_path):
    shipped = [part('970c03', '970c11'), part('970c03', '970c05'), part('970c03', '970c11', color='4'), part('3023', '3023')]
    report, cat = make(tmp_path, parts=shipped)
    rows = q(cat, "SELECT l.*, c.born_key AS colour FROM item_link l LEFT JOIN color c ON c.id=l.color_id WHERE item_id=?", item_id(cat, '970c03'))
    assert {r['origin'] for r in rows} == {'rule'} and len(rows) == 2                      # none of its parts.csv rows
    assert resolve(cat, '970c03', '0') == ('P', '970c00')                                  # one-colour legs in Black
    assert resolve(cat, '970c03', '4') == ('P', '970c11')                                  # any other hip colour
    assert resolve(cat, '3023') == ('P', '3023')
    assert report['counts']['mapping_skipped']['parts_csv_replaced_by_leg_rule'] == 3
    status = {r['provider_key']: r['status'] for r in rows}
    assert status == {'970c00': 'inferred', '970c11': 'matched'}        # Rebrickable confirms 970c11 only (970c00 is the convention)


def test_shipped_rows_scope_preferred_and_unknown_parts(tmp_path):
    shipped = [part('3001', '3001'), part('3001', '3001old', status='inferred', method='element'), part('3001', '3001-red', color='4'),
               part('3001', 'a', preferred=1), part('3001', 'b', preferred=1), part('nope', 'zzz'), part('3001', 'q', color='777')]
    report, cat = make(tmp_path, parts=shipped)
    assert resolve(cat, '3001', '4') == ('P', '3001-red') and resolve(cat, '3001', '15') == ('P', 'a')       # scoped wins; lowest preferred
    pref = q(cat, 'SELECT provider_key FROM item_link WHERE item_id=? AND color_id IS NULL AND preferred=1', item_id(cat, '3001'))
    assert pref == [{'provider_key': 'a'}]                                                 # the index allows one; counted, build did not fail
    skipped = report['counts']['mapping_skipped']
    assert skipped['preferred_resolved'] == 1 and skipped['parts_csv_item_not_in_file'] == 1 and skipped['parts_csv_colour_not_in_file'] == 1


def test_set_number_rule_and_exceptions(tmp_path):
    report, cat = make(tmp_path, exceptions=[('6081-1', 'S', '6081-1b', 'note')])
    assert resolve(cat, '9999-1') == ('S', '9999-1')
    row = q(cat, "SELECT * FROM item_link WHERE item_id=? AND provider_kind='S'", item_id(cat, '9999-1'))[0]
    assert (row['status'], row['method'], row['origin'], row['preferred']) == ('inferred', 'set_number', 'rule', 1)
    exc = q(cat, 'SELECT * FROM item_link WHERE item_id=?', item_id(cat, '6081-1'))
    assert [(r['provider_key'], r['status'], r['method'], r['origin']) for r in exc] == [('6081-1b', 'matched', 'set_exception', 'shipped')]
    assert q(cat, 'SELECT count(*) AS n FROM item_link WHERE item_id=?', item_id(cat, '5001-1'))[0]['n'] == 0      # gear by theme: no S link
    assert resolve(cat, '5003-1') == ('S', '5003-1')                                       # zero-part, no theme row: still a set


def test_local_layer_replaces_the_same_scope_only(tmp_path):
    shipped = [part('3023', '3023'), part('3023', '3023-red', color='4'), part('3001', '3001')]
    local = {'parts.csv': ([part('3023', '3023-local', method='composition'), part('3001', 'cand1', status='to_check', method='composition'),
                            part('3001', 'cand2', status='to_check', method='composition'), part('nope', 'zz')], {'note': 'manifest'}),
             'minifigs.csv': ([('fig-000001', '', 'bricklink', 'M', 'twn1', 'matched', 'composition', 1)], None)}
    report, cat = make(tmp_path, parts=shipped, local=local)
    rows = q(cat, 'SELECT provider_key, origin, color_id FROM item_link WHERE item_id=? ORDER BY provider_key', item_id(cat, '3023'))
    assert [(r['provider_key'], r['origin']) for r in rows] == [('3023-local', 'local'), ('3023-red', 'shipped')]   # other scope untouched
    assert resolve(cat, '3023', '15') == ('P', '3023-local') and resolve(cat, '3023', '4') == ('P', '3023-red')
    assert {r['provider_key'] for r in q(cat, "SELECT provider_key FROM item_link WHERE status='to_check'")} == {'cand1', 'cand2'}
    assert resolve(cat, '3001') is None                    # the local to_check rows replaced the shipped row and are never used
    assert resolve(cat, 'fig-000001') == ('M', 'twn1')
    assert report['counts']['local_mappings']['parts.csv']['manifest'] == {'note': 'manifest'}
    assert report['counts']['local_mappings']['minifigs.csv']['manifest'] is None
    assert report['counts']['mapping_skipped']['local_parts_item_not_in_file'] == 1


# ---------- FTS ----------

def test_fts_finds_an_item_by_a_linked_key(tmp_path):
    _, cat = make(tmp_path, parts=[part('3023', '3023bl')], exceptions=[('6081-1', 'S', '6081-1b', 'x')])
    with closing(sqlite3.connect(cat)) as db:
        hit = lambda term: [r[0] for r in db.execute('SELECT item_id FROM item_fts WHERE item_fts MATCH ?', (term,))]
        assert hit('"3023bl"') == [item_id(cat, '3023')]
        assert hit('"6081-1b"') == [item_id(cat, '6081-1')]
        assert hit('"970c11"') == [item_id(cat, '970c03')]                                     # a rule key
        assert hit('"3023"') == [item_id(cat, '3023')]                                         # the born key stays


# ---------- bl_digest ----------

INV = [(1, 1, '6081-1'), (2, 1, '9999-1'), (3, 1, '5003-1'), (4, 1, '5004-1'), (5, 1, '5001-1')]


def digests(cat):
    return {r['born_key']: r['bl_digest'] for r in q(cat, 'SELECT i.born_key, v.bl_digest FROM inventory v JOIN item i ON i.id=v.item_id')}


def test_bl_digest_is_equal_in_brickLink_space_and_null_when_unmapped(tmp_path):
    parts = [part('3023', 'X'), part('3001', 'X'), part('970c03', '970c00')]
    t = dict(inventories=INV, inventory_minifigs=[], inventory_sets=[],
             inventory_parts=[(1, '3023', 4, 2, 'False', ''), (1, '3001', 4, 1, 'False', ''),     # 3 x X Red: two Rebrickable parts, one key
                              (2, '3023', 4, 3, 'False', ''),                                     # 3 x X Red again, from a different set
                              (3, '3023', 4, 3, 'False', ''), (3, '3023', 4, 1, 'True', ''),      # a spare changes the digest
                              (4, '3023', 4, 1, 'False', ''), (4, '3023', 43, 1, 'False', ''),     # colour 43 has no BrickLink colour: NULL
                              (5, '3023', 4, 1, 'False', ''), (5, 'xx', 4, 1, 'False', '')])
    report, cat = make(tmp_path, parts=parts, **t)
    d = digests(cat)
    assert d['6081-1'] == d['9999-1'] and d['6081-1'] is not None
    assert d['5003-1'] not in (None, d['6081-1'])
    assert d['5004-1'] is None
    assert d['5001-1'] is None                           # 'xx' is not in the dump: the skipped line makes the list incomplete
    assert d['6081-1'] == bl_digest([('P', 'X', '5', 0, 3)])                                          # the 3.3-side helper agrees
    assert d['5003-1'] == bl_digest([('P', 'X', '5', 0, 3), ('P', 'X', '5', 1, 1)])
    assert bl_digest([('P', 'X', '5', 0, 1), ('P', 'X', '5', 0, 2)]) == bl_digest([('P', 'X', '5', 0, 3)])
    assert report['counts']['bl_digest_incomplete'] == 1
    assert report['counts']['bl_digest'] == {'with_digest': 3, 'null': 2}


def test_unmapped_part_and_to_check_only_part_give_null(tmp_path):
    local = {'parts.csv': ([part('3001', 'cand', status='to_check', method='composition')], None)}
    t = dict(inventories=INV[:2], inventory_minifigs=[], inventory_sets=[],
             inventory_parts=[(1, '3023', 4, 1, 'False', ''), (2, '3001', 4, 1, 'False', '')])
    _, cat = make(tmp_path, parts=[part('3023', '3023')], local=local, **t)
    d = digests(cat)
    assert d['6081-1'] is not None and d['9999-1'] is None


def test_figure_and_set_lines_use_their_own_links(tmp_path):
    local = {'minifigs.csv': ([('fig-000001', '', 'bricklink', 'M', 'twn1', 'matched', 'composition', 1)], None)}
    t = dict(inventories=INV[:3] + [(9, 1, 'fig-000002')], inventory_parts=[(1, '3023', 4, 1, 'False', '')],
             inventory_minifigs=[(1, 'fig-000001', 2), (3, 'fig-000002', 1)], inventory_sets=[(2, '6081-1', 1)])
    _, cat = make(tmp_path, parts=[part('3023', '3023')], local=local, **t)
    d = digests(cat)
    assert d['6081-1'] == bl_digest([('P', '3023', '5', 0, 1), ('M', 'twn1', None, 0, 2)])
    assert d['9999-1'] == bl_digest([('S', '6081-1', None, 0, 1)])                                      # the set's S link (rule)
    assert d['5003-1'] is None                                                                          # fig-000002 has no M link
    assert d['fig-000002'] == bl_digest([])


def test_counts_and_mapping_version_are_recorded(tmp_path):
    report, cat = make(tmp_path, parts=[part('3023', '3023')])
    b = q(cat, 'SELECT mapping_version, counts_json FROM build')[0]
    counts = json.loads(b['counts_json'])
    assert b['mapping_version'] == '2099.1.1.1'
    assert counts['item_links']['by_origin_method_status']['shipped/external_ids/matched'] == 1
    assert counts['item_links']['by_origin_method_status']['rule/set_number/inferred'] == 3          # 6081-1, 9999-1, 5003-1
    assert counts['item_links']['total'] == q(cat, 'SELECT count(*) AS n FROM item_link')[0]['n']
    assert sum(counts['bl_digest'].values()) == q(cat, 'SELECT count(*) AS n FROM inventory')[0]['n']
    assert q(cat, 'PRAGMA foreign_key_check') == [] and all(r['build_id'] == 1 for r in q(cat, 'SELECT build_id FROM item_link'))


def test_an_inventory_without_lines_keeps_the_empty_digest_but_a_partial_one_does_not(tmp_path):
    t = dict(inventories=INV[:2], inventory_minifigs=[], inventory_sets=[], inventory_parts=[(2, 'xx', 4, 1, 'False', '')])
    report, cat = make(tmp_path, parts=[part('3023', '3023')], **t)
    d = digests(cat)
    assert d['6081-1'] == bl_digest([])          # truly no lines in the dump
    assert d['9999-1'] is None                   # its only line named a part the dump lacks
    assert report['counts']['bl_digest_incomplete'] == 1


def test_a_partial_inventory_stays_without_a_digest_once_carried(tmp_path):
    t = dict(inventories=INV[:2], inventory_minifigs=[], inventory_sets=[], inventory_parts=[(2, 'xx', 4, 1, 'False', '')])
    _, cat = make(tmp_path, parts=[part('3023', '3023')], name='p', **t)
    assert digests(cat)['9999-1'] is None
    gone = dict(t, inventories=INV[:1], inventory_parts=[])                # 9999-1's version leaves the dump and is carried
    _, cat = make(tmp_path, parts=[part('3023', '3023')], name='p', **gone)
    carried = q(cat, 'SELECT v.retired_at, v.bl_digest FROM inventory v JOIN item i ON i.id=v.item_id WHERE i.born_key=?', '9999-1')
    assert len(carried) == 1 and carried[0]['retired_at'] and carried[0]['bl_digest'] is None


def test_a_retired_part_keeps_its_links_and_a_carried_inventory_its_digest(tmp_path):
    parts = [part('3023', 'X'), part('3001', 'Y'), part('970c03', '970c11'), part('nope', 'zzz')]
    first = dict(inventories=[(1, 1, '6081-1'), (2, 2, '6081-1')], inventory_minifigs=[], inventory_sets=[],
                 inventory_parts=[(1, '3023', 4, 1, 'False', ''), (2, '3001', 4, 2, 'False', ''), (2, '970c03', 4, 1, 'False', '')])
    _, cat = make(tmp_path, parts=parts, name='r', **first)
    before = q(cat, 'SELECT v.version, v.bl_digest FROM inventory v ORDER BY v.version')
    assert before[1]['bl_digest'] == bl_digest([('P', 'Y', '5', 0, 2), ('P', '970c11', '5', 0, 1)])
    gone = dict(first, inventories=[(1, 1, '6081-1')], inventory_parts=first['inventory_parts'][:1])       # version 2 and two parts leave the dump
    _, cat = make(tmp_path, parts=parts, name='r', dump_parts=[p for p in default()['parts'] if p[0] not in ('3001', '970c03')], **gone)
    assert q(cat, "SELECT retired_at IS NOT NULL AS r FROM item WHERE born_key='3001'") == [{'r': 1}]
    assert resolve(cat, '3001') == ('P', 'Y')                                              # a retired part keeps its CSV link
    assert {r['origin'] for r in q(cat, 'SELECT origin FROM item_link WHERE item_id=?', item_id(cat, '970c03'))} == {'rule'}    # and its leg rule
    after = q(cat, 'SELECT v.version, v.retired_at, v.bl_digest FROM inventory v ORDER BY v.version')
    assert after[1]['retired_at'] and after[1]['bl_digest'] == before[1]['bl_digest']      # the carried inventory hashes as before
