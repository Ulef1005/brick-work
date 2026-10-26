"""#41 size-aware part search: one table for Python and JavaScript, catalogue and list searches."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess

from brickwork.core import add, size_search
from brickwork.core.connect import connect
from brickwork.core.listing import filter_rows
from tests.test_bw_api_m1 import app  # noqa: F401
from tests.test_bw_api_m2 import populated  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / 'tests/fixtures/size_cases.json').read_text())


def test_catalogue_search_backfills_and_filters(populated):
    path = Path(os.environ['BW_DB_PATH']).with_name('bricklink-catalog.db')
    with closing(sqlite3.connect(path)) as cat, cat:
        cat.executemany("INSERT INTO items(item_type,item_no,name,normalized_name,category,year) VALUES('P',?,?,lower(?),'1',2020)",
                        [('3023', 'Plate 1 x 2', 'Plate 1 x 2'), ('3021', 'Plate 2 x 3', 'Plate 2 x 3'), ('3004', 'Brick 1 x 2', 'Brick 1 x 2'),
                         ('x1435', 'Gear Wheel Special', 'Gear Wheel Special')])
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        found = lambda q: sorted(r['item_no'] for r in add.search(db, 'P', q)['items'])
        assert found('2x1') == ['3004', '3023'] and found('1*2') == ['3004', '3023']
        assert found('plate 2 x 1') == ['3023']
        assert found('x3') == ['3021'] and found('x1435') == ['x1435']
    with closing(sqlite3.connect(path)) as cat:
        assert 'size_key' in {r[1] for r in cat.execute('PRAGMA table_info(items)')}
        assert cat.execute("SELECT size_key FROM items WHERE item_no='3021'").fetchone()[0] == '2x3'

