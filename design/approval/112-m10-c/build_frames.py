#!/usr/bin/env python3
"""M.10 batch C frames (#112): builds an invented 4.0 pair, runs the real app on 127.0.0.1, walks it through the screen states of the
catalogue lifecycle and captures each at the three kit sizes, light and dark, into this folder.

    /path/to/.venv/bin/python design/approval/112-m10-c/build_frames.py [--chrome PATH] [--only m10c1,m10c4]

Re-runnable: everything is built in a fresh temp dir. Nothing reads data/ or ~/Backups; the report, the dumps and the BrickLink XML are invented
(the test fixtures), and the app is pointed at the temp pair by BW_DB_PATH."""
import argparse
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from contextlib import closing

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
SIZES = (('phone', 390), ('ipad-portrait', 768), ('desktop', 1440))

import logging
logging.getLogger('werkzeug').setLevel(logging.ERROR)
os.environ.update(BW_EMBEDDED_WORKER='0', BW_AUTHENTICATION_PASSWORD='synthetic-password')


def served(tmp, name, edit=None, extra=None):
    """A fixture Rebrickable dump as the twelve gz files a fetch would serve; `edit(plain_dir)` may change the plain CSVs first."""
    from tests.store4_mint_fixtures import build_catalogue
    base = tmp / name
    base.mkdir()
    build_catalogue(base, extra_dump=extra)
    if edit:
        edit(base / 'plain')
    files = {}
    for plain in sorted((base / 'plain').glob('*.csv')):
        files[plain.name + '.gz'] = gzip.compress(plain.read_bytes())
    return files


def fetcher(files):
    return lambda url: (files[url.rsplit('/', 1)[1]], 'Mon, 26 Oct 2026 08:00:00 GMT')


def newer_dump(plain):
    """The next Rebrickable dump: one set gone (kept as retired), one renamed, one new, and a part list of 1000-1 changed."""
    sets = plain / 'sets.csv'
    lines = [l for l in sets.read_text().splitlines() if not l.startswith('10018247-1,')]
    lines = [l.replace('Syn Castle Gate', 'Syn Castle Gate (2026)') for l in lines]
    lines.append('1000-3,Syn Castle Drawbridge,2026,600,9,')
    sets.write_text('\n'.join(lines) + '\n')
    inv = plain / 'inventories.csv'
    inv.write_text(inv.read_text().rstrip('\n') + '\n9003,1,1000-3\n')
    parts = plain / 'inventory_parts.csv'
    text = parts.read_text().replace('9001,3001,4,4,False,', '9001,3001,4,5,False,')
    parts.write_text(text.rstrip('\n') + '\n9003,3001,4,3,False,\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--chrome', default=CHROME)
    ap.add_argument('--only', default='')
    args = ap.parse_args()
    only = {x for x in args.only.split(',') if x}

    from flask import Flask
    from werkzeug.serving import make_server
    from brickwork.app import setup_app
    from brickwork.core.connect import connect
    from brickwork.store4 import cli, jobs as fetch_jobs
    from brickwork.web import catalogue_jobs
    from brickwork.web.auth import SESSION_PASSWORD, password_mark
    from tests.app4 import Coll, RICH, build_world, make_pair
    from tests.store4_migrate_fixtures import build_33  # noqa: F401  (the report below uses the migration fixtures)
    from tests.test_store4_bricklink import ITEMS, write_xml
    from tests.test_store4_migrate_run import FIXTURES, make_attach_33, run as run_migration
    from tests.store4_mint_fixtures import build_catalogue

    root = Path(tempfile.mkdtemp(prefix='m10c-frames-'))
    tmp = root / 'data'
    tmp.mkdir()
    pair = make_pair(tmp, rich=True)
    paths = cli.Paths(pair.parent)
    with closing(connect(pair)) as db:
        build_world(Coll(db))
    os.environ['BW_DB_PATH'] = str(pair)

    # the download the catalogue was built from (23 Oct), and the next dump a re-download will fetch
    old_files = served(tmp, 'old', extra=RICH)
    cli.download(paths, day='2026-10-23', fetch=fetcher(old_files), say=lambda *_: None)
    new_files = served(tmp, 'new', edit=newer_dump, extra=RICH)

    # an invented migration report, written by the real migration on the migration fixtures
    (tmp / 'mig').mkdir()
    src, maps = tmp / 'mig' / 'bw33.db', tmp / 'mig' / 'maps'
    make_attach_33(src)
    shutil.copytree(FIXTURES / 'mappings', maps)
    (tmp / 'mig' / 'cat').mkdir()
    res = run_migration(src, build_catalogue(tmp / 'mig' / 'cat'), maps, tmp / 'mig' / 'out' / 'brickwork-4.db', tmp / 'mig' / 'report')
    report = tmp / 'migration-report'
    shutil.copytree(res.report, report)
    (report / '.migration-run').unlink(missing_ok=True)

    app = Flask('m10c-frames', template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    setup_app(app)
    app.config.update(SECRET_KEY='frames-session')
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    with app.test_request_context():
        from flask import session
        session['_user_id'], session['_fresh'] = 'admin', True
        session[SESSION_PASSWORD] = password_mark(app.config['AUTHENTICATION_PASSWORD'])
        cookie = app.session_interface.get_signing_serializer(app).dumps(dict(session))
    headers = {'Cookie': f'session={cookie}'}

    def shoot(frame, view, page, script=None, wait=None):
        if only and frame not in only:
            return
        jobs = [dict(url=f'{base}/manage/{page}', out=str(OUT / f'{frame}-{view}-{device}-{width}-{theme}.png'), width=width, theme=theme,
                     **({'script': script} if script else {}), **({'wait': wait} if wait else {}))
                for device, width in SIZES for theme in ('light', 'dark')]
        jobs_file = tmp / f'{frame}.json'
        jobs_file.write_text(json.dumps(dict(headers=headers, jobs=jobs)))
        subprocess.run(['node', str(ROOT / 'scripts' / 'capture_screens.cjs'), args.chrome, str(jobs_file)], check=True, cwd=ROOT)

    def forget():
        (paths.data / catalogue_jobs.FILE).unlink(missing_ok=True)

    def sql(statement):
        with closing(__import__('sqlite3').connect(pair)) as db:
            db.execute(statement)
            db.commit()

    # m10c1: the current build, reconciled, a download on disk
    catalogue_jobs.start(paths, 'reconcile', background=False)
    forget()
    shoot('m10c1', 'catalogue', 'catalogue')
    # m10c2a: a re-download in progress (this process owns the job, so it does not read as stopped)
    catalogue_jobs._write(paths, dict(kind='redownload', state='running', pid=os.getpid(), started_at=catalogue_jobs._now(), finished_at=None,
                                      step=1, folder=None, error=None, result=None))
    shoot('m10c2a', 'redownload-running', 'catalogue')
    forget()
    # m10c2c: built and swapped in, not reconciled yet
    sql('UPDATE catalogue_build SET reconciled_at=NULL')
    shoot('m10c2c', 'not-reconciled', 'catalogue')
    catalogue_jobs.start(paths, 'reconcile', background=False)
    forget()
    # m10c2b: the re-download finished
    catalogue_jobs.FETCH = fetcher(new_files)
    state = catalogue_jobs.start(paths, 'redownload', background=False)
    assert state['state'] == 'done', state
    shoot('m10c2b', 'redownload-result', 'catalogue')
    forget()
    # m10c3: the BrickLink item lists, loaded from a folder
    write_xml(paths.lists / '2026-10-26', ITEMS + [('S', '1000-1', 'Syn Castle Keep'), ('S', '1000-2', 'Syn Castle Gate'), ('S', '1000-3', 'Syn Castle Drawbridge'),
                                                  ('P', 'x999', 'Only on BrickLink')])
    write_xml(paths.lists / '2026-09-14', ITEMS)
    state = catalogue_jobs.start(paths, 'lists', folder='2026-10-26', background=False)
    assert state['state'] == 'done', state
    forget()
    shoot('m10c3', 'bricklink-lists', 'catalogue-lists')
    # m10c4: mapping files and coverage
    paths.mappings.mkdir(exist_ok=True)
    (paths.mappings / 'parts.csv').write_text('# mapping_version: 2026.10.24.1\n# dump_date: 2026-10-24\n# source: SYNTHETIC\n'
                                              'rb_part_num,rb_color_id,provider,provider_kind,provider_key,status,method,preferred\n'
                                              + ''.join(f'{n},,bricklink,P,{n},matched,external_ids,0\n' for n in ('3001', '3023', '3622', '3710')))
    (paths.mappings / 'parts.manifest.json').write_text(json.dumps(dict(source='SYNTHETIC')))
    shoot('m10c4', 'mappings-coverage', 'catalogue-mappings')
    # m10c5: Settings, with a BrickLink key (switch on) and without
    only_settings = ("document.querySelectorAll('section.bw-card').forEach(s=>{if(!['part-lists','picture-priority'].includes(s.id))s.style.display='none';});")
    original = fetch_jobs._configured
    fetch_jobs._configured = lambda source: False
    shoot('m10c5a', 'settings-no-key', 'settings', script=only_settings)
    fetch_jobs._configured = lambda source: True
    from brickwork.web import admin_ops
    admin_ops.set_prefer_bricklink(True)
    shoot('m10c5', 'settings-part-lists', 'settings', script=only_settings)
    fetch_jobs._configured = original
    # m10c6: the migration report
    os.environ['BW_MIGRATION_REPORT'] = str(report)
    sql("INSERT OR REPLACE INTO meta(key,value) VALUES('migrated_from', '" + json.dumps(dict(file='bw33.db', report_digest=res.digest)) + "')")
    shoot('m10c6', 'migration-report', 'migration')
    server.shutdown()
    shutil.rmtree(root, ignore_errors=True)
    print('done:', len(list(OUT.glob('*.png'))), 'frames in', OUT)


if __name__ == '__main__':
    main()
