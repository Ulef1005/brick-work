"""Invented 4.0 catalogue and collection files for the store4 tests; the records follow the design's worked examples."""
from contextlib import closing
import sqlite3

from brickwork.store4.connect import connect, create_catalogue

NOW = '2026-10-23T12:00:00Z'
COLOURS = [(3, 'Red', '4', '5'), (4, 'Black', '0', '11'), (5, 'White', '15', '1'), (6, 'Pastel Blue', '1051', '72'), (7, 'Maersk Blue', '313', '72')]
ITEMS = {10: ('set', 'sets', '6081-1'), 11: ('part', 'parts', '3023'), 12: ('part', 'parts', '970c03'), 13: ('part', 'parts', '970c05'),
         14: ('part', 'parts', '003402'), 16: ('part', 'parts', '3626'), 17: ('part', 'parts', '2339')}
# (item, colour, BrickLink kind, key, method): 970c03 is Black legs (970c00 in Black, 970c11 in any other hip colour, design 3.2)
LINKS = [(10, None, 'S', '6081-1', 'set_number'), (11, None, 'P', '3023', 'external_ids'), (16, None, 'P', '3626', 'external_ids'),
         (12, 4, 'P', '970c00', 'leg_rule'), (12, None, 'P', '970c11', 'leg_rule'),
         (13, 3, 'P', '970c00', 'leg_rule'), (13, None, 'P', '970c05', 'leg_rule'),
         (14, None, 'P', '310.3stk01', 'external_ids'), (14, None, 'P', '311.1stk01', 'external_ids'), (14, None, 'P', '312.3stk01', 'external_ids')]


def make_catalogue(path, catalogue_id='cat-A', builds=(1, 2), high_water=('20', '7')):
    with closing(create_catalogue(path)) as c:
        for b in builds:
            c.execute("INSERT INTO build(id, kind, started_at, app_version, files_json, counts_json) VALUES(?, ?, ?, '4.0', '[]', '{}')",
                      (b, 'rebrickable_dump' if b == 1 else 'mapping', NOW))
        c.executemany('INSERT INTO meta VALUES(?, ?)', [('catalogue_id', catalogue_id), ('item_high_water', high_water[0]),
                                                        ('color_high_water', high_water[1])])
        c.execute("INSERT INTO color VALUES(1, '[No Color/Any Color]', '05131D', 0, 'rebrickable', '9999', 1, NULL)")
        c.execute("INSERT INTO color VALUES(2, '[Unknown]', '0033B2', 0, 'rebrickable', '-1', 1, NULL)")
        for cid, name, key, bl in COLOURS:
            c.execute("INSERT INTO color VALUES(?, ?, NULL, 0, 'rebrickable', ?, 1, NULL)", (cid, name, key))
            c.execute("INSERT INTO color_link(color_id, provider, provider_key, provider_name, status, method, origin, inverse_preferred, build_id)"
                      " VALUES(?, 'bricklink', ?, ?, 'matched', 'external_ids', 'shipped', ?, 2)", (cid, bl, name, int(cid != 7)))
        c.execute("INSERT INTO theme(id, name, build_id) VALUES(186, 'Castle', 1)")
        c.execute("INSERT INTO part_category(id, name, build_id) VALUES(14, 'Plates', 1)")
        for i, (kind, ns, key) in ITEMS.items():
            c.execute("INSERT INTO item(id, kind, kind_source, name, name_key, size_key, year, num_parts, theme_id, category_id, born_provider,"
                      " born_namespace, born_key, build_id, digest) VALUES(?, ?, 'namespace', ?, ?, '1x2', 1993, 12, ?, ?, 'rebrickable', ?, ?, 1, ?)",
                      (i, kind, f'item {key}', f'item {key}', 186 if kind == 'set' else None, 14 if kind == 'part' else None, ns, key, f'digest-{i}'))
        for item, colour, kind, key, method in LINKS:
            c.execute("INSERT INTO item_link(item_id, color_id, provider, provider_kind, provider_key, status, method, origin, evidence_digest, build_id)"
                      " VALUES(?, ?, 'bricklink', ?, ?, 'matched', ?, 'shipped', 'e', 2)", (item, colour, kind, key, method))
        c.commit()


def activate(path, builds=(1, 2), **meta):
    """Record builds as activated in a collection (and optionally meta rows), as the builder will in M.2."""
    with closing(connect(path, path.parent / 'none.db')) as db:
        for b in builds:
            db.execute("INSERT OR IGNORE INTO catalogue_build VALUES(?, 'x', NULL, ?, NULL, '{}')", (b, NOW))
        db.executemany('INSERT OR REPLACE INTO meta VALUES(?, ?)', meta.items())
        db.commit()


def pair(tmp_path, **kw):
    cat, col = tmp_path / 'catalogue.db', tmp_path / 'brickwork.db'
    make_catalogue(cat, **kw)
    activate(col)
    return col, cat
