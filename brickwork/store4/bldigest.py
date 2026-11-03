"""Two digests of a part list. `inventory_digest` is the catalogue's own form (below); `bl_digest` is the BrickLink-space one.

The BrickLink-space digest of a part list (design 4.1, 8.6): one function, shared by the catalogue builder (which projects
a Rebrickable inventory through the catalogue's links) and the 3.3 migration (which hashes a copy's lines as they were).

A line is a tuple `(kind, key, color, is_spare, quantity)`:
- `kind`: the BrickLink item type, `'P'` for a part line, `'M'` for a figure component line, `'S'` for a set line;
- `key`: the BrickLink item number, a string;
- `color`: the BrickLink colour id as a string, or None when the line has no colour (figure and set lines; "no colour" parts);
- `is_spare`: 0 or 1 (spares are part of the comparison);
- `quantity`: a positive integer.
Lines naming the same `(kind, key, color, is_spare)` are summed, then the sorted tuples are hashed. Equal lists give equal
digests whatever Rebrickable or 3.3 parts they came from. Figure components are compared as their own list (their lines are
`'P'` lines of the figure)."""
import hashlib
import json


def bl_digest(lines):
    """sha256 hex over the summed, sorted BrickLink-space lines (see the module docstring for the line shape)."""
    total = {}
    for kind, key, color, is_spare, quantity in lines:
        k = (str(kind), str(key), None if color is None else str(color), int(is_spare))
        total[k] = total.get(k, 0) + int(quantity)
    ordered = sorted(total.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] is not None, kv[0][2] or '', kv[0][3]))
    return hashlib.sha256(json.dumps([[*k, q] for k, q in ordered], separators=(',', ':')).encode()).hexdigest()


def inventory_digest(part_lines, figure_lines=(), set_lines=()):
    """sha256 hex of a part list in the store's own ids: the form the catalogue builder stamps on every inventory version and
    the fetched-list writer stamps on every fetched one, so equal lists get equal digests wherever they come from.

    `part_lines` are `(item, colour, is_spare, quantity)`, `figure_lines` and `set_lines` are `(item, quantity)`. The lines
    must already be unique per key (the callers sum first); this only sorts and hashes."""
    lines = sorted([('p', *l) for l in part_lines] + [('f', i, 0, 0, q) for i, q in figure_lines]
                   + [('s', i, 0, 0, q) for i, q in set_lines])
    return hashlib.sha256(repr(lines).encode()).hexdigest()
