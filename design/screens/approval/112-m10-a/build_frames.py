"""Approval frames of M.10 batch A (issue #112): the part list on the copy page and in the Add review. Re-runnable.

    <the canonical venv's python> design/approval/112-m10-a/build_frames.py [frame id ...]   (from the repo root)

It builds an invented 4.0 pair in a temporary folder (tests/m10a_data.py) and starts the real app on 127.0.0.1, twice: with BrickLink's key only
(most frames: no Rebrickable key, so an unmapped part has no picture) and with both keys (m10a8b), logs in with a session cookie and runs scripts/capture_screens.cjs at the three kit sizes,
light and dark. Nothing under data/ is read."""
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import logging
import threading

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
SIZES = (('phone', 390), ('ipad-portrait', 768), ('desktop', 1440))
BRICKLINK = {'BW_BRICKLINK_CONSUMER_KEY': 'x', 'BW_BRICKLINK_CONSUMER_SECRET': 'x', 'BW_BRICKLINK_TOKEN_VALUE': 'x', 'BW_BRICKLINK_TOKEN_SECRET': 'x'}
KEYS = {**BRICKLINK, 'BW_REBRICKABLE_API_KEY': 'x'}

# Scripts, run in the page before the capture: wait for a condition, click a button.
WAIT = "const until=async(f,n=100)=>{for(let i=0;i<n;i++){if(f())return true;await new Promise(r=>setTimeout(r,50));}return false;};"
OPEN_SHEET = WAIT + "document.querySelector('[data-bc-part-list]').click();await until(()=>document.querySelector('#bc-part-list[open] form'));"
FIGURES_TAB = WAIT + "document.querySelector('[data-bc-tab=figures]').click();await new Promise(r=>setTimeout(r,200));"


def serve(app):
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    from werkzeug.serving import make_server
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f'http://127.0.0.1:{server.server_port}'


def build_app(folder, rebrickable):
    """The app on a fresh pair in `folder`; returns (world, app). The pair is built with the keys set (a BrickLink copy needs one)."""
    from flask import Flask
    from brickwork.app import setup_app
    from brickwork.core.connect import connect
    from tests.app4 import Coll
    from tests.m10a_data import build_world, make_a_pair
    for name in KEYS:
        os.environ.pop(name, None)
    os.environ.update(BRICKLINK)                                    # a BrickLink copy needs the key to be made
    path = make_a_pair(folder)
    with closing(connect(path)) as db:
        world = build_world(Coll(db))
    if rebrickable:
        os.environ['BW_REBRICKABLE_API_KEY'] = 'x'                 # without it: BrickLink's key only, so the picker offers its list
    os.environ.update(BW_EMBEDDED_WORKER='0', BW_AUTHENTICATION_PASSWORD='synthetic-password', BW_DB_PATH=str(path))
    app = Flask('m10a-frames', template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    setup_app(app)
    app.config.update(SECRET_KEY='m10a-frames')
    return world, app


def session_cookie(app):
    """A logged-in session whose CSRF token is already set, so the page's scripts can write with a fixed Cookie header."""
    from tests.web_fixtures import logged_in
    client = logged_in(app)
    client.get('/collection/sets')
    return 'session=' + client.get_cookie('session').value


REVIEW = WAIT + """
const R=document.querySelector('#bw-add'),pause=ms=>new Promise(r=>setTimeout(r,ms));
const shown=()=>!R.querySelector('[data-review-panel]').hidden;
"""
# Add review with a set (the Part list picker), a part with no known picture and one with a picture; then the picker moved off its preselection.
ADD_REVIEW = REVIEW + """
const add=async(kind,text,expect)=>{R.querySelector(`input[name=type][value=${kind}]`).click();const i=R.querySelector('[data-search]');i.value=text;i.dispatchEvent(new Event('input',{bubbles:true}));
 await until(()=>{const f=R.querySelector('[data-results] .bw-add-item');return f&&f.textContent.includes(expect)&&[...f.querySelectorAll('button')].some(b=>b.textContent==='Select');});
 [...R.querySelector('[data-results] .bw-add-item').querySelectorAll('button')].find(b=>b.textContent==='Select').click();await pause(100);};
await add('set','1000-1','Syn Castle Keep');await add('part','dupupn0123a','dupupn0123a');await add('part','3001','3001');
R.querySelector('[data-review]').click();await until(shown);
for(let n=0;n<2;n++){const b=[...R.querySelectorAll('[data-review-rows] button.bw-add-colour')].find(x=>x.textContent==='Choose a colour');b.click();
 await until(()=>R.querySelector('[data-colour-dialog]').open);[...R.querySelectorAll('.bw-add-colour-choice')].find(x=>x.textContent.startsWith('Red')).click();
 await until(()=>!R.querySelector('[data-colour-dialog]').open);await pause(600);}
const pick=R.querySelector('select[aria-label^="Part list for"]');pick.value='bricklink';pick.dispatchEvent(new Event('change'));await pause(200);
"""
ADD_UNKNOWN = REVIEW + """
R.querySelector('input[name=mode][value=paste]').click();R.querySelector('[data-paste]').value='9999-1';R.querySelector('[data-paste]').dispatchEvent(new Event('input'));
R.querySelector('[data-review]').click();await until(shown);await pause(200);
"""
ADD_UNKNOWN_FETCH = ADD_UNKNOWN + "[...R.querySelectorAll('.bw-add-choice')].find(b=>b.textContent.startsWith('Fetch')).click();await pause(150);"


def frames(world):
    copy = lambda cid: f'/collection/item/{world.keep}?copy={cid}'                       # noqa: E731
    gate = lambda cid: f'/collection/item/{world.gate}?copy={cid}'                       # noqa: E731
    return [
        ('m10a1', 'copy-part-list', copy(world.copy_a), '', False),
        ('m10a1b', 'copy-part-list-bricklink', copy(world.copy_b), '', False),
        ('m10a2', 'switch-sheet', copy(world.copy_a), OPEN_SHEET, False),
        ('m10a2b', 'switch-sheet-whole', copy(world.copy_a), OPEN_SHEET, False, {'phone': 1350, 'ipad-portrait': 1200, 'desktop': 1200}),
        ('m10a3', 'bricklink-pending', gate(world.copy_d), '', False),
        ('m10a4', 'list-changed', copy(world.copy_e), '', False),
        ('m10a4b', 'list-changed-figures', copy(world.copy_e), FIGURES_TAB, False),
        ('m10a5', 'retired-lines-collapsed', copy(world.copy_f), '', False),
        ('m10a5b', 'retired-lines-open', copy(world.copy_f), "document.querySelector('.bc-retired').open=true;", False),
        ('m10a6', 'figure-part-sources', copy(world.copy_b), FIGURES_TAB, False),
        ('m10a7', 'add-review-part-list', '/manage/add', ADD_REVIEW, False),
        ('m10a8', 'add-review-unknown-number', '/manage/add', ADD_UNKNOWN, False),
        ('m10a8b', 'add-review-unknown-number-keyed', '/manage/add', ADD_UNKNOWN_FETCH, True),
    ]


def run(selected):
    for rebrickable in (False, True):
        folder = Path(tempfile.mkdtemp(prefix='m10a-'))
        try:
            world, app = build_app(folder, rebrickable)
            server, base = serve(app)
            cookie = session_cookie(app)
            todo = [f for f in frames(world) if f[4] == rebrickable and (not selected or f[0] in selected)]
            jobs = []
            for frame, view, url, script, _, *tall in todo:
                for device, width in SIZES:
                    for theme in ('light', 'dark'):
                        jobs.append(dict(url=base + url, out=str(OUT / f'{frame}-{view}-{device}-{width}-{theme}.png'), width=width, theme=theme, script=script,
                                         **({'height': tall[0][device]} if tall else {})))
            if jobs:
                spec = folder / 'jobs.json'
                spec.write_text(json.dumps(dict(headers={'Cookie': cookie}, jobs=jobs)))
                subprocess.run(['node', str(ROOT / 'scripts' / 'capture_screens.cjs'), CHROME, str(spec)], cwd=ROOT, check=True)
            server.shutdown()
        finally:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == '__main__':
    run(set(sys.argv[1:]))
