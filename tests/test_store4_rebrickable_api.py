"""A set fetched through the Rebrickable API: paging, call counts, local Rebrickable-born items, fetched lists, adoption by the next
dump (design 3.1, 4.2, 4.5, 6.5). All replies are invented."""
from contextlib import closing
import json
import sqlite3
from urllib.parse import parse_qs, urlparse

import pytest

from brickwork.store4 import fetched, rebrickable_api as ra
from brickwork.store4.activate import activate
from brickwork.store4.audit import Events
from brickwork.store4.bldigest import inventory_digest
from brickwork.store4.connect import connect
from brickwork.store4.errors import Store4Error
from brickwork.store4.fetched import InventoryError
from brickwork.store4.reconcile import reconcile
from tests.store4_dump import default
from tests.store4_fixtures import pair
from tests.test_store4_builder import activated, ids, rows, run

LOCAL = 1_000_000_000
SET = 'NEW-1'


def part(num, colour=4, quantity=1, spare=False, name=None, colour_name='Red'):
    return {'id': 1, 'inv_part_id': 1, 'part': {'part_num': num, 'name': name or f'name {num}', 'part_cat_id': 1},
            'color': {'id': colour, 'name': colour_name, 'rgb': 'C91A09', 'is_trans': False}, 'set_num': SET, 'quantity': quantity,
            'is_spare': spare, 'element_id': None, 'num_sets': 1}


def figure(num, quantity=1, name=None):
    return {'id': 1, 'set_num': num, 'set_name': name or f'name {num}', 'quantity': quantity, 'set_img_url': None}


class Fake:
    """An injectable `http`: serves invented data by path, splits list endpoints into pages of `size`, records every URL."""

    def __init__(self, set_parts=(), minifigs=(), figure_parts=None, size=1000, set_status=200, set_num=SET):
        self.size, self.urls, self.set_status, self.set_num = size, [], set_status, set_num
        self.data = {f'/sets/{set_num}/parts/': list(set_parts), f'/sets/{set_num}/minifigs/': list(minifigs)}
        for fig, lines in (figure_parts or {}).items():
            self.data[f'/minifigs/{fig}/parts/'] = list(lines)

    def __call__(self, url, headers):
        assert headers['Authorization'] == 'key test-key'
        self.urls.append(url)
        u = urlparse(url)
        path = u.path[len('/api/v3/lego'):]
        q = parse_qs(u.query)
        if path == f'/sets/{self.set_num}/':
            if self.set_status != 200:
                return self.set_status, {'detail': 'Not found.'}
            return 200, {'set_num': self.set_num, 'name': 'Fetched Set', 'year': 2026, 'theme_id': 1, 'num_parts': 7}
        if path not in self.data:
            return 404, {'detail': 'Not found.'}
        rows_, page = self.data[path], int(q.get('page', ['1'])[0])
        size = min(int(q.get('page_size', ['1000'])[0]), self.size)
        chunk = rows_[(page - 1) * size:page * size]
        more = page * size < len(rows_)
        base = f'{ra.BASE}{path}?page_size={q.get("page_size", ["1000"])[0]}'
        if 'inc_minifig_parts' in q:
            base += f'&inc_minifig_parts={q["inc_minifig_parts"][0]}'
        return 200, {'count': len(rows_), 'next': f'{base}&page={page + 1}' if more else None, 'previous': None, 'results': chunk}


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv(ra.KEY_ENV, 'test-key')


@pytest.fixture
def db(tmp_path):
    """The invented catalogue (3023 is 11, 3626 is 16, colour Red is 3 and Black 4) and a collection that activated it."""
    col, cat = pair(tmp_path)
    with closing(connect(col, cat)) as conn:
        conn.commit()
        yield conn


def fetch(http, db, set_num=SET, **kw):
    return ra.fetch_set_replies(set_num, http=http, catalogue_has_figure=ra.catalogue_figure_check(db), **kw)


def q(db, sql, *args):
    return [tuple(r) for r in db.execute(sql, args)]


def lines(db, fid):
    return sorted(q(db, 'SELECT item_id, color_id, is_spare, quantity FROM main.fetched_inventory_part WHERE fetched_inventory_id=?', fid))


# ---------- the fetch ----------

def test_pages_are_followed_and_joined(db):
    http = Fake(set_parts=[part('3023', 4, 1), part('3626', 0, 2), part('3023', 15, 3)], minifigs=[], size=2)
    replies = fetch(http, db)
    assert [len(p['results']) for p in replies.pages[f'/sets/{SET}/parts/']] == [2, 1]
    assert replies.calls == 4 and len(http.urls) == 4                    # set, two parts pages, minifigs
    assert ra._joined(replies.pages[f'/sets/{SET}/parts/'])['results'] == http.data[f'/sets/{SET}/parts/']


def test_set_parts_are_asked_without_figure_parts_and_with_the_big_page_size(db):
    http = Fake(set_parts=[part('3023')])
    fetch(http, db)
    assert http.urls[0] == f'{ra.BASE}/sets/{SET}/'
    assert 'inc_minifig_parts=0' in http.urls[1] and 'page_size=1000' in http.urls[1]


def test_calls_are_three_plus_one_per_figure_the_catalogue_lacks(db):
    figs = [figure('fig-000001'), figure('fig-new1'), figure('fig-new2', 2)]      # fig-000001 is not in the base fixture: add it below
    http = Fake(set_parts=[part('3023')], minifigs=figs, figure_parts={'fig-000001': [part('3023')], 'fig-new1': [part('3023')], 'fig-new2': [part('3626', 0)]})
    assert fetch(http, db).calls == 3 + 3                                  # the fixture catalogue has no figure at all
    with closing(sqlite3.connect(db.execute('PRAGMA database_list').fetchall()[-1][2])) as c:
        c.execute("INSERT INTO item(id, kind, kind_source, name, name_key, size_key, year, num_parts, build_id, born_provider, born_namespace,"
                  " born_key, digest) VALUES(20, 'minifigure', 'namespace', 'King Leo', 'king leo', '', 1993, 4, 1, 'rebrickable', 'minifigs', 'fig-000001', 'd')")
        c.commit()
    http = Fake(set_parts=[part('3023')], minifigs=figs, figure_parts={'fig-new1': [part('3023')], 'fig-new2': [part('3626', 0)]})
    replies = fetch(http, db)
    assert replies.calls == 3 + 2 and not any('fig-000001/parts' in u for u in http.urls)
    assert 'fig-000001' not in ' '.join(replies.pages)


def test_three_calls_when_every_figure_is_in_the_catalogue_or_there_are_none(db):
    assert fetch(Fake(set_parts=[part('3023')]), db).calls == 3
    assert fetch(Fake(set_parts=[part('3023')]), db, headers={'Authorization': 'key test-key'}).calls == 3
    assert ra.fetch_set_replies(SET, http=Fake(set_parts=[part('3023')], minifigs=[figure('fig-1')]), catalogue_has_figure=lambda f: True).calls == 3


def test_a_missing_set_is_not_found(db):
    with pytest.raises(ra.NotFound) as exc:
        fetch(Fake(set_status=404), db)
    assert exc.value.status == 404 and isinstance(exc.value, ra.FetchError)


@pytest.mark.parametrize('status', [401, 429, 500])
def test_other_failures_are_fetch_errors_with_the_status(db, status):
    with pytest.raises(ra.FetchError) as exc:
        fetch(Fake(set_status=status), db)
    assert exc.value.status == status and not isinstance(exc.value, ra.NotFound)


def test_a_next_link_off_the_api_is_refused(db):
    def http(url, headers):
        if url.endswith(f'/sets/{SET}/'):
            return 200, {}
        return 200, {'results': [], 'next': 'https://evil.example/x'}
    with pytest.raises(ra.FetchError):
        fetch(http, db)


def test_the_default_http_needs_the_key_and_never_puts_it_in_a_message(monkeypatch, db):
    monkeypatch.delenv(ra.KEY_ENV)
    with pytest.raises(ra.FetchError) as exc:
        ra.fetch_set_replies(SET, catalogue_has_figure=lambda f: True)
    assert ra.KEY_ENV in str(exc.value)


def test_the_default_http_waits_a_second_between_calls():
    slept, now = [], [100.0]
    h = ra.UrllibHttp(clock=lambda: now[0], sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
    h.last = 99.6
    h.timeout = 0.001
    try:
        h('http://127.0.0.1:9/', {})
    except ra.FetchError:
        pass
    assert slept and 0.59 < slept[0] < 0.61


def test_replies_round_trip_through_json(db):
    replies = fetch(Fake(set_parts=[part('3023')]), db)
    again = ra.Replies.from_json(replies.to_json())
    assert (again.set_num, again.pages, again.calls) == (replies.set_num, replies.pages, replies.calls)


# ---------- the load ----------

def load(db, http=None, **kw):
    replies = fetch(http, db) if not isinstance(http, ra.Replies) else http
    result = ra.load_rebrickable_set(db, SET, replies, **kw)
    db.commit()
    return result


def test_the_set_is_refused_when_the_catalogue_has_it(db):
    replies = fetch(Fake(set_parts=[part('3023')]), db)
    replies.pages['/sets/6081-1/'] = [{'set_num': '6081-1', 'name': 'King Leo Castle', 'year': 1993, 'num_parts': 3}]
    replies.pages['/sets/6081-1/parts/'] = replies.pages[f'/sets/{SET}/parts/']
    replies.pages['/sets/6081-1/minifigs/'] = replies.pages[f'/sets/{SET}/minifigs/']
    with pytest.raises(ra.SetInCatalogue):
        ra.load_rebrickable_set(db, '6081-1', ra.Replies('6081-1', replies.pages), events=None)
    assert q(db, 'SELECT count(*) FROM main.fetched_inventory') == [(0,)] and q(db, 'SELECT count(*) FROM main.source_record') == [(0,)]


def test_the_set_is_refused_when_the_collection_holds_it_as_a_catalogue_item(db):
    replies = fetch(Fake(set_parts=[part('3023')]), db)
    db.execute("INSERT INTO main.item(id, origin, kind, kind_source, name, born_provider, born_namespace, born_key, catalogue_build_id, created_at, updated_at)"
               " VALUES(5000, 'catalogue', 'set', 'namespace', 'x', 'rebrickable', 'sets', ?, 1, 't', 't')", (SET,))
    with pytest.raises(ra.SetInCatalogue):
        ra.load_rebrickable_set(db, SET, replies)


def test_a_new_set_gets_local_items_and_catalogue_parts_are_projected(db):
    http = Fake(set_parts=[part('3023', 4, 2), part('newpart', 4, 3, name='A New Part')], minifigs=[figure('fig-new', 2, 'New Fig')],
                figure_parts={'fig-new': [part('3626', 0, 1), part('newpart', 0, 2)]})
    r = load(db, http)
    assert r.set_item_id == LOCAL and (r.seq, r.calls, r.provider_version) == (1, 4, None)
    assert q(db, 'SELECT origin, kind, name, year, num_parts, born_provider, born_namespace, born_key FROM main.item WHERE id=?', LOCAL) == [
        ('local', 'set', 'Fetched Set', 2026, 7, 'rebrickable', 'sets', SET)]
    local = q(db, 'SELECT id, kind, name, born_namespace, born_key FROM main.item WHERE id>=? AND id>?', LOCAL, LOCAL)
    assert local == [(LOCAL + 1, 'part', 'A New Part', 'parts', 'newpart'), (LOCAL + 2, 'minifigure', 'New Fig', 'minifigs', 'fig-new')]
    assert q(db, 'SELECT origin FROM main.item WHERE id IN (11, 16) ORDER BY id') == [('catalogue',), ('catalogue',)]     # 3023 and 3626 projected
    assert r.local_items_created == {'set': 1, 'part': 1, 'minifigure': 1} and r.local_items_reused == {'set': 0, 'part': 0, 'minifigure': 0}
    assert r.items_projected == 2                                           # 3023 from the set's list, 3626 from the figure's
    assert lines(db, r.fetched_id) == [(11, 3, 0, 2), (LOCAL + 1, 3, 0, 3)]
    assert q(db, 'SELECT item_id, quantity FROM main.fetched_inventory_figure WHERE fetched_inventory_id=?', r.fetched_id) == [(LOCAL + 2, 2)]
    (fig_list,) = r.figure_lists
    assert fig_list.item_id == LOCAL + 2 and fig_list.part_lines == 2
    assert lines(db, fig_list.fetched_id) == [(16, 4, 0, 1), (LOCAL + 1, 4, 0, 2)]
    assert q(db, 'SELECT source, seq, is_latest, part_lines, figure_lines FROM main.fetched_inventory WHERE item_id=?', LOCAL + 2) == [('rebrickable_api', 1, 1, 2, 0)]
    assert r.digest == q(db, 'SELECT digest FROM main.fetched_inventory WHERE id=?', r.fetched_id)[0][0]
    assert r.digest == inventory_digest([(11, 3, 0, 2), (LOCAL + 1, 3, 0, 3)], [(LOCAL + 2, 2)])
    assert r.matches_version is None and fig_list.matches_version is None


def test_no_item_links_are_written_for_the_new_local_items(db):
    load(db, Fake(set_parts=[part('newpart')], minifigs=[figure('fig-new')], figure_parts={'fig-new': [part('newpart')]}))
    assert q(db, 'SELECT count(*) FROM main.item_link WHERE item_id>=?', LOCAL) == [(0,)]


def test_the_colour_comes_from_the_catalogue_by_its_rebrickable_id(db):
    r = load(db, Fake(set_parts=[part('3023', 0), part('3023', 4), part('3023', 15)]))        # Black, Red, White are 4, 3, 5
    assert lines(db, r.fetched_id) == [(11, 3, 0, 1), (11, 4, 0, 1), (11, 5, 0, 1)]
    assert q(db, 'SELECT count(*) FROM main.color WHERE id>=?', LOCAL) == [(0,)]


def test_an_unknown_colour_refuses_the_list_and_writes_nothing(db):
    before = q(db, 'SELECT count(*) FROM main.item')
    with pytest.raises(InventoryError, match="download today's catalogue"):
        load(db, Fake(set_parts=[part('3023', 4), part('newpart', 4), part('3626', 9999 + 1, colour_name='Brand New')],
                      minifigs=[figure('fig-new')], figure_parts={'fig-new': [part('3023', 4)]}))
    assert q(db, 'SELECT count(*) FROM main.item') == before
    for table in ('fetched_inventory', 'fetched_inventory_part', 'source_record'):
        assert q(db, f'SELECT count(*) FROM main.{table}') == [(0,)]
    assert q(db, 'SELECT count(*) FROM main.color WHERE id>=?', LOCAL) == [(0,)]            # no local colour: those are BrickLink-only


def test_duplicate_keys_are_summed_and_spares_stay_spares(db):
    r = load(db, Fake(set_parts=[part('3023', 4, 2), part('3023', 4, 3), part('3023', 4, 1, spare=True), part('3626', 0, 1, spare=True)]))
    assert lines(db, r.fetched_id) == [(11, 3, 0, 5), (11, 3, 1, 1), (16, 4, 1, 1)]
    assert (r.part_lines, r.spare_lines, r.part_total, r.spare_total, r.duplicates_summed) == (1, 2, 5, 2, 1)


def test_a_figure_the_catalogue_has_is_projected_and_not_fetched(db):
    with closing(sqlite3.connect(db.execute('PRAGMA database_list').fetchall()[-1][2])) as c:
        c.execute("INSERT INTO item(id, kind, kind_source, name, name_key, size_key, year, num_parts, build_id, born_provider, born_namespace,"
                  " born_key, digest) VALUES(20, 'minifigure', 'namespace', 'King Leo', 'king leo', '', 1993, 4, 1, 'rebrickable', 'minifigs', 'fig-000001', 'd')")
        c.commit()
    http = Fake(set_parts=[part('3023')], minifigs=[figure('fig-000001', 3), figure('fig-new')], figure_parts={'fig-new': [part('3023')]})
    r = load(db, http)
    assert r.calls == 4 and [f.fig_num for f in r.figure_lists] == ['fig-new']
    assert q(db, 'SELECT item_id, quantity FROM main.fetched_inventory_figure WHERE fetched_inventory_id=? ORDER BY item_id', r.fetched_id) == [(20, 3), (LOCAL + 1, 1)]
    assert q(db, 'SELECT origin FROM main.item WHERE id=20') == [('catalogue',)]
    assert q(db, 'SELECT count(*) FROM main.fetched_inventory WHERE item_id=20') == [(0,)]


def test_a_missing_figure_parts_reply_refuses_the_list(db):
    replies = fetch(Fake(set_parts=[part('3023')], minifigs=[figure('fig-new')], figure_parts={'fig-new': [part('3023')]}), db)
    del replies.pages['/minifigs/fig-new/parts/']
    with pytest.raises(InventoryError, match='fig-new'):
        ra.load_rebrickable_set(db, SET, replies)
    assert q(db, 'SELECT count(*) FROM main.item WHERE id>=?', LOCAL) == [(0,)]


def test_source_records_one_per_endpoint_with_pages_joined_and_linked(db):
    http = Fake(set_parts=[part('3023', 4, 1), part('3626', 0, 1), part('3023', 15, 1)], minifigs=[figure('fig-new')], figure_parts={'fig-new': [part('3023')]}, size=2)
    r = load(db, http)
    got = q(db, "SELECT source, kind, key, id FROM main.source_record ORDER BY id")
    assert [g[:3] for g in got] == [('rebrickable', 'set', SET), ('rebrickable', 'set_parts', SET), ('rebrickable', 'set_minifigs', SET),
                                    ('rebrickable', 'minifig_parts', 'fig-new')]
    parts_payload = json.loads(q(db, 'SELECT payload FROM main.source_record WHERE kind=?', 'set_parts')[0][0])
    assert len(parts_payload['results']) == 3 and 'next' not in parts_payload
    assert q(db, 'SELECT source_record_id FROM main.fetched_inventory WHERE id=?', r.fetched_id) == [(got[1][3],)]
    assert q(db, 'SELECT source_record_id FROM main.fetched_inventory WHERE id=?', r.figure_lists[0].fetched_id) == [(got[3][3],)]
    assert json.dumps(http.data) and 'key' not in json.dumps([g[2] for g in got])           # no key anywhere in what is stored
    assert 'test-key' not in ' '.join(x[0] for x in q(db, 'SELECT payload FROM main.source_record'))


def test_a_second_load_is_seq_two_on_the_same_items(db):
    http = Fake(set_parts=[part('newpart', 4, 1)], minifigs=[figure('fig-new')], figure_parts={'fig-new': [part('newpart', 0)]})
    first = load(db, http)
    second = load(db, http)
    assert (second.set_item_id, first.seq, second.seq, second.digest) == (first.set_item_id, 1, 2, first.digest)
    assert second.local_items_created == {'set': 0, 'part': 0, 'minifigure': 0} and second.local_items_reused == {'set': 1, 'part': 1, 'minifigure': 1}
    assert second.figure_lists[0].item_id == first.figure_lists[0].item_id and second.figure_lists[0].seq == 2
    assert q(db, 'SELECT seq, is_latest FROM main.fetched_inventory WHERE item_id=? ORDER BY seq', LOCAL) == [(1, 0), (2, 1)]
    assert q(db, 'SELECT count(*) FROM main.item WHERE id>=?', LOCAL) == [(3,)]
    assert q(db, 'SELECT count(*) FROM main.source_record') == [(4,)]                       # the same replies are kept once


def test_a_failure_mid_load_leaves_nothing(db, monkeypatch):
    real = fetched.write_fetched
    def boom(db_, item, source, *a, **kw):
        if item != LOCAL:
            raise RuntimeError('disk full')                                              # the figure's list, after the set's
        return real(db_, item, source, *a, **kw)
    monkeypatch.setattr(fetched, 'write_fetched', boom)
    http = Fake(set_parts=[part('newpart')], minifigs=[figure('fig-new')], figure_parts={'fig-new': [part('newpart')]})
    replies = fetch(http, db)
    with pytest.raises(RuntimeError):
        ra.load_rebrickable_set(db, SET, replies)
    db.commit()
    for table in ('fetched_inventory', 'source_record'):
        assert q(db, f'SELECT count(*) FROM main.{table}') == [(0,)]
    assert q(db, 'SELECT count(*) FROM main.item WHERE id>=?', LOCAL) == [(0,)]


def test_a_reply_for_another_set_is_refused(db):
    replies = fetch(Fake(set_parts=[part('3023')]), db)
    replies.pages[f'/sets/{SET}/'] = [{'set_num': 'OTHER-1', 'name': 'x'}]
    with pytest.raises(InventoryError):
        ra.load_rebrickable_set(db, SET, replies)


@pytest.mark.parametrize('bad', [part('3023', quantity=0), part('3023', quantity='2'), {**part('3023'), 'is_spare': 1},
                                 {**part('3023'), 'color': {'name': 'x'}}, {**part('3023'), 'part': {'name': 'x'}}])
def test_invalid_lines_are_refused(db, bad):
    with pytest.raises(InventoryError):
        load(db, Fake(set_parts=[bad]))
    assert q(db, 'SELECT count(*) FROM main.item WHERE id>=?', LOCAL) == [(0,)]


def test_events_are_written_on_request(db):
    load(db, Fake(set_parts=[part('newpart')]), events=Events(db, 'api', 'tester'))
    kinds = [r[0] for r in q(db, 'SELECT DISTINCT entity_kind FROM main.event')]
    assert sorted(kinds) == ['fetched_inventory', 'item']


# ---------- done when: a set fetched before the dump keeps its id when the dump adopts it ----------

def test_done_when_a_set_fetched_before_the_dump_keeps_its_id_when_the_dump_adopts_it(tmp_path):
    t = default()                                           # the first dump knows neither the set, nor its part, nor its newer figure
    t['sets'] = [s for s in t['sets'] if s[0] != '9999-1']
    t['inventories'] = [i for i in t['inventories'] if i[2] != '9999-1']
    t['inventory_sets'] = []
    t['minifigs'] = [f for f in t['minifigs'] if f[0] != 'fig-000002']
    t['inventory_minifigs'] = [m for m in t['inventory_minifigs'] if m[1] != 'fig-000002']
    _, cat = run(tmp_path, 'd1', **t)
    col = activated(tmp_path, cat, ref_keys=('6081-1',))
    num = '9999-1'
    http = Fake(set_num=num, set_parts=[part('3001', 0, 1), part('newpart', 4, 2, name='New Part'), part('3023', 4, 1, spare=True)],
                minifigs=[figure('fig-000002', 2, 'Soldier')],
                figure_parts={'fig-000002': [part('3023', 4, 1), part('newpart', 0, 1)]})
    with closing(connect(col, cat)) as db:
        result = ra.load_rebrickable_set(db, num, fetch(http, db, num))
        db.commit()
        fetched_ids = {result.set_item_id: result.fetched_id, result.figure_lists[0].item_id: result.figure_lists[0].fetched_id}
        local_ids = {k: i for i, k in db.execute("SELECT id, born_key FROM main.item WHERE id>=?", (LOCAL,))}
        digest_before = {i: d for i, d in db.execute('SELECT item_id, digest FROM main.fetched_inventory')}
    assert local_ids == {'9999-1': LOCAL, 'newpart': LOCAL + 1, 'fig-000002': LOCAL + 2} and result.calls == 4
    # The next dump has all three, with the same lists.
    t2 = default()
    t2['parts'] = t2['parts'] + [('newpart', 'New Part', '5', 'Plastic')]
    t2['inventory_sets'] = []
    t2['inventory_parts'] = t2['inventory_parts'] + [(3, 'newpart', 4, 2, 'False', ''), (3, '3023', 4, 1, 'True', ''),
                                                     (6, '3023', 4, 1, 'False', ''), (6, 'newpart', 0, 1, 'False', '')]
    t2['inventory_parts'] = [p for p in t2['inventory_parts'] if p[:2] != (3, '3001')] + [(3, '3001', 0, 1, 'False', '')]
    t2['inventories'] = t2['inventories'] + [(6, 1, 'fig-000002')]
    t2['inventory_minifigs'] = t2['inventory_minifigs'] + [(3, 'fig-000002', 2)]
    report, _ = run(tmp_path, 'd2', collection=col, **t2)
    assert report['counts']['adopted'] == 3
    got = ids(cat)
    assert (got['9999-1'], got['newpart'], got['fig-000002']) == (LOCAL, LOCAL + 1, LOCAL + 2)
    assert [r['adopted'] for r in rows(cat, "SELECT adopted FROM item WHERE born_key IN ('9999-1', 'newpart', 'fig-000002')")] == [1, 1, 1]
    with closing(connect(col, cat)) as db:
        activate(db)
        recon = reconcile(db)
        db.commit()
        assert sorted(recon['adopted']) == [LOCAL, LOCAL + 1, LOCAL + 2]
        assert q(db, "SELECT id, origin FROM main.item WHERE id>=? ORDER BY id", LOCAL) == [(LOCAL, 'catalogue'), (LOCAL + 1, 'catalogue'), (LOCAL + 2, 'catalogue')]
        assert {i: f for i, f in db.execute('SELECT item_id, id FROM main.fetched_inventory')} == fetched_ids      # the lists hang on the same ids
        assert {i: d for i, d in db.execute('SELECT item_id, digest FROM main.fetched_inventory')} == digest_before
        # the fetched list equals the adopted catalogue inventory, for the set and for the figure
        for item, fetched_id in fetched_ids.items():
            cat_digest = db.execute('SELECT digest FROM catalogue.inventory WHERE item_id=? AND is_latest=1', (item,)).fetchone()[0]
            assert cat_digest == db.execute('SELECT digest FROM main.fetched_inventory WHERE id=?', (fetched_id,)).fetchone()[0]
        assert ra._catalogue_version(db, LOCAL, result.digest) == 1


def test_a_replayed_page_without_results_is_refused(db):
    replies = fetch(Fake(set_parts=[part('3023', 4)], minifigs=[figure('fig-new')], figure_parts={'fig-new': [part('3023', 4)]}), db)
    replies.pages[f'/sets/{SET}/minifigs/'] = [{'count': 1}]
    with pytest.raises(InventoryError, match='no results list'):
        ra.load_rebrickable_set(db, SET, replies)
    assert q(db, 'SELECT count(*) FROM main.fetched_inventory') == [(0,)]


def test_a_truncated_reply_is_a_fetch_error(monkeypatch):
    import http.client
    import urllib.request

    class Truncated:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            raise http.client.IncompleteRead(b'{"set', 100)

    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **kw: Truncated())
    with pytest.raises(ra.FetchError):
        ra.UrllibHttp(spacing=0)('https://rebrickable.com/api/v3/lego/sets/x/', {})
