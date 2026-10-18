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


def test_picture_projection_has_constant_queries_and_no_filesystem_calls(bw):
    picture = bw.parent / 'data/images/cost.png'
    picture.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (4,3), 'white').save(picture)
    with closing(connect(bw)) as db, db:
        db.execute("UPDATE settings SET value=? WHERE key='source_priority'", (json.dumps({'pictures': {'P': ['bricklink', 'rebrickable']}}),))
        rows = []
        for i in range(400):
            number = f'cost-{i}'
            db.execute("INSERT INTO items(item_type,item_no,name) VALUES('P',?,?)", (number, number))
            db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES(?,'P',?,11,1,'U')", (number, number))
            for source, color, stamp in [('rebrickable',11,'2026-10-14'), ('bricklink',None,'2026-10-12'), ('bricklink',11,'2026-10-13'), ('bricklink',0,'2026-10-14')]:
                db.execute("INSERT INTO item_images(item_type,item_no,color_id,source,kind,local_path,fetched_at) VALUES('P',?,?,?,'render','data/images/cost.png',?)", (number,color,source,stamp))
            observation = db.execute("INSERT INTO price_observations(item_type,item_no,color_id,condition,guide,source,price,observed_at) VALUES('P',?,11,'U','sold','bricklink','2','2026-10-14')", (number,)).lastrowid
            db.execute("INSERT INTO price_current(item_type,item_no,color_id,condition,guide,observation_id) VALUES('P',?,11,'U','sold',?)", (number,observation))
            rows.append(dict(item_type='P', item_no=number, color_id=11))
        counts = []
        with patch.object(Path, 'resolve') as resolve, patch.object(Path, 'is_file') as is_file:
            for batch in (rows[:1], rows):
                statements = []
                db.set_trace_callback(statements.append)
                try:
                    decorated = add.decorate_many(db, batch)
                finally:
                    db.set_trace_callback(None)
                counts.append(len(statements))
                for row in decorated:
                    image = db.execute('SELECT source,color_id,fetched_at FROM item_images WHERE id=?', (row['image'],)).fetchone()
                    assert tuple(image) == ('bricklink',11,'2026-10-13')
            collection.listing(db, 'P')
            planning.priced_items(db, 'P')
            resolve.assert_not_called()
            is_file.assert_not_called()
        assert counts == [4,4]
        # Generic fallback competes by priority and recency, just as decorate does.
        for color in (None, 0, 11, 999):
            row = dict(item_type='P',item_no='cost-0',color_id=color)
            assert add.decorate_many(db,[row])[0]['image'] == add.decorate(db,row)['image']


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


def test_wish_payload_labels_wanted_without_missing(bw):
    with closing(connect(bw)) as db:
        rows = collection.listing(db, 'S', wishes=True)
        data = json.loads(payload(rows))
        for row, packed in zip(rows, data['rows']):
            assert packed[str(data['fields'].index('defects'))] == f"{row['quantity']} wanted"
            assert str(data['fields'].index('missing')) not in packed
    data = json.loads(payload([dict(item_type='P',item_no='bl-part',entity='wish',id=1,need=3)]))
    assert data['rows'][0][str(data['fields'].index('defects'))] == '3 wanted'
