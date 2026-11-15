"""Category groups for part lists and picking orders on the collection store.

Categories come from `item.category_name`. The `grouped` mode maps those names
into the fixed catalogue order in `GROUPS`; unmapped or absent names go to Other.
The `bricklink` mode keeps each category name as a group. The `none` mode disables
grouping. Other is always last and is only present when a row lands in it.

`group_of` maps one category to its group; `order` orders only the supplied groups.
`mode` reads the setting; `categories` and `annotate` put the category and the group on rows; `sections` folds rows into the ordered sections the
order, print and pull-list pages draw. None of them writes to the store.
"""
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


def group_of(category_name, mode=DEFAULT):
    """Return the mapped group, the BrickLink category (or Other), or None."""
    if mode == 'none':
        return None
    if mode == 'bricklink':
        return category_name or 'Other'
    return _CATEGORY_GROUP.get(category_name, 'Other')


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
    for row in rows:
        if is_part(row):
            row['category'] = found.get(row['item_id'])
            row['group'] = group_of(row['category'], grouping)
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
