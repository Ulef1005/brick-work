"""BrickLink subsets as a fetched list: validation, extras as spares, lines resolved with the set as context (design 4.2, 4.5, 8.3).
All replies are invented."""
from contextlib import closing, contextmanager
import sqlite3

import pytest

from brickwork.store4 import bricklink_subsets as bs, fetched
from brickwork.store4.audit import Events
from brickwork.store4.bldigest import bl_digest
from brickwork.store4.connect import connect
from brickwork.store4.fetched import InventoryError
from tests.store4_fixtures import pair

LOCAL = 1_000_000_000
SET, SHEET_PART, SHEET_ALT, ONLY_PART, FIG = 10, 14, 18, 19, 20       # catalogue ids; 14 is 003402 with three sticker keys


def entry(no, colour=5, quantity=1, extra=0, type='PART', name=None, **flags):
    e = {'item': {'no': no, 'name': name or f'name {no}', 'type': type, 'category_id': 1}, 'quantity': quantity, 'extra_quantity': extra,
         'is_alternate': False, 'is_counterpart': False, **flags}
    if type == 'PART' or colour is not None:
        e['color_id'] = colour
    return e


def reply(*entries):
    """Real replies are a list of groups, one entry per group for a plain line."""
    return {'meta': {'description': 'OK', 'message': 'OK', 'code': 200}, 'data': [{'match_no': 0, 'entries': [e]} for e in entries]}


def add_catalogue(cat):
    """On top of the fixture: a second item sharing BrickLink sticker keys with 003402, a part with one key, a figure, and the
    set's inventory (003402 and 3023 in version 1, 003402b, 3626 and the figure in version 2)."""
    with closing(sqlite3.connect(cat)) as c:
        for i, ns, key in ((SHEET_ALT, 'parts', '003402b'), (ONLY_PART, 'parts', '999001')):
            c.execute("INSERT INTO item(id, kind, kind_source, name, name_key, size_key, year, num_parts, category_id, born_provider, born_namespace,"
                      " born_key, build_id, digest) VALUES(?, 'part', 'namespace', ?, ?, '1x2', 1993, 1, 14, 'rebrickable', ?, ?, 1, ?)",
                      (i, f'item {key}', f'item {key}', ns, key, f'digest-{i}'))
        c.execute("INSERT INTO item(id, kind, kind_source, name, name_key, size_key, year, num_parts, build_id, born_provider, born_namespace,"
                  " born_key, digest) VALUES(?, 'minifigure', 'namespace', 'King Leo', 'king leo', '', 1993, 4, 1, 'rebrickable', 'minifigs', 'fig-000001', 'd')",
                  (FIG,))
        for item, kind, key in ((SHEET_ALT, 'P', '312.3stk01'), (ONLY_PART, 'P', '310.3stk01'), (FIG, 'M', 'cas001')):
            c.execute("INSERT INTO item_link(item_id, color_id, provider, provider_kind, provider_key, status, method, origin, evidence_digest, build_id)"
                      " VALUES(?, NULL, 'bricklink', ?, ?, 'matched', 'external_ids', 'shipped', 'e', 2)", (item, kind, key))
        for inv, version, latest, parts, figs in ((1, 1, 0, [(SHEET_PART, 3), (11, 3)], []), (2, 2, 1, [(SHEET_ALT, 3), (16, 3)], [FIG])):
            c.execute("INSERT INTO inventory VALUES(?, ?, ?, ?, ?, NULL, 1, ?, NULL, ?, ?, 0, NULL)",
                      (inv, SET, version, version, latest, f'inv{inv}', len(parts), len(figs)))
            c.executemany('INSERT INTO inventory_part VALUES(?, ?, ?, 0, 2)', [(inv, i, col) for i, col in parts])
            c.executemany('INSERT INTO inventory_figure VALUES(?, ?, 1)', [(inv, f) for f in figs])
        c.commit()


@contextmanager
def opened(tmp_path, *statements):
    """Fixture files plus the extra catalogue, then `statements` run on the catalogue before the pair is opened."""
    col, cat = pair(tmp_path)
    add_catalogue(cat)
    with closing(sqlite3.connect(cat)) as c:
        for sql in statements:
            c.execute(sql)
        c.commit()
    with closing(connect(col, cat)) as db:
        yield db


@pytest.fixture
def env(tmp_path):
    with opened(tmp_path) as db:
        yield db


def q(db, sql, *args):
    return [tuple(r) for r in db.execute(sql, args)]


def parts(db, fid):
    return sorted(q(db, 'SELECT item_id, color_id, is_spare, quantity FROM main.fetched_inventory_part WHERE fetched_inventory_id=?', fid))


def test_extras_become_spares_that_sum_to_the_bricklink_quantity(env):
    r = bs.load_subsets(env, SET, '6081-1', reply(entry('3023', 5, 10, 3), entry('3626', 11, 4)))
    assert (r.required_lines, r.spare_lines, r.required_total, r.spare_total) == (2, 1, 11, 3)
    assert r.required_total + r.spare_total == 14                           # BrickLink said 10 + 4
    assert parts(env, r.fetched_id) == [(11, 3, 0, 7), (11, 3, 1, 3), (16, 4, 0, 4)]
    assert q(env, 'SELECT source, seq, is_latest, part_lines, figure_lines FROM main.fetched_inventory') == [('bricklink', 1, 1, 3, 0)]


def test_a_required_line_at_zero_is_dropped_and_the_spare_kept(env):
    r = bs.load_subsets(env, SET, '6081-1', reply(entry('3023', 5, 2, 2), entry('3626', 11, 1)))
    assert (r.required_lines, r.spare_lines) == (1, 1)
    assert parts(env, r.fetched_id) == [(11, 3, 1, 2), (16, 4, 0, 1)]


def test_duplicate_entries_are_summed_by_type_number_and_colour(env):
    r = bs.load_subsets(env, SET, '6081-1', reply(entry('3023', 5, 2, 1), entry('3023', 5, 3, 0), entry('3023', 11, 1), entry('3023', 5, 4, 2)))
    assert parts(env, r.fetched_id) == [(11, 3, 0, 6), (11, 3, 1, 3), (11, 4, 0, 1)]


def test_counterparts_alternates_and_other_types_are_skipped_and_counted(env):
    r = bs.load_subsets(env, SET, '6081-1', reply(entry('3023', 5, 1), entry('3626', 5, 9, is_counterpart=True), entry('3626', 5, 9, is_alternate=True),
                                                  entry('3626', 11, 2, is_alternate=True, is_counterpart=True), entry('x1', None, 1, type='BOOK'),
                                                  entry('x2', None, 1, type='GEAR'), entry('x3', None, 1, type='BOOK')))
    assert parts(env, r.fetched_id) == [(11, 3, 0, 1)]
    assert r.skipped == {'alternate': 2, 'counterpart': 2, 'type:BOOK': 2, 'type:GEAR': 1}


def test_figure_lines_keep_required_and_count_the_dropped_extras(env):
    r = bs.load_subsets(env, SET, '6081-1', reply(entry('3023', 5, 1), entry('cas001', None, 3, 1, type='MINIFIG'), entry('cas002', None, 1, 1, type='MINIFIG')))
    assert (r.figure_lines, r.figure_total, r.figure_extras_dropped) == (1, 2, 2)
    assert q(env, 'SELECT item_id, quantity FROM main.fetched_inventory_figure') == [(FIG, 2)]    # cas002 had nothing left, so no item either
    assert env.execute("SELECT count(*) FROM main.item WHERE born_key='cas002'").fetchone()[0] == 0


BAD = [({'item': {'no': 'a b', 'type': 'PART'}, 'quantity': 1, 'color_id': 5}, 'item number'),
       ({'item': {'no': '', 'type': 'PART'}, 'quantity': 1, 'color_id': 5}, 'item number'),
       ({'item': {'no': 'x' * 41, 'type': 'PART'}, 'quantity': 1, 'color_id': 5}, 'item number'),
       ({'item': {'no': 3023, 'type': 'PART'}, 'quantity': 1, 'color_id': 5}, 'item number'),
       ({'item': {'no': '3023', 'type': 'PART'}, 'quantity': 0, 'color_id': 5}, 'quantity'),
       ({'item': {'no': '3023', 'type': 'PART'}, 'quantity': 1.5, 'color_id': 5}, 'quantity'),
       ({'item': {'no': '3023', 'type': 'PART'}, 'quantity': True, 'color_id': 5}, 'quantity'),
       ({'item': {'no': '3023', 'type': 'PART'}, 'quantity': 1, 'extra_quantity': 2, 'color_id': 5}, 'extra'),
       ({'item': {'no': '3023', 'type': 'PART'}, 'quantity': 1, 'extra_quantity': -1, 'color_id': 5}, 'extra'),
       ({'item': {'no': '3023', 'type': 'PART'}, 'quantity': 1, 'extra_quantity': '1', 'color_id': 5}, 'extra'),
       ({'item': {'no': '3023', 'type': 'PART'}, 'quantity': 1}, 'colour'),
       ({'item': {'no': '3023', 'type': 'PART'}, 'quantity': 1, 'color_id': -1}, 'colour'),
       ({'item': {'no': '3023', 'type': 'PART'}, 'quantity': 1, 'color_id': '5'}, 'colour'),
       ({'quantity': 1, 'color_id': 5}, 'no item')]


@pytest.mark.parametrize('bad, why', BAD)
def test_invalid_entries_are_refused_with_nothing_written(env, bad, why):
    with pytest.raises(InventoryError, match=why):
        bs.load_subsets(env, SET, '6081-1', {'data': [{'entries': [entry('3626', 11, 1), bad]}]})
    assert q(env, 'SELECT count(*) FROM main.fetched_inventory') == [(0,)]
    assert q(env, 'SELECT count(*) FROM main.source_record') == [(0,)]


@pytest.mark.parametrize('data', [None, {}, 'x', [1], [{'entries': 3}], [{}]])
def test_malformed_replies_are_refused(env, data):
    with pytest.raises(InventoryError):
        bs.parse_subsets(data)


def test_empty_and_unusable_lists_are_refused(env):
    for body in ([], [{'match_no': 0, 'entries': []}], reply(entry('3023', 5, 1, is_counterpart=True))['data'], reply(entry('3023', 5, 2, 2, type='PART'))['data'][:0]):
        with pytest.raises(InventoryError, match='no usable lines'):
            bs.load_subsets(env, SET, '6081-1', {'data': body})
    with pytest.raises(InventoryError):
        bs.load_subsets(env, SET, '6081-1', ['not a reply'])
    assert q(env, 'SELECT count(*) FROM main.source_record') == [(0,)]


def test_a_dotted_sticker_sheet_number_is_valid():
    assert bs.parse_subsets(reply(entry('312.3stk01', 0, 1))['data']).part_lines == [('312.3stk01', 0, 0, 1)]


def test_names_are_unescaped():
    assert bs.parse_subsets(reply(entry('3023', 5, 1, name='Plate &#40;1 x 2&#41; &amp; more'))['data']).names == {('P', '3023'): 'Plate (1 x 2) & more'}


def test_bricklink_colour_zero_falls_back_to_no_colour(env):
    r = bs.load_subsets(env, SET, '6081-1', reply(entry('3023', 0, 2)))
    assert parts(env, r.fetched_id) == [(11, 1, 0, 2)]
    assert r.local_colours_created == 0


def test_bricklink_colour_zero_uses_the_catalogues_link_when_there_is_one(tmp_path):
    col, cat = pair(tmp_path)
    with closing(sqlite3.connect(cat)) as c:
        c.execute("INSERT INTO color_link(color_id, provider, provider_key, provider_name, status, method, origin, inverse_preferred, build_id)"
                  " VALUES(1, 'bricklink', '0', '(Not Applicable)', 'matched', 'external_ids', 'shipped', 0, 2)")
        c.commit()
    with closing(connect(col, cat)) as db:
        r = bs.load_subsets(db, SET, '6081-1', reply(entry('3023', 0, 2)))
        assert parts(db, r.fetched_id) == [(11, 1, 0, 2)]
        assert bs.parse_subsets(reply(entry('3023', 0, 2))['data']).bl_lines == [('P', '3023', None, 0, 2)]


def test_an_unknown_bricklink_colour_becomes_one_local_colour(env):
    first = bs.load_subsets(env, SET, '6081-1', reply(entry('3023', 999, 2), entry('3626', 999, 1)))
    assert first.local_colours_created == 1
    colour = env.execute("SELECT id, name FROM main.color WHERE born_key='999'").fetchone()
    assert (colour[0], colour[1]) == (LOCAL, 'BrickLink colour 999')
    assert parts(env, first.fetched_id) == [(11, LOCAL, 0, 2), (16, LOCAL, 0, 1)]
    second = bs.load_subsets(env, SET, '6081-1', reply(entry('3023', 999, 2), entry('3626', 999, 1)))
    assert second.local_colours_created == 0 and q(env, "SELECT count(*) FROM main.color WHERE id>=?", LOCAL) == [(1,)]
    assert second.digest == first.digest


def test_a_shared_colour_with_no_preference_refuses_the_whole_list(tmp_path):
    with opened(tmp_path, 'UPDATE color_link SET inverse_preferred=0 WHERE provider_key=\'72\'') as db:
        with pytest.raises(InventoryError, match='BrickLink colour 72 is shared'):
            bs.load_subsets(db, SET, '6081-1', reply(entry('3023', 5, 1), entry('3626', 72, 1)))
        assert q(db, 'SELECT count(*) FROM main.fetched_inventory') == [(0,)]
        # with the preference in place the same colour resolves to the preferred one
    (tmp_path / 'again').mkdir()
    with opened(tmp_path / 'again') as db:
        r = bs.load_subsets(db, SET, '6081-1', reply(entry('3626', 72, 1)))
        assert parts(db, r.fetched_id) == [(16, 6, 0, 1)]


def test_a_linked_part_resolves_through_the_catalogue_and_is_projected(env):
    r = bs.load_subsets(env, SET, '6081-1', reply(entry('3023', 5, 2)))
    assert q(env, 'SELECT origin FROM main.item WHERE id=11') == [('catalogue',)]
    assert q(env, 'SELECT origin FROM main.item WHERE id=?', SET) == [('catalogue',)]      # the catalogue set was projected too
    assert r.local_items_created == {'part': 0, 'minifigure': 0}


def test_leg_rule_resolves_by_colour(env):
    r = bs.load_subsets(env, SET, '6081-1', reply(entry('970c00', 11, 1), entry('970c00', 5, 1)))
    assert parts(env, r.fetched_id) == [(12, 4, 0, 1), (13, 3, 0, 1)]                      # Black legs for Black, red legs for Red


def test_an_unlinked_part_becomes_a_local_item_with_a_matched_link(env):
    r = bs.load_subsets(env, SET, '6081-1', reply(entry('zz-9', 5, 2, name='Odd &amp; new'), entry('zz-9', 11, 1)))
    item = env.execute("SELECT * FROM main.item WHERE born_key='zz-9'").fetchone()
    assert (item['id'], item['origin'], item['kind'], item['born_provider'], item['born_namespace'], item['name']) == \
        (LOCAL, 'local', 'part', 'bricklink', 'P', 'Odd & new')
    assert q(env, 'SELECT provider, provider_kind, provider_key, status, method, origin, color_id FROM main.item_link WHERE item_id=?', LOCAL) == \
        [('bricklink', 'P', 'zz-9', 'matched', 'bricklink_api', 'api', None)]
    assert parts(env, r.fetched_id) == [(LOCAL, 3, 0, 2), (LOCAL, 4, 0, 1)]               # one item for both colours
    assert (r.local_items_created, r.local_items_reused) == ({'part': 1, 'minifigure': 0}, {'part': 0, 'minifigure': 0})
    again = bs.load_subsets(env, SET, '6081-1', reply(entry('zz-9', 5, 2)))
    assert (again.local_items_created, again.local_items_reused) == ({'part': 0, 'minifigure': 0}, {'part': 1, 'minifigure': 0})
    assert q(env, 'SELECT count(*) FROM main.item WHERE id>=?', LOCAL) == [(1,)]


def test_an_ambiguous_key_is_settled_by_the_sets_inventories(env):
    # 310.3stk01 names 003402 (14) and 999001 (19); 14 is in version 1 of the set, 19 in none
    r = bs.load_subsets(env, SET, '6081-1', reply(entry('310.3stk01', 5, 1), entry('311.1stk01', 5, 2)))
    assert parts(env, r.fetched_id) == [(SHEET_PART, 3, 0, 3)]                  # 311.1stk01 has one candidate and needs no context
    assert (r.ambiguous_by_context, r.ambiguous_made_local) == (1, 0)
    assert q(env, 'SELECT count(*) FROM main.item WHERE id>=?', LOCAL) == [(0,)]
    assert q(env, "SELECT count(*) FROM main.item_link WHERE status='to_check'") == [(0,)]


def test_the_context_is_any_inventory_version(tmp_path):
    # 312.3stk01 names 003402 (14, in version 1) and 003402b (18, in version 2): both are in some version, so it stays open
    with opened(tmp_path) as db:
        assert bs.load_subsets(db, SET, '6081-1', reply(entry('312.3stk01', 5, 1))).ambiguous_made_local == 1
    # drop 003402 from the set's inventories: only 18 is in context now and settles it
    (tmp_path / 'b').mkdir()
    with opened(tmp_path / 'b', 'DELETE FROM inventory_part WHERE item_id=14') as db:
        r = bs.load_subsets(db, SET, '6081-1', reply(entry('312.3stk01', 5, 1)))
        assert (r.ambiguous_by_context, r.ambiguous_made_local) == (1, 0)
        assert parts(db, r.fetched_id) == [(SHEET_ALT, 3, 0, 1)]


def test_an_ambiguous_key_the_context_cannot_settle_becomes_local_with_to_check_links(env):
    # 312.3stk01 names 003402 (14) and 003402b (18); versions 1 and 2 of the set hold one each
    r = bs.load_subsets(env, SET, '6081-1', reply(entry('312.3stk01', 5, 2, name='Sheet')))
    assert (r.ambiguous_by_context, r.ambiguous_made_local) == (0, 1)
    assert parts(env, r.fetched_id) == [(LOCAL, 3, 0, 2)]
    links = q(env, 'SELECT provider, provider_kind, provider_key, status, method, origin FROM main.item_link WHERE item_id=? ORDER BY status, provider_key', LOCAL)
    assert links == [('bricklink', 'P', '312.3stk01', 'matched', 'bricklink_api', 'api'),
                     ('rebrickable', 'parts', '003402', 'to_check', 'bricklink_api_ambiguous', 'api'),
                     ('rebrickable', 'parts', '003402b', 'to_check', 'bricklink_api_ambiguous', 'api')]
    evidence = env.execute("SELECT evidence_json FROM main.item_link WHERE status='to_check'").fetchone()[0]
    assert '"set": "6081-1"' in evidence and '312.3stk01' in evidence and '003402b' in evidence


def test_a_local_item_made_for_an_ambiguous_key_is_stable_on_reload(env):
    body = reply(entry('312.3stk01', 5, 2), entry('312.3stk01', 11, 1), entry('3023', 5, 1))
    first = bs.load_subsets(env, SET, '6081-1', body)
    snapshot = (q(env, 'SELECT id FROM main.item WHERE id>=?', LOCAL), q(env, 'SELECT id, item_id, provider_key, status FROM main.item_link ORDER BY id'))
    second = bs.load_subsets(env, SET, '6081-1', body)
    assert (second.seq, first.seq) == (2, 1) and second.digest == first.digest
    assert (second.ambiguous_by_context, second.ambiguous_made_local) == (0, 1)
    assert second.local_items_created == {'part': 0, 'minifigure': 0} and second.local_items_reused == {'part': 1, 'minifigure': 0}
    assert snapshot == (q(env, 'SELECT id FROM main.item WHERE id>=?', LOCAL), q(env, 'SELECT id, item_id, provider_key, status FROM main.item_link ORDER BY id'))


def test_projecting_one_candidate_does_not_make_the_key_unambiguous_for_the_next_set(env):
    from brickwork.store4 import identity
    identity.project(env, SHEET_ALT)                                    # an earlier list settled 312.3stk01 elsewhere and projected 003402b
    r = bs.load_subsets(env, SET, '6081-1', reply(entry('312.3stk01', 5, 1)))
    assert (r.ambiguous_made_local, parts(env, r.fetched_id)[0][0] >= LOCAL) == (1, True)       # still both candidates, not the projected one


def test_a_set_without_catalogue_inventories_has_no_context(env):
    other = fetched.create_local_item(env, kind='set', born_provider='rebrickable', born_namespace='sets', born_key='9000-1', name='New')
    r = bs.load_subsets(env, other, '9000-1', reply(entry('310.3stk01', 5, 1)))
    assert r.ambiguous_made_local == 1 and r.ambiguous_by_context == 0
    assert q(env, "SELECT provider_key FROM main.item_link WHERE status='to_check' ORDER BY provider_key") == [('003402',), ('999001',)]


def test_a_minifig_line_resolves_through_its_m_link_and_otherwise_is_a_local_figure(env):
    r = bs.load_subsets(env, SET, '6081-1', reply(entry('3023', 5, 1), entry('cas001', None, 2, type='MINIFIG'), entry('cas777', None, 1, type='MINIFIG', name='New Knight')))
    figs = dict(q(env, 'SELECT item_id, quantity FROM main.fetched_inventory_figure'))
    assert figs[FIG] == 2 and len(figs) == 2
    local = env.execute("SELECT id, kind, name, born_namespace FROM main.item WHERE born_key='cas777'").fetchone()
    assert (local['id'], local['kind'], local['name'], local['born_namespace']) == (LOCAL, 'minifigure', 'New Knight', 'M')
    assert q(env, 'SELECT provider_kind, provider_key, status FROM main.item_link WHERE item_id=?', LOCAL) == [('M', 'cas777', 'matched')]
    assert r.local_items_created == {'part': 0, 'minifigure': 1}
    assert q(env, 'SELECT count(*) FROM main.fetched_inventory_part WHERE item_id=?', LOCAL) == [(0,)]                # a figure has no list here


def test_two_loads_are_seq_1_and_2_with_the_same_digest_and_one_source_record(env):
    body = reply(entry('3023', 5, 4, 1), entry('cas001', None, 1, type='MINIFIG'))
    a = bs.load_subsets(env, SET, '6081-1', body, job_id=None)
    b = bs.load_subsets(env, SET, '6081-1', body)
    assert (a.seq, b.seq, a.digest == b.digest) == (1, 2, True)
    assert q(env, 'SELECT seq, is_latest FROM main.fetched_inventory ORDER BY seq') == [(1, 0), (2, 1)]
    assert q(env, 'SELECT count(*), min(kind), min(key) FROM main.source_record') == [(1, 'subsets', '6081-1')]
    assert q(env, 'SELECT source_record_id FROM main.fetched_inventory')[0] == q(env, 'SELECT source_record_id FROM main.fetched_inventory')[1]
    stored = env.execute('SELECT payload FROM main.source_record').fetchone()[0]
    assert '"extra_quantity": 1' in stored                                                  # the whole reply is kept


def test_a_failure_mid_load_leaves_nothing(tmp_path):
    # the colour step runs first: 999 becomes a local colour before the shared, unpreferred 72 refuses the list
    with opened(tmp_path, "UPDATE color_link SET inverse_preferred=0 WHERE provider_key='72'") as db:
        with pytest.raises(InventoryError):
            bs.load_subsets(db, SET, '6081-1', reply(entry('a-new', 999, 1), entry('b-new', 72, 1)))
        assert q(db, 'SELECT count(*) FROM main.source_record') == [(0,)]
        assert q(db, 'SELECT count(*) FROM main.item WHERE id>=?', LOCAL) == [(0,)]
        assert q(db, 'SELECT count(*) FROM main.color WHERE id>=?', LOCAL) == [(0,)]
        assert q(db, 'SELECT count(*) FROM main.fetched_inventory') == [(0,)]


def test_a_failure_after_local_items_exist_rolls_them_back(env, monkeypatch):
    def boom(*a, **k):
        raise sqlite3.OperationalError('disk full')
    monkeypatch.setattr(fetched, 'write_fetched', boom)                    # fails after the local item and the source record exist
    with pytest.raises(sqlite3.OperationalError):
        bs.load_subsets(env, SET, '6081-1', reply(entry('zz-9', 5, 1), entry('cas001', None, 1, type='MINIFIG')))
    assert q(env, 'SELECT count(*) FROM main.source_record') == [(0,)]
    assert q(env, 'SELECT count(*) FROM main.item WHERE id>=?', LOCAL) == [(0,)]
    assert q(env, "SELECT count(*) FROM main.item_link WHERE provider_key='zz-9'") == [(0,)]
    assert env.in_transaction                                              # the caller's transaction is still its own
    env.rollback()


def test_the_bricklink_digest_is_compared_with_every_catalogue_version(env):
    lines = [('P', '3023', '5', 0, 3), ('P', '3626', '11', 0, 3)]
    with closing(sqlite3.connect(env.execute('PRAGMA database_list').fetchall()[-1][2])) as c:
        c.execute('UPDATE inventory SET bl_digest=? WHERE id=2', (bl_digest([('P', '3023', '5', 0, 3), ('P', '3626', '11', 0, 3), ('M', 'cas001', None, 0, 1)]),))
        c.commit()
    hit = bs.load_subsets(env, SET, '6081-1', reply(entry('3023', 5, 3), entry('3626', 11, 3), entry('cas001', None, 1, type='MINIFIG')))
    assert (hit.bl_digest_matches, hit.matches_version) == (True, 2)
    miss = bs.load_subsets(env, SET, '6081-1', reply(entry('3023', 5, 3), entry('3626', 11, 3)))
    assert (miss.bl_digest_matches, miss.matches_version) == (False, None)
    spare = bs.load_subsets(env, SET, '6081-1', reply(entry('3023', 5, 4, 1), entry('3626', 11, 3), entry('cas001', None, 2, 1, type='MINIFIG')))
    assert spare.bl_digest_matches is False                                                  # spares are part of the comparison
    assert bs.parse_subsets(reply(entry('3023', 5, 3), entry('3626', 11, 3))['data']).bl_lines == lines


def test_a_set_that_is_not_a_set_or_not_known_is_refused(env):
    with pytest.raises(InventoryError, match='neither'):
        bs.load_subsets(env, 424242, 'x-1', reply(entry('3023', 5, 1)))
    with pytest.raises(InventoryError, match='not a set'):
        bs.load_subsets(env, 11, 'x-1', reply(entry('3023', 5, 1)))
    assert q(env, 'SELECT count(*) FROM main.source_record') == [(0,)]


def test_events_are_written_for_what_the_load_creates(env):
    ev = Events(env, 'api', 'test')
    bs.load_subsets(env, SET, '6081-1', reply(entry('zz-9', 999, 1)), events=ev)
    kinds = {(r[0], r[1]) for r in env.execute('SELECT entity_kind, field FROM main.event')}
    assert {('item', 'created'), ('color', 'created'), ('fetched_inventory', 'created'), ('item_link', 'created')} <= kinds


def test_exhaustive_resolution_pools_both_stores_but_a_manual_link_decides_alone(env):
    from brickwork.store4 import identity
    identity.project(env, ONLY_PART)                                        # 310.3stk01: 999001 projected, 003402 only in the catalogue
    assert identity.resolve_inverse(env, 'P', '310.3stk01', '5')[0] == ONLY_PART                       # the old answer, blind to 003402
    with pytest.raises(bs.AmbiguousIdentity) as exc:
        identity.resolve_inverse(env, 'P', '310.3stk01', '5', exhaustive=True)
    assert exc.value.items == (SHEET_PART, ONLY_PART)
    env.execute("UPDATE main.item_link SET status='manual', origin='user' WHERE item_id=? AND provider_key='310.3stk01'", (ONLY_PART,))
    assert identity.resolve_inverse(env, 'P', '310.3stk01', '5', exhaustive=True)[0] == ONLY_PART


def test_a_manual_link_beats_the_sets_context(env):
    from brickwork.store4 import identity
    identity.project(env, SHEET_PART)
    identity.project(env, ONLY_PART)                                        # both 310.3stk01 candidates projected
    env.execute("UPDATE main.item_link SET status='manual', origin='user' WHERE item_id=? AND provider_key='310.3stk01'", (ONLY_PART,))
    r = bs.load_subsets(env, SET, '6081-1', reply(entry('310.3stk01', 5, 1)))  # the context has only 003402 (14)
    assert parts(env, r.fetched_id) == [(ONLY_PART, 3, 0, 1)]
    assert r.ambiguous_by_context == 0


def test_a_colour_that_projection_would_flip_is_refused(env):
    from brickwork.store4 import identity
    identity.project_color(env, 7)                                          # Maersk Blue holds BrickLink 72 without the preference
    env.commit()
    with pytest.raises(InventoryError, match='reconcile'):
        bs.load_subsets(env, SET, '6081-1', reply(entry('3023', 72, 1)))     # Pastel Blue (6) is the catalogue's preferred 72
    env.rollback()
    assert q(env, 'SELECT count(*) FROM main.fetched_inventory') == [(0,)]
    assert q(env, 'SELECT count(*) FROM main.color WHERE id=6') == [(0,)]
