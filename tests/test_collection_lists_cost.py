"""List cost regressions on the 4.0 store (M.8b): picture projection costs a constant number of queries and no filesystem calls; the wish
payload labels what is wanted. The name refresh test (`names.refresh`) stays with M.8f, the image route's 404 with M.8f."""
import json
from pathlib import Path
from unittest.mock import patch

from brickwork.core import collection
from brickwork.core.list_records import payload
from brickwork.store4 import fetched
from tests.app4 import STAMP, world, coll, pair, read, app4, client  # noqa: F401  (fixtures)


def parts_with_pictures(coll, count):
    """`count` local BrickLink-born parts held in red, each with four pictures and one price; returns the rows a decorate takes."""
    red, white = coll.colour('4'), coll.colour('15')
    db = coll.db
    rows = []
    for i in range(count):
        item = fetched.create_local_item(db, kind='part', born_provider='bricklink', born_namespace='P', born_key=f'cost-{i}', name=f'cost-{i}')
        db.execute("INSERT INTO stock(id,kind,item_id,color_id,quantity,condition,created_at,updated_at) VALUES(?,'part',?,?,1,'used',?,?)",
                   (f'cost-{i}', item, red, STAMP, STAMP))
        db.executemany("INSERT INTO picture(item_id,color_id,source,kind,local_path,fetched_at) VALUES(?,?,?,'render','data/images/cost.png',?)",
                       [(item, red, 'rebrickable', '2026-10-14'), (item, None, 'bricklink', '2026-10-12'),
                        (item, red, 'bricklink', '2026-10-13'), (item, white, 'bricklink', '2026-10-14')])
        rows.append(dict(item_id=item, color_id=red))
    db.commit()
    return rows


def test_picture_projection_has_constant_queries_and_no_filesystem_calls(coll, read):
    coll.setting('source_priority', json.dumps({'pictures': {'part': ['bricklink', 'rebrickable']}}))
    rows = parts_with_pictures(coll, 120)
    with read() as db:
        counts = []
        with patch.object(Path, 'resolve') as resolve, patch.object(Path, 'is_file') as is_file:
            for batch in (rows[:1], rows):
                statements = []
                db.set_trace_callback(statements.append)
                try:
                    decorated = collection.decorate(db, batch)
                finally:
                    db.set_trace_callback(None)
                counts.append(len(statements))
                for row in decorated:
                    image = db.execute('SELECT source,color_id,fetched_at FROM picture WHERE id=?', (row['image'],)).fetchone()
                    # BrickLink outranks Rebrickable; of its pictures the one of the row's colour, then the newest (colour-less is the fallback).
                    assert (image['source'], image['color_id'], image['fetched_at']) == ('bricklink', rows[0]['color_id'], '2026-10-13')
            assert len(collection.listing(db, 'P')) == 120
            resolve.assert_not_called()
            is_file.assert_not_called()
        assert counts[0] == counts[1]
        # A batch picks what a row on its own picks, whatever colour the row has (the colour-less fallback included).
        for colour in (None, coll.colour('15'), coll.colour('4'), 999):
            row = dict(item_id=rows[0]['item_id'], color_id=colour)
            assert collection.decorate(db, [row] + rows[1:3])[0]['image'] == collection.decorate(db, [row])[0]['image']


def test_a_picture_whose_file_is_gone_stays_selected(coll, read, client):
    """The newest picture row wins even when its file was deleted; the list still renders (the image route's 404 is M.8f's)."""
    part = coll.item('parts', '3001')
    red = coll.colour('4')
    coll.add_stock('part', part, colour=red, quantity=1)
    coll.sql("INSERT INTO picture(item_id,color_id,source,kind,local_path,fetched_at) VALUES(?,?,'rebrickable','render','data/images/deleted.png','2099-01-01')", (part, red))
    identifier = coll.sql('SELECT id FROM picture WHERE local_path=?', ('data/images/deleted.png',)).fetchone()[0]
    with read() as db:
        assert collection.decorate(db, [dict(item_id=part, color_id=red)])[0]['image'] == identifier
    assert client.get('/collection/P').status_code == 200


def test_wish_payload_labels_wanted_without_missing(world, read):
    with read() as db:
        rows = collection.listing(db, 'S', wishes=True)
        assert rows
        data = json.loads(payload(rows))
        for row, packed in zip(rows, data['rows']):
            assert packed[str(data['fields'].index('defects'))] == f"{row['quantity']} wanted"
            assert str(data['fields'].index('missing')) not in packed
    data = json.loads(payload([dict(item_type='P', item_no='3001', entity='wish', id='w1', need=3)]))
    assert data['rows'][0][str(data['fields'].index('defects'))] == '3 wanted'
