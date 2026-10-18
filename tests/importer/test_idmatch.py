"""Synthetic evidence only: snapshots are never used by these tests."""

import hashlib
import json
import sqlite3

import pytest

from brickwork.core.importer.idmatch import match, open_readonly


@pytest.fixture
def databases(tmp_path):
    app, web, catalog = [tmp_path / name for name in ('app.db', 'extras.db', 'catalog.db')]
    with sqlite3.connect(app) as db:
        db.executescript('''
            CREATE TABLE rebrickable_parts(part, color_id, bricklink_part_num, bricklink_color_id);
            CREATE TABLE bricktracker_parts(id, figure, part, color, spare, quantity,
                missing, damaged, checked, element, rebrickable_inventory);
            CREATE TABLE bricktracker_sets(id, "set");
            CREATE TABLE bricktracker_wishes("set");
            CREATE TABLE bricktracker_minifigures(id, figure, quantity);
            CREATE TABLE rebrickable_minifigures(figure, name);
            CREATE TABLE bricktracker_individual_minifigures(id, figure, quantity);
            CREATE TABLE bricktracker_individual_parts(id, part, color, quantity,
                missing, damaged, checked);
            CREATE TABLE bricktracker_individual_minifigure_parts(id, part, color,
                spare, quantity, missing, damaged, checked);
            INSERT INTO bricktracker_sets VALUES ('copy', '100-1');
            INSERT INTO bricktracker_wishes VALUES ('100-1'), ('200-1'), ('absent-1');
            INSERT INTO rebrickable_parts VALUES
                ('direct', 0, 'p1', 11), ('fallback', 0, NULL, NULL),
                ('badcolor', 0, 'p1', 5), ('absent', 0, 'gone', 11),
                ('zero', 99, 'p1', 0), ('invalid_direct', 0, 'gone', NULL);
            INSERT INTO bricktracker_minifigures VALUES
                ('copy', 'direct', 2), ('copy', 'reverse', 1),
                ('copy', 'ambiguous', 1), ('copy', 'absent', 1),
                ('copy', 'unknown', 1), ('copy', 'untrusted', 1);
            INSERT INTO bricktracker_individual_minifigures VALUES ('loose', 'direct', 3);
            INSERT INTO bricktracker_individual_parts VALUES ('lot', 'fallback', 0, 4, 2, 1, 1);
            INSERT INTO bricktracker_individual_minifigure_parts
                VALUES ('loose', 'direct', 0, 0, 2, 1, 0, 1);
        ''')
        db.executemany('INSERT INTO bricktracker_parts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                       [('copy', None, part, color, 0, 2, 1, 1, 1, 123, 456)
                        for part, color in [('direct', 0), ('fallback', 0), ('unknown', 0),
                                            ('ambiguous', 0), ('badcolor', 0), ('absent', 0),
                                            ('direct', 1), ('direct', 2), ('zero', 99),
                                            ('invalid_direct', 0), ('fallback_absent', 0)]])
    with sqlite3.connect(web) as db:
        db.executescript('''
            CREATE TABLE color_map(bricklink_color_id, color_id);
            CREATE TABLE part_resolutions(bricklink, parts);
            CREATE TABLE minifig_bricklink(figure, bricklink_id, source);
            CREATE TABLE bricklink_figures(bricklink_id, figure, state);
            CREATE TABLE minifig_missing(copy_id, figure, missing);
            INSERT INTO color_map VALUES (11, 0), (5, 1), (6, 1), (0, 99);
            INSERT INTO minifig_bricklink VALUES
                ('direct', 'm1', 'manual'), ('absent', 'missing_m', 'match');
            INSERT INTO bricklink_figures VALUES
                ('m2', 'reverse', 'matched'), ('m1', 'ambiguous', 'matched'),
                ('m2', 'ambiguous', 'manual'), ('m2', 'direct', 'matched'),
                ('m1', 'untrusted', 'ambiguous');
            INSERT INTO minifig_missing VALUES
                ('copy', 'direct', 1), ('orphan', 'unknown', 2);
        ''')
        db.executemany('INSERT INTO part_resolutions VALUES (?, ?)',
                       [('p2', json.dumps([{'part_num': 'fallback'}, {'part_num': 'ambiguous'},
                                           {'part_num': 'fallback'}])),
                        ('p1', json.dumps([{'part_num': 'ambiguous'}, {'part_num': 'invalid_direct'}])),
                        ('gone', json.dumps([{'part_num': 'fallback_absent'}]))])
    with sqlite3.connect(catalog) as db:
        db.executescript('''
            CREATE TABLE items(item_type, item_no, name DEFAULT 'Catalogue name');
            INSERT INTO items(item_type, item_no) VALUES ('P', 'p1'), ('P', 'p2'), ('M', 'm1'), ('M', 'm2'),
                ('S', '100-1'), ('S', '200-1'), ('M', 'gone'), ('P', 'absent-1'),
                ('P', 'missing_m');
        ''')
    return app, web, catalog


def test_parts_and_colours(databases):
    result = match(*databases)
    rows = {(r['part'], r['color']): r for r in result['parts']}
    assert rows['direct', 0]['method'] == 'rebrickable_parts'
    assert rows['direct', 0]['status'] == 'matched'
    assert rows['direct', 0]['bricklink_item_no'] == 'p1'
    assert rows['direct', 0]['bricklink_color_id'] == 11
    assert rows['zero', 99]['bricklink_color_id'] == 0
    assert rows['zero', 99]['status'] == 'matched'
    assert rows['fallback', 0]['method'] == 'part_resolutions'
    assert rows['fallback', 0]['bricklink_item_no'] == 'p2'
    assert rows['fallback', 0]['status'] == 'matched'
    for key, status, reason in [
        (('unknown', 0), 'unmatched', 'no part mapping'),
        (('ambiguous', 0), 'conflict', 'ambiguous part resolution'),
        (('badcolor', 0), 'conflict', 'part colour disagrees with color_map'),
        (('absent', 0), 'unmatched', 'not in BrickLink catalogue'),
        (('direct', 1), 'conflict', 'ambiguous colour mapping'),
        (('direct', 2), 'unmatched', 'no colour mapping'),
        (('invalid_direct', 0), 'unmatched', 'not in BrickLink catalogue'),
        (('fallback_absent', 0), 'unmatched', 'not in BrickLink catalogue'),
    ]:
        assert (rows[key]['status'], rows[key]['reason']) == (status, reason)
    assert rows['badcolor', 0]['part_bricklink_color_id'] == 5
    assert rows['badcolor', 0]['bricklink_color_id'] == 11
    assert json.loads(rows['direct', 1]['color_candidates']) == [5, 6]
    assert json.loads(rows['ambiguous', 0]['item_candidates']) == ['p1', 'p2']
    assert len(result['colours']) == 4
    assert len(result['parts']) == 11
    with sqlite3.connect(databases[0]) as db:
        db.execute("UPDATE rebrickable_parts SET bricklink_color_id=NULL WHERE part='direct'")
    direct = next(r for r in match(*databases)['parts']
                  if r['part'] == 'direct' and r['color'] == 0)
    assert (direct['status'], direct['bricklink_color_id']) == ('matched', 11)


def test_figures_sets_and_state(databases):
    result = match(*databases)
    figures = {r['figure']: r for r in result['minifigures'] if r['source'] == 'copy'}
    assert figures['direct']['bricklink_item_no'] == 'm1'
    assert figures['direct']['method'] == 'minifig_bricklink'
    assert figures['direct']['missing'] == 1
    assert figures['reverse']['method'] == 'bricklink_figures'
    assert figures['reverse']['status'] == 'matched'
    assert figures['ambiguous']['reason'] == 'ambiguous minifigure mapping'
    assert figures['absent']['reason'] == 'not in BrickLink catalogue'
    assert figures['unknown']['reason'] == 'no minifigure mapping'
    assert figures['untrusted']['reason'] == 'no minifigure mapping'
    orphan = next(r for r in result['minifigures'] if r['id'] == 'orphan')
    assert (orphan['missing'], orphan['quantity'], orphan['source']) == (2, None, 'missing_figure')
    assert len(result['minifigures']) == 8
    sets = {r['set']: r for r in result['sets']}
    assert (sets['100-1']['owned'], sets['100-1']['wanted']) == (1, 1)
    assert sets['200-1']['status'] == 'matched'
    assert sets['absent-1']['reason'] == 'not in BrickLink catalogue'
    assert len(result['loose_parts']) == 2
    assert result['summary']['parts']['matched_by_method'] == {
        'part_resolutions': 1, 'rebrickable_parts': 2}
    state = result['summary']['user_state']
    assert state['minifig_missing']['total'] == 2
    assert state['minifig_missing']['matched'] == 1
    assert state['missing>0']['parts']['total'] == 11
    assert state['checked=1']['loose_parts']['matched'] == 2
    assert result['parts'][0]['damaged'] == 1
    assert all(r['element'] == 123 and r['rebrickable_inventory'] == 456
               for r in result['parts'])


def test_readonly_inputs(databases, tmp_path):
    before = [hashlib.sha256(p.read_bytes()).digest() for p in databases]
    nonexistent = tmp_path / 'nonexistent.db'
    with pytest.raises(sqlite3.OperationalError):
        open_readonly(nonexistent)
    assert not nonexistent.exists()
    db = open_readonly(databases[0])
    try:
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            db.execute('CREATE TABLE forbidden(value)')
    finally:
        db.close()
    assert before == [hashlib.sha256(p.read_bytes()).digest() for p in databases]
    match(*databases)
    assert before == [hashlib.sha256(p.read_bytes()).digest() for p in databases]


def test_failure_examples_are_bounded_and_ids_only(databases):
    with sqlite3.connect(databases[0]) as db:
        db.executemany('INSERT INTO bricktracker_individual_parts VALUES (?, ?, ?, ?, ?, ?, ?)',
                       [(str(i), 'unknown', 0, 1, 0, 0, 0) for i in range(15)])
    reason = match(*databases)['summary']['loose_parts']['reasons'][0]
    assert reason['count'] == 15
    assert len(reason['examples']) == 10
    assert all(set(row) == {'source', 'id', 'set', 'part', 'color'} for row in reason['examples'])
