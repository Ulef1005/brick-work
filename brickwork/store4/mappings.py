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


def _colour_key(name):
    return ' '.join(w for w in name.lower().split() if w != 'the')


def leg_rule(parts, colors, external=None):
    """Yield the leg-rule rows (design 3.2, decision E) in parts.csv columns, as dicts.

    `parts` is an iterable of (rb_part_num, name) from the dump; `colors` is an iterable of colors.csv rows (dicts with
    rb_color_id, rb_name, provider, provider_key, inverse_preferred). For a part `970cNN` named "Hips and <Colour> Legs"
    (a trailing " [Plain]" is ignored) the legs colour is the Rebrickable colour of that name, B its BrickLink colour id. Two
    rows: scoped to the legs colour -> BrickLink `970c00` (one-colour legs), and unscoped -> `970c{B:02d}` (any other hip
    colour). Colour names compare case-insensitively and without "the" ("Glow In The Dark White" is "Glow in Dark White").
    Printed variants (`970c01pat03`, `...pr1258`) and names not of this form are skipped, as are legs colours with no unique
    Rebrickable colour or no BrickLink id.

    `external` maps a Rebrickable part number to the BrickLink keys its `external_ids` give (parts.csv). A row is `matched`
    only when Rebrickable confirms its exact key, else `inferred`: the convention "NN = the legs' BrickLink colour id" is
    Rebrickable's, and for newer colours BrickLink has no `970cNN` item at all (33 of 67 keys on the 2026-10-23 data,
    checked privately in M.4), so an unconfirmed key is a guess for M.4 and the local layer to correct (design § 9).

    The builder (M.2) loads these with origin 'rule' and, for a part this yields rows for, loads no `external_ids` row of
    parts.csv: Rebrickable lists both `970c00` and `970cNN` unscoped there, which in any colour but the legs' own would
    make `970c00` a second candidate (resolve_inverse would find two parts for `970c00` in Red)."""
    by_name, bricklink = {}, {}
    for c in colors:
        by_name.setdefault(_colour_key(c['rb_name']), set()).add(c['rb_color_id'])
        if c['provider'] == 'bricklink':
            bricklink.setdefault(c['rb_color_id'], []).append(c)
    for num, name in parts:
        if not re.fullmatch(r'970c\d+', num):
            continue
        m = _LEGS.fullmatch(name)
        if not m:
            continue
        ids = by_name.get(_colour_key(m.group(1)), ())
        if len(ids) != 1:
            continue
        color_id = next(iter(ids))
        links = bricklink.get(color_id, [])
        if len({k['provider_key'] for k in links}) != 1:
            continue  # no BrickLink id, or the colour has several and the choice is not ours
        confirmed = (external or {}).get(num, set())
        base = dict(rb_part_num=num, provider='bricklink', provider_kind='P', method='leg_rule', preferred='1')
        for scope, key in ((color_id, '970c00'), ('', f"970c{int(links[0]['provider_key']):02d}")):
            yield dict(base, rb_color_id=scope, provider_key=key, status='matched' if key in confirmed else 'inferred')
