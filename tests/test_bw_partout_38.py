"""#38 part-out value on the 4.0 store (M.8g, issue #110): present parts and whole figures at the used quote, with coverage. Invented data.

The API's copy read is in tests/test_api2_read_collection.py (M.11b)."""
from decimal import Decimal

from bs4 import BeautifulSoup

from brickwork.core import partout
from brickwork.core.sources.base import now
from tests.app4 import STAMP, app4, client, coll, pair, read, world  # noqa: F401 (fixtures)


def quote(coll, item, value, *, colour=None):
    coll.price(item, value, colour=colour, region='eu', currency='EUR', observed=now().isoformat())


def small_copy(coll):
    """A copy with one set line (3001 red: 4, 2 missing) and one figure line (1 of 1 missing), nothing else."""
    brick, red, figure = coll.item('parts', '3001'), coll.colour('4'), coll.item('minifigs', 'fig-000004')
    keep = coll.project(coll.item('sets', '1000-1'))
    coll.project(brick), coll.project(figure)
    coll.setting('bricklink_region', 'eu')
    coll.setting('bricklink_currency', 'EUR')
    coll.sql("INSERT INTO copy(id,item_id,inventory_source,inventory_digest,condition,created_at,updated_at) VALUES('c1',?,'migrated','d','used',?,?)",
             (keep, STAMP, STAMP))
    coll.sql('INSERT INTO copy_part(copy_id,item_id,color_id,quantity,missing) VALUES(?,?,?,4,2)', ('c1', brick, red))
    coll.sql("INSERT INTO copy_figure(copy_id,item_id,inventory_source,inventory_digest,quantity,missing,updated_at) VALUES('c1',?,'none','d',1,1,?)", (figure, STAMP))
    return brick, red, figure


def test_value_coverage_and_hint(coll, read):
    brick, red, figure = small_copy(coll)
    quote(coll, brick, '2.50', colour=red)
    with read() as db:
        # 3001 red needs 4, 2 missing -> 2 present at 2.50; the figure is needed once and missing: 0 present, so no line.
        result = partout.values(db, ['c1'])['c1']
    assert (result['value'], result['lines'], result['priced'], result['unpriced_count']) == ('5.00', 1, 1, 0)
    coll.sql('UPDATE copy_figure SET missing=0')
    with read() as db:
        result = partout.values(db, ['c1'])['c1']
        assert (result['lines'], result['priced'], result['unpriced'][0]) == (2, 1, dict(item_id=figure, color_id=None))
        # One of two lines priced is not enough for a total: no value, the unpriced items for a refresh.
        assert result['value'] is None and not result['enough'] and result['unpriced_items'] == [figure]
        compared = partout.compare(dict(complete_quote={'price': '30'}, current_value='2.00'), result)
        assert compared['partout'] is None and compared['hint'] is None and compared['unpriced_items'] == [figure]
        full = dict(result, value='5.00', enough=True)
        compared = partout.compare(dict(complete_quote={'price': '30'}, current_value='2.00'), full)
        assert compared['partout'] == '5.00' and compared['as_is'] == '2.00' and compared['complete'] == '30.00' and compared['hint'] is None     # 3.00 more is under the 5.00 floor
        assert partout.compare(dict(complete_quote={'price': '30'}, current_value='2.00'), dict(full, value='9.00'))['hint'] == '7.00'
        assert partout.compare(dict(complete_quote=None, current_value='4.50'), full)['hint'] is None
        assert partout.values(db, []) == {}


def test_a_total_when_every_line_is_priced_and_what_counts(coll, read):
    brick, red, figure = small_copy(coll)
    coll.sql('UPDATE copy_figure SET missing=0')
    plate, white = coll.item('parts', '3023'), coll.colour('15')
    coll.project(plate)
    coll.sql('INSERT INTO copy_part(copy_id,item_id,color_id,quantity,missing) VALUES(?,?,?,2,0)', ('c1', plate, white))
    coll.sql('INSERT INTO copy_part(copy_id,item_id,color_id,quantity,missing,is_spare) VALUES(?,?,?,9,0,1)', ('c1', plate, coll.colour('4')))      # a spare is no line
    coll.sql("UPDATE copy_part SET retired_at=? WHERE copy_id='c1' AND color_id=?", (STAMP, white))                                              # a retired line is no line
    coll.sql('INSERT INTO copy_part(copy_id,item_id,color_id,quantity,missing) VALUES(?,?,?,1,0)', ('c1', plate, coll.colour('14')))
    quote(coll, brick, '2.50', colour=red)
    quote(coll, figure, '8.00')
    quote(coll, plate, '0.10', colour=coll.colour('14'))
    with read() as db:
        result = partout.values(db, ['c1'])['c1']
    assert (result['lines'], result['priced'], result['enough']) == (3, 3, True)
    assert Decimal(result['value']) == Decimal('2.50') * 2 + Decimal('8.00') + Decimal('0.10')
    assert result['currency'] == 'EUR'


def test_a_stale_quote_counts_with_age_but_a_foreign_quote_does_not(coll, read):
    brick, red, figure = small_copy(coll)
    coll.sql('UPDATE copy_figure SET missing=0')
    coll.price(brick, '2.50', colour=red, region='eu', currency='USD', observed=now().isoformat())
    coll.price(figure, '8.00', region='eu', currency='EUR', observed='2026-01-01T00:00:00+00:00')
    coll.sql("INSERT OR REPLACE INTO source_freshness(source,kind,max_age_days) VALUES('bricklink','prices',30)")
    with read() as db:
        result = partout.values(db, ['c1'])['c1']
    assert result['priced'] == 1 and result['unpriced_count'] == 1
    assert result['oldest_observed'] == '2026-01-01T00:00:00+00:00'
    assert figure in result['unpriced_items']  # old cached prices can be refreshed


def test_coverage_threshold():
    assert partout.COVERAGE == 0.9


def test_partout_on_set_detail_and_complete_sets(world, client, monkeypatch):
    monkeypatch.setattr(partout, 'values', lambda db, ids: {i: dict(value='141.00', currency='EUR', lines=340, priced=312,
                                                                     unpriced=[], unpriced_count=28) for i in ids})
    monkeypatch.setattr(partout, 'compare', lambda copy, value: dict(partout='141.00', currency='EUR', lines=340, priced=312,
                                                                      complete='120.00', as_is='84.00', hint='57.00'))
    card = BeautifulSoup(client.get(f'/collection/item/{world.keep}?copy={world.copy_a}').data, 'html.parser').select_one('[data-bc-partout]')
    text = ' '.join(card.get_text(' ').split())
    assert '≈ €141.00' in text and 'Complete €120.00 · as is €84.00 · prices for 312 of 340 lines' in text
    assert 'Parting out is worth €57.00 more' in text
    page = BeautifulSoup(client.get('/planning/complete-sets').data, 'html.parser')
    assert page.select_one('[data-bp-sort] option[value=partout]').get_text() == 'Part-out value'


def test_partout_card_from_the_stored_prices_on_the_item_page(coll, client):
    brick, red, figure = small_copy(coll)
    coll.sql('UPDATE copy_figure SET missing=0')
    quote(coll, brick, '2.50', colour=red)
    quote(coll, figure, '8.00')
    quote(coll, coll.item('sets', '1000-1'), '100.00')
    page = BeautifulSoup(client.get(f'/collection/item/{coll.item("sets", "1000-1")}?copy=c1').data, 'html.parser')
    text = ' '.join(page.select_one('[data-bc-partout]').get_text(' ').split())
    assert '≈ €13.00' in text and 'prices for 2 of 2 lines' in text and 'Complete €100.00' in text
    assert 'Parting out is worth' not in text                                               # 13 is far below the 70 the copy is worth as is


def test_pending_card_offers_fetch_part_prices(world, client, app4, monkeypatch):
    monkeypatch.setattr(partout, 'compare', lambda copy, value: dict(partout=None, currency='EUR', lines=54, priced=4, hint=None,
                                                                      complete=None, as_is=None, unpriced_items=[world.brick, world.plate]))
    monkeypatch.setitem(app4.jinja_env.globals, 'bw_key_missing', lambda source: False)  # fetching prices needs a BrickLink key
    card = BeautifulSoup(client.get(f'/collection/item/{world.keep}?copy={world.copy_a}').data, 'html.parser').select_one('[data-bc-partout]')
    text = ' '.join(card.get_text(' ').split())
    assert 'Not enough prices yet' in text and 'prices for 4 of 54 lines' in text and '≈' not in text
    button = card.select_one('[data-bc-fetch-prices]')
    assert button.get_text() == 'Fetch part prices' and button['data-bc-fetch-prices'] == f'[{world.brick}, {world.plate}]'
    assert button['data-refresh-url'] == '/planning/action/refresh'
    assert 'bc-outline' in button['class'] and 'primary' not in button['class']


def test_a_complete_copy_is_worth_its_complete_value_as_is(coll, client):
    # #123: the incomplete-set discount applies only to a copy with a gap (a missing or damaged line, a missing figure).
    brick, red, figure = small_copy(coll)
    coll.sql('UPDATE copy_figure SET missing=0')
    coll.sql('UPDATE copy_part SET missing=0')
    coll.sql('INSERT INTO copy_part(copy_id,item_id,color_id,quantity,missing,is_spare) VALUES(?,?,?,1,1,1)', ('c1', brick, coll.colour('15')))  # a missing spare is no gap
    quote(coll, brick, '2.50', colour=red)
    quote(coll, figure, '8.00')
    quote(coll, coll.item('sets', '1000-1'), '100.00')

    def card():
        page = BeautifulSoup(client.get(f'/collection/item/{coll.item("sets", "1000-1")}?copy=c1').data, 'html.parser')
        return ' '.join(page.select_one('[data-bc-partout]').get_text(' ').split())
    assert 'Complete €100.00 · as is €100.00' in card()
    coll.sql("UPDATE copy_part SET damaged=1 WHERE is_spare=0")
    assert 'Complete €100.00 · as is €70.00' in card()
    coll.sql("UPDATE copy_part SET damaged=0")
    coll.sql('UPDATE copy_figure SET missing=1')
    assert 'Complete €100.00 · as is €70.00' in card()
    # A figure's own part missing is no gap of the set, as in the completeness rule (Codex review).
    coll.sql('UPDATE copy_figure SET missing=0')
    coll.sql("INSERT INTO copy_part(copy_id,item_id,color_id,quantity,missing,copy_figure_id) SELECT 'c1',?,?,1,1,id FROM copy_figure", (brick, coll.colour('14')))
    assert 'Complete €100.00 · as is €100.00' in card()


def test_the_items_a_refresh_could_fetch_are_read_once_for_all_copies(coll, read):
    """M.11b: the Complete sets list asks for the part-out value of every copy; it must not cost a read per copy."""
    brick, red, figure = small_copy(coll)
    coll.sql('UPDATE copy_figure SET missing=0')
    for n in range(2, 8):
        coll.sql("INSERT INTO copy(id,item_id,inventory_source,inventory_digest,condition,created_at,updated_at) VALUES(?,?,'migrated','d','used',?,?)",
                 (f'c{n}', coll.item('sets', '1000-1'), STAMP, STAMP))
        coll.sql('INSERT INTO copy_part(copy_id,item_id,color_id,quantity,missing) VALUES(?,?,?,4,1)', (f'c{n}', brick, red))
    counted = []
    with read() as db:
        one = partout.values(db, ['c1'])
        db.set_trace_callback(counted.append)
        partout.values(db, ['c1'])
        few = len(counted)
        counted.clear()
        many = partout.values(db, [f'c{n}' for n in range(1, 8)])
        assert len(counted) == few
    assert one['c1']['unpriced_items'] == many['c1']['unpriced_items'] == [brick, figure]
    assert all(v['unpriced_items'] == [brick] for k, v in many.items() if k != 'c1')


def test_oldest_price_used_and_configured_age(coll, read):
    from datetime import timedelta
    brick, red, figure = small_copy(coll)
    coll.sql('UPDATE copy_figure SET missing=0')
    oldest = (now() - timedelta(days=3)).isoformat()
    coll.price(brick, '2.50', colour=red, region='eu', currency='EUR', observed=oldest)
    quote(coll, figure, '8.00')
    coll.sql("INSERT OR REPLACE INTO source_freshness(source,kind,max_age_days) VALUES('bricklink','prices',2)")
    with read() as db:
        result = partout.values(db, ['c1'])['c1']
    assert result['oldest_observed'] == oldest and result['stale']
    assert result['value'] == '13.00'
    coll.sql("UPDATE source_freshness SET max_age_days=4 WHERE source='bricklink' AND kind='prices'")
    with read() as db:
        assert not partout.values(db, ['c1'])['c1']['stale']
    coll.sql('DELETE FROM price_current')
    with read() as db:
        result = partout.values(db, ['c1'])['c1']
    assert result['oldest_observed'] is None and not result['stale']


def test_one_currency_per_total_and_no_comparison(coll, read, client):
    brick, red, _ = small_copy(coll)
    coll.price(brick, '76.00', colour=red, region='eu', currency='USD', observed=now().isoformat())
    quote(coll, coll.item('sets', '1000-1'), '120.00')
    with read() as db:
        result = partout.values(db, ['c1'])['c1']
    assert result['value'] == '152.00' and result['currency'] == 'USD'
    compared = partout.compare(dict(complete_quote=dict(price='120', currency='EUR'), current_value='84'), result)
    assert compared['no_comparison'] and compared['complete'] is None and compared['as_is'] is None and compared['hint'] is None
    page = BeautifulSoup(client.get(f'/collection/item/{coll.item("sets", "1000-1")}?copy=c1').data, 'html.parser')
    text = page.select_one('[data-bc-partout]').get_text(' ', strip=True)
    assert '$152.00' in text and '€' not in text
    assert 'Part prices are in US dollars, so no comparison with the euro prices above.' in text
    assert 'Complete' not in text and 'as is' not in text and 'worth' not in text


def test_card_order_age_access_and_no_inventory(world, client, app4, monkeypatch):
    result = dict(partout='141.00', currency='EUR', lines=145, priced=138, complete='120.00', as_is='84.00',
                  hint='57.00', oldest_observed='2026-10-12T08:00:00Z', stale=False, unpriced_items=[world.brick])
    monkeypatch.setattr(partout, 'compare', lambda *a: result)
    monkeypatch.setattr('brickwork.core.collection.retail', lambda *a: dict(country='AT', price='49.00', currency='EUR'))
    monkeypatch.setitem(app4.jinja_env.globals, 'bw_key_missing', lambda source: False)
    def card():
        page = BeautifulSoup(client.get(f'/collection/item/{world.keep}?copy={world.copy_a}').data, 'html.parser')
        return page.select_one('[data-module=prices]')
    filled = card()
    assert filled.select_one('[data-bc-partout]').find_previous_sibling().has_attr('data-bc-condition-prices')
    assert filled.select_one('[data-bc-partout]').find_next_sibling().has_attr('data-bc-retail')
    assert '12 Oct' in filled.select_one('[data-bc-partout]').get_text()
    assert not filled.select_one('.bc-partout-stale')
    result['stale'] = True
    assert card().select_one('.bc-partout-stale').get_text() == 'stale'
    result.update(partout=None, complete=None, as_is=None, hint=None, oldest_observed=None, stale=False, priced=4)
    pending = card()
    assert pending.select_one('[data-bc-partout]').find_previous_sibling().has_attr('data-bc-condition-prices')
    assert pending.select_one('[data-bc-partout]').find_next_sibling().has_attr('data-bc-retail')
    assert not pending.select_one('.bc-partout-stale')
    monkeypatch.setitem(app4.jinja_env.globals, 'bw_key_missing', lambda source: True)
    no_key = card()
    assert no_key.select_one('[data-bc-partout] button').has_attr('disabled')
    assert 'Needs a BrickLink key' not in no_key.select_one('[data-bc-partout]').get_text()
    monkeypatch.setattr('brickwork.web.views.bw_collection_editable', lambda: False)
    viewer = card()
    assert not viewer.select_one('[data-bc-partout] button')
    assert 'Update price' not in viewer.get_text()
    monkeypatch.setattr(partout, 'compare', lambda *a: None)
    assert not card().select_one('[data-bc-partout]')


def test_complete_sets_line_is_visible_below_gap_and_wraps(world, client, monkeypatch):
    monkeypatch.setattr(partout, 'compare', lambda *a: dict(partout='141.00', currency='EUR', lines=145, priced=138, hint='57.00'))
    page = BeautifulSoup(client.get('/planning/complete-sets?sort=partout').data, 'html.parser')
    line = page.select_one('[data-bp-partout]')
    assert line and 'recorded gap' in line.find_previous_sibling().get_text()
    assert line.find_parent('details') is None
    assert line.name == 'p' and 'mono' in line['class']
    assert 'worth €57.00 more than as is' in line.get_text()
    assert page.select_one('[data-bp-partout-note]')
    monkeypatch.setattr(partout, 'compare', lambda *a: dict(partout=None, currency='EUR', lines=145, priced=4, hint=None))
    page = BeautifulSoup(client.get('/planning/complete-sets').data, 'html.parser')
    assert not page.select_one('[data-bp-partout]')
    assert 'Not enough prices yet' not in page.get_text()


def test_partout_fetch_runtime():
    import subprocess
    from pathlib import Path
    from tests import rendered
    rendered.need_node()
    subprocess.run(['node', str(Path(__file__).with_name('toni_bw_partout_runtime.cjs'))], check=True, capture_output=True, text=True)


def test_candidate_world_reaches_the_partout_states(tmp_path, client, app4, monkeypatch):
    from brickwork.demo import clock, dataset
    from scripts import screen_gate
    from brickwork.store4.connect import connect
    from contextlib import closing
    folder = tmp_path / 'candidate'
    folder.mkdir()
    store = folder / 'brickwork.db'
    screen_gate.build_store('edge-value', store)
    monkeypatch.setenv('BW_DB_PATH', str(store))
    monkeypatch.setitem(app4.jinja_env.globals, 'bw_key_missing', lambda source: False)
    patched = clock.freeze_clock()
    try:
        with closing(connect(store, catalogue=store.with_name('catalogue.db'), read_only=True)) as db:
            ids = {s: db.execute('SELECT id FROM copy WHERE item_id=? ORDER BY created_at,id LIMIT 1', (dataset.item_by(db, 'sets', n),)).fetchone()[0] for s,n in [('hint','99101-1'),('pending','99112-1'),('stale','99103-1'),('other-currency','99105-1')]}
            results = {s: partout.values(db, [i])[i] for s,i in ids.items()}
        import json
        from pathlib import Path
        states = json.loads(Path('design/screens/states.json').read_text())['states']
        for state, copy_id in ids.items():
            entry = next(e for e in states if e['screen']=='10-Set-detail' and e['state']=='partout-'+state)
            assert entry['path'].endswith('copy='+copy_id)
        assert results['hint']['value'] == '141.00'
        assert results['pending']['value'] is None
        assert results['stale']['stale']
        assert results['other-currency']['currency'] == 'USD'
        for state, number in [('hint', '99101-1'), ('pending', '99112-1'), ('stale', '99103-1'), ('other-currency', '99105-1')]:
            response = client.get(f'/collection/item/set/{number}?copy={ids[state]}', follow_redirects=True)
            assert response.status_code == 200
            card = BeautifulSoup(response.data, 'html.parser').select_one('[data-bc-partout]')
            assert card
            if state == 'hint': assert card.select_one('.bc-partout-hint')
            if state == 'pending': assert card.select_one('[data-bc-fetch-prices]')
            if state == 'stale': assert card.select_one('.bc-partout-stale')
            if state == 'other-currency': assert 'no comparison' in card.text
        sorted_page = BeautifulSoup(client.get('/planning/complete-sets?sort=partout').data, 'html.parser')
        assert sorted_page.select_one('[data-bp-partout]')
        demo = tmp_path / 'no-key'
        demo.mkdir()
        screen_gate.build_store('demo', demo / 'brickwork.db')
        monkeypatch.setenv('BW_DB_PATH', str(demo / 'brickwork.db'))
        monkeypatch.setitem(app4.jinja_env.globals, 'bw_key_missing', lambda source: True)
        page = BeautifulSoup(client.get('/collection/item/set/7286-1?copy=56325b99-16bc-549b-bb98-f7be2ab38829', follow_redirects=True).data, 'html.parser')
        assert page.select_one('[data-bc-partout] button[disabled]')
    finally:
        clock.thaw_clock(patched)



def test_no_inventory_has_no_parted_out_row(coll, read, client):
    small_copy(coll)
    coll.sql('DELETE FROM copy_part')
    coll.sql('DELETE FROM copy_figure')
    with read() as db:
        result = partout.values(db, ['c1'])['c1']
    assert result['lines'] == 0 and result['oldest_observed'] is None
    assert partout.compare({}, result) is None
    page = BeautifulSoup(client.get(f'/collection/item/{coll.item("sets", "1000-1")}?copy=c1').data, 'html.parser')
    assert not page.select_one('[data-bc-partout]')


def test_seed_preserves_statistics(tmp_path, monkeypatch):
    from scripts import screen_gate
    from brickwork.demo import gate_edge
    from brickwork.core import admin
    from brickwork.store4.connect import connect
    from contextlib import closing
    seed = gate_edge.seed_partout_frames
    monkeypatch.setattr(gate_edge, 'seed_partout_frames', lambda db: None)
    store = tmp_path / 'brickwork.db'
    screen_gate.build_store('edge-value', store)
    with closing(connect(store, catalogue=store.with_name('catalogue.db'))) as db:
        before = admin.statistics(db)
        copies = [tuple(r) for r in db.execute('SELECT * FROM copy ORDER BY id')]
        seed(db)
        assert admin.statistics(db) == before
        assert [tuple(r) for r in db.execute('SELECT * FROM copy ORDER BY id')] == copies


def test_foreign_override_is_not_compared(coll, client, monkeypatch):
    small_copy(coll)
    coll.sql("UPDATE copy SET current_value='84',current_value_currency='USD'")
    quote(coll, coll.item('sets', '1000-1'), '120')
    seen=[]
    original=partout.compare
    monkeypatch.setattr(partout,'compare',lambda row,value: (seen.append(row) or original(row,value)))
    client.get('/planning/complete-sets')
    assert seen and all(r.get('current_value') is None for r in seen)


def test_collection_comparison_uses_configured_currency(coll, client, monkeypatch):
    small_copy(coll)
    coll.price(coll.item('sets','1000-1'),'120',region='eu',currency='USD',observed=now().isoformat())
    seen=[]
    monkeypatch.setattr(partout,'compare',lambda row,value: seen.append(row))
    client.get(f'/collection/item/{coll.item("sets","1000-1")}?copy=c1')
    assert seen[0]['comparison_currency']=='EUR'


def test_unpriced_count_is_not_capped(coll, read, monkeypatch):
    small_copy(coll)
    monkeypatch.setattr(partout,'_summarize',lambda *a: dict(value=None,currency='EUR',lines=250,priced=0,enough=False,_unpriced_items=set(range(250))))
    monkeypatch.setattr(partout,'_refreshable',lambda db,ids: ids)
    with read() as db:
        result=partout.values(db,['c1'])['c1']
    assert len(result['unpriced_items'])==200
    assert result['unpriced_items_count']==250
