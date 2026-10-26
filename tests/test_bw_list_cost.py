"""List cost and refresh regressions against migrated Brick Work evidence."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

from PIL import Image

from brickwork.core import add, collection, names, planning
from brickwork.core.connect import connect
from brickwork.core.list_records import payload
from brickwork.core.sources.base import audit_origin
from tests.test_bw_collection import bw, legacy, reset_shell_metadata_after_test
from tests.web_fixtures import app, logged_in
from tests.web_fixtures import apps


def test_deleted_picture_stays_selected_and_image_route_returns_404(app, bw):
    with closing(connect(bw)) as db, db:
        identifier = db.execute("INSERT INTO item_images(item_type,item_no,source,kind,local_path,fetched_at) VALUES('P','bl-part','rebrickable','render','data/images/deleted.png','2099-01-01')").lastrowid
        assert add.decorate_many(db,[dict(item_type='P',item_no='bl-part',color_id=11)])[0]['image'] == identifier
    client = logged_in(app)
    assert client.get('/collection/P').status_code == 200
    assert client.get(f'/manage/images/{identifier}').status_code == 404


def test_name_refresh_only_writes_changed_values(bw):
    catalogue = bw.with_name('name-cost-catalogue.db')
    with sqlite3.connect(catalogue) as cat:
        cat.execute('CREATE TABLE items(item_type TEXT,item_no TEXT,name TEXT)')
        cat.execute("INSERT INTO items VALUES('P','bl-part','Changed catalogue name')")
        cat.executemany("INSERT INTO items VALUES('P',?,?)", [(f'name-{i}',f'Name {i}') for i in range(300)])
    with closing(connect(bw)) as db:
        with db:
            db.executemany("INSERT INTO items(item_type,item_no,name) VALUES('P',?,?)", [(f'name-{i}',f'Name {i}') for i in range(300)])
            db.executemany("INSERT INTO item_properties(item_type,item_no,key,source,value) VALUES('P',?,'name','bricklink',?)", [(f'name-{i}',f'Name {i}') for i in range(300)])
        changed_statements = []
        db.set_trace_callback(changed_statements.append)
        with db, audit_origin('app'):
            assert names.refresh(db, catalogue) == 1
        db.set_trace_callback(None)
        assert len([s for s in changed_statements if s.lstrip().upper().startswith('SELECT')]) == 4
        event = db.execute("SELECT * FROM events WHERE entity='item-name:P:bl-part' ORDER BY id DESC LIMIT 1").fetchone()
        assert event['via'] == 'app'
        assert json.loads(event['new_value']) == {'name':'Changed catalogue name','source':'bricklink'}
        before = [tuple(r) for r in db.execute('SELECT * FROM items')], [tuple(r) for r in db.execute('SELECT * FROM item_properties')], db.execute('SELECT count(*) FROM events').fetchone()[0]
        statements = []
        db.set_trace_callback(statements.append)
        try:
            with db, audit_origin('app'):
                assert names.refresh(db, catalogue) == 0
        finally:
            db.set_trace_callback(None)
        assert not any(s.lstrip().upper().startswith(('INSERT','UPDATE','DELETE')) for s in statements)
        assert len([s for s in statements if s.lstrip().upper().startswith('SELECT')]) == 4
        assert before == ([tuple(r) for r in db.execute('SELECT * FROM items')], [tuple(r) for r in db.execute('SELECT * FROM item_properties')], db.execute('SELECT count(*) FROM events').fetchone()[0])
        with sqlite3.connect(catalogue) as cat:
            cat.execute("UPDATE items SET name='Another name' WHERE item_no='bl-part'")
        try:
            with db, audit_origin('app'):
                assert names.refresh(db, catalogue) == 1
                raise ValueError('rollback')
        except ValueError:
            pass
        assert db.execute("SELECT name FROM items WHERE item_type='P' AND item_no='bl-part'").fetchone()[0] == 'Changed catalogue name'
        assert db.execute('SELECT count(*) FROM events').fetchone()[0] == before[2]

