"""Guard (a) of #110 M.8j: no typed identity. After M.8 an item is its `item_id`; a BrickLink `(type letter, number)` pair is the provider's key and
lives only at the borders.

THE RULE. A file under `brickwork/` uses `(item_type, item_no)` as an identity when, in code (not in a docstring or a comment), it:

  1. names both words in one SQL (or any other string) literal: a statement that selects, joins, groups, inserts or compares on the pair;
  2. builds a key from the pair: a tuple, list, set, subscript key or dict-key expression whose elements mention both `item_type` and `item_no`
     (as a name, an attribute, a string subscript `r['item_no']`, a `.get('item_no')`, a keyword); or
  3. defines a function that takes both as parameters (it takes a typed identity).

A display record is not an identity: a dict that carries `item_type` (the screen letter) and `item_no` (the number text) as fields next to `item_id`
and a single field read (`r['item_type'] == 'S'`) are allowed; the identity of such a row is its `item_id`.

WHAT IS LEFT OUT, BY PATH (`EXCLUDED`, each with its reason): store4's provider-key code, the API v1 modules (they answer 410 and are M.11's) and the
BrickLink XML/CSV wire formats, where `item_type`/`item_no` are the provider's own words. EVERY OTHER HIT is in `ALLOWED` by (file, function) with the
reason it is not an identity. A new hit fails the test; an allowed entry that no longer hits fails it too, so the list cannot rot."""
import ast
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORDS = ('item_type', 'item_no')
WORD = re.compile(r'\b(item_type|item_no)\b')

EXCLUDED = {
    'brickwork/store4/mint.py': "store4's provider-key code: the mint reads 3.3's BrickLink pairs and gives each an item (its input, the provider's key)",
    'brickwork/store4/migrate.py': "store4's provider-key code: the 3.3 -> 4.0 migration reads the 3.3 file, whose identity was the pair",
    'brickwork/store4/migrate_proof.py': "store4's provider-key code: the migration's proof reads the 3.3 file",
    'brickwork/store4/bricklink_list.py': "store4's provider-key code: BrickLink's item lists are keyed by (type, number); they become link evidence",
    'brickwork/store4/reconcile.py': "store4's provider-key code: reconcile compares BrickLink's list with the catalogue's links",
    'brickwork/store4/catalogue.sql': "store4's provider-key code: the BrickLink catalogue table `bricklink_item(item_type, item_no)` is the provider's",
    'brickwork/store4/layers.py': "store4's provider-key code: the shipped mapping layers name BrickLink keys",
}
EXCLUDED_DIRS = {
    'brickwork/api/': 'API v1: it answers 410 and is rewritten as v2 in M.11',
}
EXCLUDED_PATTERNS = {
    r'brickwork/core/api_[a-z_]+\.py': 'API v1 core modules: they serve v1, which answers 410; M.11 rewrites them',
}
WIRE = {
    'brickwork/core/list_exports.py': 'the printable list CSV: its columns are named in BrickLink words',
    'brickwork/core/order_exports.py': 'the order CSV export: its columns are named in BrickLink words',
    'brickwork/core/orders.py': "BrickLink order e-mail and XML: ITEMTYPE / ITEMID are the provider's words; a line is placed by `resolve_inverse` into an item id",
    'brickwork/core/wishlists.py': "the BrickLink wanted-list XML and the Rebrickable CSV: the provider's words; the export names rows through `items.bricklink_key`",
    'brickwork/core/sources/brickognize.py': "Brickognize answers in (type, id) words: the border where a prediction becomes an item id (core/identify.py)",
}
EXCLUDED.update(WIRE)

# (file, qualified function) -> why it is a display / sorting / border use and not an identity.
ALLOWED = {
    ('brickwork/core/list_records.py', 'payload'): 'positional display record of the client lists: the letter and the number text are two columns of a row whose identity is its item_id / ids',
    ('brickwork/core/listing.py', '<module>'): "the lists' filter vocabulary (a set of query-parameter names, `item_no` and `item_type` among them): names, not keys",
    ('brickwork/core/workbench.py', 'booklet_item'): "reads the BrickLink catalogue table `catalogue.bricklink_item`, the provider's own (type, number) list, for a booklet that has no item yet",
    ('brickwork/web/admin_ops.py', 'import_item'): 'the CLI border: `brickwork import <type letter> <number>` takes what a person types and resolves it with `items.find` on its first line',
}


def excluded(relative):
    return (relative in EXCLUDED or any(relative.startswith(d) for d in EXCLUDED_DIRS) or any(re.fullmatch(p, relative) for p in EXCLUDED_PATTERNS))


def docstrings(tree):
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def mentions(node):
    """Which of the two words an expression mentions as code (a name, an attribute, a keyword, a string subscript or `.get('...')` key)."""
    found = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in WORDS:
            found.add(sub.id)
        elif isinstance(sub, ast.Attribute) and sub.attr in WORDS:
            found.add(sub.attr)
        elif isinstance(sub, ast.keyword) and sub.arg in WORDS:
            found.add(sub.arg)
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.value in WORDS:
            found.add(sub.value)
    return found


def hits(path):
    """`[(qualified function, line, rule)]` for one Python file."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    docs = docstrings(tree)
    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    def qualname(node):
        names = []
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.append(node.name)
        return '.'.join(reversed(names)) or '<module>'
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            if set(WORD.findall(node.value)) >= set(WORDS):
                found.append((qualname(node), node.lineno, 'one string names both words'))
        elif isinstance(node, (ast.Tuple, ast.List, ast.Set)) and mentions(node) >= set(WORDS):
            if not any(mentions(element) >= set(WORDS) for element in node.elts):    # the innermost pair-building expression only
                found.append((qualname(node), node.lineno, 'a key built from both'))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = {a.arg for a in node.args.args + node.args.kwonlyargs}
            if names >= set(WORDS):
                outer = qualname(node)
                found.append((node.name if outer == '<module>' else outer + '.' + node.name, node.lineno, 'takes both as parameters'))
    return found


def scan():
    found = {}
    for path in sorted((ROOT / 'brickwork').rglob('*')):
        relative = path.relative_to(ROOT).as_posix()
        if not path.is_file() or '__pycache__' in relative or excluded(relative):
            continue
        if path.suffix == '.py':
            for function, line, rule in hits(path):
                found.setdefault((relative, function), []).append((line, rule))
        elif path.suffix in ('.sql', '.js', '.html', '.json'):
            text = [i + 1 for i, l in enumerate(path.read_text(encoding='utf-8').splitlines()) if set(WORD.findall(l)) >= set(WORDS) and not l.lstrip().startswith(('--', '//'))]
            if text:
                found.setdefault((relative, '<file>'), []).extend((n, 'one line names both words') for n in text)
    return found


def test_no_file_uses_a_typed_identity():
    found = scan()
    new = {key: lines for key, lines in found.items() if key not in ALLOWED}
    assert not new, 'typed identity (item_type, item_no) outside the allowlist:\n' + '\n'.join(f'  {f}:{fn} {lines}' for (f, fn), lines in sorted(new.items()))


def test_every_exclusion_and_allowance_still_applies():
    for relative in EXCLUDED:
        assert (ROOT / relative).is_file(), f'{relative} is excluded but does not exist'
    for directory in EXCLUDED_DIRS:
        assert (ROOT / directory).is_dir(), directory
    found = scan()
    stale = sorted(key for key in ALLOWED if key not in found)
    assert not stale, f'allowed but no longer a hit (delete the entry): {stale}'
    assert all(ALLOWED.values()) and all(EXCLUDED.values())


def test_the_rule_sees_what_it_is_for(tmp_path):
    """The three shapes of the rule, and the display record it leaves alone."""
    shapes = {
        'sql': "def f(db):\n    return db.execute('SELECT * FROM x WHERE item_type=? AND item_no=?')\n",
        'key': "def f(r):\n    return {(r['item_type'], r['item_no']): r}\n",
        'params': "def f(db, item_type, item_no):\n    return 1\n",
    }
    for name, code in shapes.items():
        path = tmp_path / f'{name}.py'
        path.write_text(code)
        assert hits(path), name
    display = tmp_path / 'display.py'
    display.write_text("def f(r):\n    row = dict(item_id=r['item_id'], item_type='S', item_no='1000-1')\n    return row if r['item_type'] == 'S' else None\n")
    assert hits(display) == []
