"""Display groups for part lists. Categories always come from item.category_name."""
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
