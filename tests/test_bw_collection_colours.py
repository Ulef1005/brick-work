"""The BrickLink colours action of the catalogue admin page (M.8i): moved out of test_bw_collection.py in M.8d; still the 3.3 text."""
from io import BytesIO
import json
import re
from pathlib import Path
import sqlite3

from bs4 import BeautifulSoup
from PIL import Image
import pytest

from brickwork.core import admin, collection, workbench, checker
from brickwork.core.importer.migrate import migrate
from tests.importer.test_importer import legacy
from tests.web_fixtures import app, logged_in
from tests.web_fixtures import apps
from tests.test_bw_admin import reset_shell_metadata_after_test




@pytest.fixture
def bw(legacy, monkeypatch):
    migrate(**legacy)
    monkeypatch.setenv('BW_DB_PATH',str(legacy['out_db']))
    return legacy['out_db']


def token(client):
    client.get('/collection/sets')
    with client.session_transaction() as s: return s['bw_add_csrf']


def test_colours_trigger_uses_source_client_and_app_events(app,bw,monkeypatch):
    from brickwork.core.sources.bricklink import BrickLink
    seen=[]
    def mocked(self,path,params=None,normalize=None,job_id=None):
        seen.append(path)
        with self.db:
            return normalize([dict(color_id=11,color_name='Blue',color_type='Solid',color_code='aBcDeF')])
    monkeypatch.setattr(BrickLink,'call',mocked)
    client=logged_in(app)
    response=client.post('/manage/catalogues',data={'action':'colours','csrf_token':token(client)})
    assert response.status_code==302
    assert seen==['/colors']
    with admin.database(bw) as db:
        assert db.execute('SELECT rgb FROM colors WHERE color_id=11').fetchone()[0]=='ABCDEF'
        row=db.execute("SELECT old_value,new_value FROM events WHERE entity='color:11' AND via='app'").fetchone()
        assert json.loads(row['new_value'])['rgb']=='ABCDEF'
    assert '1 with RGB' in client.get('/manage/catalogues').get_data(as_text=True)
