"""The in-place part list switch (design 4.4, 4.5; issue #108, M.6b): lines updated, inserted and retired by key, figure lines,
references that survive (test L5), the one receipt, the preview, the exact undo and its refusals. Invented data, no network."""
import json

import pytest

from brickwork.store4 import copies
from brickwork.store4.errors import Store4Error
from tests.test_store4_copies import FIG_A, FIG_B, FIG_C, SET, add, db, fetch, key, no_key, q   # noqa: F401  (fixtures)

V1, V2, BL = {'source': 'rebrickable', 'version': 1}, {'source': 'rebrickable', 'version': 2}, {'source': 'bricklink'}


def switch(db, cid, choice):
    return copies.switch_part_list(db, cid, choice, via='cli', actor='t')


def live(db, cid):
    """The copy's live lines as (figure item or 0, item, colour, spare, quantity)."""
    return q(db, '''SELECT coalesce(f.item_id, 0), p.item_id, p.color_id, p.is_spare, p.quantity FROM copy_part p
                    LEFT JOIN copy_figure f ON f.id=p.copy_figure_id WHERE p.copy_id=? AND p.retired_at IS NULL ORDER BY 1, 2, 3, 4''', cid)


def live_figures(db, cid):
    return q(db, 'SELECT item_id, quantity FROM copy_figure WHERE copy_id=? AND retired_at IS NULL ORDER BY item_id', cid)


def line_id(db, cid, item, colour, spare, figure=None):
    return q(db, '''SELECT p.id FROM copy_part p LEFT JOIN copy_figure f ON f.id=p.copy_figure_id
                    WHERE p.copy_id=? AND p.item_id=? AND p.color_id=? AND p.is_spare=? AND f.item_id IS ?''',
             cid, item, colour, spare, figure)[0][0]


def rows(db, cid):
    return {'copy': q(db, 'SELECT * FROM copy WHERE id=?', cid),
            'figures': q(db, 'SELECT * FROM copy_figure WHERE copy_id=? ORDER BY id', cid),
            'parts': q(db, 'SELECT * FROM copy_part WHERE copy_id=? ORDER BY id', cid)}


def fetch_bricklink(db):
    """A BrickLink list for the set: line (11,3) at 6, a new line (13,3), and figure C (which has no Rebrickable list) only."""
    return fetch(db, SET, 'bricklink', [(11, 3, 0, 6), (13, 3, 0, 1)], [(FIG_C, 1)])


def events(db, cid):
    return q(db, "SELECT field FROM event WHERE entity_kind='copy' AND entity_id=? ORDER BY id", cid)


# ---------- lines ----------

def test_a_switch_updates_inserts_and_retires_by_key_and_deletes_nothing(db):
    cid = add(db)['copy']['id']
    before = q(db, 'SELECT count(*) FROM copy_part')[0][0]
    r = switch(db, cid, V1)
    assert live(db, cid) == [(0, 11, 3, 0, 4)] and live_figures(db, cid) == []
    assert q(db, 'SELECT count(*) FROM copy_part')[0][0] == before                      # every old row is still there
    assert q(db, 'SELECT inventory_version, inventory_digest FROM copy') == q(db, 'SELECT version, digest FROM catalogue.inventory WHERE item_id=? AND version=1', SET)
    assert r['counts'] == {'figures_update': 0, 'figures_insert': 0, 'figures_retire': 2,
                           'lines_update': 1, 'lines_insert': 0, 'lines_retire': 2 + 3}          # 2 set lines + A's 3 components


def test_retiring_a_figure_retires_its_component_lines(db):
    cid = add(db)['copy']['id']
    switch(db, cid, V1)
    assert q(db, '''SELECT count(*) FROM copy_part p JOIN copy_figure f ON f.id=p.copy_figure_id
                    WHERE p.copy_id=? AND p.retired_at IS NULL''', cid) == [(0,)]
    assert q(db, 'SELECT count(*) FROM copy_part WHERE copy_figure_id IS NOT NULL AND retired_at IS NOT NULL') == [(3,)]
    assert q(db, 'SELECT count(*) FROM copy_figure WHERE retired_at IS NOT NULL') == [(2,)]


def test_new_keys_are_inserted_including_a_new_figure_with_its_own_list(db, key):
    cid = add(db, V1)['copy']['id']
    switch(db, cid, V2)
    assert live_figures(db, cid) == [(FIG_A, 2), (FIG_B, 1)]
    assert [l for l in live(db, cid) if l[0] == FIG_A] == [(FIG_A, 16, 3, 1, 2), (FIG_A, 16, 4, 0, 2), (FIG_A, 17, 5, 0, 4)]   # x2 figures
    assert q(db, 'SELECT inventory_source, inventory_version FROM copy_figure WHERE item_id=?', FIG_A) == [('rebrickable', 1)]


def test_missing_and_damaged_are_capped_checked_is_kept_and_both_are_receipted(db):
    cid = add(db)['copy']['id']
    pid = line_id(db, cid, 11, 3, 0)
    with db:
        db.execute('UPDATE copy_part SET missing=5, damaged=3, checked=1 WHERE id=?', (pid,))
    r = switch(db, cid, V1)                                                                # quantity 5 -> 4
    assert q(db, 'SELECT quantity, missing, damaged, checked, retired_at FROM copy_part WHERE id=?', pid) == [(4, 4, 3, 1, None)]
    (cap,) = r['not_carried_over']['capped']
    assert (cap['id'], cap['quantity'], cap['missing'], cap['damaged'], cap['checked']) == (pid, [5, 4], [5, 4], [3, 3], 1)


def test_retired_lines_with_marks_are_listed_and_unmarked_ones_are_not(db):
    cid = add(db)['copy']['id']
    marked, plain, comp = line_id(db, cid, 11, 4, 1), line_id(db, cid, 12, 4, 0), line_id(db, cid, 17, 5, 0, FIG_A)
    with db:
        db.execute('UPDATE copy_part SET missing=1 WHERE id=?', (marked,))
        db.execute('UPDATE copy_part SET checked=1 WHERE id=?', (comp,))
        db.execute('UPDATE copy_figure SET missing=1 WHERE item_id=?', (FIG_B,))
    r = switch(db, cid, V1)
    listed = {(e['kind'], e['id']) for e in r['not_carried_over']['retired']}
    assert (('part', marked) in listed and ('part', comp) in listed and ('part', plain) not in listed)
    assert ('figure', q(db, 'SELECT id FROM copy_figure WHERE item_id=?', FIG_B)[0][0]) in listed
    assert r['not_carried_over']['capped'] == []


def test_reactivation_keeps_the_row_id_and_the_checked_state(db):
    cid = add(db)['copy']['id']
    pid = line_id(db, cid, 11, 4, 1)
    with db:
        db.execute('UPDATE copy_part SET checked=1, missing=1 WHERE id=?', (pid,))
    switch(db, cid, V1)
    assert q(db, 'SELECT retired_at IS NOT NULL FROM copy_part WHERE id=?', pid) == [(1,)]
    switch(db, cid, V2)
    assert q(db, 'SELECT quantity, missing, checked, retired_at FROM copy_part WHERE id=?', pid) == [(1, 1, 1, None)]
    assert line_id(db, cid, 11, 4, 1) == pid


# ---------- references (test L5) ----------

def add_references(db, cid, line, fig_line, figure):
    """A Take, an allocation and a check session on a part line, a figure component line and a figure line."""
    with db:
        db.execute("INSERT INTO event(at, via, entity_kind, entity_id, field) VALUES('2026-10-25T00:00:00Z', 'cli', 'stock', 's', 'take')")
        eid = db.execute('SELECT max(id) FROM event').fetchone()[0]
        db.execute("INSERT INTO stock(id, kind, item_id, color_id, quantity, created_at, updated_at) VALUES('s', 'part', 11, 4, 1, 'x', 'x')")
        db.execute("INSERT INTO purchase_order(id, created_at, updated_at) VALUES(1, 'x', 'x')")
        db.execute("INSERT INTO order_document(id, order_id, source, digest, phase, created_at, updated_at) VALUES(1, 1, 'xml', 'd', 'saved', 'x', 'x')")
        db.execute("INSERT INTO order_line(id, order_id, document_id, line_no, state, qty, updated_at) VALUES(1, 1, 1, 1, 'confirmed', 1, 'x')")
        for part, fig in ((line, None), (fig_line, None), (None, figure)):
            db.execute('''INSERT INTO stock_transfer(at, kind, stock_id, copy_id, copy_part_id, copy_figure_id, item_id, quantity, source_snapshot,
                          event_id) VALUES('x', 'part', 's', ?, ?, ?, 11, 1, '{}', ?)''', (cid, part, fig, eid))
            db.execute('''INSERT INTO allocation(confirm_id, order_id, line_id, qty, state, target_kind, kind, copy_id, copy_part_id,
                          copy_figure_id, item_id, created_at) VALUES('c', 1, 1, 1, 'applied', 'copy', 'missing_part', ?, ?, ?, 11, 'x')''',
                       (cid, part, fig))
        db.execute('''INSERT INTO part_check(copy_id, copy_figure_id, session_id, order_mode, session_json, started_at, updated_at)
                      VALUES(?, NULL, 'a', 'inventory', ?, 'x', 'x')''', (cid, json.dumps({'answers': {str(line): 'ok'}})))
        db.execute('''INSERT INTO part_check(copy_id, copy_figure_id, session_id, order_mode, session_json, started_at, updated_at)
                      VALUES(?, ?, 'b', 'inventory', ?, 'x', 'x')''', (cid, figure, json.dumps({'answers': {str(fig_line): 'ok'}})))


def test_references_survive_a_switch_away_and_back_and_the_rows_come_back_under_the_same_id(db):
    cid = add(db)['copy']['id']
    line, fig_line = line_id(db, cid, 11, 4, 1), line_id(db, cid, 17, 5, 0, FIG_A)
    figure = q(db, 'SELECT id FROM copy_figure WHERE item_id=?', FIG_A)[0][0]
    add_references(db, cid, line, fig_line, figure)
    switch(db, cid, V1)
    for table, ids in (('copy_part', (line, fig_line)), ('copy_figure', (figure,))):
        for i in ids:
            assert q(db, f'SELECT retired_at IS NOT NULL FROM {table} WHERE id=?', i) == [(1,)]           # retired, not deleted
    assert q(db, 'PRAGMA foreign_key_check') == []
    switch(db, cid, V2)
    assert q(db, 'SELECT retired_at FROM copy_part WHERE id IN (?, ?)', line, fig_line) == [(None,), (None,)]
    assert q(db, 'SELECT retired_at FROM copy_figure WHERE id=?', figure) == [(None,)]
    assert q(db, 'SELECT count(*) FROM stock_transfer') == [(3,)] and q(db, 'SELECT count(*) FROM allocation') == [(3,)]
    assert q(db, 'SELECT count(*) FROM part_check') == [(2,)]
    assert q(db, 'SELECT count(*) FROM copy_part WHERE copy_id=?', cid) == [(6,)]                  # none added by going back
    assert q(db, 'PRAGMA foreign_key_check') == [] and q(db, 'PRAGMA integrity_check') == [('ok',)]


# ---------- across sources ----------

def test_bricklink_and_back_across_a_figure_that_exists_in_only_one_list(db, key):
    fetch_bricklink(db)
    cid = add(db)['copy']['id']
    fig_a = q(db, 'SELECT id FROM copy_figure WHERE item_id=?', FIG_A)[0][0]
    switch(db, cid, BL)
    assert live(db, cid) == [(0, 11, 3, 0, 6), (0, 13, 3, 0, 1)] and live_figures(db, cid) == [(FIG_C, 1)]
    assert q(db, 'SELECT inventory_source, inventory_version, fetched_inventory_id IS NOT NULL FROM copy') == [('bricklink', None, 1)]
    assert q(db, 'SELECT inventory_source FROM copy_figure WHERE item_id=?', FIG_C) == [('none',)]
    fig_c = q(db, 'SELECT id FROM copy_figure WHERE item_id=?', FIG_C)[0][0]
    switch(db, cid, V2)
    assert live(db, cid)[:3] == [(0, 11, 3, 0, 5), (0, 11, 4, 1, 1), (0, 12, 4, 0, 2)] and live_figures(db, cid) == [(FIG_A, 2), (FIG_B, 1)]
    assert q(db, 'SELECT retired_at IS NULL FROM copy_figure WHERE id=?', fig_a) == [(1,)]                # the same row, re-activated
    assert q(db, 'SELECT retired_at IS NOT NULL FROM copy_figure WHERE id=?', fig_c) == [(1,)]
    assert q(db, 'SELECT inventory_source, fetched_inventory_id FROM copy') == [('rebrickable', None)]


# ---------- the receipt ----------

def test_one_receipt_event_per_switch_and_the_receipt_holds_every_changed_row(db, key):
    fetch_bricklink(db)
    cid = add(db)['copy']['id']
    n = q(db, 'SELECT count(*) FROM event')[0][0]
    r = switch(db, cid, BL)
    assert q(db, 'SELECT count(*) FROM event')[0][0] == n + 1
    (ev,) = q(db, "SELECT entity_kind, entity_id, field, old_value FROM event WHERE id=?", r['event_id'])
    assert ev == ('copy', cid, 'part_list_switch', None)
    stored = json.loads(q(db, 'SELECT new_value FROM event WHERE id=?', r['event_id'])[0][0])
    assert stored['choice'] == BL and stored['parts']['columns'][0] == 'id'
    cols = stored['parts']['columns']
    for op, old, new in stored['parts']['ops']:                                            # after-rows are the rows now in the table
        assert q(db, f'SELECT {", ".join(cols)} FROM copy_part WHERE id=?', new[0]) == [tuple(new)]
        assert (old is None) == (op == 'insert')
    assert len(stored['parts']['ops']) == sum(v for k, v in r['counts'].items() if k.startswith('lines_'))
    assert stored['copy']['before'][0] == 'rebrickable' and stored['copy']['after'][0] == 'bricklink'
    assert events(db, cid) == [('add',), ('part_list_switch',)]


def test_a_failure_rolls_everything_back(db, monkeypatch):
    cid = add(db)['copy']['id']
    snapshot, n = rows(db, cid), q(db, 'SELECT count(*) FROM event')
    monkeypatch.setattr(copies.Events, 'write', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    with pytest.raises(RuntimeError):
        switch(db, cid, V1)
    assert rows(db, cid) == snapshot and q(db, 'SELECT count(*) FROM event') == n and not db.in_transaction


def test_a_target_that_cannot_be_built_changes_nothing(db, key):
    cid = add(db)['copy']['id']
    snapshot = rows(db, cid)
    with pytest.raises(copies.BrickLinkPending):
        switch(db, cid, BL)
    assert rows(db, cid) == snapshot


def test_the_same_list_is_refused_and_the_preview_says_so(db):
    cid = add(db)['copy']['id']
    assert copies.preview_switch(db, cid, V2)['same_list'] is True
    with pytest.raises(copies.NothingToSwitch):
        switch(db, cid, V2)
    assert events(db, cid) == [('add',)]


def test_a_switch_clears_the_pending_state(db):
    cid = add(db)['copy']['id']
    with db:
        db.execute("INSERT INTO job(id, source, kind, state, via, created_at, updated_at) VALUES(1, 'bricklink', 'subsets', 'done', 'cli', 'x', 'x')")
        db.execute("UPDATE copy SET inventory_pending='bricklink', pending_job_id=1 WHERE id=?", (cid,))
    switch(db, cid, V1)
    assert q(db, 'SELECT inventory_pending, pending_job_id FROM copy') == [(None, None)]
    assert copies.preview_switch(db, cid, V1)['same_list'] is True


def test_completeness_is_recomputed_only_when_derived(db):
    cid = add(db)['copy']['id']
    with db:
        db.execute("INSERT INTO flag(id, name, kind, system, created_at) VALUES('f', 'Set is checked', 'status', 1, 'x')")
        db.execute("INSERT INTO copy_flag VALUES(?, 'f')", (cid,))
        db.execute("UPDATE copy SET completeness='sealed', completeness_source='manual' WHERE id=?", (cid,))
    switch(db, cid, V1)
    assert q(db, 'SELECT completeness FROM copy') == [('sealed',)]                       # manual: untouched
    with db:
        db.execute("UPDATE copy SET completeness_source='derived' WHERE id=?", (cid,))
    pid = line_id(db, cid, 11, 3, 0)
    with db:
        db.execute('UPDATE copy_part SET missing=1 WHERE id=?', (pid,))
    switch(db, cid, V2)
    assert q(db, 'SELECT completeness FROM copy') == [('incomplete',)]
    with db:
        db.execute('UPDATE copy_part SET missing=0 WHERE id=?', (pid,))
        db.execute('UPDATE copy_part SET missing=1 WHERE id=?', (line_id(db, cid, 11, 4, 1),))     # a spare: not a defect
        db.execute('UPDATE copy_part SET missing=1 WHERE id=?', (line_id(db, cid, 17, 5, 0, FIG_A),))   # a figure component: not a defect
    switch(db, cid, V1)                                                                    # retires both
    assert q(db, 'SELECT completeness FROM copy') == [('complete',)]
    with db:
        db.execute('UPDATE copy_figure SET missing=1 WHERE item_id=?', (FIG_A,))
    switch(db, cid, V2)
    assert q(db, 'SELECT completeness FROM copy') == [('incomplete',)]                      # a missing whole figure counts


# ---------- undo ----------

def strip(db, cid):
    return {'copy': q(db, 'SELECT id, item_id, inventory_source, inventory_version, fetched_inventory_id, inventory_digest, materialised_at, '
                          'inventory_pending, pending_job_id, completeness, completeness_source, note, created_at FROM copy WHERE id=?', cid),
            'figures': q(db, 'SELECT id, copy_id, item_id, inventory_source, inventory_version, fetched_inventory_id, inventory_digest, '
                             'quantity, missing, retired_at FROM copy_figure WHERE copy_id=? ORDER BY id', cid),
            'parts': q(db, 'SELECT * FROM copy_part WHERE copy_id=? ORDER BY id', cid)}


def assert_restored(db, cid, start):
    now = strip(db, cid)
    assert now['copy'] == start['copy']
    for table in ('figures', 'parts'):
        by_id = {r[0]: r for r in now[table]}
        assert all(by_id[r[0]] == r for r in start[table])                                  # every old row, column for column
        extra = [r for r in now[table] if r[0] not in {s[0] for s in start[table]}]
        assert all(r[-1] is not None for r in extra)                                        # rows the switch inserted: retired


def test_undo_restores_the_previous_lines_exactly(db, key):
    fetch_bricklink(db)
    cid = add(db)['copy']['id']
    marked = line_id(db, cid, 11, 3, 0)
    with db:
        db.execute('UPDATE copy_part SET missing=4, damaged=2, checked=1 WHERE id=?', (marked,))
        db.execute('UPDATE copy_figure SET missing=1 WHERE item_id=?', (FIG_A,))
    start = strip(db, cid)
    live_start = (live(db, cid), live_figures(db, cid))
    r = switch(db, cid, BL)
    u = copies.undo_switch(db, r['event_id'], via='cli', actor='t')
    assert_restored(db, cid, start)
    assert (live(db, cid), live_figures(db, cid)) == live_start
    assert q(db, 'SELECT event_id, undo_event_id FROM event_undo') == [(r['event_id'], u['event_id'])]
    assert events(db, cid) == [('add',), ('part_list_switch',), ('part_list_switch_undo',)]
    assert q(db, 'PRAGMA foreign_key_check') == []


def test_two_switches_undone_in_reverse_order_restore_the_start(db, key):
    fetch_bricklink(db)
    cid = add(db)['copy']['id']
    with db:
        db.execute('UPDATE copy_part SET missing=1, checked=1 WHERE id=?', (line_id(db, cid, 11, 4, 1),))
    start = strip(db, cid)
    first, second = switch(db, cid, BL), None
    mid = strip(db, cid)
    second = switch(db, cid, V2)
    with pytest.raises(copies.SwitchUndoRefused):                                          # the first is overlaid by the second
        copies.undo_switch(db, first['event_id'], via='cli')
    copies.undo_switch(db, second['event_id'], via='cli')
    assert_restored(db, cid, mid)
    copies.undo_switch(db, first['event_id'], via='cli')
    assert_restored(db, cid, start)


def test_undo_is_refused_after_a_later_change_and_a_second_undo_is_refused(db):
    cid = add(db)['copy']['id']
    r = switch(db, cid, V1)
    with db:
        db.execute('UPDATE copy_part SET checked=1 WHERE id=?', (line_id(db, cid, 11, 3, 0),))
    snapshot = rows(db, cid)
    with pytest.raises(copies.SwitchUndoRefused, match='changed after the switch'):
        copies.undo_switch(db, r['event_id'], via='cli')
    assert rows(db, cid) == snapshot and events(db, cid) == [('add',), ('part_list_switch',)]
    with db:
        db.execute('UPDATE copy_part SET checked=0 WHERE id=?', (line_id(db, cid, 11, 3, 0),))
    u = copies.undo_switch(db, r['event_id'], via='cli')
    with pytest.raises(copies.SwitchUndoRefused, match='already'):
        copies.undo_switch(db, r['event_id'], via='cli')
    with pytest.raises(copies.SwitchUndoRefused, match='not a part list switch'):           # neither the undo nor the add is a switch
        copies.undo_switch(db, u['event_id'], via='cli')
    with pytest.raises(copies.SwitchUndoRefused):
        copies.undo_switch(db, q(db, "SELECT id FROM event WHERE field='add'")[0][0], via='cli')


def test_a_copy_change_that_is_not_a_switch_column_does_not_block_the_undo(db):
    cid = add(db)['copy']['id']
    r = switch(db, cid, V1)
    with db:
        db.execute("UPDATE copy SET note='hello', updated_at='later' WHERE id=?", (cid,))
    copies.undo_switch(db, r['event_id'], via='cli')
    assert q(db, 'SELECT inventory_version, note FROM copy') == [(2, 'hello')]


# ---------- the preview ----------

def test_the_preview_equals_the_receipt_and_writes_nothing(db):
    cid = add(db)['copy']['id']
    with db:
        db.execute('UPDATE copy_part SET missing=5, checked=1 WHERE id=?', (line_id(db, cid, 11, 3, 0),))
        db.execute('UPDATE copy_part SET damaged=1 WHERE id=?', (line_id(db, cid, 17, 5, 0, FIG_A),))
    snapshot, n = rows(db, cid), q(db, 'SELECT count(*) FROM event')
    p = copies.preview_switch(db, cid, V1)
    assert rows(db, cid) == snapshot and q(db, 'SELECT count(*) FROM event') == n and not db.in_transaction
    r = switch(db, cid, V1)
    assert p['not_carried_over'] == r['not_carried_over'] and p['counts'] == r['counts'] and p['same_list'] is False
    assert p['not_carried_over']['retired'] and p['not_carried_over']['capped']


def derived_and_checked(db, cid):
    with db:
        db.execute("INSERT INTO flag(id, name, kind, system, created_at) VALUES('f', 'Set is checked', 'status', 1, 'x')")
        db.execute("INSERT INTO copy_flag VALUES(?, 'f')", (cid,))
        db.execute("UPDATE copy SET completeness='complete', completeness_source='derived' WHERE id=?", (cid,))


def test_a_manual_completeness_chosen_after_the_switch_refuses_its_undo(db):
    cid = add(db)['copy']['id']
    derived_and_checked(db, cid)
    r = switch(db, cid, V1)
    with db:
        db.execute("UPDATE copy SET completeness_source='manual' WHERE id=?", (cid,))
    with pytest.raises(copies.SwitchUndoRefused):
        copies.undo_switch(db, r['event_id'], via='cli', actor='t')
    assert q(db, 'SELECT completeness, completeness_source FROM copy') == [('complete', 'manual')]


def test_undo_recomputes_derived_completeness_from_lines_the_switch_left_alone(db, key):
    cid = add(db)['copy']['id']
    derived_and_checked(db, cid)
    fetch(db, SET, 'bricklink', [(11, 3, 0, 5), (12, 4, 0, 2)])                  # the two set lines unchanged; spare and figures go
    r = switch(db, cid, BL)
    assert q(db, 'SELECT completeness FROM copy') == [('complete',)]
    with db:
        db.execute('UPDATE copy_part SET missing=1 WHERE id=?', (line_id(db, cid, 12, 4, 0),))   # a line the switch did not touch
    copies.undo_switch(db, r['event_id'], via='cli', actor='t')
    assert q(db, 'SELECT completeness FROM copy') == [('incomplete',)]
