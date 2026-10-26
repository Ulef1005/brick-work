"""The migration command (design 8.2, 8.6, 8.7, 8.8; issue #109, M.7c): lists attached in BrickLink space, the independent proof, the
report, publish only on PASS, pinning and the exit codes. Stores: the frozen regression fixtures and the synthetic 3.3 store of
`store4_migrate_fixtures`, against the fixture catalogue of the mint tests."""
import csv
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from brickwork.core.connect import connect as connect33
from brickwork.store4 import cli, migrate_run
from brickwork.store4.connect import connect
from brickwork.store4.migrate import MigrationError, NeedsDecision
from brickwork.store4.migrate_report import dict_csv, report_digest
from brickwork.store4.migrate_run import PinMismatch, Refused, read_pins, run
from tests.store4_migrate_fixtures import build_33, ins
from tests.store4_mint_fixtures import FIXTURES, build_catalogue

REGRESSION = sorted((Path(__file__).parent / 'regression' / 'fixtures').glob('*.db'))
REPORT_FILES = ('summary.md', 'mint.csv', 'collisions.csv', 'local-items.csv', 'colours.csv', 'summed-lines.csv', 'extras.csv', 'attached.csv',
                'migrated-lists.csv', 'manual-decisions.csv', 'not-carried.csv', 'settings.csv', 'proof.json', 'type-crossed.csv',
                'figure-lines-from-parts.csv', 'figure-lines-retained-duplicate.csv', 'non-part-lines.csv', 'value-fixes.csv', 'money-fills.csv',
                'count-fixes.csv', 'timestamp-rules.csv')
PARTS = ('lists', 'prices', 'plain', 'structure', 'injectivity', 'attach')


@pytest.fixture
def catalogue(tmp_path):
    (tmp_path / 'cat').mkdir()
    return build_catalogue(tmp_path / 'cat')


@pytest.fixture
def mappings(tmp_path):
    shutil.copytree(FIXTURES / 'mappings', tmp_path / 'maps')
    return tmp_path / 'maps'


def make_attach_33(path):
    """The synthetic 3.3 store plus the copies that tell attaching apart. The fixture catalogue lists set 2070-1 (version 1: 2071c01pb01 in BrickLink
    colour 3, x1718c01 in 5, dupphonec01 in 5, once each; version 2 has no BrickLink-space digest) and the figure syn-fig-0004 (3626ap01/3, 3901/8,
    970c00/11, 973c001/1). Returns the ids."""
    build_33(path)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=OFF')
    for key in (('P', '2071c01pb01'), ('P', 'x1718c01'), ('P', 'dupphonec01'), ('P', '3901'), ('P', '973c001'), ('M', 'syn-fig-0004')):
        db.execute('INSERT OR IGNORE INTO items(item_type, item_no, name) VALUES(?, ?, ?)', (*key, key[1]))
    ins(db, 'colors', color_id=8, name='Light Gray', type='Solid', rgb='9BA19D')
    ex_line = ins(db, 'inventory_lines', parent_item_type='S', parent_item_no='2070-1', child_item_type='P', child_item_no='x1718c01', color_id=5,
                  quantity=2, extra_quantity=1, source='bricklink', fetched_at='2026-10-14T18:00:58+00:00')

    def set_lines(copy_id, *, x_quantity=1, x_ref=9001):
        for item_no, color, quantity, extra in (('2071c01pb01', 3, 1, {}), ('x1718c01', 5, x_quantity, {'source_ref': x_ref}), ('dupphonec01', 5, 1, {})):
            ins(db, 'copy_parts', copy_id=copy_id, item_type='P', item_no=item_no, color_id=color, spare=0, quantity=quantity, missing=0, damaged=0,
                checked=0, **extra)

    def figure_lines(**where):
        for item_no, color in (('3626ap01', 3), ('3901', 8), ('970c00', 11), ('973c001', 1)):
            ins(db, 'copy_parts' if 'copy_id' in where else 'loose_minifig_parts', item_type='P', item_no=item_no, color_id=color, spare=0,
                quantity=1, missing=0, damaged=0, checked=0,
                **({'parent_minifig_type': 'M', 'parent_minifig': 'syn-fig-0004', **where} if 'copy_id' in where else where))

    ins(db, 'copies', id='copy-eq', item_type='S', set_no='2070-1', updated_at='2026-10-01T00:00:00+00:00')
    set_lines('copy-eq')
    db.execute("UPDATE copy_parts SET checked=1, missing=1 WHERE copy_id='copy-eq' AND item_no='2071c01pb01'")
    ins(db, 'copies', id='copy-ex', item_type='S', set_no='2070-1', updated_at='2026-10-01T00:00:00+00:00')
    set_lines('copy-ex', x_quantity=2, x_ref=ex_line)                   # 2 - 1 extra = 1: equal to version 1 after the correction
    ins(db, 'copies', id='copy-fig', item_type='S', set_no='2070-1', updated_at='2026-10-01T00:00:00+00:00')
    set_lines('copy-fig')
    figure_lines(copy_id='copy-fig')
    ins(db, 'copy_minifigs', copy_id='copy-fig', item_type='M', minifig_no='syn-fig-0004', quantity=1, missing=0)
    ins(db, 'loose_stock', id='fig-eq', item_type='M', item_no='syn-fig-0004', quantity=1)
    figure_lines(stock_id='fig-eq')
    db.commit()
    db.execute('PRAGMA journal_mode=DELETE')
    db.close()
    return ex_line


@pytest.fixture
def attach_33(tmp_path):
    make_attach_33(tmp_path / 'bw33.db')
    return tmp_path / 'bw33.db'


def go(tmp_path, src, catalogue, mappings, name='1', **kw):
    return run(src, catalogue, mappings, tmp_path / name / 'brickwork-4.db', tmp_path / name / 'report', **kw)


def records(result, kind):
    return {a['ref']: a for a in result.migration.attach if a['kind'] == kind}


# ---------- attaching (design 8.6) ----------

def test_a_copy_equal_in_brick_link_space_attaches_and_keeps_its_check_state(tmp_path, attach_33, catalogue, mappings):
    res = go(tmp_path, attach_33, catalogue, mappings)
    assert res.result == 'PASS' and res.published
    copies = records(res, 'copy')
    assert copies['copy-eq']['status'] == 'attached' and copies['copy-eq']['version'] == 1 and copies['copy-eq']['ids_equal'] is True
    with closing(connect(res.out, catalogue, read_only=True)) as db:
        copy = db.execute("SELECT * FROM copy WHERE id='copy-eq'").fetchone()
        digest = db.execute('SELECT digest FROM catalogue.inventory WHERE item_id=? AND version=1', (copy['item_id'],)).fetchone()[0]
        assert (copy['inventory_source'], copy['inventory_version'], copy['inventory_digest']) == ('rebrickable', 1, digest)
        assert copy['fetched_inventory_id'] is None
        lines = {(l['item_id'], l['quantity'], l['missing'], l['checked']) for l in db.execute("SELECT * FROM copy_part WHERE copy_id='copy-eq'")}
        assert sorted((q, m, c) for _, q, m, c in lines) == [(1, 0, 0), (1, 0, 0), (1, 1, 1)]      # the line the user checked keeps its state


def test_a_copy_that_differs_stays_migrated_with_the_reason(tmp_path, attach_33, catalogue, mappings):
    res = go(tmp_path, attach_33, catalogue, mappings)
    copies = records(res, 'copy')
    assert copies['copy-upd']['status'] == 'migrated' and copies['copy-upd']['reason'] == 'digest_differs'       # one line the catalogue's lists lack
    assert copies['copy-proj']['reason'] == 'placeholder_without_bricklink_key'                                 # a `?` figure the catalogue has no BrickLink key for
    assert copies['copy-bl']['reason'] == 'no_catalogue_list'                  # 5008074-1 is a local set: the catalogue has no list of it
    assert copies['copy-fig']['status'] == 'migrated'                         # its figure line is part of the comparison
    with closing(connect(res.out, catalogue, read_only=True)) as db:
        sources = dict(db.execute('SELECT id, inventory_source FROM copy'))
    assert sources['copy-proj'] == 'migrated' and sources['copy-bl'] == 'migrated' and sources['copy-eq'] == 'rebrickable'


def test_a_copy_equal_in_brick_link_space_but_on_other_items_stays_migrated(tmp_path, attach_33, catalogue, mappings, monkeypatch):
    # a rule-4 tie can put a line on a local item while BrickLink space still equals the catalogue list: a `rebrickable` copy must hold
    # the catalogue list's own lines, so the copy stays migrated (its own digest, here made to differ from the catalogue's)
    from brickwork.store4 import migrate as migrate_mod
    original = migrate_mod._Writer._compare

    def compare(self, kind, row, ref, label, item_id, lines, own_digest, **kw):
        return original(self, kind, row, ref, label, item_id, lines, 'other-items' if ref == 'copy-eq' else own_digest, **kw)
    monkeypatch.setattr(migrate_mod._Writer, '_compare', compare)
    res = go(tmp_path, attach_33, catalogue, mappings)
    assert res.result == 'PASS'
    rec = records(res, 'copy')['copy-eq']
    assert (rec['status'], rec['reason'], rec['ids_equal'], rec['version']) == ('migrated', 'ids_differ', False, 1)
    with closing(connect(res.out, catalogue, read_only=True)) as db:
        assert tuple(db.execute("SELECT inventory_source, inventory_version FROM copy WHERE id='copy-eq'").fetchone()) == ('migrated', None)


def test_an_extras_corrected_copy_is_compared_after_the_correction(tmp_path, attach_33, catalogue, mappings):
    res = go(tmp_path, attach_33, catalogue, mappings)
    assert [e['copy_id'] for e in res.migration.extras if e['copy_id'] == 'copy-ex'] == ['copy-ex']
    assert records(res, 'copy')['copy-ex']['status'] == 'attached'            # 2 - 1 extra = 1 equals the catalogue's version 1


def test_figure_lines_and_loose_figures_attach_to_the_latest_list_of_the_figure(tmp_path, attach_33, catalogue, mappings):
    res = go(tmp_path, attach_33, catalogue, mappings)
    figures = [a for a in res.migration.attach if a['kind'] == 'figure']
    assert [(a['ref'], a['status']) for a in figures if a['ref'].startswith('copy-fig')] == [('copy-fig M:syn-fig-0004', 'attached')]
    other = [a for a in figures if not a['ref'].startswith('copy-fig')]
    assert other and all(a['status'] == 'migrated' for a in other)           # copy-proj's figure has no gear-free list equal to the catalogue's
    loose = records(res, 'loose_figure')
    assert loose['fig-eq']['status'] == 'attached' and loose['s-fig']['status'] == 'migrated'
    with closing(connect(res.out, catalogue, read_only=True)) as db:
        f = db.execute("SELECT * FROM copy_figure WHERE copy_id='copy-fig'").fetchone()
        s = db.execute("SELECT * FROM stock WHERE id='fig-eq'").fetchone()
        for row in (f, s):
            digest = db.execute('SELECT digest FROM catalogue.inventory WHERE item_id=? AND is_latest=1', (row['item_id'],)).fetchone()[0]
            assert (row['inventory_source'], row['inventory_version'], row['inventory_digest']) == ('rebrickable', 1, digest)
        assert db.execute("SELECT inventory_source FROM stock WHERE id='s-fig'").fetchone()[0] == 'migrated'


def test_every_list_has_a_record_with_its_reason(tmp_path, attach_33, catalogue, mappings):
    res = go(tmp_path, attach_33, catalogue, mappings)
    counts = res.migration.attach_counts()
    with closing(connect(res.out, catalogue, read_only=True)) as db:
        assert counts['copy']['total'] == db.execute('SELECT count(*) FROM copy').fetchone()[0]
        assert counts['figure']['total'] == db.execute('SELECT count(*) FROM copy_figure').fetchone()[0]
        assert counts['loose_figure']['total'] == db.execute("SELECT count(*) FROM stock WHERE kind='minifigure'").fetchone()[0]
    for a in res.migration.attach:
        assert (a['status'] == 'attached') == (a['reason'] is None)
        assert a['reason'] in (None, 'no_catalogue_list', 'no_bl_digest', 'digest_differs', 'placeholder_without_bricklink_key')


# ---------- the proof (design 8.7) ----------

def test_the_proof_passes_on_the_synthetic_store(tmp_path, attach_33, catalogue, mappings):
    res = go(tmp_path, attach_33, catalogue, mappings)
    assert res.result == 'PASS'
    assert sorted(res.proof['parts']) == sorted(PARTS)
    for name, part in res.proof['parts'].items():
        assert part['result'] == 'PASS' and part['checked'] > 0 and part['differences'] == 0, name


@pytest.mark.parametrize('fixture', REGRESSION, ids=lambda p: p.name)
def test_the_proof_passes_on_every_regression_fixture(fixture, tmp_path, catalogue, mappings):
    src = tmp_path / 'bw33.db'
    shutil.copy(fixture, src)
    connect33(src).close()
    with sqlite3.connect(src) as db:
        db.execute('PRAGMA journal_mode=DELETE')
    res = go(tmp_path, src, catalogue, mappings)
    assert res.result == 'PASS', [(n, p['first_differences'][:2]) for n, p in res.proof['parts'].items() if p['differences']]
    assert res.published and res.out.exists()


def tamper(sql, *args):
    def apply(m):
        db = sqlite3.connect(m.temp_path)
        try:
            db.execute('PRAGMA foreign_keys=OFF')
            db.execute(sql, args)
            db.commit()
        finally:
            db.close()
    return apply


TAMPERING = {
    'a quantity': ('lists', "UPDATE copy_part SET quantity=quantity+1 WHERE id=(SELECT min(id) FROM copy_part)"),
    'a line removed': ('lists', "DELETE FROM copy_part WHERE id=(SELECT max(id) FROM copy_part)"),
    'a swapped colour': ('lists', "UPDATE copy_part SET color_id=(SELECT max(id) FROM color WHERE origin='catalogue') WHERE id=(SELECT min(id) FROM copy_part)"),
    'a wish quantity': ('lists', "UPDATE wish SET quantity=quantity+5 WHERE id=(SELECT min(id) FROM wish)"),
    'a loose figure part': ('lists', "UPDATE stock_part SET quantity=quantity+1 WHERE id=(SELECT min(id) FROM stock_part)"),
    'a missing price observation': ('prices', "DELETE FROM price_observation WHERE id=(SELECT min(id) FROM price_observation WHERE id NOT IN "
                                              "(SELECT observation_id FROM price_current))"),
    'a price value': ('prices', "UPDATE price_observation SET price='999.99' WHERE id=(SELECT min(id) FROM price_observation WHERE price IS NOT NULL)"),
    'a price_current row': ('prices', "UPDATE price_current SET observation_id=(SELECT min(id) FROM price_observation) "
                                      "WHERE rowid=(SELECT max(rowid) FROM price_current)"),
    'a token': ('plain', "UPDATE api_token SET hash='tampered'"),
    'a setting': ('plain', "UPDATE setting SET value='tampered' WHERE key='bricklink_region'"),
    'a flag link': ('plain', "DELETE FROM copy_flag"),
    'a foreign id': ('structure', "UPDATE item SET born_key='not-in-the-catalogue' WHERE id=(SELECT min(id) FROM item WHERE origin='catalogue')"),
    'a dangling reference': ('structure', "UPDATE copy SET storage_id='nowhere' WHERE id=(SELECT min(id) FROM copy)"),
    'an attach claim': ('attach', "UPDATE copy SET inventory_digest='0000' WHERE inventory_source='rebrickable' "
                                  "AND id=(SELECT min(id) FROM copy WHERE inventory_source='rebrickable')"),
    'an attach to another version': ('attach', "UPDATE copy SET inventory_source='migrated', inventory_version=NULL "
                                               "WHERE id=(SELECT min(id) FROM copy WHERE inventory_source='rebrickable')"),
}


@pytest.mark.parametrize('what', TAMPERING)
def test_a_deliberately_broken_output_fails_and_is_not_published(what, tmp_path, attach_33, catalogue, mappings):
    part, sql = TAMPERING[what]
    res = go(tmp_path, attach_33, catalogue, mappings, after_write=tamper(sql))
    assert res.result == 'FAIL' and not res.published
    assert res.proof['parts'][part]['result'] == 'FAIL' and res.proof['parts'][part]['first_differences']
    assert not res.out.exists()
    assert [p.name for p in res.out.parent.iterdir() if p.name != 'report'] == []        # the temporary file is gone too
    assert json.loads((res.report / 'proof.json').read_text())['result'] == 'FAIL'
    assert (res.report / 'summary.md').read_text().startswith('# Brick Work 3.3 to 4.0 migration: FAIL')


def test_a_foreign_id_is_found_by_the_cross_file_check(tmp_path, attach_33, catalogue, mappings):
    res = go(tmp_path, attach_33, catalogue, mappings, after_write=tamper(TAMPERING['a foreign id'][1]))
    assert any('born key' in d['what'] for d in res.proof['parts']['structure']['first_differences'])


def test_the_proof_names_the_first_differences(tmp_path, attach_33, catalogue, mappings):
    res = go(tmp_path, attach_33, catalogue, mappings, after_write=tamper(TAMPERING['a quantity'][1]))
    first = res.proof['parts']['lists']['first_differences'][0]
    assert first['what'].startswith('copy line') and first['3.3'] != first['4.0']


# ---------- the report (design 8.8) ----------

def test_the_report_files_are_present_and_parse(tmp_path, attach_33, catalogue, mappings):
    res = go(tmp_path, attach_33, catalogue, mappings)
    for name in REPORT_FILES:
        assert (res.report / name).is_file(), name
    for path in res.report.glob('*.csv'):
        with open(path, newline='', encoding='utf-8') as f:
            rows = list(csv.reader(f))
        assert rows and all(len(r) == len(rows[0]) for r in rows), path.name
    proof = json.loads((res.report / 'proof.json').read_text())
    assert proof['result'] == 'PASS' and set(proof['parts']) == set(PARTS) and set(proof['pins']) == {'catalogue', 'mappings', 'shipped_mappings'}
    attached = list(csv.DictReader(open(res.report / 'attached.csv', newline='')))
    migrated = list(csv.DictReader(open(res.report / 'migrated-lists.csv', newline='')))
    assert {r['ref'] for r in attached} >= {'copy-eq', 'copy-ex', 'fig-eq'} and all(r['reason'] for r in migrated)
    assert len(attached) + len(migrated) == len(res.migration.attach)
    assert 'copy-ex' in (res.report / 'extras.csv').read_text()
    assert len(list(csv.DictReader(open(res.report / 'manual-decisions.csv', newline='')))) == len(res.migration.manual_decisions)
    summary = (res.report / 'summary.md').read_text()
    assert 'copies' in summary and '## Pins' in summary and res.migration.source['sha256'] in summary


def test_the_digest_is_in_the_event_and_in_meta(tmp_path, attach_33, catalogue, mappings):
    res = go(tmp_path, attach_33, catalogue, mappings)
    want = hashlib.sha256((res.report / 'summary.md').read_bytes() + (res.report / 'proof.json').read_bytes()).hexdigest()
    assert res.digest == want == report_digest(res.report)
    with closing(connect(res.out, catalogue, read_only=True)) as db:
        meta = json.loads(db.execute("SELECT value FROM meta WHERE key='migrated_from'").fetchone()[0])
        events = db.execute('SELECT new_value FROM event').fetchall()
    assert meta['report_digest'] == want and len(events) == 1 and json.loads(events[0][0])['report_digest'] == want


def test_every_report_cell_goes_through_csv_safe(tmp_path):
    path = tmp_path / 'x.csv'
    dict_csv(path, [{'a': '=cmd()', 'b': '-2.00', 'c': '+SUM(A1)', 'd': {'k': '=x'}}])
    row = list(csv.reader(open(path, newline='')))[1]
    assert row[0] == "'=cmd()" and row[1] == '-2.00' and row[2] == "'+SUM(A1)" and row[3] == '{"k":"=x"}'


# ---------- publish only on PASS, inputs, refusals ----------

def test_a_pass_publishes_and_inputs_are_untouched(tmp_path, attach_33, catalogue, mappings):
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (attach_33, catalogue)]
    res = go(tmp_path, attach_33, catalogue, mappings)
    assert res.published and res.out.exists()
    assert before == [hashlib.sha256(p.read_bytes()).hexdigest() for p in (attach_33, catalogue)]
    with closing(connect(res.out, catalogue, read_only=True)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_an_existing_output_or_a_used_report_folder_is_refused_before_anything_is_written(tmp_path, attach_33, catalogue, mappings):
    out = tmp_path / 'o' / 'brickwork-4.db'
    out.parent.mkdir()
    out.write_text('precious')
    with pytest.raises(Refused, match='exists'):
        run(attach_33, catalogue, mappings, out, tmp_path / 'o' / 'report')
    assert out.read_text() == 'precious' and not (tmp_path / 'o' / 'report').exists()
    (tmp_path / 'used').mkdir()
    (tmp_path / 'used' / 'old.txt').write_text('x')
    with pytest.raises(Refused, match='not empty'):
        run(attach_33, catalogue, mappings, tmp_path / 'p' / 'brickwork-4.db', tmp_path / 'used')
    assert not (tmp_path / 'p').exists()


def test_rows_that_need_a_decision_stop_the_run_and_publish_nothing(tmp_path, catalogue, mappings):
    src = tmp_path / 'bw33.db'
    build_33(src)
    with sqlite3.connect(src) as db:
        db.execute("UPDATE copy_parts SET quantity=1, missing=5 WHERE id=(SELECT min(id) FROM copy_parts)")
    with pytest.raises(NeedsDecision):
        go(tmp_path, src, catalogue, mappings)
    assert not (tmp_path / '1' / 'brickwork-4.db').exists() and not (tmp_path / '1' / 'report').exists()
    assert [p.name for p in (tmp_path / '1').iterdir()] == []


# ---------- pinning (design 8.2, finding 9.8) ----------

def test_the_report_records_the_hashes_of_the_catalogue_and_every_mapping_file(tmp_path, attach_33, catalogue, mappings):
    res = go(tmp_path, attach_33, catalogue, mappings)
    pins = json.loads((res.report / 'proof.json').read_text())['pins']
    assert pins['catalogue']['sha256'] == hashlib.sha256(catalogue.read_bytes()).hexdigest()
    assert pins['mappings'] == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(mappings.iterdir())}
    assert pins['shipped_mappings'] and 'parts.csv' in pins['shipped_mappings']
    assert read_pins(res.report / 'summary.md') == read_pins(res.report / 'proof.json') == read_pins(res.report) == pins


def test_a_pinned_run_with_identical_inputs_passes(tmp_path, attach_33, catalogue, mappings):
    first = go(tmp_path, attach_33, catalogue, mappings, '1')
    second = go(tmp_path, attach_33, catalogue, mappings, '2', pin=first.report / 'proof.json')
    assert second.result == 'PASS' and second.published
    third = go(tmp_path, attach_33, catalogue, mappings, '3', pin=first.report / 'summary.md')
    assert third.published


def test_a_changed_mapping_file_or_catalogue_refuses_before_anything_is_written(tmp_path, attach_33, catalogue, mappings):
    first = go(tmp_path, attach_33, catalogue, mappings, '1')
    changed = tmp_path / 'maps2'
    shutil.copytree(mappings, changed)
    with open(changed / 'parts.csv', 'a') as f:
        f.write('\n')
    with pytest.raises(PinMismatch, match='parts.csv') as raised:
        go(tmp_path, attach_33, catalogue, changed, '2', pin=first.report / 'proof.json')
    assert raised.value.differences and not (tmp_path / '2').exists()
    extra = tmp_path / 'maps3'
    shutil.copytree(mappings, extra)
    (extra / 'extra.csv').write_text('x')
    with pytest.raises(PinMismatch, match='extra.csv'):
        go(tmp_path, attach_33, catalogue, extra, '3', pin=first.report / 'proof.json')
    other = tmp_path / 'other-catalogue.db'
    shutil.copy(catalogue, other)
    with sqlite3.connect(other) as db:
        db.execute("UPDATE meta SET value=value||'x' WHERE key='app_version'") if db.execute("SELECT 1 FROM meta WHERE key='app_version'").fetchone() \
            else db.execute("INSERT INTO meta(key, value) VALUES('app_version', 'x')")
    with pytest.raises(PinMismatch, match='catalogue'):
        go(tmp_path, attach_33, other, mappings, '4', pin=first.report / 'proof.json')
    assert not (tmp_path / '4').exists()


def test_a_pin_file_without_pins_is_refused(tmp_path, attach_33, catalogue, mappings):
    (tmp_path / 'junk.json').write_text('{"result": "PASS"}')
    with pytest.raises(Refused, match='no pins'):
        go(tmp_path, attach_33, catalogue, mappings, pin=tmp_path / 'junk.json')
    with pytest.raises(Refused, match='cannot read'):
        go(tmp_path, attach_33, catalogue, mappings, pin=tmp_path / 'missing.json')


# ---------- the command and its exit codes ----------

def argv(tmp_path, src, catalogue, mappings, name='1', *extra):
    return ['migrate', '--in', str(src), '--catalogue', str(catalogue), '--mappings', str(mappings), '--out', str(tmp_path / name / 'brickwork-4.db'),
            '--report', str(tmp_path / name / 'report'), *extra]


def test_the_command_prints_a_summary_and_exits_zero_on_pass(tmp_path, attach_33, catalogue, mappings, capsys):
    out = io.StringIO()
    assert cli.main(argv(tmp_path, attach_33, catalogue, mappings), out=out) == 0
    text = out.getvalue()
    assert 'proof PASS' in text and 'copies' in text and '%' in text and str(tmp_path / '1' / 'report') in text and 'published' in text
    assert (tmp_path / '1' / 'brickwork-4.db').exists()
    again = io.StringIO()
    code = cli.main(['--json', *argv(tmp_path, attach_33, catalogue, mappings, '2', '--pin', str(tmp_path / '1' / 'report' / 'proof.json')), ], out=again)
    data = json.loads(again.getvalue())
    assert code == 0 and data['result'] == 'PASS' and data['published'] and data['attach']['copy']['attached'] == 2


def test_the_exit_codes_tell_fail_refused_and_needs_a_decision_apart(tmp_path, attach_33, catalogue, mappings, monkeypatch, capsys):
    real = migrate_run.prove

    def broken(temp, cat, src, result):
        tamper(TAMPERING['a quantity'][1])(type('M', (), {'temp_path': temp}))
        return real(temp, cat, src, result)
    monkeypatch.setattr(migrate_run, 'prove', broken)
    assert cli.main(argv(tmp_path, attach_33, catalogue, mappings, '1'), out=io.StringIO()) == cli.EXIT_FAILED_PROOF == 10
    assert not (tmp_path / '1' / 'brickwork-4.db').exists() and (tmp_path / '1' / 'report' / 'proof.json').exists()
    monkeypatch.setattr(migrate_run, 'prove', real)
    assert cli.main(argv(tmp_path, attach_33, catalogue, mappings, '2'), out=io.StringIO()) == 0
    assert cli.main(argv(tmp_path, attach_33, catalogue, mappings, '2'), out=io.StringIO()) == cli.EXIT_REFUSED == 11     # output and report exist
    assert 'refused' in capsys.readouterr().err
    maps2 = tmp_path / 'maps2'
    shutil.copytree(mappings, maps2)
    (maps2 / 'colors.csv').write_text((maps2 / 'colors.csv').read_text() + '\n')
    pin = str(tmp_path / '2' / 'report' / 'proof.json')
    assert cli.main(argv(tmp_path, attach_33, catalogue, maps2, '3', '--pin', pin), out=io.StringIO()) == cli.EXIT_REFUSED
    assert not (tmp_path / '3').exists()
    bad = tmp_path / 'bad33.db'
    build_33(bad)
    with sqlite3.connect(bad) as db:
        db.execute("UPDATE copy_parts SET quantity=1, missing=5 WHERE id=(SELECT min(id) FROM copy_parts)")
    assert cli.main(argv(tmp_path, bad, catalogue, mappings, '4'), out=io.StringIO()) == cli.EXIT_NEEDS_DECISION == 12
    assert 'needs a decision' in capsys.readouterr().err
    assert len({cli.EXIT_PASS, cli.EXIT_FAILED_PROOF, cli.EXIT_REFUSED, cli.EXIT_NEEDS_DECISION}) == 4


# ---------- review fixes (Codex, M.7c) ----------

def test_a_later_version_equal_on_the_4_0_items_is_attached_over_an_earlier_brick_link_only_match(tmp_path, attach_33, catalogue, mappings,
                                                                                                   monkeypatch):
    # two versions can project to the same BrickLink list with different 4.0 items: the one whose own digest matches wins
    from brickwork.store4 import migrate as migrate_mod
    original = migrate_mod._Writer._versions

    def versions(self, item_id, latest_only=False):
        rows = [dict(r) for r in original(self, item_id, latest_only)]
        v1 = next((r for r in rows if r['version'] == 1 and r['bl_digest']), None)
        return ([dict(v1, version=7, digest='another-list-of-items')] if v1 else []) + rows
    monkeypatch.setattr(migrate_mod._Writer, '_versions', versions)
    res = go(tmp_path, attach_33, catalogue, mappings)
    rec = records(res, 'copy')['copy-eq']
    assert (rec['status'], rec['version'], rec['ids_equal']) == ('attached', 1, True)


def test_a_catalogue_replaced_after_the_pin_check_is_refused(tmp_path, attach_33, catalogue, mappings, monkeypatch):
    real = migrate_run.compute_pins
    monkeypatch.setattr(migrate_run, 'compute_pins', lambda c, m: dict(real(c, m), catalogue={'name': 'x', 'sha256': 'the-pinned-one'}))
    with pytest.raises(Refused, match='changed between the pin check'):
        go(tmp_path, attach_33, catalogue, mappings)
    assert not (tmp_path / '1' / 'brickwork-4.db').exists() and not (tmp_path / '1' / 'report').exists()


def test_a_report_folder_reserved_by_another_run_is_refused(tmp_path, attach_33, catalogue, mappings):
    (tmp_path / 'r').mkdir()
    (tmp_path / 'r' / migrate_run.RESERVATION).touch()
    with pytest.raises(Refused):
        run(attach_33, catalogue, mappings, tmp_path / 'o' / 'brickwork-4.db', tmp_path / 'r')
    assert (tmp_path / 'r' / migrate_run.RESERVATION).exists()            # the other run's reservation is left alone
    res = go(tmp_path, attach_33, catalogue, mappings)
    assert not (res.report / migrate_run.RESERVATION).exists()            # a finished run releases its own
