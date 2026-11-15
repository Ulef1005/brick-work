"""Category groups for part lists and picking orders on the collection store.

Categories come from `item.category_name`. The `grouped` mode maps those names
into the fixed catalogue order in `GROUPS`; unmapped or absent names go to Other.
The `bricklink` mode keeps each category name as a group. The `none` mode disables
grouping. Other is always last and is only present when a row lands in it.

`group_of` maps one category to its group; `order` orders only the supplied groups.
`mode` and `overrides` read the settings; `categories` and `annotate` put the category and the group on rows; `sections` folds rows into the ordered sections the
order, print and pull-list pages draw. None of them writes to the store.

Your own changes to the table are the setting `part_group_overrides`, a JSON object `{category name: group name}` that holds only the
differences from `GROUPS`. They apply in the `grouped` mode only; `valid_overrides` is the one check every writer uses.
"""
import json

MODES = ('grouped', 'bricklink', 'none')
DEFAULT = 'grouped'
GROUPS = {
    'Bricks': ('Bricks', 'Bricks Special', 'Bricks Round and Cones', 'Baseplates'),
    'Slopes and curves': ('Bricks Sloped', 'Bricks Curved', 'Bricks Wedged'),
    'Plates': ('Plates', 'Plates Special', 'Plates Round Curved and Dishes', 'Plates Wedged'),
    'Tiles': ('Tiles', 'Tiles Round and Curved', 'Tiles Special'),
    'Technic': ('Technic Axles', 'Technic Beams', 'Technic Beams Special', 'Technic Bricks', 'Technic Bushes', 'Technic Connectors', 'Technic Gears', 'Technic Pins', 'Technic Special', 'Pneumatics'),
    'Hinges, bars and connectors': ('Hinges, Arms and Turntables', 'Bars, Ladders and Fences', 'Tubes and Hoses', 'String, Bands and Reels'),
    'Windows, doors and panels': ('Windows and Doors', 'Panels', 'Windscreens and Fuselage'),
    'Wheels and vehicles': ('Wheels and Tyres', 'Transportation - Land', 'Transportation - Sea and Air'),
    'Minifigure parts': ('Minifig Accessories', 'Minifig Heads', 'Minifig Headwear', 'Minifig Headwear Accessories', 'Minifig Neckwear', 'Minifig Shields, Weapons, & Tools', 'Minifig Upper Body', 'Large Buildable Figures', 'Tools'),
    'Nature and creatures': ('Plants & Trees', 'Animal / Creature Accessories', 'Animal / Creature Body Parts', 'Animals / Creatures'),
    'Decoration and extras': ('Containers', 'Flags, Banners and Signs', 'Energy Effects', 'Projectiles / Launchers', 'Stickers', 'Electronics'),
    'Other': ('Other',),
}
_CATEGORY_GROUP = {category: group for group, categories in GROUPS.items() for category in categories}


OVERRIDES_KEY = 'part_group_overrides'
MAX_OVERRIDES = 200
MAX_CATEGORY = 100


def default_group(category_name):
    """The group the built-in table puts a category in (Other for one it does not know)."""
    return _CATEGORY_GROUP.get(category_name, 'Other')


def group_of(category_name, mode=DEFAULT, overrides=None):
    """Return the mapped group, the BrickLink category (or Other), or None. `overrides` (`overrides(db)`) move categories between groups in
    the `grouped` mode only."""
    if mode == 'none':
        return None
    if mode == 'bricklink':
        return category_name or 'Other'
    return (overrides or {}).get(category_name) or default_group(category_name)


def valid_overrides(value):
    """The overrides to store for `value` (None or `{}` clears them): `{category: group}` with every entry that equals the default table
    dropped, sorted by category. Raises ValueError with a message for the person on anything that does not fit."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError('part_group_overrides is {category name: group name}')
    if len(value) > MAX_OVERRIDES:
        raise ValueError(f'part_group_overrides holds at most {MAX_OVERRIDES} categories')
    found = {}
    for category, group in value.items():
        if not isinstance(category, str) or not category.strip():
            raise ValueError('Each category name must be a non-empty string')
        if len(category.strip()) > MAX_CATEGORY:
            raise ValueError(f'A category name is at most {MAX_CATEGORY} characters')
        if not isinstance(group, str) or group not in GROUPS:
            raise ValueError('Choose one of these groups for ' + category.strip() + ': ' + ', '.join(GROUPS))
        if group != default_group(category.strip()):
            found[category.strip()] = group
    return dict(sorted(found.items()))


def parse_overrides(text):
    """`{category: group}` from the stored text; a value that does not read cleanly is left out entry by entry."""
    try:
        stored = json.loads(text) if text else {}
    except ValueError:
        return {}
    if not isinstance(stored, dict):
        return {}
    return {c: g for c, g in stored.items() if isinstance(c, str) and c.strip() and isinstance(g, str) and g in GROUPS}


def overrides(db):
    """The saved `part_group_overrides` as `{category: group}`."""
    row = db.execute('SELECT value FROM main.setting WHERE key=?', (OVERRIDES_KEY,)).fetchone()
    return parse_overrides(row[0] if row else None)


def encode_overrides(value):
    """The stored text of valid overrides: canonical JSON, or None for no overrides (the setting is then absent)."""
    value = valid_overrides(value)
    return json.dumps(value, sort_keys=True) if value else None


def held_counts(db):
    """`{category name: parts}`: how many different parts of that category the collection holds (set copies and loose stock) and, with a
    value of 0, every category the catalogue and the table name. A part with no category is not counted. Read-only."""
    ids = [r[0] for r in db.execute("""SELECT item_id FROM main.copy_part WHERE retired_at IS NULL AND is_spare=0
                                       UNION SELECT item_id FROM main.stock WHERE kind='part' AND archived_at IS NULL""")]
    counts = {category: 0 for categories in GROUPS.values() for category in categories}
    from . import collection
    if collection.has_catalogue(db):
        for r in db.execute('SELECT name FROM catalogue.part_category WHERE retired_at IS NULL'):
            if (r[0] or '').strip():
                counts.setdefault(r[0].strip(), 0)
    for category in categories(db, ids).values():
        if category:
            counts[category] = counts.get(category, 0) + 1
    for category in overrides(db):
        counts.setdefault(category, 0)
    return counts


def order(groups, mode=DEFAULT):
    """Order only the groups present; an unused Other section is never inserted."""
    if mode == 'none':
        return []
    return sorted(set(groups), key=(lambda g: (g == 'Other', g.casefold())) if mode == 'bricklink'
                  else lambda g: list(GROUPS).index(g))


def mode(db):
    """The saved `part_list_grouping` (a value that is not one of `MODES` reads as the default)."""
    row = db.execute("SELECT value FROM main.setting WHERE key='part_list_grouping'").fetchone()
    return row[0] if row and row[0] in MODES else DEFAULT


def editor(db):
    """`[dict(name, rows=[dict(category, count, group, default)])]` for the Settings editor: every category under the group the built-in table
    puts it in (the table's order; a category the table does not know, with the ones you moved, last under Other), `group` being where it
    sits now and `count` how many different parts of it the collection holds."""
    counts, moved = held_counts(db), overrides(db)
    listed = {name: [c for c in names if c in counts] for name, names in GROUPS.items()}
    extra = sorted((c for c in counts if c not in _CATEGORY_GROUP), key=str.casefold)
    listed['Other'] += extra
    return [dict(name=name, rows=[dict(category=c, count=counts[c], group=moved.get(c, name), default=name) for c in names])
            for name, names in listed.items()]


def categories(db, item_ids):
    """`{item id: category name or None}`: the same name the set parts list groups by (the collection's, else the catalogue's)."""
    from . import collection
    ids = list(dict.fromkeys(item_ids))
    names = collection._names(db, ids) if ids else {}
    return {i: ((names.get(i) or {}).get('category_name') or '').strip() or None for i in ids}


def annotate(db, rows, grouping, *, is_part=lambda row: True):
    """Put `category` and `group` on every row (in place). A row that is not a part (`is_part` false: a whole figure, a set) has `group` None and stays
    outside the sections; with `none` every `group` is None."""
    if grouping == 'none':
        for row in rows:
            row['group'] = None
        return rows
    found = categories(db, [row['item_id'] for row in rows if is_part(row)])
    moved = overrides(db)
    for row in rows:
        if is_part(row):
            row['category'] = found.get(row['item_id'])
            row['group'] = group_of(row['category'], grouping, moved)
        else:
            row['group'] = None
    return rows


def sections(rows, grouping, *, pieces=lambda row: row.get('quantity') or 0):
    """`(outside, sections)`: the rows with no `group` (in their order) and `[dict(name, rows, lines, pieces)]` in `order` for the rest.

    With `none` nothing is grouped: `sections` is empty and `outside` is every row, so a template draws the plain list."""
    outside, grouped = [], {}
    for row in rows:
        if grouping == 'none' or row.get('group') is None:
            outside.append(row)
        else:
            grouped.setdefault(row['group'], []).append(row)
    return outside, [dict(name=name, rows=grouped[name], lines=len(grouped[name]), pieces=sum(pieces(r) for r in grouped[name]))
                     for name in order(grouped, grouping)]
