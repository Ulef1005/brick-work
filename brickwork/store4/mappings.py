"""Shipped mapping files (design 3.3): the reader and the leg rule."""
import csv
import re
from pathlib import Path

MAPPINGS_DIR = Path(__file__).resolve().parent.parent / 'catalogue' / 'mappings'
PARTS_COLUMNS = ('rb_part_num', 'rb_color_id', 'provider', 'provider_kind', 'provider_key', 'status', 'method', 'preferred')
COLUMNS = {
    'colors.csv': ('rb_color_id', 'rb_name', 'provider', 'provider_key', 'provider_name', 'inverse_preferred', 'rb_num_parts'),
    'parts.csv': PARTS_COLUMNS,
    'minifigs.csv': PARTS_COLUMNS,  # the shipped format of the figure mapping (design 3.4)
    'set_exceptions.csv': ('rb_set_num', 'provider_kind', 'provider_key', 'note'),
    'theme_kinds.csv': ('rb_theme_id', 'theme_name', 'kind'),
}
REQUIRED_META = ('mapping_version', 'dump_date')


def read_mapping(path):
    """Return (meta, rows): the `# key: value` header lines as a dict, then the CSV rows as dicts of strings."""
    path = Path(path)
    if path.name not in COLUMNS:
        raise ValueError(f'{path.name}: not a known mapping file')
    meta, body = {}, []
    with open(path, newline='', encoding='utf-8') as f:
        for line in f:
            if line.startswith('#') and not body:
                key, sep, value = line[1:].partition(':')
                if sep:
                    meta[key.strip()] = value.strip()
            else:
                body.append(line)
    for key in REQUIRED_META:
        if not meta.get(key):
            raise ValueError(f'{path.name}: header lacks {key}')
    reader = csv.DictReader(body)
    if tuple(reader.fieldnames or ()) != COLUMNS[path.name]:
        raise ValueError(f'{path.name}: columns {reader.fieldnames} differ from the expected {list(COLUMNS[path.name])}')
    return meta, list(reader)


_LEGS = re.compile(r'Hips and (.+?) Legs(?: \[Plain\])?')


def leg_rule(parts, colors):
    """Yield the leg-rule rows (design 3.2, decision E) in parts.csv columns, as dicts.

    `parts` is an iterable of (rb_part_num, name) from the dump; `colors` is an iterable of colors.csv rows (dicts with
    rb_color_id, rb_name, provider, provider_key, inverse_preferred). For a part `970cNN` named "Hips and <Colour> Legs"
    (a trailing " [Plain]" is ignored) the legs colour is the Rebrickable colour of that name, B its BrickLink colour id. Two
    rows: scoped to the legs colour -> BrickLink `970c00` (one-colour legs), and unscoped -> `970c{B:02d}` (any other hip
    colour). Printed variants (`970c01pat03`, `...pr1258`) and names not of this form are skipped, as are legs colours with
    no unique Rebrickable colour or no BrickLink id.

    The builder (M.2) loads these with origin 'rule'. A row here and an `external_ids` row of parts.csv with the same unscoped
    key are the same link; the builder keeps one."""
    by_name, bricklink = {}, {}
    for c in colors:
        by_name.setdefault(c['rb_name'], set()).add(c['rb_color_id'])
        if c['provider'] == 'bricklink':
            bricklink.setdefault(c['rb_color_id'], []).append(c)
    for num, name in parts:
        if not re.fullmatch(r'970c\d+', num):
            continue
        m = _LEGS.fullmatch(name)
        if not m:
            continue
        ids = by_name.get(m.group(1), ())
        if len(ids) != 1:
            continue
        color_id = next(iter(ids))
        links = bricklink.get(color_id, [])
        if len({k['provider_key'] for k in links}) != 1:
            continue  # no BrickLink id, or the colour has several and the choice is not ours
        base = dict(rb_part_num=num, provider='bricklink', provider_kind='P', status='matched', method='leg_rule', preferred='1')
        yield dict(base, rb_color_id=color_id, provider_key='970c00')
        yield dict(base, rb_color_id='', provider_key=f"970c{int(links[0]['provider_key']):02d}")
