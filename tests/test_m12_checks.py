"""M.12 (issue #114): the cross-file checks of `brickwork check` (design 3.1, 6.7, 8.7 point 4): each passes on a pair that belongs together and
fails, with the fix named, on one that does not."""
from contextlib import closing
import sqlite3

import pytest

from brickwork.core import admin
from brickwork.core.connect import connect
from brickwork.store4 import crosscheck
from brickwork.store4.reconcile import reconcile
from brickwork.web.cli import main
from tests.app4 import app4, client, coll, csrf, pair, world  # noqa: F401  (fixtures)


@pytest.fixture
def reconciled(coll, world):
    reconcile(coll.db, via='cli')
    return coll


def by_name(db):
    return {c['name']: c for c in crosscheck.run(db)}


def test_a_pair_that_belongs_together_passes_every_check(reconciled):
    found = by_name(reconciled.db)
    assert list(found) == ['binding', 'born_keys', 'inventory_keys', 'digests']
    assert all(c['ok'] and c['count'] == 0 for c in found.values()), found
    assert admin.check_ok(admin.check_all(reconciled.db))


def test_without_a_catalogue_there_is_nothing_to_cross_check(tmp_path):
    with closing(connect(tmp_path / 'brickwork.db', require_catalogue=False)) as db:
        assert crosscheck.run(db) == [] and admin.check_all(db)['cross_checks'] == []


def test_the_binding_check_fails_when_the_collection_is_bound_to_another_catalogue(reconciled):
    reconciled.sql("UPDATE main.meta SET value='another-catalogue' WHERE key='catalogue_id'")
    found = crosscheck.run(reconciled.db)
    assert [c['name'] for c in found] == ['binding'] and not found[0]['ok'] and 'another catalogue' in found[0]['message'] and 'rebuild' in found[0]['message']


def test_born_keys_fail_for_an_item_or_a_colour_with_another_key_in_the_catalogue(reconciled, world):
    reconciled.sql("UPDATE main.item SET born_key='9999-9' WHERE id=?", (world.keep,))
    reconciled.sql("UPDATE main.color SET born_key='777' WHERE id=?", (reconciled.colour('4'),))
    check = by_name(reconciled.db)['born_keys']
    assert not check['ok'] and check['count'] == 2 and str(world.keep) in check['message'] and '1 items and 1 colours' in check['message'] and 'rebuild' in check['message']


def test_born_keys_fail_for_an_item_the_catalogue_lacks(reconciled, world):
    reconciled.sql('''INSERT INTO main.item(id,origin,kind,kind_source,name,born_provider,born_namespace,born_key,created_at,updated_at)
                      VALUES(99999,'catalogue','part','namespace','Stray','rebrickable','parts','stray','2026-10-26T12:00:00.000Z','2026-10-26T12:00:00.000Z')''')
    assert not by_name(reconciled.db)['born_keys']['ok'] and '99999' in by_name(reconciled.db)['born_keys']['message']


def test_a_merged_item_and_a_local_item_are_not_held_to_the_catalogue(reconciled):
    reconciled.local('part', 'A local part', born_key='9999-local')
    assert by_name(reconciled.db)['born_keys']['ok']


def test_inventory_keys_fail_for_a_part_list_the_catalogue_lacks(reconciled, world):
    reconciled.sql("UPDATE main.copy SET inventory_version=99 WHERE id=?", (world.copy_a,))
    check = by_name(reconciled.db)['inventory_keys']
    assert not check['ok'] and check['count'] == 1 and ' v99' in check['message'] and 'rebuild' in check['message']


def test_a_retired_version_is_not_a_key_failure(reconciled, world, pair):
    reconciled.db.close()
    with closing(sqlite3.connect(pair.with_name('catalogue.db'))) as cat:
        cat.execute("UPDATE inventory SET retired_at='2026-10-26T12:00:00.000Z'")
        cat.commit()
    with closing(connect(pair)) as db:
        assert by_name(db)['inventory_keys']['ok']


def test_the_row_digests_are_checked_once_reconciled(coll, world):
    coll.sql("UPDATE main.item SET digest='stale' WHERE id=?", (world.keep,))
    assert by_name(coll.db)['digests']['ok'] and 'reconciled' in by_name(coll.db)['digests']['message']       # not reconciled yet: skipped, said so
    reconcile(coll.db, via='cli')                                                     # reconcile refreshes the digest again
    assert by_name(coll.db)['digests']['ok']
    coll.sql("UPDATE main.item SET digest='stale' WHERE id=?", (world.keep,))
    check = by_name(coll.db)['digests']
    assert not check['ok'] and check['count'] == 1 and 'reconcile' in check['message'] and str(world.keep) in check['message']


def test_a_part_list_that_does_not_match_its_own_lines_fails(reconciled, world, pair):
    reconciled.db.close()
    with closing(sqlite3.connect(pair.with_name('catalogue.db'))) as cat:
        cat.execute("UPDATE inventory_part SET quantity=quantity+1 WHERE inventory_id=(SELECT id FROM inventory WHERE item_id=? AND is_latest=1)", (world.keep,))
        cat.commit()
    with closing(connect(pair)) as db:
        check = by_name(db)['digests']
        assert not check['ok'] and 'do not match their own lines' in check['message'] and 'rebuild' in check['message']


def test_a_changed_part_list_is_counted_not_failed(reconciled, world):
    reconciled.sql("UPDATE main.copy SET inventory_digest='older' WHERE id=?", (world.copy_a,))      # the copy was built from the list before a re-download
    check = by_name(reconciled.db)['digests']
    assert check['ok'] and '1 copies carry a part list that changed' in check['message']


def test_brickwork_check_exits_zero_on_a_good_pair_and_names_the_failure_on_a_bad_one(reconciled, world, pair, app4, capsys):
    assert main(['check']) == 0
    out = capsys.readouterr().out
    assert 'cross_checks:' in out and 'ok   born_keys' in out and 'FAIL' not in out
    reconciled.sql("UPDATE main.copy SET inventory_version=99 WHERE id=?", (world.copy_a,))
    assert main(['check']) == 1
    out = capsys.readouterr().out
    assert 'FAIL inventory_keys' in out and 'rebuild' in out
    assert main(['--json', 'check']) == 1
    assert '"cross_checks"' in capsys.readouterr().out


def test_brickwork_check_reports_a_pair_that_cannot_attach_as_the_binding_check(reconciled, pair, app4, capsys):
    reconciled.sql("UPDATE main.meta SET value='another-catalogue' WHERE key='catalogue_id'")
    assert main(['check']) == 1
    out = capsys.readouterr().out
    assert 'FAIL binding' in out and 'another catalogue' in out and "integrity_check" in out


def test_the_database_page_shows_the_cross_checks(reconciled, world, client):
    token = csrf(client)
    client.post('/manage/database', data={'csrf_token': token, 'action': 'check'})
    html = client.get('/manage/database').get_data(as_text=True)
    assert 'Database checks passed' in html and 'data-cross-check="born_keys"' in html
    reconciled.sql("UPDATE main.copy SET inventory_version=99 WHERE id=?", (world.copy_a,))
    client.post('/manage/database', data={'csrf_token': token, 'action': 'check'})
    html = client.get('/manage/database').get_data(as_text=True)
    assert 'Database needs attention' in html and 'data-cross-check="inventory_keys" data-ok="false"' in html


def test_api_v2_database_check_keeps_its_shape(reconciled):
    assert 'cross_checks' not in admin.check(reconciled.db)
