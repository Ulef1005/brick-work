"""Size-aware part search (#41): "1x2", "2x1", "1 x 2", "1*2" and "1×2" find the same parts.

A size key is the dimensions of the first size in a name, sorted ascending and joined by "x"
("Plate 2 x 1" and "Plate 1 x 2" → "1x2"; "Brick 1 x 2 x 3" → "1x2x3"; "Tile 1 1/2 x 2" → "1.5x2").
A query may hold a full size (any order, x, ×, * or a space between two or three bare numbers) or a
partial one ("x2", "2x": any part with that dimension); the other words match as before.
JavaScript mirrors this in static/web/toni/size-search.js (tested against the same table).
"""
import re

NUM = r'(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)'
SEP = r'\s*[x×*]\s*'
IN_NAME = re.compile(rf'(?<![\w./])({NUM}){SEP}({NUM})(?:{SEP}({NUM}))?(?![\w/])', re.I)
FULL = re.compile(rf'(?<![\w./])({NUM}){SEP}({NUM})(?:{SEP}({NUM}))?(?![\w/])', re.I)
BARE = re.compile(rf'^\s*({NUM})\s+({NUM})(?:\s+({NUM}))?\s*$')
# A partial size is one or two digits (or a fraction): "x1435" stays a part number, not a size.
SMALL = r'(?:\d{1,2}(?:\s+\d/\d|/\d|\.\d+)?)'
PARTIAL = re.compile(rf'(?<![\w./])(?:[x×*]\s*({SMALL})|({SMALL})\s*[x×*])(?![\w/])', re.I)


def _number(text):
    text = text.strip()
    if '/' in text:
        whole, _, fraction = text.rpartition(' ')
        a, b = fraction.split('/')
        value = (float(whole) if whole else 0.0) + float(a) / float(b)
    else:
        value = float(text)
    return value


def _fmt(value):
    return str(int(value)) if value == int(value) else format(value, 'g')


def key_of(dims):
    try:
        return 'x'.join(_fmt(v) for v in sorted(_number(d) for d in dims if d))
    except (ValueError, ZeroDivisionError):
        return None


def name_key(name):
    """The size key of a catalogue name, or None."""
    match = IN_NAME.search(name or '')
    return key_of(match.groups()) if match else None


def parse(query):
    """(full key or None, partial dimension or None, the remaining words)."""
    query = (query or '').strip()
    bare = BARE.match(query)
    if bare:
        return key_of(bare.groups()), None, ''
    full = FULL.search(query)
    if full:
        return key_of(full.groups()), None, ' '.join((query[:full.start()] + ' ' + query[full.end():]).split())
    partial = PARTIAL.search(query)
    if partial:
        dim = partial.group(1) or partial.group(2)
        try:
            return None, _fmt(_number(dim)), ' '.join((query[:partial.start()] + ' ' + query[partial.end():]).split())
        except (ValueError, ZeroDivisionError):
            pass
    return None, None, query


def matches(name, full, partial):
    key = name_key(name)
    if full:
        return key == full
    if partial:
        return key is not None and partial in key.split('x')
    return True


def ensure_column(path):
    """Add and fill the indexed size_key column on an older catalogue file, once. False when read-only."""
    import sqlite3
    from contextlib import closing
    try:
        with closing(sqlite3.connect(path)) as db:
            columns = {r[1] for r in db.execute('PRAGMA table_info(items)')}
            if 'size_key' in columns:
                return True
            with db:
                db.create_function('size_key', 1, name_key, deterministic=True)
                db.execute('ALTER TABLE items ADD COLUMN size_key TEXT')
                db.execute('UPDATE items SET size_key=size_key(name)')
                db.execute('CREATE INDEX IF NOT EXISTS items_size ON items(size_key)')
            return True
    except sqlite3.Error:
        return False
