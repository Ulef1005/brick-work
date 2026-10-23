"""The BrickLink-space digest of a part list (design 4.1, 8.6): one function, shared by the catalogue builder (which projects
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
