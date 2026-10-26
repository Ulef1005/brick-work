"""Conservative visual size proxy. No dimensions or size state are persisted."""
import re

# family: (weight, representative size when dimensions are absent)
WEIGHTS = {'baseplate': (8, 64), 'large': (6, 16), 'brick': (3, 4),
           'plate': (2, 4), 'small': (.5, 1), 'neutral': (1, 4)}
NUMBER = r'(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)'
DIMENSIONS = re.compile(rf'(?<![\w./])({NUMBER})\s*[x×]\s*({NUMBER})(?:\s*[x×]\s*({NUMBER}))?', re.I)


def number(value):
    if '/' in value:
        whole, _, fraction = value.strip().rpartition(' ')
        a, b = fraction.split('/')
        return float(whole or 0) + float(a) / float(b)
    return float(value)


def size_score(name='', category=''):
    text = (name + ' ' + category).lower()
    wheel = name.lower().startswith(('wheel ', 'tyre ', 'tire ')) and not name.lower().startswith('wheel arch')
    if 'baseplate' in text:
        family = 'baseplate'
    elif wheel or any(x in text for x in ('hull', 'castle wall', 'wall panel', 'panel', 'windscreen')):
        family = 'large'
    elif any(x in name.lower() for x in ('tile', 'minifig', 'headwear', 'equipment', 'weapon', 'tool', 'plant')) or name.lower().startswith(('technic pin', 'technic axle', 'technic bush')):
        family = 'small'
    elif any(x in text for x in ('brick', 'slope', 'wedge', 'beam', 'liftarm')):
        family = 'brick'
    elif 'plate' in text:
        family = 'plate'
    else:
        family = 'neutral'
    weight, proxy = WEIGHTS[family]
    dimensions = list(DIMENSIONS.finditer(name))
    if len(dimensions) == 1:
        try:
            a, b, h = dimensions[0].groups()
            height = number(h) if h else (1/3 if family in ('plate', 'small') else 1)
            proxy = number(a) * number(b) * height
            # Wheel/tyre catalog dimensions are millimetres, not studs.
            if wheel:
                proxy /= 64
        except (ValueError, ZeroDivisionError):
            pass
    # A single axle length is a conservative recognition hint, never a footprint.
    axle = re.match(r'^Technic Axle (\d+(?:\.\d+)?)\b', name, re.I)
    if axle and not dimensions:
        proxy = max(1, min(32, float(axle[1])))
    return weight * proxy


def identities(db, item_ids):
    """`{item id: (name, category)}` for parts, one lookup: the projected item (design 6.3: name and `category_name` are projected),
    else the catalogue's. An id neither file knows is left out; ordering then falls back to a neutral score."""
    import json
    ids = json.dumps(sorted({i for i in item_ids if i}))
    found = {}
    if ids == '[]':
        return found
    from ..store4.connect import has_catalogue
    stores = [('main', 'i.category_name', '')]
    if has_catalogue(db):
        stores.append(('catalogue', 'c.name', ' LEFT JOIN catalogue.part_category c ON c.id=i.category_id'))
    for store, column, join in stores:
        for r in db.execute(f'SELECT i.id,i.name,{column} AS category FROM {store}.item i{join} WHERE i.id IN (SELECT value FROM json_each(?))', (ids,)):
            found.setdefault(r['id'], (r['name'], r['category'] or ''))
    return found


def ordered(rows, order='largest'):
    def key(row):
        tail = bool(row['spare'])
        tie = (row['sequence'], row['key'])
        if order == 'inventory':
            return (tail, *tie)
        if order == 'colour':
            return (tail, row['colour'].casefold(), *tie)
        if order in ('name', 'part', 'category'):
            return (tail, str(row[order]).casefold(), *tie)
        if order in ('quantity', 'damaged', 'checked'):
            return (tail, -row[order], *tie)
        if order == 'missing':
            return (tail, not bool(row['missing']), -row['score'], *tie)
        return (tail, -row['score'], *tie)
    return sorted(rows, key=key)


def progress(rows):
    required = [r for r in rows if not r['spare']]
    return dict(total=len(required), checked=sum(bool(r['checked']) for r in required),
                missing=sum(r['missing'] for r in required),
                checked_missing=sum(r['missing'] for r in required if r['checked']))
