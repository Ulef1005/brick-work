"""The gaps of copies as a BrickLink Wanted List (M.8d, issue #110; design 3.2, 4.4, 4.5).

A gap is what a copy lacks: a live set line's missing and damaged pieces (a retired line is no line; spares and a figure's own parts
are not set gaps) and a live figure line's missing figures. The export names every gap by the item's BrickLink number, type and colour
number (`core.items.bricklink_key`, which goes through `store4.identity.resolve`). An item with no confirmed BrickLink number cannot be
named in a wanted list: it is **skipped and listed**, never exported under a made-up number and never a reason to stop the export.
Its Planning route is `planning.export` (M.8g), which names a repair's remaining quantities through `export_lines`; the printable list is `list_exports`."""
from collections import defaultdict
import json
from xml.etree import ElementTree as ET

from . import errors, items

CONDITION = {'new': 'N', 'used': 'U'}                              # a copy with no recorded condition is exported as used, as before


def copy_gaps(db, copy_ids):
    """The gaps of live copies: `[dict(copy_id, item_id, color_id, quantity, condition)]`, set lines first, then figures, in line order."""
    if not isinstance(copy_ids, list) or not copy_ids or len(copy_ids) > 2000 or len(set(copy_ids)) != len(copy_ids):
        raise ValueError('Choose copies to export')
    wanted = json.dumps(copy_ids)
    conditions = {r['id']: r['condition'] for r in db.execute('SELECT id,condition FROM main.copy WHERE archived_at IS NULL AND id IN (SELECT value FROM json_each(?))', (wanted,))}
    if len(conditions) != len(copy_ids):
        raise ValueError('Copy is unavailable')
    found = []
    for r in db.execute('''SELECT copy_id,item_id,color_id,missing+damaged AS need FROM main.copy_part
                           WHERE retired_at IS NULL AND is_spare=0 AND copy_figure_id IS NULL AND missing+damaged>0
                           AND copy_id IN (SELECT value FROM json_each(?)) ORDER BY copy_id,id''', (wanted,)):
        found.append(dict(copy_id=r['copy_id'], item_id=r['item_id'], color_id=r['color_id'], quantity=r['need'], condition=conditions[r['copy_id']]))
    for r in db.execute('''SELECT copy_id,item_id,missing FROM main.copy_figure WHERE retired_at IS NULL AND missing>0
                           AND copy_id IN (SELECT value FROM json_each(?)) ORDER BY copy_id,id''', (wanted,)):
        found.append(dict(copy_id=r['copy_id'], item_id=r['item_id'], color_id=None, quantity=r['missing'], condition=conditions[r['copy_id']]))
    return found


def missing_lines(db, copy_ids):
    """The gaps combined per item, colour and condition, each named for BrickLink where it can be: `(lines, skipped)`.

    A line is `dict(item_id, color_id, condition, quantity, name, color_name, bricklink=(type, number, colour number))`; a skipped line is
    the same with `bricklink=None` and `why` (`no BrickLink number` or `no BrickLink colour`)."""
    total = defaultdict(int)
    for gap in copy_gaps(db, copy_ids):
        total[gap['item_id'], gap['color_id'], CONDITION.get(gap['condition'], 'U')] += gap['quantity']
    return named_lines(db, total)


def named_lines(db, total):
    """`missing_lines` for quantities already combined: `total` is `{(item id, colour id, 'N'|'U'): quantity}`."""
    names = {r['id']: r['name'] for r in db.execute('SELECT id,name FROM main.item WHERE id IN (SELECT value FROM json_each(?))', (json.dumps(sorted({k[0] for k in total})),))}
    colours = {r['id']: r['name'] for r in db.execute('SELECT id,name FROM main.color WHERE id IN (SELECT value FROM json_each(?))', (json.dumps(sorted({k[1] for k in total if k[1] is not None})),))}
    lines, skipped = [], []
    for (item_id, colour, condition), quantity in sorted(total.items(), key=lambda pair: (str(pair[0][0]).zfill(12), pair[0][1] or 0, pair[0][2])):
        line = dict(item_id=item_id, color_id=colour, condition=condition, quantity=quantity, name=names.get(item_id), color_name=colours.get(colour))
        try:
            key = items.bricklink_key(db, item_id, colour)
        except errors.Unidentified:
            skipped.append(dict(line, bricklink=None, why='no BrickLink number'))
            continue
        if colour is not None and key[2] is None:
            skipped.append(dict(line, bricklink=key, why='no BrickLink colour'))
            continue
        lines.append(dict(line, bricklink=key))
    return lines, skipped


def export(db, copy_ids):
    """`dict(xml, lines, skipped)`: BrickLink Wanted List XML of the named lines, the lines in it and the ones left out (and why)."""
    return export_lines(db, None, missing_lines(db, copy_ids))


def export_lines(db, total, named=None):
    """The same for quantities already combined (`total`, see `named_lines`), e.g. what a repair still has to buy."""
    lines, skipped = named if named is not None else named_lines(db, total)
    root = ET.Element('INVENTORY')
    for line in lines:
        kind, number, colour = line['bricklink']
        item = ET.SubElement(root, 'ITEM')
        for tag, value in (('ITEMTYPE', kind), ('ITEMID', number), ('COLOR', colour), ('MINQTY', line['quantity']), ('CONDITION', line['condition'])):
            if value is not None:
                ET.SubElement(item, tag).text = str(value)
    return dict(xml=ET.tostring(root, encoding='utf-8', xml_declaration=True), lines=lines, skipped=skipped)
