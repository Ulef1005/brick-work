"""Design 12 regression coverage that no module test owns (M.9, issue #111): the user journey replayed through the app's own writers
and the eight 3.3 lines of probes B5 and B6 through the real migration. `docs/data-model-4.0/regression-map.md` maps every check of the
design's three scripts to the test that guards it. Invented data, no network: every transport is a fake."""
from contextlib import closing
import json
import shutil

from cryptography.fernet import Fernet
import pytest

from brickwork.core import keys, pipeline
from brickwork.core.connect import connect
from brickwork.core.pipeline import Pipeline
from brickwork.store4 import jobs, migrate_run
from brickwork.store4.connect import connect as connect4
from tests.app4 import app4, client, make_pair, read  # noqa: F401 (fixtures)
from tests.sources4 import Net, Pictures, Router, keyed, price_reply, step_handlers, unkeyed
from tests.store4_mint_fixtures import FIXTURES, build_catalogue
from tests.test_store4_bricklink_subsets import entry, reply

# The journey's catalogue: set 6081-1 (Castle) with two copies of the figure fig-004576, the arch 2339 that BrickLink has no number for, and the
# loose waiter fig-018222 that the local composition file does not know. Rows are invented, in the shapes of the Rebrickable dump.
JOURNEY_DUMP = {
    'themes': [[600, 'Castle', '']],
    'sets': [['6081-1', 'Syn Mountain Fortress', 1990, 600, 11, '']],
    'parts': [['2339', 'Brick Arch 1 x 5 x 4', '11', 'Plastic']],
    'minifigs': [['fig-004576', 'Syn Knight - Black Legs', 4, ''], ['fig-018222', 'Syn Waiter, White Torso, Pink Legs', 4, '']],
    'inventories': [[9101, 1, '6081-1'], [9102, 1, 'fig-004576'], [9103, 1, 'fig-018222']],
    'inventory_parts': [[9101, '2339', 0, 2, 'False', ''], [9101, '3023', 0, 4, 'False', ''], [9101, '3023', 4, 1, 'False', ''],
                        [9101, '3023', 15, 1, 'False', ''], [9101, '3001', 4, 2, 'False', ''], [9101, '3001', 15, 1, 'True', ''],
                        [9102, '3626apr0001', 14, 1, 'False', ''], [9102, '3901', 6, 1, 'False', ''], [9102, '970c03', 0, 1, 'False', ''],
                        [9102, '973c27h01', 15, 1, 'False', ''],
                        [9103, '3626apr0001', 14, 1, 'False', ''], [9103, '3901', 6, 1, 'False', ''], [9103, '970c22', 4, 1, 'False', ''],
                        [9103, '973c27h01', 15, 1, 'False', '']],
    'inventory_minifigs': [[9101, 'fig-004576', 2]],
}
# the local composition file: the knight has a BrickLink number, the waiter (newer than the file) has none
JOURNEY_LOCAL = [['fig-004576', '', 'bricklink', 'M', 'syn-knight', 'matched', 'composition_leg_rule', '1']]
BRICKLINK_VALUES = dict(zip(('consumer_key', 'consumer_secret', 'token_value', 'token_secret'), ('ck-123456', 'cs-123456', 'tv-123456', 'ts-123456')))
STEPS = ('identity', 'inventory', 'matching', 'pictures', 'metadata', 'market_price')


@pytest.fixture
def pair(tmp_path):
    return make_pair(tmp_path, extra_dump=JOURNEY_DUMP, extra_local=JOURNEY_LOCAL)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    unkeyed(monkeypatch)
    from brickwork.core.sources import base
    monkeypatch.setattr(base, 'transport', lambda request: (_ for _ in ()).throw(AssertionError('network forbidden')))
    monkeypatch.setattr(base.time, 'sleep', lambda _: None)
    monkeypatch.setattr('brickwork.core.sources.images.transport', lambda request: (_ for _ in ()).throw(AssertionError('network forbidden')))


@pytest.fixture
def token(client):
    assert client.get('/manage/add').status_code == 200
    with client.session_transaction() as session:
        return session['bw_add_csrf']


def review(client, token, text, **data):
    return client.post('/manage/add/review', json=dict(csrf_token=token, type=data.pop('type', 'set'), where=data.pop('where', 'owned'),
                                                       mode='paste', text=text, **data)).json


def confirm(client, token, proposal, **edits):
    rows = json.loads(json.dumps(proposal['items']))
    for row in rows:
        row.update(edits)
    answer = client.post('/manage/add/confirm', json=dict(csrf_token=token, token=proposal['token'], items=rows))
    assert answer.status_code == 200, answer.get_data(as_text=True)
    return answer.json['receipts'][0]


def one(db, sql, *args):
    return db.execute(sql, args).fetchone()[0]


def item_of(db, namespace, key):
    return one(db, 'SELECT id FROM catalogue.item WHERE born_namespace=? AND born_key=?', namespace, key)


def run_item_job(db, job, **transports):
    """The pipeline job of an Add, through the source handlers with fake transports (design 2: pictures, metadata, market price)."""
    pl = Pipeline(db, handlers=step_handlers(**transports))
    pl.run(job)
    return {s['name']: (s['state'], s['error_code']) for s in pl.status(job)['steps']}


def test_the_user_journey_replays_through_the_apps_writers(tmp_path, client, token, read, pair, monkeypatch):
    """user-journey.md in order. Writers used: setup and `activate` (the pair fixture), `core.keys` (save, check), the Add routes (review,
    confirm: a set, loose parts, loose figures), the BrickLink part-list job and the pipeline's six steps with fake transports, and
    `core.identify.store`. Every row the journey names comes from one of them; the test writes none by SQL (the one setting and the one
    storage place are the Settings and Storage screens' rows, set directly). Where this file differs from user-journey.md the test asserts
    what the app does: the Brickognize link candidate is not written by
    `identify.store`, and a Brickset call without a key ends the metadata step `failed`. Ends with the foreign-key and integrity checks clean."""
    # --- 0 and 1.1: a fresh collection file (setup: freshness rules, the three system flags, the setup event), the catalogue activated
    from brickwork.web import admin_ops
    monkeypatch.setenv('BW_DB_PATH', str(pair))
    assert admin_ops.setup()['setup'] == 'ok'
    with read() as db:
        assert sorted(tuple(r) for r in db.execute("SELECT name, system FROM flag")) == [('Box present', 1), ('Instructions present', 1), ('Set is checked', 1)]
        assert one(db, "SELECT value FROM meta WHERE key='schema_version'") == '4.0' and one(db, "SELECT count(*) FROM meta WHERE key='install_id'") == 1
        assert [tuple(r) for r in db.execute('SELECT id, born_key FROM color WHERE id<=2 ORDER BY id')] == [(1, '9999'), (2, '-1')]
        assert one(db, "SELECT count(*) FROM source WHERE id='import'") == 1 and one(db, 'SELECT count(*) FROM wishlist') == 1
        assert one(db, 'SELECT count(*) FROM color') == one(db, 'SELECT count(*) FROM catalogue.color')                  # every colour projected
        assert one(db, 'SELECT count(*) FROM item') == 0 and one(db, 'SELECT count(*) FROM copy') == 0              # nothing but the dictionary
        assert sorted(tuple(r) for r in db.execute("SELECT entity_kind, field, via FROM event WHERE entity_kind!='flag'")) == [
            ('catalogue_build', 'activated', 'cli'), ('database', 'setup', 'cli')]
        assert one(db, 'SELECT count(*) FROM catalogue_build') == one(db, 'SELECT count(*) FROM catalogue.build') == 1
        assert one(db, "SELECT value FROM meta WHERE key='catalogue_id'") == one(db, "SELECT value FROM catalogue.meta WHERE key='catalogue_id'")

    # --- 1.2: a BrickLink key saved (encrypted, never in an event) and tested with the cheapest call
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    with closing(connect(pair)) as db:
        keys.save(db, 'bricklink', BRICKLINK_VALUES)
        net = Net({'meta': {'code': 200}, 'data': {'color_id': 1}})
        assert keys.check(db, 'bricklink', http=net)['ok'] is True
        stored = one(db, "SELECT ciphertext FROM source_key WHERE source='bricklink'")
        assert 'ck-123456' not in stored and not any('ck-123456' in (r[0] or '') for r in db.execute('SELECT new_value FROM event'))
        assert one(db, "SELECT count(*) FROM event WHERE entity_kind='source_key' AND entity_id='bricklink' AND field='save'") == 1
        assert len(net.requests) == 1 and '/colors/1' in net.requests[0].full_url

    # --- 2: an owned copy of 6081-1 through Add
    proposal = review(client, token, '6081-1')
    assert proposal['unresolved'] == [] and len(proposal['items']) == 1
    first = confirm(client, token, proposal, condition='used')
    copy_a = first['copies'][0]
    with read() as db:
        set_item = item_of(db, 'sets', '6081-1')
        copy = db.execute('SELECT * FROM copy WHERE id=?', (copy_a,)).fetchone()
        assert (copy['item_id'], copy['inventory_source'], copy['inventory_version'], copy['condition']) == (set_item, 'rebrickable', 1, 'used')
        figure = db.execute('SELECT * FROM copy_figure WHERE copy_id=?', (copy_a,)).fetchall()
        assert [(f['item_id'], f['quantity']) for f in figure] == [(item_of(db, 'minifigs', 'fig-004576'), 2)]
        set_lines = one(db, 'SELECT count(*) FROM copy_part WHERE copy_id=? AND copy_figure_id IS NULL', copy_a)
        figure_lines = one(db, 'SELECT count(*) FROM copy_part WHERE copy_id=? AND copy_figure_id IS NOT NULL', copy_a)
        assert (set_lines, figure_lines) == (6, 4) and one(db, 'SELECT sum(is_spare) FROM copy_part WHERE copy_id=?', copy_a) == 1
        assert one(db, 'SELECT sum(quantity) FROM copy_part WHERE copy_id=? AND copy_figure_id IS NOT NULL', copy_a) == 8        # 4 parts x 2 figures
        projected = {r['born_key'] for r in db.execute('SELECT born_key FROM item')}
        assert {'6081-1', 'fig-004576', '2339', '3023', '3001', '970c03'} <= projected and 'fig-018222' not in projected
        # the catalogue links of the projected items came with them (the leg rule, the shipped mapping, the local composition row)
        links = {(r['born_key'], r['provider_key'], r['color_id'] is not None) for r in db.execute(
            'SELECT i.born_key, l.provider_key, l.color_id FROM item_link l JOIN item i ON i.id=l.item_id')}
        assert ('3023', '3023', False) in links and ('970c03', '970c00', True) in links and ('970c03', '970c11', False) in links
        assert ('fig-004576', 'syn-knight', False) in links and ('2339', '2339', False) not in links                          # no number for 2339
        assert [r['field'] for r in db.execute("SELECT field FROM event WHERE entity_kind='add' AND entity_id=?", (first['batch'],))] == ['receipt']
        job = pipeline.Pipeline(db).status(first['job_id'])
        assert [s['name'] for s in job['steps']] == list(STEPS) and job['state'] == 'queued'

    # the job: local steps, the picture, the Brickset call without a key, the price guide
    pictures, replies = Pictures(), Router({'/items/SET/6081-1/price': price_reply(quantity=12, average='389.50')})
    keyed(monkeypatch, 'bricklink')
    with closing(connect(pair)) as db:
        got = run_item_job(db, first['job_id'], http=replies, image_http=pictures)
        assert got['identity'] == got['inventory'] == got['matching'] == ('done', None)
        assert got['market_price'] == ('done', None) and got['metadata'] == ('failed', 'source_not_configured')     # no Brickset key
        assert pictures.asked == ['https://img.bricklink.com/ItemImage/SN/0/6081-1.png']
        assert one(db, "SELECT count(*) FROM picture WHERE item_id=? AND source='bricklink'", set_item) == 1
        used = db.execute("SELECT * FROM price_observation WHERE item_id=? AND condition='used'", (set_item,)).fetchone()
        assert (used['source'], used['provider_key'], used['guide'], used['price']) == ('bricklink', 'S:6081-1', 'sold', '389.50')
        assert one(db, 'SELECT count(*) FROM price_current WHERE item_id=?', set_item) >= 1
        assert db.execute("SELECT status, method FROM item_link WHERE item_id=? AND provider_key='6081-1'", (set_item,)).fetchone()[:] == ('matched', 'bricklink_api')

    # --- 2.1: "prefer BrickLink" on and a key present: a second copy takes Rebrickable's list at once, BrickLink's is pending
    with closing(connect(pair)) as db:
        db.execute("INSERT OR REPLACE INTO setting(key, value) VALUES('prefer_bricklink_inventory', 'true')")
        db.commit()
    proposal = review(client, token, '6081-1')
    assert "Part list: BrickLink's" in proposal['items'][0]['import_notes'][0]
    second = confirm(client, token, proposal, decision='another', condition='used')
    copy_b = second['copies'][0]
    with read() as db:
        row = db.execute('SELECT * FROM copy WHERE id=?', (copy_b,)).fetchone()
        assert (row['inventory_source'], row['inventory_version'], row['inventory_pending']) == ('rebrickable', 1, 'bricklink')
        assert one(db, 'SELECT kind FROM job WHERE id=?', row['pending_job_id']) == 'bricklink_subsets'
        before = {(r['item_id'], r['color_id'], r['is_spare']): r['quantity'] for r in db.execute('SELECT * FROM copy_part WHERE copy_id=? AND copy_figure_id IS NULL', (copy_b,))}
    # the job succeeds with a list that differs from Rebrickable's by one line less (no red 3023) and one line more (a required white 3001 and its spare)
    monkeypatch.setitem(jobs._DEFAULT_HTTP, 'bricklink', lambda url, headers: (200, reply(
        entry('2339', 11, 2), entry('3023', 11, 4), entry('3023', 1, 1), entry('3001', 5, 2), entry('3001', 1, 2, extra=1))))
    with closing(connect(pair)) as db:
        jobs.drain(db)
        row = db.execute('SELECT * FROM copy WHERE id=?', (copy_b,)).fetchone()
        assert (row['inventory_source'], row['inventory_pending'], row['pending_job_id']) == ('bricklink', None, None)       # switched in place
        assert row['fetched_inventory_id'] is not None and row['inventory_version'] is None
        lines = db.execute('SELECT * FROM copy_part WHERE copy_id=? AND copy_figure_id IS NULL', (copy_b,)).fetchall()
        assert len(lines) == len(before) + 2                              # nothing deleted; added: the white 3001 and BrickLink's own 2339
        black, red = (one(db, 'SELECT id FROM catalogue.color WHERE born_key=?', k) for k in ('0', '4'))
        retired = {(r['item_id'], r['color_id']) for r in lines if r['retired_at']}
        # the red plate is not in BrickLink's list; Rebrickable's arch is retired because BrickLink has no number mapped to it, so its 2339 is a local item
        assert retired == {(item_of(db, 'parts', '3023'), red), (item_of(db, 'parts', '2339'), black)}
        local = db.execute("SELECT * FROM item WHERE origin='local' AND born_provider='bricklink' AND born_key='2339'").fetchone()
        assert local is not None and local['id'] >= 1_000_000_000 and any(l['item_id'] == local['id'] and not l['retired_at'] for l in lines)
        assert one(db, 'SELECT count(*) FROM fetched_inventory WHERE item_id=? AND source=? AND is_latest=1', set_item, 'bricklink') == 1
        assert [tuple(r) for r in db.execute("SELECT entity_kind, field FROM event WHERE entity_id=? ORDER BY id", (copy_b,))][-1][0] == 'copy'
        assert one(db, 'SELECT state FROM job WHERE id=?', one(db, 'SELECT id FROM job WHERE kind=?', 'bricklink_subsets')) == 'done'

    # --- 3: loose parts
    with closing(connect(pair)) as db:
        db.execute("INSERT INTO storage(id, name, type, created_at) VALUES('box-a', 'Box A', 'Box', '2026-10-27T10:00:00.000Z')")
        db.commit()
    plate, arch = item_of_ids(read, 'parts', '3023'), item_of_ids(read, 'parts', '2339')
    white, black = colour_of_ids(read, '15'), colour_of_ids(read, '0')
    stock_ids = []
    for number, colour, quantity in (('3023', white, 10), ('2339', black, 2), ('970c03', black, 1)):
        stock_ids.append(confirm(client, token, review(client, token, f'{number} x{quantity}', type='part', where='loose'), color_id=colour,
                                 condition='used', storage_id='box-a', decision='another')['stock'])
    again = confirm(client, token, review(client, token, '3023', type='part', where='loose'), color_id=white, condition='used', storage_id='box-a',
                    decision='another')
    assert again['stock'] == stock_ids[0]                                                     # the repeat merges, no duplicate row
    with read() as db:
        assert one(db, 'SELECT quantity FROM stock WHERE id=?', stock_ids[0]) == 11
        assert one(db, 'SELECT count(*) FROM stock WHERE archived_at IS NULL') == 3
    # 2339 has no BrickLink number: the matching step records "no match" and the price step ends `unidentified`
    net = Router({'/items/PART/3023/price': price_reply(average='0.03')})
    with read() as db:
        arch_job = one(db, "SELECT id FROM job WHERE kind='item' AND item_id=? ORDER BY id DESC LIMIT 1", arch)
        plate_job = one(db, "SELECT id FROM job WHERE kind='item' AND item_id=? ORDER BY id DESC LIMIT 1", plate)
    with closing(connect(pair)) as db:
        got = run_item_job(db, arch_job, http=net, image_http=Pictures())
        assert got['matching'] == ('done', 'unidentified') and got['market_price'] == ('done', 'unidentified')
        status = db.execute("SELECT status, reason, evidence_json FROM item_provider_status WHERE item_id=? AND provider='bricklink'", (arch,)).fetchone()
        assert (status['status'], status['reason']) == ('unmatched', 'no_match') and json.loads(status['evidence_json']) == {'rebrickable': '2339'}
        got = run_item_job(db, plate_job, http=net, image_http=Pictures())
        assert got['matching'] == ('done', None) and got['market_price'] == ('done', None)
        keyed_prices = {r['provider_key'] for r in db.execute('SELECT provider_key FROM price_observation WHERE item_id=?', (plate,))}
        assert keyed_prices == {'P:3023/1', 'P:3023/5', 'P:3023/11'}      # every colour the part is held in, as BrickLink numbers it (15, 4, 0 at Rebrickable)

    # --- 4: loose figures, the second with no BrickLink number at all
    knight = confirm(client, token, review(client, token, 'fig-004576', type='minifigure', where='loose'), condition='used', storage_id='box-a', decision='another')
    waiter = confirm(client, token, review(client, token, 'fig-018222', type='minifigure', where='loose'), condition='used', storage_id='box-a', decision='another')
    with read() as db:
        for receipt, parts in ((knight, 4), (waiter, 4)):
            row = db.execute('SELECT * FROM stock WHERE id=?', (receipt['stock'],)).fetchone()
            assert (row['kind'], row['inventory_source'], row['inventory_version']) == ('minifigure', 'rebrickable', 1)
            assert one(db, 'SELECT count(*) FROM stock_part WHERE stock_id=?', receipt['stock']) == parts
        waiter_item = item_of(db, 'minifigs', 'fig-018222')
        waiter_job = one(db, "SELECT id FROM job WHERE kind='item' AND item_id=? ORDER BY id DESC LIMIT 1", waiter_item)
    with closing(connect(pair)) as db:
        got = run_item_job(db, waiter_job, http=net, image_http=Pictures())
        assert got['matching'] == ('done', 'unidentified')
        assert one(db, "SELECT count(*) FROM item_provider_status WHERE item_id=? AND provider='bricklink' AND reason='no_match'", waiter_item) == 1
        # Identify: a photo of the waiter, the recogniser's candidates stored as one identification
        from brickwork.core import identify
        stored = identify.store(db, tmp_path, Pictures().default, [dict(item_id=waiter_item, item_type='M', item_no='twn999', score=.71)])
        assert one(db, 'SELECT count(*) FROM identification WHERE id=?', stored['id']) == 1

    # --- the end: every foreign key and the file's integrity
    with read() as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall() == [] and one(db, 'PRAGMA integrity_check') == 'ok'
        counts = {t: one(db, f'SELECT count(*) FROM {t}') for t in ('item', 'copy', 'copy_figure', 'copy_part', 'stock', 'stock_part', 'fetched_inventory_part', 'event', 'job')}
        assert counts['copy'] == 2 and counts['stock'] == 5 and counts['copy_figure'] == 2 and counts['stock_part'] == 8


def item_of_ids(read, namespace, key):
    with read() as db:
        return item_of(db, namespace, key)


def colour_of_ids(read, born_key):
    with read() as db:
        return one(db, 'SELECT id FROM catalogue.color WHERE born_key=?', born_key)


# ---------- probes B5 and B6 of design 12: the eight 3.3 lines of one copy through the real migration ----------

EIGHT = [('P', '3023', 1, 4), ('P', '970c00', 11, 1), ('P', '970c11', 5, 1), ('P', '970c00', 5, 1), ('P', '310.3stk01', None, 1),
         ('P', '311.1stk01', None, 1), ('P', '99999', 1, 2), ('P', '3023', 72, 1)]


def test_b5_b6_eight_lines_of_one_copy_insert_under_the_line_key_and_read_back_in_bricklink_space(tmp_path):
    """The lines of design 12 (colour-scoped legs, the shared sticker sheet, an unmapped part, BrickLink colour 72) go through
    `migrate_run.run` against the fixture catalogue: all eight land under the 4.0 line key without a collision (B5) and the run's own
    proof, which reads every 4.0 line back through the mint table, equals the 3.3 file (B6)."""
    from tests.legacy33 import create_33
    from tests.store4_migrate_fixtures import ins
    src = tmp_path / 'bw33.db'
    db = create_33(src)
    db.execute('PRAGMA foreign_keys=OFF')
    for colour, name in ((1, 'White'), (5, 'Red'), (11, 'Black'), (72, 'Maersk Blue')):
        ins(db, 'colors', color_id=colour, name=name, type='Solid', rgb=None)
    ins(db, 'items', item_type='S', item_no='2070-1', name='Ring Me Rabbit')
    ins(db, 'copies', id='copy-8', item_type='S', set_no='2070-1', updated_at='2026-10-01T00:00:00+00:00')
    for kind, number, colour, quantity in EIGHT:
        db.execute('INSERT OR IGNORE INTO items(item_type, item_no, name) VALUES(?, ?, ?)', (kind, number, number))
        ins(db, 'copy_parts', copy_id='copy-8', item_type=kind, item_no=number, color_id=colour, spare=0, quantity=quantity, missing=0, damaged=0, checked=0)
    db.commit()
    db.execute('PRAGMA journal_mode=DELETE')
    db.close()
    (tmp_path / 'cat').mkdir()
    catalogue = build_catalogue(tmp_path / 'cat')
    shutil.copytree(FIXTURES / 'mappings', tmp_path / 'maps')
    res = migrate_run.run(src, catalogue, tmp_path / 'maps', tmp_path / 'out' / 'brickwork-4.db', tmp_path / 'out' / 'report')
    assert res.result == 'PASS' and res.published
    assert res.proof['parts']['injectivity']['result'] == 'PASS' and res.proof['parts']['lists']['result'] == 'PASS'
    with closing(connect4(res.out, catalogue, read_only=True)) as out:
        lines = out.execute('''SELECT i.origin, i.born_provider, i.born_key, c.born_key AS colour, p.quantity FROM copy_part p JOIN item i ON i.id=p.item_id
                               LEFT JOIN color c ON c.id=p.color_id WHERE p.copy_id='copy-8' ''').fetchall()
        assert len(lines) == 8 and len({(r['born_key'], r['colour'], r['origin']) for r in lines}) == 8
        by = {(r['born_key'], r['colour']): r for r in lines}
        assert by[('3023', '15')]['quantity'] == 4 and ('3023', '1051') in by                          # BrickLink 72 -> Pastel Blue (inverse preferred)
        assert sorted(r['origin'] for r in lines if r['born_key'] in ('003402', '311.1stk01')) == ['catalogue', 'local']      # sheets stay apart
        assert [r['origin'] for r in lines if r['born_key'] == '99999'] == ['local']
        assert out.execute('PRAGMA foreign_key_check').fetchall() == [] and out.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


# ---------- probe A3 of design 12: another install numbers differently ----------

def test_a3_an_install_with_another_history_numbers_the_same_dump_differently(tmp_path):
    """Design 12 A3 (decided, design 3.1): ids are running numbers seeded by the history of one install, so a second install that built the
    same final dump fresh has other numbers and another catalogue id. `test_store4_builder.py::test_a3...` holds the other half (two fresh
    builds of one dump agree), which is why nothing may rely on a particular number."""
    from tests.store4_dump import default
    from tests.test_store4_builder import ids, run, shuffled
    (tmp_path / 'x').mkdir()
    (tmp_path / 'y').mkdir()
    first, cat_x = run(tmp_path / 'x')
    second = default()
    second['sets'] = [s for s in second['sets'] if s[0] != '9999-1'] + [('0001-1', 'Sorts First 2 x 2', '2020', '186', '1', '')]
    second['inventories'] = [i for i in second['inventories'] if i[2] != '9999-1']
    second['inventory_sets'] = []
    run(tmp_path / 'x', 'd2', **shuffled(second))                                  # a re-download on install X: old keys keep their numbers
    report_y, cat_y = run(tmp_path / 'y', 'd2', **second)                          # install Y builds that dump from nothing
    x, y = ids(cat_x), ids(cat_y)
    assert x['0001-1'] != y['0001-1']                                              # the new set is numbered last on X and first on Y
    assert first['catalogue_id'] != report_y['catalogue_id']
