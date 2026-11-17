"""Short body-part names for the missing parts on a figure line (#34, design frame 12g: "Torso · Legs").

The category of a part is its catalogue part category name (`catalogue.part_category`, from the Rebrickable dump, or the collection's own
`item.category_name`). The table below maps those names, and the BrickLink names for the same categories, to one of eight short names.
Rebrickable's Upper Body and Lower Body hold more than torsos and legs, so the part name settles Hips, Hair and arms and hands.
A part whose category matches none gets the first words of its own name.
"""

SHORT_NAMES = ('Head', 'Torso', 'Legs', 'Hips', 'Headgear', 'Hair', 'Accessory', 'Other')

# Category name (case-folded) to short name. Rebrickable names first, then the BrickLink names of the same categories.
CATEGORY_SHORT = {
    'minifig heads': 'Head', 'minifigure, head': 'Head',
    'minifig upper body': 'Torso', 'minifigure, torso': 'Torso',
    'minifig lower body': 'Legs', 'minifigure, legs': 'Legs',
    'minifigure, hips': 'Hips',
    'minifig headwear': 'Headgear', 'minifigure, headgear': 'Headgear',
    'minifigure, hair': 'Hair',
    'minifig accessories': 'Accessory', 'minifig headwear accessories': 'Accessory', 'minifig neckwear': 'Accessory',
    'minifig shields, weapons, & tools': 'Accessory', 'minifigure, accessory': 'Accessory', 'minifigure, utensil': 'Accessory',
    'minifigure, headgear accessories': 'Accessory', 'minifigure, neckwear': 'Accessory',
    'minifigs': 'Other', 'minifigure, other': 'Other', 'minifigure, part': 'Other',
}

FALLBACK_WORDS = 3


def short_name(category, name):
    """The short body-part name of one figure part, from its category name and its full catalogue name."""
    key = ' '.join(str(category or '').casefold().split())
    short = CATEGORY_SHORT.get(key)
    words = str(name or '').casefold().split()
    if short == 'Legs' and 'hips' in words and 'legs' not in words:
        short = 'Hips'
    elif short == 'Headgear' and 'hair' in words:
        short = 'Hair'
    elif short == 'Torso' and ('arm' in words or 'hand' in words or 'arms' in words or 'hands' in words) and 'torso' not in words:
        short = 'Other'
    if short:
        return short
    first = str(name or '').split()[:FALLBACK_WORDS]
    while first and first[-1] in ('x', '×', '-', '·'):
        first.pop()
    first = ' '.join(first).rstrip(',;:')
    return first or 'Other'


def short_names(parts):
    """`parts` is a list of (category, full name). Returns the distinct short names in order, so two torsos show once."""
    return list(dict.fromkeys(short_name(category, name) for category, name in parts))
