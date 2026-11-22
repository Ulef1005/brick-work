"""#489: `copy.checked_by`, who checked a copy (schema 4.7, ADR 0038). A Rebrickable pull labels the copy that received it and only that copy, a check
or mark by hand takes the label off, Undo brings back what was there, the bar and the line follow, and the 4.6 file migrates with every copy NULL.
Invented data against the fake Rebrickable of test_bw_sync."""
from contextlib import closing
import json
import sqlite3
from pathlib import Path

import pytest

from brickwork.core import checker, collection, sync
from brickwork.core.sync import lost_parts
from brickwork.store4.connect import HERE, SCHEMA_VERSION, connect, upgrade
from tests.test_bw_sync import rebrickable_ready, store  # noqa: F401
from tests.test_bw_sync import pair  # noqa: F401
from tests.test_bw_sync_lost_parts import Remote, copy_of, marks, new_copies_of, planned, raw, two_copies_line

ROOT = Path(__file__).parent.parent


def column(db, copy_id):
    r = db.execute('SELECT checked_by, completeness, completeness_source FROM copy WHERE id=?', (copy_id,)).fetchone()
    return tuple(r)


def labelled(db):
    return {r[0] for r in db.execute("SELECT id FROM copy WHERE checked_by='rebrickable'")}


# --- the migration ------------------------------------------------------------------------------

def test_a_46_store_migrates_with_every_copy_null_and_matches_a_fresh_one(tmp_path):
    old = tmp_path / 'old.db'
    with closing(sqlite3.connect(old)) as db:
        db.executescript((HERE / 'brickwork.sql').read_text().split('-- Who checked a copy, schema 4.7')[0])
        db.execute("INSERT INTO meta(key,value) VALUES('schema_version','4.6')")
        assert 'checked_by' not in {r[1] for r in db.execute('PRAGMA table_info(copy)')}
        db.commit()
    assert upgrade(old) == upgrade(old) == SCHEMA_VERSION == '4.8'
    with closing(connect(old, tmp_path / 'catalogue.db')) as upgraded, closing(connect(tmp_path / 'new.db', tmp_path / 'catalogue.db')) as fresh:
        assert dict(upgraded.execute('SELECT key,value FROM meta'))['upgraded_to_4.7'].endswith('Z')
        defs = [db.execute("SELECT sql FROM sqlite_master WHERE name='copy'").fetchone()[0] for db in (upgraded, fresh)]
        assert defs[0] == defs[1] and "checked_by TEXT CHECK(checked_by IS NULL OR checked_by IN ('rebrickable'))" in defs[0]


# --- the pull -----------------------------------------------------------------------------------

def test_the_pull_labels_only_the_copy_that_received_the_lost_parts(store):
    copies, row = two_copies_line(store)
    plan = planned(store, Remote([row]))
    sync.apply_pull(store, plan['id'], [], picks={'2070-1': copies[1]})
    assert column(store, copies[1])[0] == 'rebrickable' and marks(store, copies[1])
    assert column(store, copies[0])[0] is None and not marks(store, copies[0])            # the set's other copy is not touched
    assert column(store, copies[1])[2] == 'derived' and column(store, copies[1])[1] == 'incomplete'


def test_a_set_with_one_copy_labels_that_copy_and_undo_restores_the_column(store):
    one = copy_of(store, '1000-1', marks=[('3001', '4', 3)])
    before = column(store, one)
    assert before[0] is None
    result = sync.apply_pull(store, planned(store, Remote([raw('1000-1', '3001', 4, 1)]), 'per_part')['id'])
    assert result['counts']['lost_sets'] == 1 and column(store, one)[0] == 'rebrickable' and marks(store, one) == {('3001', '4', False): 1}
    others = set(new_copies_of(store, '1000-1')) - {one}
    assert others and not (labelled(store) & others)                                        # the copies the same pull added are not the ones that received it
    sync.undo(store, result['event_id'])
    assert column(store, one) == before and marks(store, one) == {('3001', '4', False): 3}


def test_a_pulled_copy_without_lost_parts_is_complete_and_undo_takes_it_back(store):
    assert not new_copies_of(store, '1000-2')
    plan = planned(store, Remote([]))
    result = sync.apply_pull(store, plan['id'])
    (made,) = new_copies_of(store, '1000-2')
    assert column(store, made) == ('rebrickable', 'complete', 'derived')
    assert not marks(store, made)
    bar = collection._copy_bars(store, [made])[made]
    assert bar[0] == bar[2] and bar[1] == 0 and bar[5] == 'rebrickable'                     # every piece found, labelled
    twin = [c for c in new_copies_of(store, '1000-1')]
    assert not (labelled(store) & set(twin))                                               # two copies of 1000-1 came in: neither is labelled
    receipt = json.loads(store.execute('SELECT new_value FROM event WHERE id=?', (result['event_id'],)).fetchone()[0])
    assert [x['set_no'] for x in receipt['lost']['labelled']] == ['1000-2']
    sync.undo(store, result['event_id'])
    assert not labelled(store) and not new_copies_of(store, '1000-2')


def test_nothing_is_labelled_when_the_list_was_not_read_whole(store):
    broken = dict(raw('1000-1', '3023', 15, 1), inv_part=dict(raw('1000-1', '3023', 15, 1)['inv_part'], is_spare='no'))
    sync.apply_pull(store, planned(store, Remote([broken]))['id'])
    assert not labelled(store) and new_copies_of(store, '1000-2')
    remote = Remote([])
    remote.error = OSError('down')
    again = sync.plan_pull(store, 'rebrickable', http=remote)
    assert again['lost']['status'] == 'failed'
    sync.apply_pull(store, again['id'])
    assert not labelled(store)


def test_an_existing_copy_you_checked_is_not_relabelled(store):
    """The set has one live copy that the person made; it carries no 'imported from Rebrickable' tag, so a pull never says Rebrickable checked it."""
    mine = copy_of(store, '1000-2', marks=[('3001', '4', 1)])
    sync.apply_pull(store, planned(store, Remote([]))['id'])
    assert column(store, mine)[0] is None and marks(store, mine)


# --- a check or mark by hand --------------------------------------------------------------------

def labelled_copy(store):
    sync.apply_pull(store, planned(store, Remote([]))['id'])
    (made,) = new_copies_of(store, '1000-2')
    assert column(store, made)[0] == 'rebrickable'
    return made


def test_a_mark_by_hand_clears_the_label_and_its_undo_brings_it_back(store):
    made = labelled_copy(store)
    line = store.execute('SELECT id FROM copy_part WHERE copy_id=? AND copy_figure_id IS NULL AND is_spare=0 AND retired_at IS NULL LIMIT 1', (made,)).fetchone()[0]
    event = checker.mark(store, made, [('p:%d' % line, dict(missing=1, checked=True))])
    assert column(store, made)[0] is None
    from brickwork.core import undo
    undo.undo_event(store, event, via='app', actor=None)
    assert column(store, made)[0] == 'rebrickable' and not marks(store, made)


def test_the_set_is_checked_switch_clears_the_label(store):
    made = labelled_copy(store)
    checker.set_checked(store, made, True)
    assert column(store, made)[0] is None


def test_a_check_answer_clears_the_label(store):
    made = labelled_copy(store)
    session = checker.write(store, made, dict(action='start', operation='a1'))
    token = session['session']['order'][0]
    checker.write(store, made, dict(action='answer', operation='a2', session=session['session']['id'], token=token, found=1))
    assert column(store, made)[0] is None


def test_editing_the_completeness_by_hand_clears_the_label_but_other_edits_keep_it(store):
    made = labelled_copy(store)
    collection.save(store, 'copy', [made], dict(note='shelf talk'))
    assert column(store, made)[0] == 'rebrickable'
    collection.save(store, 'copy', [made], dict(completeness='incomplete'))
    assert column(store, made)[0] is None


def test_a_pre_47_check_receipt_still_undoes(store):
    """A receipt written before the column existed has no checked_by in its copy snapshot."""
    one = copy_of(store, '1000-1')
    line = store.execute('SELECT id FROM copy_part WHERE copy_id=? AND copy_figure_id IS NULL AND is_spare=0 AND retired_at IS NULL LIMIT 1', (one,)).fetchone()[0]
    event = checker.mark(store, one, [('p:%d' % line, dict(missing=1, checked=True))])
    store.execute('DROP TRIGGER event_no_update')                                            # the test rewrites a receipt as 4.6 wrote it
    for field in ('old_value', 'new_value'):
        body = json.loads(store.execute(f'SELECT {field} FROM event WHERE id=?', (event,)).fetchone()[0])
        body['copy'].pop('checked_by')
        store.execute(f'UPDATE event SET {field}=? WHERE id=?', (json.dumps(body), event))
    from brickwork.core import undo
    undo.undo_event(store, event, via='app', actor=None)
    assert not marks(store, one)


# --- what the page shows ------------------------------------------------------------------------

def test_a_checked_copy_counts_every_piece_that_is_not_missing_as_found(store):
    made = labelled_copy(store)
    line = store.execute('SELECT id,quantity FROM copy_part WHERE copy_id=? AND copy_figure_id IS NULL AND is_spare=0 AND retired_at IS NULL LIMIT 1', (made,)).fetchone()
    store.execute('UPDATE copy_part SET missing=1 WHERE id=?', (line[0],))
    bar = collection._copy_bars(store, [made])[made]
    assert bar[1] == 1 and bar[0] + bar[1] == bar[2] and bar[5] == 'rebrickable'
    store.execute("UPDATE copy SET checked_by=NULL WHERE id=?", (made,))
    assert collection._copy_bars(store, [made])[made][5] is None


def test_the_tile_line_and_the_detail_tag_are_written_for_a_pulled_copy_only():
    js = (ROOT / 'static/web/toni/bw-collection.js').read_text()
    assert "bar[5]==='rebrickable'?[track,bartxt,el('div','bar-src mono','Checked on Rebrickable')]:[track,bartxt]" in js
    head = (ROOT / 'templates/web/toni/web/bw_collection_detail.html').read_text()
    assert "s.checked_by=='rebrickable' %}<span class=\"bc-status complete\">Checked on Rebrickable</span>" in head
    info = (ROOT / 'templates/web/toni/brickwork/collection_modules.html').read_text()
    assert "s.checked_by=='rebrickable' else 'Not checked'" in info


def test_the_frames_pulled_world_has_frame_48s_two_copies(tmp_path):
    from brickwork.core.connect import connect as web_connect
    from scripts import screen_gate
    path = tmp_path / 'brickwork.db'
    screen_gate.build_store('frames-pulled', path)
    with closing(web_connect(path)) as db:
        rows = {r['item_no']: r for r in collection.listing(db, 'S')}
        assert rows['8043-1']['bars'] == [[1123, 0, 1123, 0, 0, 'rebrickable']] and rows['8043-1']['statuses'] == ['complete']
        assert rows['21028-1']['bars'] == [[589, 9, 598, 0, 0, 'rebrickable']] and rows['21028-1']['statuses'] == ['incomplete']
        assert rows['7213-1']['bars'][0][5] is None and rows['31120-1']['bars'][0][5] is None   # a copy Brick Work checked itself has no label


# --- review fixes of the pull (#489) ------------------------------------------------------------

def relabel_before_the_label_step(monkeypatch, sql):
    """Run `sql` on the pull's copies just before the label step reads them (the copy and its tag exist by then)."""
    real = lost_parts._copies

    def copies(db, items):
        if items:
            db.execute(sql)
        return real(db, items)
    monkeypatch.setattr(lost_parts, '_copies', copies)


def test_a_copy_without_a_part_list_is_not_labelled(store, monkeypatch):
    relabel_before_the_label_step(monkeypatch, "UPDATE copy SET inventory_source='none', inventory_version=NULL")
    sync.apply_pull(store, planned(store, Remote([]))['id'])
    (made,) = new_copies_of(store, '1000-2')
    assert column(store, made)[0] is None


def test_an_import_tag_in_another_case_still_lets_the_new_copy_be_labelled(store, monkeypatch):
    relabel_before_the_label_step(monkeypatch, "UPDATE flag SET name='Imported from Rebrickable' WHERE kind='tag' AND lower(name)='imported from rebrickable'")
    sync.apply_pull(store, planned(store, Remote([]))['id'])
    (made,) = new_copies_of(store, '1000-2')
    assert column(store, made)[0] == 'rebrickable'


def test_a_copy_brick_work_checked_gets_no_label_from_a_pull(store):
    one = copy_of(store, '1000-1')
    checker.set_checked(store, one, True)
    checker.mark_pulled(store, one, [], 'rebrickable')
    assert column(store, one)[0] is None


def test_a_label_counts_as_a_change_for_the_undo_of_an_add(store):
    from brickwork.core import add
    one = copy_of(store, '1000-1')
    snapshot = dict(store.execute('SELECT * FROM copy WHERE id=?', (one,)).fetchone())
    assert add._copy_untouched(store, one, snapshot)
    store.execute("UPDATE copy SET checked_by='rebrickable' WHERE id=?", (one,))
    assert not add._copy_untouched(store, one, snapshot)


def test_a_labelled_copy_is_checked_for_the_workbench_and_the_deductions(store):
    from brickwork.core import deductions, workbench
    made = labelled_copy(store)
    assert made in workbench.completion_context(store, [])[1]
    assert made in deductions.checked(store, [dict(id=made, completeness='complete')])
    store.execute("UPDATE copy SET checked_by=NULL WHERE id=?", (made,))
    assert made not in workbench.completion_context(store, [])[1]


def test_a_labelled_copy_has_known_progress_and_a_recorded_check(store):
    made = labelled_copy(store)
    item = store.execute('SELECT item_id FROM copy WHERE id=?', (made,)).fetchone()[0]
    progress = collection.detail(store, item, copy_id=made)['progress']
    assert progress['known'] and progress['check_recorded']


def test_choosing_manual_completeness_clears_the_label(store):
    made = labelled_copy(store)
    collection.save(store, 'copy', [made], dict(completeness_source='manual'))
    assert column(store, made)[0] is None
