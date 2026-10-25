"""Materialising a copy (design 4.3, 4.5; issue #108, M.6a): the picker's choices and preselection, each choice, figures from their
own lists, quantities, digests, the one receipt event and the all-or-nothing transaction. Invented data, no network."""
from contextlib import closing
import json
import sqlite3

import pytest

from brickwork.store4 import copies, fetched, identity
from brickwork.store4.audit import Events
from brickwork.store4.bldigest import inventory_digest
from brickwork.store4.connect import connect
from brickwork.store4.errors import CatalogueError, CatalogueMismatch, Store4Error
from tests.store4_fixtures import pair

SET, NEWER_SET = 10, 21                          # 6081-1 (two catalogue versions) and a set the catalogue has no list for
FIG_A, FIG_B, FIG_C = 30, 31, 32                 # A: catalogue list; B: only a fetched Rebrickable list; C: no list anywhere
KEYS = ('CONSUMER_KEY', 'CONSUMER_SECRET', 'TOKEN_VALUE', 'TOKEN_SECRET')


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv('BW_BRICKLINK_' + k, raising=False)


@pytest.fixture
def key(monkeypatch):
    for k in KEYS:
        monkeypatch.setenv('BW_BRICKLINK_' + k, 'x')


def add_catalogue(cat):
    """Set 10 with versions 1 and 2 (3 figure lines on v2), figures 30-32, set 21 without any list."""
    with closing(sqlite3.connect(cat)) as c:
        for i, kind, ns, key in ((FIG_A, 'minifigure', 'minifigs', 'fig-001'), (FIG_B, 'minifigure', 'minifigs', 'fig-002'),
                                 (FIG_C, 'minifigure', 'minifigs', 'fig-003'), (NEWER_SET, 'set', 'sets', '7777-1')):
            c.execute("INSERT INTO item(id, kind, kind_source, name, name_key, size_key, year, num_parts, build_id, born_provider, born_namespace,"
                      " born_key, digest) VALUES(?, ?, 'namespace', ?, ?, '', 1993, 4, 1, 'rebrickable', ?, ?, 'd')", (i, kind, key, key, ns, key))

        def inventory(inv, item, version, latest, parts, figs=()):
            digest = inventory_digest(parts, figs)
            c.execute("INSERT INTO inventory VALUES(?, ?, ?, ?, ?, NULL, 1, ?, NULL, ?, ?, 0, NULL)",
                      (inv, item, version, version, latest, digest, len(parts), len(figs)))
            c.executemany('INSERT INTO inventory_part VALUES(?, ?, ?, ?, ?)', [(inv, *p) for p in parts])
            c.executemany('INSERT INTO inventory_figure VALUES(?, ?, ?)', [(inv, *f) for f in figs])

        inventory(1, SET, 1, 0, [(11, 3, 0, 4)])
        inventory(2, SET, 2, 1, [(11, 3, 0, 5), (11, 4, 1, 1), (12, 4, 0, 2)], [(FIG_A, 2), (FIG_B, 1)])
        inventory(3, FIG_A, 1, 1, [(16, 4, 0, 1), (17, 5, 0, 2), (16, 3, 1, 1)])
        c.commit()


@pytest.fixture
def db(tmp_path):
    col, cat = pair(tmp_path)
    add_catalogue(cat)
    with closing(connect(col, cat)) as conn:
        yield conn


def q(db, sql, *args):
    return [tuple(r) for r in db.execute(sql, args)]


def fetch(db, item, source, parts, figures=()):
    """Store a fetched list; its items are projected first, as the adapters do."""
    with db:
        for i in [item, *(p[0] for p in parts), *(f[0] for f in figures)]:
            identity.project(db, i)
        for c in {p[1] for p in parts}:
            identity.project_color(db, c)
        return fetched.write_fetched(db, item, source, parts, figures)


def add(db, choice=None, item=SET, **kw):
    return copies.create_copy(db, item, choice or {'source': 'rebrickable', 'version': 2}, via='cli', actor='t', **kw)


# ---------- the picker ----------

def test_picker_lists_the_versions_and_preselects_the_latest(db):
    r = copies.part_list_choices(db, SET)
    assert [v['label'] for v in r['rebrickable']] == ['Version 1 of 2', 'Version 2 of 2, latest']
    assert (r['bricklink'], r['rebrickable_api'], r['needs_choice']) == (None, None, True)
    assert r['preselected'] == {'source': 'rebrickable', 'version': 2}


def test_no_choice_is_shown_for_a_set_with_one_list_and_no_key(db):
    fetch(db, NEWER_SET, 'rebrickable_api', [(11, 3, 0, 2)])
    assert copies.part_list_choices(db, NEWER_SET)['needs_choice'] is False


def test_a_key_offers_bricklink_and_says_whether_a_list_is_fetched(db, key):
    r = copies.part_list_choices(db, SET)
    assert r['bricklink'] == {'fetched_inventory_id': None}
    assert r['preselected'] == {'source': 'rebrickable', 'version': 2}              # offered, not preselected
    fid = fetch(db, SET, 'bricklink', [(11, 3, 0, 5)])
    assert copies.part_list_choices(db, SET)['bricklink'] == {'fetched_inventory_id': fid}


def test_bricklink_is_never_offered_without_a_key(db):
    fetch(db, SET, 'bricklink', [(11, 3, 0, 5)])
    assert copies.part_list_choices(db, SET)['bricklink'] is None


def set_preference(db, source, version=None):
    with db:
        identity.project(db, SET)
        db.execute("INSERT OR REPLACE INTO set_preference VALUES(?, ?, ?, '2026-10-25T00:00:00Z')", (SET, source, version))


def set_global(db, value):
    with db:
        db.execute("INSERT OR REPLACE INTO setting VALUES('prefer_bricklink_inventory', ?)", (value,))


def test_preselection_tier_one_is_the_sets_own_preference(db, key):
    set_global(db, 'true')
    set_preference(db, 'rebrickable', 1)
    assert copies.part_list_choices(db, SET)['preselected'] == {'source': 'rebrickable', 'version': 1}      # beats the global switch
    set_preference(db, 'bricklink')
    set_global(db, 'false')
    assert copies.part_list_choices(db, SET)['preselected'] == {'source': 'bricklink'}
    set_preference(db, 'rebrickable', None)                                         # "the latest" pinned as no version
    assert copies.part_list_choices(db, SET)['preselected'] == {'source': 'rebrickable', 'version': 2}


def test_a_bricklink_preference_needs_the_key_and_then_the_next_tier_decides(db, monkeypatch):
    set_preference(db, 'bricklink')
    assert copies.part_list_choices(db, SET)['preselected'] == {'source': 'rebrickable', 'version': 2}
    set_global(db, 'true')
    assert copies.part_list_choices(db, SET)['preselected'] == {'source': 'rebrickable', 'version': 2}      # no key: no effect
    for k in KEYS:
        monkeypatch.setenv('BW_BRICKLINK_' + k, 'x')
    assert copies.part_list_choices(db, SET)['preselected'] == {'source': 'bricklink'}


def test_preselection_tier_two_is_the_global_switch_only_with_a_key(db, key, monkeypatch):
    set_global(db, 'true')
    assert copies.part_list_choices(db, SET)['preselected'] == {'source': 'bricklink'}
    set_global(db, 'false')
    assert copies.part_list_choices(db, SET)['preselected'] == {'source': 'rebrickable', 'version': 2}


def test_a_pinned_version_the_catalogue_no_longer_has_falls_back_to_the_latest(db):
    set_preference(db, 'rebrickable', 9)
    assert copies.part_list_choices(db, SET)['preselected'] == {'source': 'rebrickable', 'version': 2}


def test_a_set_newer_than_the_catalogue_is_offered_its_fetched_rebrickable_list(db):
    assert copies.part_list_choices(db, NEWER_SET)['preselected'] is None
    fid = fetch(db, NEWER_SET, 'rebrickable_api', [(11, 3, 0, 2)])
    r = copies.part_list_choices(db, NEWER_SET)
    assert r['rebrickable'] == [] and r['rebrickable_api']['fetched_inventory_id'] == fid
    assert r['preselected'] == {'source': 'rebrickable_api'}


def test_a_fetched_bricklink_list_is_preselected_when_it_is_the_only_list(db, key):
    fetch(db, NEWER_SET, 'bricklink', [(11, 3, 0, 2)])
    r = copies.part_list_choices(db, NEWER_SET)
    assert r['preselected'] == {'source': 'bricklink'} and not r['needs_choice']


# ---------- each choice ----------

def lines(db, copy_id):
    return q(db, '''SELECT coalesce(f.item_id, 0), p.item_id, p.color_id, p.is_spare, p.quantity FROM copy_part p
                    LEFT JOIN copy_figure f ON f.id=p.copy_figure_id WHERE p.copy_id=? ORDER BY 1, 2, 3, 4''', copy_id)


def test_a_rebrickable_version_copies_the_catalogue_lines_and_its_digest(db):
    r = add(db)
    cid = r['copy']['id']
    assert q(db, 'SELECT item_id, inventory_source, inventory_version, fetched_inventory_id, inventory_digest, pinned FROM copy') == [
        (SET, 'rebrickable', 2, None, q(db, 'SELECT digest FROM catalogue.inventory WHERE item_id=? AND version=2', SET)[0][0], 0)]
    assert [l for l in lines(db, cid) if l[0] == 0] == [(0, 11, 3, 0, 5), (0, 11, 4, 1, 1), (0, 12, 4, 0, 2)]
    assert q(db, 'SELECT count(*) FROM copy_part WHERE copy_figure_id IS NULL')[0][0] == 3
    assert q(db, 'SELECT inventory_pending, pending_job_id FROM copy') == [(None, None)]


def test_an_older_version_is_copied_when_chosen(db):
    cid = add(db, {'source': 'rebrickable', 'version': 1})['copy']['id']
    assert lines(db, cid) == [(0, 11, 3, 0, 4)]
    assert q(db, 'SELECT inventory_version FROM copy') == [(1,)]
    assert q(db, 'SELECT count(*) FROM copy_figure') == [(0,)]


def test_rebrickable_without_a_version_is_the_latest(db):
    add(db, {'source': 'rebrickable'})
    assert q(db, 'SELECT inventory_version FROM copy') == [(2,)]


def test_the_copy_digest_equals_the_digest_of_its_own_set_lines(db):
    cid = add(db)['copy']['id']
    parts = [(i, c, s, n) for _, i, c, s, n in lines(db, cid) if _ == 0]
    figs = q(db, 'SELECT item_id, quantity FROM copy_figure WHERE copy_id=?', cid)
    assert inventory_digest(parts, figs) == q(db, 'SELECT inventory_digest FROM copy')[0][0]


def test_a_fetched_rebrickable_list_for_a_set_newer_than_the_catalogue(db):
    fid = fetch(db, NEWER_SET, 'rebrickable_api', [(11, 3, 0, 2), (12, 4, 1, 1)])
    cid = add(db, {'source': 'rebrickable_api'}, item=NEWER_SET)['copy']['id']
    assert q(db, 'SELECT inventory_source, inventory_version, fetched_inventory_id, inventory_digest FROM copy') == [
        ('rebrickable_api', None, fid, q(db, 'SELECT digest FROM main.fetched_inventory WHERE id=?', fid)[0][0])]
    assert lines(db, cid) == [(0, 11, 3, 0, 2), (0, 12, 4, 1, 1)]


def test_the_latest_fetched_bricklink_list_is_used_and_nothing_is_queued(db, key):
    fetch(db, SET, 'bricklink', [(11, 3, 0, 1)])
    latest = fetch(db, SET, 'bricklink', [(11, 3, 0, 7), (11, 3, 1, 2), (12, 4, 0, 1)])
    cid = add(db, {'source': 'bricklink'})['copy']['id']
    assert q(db, 'SELECT inventory_source, inventory_version, fetched_inventory_id, inventory_pending, pending_job_id FROM copy') == [
        ('bricklink', None, latest, None, None)]
    assert q(db, 'SELECT inventory_digest FROM copy') == q(db, 'SELECT digest FROM main.fetched_inventory WHERE id=?', latest)
    assert lines(db, cid) == [(0, 11, 3, 0, 7), (0, 11, 3, 1, 2), (0, 12, 4, 0, 1)]
    assert q(db, 'SELECT count(*) FROM job') == [(0,)]


def test_bricklink_with_nothing_fetched_is_refused_for_now_and_writes_nothing(db, key):
    with pytest.raises(copies.BrickLinkPending):
        add(db, {'source': 'bricklink'})
    assert q(db, 'SELECT (SELECT count(*) FROM copy), (SELECT count(*) FROM event), (SELECT count(*) FROM job)') == [(0, 0, 0)]


def test_bricklink_is_refused_without_a_key(db):
    fetch(db, SET, 'bricklink', [(11, 3, 0, 5)])
    with pytest.raises(Store4Error, match='key'):
        add(db, {'source': 'bricklink'})


@pytest.mark.parametrize('choice', [{'source': 'rebrickable', 'version': 9}, {'source': 'rebrickable_api'}, {'source': 'nope'}])
def test_a_choice_the_set_cannot_serve_is_refused(db, choice):
    with pytest.raises(Store4Error):
        add(db, choice)
    assert q(db, 'SELECT count(*) FROM copy') == [(0,)]


# ---------- figures ----------

def test_each_figure_line_has_its_own_list_and_its_parts_are_multiplied(db):
    fetch(db, FIG_B, 'rebrickable_api', [(17, 5, 0, 3)])
    cid = add(db)['copy']['id']                                                     # FIG_A x2 from the catalogue, FIG_B x1 fetched
    got = q(db, 'SELECT item_id, inventory_source, inventory_version, fetched_inventory_id IS NOT NULL, inventory_digest IS NOT NULL, quantity FROM copy_figure ORDER BY item_id')
    assert got == [(FIG_A, 'rebrickable', 1, 0, 1, 2), (FIG_B, 'rebrickable_api', None, 1, 1, 1)]
    assert [l for l in lines(db, cid) if l[0] == FIG_A] == [(FIG_A, 16, 3, 1, 2), (FIG_A, 16, 4, 0, 2), (FIG_A, 17, 5, 0, 4)]    # spare kept, x2
    assert [l for l in lines(db, cid) if l[0] == FIG_B] == [(FIG_B, 17, 5, 0, 3)]
    assert q(db, 'SELECT inventory_digest FROM copy_figure WHERE item_id=?', FIG_A) == q(db, 'SELECT digest FROM catalogue.inventory WHERE item_id=?', FIG_A)


def test_a_figure_without_any_rebrickable_list_is_none_with_no_part_lines(db):
    cid = add(db)['copy']['id']                                                     # FIG_B has no list at all here
    assert q(db, 'SELECT inventory_source, inventory_version, fetched_inventory_id, inventory_digest FROM copy_figure WHERE item_id=?', FIG_B) == [
        ('none', None, None, None)]
    assert [l for l in lines(db, cid) if l[0] == FIG_B] == []


def test_a_bricklink_set_list_still_takes_its_figure_parts_from_the_figures_own_rebrickable_list(db, key):
    fetch(db, FIG_B, 'rebrickable_api', [(17, 5, 0, 1)])
    fetch(db, SET, 'bricklink', [(11, 3, 0, 4)], [(FIG_A, 3), (FIG_B, 1), (FIG_C, 2)])
    cid = add(db, {'source': 'bricklink'})['copy']['id']
    assert q(db, 'SELECT item_id, inventory_source, quantity FROM copy_figure ORDER BY item_id') == [
        (FIG_A, 'rebrickable', 3), (FIG_B, 'rebrickable_api', 1), (FIG_C, 'none', 2)]
    assert [l for l in lines(db, cid) if l[0] == FIG_A] == [(FIG_A, 16, 3, 1, 3), (FIG_A, 16, 4, 0, 3), (FIG_A, 17, 5, 0, 6)]
    assert [l for l in lines(db, cid) if l[0] == FIG_C] == []
    assert q(db, 'SELECT count(*) FROM copy_part WHERE copy_figure_id IS NULL') == [(1,)]


def test_the_same_part_in_the_set_and_in_a_figure_stays_two_rows(db):
    cid = add(db)['copy']['id']
    assert q(db, 'SELECT count(*) FROM copy_part WHERE copy_id=? AND item_id=16 AND color_id=4', cid) == [(1,)]
    fetch(db, SET, 'rebrickable_api', [(16, 4, 0, 9)], [(FIG_A, 1)])
    cid2 = add(db, {'source': 'rebrickable_api'})['copy']['id']
    assert q(db, 'SELECT count(*) FROM copy_part WHERE copy_id=? AND item_id=16 AND color_id=4', cid2) == [(2,)]


def test_lines_of_quantity_zero_are_not_in_the_target():
    t = copies.Target(1, 'rebrickable', 1, None, 'd', {(11, 3, 0): 0, (12, 3, 0): 2},
                      [copies.FigureTarget(5, 0, 'rebrickable', parts={(16, 4, 0): 1}), copies.FigureTarget(6, 2, 'rebrickable', parts={(16, 4, 0): 0})])
    assert t.lines() == {(None, 12, 3, 0): 2}


def test_the_target_is_the_line_set_a_switch_needs_and_writes_nothing(db):
    before = q(db, 'SELECT (SELECT count(*) FROM copy), (SELECT count(*) FROM main.item)')
    t = copies.build_target(db, SET, {'source': 'rebrickable', 'version': 2})
    assert t.lines()[(None, 11, 3, 0)] == 5 and t.lines()[(FIG_A, 17, 5, 0)] == 4
    assert q(db, 'SELECT (SELECT count(*) FROM copy), (SELECT count(*) FROM main.item)') == before


# ---------- receipt and transaction ----------

def test_one_receipt_event_holds_the_rows_written(db):
    fetch(db, FIG_B, 'rebrickable_api', [(17, 5, 0, 3)])
    n = q(db, 'SELECT count(*) FROM event')[0][0]
    r = add(db)
    cid = r['copy']['id']
    ev = q(db, "SELECT via, actor, entity_kind, entity_id, field, old_value, new_value FROM event WHERE id>(SELECT max(id)-1 FROM event)")
    assert q(db, 'SELECT count(*) FROM event')[0][0] == n + 1
    via, actor, kind, eid, field, old, new = ev[0]
    assert (via, actor, kind, eid, field, old) == ('cli', 't', 'copy', cid, 'add', None)
    assert json.loads(new) == json.loads(json.dumps(r))
    assert sorted(x[0] for x in json.loads(new)['parts']['rows']) == [x[0] for x in q(db, 'SELECT id FROM copy_part WHERE copy_id=? ORDER BY id', cid)]
    assert [f['item_id'] for f in json.loads(new)['figures']] == [FIG_A, FIG_B]


def test_a_failure_anywhere_rolls_the_whole_copy_back(db, monkeypatch):
    def boom(self, *a, **k):
        raise RuntimeError('event write failed')
    monkeypatch.setattr(Events, 'write', boom)
    with pytest.raises(RuntimeError):
        add(db)
    assert q(db, 'SELECT (SELECT count(*) FROM copy), (SELECT count(*) FROM copy_figure), (SELECT count(*) FROM copy_part)') == [(0, 0, 0)]
    assert not db.in_transaction


def test_a_constraint_failure_midway_leaves_nothing(db, monkeypatch):
    real = copies._project
    def bad(db, target):
        real(db, target)
        db.execute("UPDATE main.item SET kind='part' WHERE id=?", (target.item_id,))        # the copy guard now refuses the set
    monkeypatch.setattr(copies, '_project', bad)
    with pytest.raises(sqlite3.DatabaseError):
        add(db)
    assert q(db, 'SELECT (SELECT count(*) FROM copy), (SELECT count(*) FROM copy_part), (SELECT count(*) FROM event)') == [(0, 0, 0)]


def test_items_and_colours_are_projected_and_copies_are_independent(db):
    a, b = add(db)['copy']['id'], add(db)['copy']['id']
    assert a != b
    assert q(db, 'SELECT count(*) FROM main.item WHERE id IN (10, 11, 12, 16, 17, 30, 31)') == [(7,)]
    assert len(lines(db, a)) == len(lines(db, b)) and q(db, 'SELECT count(*) FROM event WHERE field=?', 'add') == [(2,)]


def test_optional_copy_fields_are_stored(db):
    add(db, condition='used', completeness='incomplete', note='box missing')
    assert q(db, 'SELECT condition, completeness, completeness_source, note FROM copy') == [('used', 'incomplete', 'manual', 'box missing')]


# ---------- the catalogue boundary ----------

def test_a_catalogue_the_collection_has_moved_past_is_refused_before_any_write(db):
    with db:
        db.execute("INSERT INTO main.catalogue_build VALUES(99, 'x', NULL, '2026-10-25', NULL, '{}')")   # activated elsewhere
    with pytest.raises(CatalogueMismatch):
        add(db)
    assert q(db, 'SELECT count(*) FROM copy') == [(0,)]


def test_a_part_list_from_a_build_not_yet_activated_is_refused(tmp_path):
    col, cat = pair(tmp_path)
    add_catalogue(cat)
    with closing(sqlite3.connect(cat)) as c:
        c.execute("INSERT INTO build(id, kind, started_at, app_version, files_json, counts_json) VALUES(50, 'rebrickable_dump', 'x', '4.0', '[]', '{}')")
        c.execute('UPDATE inventory SET build_id=50 WHERE id=3')                    # FIG_A's list, rebuilt and not activated
        c.commit()
    with closing(connect(col, cat)) as db:
        with pytest.raises(CatalogueError, match='not activated'):
            add(db)
        assert q(db, 'SELECT count(*) FROM copy') == [(0,)]
