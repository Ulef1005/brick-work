"""#35 wishlist progress: derived filled quantity, manual override, QTYFILLED export, API and page. Invented data."""
from contextlib import closing
import os

from bs4 import BeautifulSoup

from brickwork.core import collection, planning, wishlists
from brickwork.core.connect import connect
from tests.test_bw_api_m1 import app  # noqa: F401
from tests.test_bw_api_m2 import populated  # noqa: F401

H = {'Authorization': 'Bearer synthetic-bootstrap'}


def store():
    return closing(connect(os.environ['BW_DB_PATH']))


def test_derived_manual_and_order(populated):
    with store() as db:
        with db:
            # Wish 1: 2 used 3001 red; loose stock t1 holds 9 used: filled. Wish 2: a set with one copy of three wanted.
            db.execute("INSERT INTO wishlist(item_type,item_no,quantity,condition,list_id) VALUES('S','100-1',3,'any','default')")
        rows = {r['item_no']: r for r in planning.wishes(db)}
        part, kit = rows['3001'], rows['100-1']
        assert (part['qty_filled'], part['qty_filled_source'], part['filled']) == (9, 'derived', True)
        assert (kit['qty_filled'], kit['filled']) == (1, False)
        assert [r['item_no'] for r in planning.wishes(db)] == ['100-1', '3001']  # filled lines last
        collection.save(db, 'wish', [kit['id']], {'qty_filled_manual': '3'})
        kit = next(r for r in planning.wishes(db) if r['item_no'] == '100-1')
        assert (kit['qty_filled'], kit['qty_filled_source'], kit['filled']) == (3, 'manual', True)
        collection.save(db, 'wish', [kit['id']], {'qty_filled_manual': ''})
        assert next(r for r in planning.wishes(db) if r['item_no'] == '100-1')['qty_filled_source'] == 'derived'


def test_export_writes_qtyfilled_capped(populated):
    with store() as db:
        result = wishlists.export(db, 'default', format='bricklink')
    assert '<QTYFILLED>2</QTYFILLED>' in result['content']  # 9 in stock, capped at the wanted 2


def test_api_fields_and_patch(populated):
    c = populated.test_client()
    wish = c.get('/api/v1/wishes/1', headers=H).json['data']
    assert (wish['qty_filled'], wish['qty_filled_source'], wish['qty_filled_manual']) == (9, 'derived', None)
    etag = c.get('/api/v1/wishes/1', headers=H).headers.get('ETag')
    patched = c.patch('/api/v1/wishes/1', json={'qty_filled_manual': 1}, headers=dict(H, **{'Idempotency-Key': 'wf-1', 'If-Match': etag or '*'}))
    assert patched.status_code == 200, patched.json
    wish = c.get('/api/v1/wishes/1', headers=H).json['data']
    assert (wish['qty_filled'], wish['qty_filled_source']) == (1, 'manual')


def test_wishlist_page_progress_and_chip(populated):
    from tests.web_fixtures import logged_in
    from brickwork.app import setup_app
    from flask import Flask
    from tests.web_fixtures import ROOT
    os.environ.setdefault('BW_AUTHENTICATION_PASSWORD', 'synthetic-password')
    web = Flask('wish-progress', template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    setup_app(web)
    web.config.update(TESTING=True, SECRET_KEY='synthetic-session')
    soup = BeautifulSoup(logged_in(web).get('/planning/wishlist').data, 'html.parser')
    line = soup.select_one('.bp-filled')
    assert line['data-filled'] == 'true' and line.select_one('.mono').get_text() == '2 of 2' and 'Filled' in line.get_text()
    chip = soup.select_one('[data-bp-pick=filled][data-value=false]')
    assert chip and chip.get_text(' ', strip=True).startswith('Not yet filled')
