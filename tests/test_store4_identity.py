"""Projection and provider-link resolution of the 4.0 store, with invented records from the design's worked examples."""
from contextlib import closing
import sqlite3

import pytest

from brickwork.store4 import identity
from brickwork.store4.connect import connect
from brickwork.store4.errors import AmbiguousIdentity, CatalogueError, NotInCatalogue
from tests.store4_fixtures import NOW, activate, make_catalogue, pair


@pytest.fixture
def db(tmp_path):
    col, cat = pair(tmp_path)
    with closing(connect(col, cat)) as conn:
        yield conn


def link_count(db, item_id):
    return db.execute('SELECT count(*) FROM main.item_link WHERE item_id=?', (item_id,)).fetchone()[0]


def test_project_copies_the_item_its_links_and_colours(db):
    assert identity.project(db, 12) == 12
    row = db.execute('SELECT * FROM main.item WHERE id=12').fetchone()
    assert (row['origin'], row['kind'], row['kind_source'], row['name'], row['size_key'], row['year'], row['num_parts']) == \
        ('catalogue', 'part', 'namespace', 'item 970c03', '1x2', 1993, 12)
    assert (row['born_provider'], row['born_namespace'], row['born_key']) == ('rebrickable', 'parts', '970c03')
    assert (row['category_name'], row['theme_name'], row['catalogue_build_id'], row['digest'], row['catalogue_retired_at']) == \
        ('Plates', None, 1, 'digest-12', None)
    assert row['created_at'].endswith('Z') and row['updated_at'] == row['created_at']
    links = db.execute('SELECT * FROM main.item_link WHERE item_id=12 ORDER BY provider_key').fetchall()
    assert [(k['provider_key'], k['color_id'], k['status'], k['method'], k['origin'], k['catalogue_build_id'], k['evidence_digest'])
            for k in links] == [('970c00', 4, 'matched', 'leg_rule', 'shipped', 2, 'e'), ('970c11', None, 'matched', 'leg_rule', 'shipped', 2, 'e')]
    assert all(k['decided_at'].endswith('Z') for k in links)
    # the colour the scoped link names came along, with its BrickLink link
    assert db.execute('SELECT name, born_key, origin FROM main.color WHERE id=4').fetchone()[:] == ('Black', '0', 'catalogue')
    assert db.execute("SELECT provider_key, inverse_preferred, catalogue_build_id FROM main.color_link WHERE color_id=4").fetchone()[:] == ('11', 1, 2)
    assert db.execute('SELECT count(*) FROM main.color WHERE id=3').fetchone()[0] == 0


def test_project_a_set_takes_its_theme_name(db):
    identity.project(db, 10)
    row = db.execute('SELECT theme_name, category_name, kind FROM main.item WHERE id=10').fetchone()
    assert (row['theme_name'], row['category_name'], row['kind']) == ('Castle', None, 'set')


def test_project_is_idempotent(db):
    identity.project(db, 12)
    before = db.execute('SELECT * FROM main.item WHERE id=12').fetchone()[:]
    assert identity.project(db, 12) == 12
    assert link_count(db, 12) == 2
    assert db.execute('SELECT * FROM main.item WHERE id=12').fetchone()[:] == before
    assert db.execute('SELECT count(*) FROM main.color_link WHERE color_id=4').fetchone()[0] == 1
    identity.project(db, 13)                                   # shares no colour but a key: nothing clashes
    assert db.execute('SELECT count(*) FROM main.item').fetchone()[0] == 2
    assert identity.project_color(db, 4) == 4
    assert list(db.execute('PRAGMA foreign_key_check')) == []


def test_project_runs_inside_the_callers_transaction(db):
    db.execute('BEGIN')
    identity.project(db, 12)
    db.rollback()
    assert db.execute('SELECT count(*) FROM main.item').fetchone()[0] == 0
    assert db.execute('SELECT count(*) FROM main.item_link').fetchone()[0] == 0


def test_project_refused_without_catalogue(tmp_path):
    with closing(connect(tmp_path / 'brickwork.db', tmp_path / 'absent.db')) as db:
        with pytest.raises(CatalogueError, match='not attached'):
            identity.project(db, 12)
        with pytest.raises(CatalogueError, match='not attached'):
            identity.project_color(db, 4)


def test_project_refused_when_the_build_is_not_activated(tmp_path):
    cat = tmp_path / 'catalogue.db'
    make_catalogue(cat)
    col = tmp_path / 'brickwork.db'
    activate(col, builds=(1,))                                 # the mapping build (2) carries the links
    with closing(connect(col, cat)) as db:
        with pytest.raises(CatalogueError, match=r'\[2\].*not activated'):
            identity.project(db, 12)
        assert db.execute('SELECT count(*) FROM main.item').fetchone()[0] == 0
    col2 = tmp_path / 'second.db'
    activate(col2, builds=())
    with closing(connect(col2, cat)) as db:
        with pytest.raises(CatalogueError, match='not activated'):
            identity.project(db, 10)


def test_project_unknown_item_and_colour(db):
    with pytest.raises(NotInCatalogue):
        identity.project(db, 999)
    with pytest.raises(NotInCatalogue):
        identity.project_color(db, 999)


def test_a_failed_projection_leaves_nothing_behind(db):
    db.execute("INSERT INTO main.item(id, origin, kind, kind_source, name, created_at, updated_at) VALUES(1000000009, 'local', 'part', 'manual', 'x', ?, ?)",
               (NOW, NOW))
    db.execute("INSERT INTO main.color(id, origin, name, is_trans, born_provider, born_key, created_at, updated_at)"
               " VALUES(1000000009, 'local', 'x', 0, 'rebrickable', '4', ?, ?)", (NOW, NOW))        # Rebrickable key 4 (Red) taken
    with pytest.raises(sqlite3.IntegrityError):
        identity.project(db, 13)                                 # its Red-scoped link projects colour 3, whose born key is 4
    assert db.execute('SELECT count(*) FROM main.item WHERE id=13').fetchone()[0] == 0
    assert db.execute('SELECT count(*) FROM main.color WHERE id=3').fetchone()[0] == 0


def projected(db, *ids):
    for i in ids:
        identity.project(db, i)
    return db


def test_resolve_follows_the_leg_rule(db):
    projected(db, 12)
    identity.project_color(db, 3)                                # Red: BrickLink colour 5
    assert identity.resolve(db, 12, 4) == ('P', '970c00', '11')  # Black legs: one-colour part
    assert identity.resolve(db, 12, 3) == ('P', '970c11', '5')   # any other hip colour: the unscoped link
    assert identity.resolve(db, 12, 1) == ('P', '970c11', None)  # no colour: unscoped, and no BrickLink colour


def test_resolve_without_a_link_or_a_colour_scope_match(db):
    projected(db, 13, 17)
    assert identity.resolve(db, 17, 3) is None
    assert identity.resolve(db, 13, 3)[:2] == ('P', '970c00')
    assert identity.resolve(db, 13, 5)[:2] == ('P', '970c05')
    assert identity.resolve(db, 13, None)[:2] == ('P', '970c05')
    assert identity.resolve(db, 13, 3, provider='brickset') is None


def test_resolve_orders_by_preferred_then_status_then_key(db):
    projected(db, 14)
    assert identity.resolve(db, 14, 1)[:2] == ('P', '310.3stk01')            # equal rank: the key
    db.execute("UPDATE main.item_link SET status='inferred' WHERE provider_key='310.3stk01'")
    assert identity.resolve(db, 14, 1)[:2] == ('P', '311.1stk01')            # matched beats inferred
    db.execute("UPDATE main.item_link SET status='manual', origin='user' WHERE provider_key='312.3stk01'")
    assert identity.resolve(db, 14, 1)[:2] == ('P', '312.3stk01')            # manual beats matched
    db.execute("UPDATE main.item_link SET preferred=1 WHERE provider_key='311.1stk01'")
    assert identity.resolve(db, 14, 1)[:2] == ('P', '311.1stk01')            # preferred beats status
    db.execute("UPDATE main.item_link SET status='to_check' WHERE provider_key='311.1stk01'")
    assert identity.resolve(db, 14, 1)[:2] == ('P', '312.3stk01')            # to_check never resolves
    db.execute("UPDATE main.item_link SET status='to_check'")
    assert identity.resolve(db, 14, 1) is None


def test_resolve_a_colour_scoped_choice_overrides_the_unscoped_preference(db):
    projected(db, 14)
    db.execute("UPDATE main.item_link SET preferred=1 WHERE provider_key='310.3stk01'")
    identity.project_color(db, 3)
    db.execute("INSERT INTO main.item_link(item_id, color_id, provider, provider_kind, provider_key, status, method, origin, preferred, decided_at)"
               " VALUES(14, 3, 'bricklink', 'P', '312.3stk01', 'manual', 'manual', 'user', 1, ?)", (NOW,))
    assert identity.resolve(db, 14, 3)[:2] == ('P', '312.3stk01')
    assert identity.resolve(db, 14, 4)[:2] == ('P', '310.3stk01')


def test_inverse_finds_item_and_colour_with_the_leg_rule(db):
    projected(db, 12, 13)
    for c in (3, 4):
        identity.project_color(db, c)
    assert identity.resolve_inverse(db, 'P', '970c00', '11') == (12, 4)       # 970c00 in Black is 970c03 in Black
    assert identity.resolve_inverse(db, 'P', '970c11', '5') == (12, 3)        # 970c11 in Red is 970c03 in Red
    assert identity.resolve_inverse(db, 'P', '970c00', '5') == (13, 3)        # 970c00 in Red is the Red-legs part
    assert identity.resolve_inverse(db, 'P', '970c11', '11') is None          # Black has its own scoped link: unscoped does not apply
    assert identity.resolve_inverse(db, 'P', '970c05', None) == (13, 1)       # no colour
    assert identity.resolve_inverse(db, 'P', 'nope', '11') is None


def test_inverse_reads_the_catalogue_when_nothing_is_projected(db):
    assert db.execute('SELECT count(*) FROM main.item').fetchone()[0] == 0
    assert identity.resolve_inverse(db, 'P', '970c00', '11') == (12, 4)
    assert identity.resolve_inverse(db, 'S', '6081-1', None) == (10, 1)
    assert identity.resolve_inverse(db, 'P', '3023', '999') is None          # a BrickLink colour nobody maps


def test_inverse_bricklink_colour_72_takes_the_preferred_rebrickable_colour(db):
    assert identity.resolve_inverse(db, 'P', '3023', 72) == (11, 6)           # Pastel Blue over Maersk Blue
    identity.project_color(db, 7)                                             # only the other colour is in the collection
    assert identity.resolve_inverse(db, 'P', '3023', '72') == (11, 6)
    db.execute("UPDATE main.color_link SET inverse_preferred=1 WHERE color_id=7")   # the user's own choice wins
    assert identity.resolve_inverse(db, 'P', '3023', '72') == (11, 7)


def test_inverse_keeps_sticker_sheets_apart_and_is_injective(db):
    keys = ['310.3stk01', '311.1stk01', '312.3stk01']
    assert [identity.resolve_inverse(db, 'P', k, None) for k in keys] == [(14, 1)] * 3   # one Rebrickable sheet, three keys
    pairs = {identity.resolve_inverse(db, kind, key, bl) for kind, key, bl in
             (('P', '970c00', '11'), ('P', '970c11', '5'), ('P', '970c00', '5'), ('P', '3023', '1'), ('P', '3023', '72'))}
    assert len(pairs) == 5


def test_inverse_prefers_the_collection_and_finds_local_items(db):
    db.execute("INSERT INTO main.item(id, origin, kind, kind_source, name, born_provider, born_namespace, born_key, created_at, updated_at)"
               " VALUES(1000000001, 'local', 'part', 'bricklink', 'BrickLink only', 'bricklink', 'P', '99999', ?, ?)", (NOW, NOW))
    db.execute("INSERT INTO main.item_link(item_id, provider, provider_kind, provider_key, status, method, origin, decided_at)"
               " VALUES(1000000001, 'bricklink', 'P', '99999', 'matched', 'migration', 'migration', ?)", (NOW,))
    db.execute("INSERT INTO main.item_link(item_id, provider, provider_kind, provider_key, status, method, origin, decided_at)"
               " VALUES(1000000001, 'bricklink', 'P', '3023', 'manual', 'manual', 'user', ?)", (NOW,))
    assert identity.resolve_inverse(db, 'P', '99999', '5') == (1000000001, 3)
    assert identity.resolve_inverse(db, 'P', '3023', '5') == (1000000001, 3)           # the collection answers before the catalogue


def test_inverse_ambiguity_raises_with_the_candidates(db):
    projected(db, 11, 16)
    db.execute("INSERT INTO main.item_link(item_id, provider, provider_kind, provider_key, status, method, origin, decided_at)"
               " VALUES(16, 'bricklink', 'P', '3023', 'manual', 'manual', 'user', ?)", (NOW,))
    with pytest.raises(AmbiguousIdentity, match=r'\[11, 16\]') as err:
        identity.resolve_inverse(db, 'P', '3023', '1')
    assert err.value.items == (11, 16)


def test_inverse_colour_shared_without_a_preferred_one_raises(db):
    identity.project_color(db, 6)
    identity.project_color(db, 7)
    db.execute("UPDATE main.color_link SET inverse_preferred=0")              # the collection's rows hide the catalogue's flag
    with pytest.raises(AmbiguousIdentity, match=r'colours \[6, 7\]') as err:
        identity.resolve_inverse(db, 'P', '3023', '72')
    assert err.value.items == (6, 7)


def test_a_projected_collection_stays_consistent(db):
    projected(db, 10, 11, 12, 14)
    identity.project_color(db, 5)
    db.execute("INSERT INTO main.stock(id, kind, item_id, color_id, quantity, condition, created_at, updated_at)"
               " VALUES('s1', 'part', 11, 5, 4, 'used', ?, ?)", (NOW, NOW))
    db.execute("INSERT INTO main.copy(id, item_id, inventory_source, inventory_version, inventory_digest, created_at, updated_at)"
               " VALUES('c1', 10, 'rebrickable', 1, 'dg', ?, ?)", (NOW, NOW))
    db.commit()
    assert list(db.execute('PRAGMA foreign_key_check')) == []
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert identity.resolve(db, 11, 5) == ('P', '3023', '1')


def test_project_without_a_begin_follows_the_callers_rollback(db):
    with pytest.raises(RuntimeError):
        with db:                                                   # a with-block issues no BEGIN of its own
            identity.project(db, 12)
            identity.project_color(db, 5)
            raise RuntimeError('caller fails')
    assert db.execute('SELECT count(*) FROM main.item').fetchone()[0] == 0
    assert db.execute('SELECT count(*) FROM main.color WHERE id=5').fetchone()[0] == 0


def test_inverse_never_falls_back_to_the_catalogue_for_a_projected_item(db):
    projected(db, 12)
    identity.project_color(db, 3)
    db.execute("INSERT INTO main.item_link(item_id, color_id, provider, provider_kind, provider_key, status, method, origin, decided_at)"
               " VALUES(12, 3, 'bricklink', 'P', '970c99', 'manual', 'manual', 'user', ?)", (NOW,))
    assert identity.resolve_inverse(db, 'P', '970c11', '5') is None          # the Red override hides 970c11 in Red
    assert identity.resolve_inverse(db, 'P', '970c99', '5') == (12, 3)
    db.execute("UPDATE main.item_link SET status='to_check' WHERE item_id=12 AND provider_key='970c00'")
    assert identity.resolve_inverse(db, 'P', '970c00', '11') is None         # disputed in the collection: not resurrected


def test_inverse_colour_never_falls_back_for_a_colour_the_collection_holds(db):
    identity.project_color(db, 6)
    db.execute("UPDATE main.color_link SET status='to_check' WHERE color_id=6")
    assert identity.resolve_inverse(db, 'P', '3023', '72') == (11, 7)        # colour 6 is disputed; only Maersk Blue remains


def _catalogue_rows(cat, *statements):
    with closing(sqlite3.connect(cat)) as raw:
        for sql in statements:
            raw.execute(sql)
        raw.commit()


def test_fixed_colours_and_lego_links_are_projected(tmp_path):
    col, cat = pair(tmp_path)
    _catalogue_rows(cat, "INSERT INTO color_link(color_id, provider, provider_key, provider_name, status, method, origin, build_id)"
                         " VALUES(1, 'bricklink', '0', '(Not Applicable)', 'matched', 'external_ids', 'shipped', 2)",
                    "INSERT INTO color_link(color_id, provider, provider_key, provider_name, status, method, origin, build_id)"
                    " VALUES(3, 'lego', '21', 'Bright Red', 'matched', 'external_ids', 'shipped', 2)")
    with closing(connect(col, cat)) as db:
        identity.project_color(db, 1)
        identity.project_color(db, 3)
        db.commit()
        assert db.execute("SELECT provider_key FROM main.color_link WHERE color_id=1").fetchall()[0][0] == '0'
        assert db.execute("SELECT provider_key FROM main.color_link WHERE color_id=3 AND provider='lego'").fetchone()[0] == '21'
        projected(db, 11)
        assert identity.resolve(db, 11, 1) == ('P', '3023', '0')
        identity.project_color(db, 1)                                          # idempotent once the links are in
        assert db.execute("SELECT count(*) FROM main.color_link WHERE color_id=1").fetchone()[0] == 1


def test_project_color_refuses_a_colour_from_an_unactivated_build(tmp_path):
    col, cat = pair(tmp_path)
    _catalogue_rows(cat, "INSERT INTO build(id, kind, started_at, app_version, files_json, counts_json)"
                         " VALUES(3, 'rebrickable_dump', '2026-10-23', '4.0', '[]', '{}')",
                    "INSERT INTO color VALUES(8, 'Olive', NULL, 0, 'rebrickable', '326', 3, NULL)")
    with closing(connect(col, cat)) as db:
        with pytest.raises(CatalogueError, match=r'\[3\].*not activated'):
            identity.project_color(db, 8)
