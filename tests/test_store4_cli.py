"""`python -m brickwork.store4 catalogue ...` (M.2e, design 6.1, 6.2, 6.6, Q14): download with an injected fetch, import, rebuild,
reconcile and status on invented dumps and XML. No network."""
from contextlib import closing
from datetime import timedelta
import hashlib
import json
import subprocess
import sys

import pytest

from brickwork.store4 import cli, identity
from brickwork.store4.connect import connect
from brickwork.store4.dump import HEADERS
from tests.store4_dump import SETS, default, write_dump, write_mappings
from tests.test_store4_bricklink import EXTRA_SETS, ITEMS, write_xml
from tests.test_store4_reconcile import COLORS, PARTS, STAMP, ids, q, tables


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


class World:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.data = tmp_path / 'data'
        self.maps = write_mappings(tmp_path / 'maps', colors=COLORS, parts=PARTS)
        self.cat, self.col = self.data / 'catalogue.db', self.data / 'brickwork.db'

    def download_dir(self, day):
        return self.data / 'catalogue-src' / 'rebrickable' / day

    def make_download(self, day, **given):
        """A complete download directory (dump + manifest) without going through `download`."""
        d = write_dump(self.download_dir(day), **{**tables(), **given})
        entries = [dict(name=f'{n}.csv.gz', bytes=(d / f'{n}.csv.gz').stat().st_size,
                        sha256=hashlib.sha256((d / f'{n}.csv.gz').read_bytes()).hexdigest(), last_modified=None) for n in HEADERS]
        cli.write_manifest(d, entries, day)
        return d

    def run(self, capsys, *args, fetch=cli.http_fetch, json_out=False, expect=0):
        argv = ['--data', str(self.data), *(['--json'] if json_out else []), 'catalogue', *args]
        code = cli.main(argv, fetch=fetch, mappings_dir=self.maps, now=STAMP)
        captured = capsys.readouterr()
        assert code == expect, captured.err + captured.out
        return json.loads(captured.out) if json_out else captured

    def status(self, capsys):
        return self.run(capsys, 'status', json_out=True)

    def project(self, *keys):
        with closing(connect(self.col, self.cat)) as db:
            for k in keys:
                identity.project(db, ids(self.cat)[k])
            db.commit()


def fake_fetch(tables_=None, fail_on=None, calls=None):
    """Serves the invented dump's gzip files by URL; raises on the file `fail_on`."""
    import tempfile
    from pathlib import Path
    folder = Path(tempfile.mkdtemp())
    write_dump(folder, **(tables_ or tables()))

    def fetch(url):
        name = url.rsplit('/', 1)[1]
        if calls is not None:
            calls.append(name)
        if name == f'{fail_on}.csv.gz':
            raise ConnectionError('network went away')
        return (folder / name).read_bytes(), 'Fri, 23 Oct 2026 07:00:00 GMT'
    return fetch


# ---------- download ----------

def test_download_writes_files_manifest_and_the_q14_text(world, capsys):
    out = world.run(capsys, 'download', '--date', '2026-10-23', fetch=fake_fetch())
    assert 'Rebrickable asks for at most one download a day.' in out.out
    d = world.download_dir('2026-10-23')
    manifest = json.loads((d / 'manifest.json').read_text())
    assert [f['name'] for f in manifest['files']] == [f'{n}.csv.gz' for n in HEADERS]
    for f in manifest['files']:
        body = (d / f['name']).read_bytes()
        assert f['bytes'] == len(body) and f['sha256'] == hashlib.sha256(body).hexdigest()
        assert f['last_modified'] == 'Fri, 23 Oct 2026 07:00:00 GMT'
    assert not list(d.glob('*.part'))


def test_download_is_not_repeated_when_today_is_complete(world, capsys):
    world.run(capsys, 'download', '--date', '2026-10-23', fetch=fake_fetch())
    calls = []
    out = world.run(capsys, 'download', '--date', '2026-10-23', fetch=fake_fetch(calls=calls))
    assert calls == []
    assert 'at most one download a day' in out.out and 'catalogue import' in out.out
    world.run(capsys, 'download', '--date', '2026-10-23', '--force', fetch=fake_fetch(calls=calls))
    assert len(calls) == 12


def test_interrupted_download_has_no_manifest_and_import_refuses_it(world, capsys):
    err = world.run(capsys, 'download', '--date', '2026-10-23', fetch=fake_fetch(fail_on='parts'), expect=1).err
    d = world.download_dir('2026-10-23')
    assert 'error:' in err and 'Traceback' not in err
    assert not (d / 'manifest.json').exists() and not list(d.glob('*.part'))
    assert (d / 'colors.csv.gz').exists()
    err = world.run(capsys, 'import', expect=1).err                         # no complete download at all
    assert 'no complete download' in err
    err = world.run(capsys, 'import', '--src', str(d), expect=1).err
    assert 'manifest' in err and 'Traceback' not in err
    assert not world.cat.exists()


def test_a_forced_download_that_is_interrupted_drops_the_old_manifest(world, capsys):
    world.run(capsys, 'download', '--date', '2026-10-23', fetch=fake_fetch())
    world.run(capsys, 'download', '--date', '2026-10-23', '--force', fetch=fake_fetch(fail_on='sets'), expect=1)
    assert not (world.download_dir('2026-10-23') / 'manifest.json').exists()


def test_a_retry_after_an_interruption_completes(world, capsys):
    world.run(capsys, 'download', '--date', '2026-10-23', fetch=fake_fetch(fail_on='parts'), expect=1)
    world.run(capsys, 'download', '--date', '2026-10-23', fetch=fake_fetch())
    assert (world.download_dir('2026-10-23') / 'manifest.json').exists()


def test_import_refuses_a_download_changed_after_the_manifest(world, capsys):
    d = world.make_download('2026-10-23')
    body = (d / 'themes.csv.gz').read_bytes()
    (d / 'themes.csv.gz').write_bytes(body[:-5] + bytes([body[-5] ^ 1]) + body[-4:])
    err = world.run(capsys, 'import', expect=1).err
    assert 'themes.csv.gz' in err and 'Traceback' not in err


# ---------- import ----------

def test_import_on_a_fresh_data_dir_creates_activates_and_reconciles(world, capsys):
    world.make_download('2026-10-23')
    out = world.run(capsys, 'import', json_out=True)
    assert out['activation']['bound'] and out['activation']['builds'] == [1]
    assert world.col.exists() and world.cat.exists()
    st = world.status(capsys)
    assert st['collection']['catalogue_id'] == st['catalogue']['catalogue_id']
    assert [b['id'] for b in st['collection']['activated_builds']] == [b['id'] for b in st['catalogue']['builds']]
    assert all(b['reconciled_at'] for b in st['collection']['activated_builds'])
    assert st['collection']['last_reconcile']['coverage'] is not None
    assert st['download']['date'] == '2026-10-23' and st['catalogue']['bricklink_lists_loaded'] is False
    assert st['catalogue']['item_high_water'] and st['collection']['item_high_water'] == st['catalogue']['item_high_water']


def test_import_text_output_and_no_args_uses_the_newest_download(world, capsys):
    world.make_download('2026-10-22')
    world.make_download('2026-10-23', sets=SETS + [('7000-1', 'Newer Set', '2020', '186', '1', '')])
    out = world.run(capsys, 'import').out
    assert 'reconcile:' in out and 'activated builds' in out
    assert 'Newer Set' in json.dumps(q(world.cat, 'SELECT name FROM item'))


def test_second_import_from_a_newer_download_keeps_every_referenced_id(world, capsys):
    world.make_download('2026-10-22')
    world.run(capsys, 'import')
    world.project('6081-1', '3023', '3001')
    before = ids(world.cat)
    world.make_download('2026-10-23', sets=SETS + [('7000-1', 'Newer Set', '2020', '186', '1', '')])
    world.run(capsys, 'import')
    after = ids(world.cat)
    assert all(after[k] == v for k, v in before.items())
    assert '7000-1' in after and after['7000-1'] not in before.values()
    st = world.status(capsys)
    assert len(st['collection']['activated_builds']) == len(st['catalogue']['builds'])


def test_local_layer_is_used_when_data_mappings_has_csv_files(world, capsys):
    world.make_download('2026-10-23')
    world.run(capsys, 'import')
    assert cli.Paths(world.data).local_dir() is None
    (world.data / 'mappings').mkdir()
    (world.data / 'mappings' / 'notes.txt').write_text('x')
    assert cli.Paths(world.data).local_dir() is None
    (world.data / 'mappings' / 'minifigs.csv').write_text('x')
    assert cli.Paths(world.data).local_dir() == world.data / 'mappings'


# ---------- rebuild ----------

def test_rebuild_after_the_catalogue_is_deleted_keeps_the_ids(world, capsys):
    world.make_download('2026-10-23')
    world.run(capsys, 'import')
    world.project('6081-1', '3023', '3001')
    before = ids(world.cat)
    world.cat.unlink()
    world.run(capsys, 'rebuild')
    after = ids(world.cat)
    assert all(after[k] == before[k] for k in ('6081-1', '3023', '3001'))       # the collection's items; the rest is numbered afresh
    assert not list(world.data.glob('catalogue.db.damaged-*'))
    st = world.status(capsys)
    assert st['collection']['catalogue_id'] == st['catalogue']['catalogue_id']


def test_rebuild_moves_a_damaged_catalogue_aside_and_keeps_it(world, capsys):
    world.make_download('2026-10-23')
    world.run(capsys, 'import')
    world.project('6081-1', '3023')
    before = ids(world.cat)
    world.cat.write_bytes(b'not a database' * 100)
    world.run(capsys, 'rebuild')
    aside = list(world.data.glob('catalogue.db.damaged-*'))
    assert len(aside) == 1 and aside[0].read_bytes() == b'not a database' * 100
    after = ids(world.cat)
    assert all(after[k] == before[k] for k in ('6081-1', '3023'))


def test_a_failed_rebuild_puts_the_catalogue_back(world, capsys):
    d = world.make_download('2026-10-23')
    world.run(capsys, 'import')
    original = world.cat.read_bytes()
    (d / 'themes.csv.gz').write_bytes(b'junk')
    # a manifest that still matches the junk, so the failure comes from the builder, not the manifest check
    entries = [dict(name=f'{n}.csv.gz', bytes=(d / f'{n}.csv.gz').stat().st_size,
                    sha256=hashlib.sha256((d / f'{n}.csv.gz').read_bytes()).hexdigest(), last_modified=None) for n in HEADERS]
    cli.write_manifest(d, entries, '2026-10-23')
    err = world.run(capsys, 'rebuild', expect=1).err
    assert 'error:' in err and 'Traceback' not in err
    assert world.cat.read_bytes() == original


# ---------- reconcile, bricklink, status ----------

def test_reconcile_prints_changes_not_applied_and_coverage(world, capsys):
    world.make_download('2026-10-23')
    world.run(capsys, 'import')
    world.project('6081-1', '3023')
    out = world.run(capsys, 'reconcile').out
    assert 'changes:' in out and 'not applied:' in out and 'coverage set:' in out
    again = world.run(capsys, 'reconcile', json_out=True)
    assert again['activation']['builds'] == [] and again['reconcile']['changes'] == {}


def test_reconcile_without_a_catalogue_is_an_error(world, capsys):
    err = world.run(capsys, 'reconcile', expect=1).err
    assert 'catalogue.db' in err and 'Traceback' not in err


def test_import_bricklink_loads_the_lists_then_activates_and_reconciles(world, capsys):
    world.make_download('2026-10-23')
    world.run(capsys, 'import')
    world.project('6081-1')
    lists = write_xml(world.tmp / 'bl', ITEMS)
    out = world.run(capsys, 'import', 'bricklink', '--from', str(lists), json_out=True)
    assert out['bricklink']['counts']['items'] == len(ITEMS)
    st = world.status(capsys)
    assert st['catalogue']['bricklink_lists_loaded'] and st['catalogue']['bricklink_items'] == len(ITEMS)
    assert any(b['kind'] == 'bricklink_list' for b in st['catalogue']['builds'])
    assert len(st['collection']['activated_builds']) == len(st['catalogue']['builds'])
    assert all(b['reconciled_at'] for b in st['collection']['activated_builds'])
    # and the next Rebrickable import carries the lists
    world.make_download('2026-10-24')
    world.run(capsys, 'import')
    assert world.status(capsys)['catalogue']['bricklink_lists_loaded']


def test_import_bricklink_without_a_catalogue_is_an_error(world, capsys):
    lists = write_xml(world.tmp / 'bl', ITEMS)
    err = world.run(capsys, 'import', 'bricklink', '--from', str(lists), expect=1).err
    assert 'does not exist' in err and 'Traceback' not in err


def test_status_text_on_an_empty_data_dir(world, capsys):
    out = world.run(capsys, 'status').out
    assert 'catalogue: none' in out and 'collection: none' in out and 'newest download: none' in out


def test_status_text_after_an_import(world, capsys):
    world.make_download('2026-10-23')
    world.run(capsys, 'import')
    out = world.run(capsys, 'status').out
    for text in ('rebrickable_dump', 'BrickLink lists: not loaded', 'bl_digest:', 'last reconcile:', 'newest download:'):
        assert text in out


# ---------- review fixes ----------

def hold(path):
    import fcntl
    lock = open(path, 'a')
    fcntl.flock(lock, fcntl.LOCK_EX)
    return lock


def test_rebuild_takes_the_lock_before_moving_the_catalogue(world, capsys):
    world.make_download('2026-10-23')
    world.run(capsys, 'import')
    original = world.cat.read_bytes()
    lock = hold(world.data / 'catalogue.db.lock')
    try:
        err = world.run(capsys, 'rebuild', expect=1).err
    finally:
        lock.close()
    assert 'another catalogue build' in err and 'Traceback' not in err
    assert world.cat.read_bytes() == original and not list(world.data.glob('catalogue.db.damaged-*'))


def test_a_second_download_is_refused_as_busy_and_touches_nothing(world, capsys):
    world.download_dir('x').parent.mkdir(parents=True)
    lock = hold(world.download_dir('x').parent / '.lock')
    try:
        calls = []
        err = world.run(capsys, 'download', '--date', '2026-10-23', fetch=fake_fetch(calls=calls), expect=1).err
    finally:
        lock.close()
    assert 'busy' in err and 'Traceback' not in err and calls == []
    assert not world.download_dir('2026-10-23').exists()


def test_text_status_summarises_a_non_empty_not_applied_once(world, capsys):
    import sqlite3
    world.make_download('2026-10-23')
    world.run(capsys, 'import')
    with closing(sqlite3.connect(world.col)) as db:
        counts = json.loads(db.execute('SELECT counts_json FROM catalogue_build ORDER BY id DESC LIMIT 1').fetchone()[0])
        counts['reconcile']['not_applied'] = {'downgrade': [{'item_id': 1}, {'item_id': 2}], 'vanished': [{'item_id': 3}]}
        db.execute('UPDATE catalogue_build SET counts_json=? WHERE id=(SELECT max(id) FROM catalogue_build)', (json.dumps(counts),))
        db.commit()
    out = world.run(capsys, 'status').out
    assert 'downgrade 2' in out and 'vanished 1' in out
    assert world.status(capsys)['collection']['last_reconcile']['not_applied'] == {'downgrade': 2, 'vanished': 1}


@pytest.mark.parametrize('manifest', [
    {'files': [{'name': 'colors.csv.gz', 'sha256': 'x'}]},                       # no bytes
    {'files': [{'bytes': 1, 'sha256': 'x'}]},                                    # no name
    {'files': [{'name': 'colors.csv.gz', 'bytes': 'ten', 'sha256': 'x'}]},       # wrong type
    {'files': [{'name': 'colors.csv.gz', 'bytes': 1}]},                          # no sha256
    {'files': 5}, {'files': [7]}, [], 'text'])
def test_a_malformed_manifest_is_an_incomplete_download(world, capsys, manifest):
    good = world.make_download('2026-10-22')
    d = world.make_download('2026-10-23')
    (d / 'manifest.json').write_text(json.dumps(manifest))
    assert cli.newest_download(cli.Paths(world.data))[0].name == '2026-10-22'      # skipped, not a KeyError
    err = world.run(capsys, 'import', '--src', str(d), expect=1).err
    assert 'error:' in err and 'Traceback' not in err
    world.run(capsys, 'import')                                                    # falls back to the older complete one
    assert good.exists()


def test_rebuild_reloads_the_newest_bricklink_lists_from_disk(world, capsys):
    world.make_download('2026-10-23', sets=EXTRA_SETS)
    write_xml(world.data / 'bricklink-lists' / '2026-10-01', ITEMS[:2])
    lists = write_xml(world.data / 'bricklink-lists' / '2026-10-12', ITEMS)
    world.run(capsys, 'import')
    world.project('5001-1')
    world.cat.unlink()
    out = world.run(capsys, 'rebuild').out
    assert 'BrickLink lists imported' in out
    st = world.status(capsys)
    assert st['catalogue']['bricklink_lists_loaded'] and st['catalogue']['bricklink_items'] == len(ITEMS)
    assert q(world.cat, "SELECT kind, kind_source FROM item WHERE born_key='5001-1'") == [{'kind': 'book', 'kind_source': 'bricklink'}]
    assert lists.exists()


def test_rebuild_says_when_there_are_no_lists_to_reload(world, capsys):
    world.make_download('2026-10-23')
    world.run(capsys, 'import')
    out = world.run(capsys, 'rebuild').out
    assert 'BrickLink lists are not loaded' in out
    assert world.run(capsys, 'rebuild', json_out=True)['bricklink'] is None


# ---------- errors ----------

def test_a_second_builder_is_refused_without_a_traceback(world, capsys):
    import fcntl
    world.make_download('2026-10-23')
    world.data.mkdir(parents=True, exist_ok=True)
    with open(world.data / 'catalogue.db.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        err = world.run(capsys, 'import', expect=1).err
    assert 'another catalogue build' in err and 'Traceback' not in err


def test_a_mismatched_catalogue_is_refused_without_a_traceback(world, capsys, tmp_path):
    world.make_download('2026-10-23')
    world.run(capsys, 'import')
    other = World(tmp_path / 'other')
    other.make_download('2026-10-23')
    other.run(capsys, 'import')
    world.cat.unlink()
    (other.data / 'catalogue.db').rename(world.cat)
    err = world.run(capsys, 'reconcile', expect=1).err
    assert 'error:' in err and 'Traceback' not in err


def test_json_errors_are_json_and_non_zero(world, capsys):
    out = world.run(capsys, 'import', json_out=True, expect=1)
    assert 'error' in out


def test_module_help_runs():
    done = subprocess.run([sys.executable, '-m', 'brickwork.store4', '--help'], capture_output=True, text=True)
    assert done.returncode == 0 and 'catalogue' in done.stdout
    done = subprocess.run([sys.executable, '-m', 'brickwork.store4', 'catalogue', '--help'], capture_output=True, text=True)
    assert done.returncode == 0 and 'rebuild' in done.stdout


def test_module_exits_non_zero_without_a_traceback(tmp_path):
    done = subprocess.run([sys.executable, '-m', 'brickwork.store4', '--data', str(tmp_path), 'catalogue', 'import'], capture_output=True, text=True)
    assert done.returncode == 1 and 'Traceback' not in done.stderr and done.stderr.startswith('error:')


# ---------- fetch and jobs (M.5d) ----------

@pytest.fixture
def fetching(tmp_path, monkeypatch):
    from tests.store4_fixtures import pair
    from tests.test_store4_jobs import KEYS
    for name, value in KEYS.items():
        monkeypatch.setenv(name, value)
    for name in ('BW_BRICKLINK_DAILY_BUDGET', 'BW_REBRICKABLE_DAILY_BUDGET'):
        monkeypatch.delenv(name, raising=False)
    pair(tmp_path)
    return tmp_path


def fetch_cli(data, capsys, *args, http, expect=0, json_out=False):
    code = cli.main(['--data', str(data), *(['--json'] if json_out else []), *args], http=http, clock=T_FETCH)
    captured = capsys.readouterr()
    assert code == expect, captured.err + captured.out
    return json.loads(captured.out) if json_out else captured


def T_FETCH():
    from tests.test_store4_jobs import T0
    return T0


def test_fetch_bricklink_queues_runs_and_prints_the_summary(fetching, capsys):
    from tests.test_store4_jobs import Net
    out = fetch_cli(fetching, capsys, 'fetch', 'bricklink', '6081-1', http=Net()).out
    assert 'job 1 bricklink_subsets 6081-1: done, attempt 1, 1 call(s)' in out
    assert '2 required (11 pieces), 1 spare lines (3), 0 figure lines' in out and 'digest matches no catalogue version' in out
    with closing(connect(fetching / 'brickwork.db', fetching / 'catalogue.db')) as db:
        assert [tuple(r) for r in db.execute('SELECT job_id, source FROM main.fetched_inventory')] == [(1, 'bricklink')]


def test_fetch_rebrickable_prints_the_summary_and_json_is_the_run_result(fetching, capsys):
    from tests.test_store4_jobs import Net, rebrickable
    out = fetch_cli(fetching, capsys, 'fetch', 'rebrickable', 'NEW-1', http=Net(rb=rebrickable()), json_out=True)
    assert (out['state'], out['kind'], out['step']['count']) == ('done', 'rebrickable_set', 5)
    assert out['result']['part_lines'] == 2 and len(out['result']['figure_lists']) == 2


def test_fetch_that_does_not_finish_prints_why_and_exits_1(fetching, capsys):
    from tests.test_store4_jobs import Net
    out = fetch_cli(fetching, capsys, 'fetch', 'bricklink', '6081-1', http=Net(bl=(404, {})), expect=1).out
    assert 'failed' in out and 'not_found' in out


def test_fetch_for_a_set_nobody_holds_or_one_the_catalogue_has_is_an_error(fetching, capsys):
    from tests.test_store4_jobs import Net
    err = fetch_cli(fetching, capsys, 'fetch', 'bricklink', 'NEW-1', http=Net(), expect=1).err
    assert 'fetch it from Rebrickable first' in err
    err = fetch_cli(fetching, capsys, 'fetch', 'rebrickable', '6081-1', http=Net(), expect=1).err
    assert 'catalogue already has set 6081-1' in err


def test_fetch_without_a_collection_is_an_error(tmp_path, capsys):
    assert cli.main(['--data', str(tmp_path), 'fetch', 'bricklink', '6081-1']) == 1
    assert 'catalogue import' in capsys.readouterr().err


def test_jobs_lists_and_drain_runs_what_is_due(fetching, capsys, monkeypatch):
    from tests.test_store4_jobs import Net
    monkeypatch.setenv('BW_BRICKLINK_DAILY_BUDGET', '1')
    fetch_cli(fetching, capsys, 'fetch', 'bricklink', '6081-1', http=Net())
    fetch_cli(fetching, capsys, 'fetch', 'bricklink', '6081-1', http=Net(), expect=1)              # budget used: waits
    listed = fetch_cli(fetching, capsys, 'jobs', http=Net()).out
    assert 'job 1 bricklink_subsets 6081-1: done' in listed and 'job 2 bricklink_subsets 6081-1: waiting_for_budget' in listed
    assert 'no job was due' in fetch_cli(fetching, capsys, 'jobs', 'drain', http=Net()).out
    code = cli.main(['--data', str(fetching), 'jobs', 'drain'], http=Net(), clock=lambda: T_FETCH() + timedelta(days=1))
    assert code == 0 and 'job 2 bricklink_subsets 6081-1: done' in capsys.readouterr().out
    assert fetch_cli(fetching, capsys, 'jobs', http=Net(), json_out=True)['jobs'][1]['state'] == 'done'
