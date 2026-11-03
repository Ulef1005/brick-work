"""Invented Rebrickable dumps (small gzip CSVs) for the catalogue builder tests. No Rebrickable data is used."""
import csv
import gzip

from brickwork.store4.dump import HEADERS

COLORS = [('9999', '[No Color/Any Color]', '05131D', 'False'), ('-1', '[Unknown]', '0033B2', 'False'), ('0', 'Black', '05131D', 'False'),
          ('4', 'Red', 'C91A09', 'False'), ('15', 'White', 'FFFFFF', 'False'), ('43', 'Trans-Light Blue', 'AEE9EF', 'True')]
THEMES = [('186', 'Castle', ''), ('501', 'Gear', ''), ('9001', 'Gear Child', '501'), ('9002', 'Plain Child', '186'), ('497', 'Books', '')]
CATEGORIES = [('14', 'Plates'), ('5', 'Bricks')]
SETS = [('6081-1', 'King Leo Castle 12 x 4', '1993', '186', '3', 'https://img/6081.jpg'),
        ('9999-1', 'Plain Set 8 x 8', '2001', '186', '2', ''),
        ('5001-1', 'Gear Bag', '2010', '501', '0', ''),
        ('5002-1', 'Gear Child Keychain', '2011', '9001', '0', ''),
        ('5003-1', 'Plain Zero', '2012', '9002', '0', ''),
        ('5004-1', 'Reading Book', '2013', '497', '0', '')]
PARTS = [('3023', 'Plate 1 x 2', '14', 'Plastic'), ('3001', 'Brick 2 x 4', '5', 'Plastic'), ('970c03', 'Hips and Black Legs', '5', 'Plastic')]
FIGS = [('fig-000001', 'King Leo', '4', 'https://img/fig1.jpg'), ('fig-000002', 'Soldier', '3', '')]
# inventories: (id, version, parent)
INVENTORIES = [(1, 1, '6081-1'), (2, 2, '6081-1'), (3, 1, '9999-1'), (4, 1, 'fig-000001'), (5, 1, 'no-such-set')]
INVENTORY_PARTS = [(1, '3023', 4, 2, 'False', 'https://img/3023-red.jpg'), (1, '3023', 4, 1, 'False', ''), (1, '3001', 15, 3, 'False', ''),
                   (2, '3023', 4, 5, 'False', ''), (2, '3023', 4, 1, 'True', ''), (3, '3001', 0, 1, 'False', ''),
                   (4, '970c03', 0, 1, 'False', ''), (1, 'no-part', 4, 1, 'False', '')]
INVENTORY_MINIFIGS = [(1, 'fig-000001', 1), (1, 'fig-000002', 2)]
INVENTORY_SETS = [(3, '6081-1', 1)]
ELEMENTS = [('4211234', '3023', 4, '3023'), ('4211235', '3001', 15, ''), ('999', 'no-part', 4, '')]
RELATIONSHIPS = [('A', '3023', '3001'), ('M', '3001', '3023'), ('M', '3001', 'no-part')]


def default():
    return dict(colors=list(COLORS), themes=list(THEMES), part_categories=list(CATEGORIES), sets=list(SETS), parts=list(PARTS),
                minifigs=list(FIGS), inventories=list(INVENTORIES), inventory_parts=list(INVENTORY_PARTS),
                inventory_minifigs=list(INVENTORY_MINIFIGS), inventory_sets=list(INVENTORY_SETS), elements=list(ELEMENTS),
                part_relationships=list(RELATIONSHIPS))


def padded(name, row):
    """Rebrickable files carry a few columns the builder ignores (colors: num_parts, num_sets, y1, y2)."""
    width = len(HEADERS[name].split(','))
    return list(row) + [''] * (width - len(row))


def write_dump(directory, **tables):
    """Write the 12 files into `directory` (created). `tables` replace the defaults by name."""
    directory.mkdir(parents=True, exist_ok=True)
    data = default()
    data.update(tables)
    for name, header in HEADERS.items():
        with gzip.open(directory / f'{name}.csv.gz', 'wt', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(header.split(','))
            writer.writerows(padded(name, r) for r in data[name])
    return directory


def write_mappings(directory, *, colors=(), parts=(), exceptions=(), theme_kinds=None, version='2099.1.1.1'):
    """Tiny shipped-style mapping files (rows as tuples in each file's columns). theme_kinds defaults to the real two rows."""
    directory.mkdir(parents=True, exist_ok=True)
    head = f'# mapping_version: {version}\n# dump_date: 2099-01-01\n# source: invented\n'
    heads = {'colors.csv': 'rb_color_id,rb_name,provider,provider_key,provider_name,inverse_preferred,rb_num_parts',
             'parts.csv': 'rb_part_num,rb_color_id,provider,provider_kind,provider_key,status,method,preferred',
             'set_exceptions.csv': 'rb_set_num,provider_kind,provider_key,note',
             'theme_kinds.csv': 'rb_theme_id,theme_name,kind'}
    rows = {'colors.csv': colors, 'parts.csv': parts, 'set_exceptions.csv': exceptions,
            'theme_kinds.csv': theme_kinds if theme_kinds is not None else [('501', 'Gear', 'gear'), ('497', 'Books', 'book')]}
    for name, header in heads.items():
        (directory / name).write_text(head + header + '\n' + ''.join(','.join(map(str, r)) + '\n' for r in rows[name]))
    return directory
