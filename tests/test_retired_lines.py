"""Guard (b) of #110 M.8j: retired lines. An in-place part-list switch (design 4.4) does not delete the lines that left the list: it stamps
`retired_at` on them, so Take/Give, allocation and check-session references stay valid. A retired line is not a line of the copy, so every
query on lines must leave it out.

THE RULE. A string literal in code under `brickwork/` (not a docstring) that reads or changes `copy_part`, `copy_figure` or `stock_part` by name
(`FROM`, `JOIN`, `UPDATE`) must, in the same statement, say `retired_at IS NULL`, unless

  * it addresses one row by that row's own primary key (`WHERE ... id=?`: the row was found, with the predicate, before), or
  * its (file, function) is in `ALLOWED` with the reason retired rows belong in that query (the switch itself, undo, merge, migration, a digest).

The three tables are exactly the tables that have a `retired_at` column (checked against the schema, so a new one fails here until it is guarded).
Fetched lines (`fetched_inventory_part`, `fetched_inventory_figure`) have none: a fetched list is immutable and versioned, and a copy reads the
list it names (`fetched_inventory_id`) or the latest (`is_latest`). A query whose table name is built at run time (`f'... {table} ...'`) is not seen;
those write by primary key. An allowed entry that no longer hits fails the test, so the list cannot rot."""
import ast
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
GUARDED = ('copy_part', 'copy_figure', 'stock_part')
USE = re.compile(r'\b(FROM|JOIN|UPDATE)\s+(?:main\.)?(' + '|'.join(GUARDED) + r')\b', re.IGNORECASE)
PREDICATE = re.compile(r'retired_at\s+IS\s+NULL', re.IGNORECASE)
BY_KEY = re.compile(r'\bWHERE\b[^;]*?(?<![\w.])id\s*=\s*\?', re.IGNORECASE | re.DOTALL)

# (file, qualified function) -> why retired rows belong in that query.
ALLOWED = {
    ('brickwork/core/add.py', '_copy_untouched'): "Undo of an Add refuses when a person marked a line, and a mark on a line the copy later switched away from is still their work",
    ('brickwork/core/importer/bricktracker.py', '_line_digest'): "the digest Undo of an import compares: any change to any line, retired or not, means the copy was edited since",
    ('brickwork/core/stock.py', 'part_digest'): 'the digest Undo of an add compares: any change to any line of a loose figure, retired or not, means it was edited since',
    ('brickwork/core/stock.py', 'dependents'): 'a Take or Give that points at a retired line still depends on it',
    ('brickwork/store4/copies.py', '_plan'): 'the switch itself (design 4.4): it matches the wanted lines to every existing row, retired ones too, and re-activates a line that came back',
    ('brickwork/store4/copies.py', 'switch_part_list_in'): 'the switch itself (design 4.4): it retires and re-activates lines',
    ('brickwork/store4/merge.py', '_refuse_double_lines'): "the unique key of a line spans retired rows, so a merge must see them: a retired line of the other item would collide",
    ('brickwork/store4/part_list_read.py', 'retired_counts'): 'the copy page counts the retired lines it keeps (design 4.4), which are the retired rows by definition',
    ('brickwork/store4/part_list_read.py', 'retired_lines'): 'the copy page lists the retired lines it keeps (design 4.4), which are the retired rows by definition',
    ('brickwork/store4/migrate_proof.py', '_Proof.attach'): 'the migration proof reads the file it just wrote, where nothing is retired yet',
}


def docstrings(tree):
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def hits(path):
    """`[(qualified function, line, matched text)]` of queries on guarded tables with no `retired_at IS NULL` in their statement."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    docs = docstrings(tree)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs):
            continue
        for match in USE.finditer(node.value):
            statement = node
            while not isinstance(statement, ast.stmt):
                statement = parents[statement]
            words = ' '.join(s.value for s in ast.walk(statement) if isinstance(s, ast.Constant) and isinstance(s.value, str) and id(s) not in docs)
            if PREDICATE.search(words) or BY_KEY.search(words):
                continue
            names, scope = [], node
            while scope in parents:
                scope = parents[scope]
                if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.append(scope.name)
            found.append(('.'.join(reversed(names)) or '<module>', node.lineno, match.group(0)))
    return found


def scan():
    found = {}
    for path in sorted((ROOT / 'brickwork').rglob('*.py')):
        for function, line, text in hits(path):
            found.setdefault((path.relative_to(ROOT).as_posix(), function), []).append((line, text))
    return found


def test_every_query_on_lines_leaves_retired_rows_out():
    found = scan()
    new = {key: lines for key, lines in found.items() if key not in ALLOWED}
    assert not new, 'a query on copy_part / copy_figure / stock_part without `retired_at IS NULL`:\n' + '\n'.join(f'  {f}:{fn} {lines}' for (f, fn), lines in sorted(new.items()))


def test_every_allowance_still_applies():
    found = scan()
    stale = sorted(key for key in ALLOWED if key not in found)
    assert not stale, f'allowed but no longer a hit (delete the entry): {stale}'
    for (relative, _), reason in ALLOWED.items():
        assert (ROOT / relative).is_file() and reason


def test_the_guarded_tables_are_the_tables_with_retired_rows():
    schema = (ROOT / 'brickwork/store4/brickwork.sql').read_text(encoding='utf-8')
    tables = {}
    for name, body in re.findall(r'CREATE TABLE (\w+)\((.*?)\) STRICT', schema, re.DOTALL):
        tables[name] = body
    with_retired = {name for name, body in tables.items() if re.search(r'^\s*retired_at\b', body, re.MULTILINE) or ' retired_at TEXT' in body}
    assert with_retired == set(GUARDED), with_retired
    assert not [n for n in tables if n.startswith('fetched_inventory') and 'retired_at' in tables[n]]


def test_the_rule_sees_what_it_is_for(tmp_path):
    cases = {
        'select': ("def f(db):\n    return db.execute('SELECT * FROM main.copy_part WHERE copy_id=?')\n", True),
        'join': ("def f(db):\n    return db.execute('SELECT * FROM x JOIN stock_part s ON s.stock_id=x.id')\n", True),
        'update': ("def f(db):\n    db.execute('UPDATE copy_figure SET missing=0 WHERE copy_id=?')\n", True),
        'live': ("def f(db):\n    return db.execute('SELECT * FROM main.copy_part WHERE copy_id=? AND retired_at IS NULL')\n", False),
        'split': ("def f(db, scope):\n    return db.execute('SELECT * FROM copy_part WHERE copy_id=? ' + 'AND retired_at IS NULL')\n", False),
        'by key': ("def f(db):\n    db.execute('UPDATE main.copy_part SET missing=0 WHERE id=?')\n", False),
        'not a key': ("def f(db):\n    db.execute('UPDATE main.copy_part SET missing=0 WHERE copy_id=?')\n", True),
        'other table': ("def f(db):\n    return db.execute('SELECT * FROM fetched_inventory_part')\n", False),
    }
    for name, (code, expected) in cases.items():
        path = tmp_path / 'case.py'
        path.write_text(code)
        assert bool(hits(path)) is expected, name
