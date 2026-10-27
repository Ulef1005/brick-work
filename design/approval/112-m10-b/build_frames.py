"""M.10 batch B frames (issue #112): identity on the item page, merge and unmerge, Unresolved items, the unidentified item.

    /Users/adminuser/Workspace/brick-work/.venv/bin/python design/approval/112-m10-b/build_frames.py [--no-capture]

Builds an invented 4.0 pair (the fixture catalogue of tests/app4.py plus local items made here), starts the real app on 127.0.0.1, signs the
browser in with a session cookie, writes JOBS.json and runs scripts/capture_screens.cjs. Re-runnable: everything lives in a fresh temp folder.
Nothing under data/ and no network is touched."""
from contextlib import closing
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'

import os  # noqa: E402

from flask import Flask  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

from brickwork.app import setup_app  # noqa: E402
from brickwork.core import identity_admin  # noqa: E402
from brickwork.core.connect import connect  # noqa: E402
from brickwork.core.sources.base import audit_origin  # noqa: E402
from brickwork.web.auth import SESSION_PASSWORD, password_mark  # noqa: E402
from tests.app4 import Coll, STAMP, build_world, make_pair  # noqa: E402

DEVICES = [('phone', 390), ('ipad-portrait', 768), ('desktop', 1440)]
PASSWORD = 'synthetic-password'


def build(tmp):
    """The invented collection. Returns (path, ids)."""
    path = make_pair(tmp, rich=True)
    with closing(connect(path)) as db:
        coll = Coll(db)
        w = build_world(coll)
        ids = dict(w.__dict__)
        black, red, white = coll.colour('0'), w.red, w.white
        ids.update(black=black)
        # the leg rule (design 3.2): Rebrickable 970c03 is BrickLink 970c00 in Black and 970c11 in every other hip colour
        leg = coll.item('parts', '970c03')
        coll.add_stock('part', leg, colour=black, quantity=4, condition='used')
        coll.add_stock('part', leg, colour=red, quantity=2, condition='new')
        coll.project(leg) if not db.execute('SELECT 1 FROM main.item WHERE id=?', (leg,)).fetchone() else None
        ids['leg'] = leg
        # a sticker sheet with three BrickLink numbers (design 3.2): the user picks one
        sheet = coll.item('parts', '003402')
        coll.add_stock('part', sheet, colour=white, quantity=3, condition='new')
        ids['sheet'] = sheet
        # every pill and the keyless provider rows on one part: 3001 in red
        coll.link(w.brick, '3001a', kind='P', status='inferred')
        coll.link(w.brick, '3001b', kind='P', colour=red, status='manual', preferred=1)
        coll.link(w.brick, '3001-old', kind='parts', provider='rebrickable', status='to_check')
        coll.sql("INSERT INTO item_provider_status(item_id,provider,status,reason,evidence_json,checked_at) VALUES(?,'lego','unmatched','no_match',NULL,?)", (w.brick, STAMP))
        # merge: a BrickLink-born part that is the catalogue brick (rule-4 tie) with rows of its own
        tied = coll.local('part', 'Brick 2 x 4 (from BrickLink)', born_key='3001')
        coll.link(tied, '3001', kind='P', status='matched')
        coll.link(tied, '3001', kind='parts', provider='rebrickable', status='to_check')
        coll.add_stock('part', tied, colour=red, quantity=2, condition='used')
        coll.add_stock('part', tied, colour=black, quantity=1, condition='new')
        coll.add_wish(tied, colour=red, quantity=2, condition='any')
        coll.price(tied, '0.35', colour=red, condition='used', minimum='0.20', maximum='0.50', sold=5)
        ids['tied'] = tied
        # a second one that cannot merge: a copy holds a line for both items in one colour
        double = coll.local('part', 'Brick 2 x 4 (second entry)', born_key='3001-dup')
        copy_line = db.execute('SELECT * FROM main.copy_part WHERE copy_id=? AND item_id=? AND retired_at IS NULL LIMIT 1', (w.copy_a, w.brick)).fetchone()
        generated = {r['name'] for r in db.execute('PRAGMA main.table_xinfo(copy_part)') if r['hidden'] in (2, 3)}
        columns = [c for c in copy_line.keys() if c != 'id' and c not in generated]
        values = {c: copy_line[c] for c in columns}
        values['item_id'] = double
        db.execute(f'INSERT INTO main.copy_part({",".join(values)}) VALUES({",".join("?" * len(values))})', tuple(values.values()))
        db.commit()
        ids['double'] = double
        # a local plate for the done frame, merged by the script
        plate_local = coll.local('part', 'Plate 1 x 2 (from BrickLink)', born_key='3023')
        coll.link(plate_local, '3023', kind='P', status='matched')
        coll.add_stock('part', plate_local, colour=white, quantity=6, condition='used')
        ids['plate_local'] = plate_local
        # Unresolved items: more of each reason
        guess = coll.local('part', 'Hair (from BrickLink)', born_key='3901x')
        coll.link(guess, '3901', kind='parts', provider='rebrickable', status='to_check')
        coll.link(guess, 'dupupn0123', kind='parts', provider='rebrickable', status='to_check')
        coll.add_stock('part', guess, colour=black, quantity=3, condition='used')
        coll.link(w.figure, 'syn-fig-guess', kind='M', status='to_check')
        coll.sql("INSERT INTO item_provider_status(item_id,provider,status,reason,evidence_json,checked_at) VALUES(?,'bricklink','to_check','kind_differs',?,?)",
                 (w.local_booklet, json.dumps({'to': 'book'}), STAMP))
        cone = coll.local('part', 'Cone 1 x 1 (migrated)', born_key='cone-mig')
        coll.add_stock('part', cone, colour=red, quantity=8, condition='used')
        coll.sql("INSERT INTO item_provider_status(item_id,provider,status,reason,evidence_json,checked_at) VALUES(?,'bricklink','to_check','migration',NULL,?)", (cone, STAMP))
        coll.sql("INSERT INTO item_provider_status(item_id,provider,status,reason,evidence_json,checked_at) VALUES(?,'bricklink','to_check','no_candidate',NULL,?)", (w.local_part, STAMP))
        # merged items on a survivor (the hair), one of which cannot be taken back: its moved red row was edited afterwards
        hair = coll.item('parts', '3901')
        coll.add_stock('part', hair, colour=white, quantity=1, condition='new')
        ids['hair'] = hair
        with audit_origin('app'):
            for number, name, quantity, colour in (('3901-m2', 'Hair (BrickLink copy)', 7, red), ('3901-m1', 'Hair (old entry)', 4, black)):
                old = coll.local('part', name, born_key=number)
                coll.add_stock('part', old, colour=colour, quantity=quantity, condition='used')
                coll.add_wish(old, colour=colour, quantity=1, condition='any')
                ids['merged_' + number] = old
                identity_admin.merge_item(db, old, hair)
            db.execute('UPDATE main.stock SET quantity=quantity+1, updated_at=? WHERE item_id=? AND color_id=?', (STAMP, hair, red))
            db.commit()
            # done frame: the plate is merged right now, the event goes to the URL
            ids['done_event'] = identity_admin.merge_item(db, plate_local, w.plate)['event_id']
            # preferred, for one colour: the sticker sheet in white
            links = [r for r in db.execute("SELECT id, provider_key FROM main.item_link WHERE item_id=? AND provider='bricklink' ORDER BY provider_key", (sheet,))]
            ids['sheet_links'] = [dict(r) for r in links]
        db.commit()
    return path, ids


def session_cookie(app, extra=None):
    with app.app_context():
        mark = password_mark(app.config['AUTHENTICATION_PASSWORD'])
    data = {'_user_id': 'admin', '_fresh': True, SESSION_PASSWORD: mark, **(extra or {})}
    return 'session=' + app.session_interface.get_signing_serializer(app).dumps(data)


def main():
    capture = '--no-capture' not in sys.argv
    tmp = Path(tempfile.mkdtemp(prefix='bw-m10b-'))
    path, ids = build(tmp)
    os.environ.update(BW_EMBEDDED_WORKER='0', BW_AUTHENTICATION_PASSWORD=PASSWORD, BW_DB_PATH=str(path))
    app = Flask('m10b-frames', template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    setup_app(app)
    app.config.update(SECRET_KEY='synthetic-session')
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    item = lambda i, **q: f'{base}/collection/item/{i}' + ('?' + '&'.join(f'{k}={v}' for k, v in q.items()) if q else '')
    # a preferred choice for one colour on the sticker sheet (what the sheet's second button does), with its Undo notice
    with closing(connect(path)) as db, audit_origin('app'):
        choose = ids['sheet_links'][1]['id']
        prefer_event = identity_admin.set_preferred(db, choose, ids['white'])['event_id']
        db.commit()
    open_sheet = "document.querySelector('[data-bw-open=bi-prefer-bricklink]').click()"
    filters = ("document.querySelector('[data-bu-open=filters]').click();"
               "const r=document.querySelector('[data-bu-filter][value=merge]');r.checked=true;r.dispatchEvent(new Event('change',{bubbles:true}))")
    frames = [
        ('m10b1', 'links-leg-rule', item(ids['leg'], colour=ids['black']), None, '[data-identity-module=links]'),
        ('m10b1', 'links-statuses', item(ids['brick'], colour=ids['red']), None, '[data-identity-module=links]'),
        ('m10b2', 'prefer-sheet', item(ids['sheet'], colour=ids['white'], done=''), open_sheet, '[data-identity-module=links]'),
        ('m10b2', 'prefer-done', item(ids['sheet'], colour=ids['white'], done=prefer_event), None, '[data-identity-module=links]'),
        ('m10b3', 'merge-pick', f"{base}/collection/item/{ids['tied']}/merge", None, '.bi-merge'),
        ('m10b3', 'merge-preview', f"{base}/collection/item/{ids['tied']}/merge?target={ids['brick']}", None, '.bi-preview'),
        ('m10b3', 'merge-refused', f"{base}/collection/item/{ids['double']}/merge?target={ids['brick']}", None, '.bi-preview'),
        ('m10b3', 'merge-blocked', f"{base}/collection/item/{ids['brick']}/merge", None, '.bi-merge'),
        ('m10b3', 'merge-done', item(ids['plate'], colour=ids['white'], done=ids['done_event']), None, '.bi-notice'),
        ('m10b4', 'merged-item', item(ids['hair'], colour=ids['white']), None, '#bi-merged'),
        ('m10b5', 'unresolved', f'{base}/manage/unresolved', None, '[data-bu-row]'),
        ('m10b5', 'unresolved-filtered', f'{base}/manage/unresolved', filters, '[data-bu-row]'),
        ('m10b6', 'unidentified', item(ids['mystery']), None, '[data-identity-module=unidentified]'),
    ]
    jobs = []
    for frame, view, url, script, wait in frames:
        for device, width in DEVICES:
            for theme in ('light', 'dark'):
                job = dict(url=url, out=str(OUT / f'{frame}-{view}-{device}-{width}-{theme}.png'), width=width, theme=theme, wait=wait)
                if script:
                    job['script'] = script
                jobs.append((frame, view, job))
    # the merged-item page comes from an old address: the cookie carries the flag the redirect sets
    plain = {'Cookie': session_cookie(app)}
    followed = {'Cookie': session_cookie(app, {'bw_merged_from': ids['merged_3901-m1']})}
    runs = [('plain', plain, [j for f, v, j in jobs if v != 'merged-item'])]
    # the old-address notice is shown once (the redirect sets the flag, the next page pops it): one browser run, and one cookie, per capture
    runs += [(f'followed-{n}', followed, [j]) for n, j in enumerate(j for f, v, j in jobs if v == 'merged-item')]
    for name, headers, selected in runs:
        (tmp / f'jobs-{name}.json').write_text(json.dumps({'headers': headers, 'jobs': selected}))
    print('app on', base, '· data in', tmp, '· ids', {k: v for k, v in ids.items() if isinstance(v, int)})
    if capture:
        for name, _, _ in runs:
            subprocess.run(['node', str(ROOT / 'scripts' / 'capture_screens.cjs'), CHROME, str(tmp / f'jobs-{name}.json')], check=True, cwd=ROOT)
    server.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()
