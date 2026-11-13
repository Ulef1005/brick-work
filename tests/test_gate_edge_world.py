"""The screen gate's `edge` worlds (#268, decision 595): synthetic data for the approved states that were untested for want of data or a seam.

The approved baselines are Linux renders that cannot be re-made here, so the three older worlds keep their data (apart from meta.schema_version on a schema upgrade): the first test
fingerprints their built databases (every table's rows, ids and build-time stamps masked, rows sorted) and compares them with the fingerprints taken
on origin/main before the edge worlds existed. The module is in the `rendered` group: the gate's world folder is shared."""
import datetime as dt
import hashlib
import http.cookiejar
import io
import json
import re
import sqlite3
import tempfile
import urllib.request
import uuid
from contextlib import closing
from pathlib import Path

import pytest

from PIL import Image

from brickwork.demo import gate_edge, showcase
from brickwork.demo.clock import FIXED_NOW
from scripts import screen_gate as gate
from tests import rendered

pytestmark = rendered.group

HEX = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{32}|[0-9a-f]{64}')
STAMP = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z')
CEILING = FIXED_NOW + dt.timedelta(days=7)
SKIPPED = {('catalogue.db', 'build')}     # the build row holds the byte sizes of the dump files, which depend on the zlib in use


def mask(value):
    if isinstance(value, bytes):
        return value.hex()
    if not isinstance(value, str):
        return repr(value)
    def late(m):
        return '#T' if dt.datetime.fromisoformat(m.group(0).replace('Z', '+00:00')) > CEILING else m.group(0)   # the build moment: a stamp the demo clock never gives
    return STAMP.sub(late, HEX.sub('#', value))


def fingerprint(name):
    """{database file: {table: sha256 of its sorted, masked rows}} of the world `name` built by the gate's own build_store."""
    result = {}
    with tempfile.TemporaryDirectory() as scratch:
        store = Path(scratch) / 'brickwork.db'
        gate.build_store(name, store)
        for file in ('brickwork.db', 'catalogue.db'):
            with closing(sqlite3.connect(Path(scratch) / file)) as db:
                tables = sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
                result[file] = {}
                for table in tables:
                    if (file, table) in SKIPPED:
                        continue
                    rows = sorted('|'.join(mask(v) for v in row) for row in db.execute(f'SELECT * FROM "{table}"'))
                    result[file][table] = hashlib.sha256('\n'.join(rows).encode()).hexdigest()
    return result


def digest(name):
    prints = fingerprint(name)
    return hashlib.sha256(repr(sorted((f, sorted(t.items())) for f, t in prints.items())).encode()).hexdigest()


# Taken on origin/main (21ac7ce), before the edge worlds were added; advanced for schema 4.3 (#315).
# For all three worlds, substituting only meta.schema_version=4.2 reproduces the original fingerprint exactly.
BEFORE = {
    'demo': 'c8bca9e90adc57718a2b43e8aaba1f533b8e113432ebfa77601879774b4b54d2',
    'showcase': '7388699a853ccbca29455768925e185571d36a551d28550cd87024012c183ade',
    'extras': 'abcfac8acc3d18ff2af980a50792b8c58a30d654093653f520127e445df6f5fb',
}


@pytest.mark.parametrize('name', ['demo', 'showcase', 'extras'])
def test_the_older_worlds_are_unchanged(name):
    assert digest(name) == BEFORE[name]




# ---------- the edge worlds' data ----------

@pytest.fixture(scope='module')
def stores(tmp_path_factory):
    """The built databases of the edge worlds (built once)."""
    built = {}
    for name in ('edge', 'edge-empty'):
        folder = tmp_path_factory.mktemp(name)
        gate.build_store(name, folder / 'brickwork.db')
        db = sqlite3.connect(folder / 'brickwork.db')
        db.row_factory = sqlite3.Row
        db.execute('ATTACH DATABASE ? AS catalogue', (str(folder / 'catalogue.db'),))
        built[name] = db
    yield built
    for db in built.values():
        db.close()


def count(db, sql, *args):
    return db.execute(sql, args).fetchone()[0]


def test_the_edge_world_holds_the_extras_world_and_its_additions(stores):
    db = stores['edge']
    assert count(db, "SELECT count(*) FROM wish WHERE id='wish-usd-pier'") == 1           # the extras layer's dollar wish
    assert count(db, 'SELECT count(*) FROM copy') == 26                                  # the showcase's 25 copies and the spare copy
    for number in gate_edge.KINDS:
        assert count(db, 'SELECT count(*) FROM stock s JOIN catalogue.item i ON i.id=s.item_id WHERE i.born_key=?', number) == 1


def test_the_spare_copy_has_spare_lines_and_a_check_that_said_yes_to_them(stores):
    db = stores['edge']
    assert count(db, 'SELECT count(*) FROM copy_part WHERE copy_id=? AND is_spare=1', gate_edge.SPARE_COPY) == 3
    assert count(db, 'SELECT count(*) FROM copy_part WHERE copy_id=? AND is_spare=0', gate_edge.SPARE_COPY) == 14
    check = db.execute('SELECT spares, finished, session_json FROM part_check WHERE copy_id=?', (gate_edge.SPARE_COPY,)).fetchone()
    session = json.loads(check['session_json'])
    assert check['spares'] == 'yes' and not check['finished']
    assert len(session['order']) == 17 and session['cursor'] == 14                        # the fourteen required lines answered, the first spare line is next
    assert sum(1 for t in session['order'] if session['answers'].get(t) == 'answered') == 14


def test_two_incomplete_copies_are_pinned(stores):
    db = stores['edge']
    pinned = {r[0] for r in db.execute('SELECT id FROM copy WHERE pinned=1')}
    assert pinned == {showcase.uid('copy', number, letter) for number, letter in gate_edge.PINNED}


def test_the_listing_box_has_a_listing_and_no_sale_and_the_booklet_has_no_price(stores):
    db = stores['edge']
    box = db.execute('SELECT item_id FROM stock s JOIN catalogue.item i ON i.id=s.item_id WHERE i.born_key=?', (gate_edge.LISTING_BOX[0],)).fetchone()[0]
    rows = db.execute('SELECT o.guide, o.sold FROM price_observation o WHERE o.item_id=?', (box,)).fetchall()
    assert [(r['guide'], r['sold']) for r in rows] == [('stock', 0)]
    bare = db.execute('SELECT item_id FROM stock s JOIN catalogue.item i ON i.id=s.item_id WHERE i.born_key=?', (gate_edge.BARE_BOOKLET[0],)).fetchone()[0]
    assert count(db, 'SELECT count(*) FROM price_observation WHERE item_id=?', bare) == 0


def test_the_import_sets_are_in_the_catalogue_and_nobody_owns_or_wishes_for_them(stores):
    db = stores['edge']
    for number, *_ in gate_edge.IMPORT_SETS:
        item = db.execute("SELECT id FROM catalogue.item WHERE born_namespace='sets' AND born_key=?", (number,)).fetchone()
        assert item
        assert count(db, 'SELECT count(*) FROM copy WHERE item_id=?', item[0]) == 0
        assert count(db, 'SELECT count(*) FROM wish WHERE item_id=?', item[0]) == 0
        assert count(db, 'SELECT count(*) FROM stock WHERE item_id=?', item[0]) == 0


def test_the_empty_world_owns_nothing_and_keeps_the_catalogue(stores):
    db = stores['edge-empty']
    for table in ('copy', 'copy_part', 'stock', 'wish', 'part_check'):
        assert count(db, f'SELECT count(*) FROM {table}') == 0, table
    assert count(db, "SELECT count(*) FROM catalogue.item WHERE born_key='99101-1'") == 1          # the sets are in the catalogue, nobody owns one


# ---------- the seams ----------

def test_the_staged_transport_answers_the_recognition_and_nothing_else():
    class Request:
        full_url = 'https://api.brickognize.com/predict/parts/'
    reply = gate_edge.transport(Request())
    assert [(i['id'], i['score']) for i in reply['items']] == list(gate_edge.RECOGNISED) and {i['type'] for i in reply['items']} == {'part'}
    Request.full_url = 'https://api.bricklink.com/api/store/v1/items'
    with pytest.raises(OSError):
        gate_edge.transport(Request)


def test_the_edge_seams_switch_on_for_the_edge_worlds_only_and_are_put_back():
    import os
    from brickwork.core.sources import base
    original = base.transport
    key = next(iter(gate_edge.KEYS))
    before = os.environ.get(key)
    for name in ('demo', 'showcase', 'extras'):
        with gate.edge_seams(name):
            assert base.transport is original and os.environ.get(key) == before
    for name in ('edge', 'edge-read-only', 'edge-empty'):
        with gate.edge_seams(name):
            assert base.transport is gate_edge.transport and os.environ[key] == gate_edge.KEYS[key]
        assert base.transport is original and os.environ.get(key) == before
    with pytest.raises(RuntimeError):
        with gate.edge_seams('edge'):
            raise RuntimeError('a world that fails to build')
    assert base.transport is original and os.environ.get(key) == before


def fetch(opener, url, data=None, headers=None):
    request = urllib.request.Request(url, data=data, headers=headers or {})
    with opener.open(request) as reply:
        return reply.read().decode()


def test_the_edge_world_is_served_with_its_seams_and_only_there():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    with gate.world('edge') as base_url:
        item = fetch(opener, base_url + '/collection/item/instructions/99872-1')
        assert 'data-bc-fetch-prices' in item and 'Needs a BrickLink key' not in item              # Update price is offered, as it is with a key
        assert 'Read only' not in fetch(opener, base_url + '/collection/P')
        page = fetch(opener, base_url + '/workbench/part-to-inventory')
        csrf = re.search(r'data-csrf="([^"]+)"', page).group(1)
        picture = io.BytesIO()
        Image.new('RGB', (24, 24), 'gray').save(picture, format='PNG')
        boundary = 'gate' + uuid.uuid4().hex
        body = b''.join([f'--{boundary}\r\nContent-Disposition: form-data; name="csrf_token"\r\n\r\n{csrf}\r\n'.encode(),
                         f'--{boundary}\r\nContent-Disposition: form-data; name="endpoint"\r\n\r\nparts\r\n'.encode(),
                         f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="p.png"\r\nContent-Type: image/png\r\n\r\n'.encode(),
                         picture.getvalue(), f'\r\n--{boundary}--\r\n'.encode()])
        reply = json.loads(fetch(opener, base_url + '/workbench/part-to-inventory/detect', body, {'Content-Type': 'multipart/form-data; boundary=' + boundary}))
        assert [c['item_no'] for c in reply['candidates']] == [n for n, _ in gate_edge.RECOGNISED] and reply['unresolved'] == []
    with gate.world('extras') as base_url:
        assert 'data-bc-fetch-prices' not in fetch(opener, base_url + '/collection/item/instructions/99801-1')   # no key in the older worlds: Update price stays disabled


def test_the_read_only_world_says_so_and_the_empty_world_has_no_copies():
    opener = urllib.request.build_opener()
    with gate.world('edge-read-only') as base_url:
        assert 'Read only' in fetch(opener, base_url + '/collection/P')
    with gate.world('edge-empty') as base_url:
        assert 'No copies to check yet.' in fetch(opener, base_url + '/workbench/check-parts')


# ---------- the states ----------

NEW = {('16-Module-states', 'loading'), ('16-Module-states', 'error'), ('16-Module-states', 'listings-only'), ('19-Item-lists', 'read-only'),
       ('20-Add-into-a-lot', 'import-progress'), ('31-Part-to-inventory', 'has-a-sticker'), ('35-Orders-capabilities', 'xml-link'),
       ('36-Check-this-copy', 'no-copies'), ('36-Check-this-copy', 'save-error'), ('36-Check-this-copy', 'javascript-off'),
       ('39-Include-spare-parts', 'spare-pass'), ('44-Complete-sets', 'pins')}


# #57: the Value module and Paid vs value states, in their own world (`edge-value`: the edge world plus gate_edge.ValueLayer), added as candidates, approved on 13.11.
VALUE = {('10-Set-detail', s) for s in ('value-loss', 'value-no-price', 'value-no-quote', 'value-override', 'value-stale', 'value-other-currency')} | {
    ('49-Statistics', 'paid-vs-value'), ('49-Statistics', 'insurance-report'), ('49-Statistics', 'insurance-report-empty')}


def test_the_value_states_use_the_edge_value_world_or_the_empty_one_and_are_built():
    states = {(e['screen'], e['state']): e for e in gate.load()['states']}
    assert VALUE <= set(states)
    for key in VALUE:
        assert states[key]['world'] in ('edge-value', 'edge-empty') and states[key]['built'] is True and isinstance(states[key]['approved'], bool), key   # approved by Ulf on 13.11. (decision 602); a state that moves is approved again by him


def test_the_new_states_are_built_in_a_known_world():
    states = {(e['screen'], e['state']): e for e in gate.load()['states']}
    assert NEW <= set(states)
    for key in NEW:
        entry = states[key]
        assert entry['built'] is True and isinstance(entry['approved'], bool), key         # approved by the maintainer on 12.11. (decision 600); a state that moves is approved again by him
        assert entry['world'] in gate.WORLDS and entry['path'].startswith('/'), key
    assert {k for k in NEW if states[k].get('javascript') is False} == {('36-Check-this-copy', 'javascript-off')}
    assert {k for k in NEW if not states[k]['world'].startswith('edge')} == {('35-Orders-capabilities', 'xml-link'), ('36-Check-this-copy', 'save-error'),
                                                                               ('36-Check-this-copy', 'javascript-off')}     # script-only states add no data, so they use the showcase


def test_only_the_new_states_use_an_edge_world():
    """No state approved before the edge worlds existed was moved into one: its baseline would then depend on the edge data."""
    assert {(e['screen'], e['state']) for e in gate.load()['states'] if e.get('world', '').startswith('edge')} <= NEW | VALUE | SOURCE


def test_the_state_left_unbuilt_says_what_is_missing():
    entry = next(e for e in gate.load()['states'] if e['state'] == 'add-part-lot')
    assert entry['built'] is False and 'switch' in entry['reason'] and 'not in the app' in entry['reason']


def test_the_edge_states_render_the_same_twice(tmp_path, monkeypatch):
    """Each new state is captured twice at one size (the scripts, the staged recognition and the staged progress included): the two captures agree."""
    chrome = rendered.chrome(pinned=True)
    monkeypatch.setattr(gate, 'WIDTHS', (1440,))
    monkeypatch.setattr(gate, 'THEMES', ('light',))
    entries = [e for e in gate.load()['states'] if (e['screen'], e['state']) in NEW]
    assert len(entries) == len(NEW)
    first = gate.render(entries, lambda e, w, t: tmp_path / '1' / gate.filename(e['screen'], e['state'], w, t), chrome)
    second = gate.render(entries, lambda e, w, t: tmp_path / '2' / gate.filename(e['screen'], e['state'], w, t), chrome)
    for one, two in zip(first, second):
        result = gate.compare_images(one, two)
        assert not result['size_differs'] and result['share'] <= gate.TOLERANCE['pixels'] / 5, (one.name, result)


def test_a_capture_without_javascript_does_not_leak_into_the_next_one(tmp_path):
    """One Chrome session, three jobs of the same page: scripts off, on, off. The first and third show the no-script page, the second the scripted one."""
    chrome = rendered.chrome(pinned=True)
    path = '/workbench/check-parts/60b6e39e-1532-5baf-a0df-08566d2328a2'
    with gate.world('showcase', [path]) as base_url:
        jobs = [{'url': base_url + path, 'out': str(tmp_path / f'{n}.png'), 'width': 1024, 'theme': 'light', 'max': 1600, **extra}
                for n, extra in enumerate(({'javascript': False}, {}, {'javascript': False}))]
        gate.run_jobs(jobs, str(tmp_path), chrome)
    off1, on, off2 = (tmp_path / f'{n}.png' for n in range(3))
    assert gate.compare_images(off1, off2)['share'] <= gate.TOLERANCE['pixels']
    assert gate.compare_images(off1, on)['share'] > gate.TOLERANCE['pixels'] or gate.compare_images(off1, on)['size_differs']


# #54: the order list's source states, in the `edge-order` world (the edge world plus element ids in the catalogue), added as candidates.
SOURCE = {('43-Complete-sets', 'order-missing-parts-source'), ('43-Complete-sets', 'order-missing-parts-pick-a-brick')}


def test_the_source_states_use_the_edge_order_world_and_are_built():
    states = {(e['screen'], e['state']): e for e in gate.load()['states']}
    assert SOURCE <= set(states)
    for key in SOURCE:
        assert states[key]['world'] == 'edge-order' and states[key]['built'] is True and isinstance(states[key]['approved'], bool), key


def test_the_edge_order_world_adds_element_ids_to_the_catalogue_and_nothing_else():
    plain, order = fingerprint('edge'), fingerprint('edge-order')
    assert plain['brickwork.db'] == order['brickwork.db']
    assert {t for t in order['catalogue.db'] if order['catalogue.db'][t] != plain['catalogue.db'].get(t)} == {'element'}
