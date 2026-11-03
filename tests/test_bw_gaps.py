"""The gaps of copies as a BrickLink Wanted List on the 4.0 store (M.8d, issue #110): named by `items.bricklink_key`, unidentified lines skipped and listed."""
import xml.etree.ElementTree as ET

import pytest

from brickwork.core import gaps
from tests.app4 import coll, pair, world  # noqa: F401 (fixtures)


def lines_of(xml):
    return [{child.tag: child.text for child in item} for item in ET.fromstring(xml)]


def test_gaps_are_combined_and_named_for_bricklink(world, coll):
    w, db = world, coll.db
    coll.mark(w.copy_a, '3001', '4', missing=3, damaged=1)                    # 3 missing + 1 damaged: four to replace
    coll.mark(w.copy_a, '3023', '15', missing=1)
    coll.mark_figure(w.copy_a, 'fig-000004', missing=1)
    coll.mark(w.copy_b, '3001', '4', missing=2)                               # copy B is new: its own condition
    out = gaps.export(db, [w.copy_a, w.copy_b])
    assert out['skipped'] == []
    assert lines_of(out['xml']) == [
        {'ITEMTYPE': 'P', 'ITEMID': '3001', 'COLOR': '5', 'MINQTY': '2', 'CONDITION': 'N'},
        {'ITEMTYPE': 'P', 'ITEMID': '3001', 'COLOR': '5', 'MINQTY': '4', 'CONDITION': 'U'},
        {'ITEMTYPE': 'P', 'ITEMID': '3023', 'COLOR': '1', 'MINQTY': '1', 'CONDITION': 'U'},
        {'ITEMTYPE': 'M', 'ITEMID': 'syn-fig-0004', 'MINQTY': '1', 'CONDITION': 'U'}]
    assert [l['bricklink'] for l in out['lines']][:1] == [('P', '3001', '5')]
    assert out['xml'].startswith(b"<?xml version='1.0' encoding='utf-8'?>")


def test_spares_figure_parts_and_retired_lines_are_no_gaps(world, coll):
    w, db = world, coll.db
    coll.mark(w.copy_a, '3001', '4', missing=0)
    coll.sql('UPDATE copy_part SET missing=1 WHERE copy_id=? AND is_spare=1', (w.copy_a,))                       # a missing spare is nobody's gap
    coll.sql('UPDATE copy_part SET missing=1 WHERE copy_id=? AND copy_figure_id IS NOT NULL', (w.copy_a,))       # nor a figure's own part
    assert gaps.copy_gaps(db, [w.copy_a]) == []
    coll.sql('UPDATE copy_part SET missing=0, damaged=0 WHERE copy_id=?', (w.copy_a,))
    coll.sql('UPDATE copy_part SET missing=1 WHERE copy_id=? AND copy_figure_id IS NULL AND is_spare=0', (w.copy_a,))
    coll.sql("UPDATE copy_part SET retired_at='2026-10-27T00:00:00.000Z' WHERE copy_id=?", (w.copy_a,))
    assert gaps.copy_gaps(db, [w.copy_a]) == []                                # a retired line is no line


def test_an_unidentified_item_is_skipped_and_listed_not_exported(world, coll):
    w, db = world, coll.db
    mystery = coll.local('part', 'Mystery part')                              # no number from any provider
    coll.sql('INSERT INTO copy_part(copy_id,item_id,color_id,quantity,missing) VALUES(?,?,?,3,2)', (w.copy_a, mystery, w.red))
    coll.mark(w.copy_a, '3001', '4', missing=1)
    out = gaps.export(db, [w.copy_a])
    assert [l['ITEMID'] for l in lines_of(out['xml'])] == ['3001']
    assert [(s['item_id'], s['name'], s['quantity'], s['why']) for s in out['skipped']] == [(mystery, 'Mystery part', 2, 'no BrickLink number')]
    # a BrickLink-born local part is named by its own BrickLink number
    local = coll.local('part', 'Only on BrickLink', born_key='x999')
    coll.sql('INSERT INTO copy_part(copy_id,item_id,color_id,quantity,missing) VALUES(?,?,?,1,1)', (w.copy_b, local, w.red))
    assert [l['ITEMID'] for l in lines_of(gaps.export(db, [w.copy_b])['xml'])] == ['x999']


def test_a_colour_with_no_bricklink_number_is_skipped_and_listed(world, coll):
    w, db = world, coll.db
    coll.sql("INSERT INTO color(id,origin,name,rgb,is_trans,born_provider,born_key,created_at,updated_at) VALUES(90001,'catalogue','Syn Colour','112233',0,'rebrickable','90001','2026-10-27T00:00:00.000Z','2026-10-27T00:00:00.000Z')")
    coll.sql('INSERT INTO copy_part(copy_id,item_id,color_id,quantity,missing) VALUES(?,?,?,1,1)', (w.copy_b, w.brick, 90001))
    out = gaps.export(db, [w.copy_b])
    assert lines_of(out['xml']) == [] and [(s['color_name'], s['why']) for s in out['skipped']] == [('Syn Colour', 'no BrickLink colour')]


def test_the_copies_asked_for_must_be_live_and_distinct(world, coll):
    w, db = world, coll.db
    for bad in ([], 'x', [w.copy_a, w.copy_a], ['nope'], [w.copy_a, 'nope']):
        with pytest.raises(ValueError):
            gaps.export(db, bad)
    coll.sql("UPDATE copy SET archived_at='2026-10-27T00:00:00.000Z' WHERE id=?", (w.copy_b,))
    with pytest.raises(ValueError, match='unavailable'):
        gaps.export(db, [w.copy_b])
    assert gaps.export(db, [w.copy_c])['lines'] == []                           # no gaps: an empty list, not an error
