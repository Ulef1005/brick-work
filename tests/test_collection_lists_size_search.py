"""#41 size-aware part search on the collection lists: one table for Python and JavaScript, and the list filter (M.8b).

Add's catalogue search by size is in `test_bw_size_search_41.py` (M.8c); the 3.3 backfill of the size column is gone, the 4.0 builder fills it."""
import json
from pathlib import Path
import subprocess

from brickwork.core import size_search
from brickwork.core.listing import filter_rows

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


def test_list_filter():
    rows = [dict(name='Plate 1 x 2', number='3023', colour='Red'), dict(name='Plate 2 x 2', number='3022', colour='Red'),
            dict(name='Brick 1 x 2', number='3004', colour='Blue')]
    assert [r['number'] for r in filter_rows(rows, '2x1')] == ['3004', '3023']
    assert [r['number'] for r in filter_rows(rows, 'plate 2x1 red')] == ['3023']
    assert [r['number'] for r in filter_rows(rows, '3022')] == ['3022']
