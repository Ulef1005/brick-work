"""'Part list changed' (design 4.4 last paragraph, 4.2; issue #108, M.6d): which live copies and figure lines carry a list that
differs from the catalogue's after a re-download, for each source; the choice each entry offers really switches. Invented data."""
from contextlib import closing
import sqlite3

import pytest

from brickwork.store4 import copies
from brickwork.store4.bldigest import inventory_digest
from brickwork.store4.connect import connect
from tests.store4_fixtures import pair
from tests.test_store4_copies import FIG_A, FIG_B, NEWER_SET, SET, add, add_catalogue, fetch, key, no_key, q   # noqa: F401  (fixtures)
from tests.test_store4_switch import live, live_figures


class World:
    def __init__(self, db, cat):
        self.db, self.cat = db, cat

    def redownload(self, inventory, parts, figures=(), *, retire=False):
        """What a new dump does to one inventory: other lines, so another digest (or the version gone)."""
        with closing(sqlite3.connect(self.cat)) as c:
            if retire:
                c.execute('UPDATE inventory SET retired_at=? WHERE id=?', ('2026-10-25T00:00:00Z', inventory))
            else:
                c.execute('DELETE FROM inventory_part WHERE inventory_id=?', (inventory,))
                c.execute('DELETE FROM inventory_figure WHERE inventory_id=?', (inventory,))
                c.executemany('INSERT INTO inventory_part VALUES(?, ?, ?, ?, ?)', [(inventory, *p) for p in parts])
                c.executemany('INSERT INTO inventory_figure VALUES(?, ?, ?)', [(inventory, *f) for f in figures])
                c.execute('UPDATE inventory SET digest=? WHERE id=?', (inventory_digest(parts, figures), inventory))
            c.commit()

    def adopt(self, inventory, item, parts, figures=(), version=1):
        """The dump now holds a list for an item that had only a fetched one."""
        with closing(sqlite3.connect(self.cat)) as c:
            c.execute('INSERT INTO inventory VALUES(?, ?, ?, ?, 1, NULL, 1, ?, NULL, ?, ?, 0, NULL)',
                      (inventory, item, version, version, inventory_digest(parts, figures), len(parts), len(figures)))
            c.executemany('INSERT INTO inventory_part VALUES(?, ?, ?, ?, ?)', [(inventory, *p) for p in parts])
            c.commit()


@pytest.fixture
def world(tmp_path):
    col, cat = pair(tmp_path)
    add_catalogue(cat)
    with closing(connect(col, cat)) as conn:
        yield World(conn, cat)


V2 = [(11, 3, 0, 6), (11, 4, 1, 1), (12, 4, 0, 2)]            # version 2 with the red 3023 raised from 5 to 6
FIG_A_NEW = [(16, 4, 0, 1), (17, 5, 0, 3), (16, 3, 1, 1)]     # figure A with the 2339 raised from 2 to 3


def kinds(db, copy_id=None):
    return [(e['kind'], e['figure_item_id'], e['source']) for e in copies.part_list_changes(db, copy_id)]


def test_a_fresh_copy_has_no_change(world):
    add(world.db)
    assert copies.part_list_changes(world.db) == []
    assert copies.summarise_changes([]) == {'copies': 0, 'entries': 0, 'gone': 0, 'by_kind': {}}


def test_a_changed_catalogue_list_is_reported_with_the_choice_that_brings_it_up_to_date(world):
    cid = add(world.db)['copy']['id']
    other = add(world.db, {'source': 'rebrickable', 'version': 1})['copy']['id']
    world.redownload(2, V2, [(FIG_A, 2), (FIG_B, 1)])
    (e,) = copies.part_list_changes(world.db)
    assert (e['copy_id'], e['item_id'], e['kind'], e['source'], e['version'], e['figure_id']) == (cid, SET, 'changed', 'rebrickable', 2, None)
    assert e['current_digest'] != e['catalogue_digest'] and e['choice'] == {'source': 'rebrickable', 'version': 2}
    assert e['pending'] is None and kinds(world.db, other) == []
    assert copies.summarise_changes([e]) == {'copies': 1, 'entries': 1, 'gone': 0, 'by_kind': {'changed': 1}}
    preview = copies.preview_switch(world.db, cid, e['choice'])
    assert preview['same_list'] is False and preview['counts']['lines_update'] == 1
    copies.switch_part_list(world.db, cid, e['choice'], via='cli')                      # the entry's own choice brings it up to date
    assert copies.part_list_changes(world.db) == []
    assert (0, 11, 3, 0, 6) in live(world.db, cid)


def test_a_version_the_catalogue_dropped_is_gone_with_no_automatic_choice(world):
    cid = add(world.db)['copy']['id']
    world.redownload(2, [], retire=True)
    (e,) = copies.part_list_changes(world.db)
    assert (e['kind'], e['choice'], e['catalogue_digest']) == ('gone', None, None)
    with closing(sqlite3.connect(world.cat)) as c:                                    # missing altogether, not only retired
        c.execute('DELETE FROM inventory WHERE id=2')
        c.commit()
    assert kinds(world.db, cid) == [('gone', None, 'rebrickable')]
    copies.switch_part_list(world.db, cid, {'source': 'rebrickable', 'version': 1}, via='cli')    # the picker's way out
    assert copies.part_list_changes(world.db) == []


def test_a_changed_figure_list_alone_is_reported_and_the_copys_own_choice_re_takes_it(world):
    cid = add(world.db)['copy']['id']
    world.redownload(3, FIG_A_NEW)
    (e,) = copies.part_list_changes(world.db)
    assert (e['kind'], e['figure_item_id'], e['version'], e['choice']) == ('changed', FIG_A, 1, {'source': 'rebrickable', 'version': 2})
    assert e['figure_id'] is not None and e['item_id'] == SET
    preview = copies.preview_switch(world.db, cid, e['choice'])                       # the set's digest is equal: not NothingToSwitch
    assert preview['same_list'] is False and preview['counts']['figures_update'] == 1
    receipt = copies.switch_part_list(world.db, cid, e['choice'], via='cli')
    assert receipt['counts']['figures_update'] == 1 and (FIG_A, 17, 5, 0, 6) in live(world.db, cid)   # 2 figures x 3
    assert copies.part_list_changes(world.db) == []
    with pytest.raises(copies.NothingToSwitch):
        copies.switch_part_list(world.db, cid, e['choice'], via='cli')


def test_a_figure_line_whose_list_vanished_is_gone_and_a_gone_set_list_blocks_its_choice(world):
    cid = add(world.db)['copy']['id']
    world.redownload(3, [], retire=True)
    assert [(e['kind'], e['figure_item_id'], e['choice']) for e in copies.part_list_changes(world.db)] == \
           [('gone', FIG_A, {'source': 'rebrickable', 'version': 2})]
    world.redownload(2, [], retire=True)
    assert [(e['kind'], e['figure_item_id'], e['choice']) for e in copies.part_list_changes(world.db)] == \
           [('gone', None, None), ('gone', FIG_A, None)]


def test_a_rebrickable_api_copy_is_offered_the_catalogue_list_only_when_the_digest_differs(world, key):
    fetch(world.db, NEWER_SET, 'rebrickable_api', [(11, 3, 0, 2)])
    cid = add(world.db, {'source': 'rebrickable_api'}, item=NEWER_SET)['copy']['id']
    assert copies.part_list_changes(world.db) == []                                   # the catalogue does not have the set yet
    world.adopt(4, NEWER_SET, [(11, 3, 0, 2)])                                        # adopted with the same list: nothing to say
    assert copies.part_list_changes(world.db) == []
    world.redownload(4, [(11, 3, 0, 3)])
    (e,) = copies.part_list_changes(world.db)
    assert (e['kind'], e['source'], e['choice'], e['fetched_inventory_id']) == ('offered', 'rebrickable_api', {'source': 'rebrickable', 'version': 1}, 1)
    copies.switch_part_list(world.db, cid, e['choice'], via='cli')
    assert copies.part_list_changes(world.db) == [] and q(world.db, 'SELECT inventory_source FROM copy WHERE id=?', cid) == [('rebrickable',)]


def test_a_rebrickable_api_figure_the_catalogue_adopted_with_another_list_is_offered(world):
    fetch(world.db, FIG_B, 'rebrickable_api', [(16, 4, 0, 1)])
    cid = add(world.db)['copy']['id']
    assert q(world.db, 'SELECT inventory_source FROM copy_figure WHERE copy_id=? AND item_id=?', cid, FIG_B) == [('rebrickable_api',)]
    world.adopt(5, FIG_B, [(16, 4, 0, 1)])
    assert copies.part_list_changes(world.db) == []                                   # same list
    world.redownload(5, [(16, 4, 0, 2)])
    (e,) = copies.part_list_changes(world.db)
    assert (e['kind'], e['figure_item_id'], e['choice']) == ('offered', FIG_B, {'source': 'rebrickable', 'version': 2})
    copies.switch_part_list(world.db, cid, e['choice'], via='cli')                       # re-takes the figure from the catalogue
    assert copies.part_list_changes(world.db) == []
    assert q(world.db, 'SELECT inventory_source FROM copy_figure WHERE copy_id=? AND item_id=?', cid, FIG_B) == [('rebrickable',)]


def test_a_bricklink_copy_is_told_of_a_newer_fetched_list_with_another_digest(world, key):
    carried = fetch(world.db, SET, 'bricklink', [(11, 3, 0, 5)])
    cid = add(world.db, {'source': 'bricklink'})['copy']['id']
    fetch(world.db, SET, 'bricklink', [(11, 3, 0, 5)])                                # fetched again, nothing new in it
    assert copies.part_list_changes(world.db) == []
    newer = fetch(world.db, SET, 'bricklink', [(11, 3, 0, 7)])
    (e,) = copies.part_list_changes(world.db)
    assert (e['fetched_inventory_id'], e['newer_fetched_inventory_id']) == (carried, newer)   # what it carries, what it would take
    assert (e['kind'], e['source'], e['choice'], e['figure_id']) == ('newer_list', 'bricklink', {'source': 'bricklink'}, None)
    copies.switch_part_list(world.db, cid, e['choice'], via='cli')
    assert copies.part_list_changes(world.db) == []


def test_archived_copies_and_retired_figure_lines_are_not_reported_and_one_copy_can_be_asked(world):
    a, b = add(world.db)['copy']['id'], add(world.db)['copy']['id']
    world.redownload(2, V2, [(FIG_A, 2), (FIG_B, 1)])
    world.redownload(3, FIG_A_NEW)
    assert {e['copy_id'] for e in copies.part_list_changes(world.db)} == {a, b}
    assert len(copies.part_list_changes(world.db, a)) == 2 and {e['copy_id'] for e in copies.part_list_changes(world.db, a)} == {a}
    with world.db:
        world.db.execute("UPDATE copy SET archived_at='2026-10-25T00:00:00Z' WHERE id=?", (a,))
        world.db.execute('UPDATE copy_figure SET retired_at=? WHERE copy_id=? AND item_id=?', ('2026-10-25T00:00:00Z', b, FIG_A))
    assert kinds(world.db) == [('changed', None, 'rebrickable')]
    assert copies.part_list_changes(world.db, a) == []


def test_without_a_catalogue_only_the_bricklink_case_is_answered(tmp_path, key):
    col, cat = pair(tmp_path)
    add_catalogue(cat)
    with closing(connect(col, cat)) as db:
        fetch(db, SET, 'bricklink', [(11, 3, 0, 5)])
        add(db, {'source': 'bricklink'})
        fetch(db, SET, 'bricklink', [(11, 3, 0, 7)])
    with closing(connect(col, tmp_path / 'absent.db')) as db:
        assert [e['kind'] for e in copies.part_list_changes(db)] == ['newer_list']


def test_a_figure_that_got_a_new_catalogue_version_is_changed_since_copies_take_its_latest_list(world):
    cid = add(world.db)['copy']['id']
    with closing(sqlite3.connect(world.cat)) as c:
        c.execute('UPDATE inventory SET is_latest=0 WHERE id=3')                    # version 1 stays live, no longer the latest
        c.commit()
    world.adopt(10, FIG_A, FIG_A_NEW, version=2)
    (e,) = copies.part_list_changes(world.db)
    assert (e['kind'], e['figure_item_id'], e['version']) == ('changed', FIG_A, 1)
    copies.switch_part_list(world.db, cid, e['choice'], via='cli')
    assert q(world.db, 'SELECT inventory_version FROM copy_figure WHERE item_id=?', FIG_A) == [(2,)]
    assert copies.part_list_changes(world.db) == []


def test_a_figure_without_a_list_that_the_catalogue_now_has_is_changed(world, key):
    from tests.test_store4_copies import FIG_C
    fetch(world.db, SET, 'bricklink', [(11, 3, 0, 6)], [(FIG_C, 1)])
    cid = add(world.db, {'source': 'bricklink'})['copy']['id']
    assert copies.part_list_changes(world.db) == []
    world.adopt(11, FIG_C, [(16, 4, 0, 1)])
    (e,) = copies.part_list_changes(world.db)
    assert (e['kind'], e['figure_item_id'], e['choice']) == ('changed', FIG_C, {'source': 'bricklink'})
    copies.switch_part_list(world.db, cid, e['choice'], via='cli')
    assert q(world.db, 'SELECT inventory_source FROM copy_figure WHERE item_id=?', FIG_C) == [('rebrickable',)]
    assert copies.part_list_changes(world.db) == []


def test_a_fetched_figure_is_compared_with_its_latest_catalogue_list_not_the_version_its_reply_named(world):
    from brickwork.store4 import fetched, identity
    with world.db:
        for i in (FIG_B, 16):
            identity.project(world.db, i)
        identity.project_color(world.db, 4)
        fetched.write_fetched(world.db, FIG_B, 'rebrickable_api', [(16, 4, 0, 1)], provider_version=1)
    cid = add(world.db)['copy']['id']
    world.adopt(5, FIG_B, [(16, 4, 0, 1)], version=1)                                 # the reply's version, the same list
    with closing(sqlite3.connect(world.cat)) as c:
        c.execute('UPDATE inventory SET is_latest=0 WHERE id=5')
        c.commit()
    world.adopt(6, FIG_B, [(16, 4, 0, 2)], version=2)                                 # a newer version: what a switch takes
    (e,) = copies.part_list_changes(world.db)
    assert (e['kind'], e['figure_item_id']) == ('offered', FIG_B)
    copies.switch_part_list(world.db, cid, e['choice'], via='cli')
    assert q(world.db, 'SELECT inventory_source, inventory_version FROM copy_figure WHERE item_id=?', FIG_B) == [('rebrickable', 2)]
    assert copies.part_list_changes(world.db) == []
