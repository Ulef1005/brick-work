"""Size-aware part search (#41): "1x2", "2x1", "1 x 2", "1*2" and "1×2" find the same parts.

A size key is the dimensions of the first size in a name, sorted ascending and joined by "x"
("Plate 2 x 1" and "Plate 1 x 2" → "1x2"; "Brick 1 x 2 x 3" → "1x2x3"; "Tile 1 1/2 x 2" → "1.5x2").
A query may hold a full size (any order, x, ×, * or a space between two or three bare numbers) or a
partial one ("x2", "2x": any part with that dimension); the other words match as before.
JavaScript mirrors this in static/web/toni/size-search.js (tested against the same table).
"""
import re

from ..store4.sizekey import IN_NAME, NUM, SEP, _fmt, _number, key_of, name_key  # noqa: F401 — moved to store4 (M.8a)

FULL = re.compile(rf'(?<![\w./])({NUM}){SEP}({NUM})(?:{SEP}({NUM}))?(?![\w/])', re.I)
BARE = re.compile(rf'^\s*({NUM})\s+({NUM})(?:\s+({NUM}))?\s*$')
# A partial size is one or two digits (or a fraction): "x1435" stays a part number, not a size.
SMALL = r'(?:\d{1,2}(?:\s+\d/\d|/\d|\.\d+)?)'
PARTIAL = re.compile(rf'(?<![\w./])(?:[x×*]\s*({SMALL})|({SMALL})\s*[x×*])(?![\w/])', re.I)


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
