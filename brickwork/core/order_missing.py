"""Order missing parts (#225): the copies with gaps, a choice among them, and the combined order list of that choice.

Read-only, on the same rows as Complete sets: `planning.ranking` gives every live copy with a gap, its lines already net of the loose stock
the repair settings let it use, so the list here is the file `planning.export` writes for the same copies, line for line. The one thing
added is where each combined line comes from: `sources`, the ticked copies and their quantities. Loose stock is taken from one pool over all
copies in set-number order, as the export does, not afresh per choice. The XML itself is `planning.export`; nothing here writes it."""
from collections import defaultdict
from decimal import Decimal
import json
import re

from . import collection, gaps, planning

# Brick Work has no "to sell" or "part out" mark on a copy, so the screen reads the copy's own status and tag flags (the user names them).
# A flag counts when its lower-cased name, hyphens as spaces, holds one of these words.
LEAVE_OUT = ('to sell', 'for sale', 'selling', 'sell', 'part out', 'parting out', 'parted out', 'donor')
SORTS = (('missing', 'Most missing'), ('fewest', 'Fewest missing'), ('gain', 'Most gain'), ('number', 'Number'), ('name', 'Name'))
FIRST_LINES = 4


def sell_flag(name):
    """Whether a flag's name says its copy is for sale or to be parted out."""
    text = re.sub(r'[\s\-_]+', ' ', (name or '').lower())
    return any(re.search(rf'\b{re.escape(word)}\b', text) for word in LEAVE_OUT)


def candidates(db):
    """Every live copy with a gap, in set-number order: the ranking row plus `parts` and `figures` (the recorded gap), `gain` (the net
    gain of repairing it, or None where the ranking gives none), `to_sell` (the matching flag's name or None) and `checking`."""
    rows = [dict(r) for r in planning.ranking(db)['rows']]
    ids = [r['id'] for r in rows]
    flags = defaultdict(list)
    for r in db.execute('''SELECT cf.copy_id,f.name FROM copy_flag cf JOIN flag f ON f.id=cf.flag_id AND f.archived_at IS NULL
                           WHERE f.kind IN ('status','tag') AND cf.copy_id IN (SELECT value FROM json_each(?)) ORDER BY f.name''', (json.dumps(ids),)):
        flags[r[0]].append(r[1])
    checking = {r[0] for r in db.execute('SELECT copy_id FROM part_check WHERE copy_figure_id IS NULL AND finished=0')}
    sets = defaultdict(int)
    for r in rows:
        sets[r['item_no']] += 1
        r['parts'] = sum(i['original_gap'] for i in r['items'] if i['type'] != 'M')
        r['figures'] = sum(i['original_gap'] for i in r['items'] if i['type'] == 'M')
        r['gain'] = r['net_gain'] if r['group'] in ('ranked', 'free_repairs') and r['net_gain'] > 0 else None
        r['to_sell'] = next((n for n in flags[r['id']] if sell_flag(n)), None)
        r['checking'] = r['id'] in checking
    for r in rows:
        r['show_label'] = sets[r['item_no']] > 1 or r['label'] != 'Set 1'               # "Set 2" says which copy, as Complete sets does
        r['source_label'] = (r['number_text'] or r['item_no'] or r['name'] or '') + (f' · {r["label"]}' if r['show_label'] else '')
    return sorted(rows, key=lambda r: (r['set_num'], r['id']))


def left_out(row, *, sell, gain):
    """Why a copy is left out of the default choice, or None: its sale flag (while `sell`) or no gain (while `gain` asks for it)."""
    if sell and row['to_sell']:
        return row['to_sell']
    if gain and row['gain'] is None:
        return 'no value gain'
    return None


def visible(rows, *, query='', theme=''):
    """The rows the search and the theme leave on the screen."""
    needle = query.strip().lower()
    return [r for r in rows if (not theme or (r['theme'] or '') == theme)
            and (not needle or needle in ' '.join(str(x or '') for x in (r['item_no'], r['number_text'], r['name'], r['label'])).lower())]


def ordered(rows, sort):
    """`rows` in the chosen order (ties by number, then copy)."""
    base = sorted(rows, key=lambda r: (r['set_num'], r['id']))
    if sort == 'fewest':
        return sorted(base, key=lambda r: r['parts'] + r['figures'])
    if sort == 'gain':
        return sorted(base, key=lambda r: (r['gain'] is None, -(r['gain'] or 0)))
    if sort == 'name':
        return sorted(base, key=lambda r: (r['name'] or '').lower())
    if sort == 'number':
        return base
    return sorted(base, key=lambda r: -(r['parts'] + r['figures']))


def combine(rows, chosen, quotes=None):
    """`({(item id, colour id, 'N'|'U'): to buy}, {same key: [(copy id, to buy)]})` over the chosen copies only.

    The grouping is `planning.export`'s: the quantity still to buy of each line, per item, colour and condition."""
    total, sources = defaultdict(int), defaultdict(list)
    for row in rows:
        if row['id'] not in chosen:
            continue
        mine = defaultdict(int)
        for line in row['items']:
            if line['missing']:
                key = line['item_id'], line['color_id'], gaps.CONDITION.get(row['condition'], 'U')
                mine[key] += line['missing']
                if quotes is not None and line.get('quote') and key not in quotes:
                    quotes[key] = line['quote']                                      # a copy's condition fixes the quote, so any source gives the same
        for key, quantity in mine.items():
            total[key] += quantity
            sources[key].append((row['id'], quantity))
    return total, sources


def order_list(db, rows, chosen):
    """The order list of the chosen copies: `dict(lines, skipped, pieces)`.

    A line is `gaps.named_lines`' (name, colour, condition, BrickLink key) with `quantity`, the screen's words for the item (`number_text`,
    `image`, colour `rgb` and `ink`) and `sources`: `[dict(copy_id, label, quantity)]`, the largest first. `skipped` are the lines the file
    leaves out (no BrickLink number or colour), the same way. `pieces` is the sum of the lines in the file, a figure counting as many as its
    quantity."""
    quotes = {}
    total, sources = combine(rows, chosen, quotes)
    lines, skipped = gaps.named_lines(db, total)
    by_copy = {r['id']: r for r in rows}
    key = lambda line: (line['item_id'], line['color_id'], line['condition'])           # noqa: E731
    shown = collection.decorate(db, [dict(item_id=l['item_id'], color_id=l['color_id']) for l in lines + skipped])
    names = {(s['item_id'], s['color_id']): s for s in shown}
    for line in lines + skipped:
        line['quote'] = quotes.get(key(line))
        line.update(sources=[dict(copy_id=c, label=by_copy[c]['source_label'], quantity=q)
                             for c, q in sorted(sources[key(line)], key=lambda s: (-s[1], by_copy[s[0]]['source_label']))])
        shown_line = names[line['item_id'], line['color_id']]
        line.update({k: shown_line.get(k) for k in ('number_text', 'image', 'rgb', 'ink', 'item_type')})
    lines.sort(key=lambda l: (-l['quantity'], l['number_text'] or l['name'] or '', l['color_id'] or 0, l['condition']))
    return dict(lines=lines, skipped=skipped, pieces=sum(l['quantity'] for l in lines))


# ---------- the source of each line (#54): BrickLink or Pick a Brick ----------

BL, PAB = 'bl', 'pab'
PAB_FILE_LIMIT = 400                                                       # part types one Pick a Brick upload takes, as reported; the file is not split
SOURCE_WORDS = {BL: 'BrickLink', PAB: 'Pick a Brick'}


def line_key(line):
    """The line's address in the query: item, colour (0 for none) and condition, `<item>.<colour>.<N|U>`."""
    return f"{line['item_id']}.{line['color_id'] if line['color_id'] is not None else 0}.{line['condition']}"


def parse_choices(values):
    """`{line key: 'bl'|'pab'}` from the query's `src` values (`<line key>.<b|p>`); anything else is ignored."""
    chosen = {}
    for value in values or []:
        key, _, letter = str(value).rpartition('.')
        if key and letter in ('b', 'p'):
            chosen[key] = PAB if letter == 'p' else BL
    return chosen


def choice_value(key, source):
    return f"{key}.{'p' if source == PAB else 'b'}"


def element_ids(db, lines):
    """`{(item id, colour id): Pick a Brick element id}` for the lines: the catalogue's lowest element id of the part in that colour
    (a part and colour can have several; the lowest is always the same one)."""
    wanted = sorted({l['item_id'] for l in lines if l['color_id'] is not None})
    if not wanted:
        return {}
    found = db.execute("""SELECT item_id,color_id,min(CAST(element_id AS INTEGER)) FROM catalogue.element
                          WHERE item_id IN (SELECT value FROM json_each(?)) GROUP BY item_id,color_id""", (json.dumps(wanted),))
    return {(r[0], r[1]): str(r[2]) for r in found}


def split(db, order, *, prefer, chosen, config):
    """`order` (from `order_list`) with every line placed: `source` ('bl' or 'pab'), `element_id` (or None), `key` and `price`
    (the BrickLink quote's price as a Decimal, or None), then `split`: the totals per source.

    A line goes where the query's `chosen` says; else to Pick a Brick when `prefer` is on and the line has an element id; else to BrickLink.
    A choice of Pick a Brick for a line with no element id is ignored. Pick a Brick has no price here (its prices are not looked up);
    the BrickLink total counts the lines with a quote and says how many have none. Shipping is the Repair settings' for the BrickLink part."""
    elements = element_ids(db, order['lines'])
    for line in order['lines']:
        line['key'] = line_key(line)
        line['element_id'] = elements.get((line['item_id'], line['color_id']))
        wanted = chosen.get(line['key'])
        if wanted == PAB and not line['element_id']:
            wanted = None
        line['source'] = wanted or (PAB if prefer and line['element_id'] else BL)
        quote = line.get('quote')
        line['price'] = Decimal(str(quote['price'])) if quote and quote.get('price') is not None else None
    parts = {src: [l for l in order['lines'] if l['source'] == src] for src in (BL, PAB)}
    bl_total = sum((l['price'] * l['quantity'] for l in parts[BL] if l['price'] is not None), Decimal(0))
    shipping = Decimal(str(config['repair_shipping'])) if parts[BL] else None
    order['split'] = dict(
        bl=dict(lines=len(parts[BL]), pieces=sum(l['quantity'] for l in parts[BL]), total=bl_total, no_sales=sum(1 for l in parts[BL] if l['price'] is None)),
        pab=dict(lines=len(parts[PAB]), pieces=sum(l['quantity'] for l in parts[PAB])),
        shipping=shipping, estimate=bl_total + (shipping or Decimal(0)), no_element=[l for l in order['lines'] if not l['element_id']])
    return order


def pick_a_brick_csv(order):
    """The Pick a Brick upload file of the lines placed on Pick a Brick: `elementId,quantity`, one line each, in the list's order."""
    rows = ['elementId,quantity'] + [f"{l['element_id']},{l['quantity']}" for l in order['lines'] if l['source'] == PAB]
    return '\r\n'.join(rows) + '\r\n'
