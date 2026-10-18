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


def test_python_table():
    for name, key in CASES['keys']:
        assert size_search.name_key(name) == key, name
    for query, full, partial, rest in CASES['queries']:
        assert size_search.parse(query) == (full, partial, rest), query
    for query, name, expected in CASES['matches']:
        full, partial, _ = size_search.parse(query)
        assert size_search.matches(name, full, partial) is expected, (query, name)


def test_javascript_agrees():
    script = f"""
const fs=require('fs'),vm=require('vm');const ctx={{}};vm.runInNewContext(fs.readFileSync('static/web/toni/size-search.js','utf8'),ctx);
const S=ctx.BrickSize,c=JSON.parse(fs.readFileSync('tests/fixtures/size_cases.json','utf8'));
const out={{keys:c.keys.map(([n])=>S.nameKey(n)),queries:c.queries.map(([q])=>{{const p=S.parse(q);return [p.full,p.partial,p.rest];}}),
matches:c.matches.map(([q,n])=>S.matches(n,S.parse(q)))}};console.log(JSON.stringify(out));"""
    result = json.loads(subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True, check=True).stdout)
    assert result['keys'] == [k for _, k in CASES['keys']]
    assert result['queries'] == [[f, p, r] for _, f, p, r in CASES['queries']]
    assert result['matches'] == [m for *_, m in CASES['matches']]


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


def test_list_filter():
    rows = [dict(name='Plate 1 x 2', number='3023', colour='Red'), dict(name='Plate 2 x 2', number='3022', colour='Red'),
            dict(name='Brick 1 x 2', number='3004', colour='Blue')]
    assert [r['number'] for r in filter_rows(rows, '2x1')] == ['3004', '3023']
    assert [r['number'] for r in filter_rows(rows, 'plate 2x1 red')] == ['3023']
    assert [r['number'] for r in filter_rows(rows, '3022')] == ['3022']
