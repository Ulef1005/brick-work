"""#45 identification shows whether and where you own the part. Invented data."""
from contextlib import closing
import os

from bs4 import BeautifulSoup

from brickwork.core import ownership, part_inventory
from brickwork.core.connect import connect
from tests.test_bw_api_m1 import app  # noqa: F401
from tests.test_bw_api_m2 import populated  # noqa: F401
from tests.test_bw_collection import bw, legacy, reset_shell_metadata_after_test  # noqa: F401
from tests.web_fixtures import apps, logged_in  # noqa: F401


def store():
    return closing(connect(os.environ['BW_DB_PATH']))


def test_summary_text_and_candidates(populated):
    with store() as db:
        with db:
            db.execute("INSERT INTO colors VALUES(11,'Synthetic black','Solid','111111')")
            db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES('t2','P','3001',11,14,'U')")
        info = ownership.summary(db, [('P', '3001'), ('P', 'nothing')])
        part = info[('P', '3001')]
        assert part['total'] == 23 and [c['name'] for c in part['colours']] == ['Synthetic black', 'Synthetic red']
        assert part['colours'][1]['storages'] == ['Synthetic storage'] and part['needed_count'] == 1 and part['needed_by'][0]['set_no'] == '100-1'
        assert ownership.text(part) == 'You have 23 in 2 colours: Synthetic black 14, Synthetic red 9 (Synthetic storage)'
        assert info[('P', 'nothing')]['total'] == 0 and ownership.text(info[('P', 'nothing')]) == 'Not in your collection'
        import sqlite3
        from pathlib import Path
        with sqlite3.connect(Path(os.environ['BW_DB_PATH']).with_name('bricklink-catalog.db')) as cat:
            cat.execute("INSERT INTO items VALUES('P','3001','Synthetic brick','Synthetic',2025,'synthetic brick')")
        with db:
            db.execute("UPDATE id_match SET status='matched'")
        rows, _ = part_inventory.candidates(db, [dict(item_type='P', item_no='3001', score=0.9)])
        assert rows[0]['owned_summary']['total'] == 23 and rows[0]['owned_summary']['text'].startswith('You have 23')


def test_page_jump_link_and_script(bw, apps):
    client = logged_in(apps('toni'))
    page = BeautifulSoup(client.get('/workbench/what-is-this').data, 'html.parser')
    root = page.select_one('[data-wi-root]')
    assert root['data-url'] == '/workbench/part-to-inventory/detect' and root.select_one('input[type=file][accept="image/*"]')
    # Frame 3f capture: live preview with a guide, one primary that enables the camera, a saved photo as the quiet way in.
    assert root.select_one('[data-wi-viewfinder][hidden] video[playsinline]') and root.select_one('[data-wi-viewfinder] .wi-guide')
    assert root.select_one('button.wi-primary[data-wi-capture]').get_text(strip=True) == 'Enable camera'
    assert root.select_one('label.wi-link').get_text(strip=True) == 'Choose a saved photo'
    assert not root.select_one('input[capture]')  # the live camera replaces the picker's capture hint
    assert page.select_one('#global-jump a.jump-whatis')['href'] == '/workbench/what-is-this'
