"""`python -m brickwork.store4 copy ...` and the changed-part-list line of `catalogue status` (issue #108, M.6d), through
`cli.main` on invented files. No network: the job runner's transport is a fake."""
from contextlib import closing
import json

import pytest

from brickwork.store4 import cli
from brickwork.store4.connect import connect
from tests.store4_fixtures import pair
from tests.test_store4_changes import FIG_A_NEW, V2, World
from tests.test_store4_copies import FIG_A, FIG_B, NEWER_SET, SET, add_catalogue, key, no_key, q   # noqa: F401  (fixtures)
from tests.test_store4_pending import ok


@pytest.fixture
def data(tmp_path):
    col, cat = pair(tmp_path)
    add_catalogue(cat)
    return tmp_path


def run(data, capsys, *args, expect=0, as_json=False, http=None):
    code = cli.main(['--data', str(data), *(['--json'] if as_json else []), *args], http=http)
    captured = capsys.readouterr()
    assert code == expect, captured.err + captured.out
    return json.loads(captured.out) if as_json else captured


def add(data, capsys, *args, set_number='6081-1'):
    return run(data, capsys, 'copy', 'add', set_number, *args, as_json=True)['id']


def redownload(data, inventory, parts, figures=()):
    World(None, data / 'catalogue.db').redownload(inventory, parts, figures)


def test_add_uses_the_pickers_preselection_and_show_describes_the_copy(data, capsys):
    out = run(data, capsys, 'copy', 'add', '6081-1').out
    assert 'set 6081-1 from rebrickable version 2, 2 figure line(s), 6 part line(s)' in out
    cid = out.split()[1].rstrip(':')
    shown = run(data, capsys, 'copy', 'show', cid[:8]).out                              # a unique start of the id is enough
    assert f'copy {cid}: set 6081-1' in shown and 'part list: rebrickable version 2' in shown
    assert 'lines: 6 live, 0 retired; figures: 2 live, 0 retired; none 1, rebrickable 1' in shown      # FIG_B has no list anywhere
    assert 'no marks' in shown and 'changed:' not in shown
    with closing(connect(data / 'brickwork.db', data / 'catalogue.db')) as db:
        assert q(db, "SELECT via FROM event WHERE entity_kind='copy'") == [('cli',)]


def test_add_takes_a_version_and_refuses_what_it_cannot_resolve(data, capsys):
    cid = add(data, capsys, '--rebrickable', '1')
    assert run(data, capsys, 'copy', 'show', cid, as_json=True)['version'] == 1
    assert run(data, capsys, 'copy', 'add', '6081-1', '--rebrickable', as_json=True)['version'] == 2    # no number: the latest
    run(data, capsys, 'copy', 'add', '9999-1', expect=1)
    run(data, capsys, 'copy', 'add', '6081-1', '--bricklink', expect=1)                    # no key: BrickLink is not offered
    run(data, capsys, 'copy', 'add', '7777-1', expect=1)                                   # the catalogue has no list for it
    run(data, capsys, 'copy', 'show', 'zzzz', expect=1)


def test_a_prefix_that_names_two_copies_is_refused(data, capsys):
    ids = [add(data, capsys) for _ in range(40)]
    clash = next(p for p in {i[:1] for i in ids} if sum(i.startswith(p) for i in ids) > 1)
    assert 'more than one' in run(data, capsys, 'copy', 'show', clash, expect=1).err


def test_switch_preview_switch_and_undo(data, capsys):
    cid = add(data, capsys)
    preview = run(data, capsys, 'copy', 'switch', cid, 'rebrickable:1', '--preview').out
    assert 'would switch' in preview and 'lines_retire' in preview
    assert run(data, capsys, 'copy', 'show', cid, as_json=True)['version'] == 2             # the preview wrote nothing
    switched = run(data, capsys, 'copy', 'switch', cid, 'rebrickable:1', as_json=True)
    assert run(data, capsys, 'copy', 'show', cid, as_json=True)['version'] == 1
    assert 'already carries' in run(data, capsys, 'copy', 'switch', cid, 'rebrickable:1', '--preview').out
    run(data, capsys, 'copy', 'switch', cid, 'rebrickable:1', expect=1)                    # NothingToSwitch
    run(data, capsys, 'copy', 'switch', cid, 'nonsense', expect=1)
    assert 'undid event' in run(data, capsys, 'copy', 'undo', str(switched['event_id'])).out
    assert run(data, capsys, 'copy', 'show', cid, as_json=True)['version'] == 2
    run(data, capsys, 'copy', 'undo', str(switched['event_id']), expect=1)                  # twice


def test_changes_and_the_status_line_follow_a_re_download_and_clear_after_the_switch(data, capsys):
    cid, other = add(data, capsys), add(data, capsys, '--rebrickable', '1')
    assert '0 copies with a changed part list' in run(data, capsys, 'catalogue', 'status').out
    assert run(data, capsys, 'catalogue', 'status', as_json=True)['collection']['part_lists']['copies'] == 0
    redownload(data, 2, V2, [(FIG_A, 2), (FIG_B, 1)])
    redownload(data, 3, FIG_A_NEW)
    status = run(data, capsys, 'catalogue', 'status')
    assert '1 copies with a changed part list (changed 2; 0 copies whose list is gone)' in status.out
    changes = run(data, capsys, 'copy', 'changes').out
    assert f'1 copies with a changed part list (2 entries)' in changes and cid[:8] in changes and other[:8] not in changes
    assert f'figure {FIG_A} on rebrickable version 1' in changes and 'switch to rebrickable:2' in changes
    assert run(data, capsys, 'copy', 'changes', other).out.startswith('0 copies')
    assert 'changed: set list' in run(data, capsys, 'copy', 'show', cid).out
    run(data, capsys, 'copy', 'switch', cid, 'rebrickable:2')
    assert run(data, capsys, 'copy', 'changes', as_json=True)['changes'] == []
    assert '0 copies with a changed part list' in run(data, capsys, 'catalogue', 'status').out


def test_a_pending_copy_is_listed_settled_by_the_drain_and_a_marked_one_is_offered(data, capsys, key):
    plain, marked = add(data, capsys, '--bricklink'), add(data, capsys, '--bricklink')
    assert 'BrickLink list waiting (job 1, queued)' in run(data, capsys, 'copy', 'show', marked).out    # one job serves both copies
    with closing(connect(data / 'brickwork.db', data / 'catalogue.db')) as db, db:
        db.execute('UPDATE copy_part SET checked=1 WHERE copy_id=? AND item_id=11 AND color_id=3', (marked,))
    listed = run(data, capsys, 'copy', 'pending').out
    assert f'{plain}: waiting' in listed and f'{marked}: waiting' in listed
    run(data, capsys, 'jobs', 'drain', http=ok())
    assert run(data, capsys, 'copy', 'show', plain, as_json=True)['source'] == 'bricklink'          # unmarked: switched by itself
    assert run(data, capsys, 'copy', 'pending').out.strip() == f'{marked}: ready'
    assert 'switch now?' in run(data, capsys, 'copy', 'pending', marked).out
    assert run(data, capsys, 'copy', 'settle').out.strip() == f'copy {marked}: offered'
    accepted = run(data, capsys, 'copy', 'pending', 'accept', marked).out
    assert 'switched to BrickLink' in accepted and 'not carried over' in accepted
    assert 'no copy is waiting' in run(data, capsys, 'copy', 'pending').out
    run(data, capsys, 'copy', 'pending', 'accept', marked, expect=1)


def test_cancel_declines_and_keeps_the_rebrickable_list(data, capsys, key):
    cid = add(data, capsys, '--bricklink')
    assert 'stays on rebrickable version 2' in run(data, capsys, 'copy', 'pending', 'cancel', cid).out
    run(data, capsys, 'copy', 'pending', 'cancel', cid, expect=1)                           # no longer pending
    assert run(data, capsys, 'copy', 'show', cid, as_json=True)['pending'] is None
    run(data, capsys, 'copy', 'pending', 'bogus', cid, expect=1)


def test_preferences_and_the_global_switch(data, capsys, key):
    assert run(data, capsys, 'copy', 'preference', '6081-1', 'rebrickable:1').out.strip() == 'preference for 6081-1: rebrickable:1'
    assert run(data, capsys, 'copy', 'add', '6081-1', as_json=True)['version'] == 1             # the Add picker follows it
    run(data, capsys, 'copy', 'preference', '6081-1', 'rebrickable:9', expect=1)
    assert 'cleared' in run(data, capsys, 'copy', 'preference', '6081-1', 'clear').out
    assert run(data, capsys, 'copy', 'prefer-bricklink', 'on').out.strip() == 'prefer BrickLink: on'
    assert run(data, capsys, 'copy', 'add', '6081-1', as_json=True)['pending']['source'] == 'bricklink'
    assert run(data, capsys, 'copy', 'prefer-bricklink', 'off').out.strip() == 'prefer BrickLink: off'


def test_the_re_download_commands_report_the_changed_count(data, capsys):
    add(data, capsys)
    assert run(data, capsys, 'catalogue', 'reconcile', as_json=True)['part_lists']['copies'] == 0
    redownload(data, 2, V2, [(FIG_A, 2), (FIG_B, 1)])
    assert '1 copies with a changed part list' in run(data, capsys, 'catalogue', 'reconcile').out
