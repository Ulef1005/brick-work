"""Category groups for part lists and picking orders on the collection store.

Categories come from `item.category_name`. The `grouped` mode maps those names
into the fixed catalogue order in `GROUPS`; unmapped or absent names go to Other.
The `bricklink` mode keeps each category name as a group. The `none` mode disables
grouping. Other is always last and is only present when a row lands in it.

`group_of` maps one category to its group; `order` orders only the supplied groups.
These helpers do not read or change the store.
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
