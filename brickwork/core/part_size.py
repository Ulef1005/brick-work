"""How big a part is, from its catalogue name and category, in brick volumes (a 1 x 1 brick is 1).

Check Set Parts orders "Largest first" by this, so the pieces that are easiest to find in a pile and
take the most room come first. The first size in the name gives width x depth x height in studs and
bricks ("Brick 2 x 4" is 8, "Brick 1 x 2 x 3" is 6); plates, tiles and baseplates without a height are
a third of a brick ("Plate 2 x 4" is 2.67, "Baseplate 32 x 32" is 341). A name without a size falls
back to its family. It is an estimate for ordering, never stored or shown.
"""
import re

NUMBER = r'(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)'
SIZE = re.compile(rf'(?<![\w./])({NUMBER})\s*[x×]\s*({NUMBER})(?:\s*[x×]\s*({NUMBER}))?(?![\w/])', re.I)
THIN = ('plate', 'tile', 'baseplate', 'panel')
# Families for names without a size: (words in the name or category, brick volumes)
FAMILIES = (
    (('baseplate', 'road plate'), 100.0),
    (('hull', 'castle wall', 'wall element', 'windscreen', 'boat', 'train base'), 16.0),
    (('minifig', 'utensil', 'weapon', 'tool', 'plant', 'flower', 'headwear', 'hair', 'equipment',
      'technic, pin', 'technic pin', 'technic bush', 'antenna', 'bar ', 'lever'), 0.2),
    (('wheel', 'tyre', 'tire'), 1.5),
    (('brick', 'slope', 'wedge', 'arch', 'cylinder', 'cone'), 2.0),
)


def number(value):
    value = value.strip()
    if '/' in value:
        whole, _, fraction = value.rpartition(' ')
        a, b = fraction.split('/')
        return (float(whole) if whole else 0.0) + float(a) / float(b)
    return float(value)


def volume(name, category=''):
    name, category = name or '', category or ''
    text = f'{name} {category}'.lower()
    match = SIZE.search(name)
    if match and 'mm' not in name[match.start():match.end() + 3].lower():
        try:
            width, depth, height = match.groups()
            if height:
                h = number(height)
            elif any(word in text for word in THIN):
                h = 1 / 3
            else:
                h = 1.0
            return number(width) * number(depth) * h
        except (ValueError, ZeroDivisionError):
            pass
    axle = re.match(r'^technic,?\s+axle\s+(\d+(?:\.\d+)?)\b', name, re.I)
    if axle:
        return float(axle[1]) * 0.25  # long and thin
    for words, size in FAMILIES:
        if any(word in text for word in words):
            return size
    if 'plate' in text or 'tile' in text:
        return 0.5
    return 1.0
