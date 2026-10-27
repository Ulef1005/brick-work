"""Orders on the 4.0 store (M.8h, issue #110; design 5 `purchase_order`, `order_document`, `order_line`, `line_receipt`, `allocation`, 3.2, 3.8).

An order is a BrickLink purchase; a document is one way it came in (the order XML, the store's e-mail, the BrickLink API), reviewed in
phases (`draft` → `reviewed` → `saved`; `undone` when its import is taken back). A line keeps the provider's own words verbatim (`raw_*`)
and, where it could be placed, the item and colour it stands for. **Placing is by item id**: a BrickLink type, number and colour number go
through `store4.identity.resolve_inverse(..., exhaustive=True)` (the pooled answer: the collection's links and the catalogue's), so a key
that names two items is never guessed. It becomes an *unresolved* line (`state='by_hand'`, the candidates in `suggestions_json`) that the
person matches in the draft. A colour name from an e-mail goes through the BrickLink colour names of `color_link`, an item name through exact
names (the BrickLink item list when loaded, else the catalogue's); several hits stay for hand matching.

Receipts count what came out of the bag per saved line (`line_receipt`, every change logged in `line_receipt_log`). Allocation is explicit:
a received piece goes to a copy's gap (the Workbench's gap semantics, `core/workbench.py`) or into loose stock, never by itself.

**Every write is one event** `orders:<order id>` / `<action>` whose receipt lists the tables it changed, before and after (the Workbench's
`Tracker`, here `Journal`). Undo (`core/undo.py`) refuses unless every row still equals what the request left, puts the order rows back
(an import is not erased: its document becomes `undone`, its lines and the raw record stay as provenance) and hands the copy and stock rows
to the collection's generic undoer. A guard row keeps a copy's status as the allocation left it.
"""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from uuid import uuid4
from xml.etree import ElementTree as ET

from ..store4 import identity
from ..store4.connect import has_catalogue, now as stamp_now
from ..store4.errors import AmbiguousIdentity, Store4Error
from . import add, collection, errors, items, stock as stock_module
from . import undo as undoing
from . import workbench as w
from .transaction import transaction
from .sources.bricklink import BrickLink, TYPE_IDS

ENTITY = 'orders'
LIVE = "('applied','pending','conflict','undoing')"
ORDER_TABLES = ('purchase_order', 'order_document', 'order_line', 'line_receipt', 'line_receipt_log', 'allocation')
KEYS = {'line_receipt': 'line_id'}                                     # every other order table is keyed by `id`
CONDITIONS = {'N': 'new', 'U': 'used', 'new': 'new', 'used': 'used'}
LETTERS = {'new': 'N', 'used': 'U'}
GAP_KINDS = {'part': 'missing_part', 'figure': 'missing_figure', 'instructions': 'instructions', 'box': 'box'}
CHANGED = 'This item changed after saving · undo the later save first'


def price(value):
    if value in (None, ''):
        return None
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number.as_tuple().exponent < -4:
            raise InvalidOperation()
    except InvalidOperation:
        raise ValueError('Use a non-negative price with up to four decimals') from None
    return format(number, 'f')


# ---------- the receipt of a request ----------

_JOURNAL = None


def Journal(db):
    """The tracker of a request. Built on first use: `workbench` (the base class) imports `add`, which registers every undoer through
    `undo`, which imports this module, so the class cannot be made while this module loads."""
    global _JOURNAL
    if _JOURNAL is None:
        _JOURNAL = _journal_class()
    return _JOURNAL(db)


def _journal_class():
    class Journal(w.Tracker):
        """The Workbench's tracker over the order tables too, plus a guard on the copies an allocation changed."""

        def __init__(self, db):
            super().__init__(db)
            self.guarded = set()

        def key(self, table):
            return KEYS.get(table, 'id')

        def snapshot(self, table, ids):
            if table not in ORDER_TABLES:
                return super().snapshot(table, ids)
            key = self.key(table)
            return [dict(r) for r in self.db.execute(f'SELECT * FROM main.{table} WHERE {key} IN (SELECT value FROM json_each(?)) ORDER BY {key}',
                                                     (json.dumps([int(i) for i in ids]),))]

        def guard(self, *copy_ids):
            self.guarded.update(copy_ids)

        def entries(self):
            entries = super().entries()
            if self.guarded:
                entries.append(('guard', [], copy_guard(self.db, sorted(self.guarded))))
            return entries

        def write(self, field, order_id):
            return super().write(field, ENTITY + ':' + str(order_id))
    return Journal


def copy_guard(db, copy_ids):
    """The status of copies as an allocation left it: the copy row and its status flags."""
    return [dict(id=c, copy=dict(row) if (row := db.execute('SELECT * FROM main.copy WHERE id=?', (c,)).fetchone()) else None,
                 flags=[r[0] for r in db.execute('SELECT flag_id FROM main.copy_flag WHERE copy_id=? ORDER BY flag_id', (c,))]) for c in copy_ids]


# ---------- reads ----------

def get(db, order_id):
    row = db.execute('SELECT * FROM main.purchase_order WHERE id=?', (order_id,)).fetchone()
    if not row:
        raise ValueError('Order is unavailable')
    return dict(row)


def listing(db):
    rows = [dict(r) for r in db.execute("""WITH a AS (
      SELECT line_id,sum(qty) AS allocated FROM main.allocation WHERE state IN """ + LIVE + """ GROUP BY line_id),
      l AS (SELECT l.order_id,count(*) AS lots,sum(l.qty) AS pieces,
      sum(coalesce(r.received,0)) AS received,sum(coalesce(a.allocated,0)) AS allocated,sum(l.state='held') AS held
      FROM main.order_line l JOIN main.order_document d ON d.id=l.document_id
      LEFT JOIN main.line_receipt r ON r.line_id=l.id LEFT JOIN a ON a.line_id=l.id
      WHERE d.phase='saved' AND l.paired_line_id IS NULL GROUP BY l.order_id),
      d AS (SELECT order_id,sum(phase='draft') AS drafts,sum(phase='reviewed') AS reviewed,count(*) AS documents
      FROM main.order_document WHERE phase!='undone' GROUP BY order_id)
      SELECT o.*,coalesce(l.lots,0) AS lots,coalesce(l.pieces,0) AS pieces,
      coalesce(l.received,0) AS received,coalesce(l.allocated,0) AS allocated,coalesce(l.held,0) AS held,
      coalesce(d.drafts,0) AS drafts,coalesce(d.reviewed,0) AS reviewed
      FROM main.purchase_order o LEFT JOIN l ON l.order_id=o.id LEFT JOIN d ON d.order_id=o.id
      ORDER BY coalesce(o.date_ordered,o.created_at) DESC,o.id DESC""")]
    for row in rows:
        row['phase'] = ('Draft' if row['drafts'] else 'Reviewed' if row['reviewed'] else
                        'Held' if row['held'] else 'Reconciled' if row['status'] == 'Reconciled' else
                        'Allocated' if row['received'] and row['received'] == row['allocated'] else
                        'Counting' if row['received'] else 'Open')
    return rows


def lines(db, order_id):
    """Every line of an order with its document's phase, what was received and what is allocated (live allocations), and its item's kind."""
    return [dict(r) for r in db.execute('''SELECT l.*,d.phase,coalesce(r.received,0) AS received,coalesce(a.allocated,0) AS allocated,i.kind AS kind
      FROM main.order_line l JOIN main.order_document d ON d.id=l.document_id
      LEFT JOIN main.line_receipt r ON r.line_id=l.id
      LEFT JOIN (SELECT line_id,sum(qty) AS allocated FROM main.allocation WHERE state IN ''' + LIVE + ''' GROUP BY line_id) a ON a.line_id=l.id
      LEFT JOIN main.item i ON i.id=l.item_id WHERE l.order_id=? ORDER BY l.document_id,l.line_no''', (order_id,))]


def decorate_lines(db, rows):
    """Identity, colour and picture for lines that have an item; the provider's own words for the ones that have not (`unplaced`)."""
    placed = [r for r in rows if r['item_id'] is not None]
    done = iter(collection.decorate(db, placed))
    # Candidates of an unplaced line: the ones your copies are missing come first, with the count; the person still chooses.
    missing = defaultdict(int)
    if any(r['item_id'] is None and r.get('suggestions_json') for r in rows):
        for gap in w.gaps(db):
            missing[gap['item_id'], gap.get('color_id')] += gap['need']
    result = []
    for row in rows:
        if row['item_id'] is not None:
            row = next(done)
            row['name'] = row.get('name') or row.get('raw_name')
        else:
            colour = row['raw_color_name'] or (f"BrickLink colour {row['raw_color_id']}" if row['raw_color_id'] is not None else None)
            row = dict(row, item_type=row['raw_item_type'] or '?', item_no='', number_text='', name=row['raw_name'] or row['raw_item_no'] or row['raw_text'],
                       image=None, color_name=colour, rgb=None, ink=None, unresolved=False, unplaced=True, kind=items.TYPE_KIND.get(row['raw_item_type']))
        row['unplaced'] = row['item_id'] is None
        try:
            row['suggestions'] = json.loads(row['suggestions_json']) if row.get('suggestions_json') else []
        except ValueError:
            row['suggestions'] = []
        for suggestion in row['suggestions']:
            suggestion['missing'] = missing[suggestion['item_id'], row.get('color_id')]
        row['suggestions'].sort(key=lambda suggestion: -suggestion['missing'])
        result.append(row)
    return result


def history(db, order_id, *, limit=200):
    """The newest saves of an order: `[dict(id, at, receipt=dict(action), receipt_count, undone, undo_available)]`."""
    rows = db.execute(f"""SELECT e.id,e.at,e.field,{undoing.undone_sql()} AS undone,{undoing.undoable_sql()} AS undoable FROM main.event e
                          WHERE e.entity_kind=? AND e.entity_id=? ORDER BY e.id DESC LIMIT ?""", (ENTITY, str(order_id), limit))
    return [dict(id=r['id'], at=r['at'], receipt=dict(action=r['field']), receipt_count=1, undone=bool(r['undone']),
                 undo_available=bool(r['undoable']) and not r['undone']) for r in rows]


def allocation_rows(db, order_id, line_rows):
    """The allocations of an order, newest first, each with its line, a target label and the event that undoes it (None when it is not the
    allocation's own save any more)."""
    rows = [dict(r) for r in db.execute('SELECT * FROM main.allocation WHERE order_id=? ORDER BY id DESC', (order_id,))]
    if not rows:
        return rows
    by_line = {r['id']: r for r in line_rows}
    copies = sorted({r['copy_id'] for r in rows if r['copy_id']})
    labels = collection.copy_labels(db, copies) if copies else {}
    numbers = {}
    if copies:
        sets = {r['id']: r['item_id'] for r in db.execute('SELECT id,item_id FROM main.copy WHERE id IN (SELECT value FROM json_each(?))', (json.dumps(copies),))}
        numbers = {k[0]: label.text for k, label in items.labels(db, [(i, None) for i in set(sets.values())]).items()}
        numbers = {c: numbers.get(i, '') for c, i in sets.items()}
    stocks = {r['id']: dict(r) for r in db.execute('''SELECT s.id,t.name AS storage,l.name AS lot FROM main.stock s LEFT JOIN main.storage t ON t.id=s.storage_id
                                                    LEFT JOIN main.lot l ON l.id=s.lot_id WHERE s.id IN (SELECT value FROM json_each(?))''',
                                                 (json.dumps(sorted({r['stock_id'] for r in rows if r['stock_id']})),))}
    undo = {}
    for event in db.execute(f"""SELECT e.id,e.new_value FROM main.event e WHERE e.entity_kind=? AND e.entity_id=? AND e.field='allocate'
                               AND NOT {undoing.undone_sql()} ORDER BY e.id""", (ENTITY, str(order_id))):
        for table in json.loads(event['new_value']):
            if table['table'] == 'allocation':
                for row in table['rows']:
                    undo[row['id']] = event['id']
    for row in rows:
        row['identity'] = by_line.get(row['line_id'])
        if row['target_kind'] == 'copy':
            row['target_label'] = ' · '.join(['Copy ' + numbers.get(row['copy_id'], ''), labels.get(row['copy_id'], '')]).strip(' ·')
        else:
            stock = stocks.get(row['stock_id']) or {}
            row['target_label'] = ('Lot ' + stock['lot'] if stock.get('lot') else 'Loose stock') + (' · ' + stock['storage'] if stock.get('storage') else '')
        row['undo_event'] = undo.get(row['id']) if row['state'] == 'applied' else None
    return rows


def detail(db, order_id):
    order = get(db, order_id)
    rows = decorate_lines(db, lines(db, order_id))
    saved = [r for r in rows if r['phase'] == 'saved' and r['paired_line_id'] is None]
    documents = [dict(r) for r in db.execute('SELECT * FROM main.order_document WHERE order_id=? ORDER BY id', (order_id,))]
    return dict(order=order, documents=documents, lines=rows, saved=saved, allocations=allocation_rows(db, order_id, rows),
                ordered=sum(r['qty'] or 0 for r in saved), received=sum(r['received'] for r in saved), allocated=sum(r['allocated'] for r in saved),
                history=history(db, order_id))


# ---------- reading a document ----------

def parse_xml(text):
    """BrickLink order or inventory XML → `(rows, header)`: the provider's words only, nothing looked up."""
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise ValueError('Choose XML without document declarations')
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        raise ValueError('The XML could not be read') from None
    if root.tag not in ('ORDER', 'ORDERS', 'INVENTORY'):
        raise ValueError('Choose a BrickLink order or inventory XML')
    if root.tag == 'ORDERS':
        entries = root.findall('ORDER')
        if len(entries) != 1:
            raise ValueError('Choose exactly one order per file')
        root = entries[0]
    rows = []
    for n, item in enumerate(root.findall('.//ITEM'), 1):
        values = {e.tag.upper(): (e.text or '').strip() for e in item}
        letter = values.get('ITEMTYPE', '').upper()
        if letter not in items.TYPE_KIND:
            raise ValueError(f'Line {n} · choose a BrickLink item type')
        rows.append(dict(line_no=n, item_type=letter, item_no=values.get('ITEMID', ''), color_id=values.get('COLOR') if letter == 'P' else None,
                         condition=values.get('CONDITION', ''), qty=values.get('QTY') or values.get('MINQTY'), unit_price=values.get('PRICE'),
                         remark=values.get('REMARKS', ''), raw_text=ET.tostring(item, encoding='unicode')))
    return rows, dict(bricklink_order_id=root.findtext('.//ORDERID'), store=root.findtext('STORENAME'), seller=root.findtext('SELLER'),
                      date_ordered=root.findtext('ORDERDATE'), status=root.findtext('STATUS'), currency=root.findtext('CURRENCY'), cost=root.findtext('COST'))


def _bricklink_colour_names(db):
    """`{lower name: BrickLink colour number}` from the colour links' provider names (the collection's rows win over the catalogue's)."""
    names = {}
    for store in ('main', 'catalogue') if has_catalogue(db) else ('main',):
        for r in db.execute(f"SELECT provider_key,provider_name FROM {store}.color_link WHERE provider='bricklink' AND provider_name IS NOT NULL"):
            names.setdefault(r['provider_name'].lower(), r['provider_key'])
    return names


def parse_email(db, text):
    """A store's order e-mail → `(rows, header)`. A line carries a BrickLink colour name and an item name, no number: the colour name is read
    through the colour links and the item name stays (`name_query`) for `resolve_names`. An instruction line names its set."""
    colours = _bricklink_colour_names(db)
    ordered = sorted(colours, key=lambda n: -len(n))
    pattern = re.compile(r'^\[(New|Used)\] (.+?)\s+\(x(\d+)\) \.+ EUR ([\d.]+) each = EUR ([\d.]+)$')
    rows = []
    batch = submitted = None
    for n, line in enumerate(text.splitlines(), 1):
        head = re.fullmatch(r'\* Batch #(\d+) \(submitted (.+)\)', line.strip())
        if head:
            batch, submitted = int(head[1]), head[2]
            continue
        match = pattern.fullmatch(line.strip())
        if not match:
            if line.lstrip().startswith(('[New]', '[Used]')):
                raise ValueError(f'Line {n} · the quantity or price could not be read')
            continue
        condition, raw, qty, unit, total = match.groups()
        cleaned = ' '.join(raw.replace('<x>', '').split())
        row = dict(line_no=n, condition='N' if condition == 'New' else 'U', qty=qty, unit_price=unit, line_total=total, item_type=None, item_no=None,
                   color_id=None, colour_name=None, name=None, name_query=None, raw_text=raw, remark='', batch=batch, submitted=submitted)
        instr = re.match(r'^\(Instructions\) for Set ([A-Za-z0-9-]+)\b', cleaned)
        if instr:
            row.update(item_type='I', item_no=instr[1])
        else:
            rest = cleaned
            for name in ordered:
                if rest.lower().startswith(name + ' '):
                    row.update(color_id=colours[name], colour_name=rest[:len(name)])
                    rest = rest[len(name):].strip()
                    break
            row.update(name=rest, name_query=rest.lower())                 # exact names only; ambiguous or qualified ones stay for hand matching
            sticker = re.search(r'\(Stickers?\) - Set ([A-Za-z0-9-]+)', cleaned)
            if sticker:
                row['sticker_set_no'] = sticker[1]
        rows.append(row)
    date = None
    submitted = next((r['submitted'] for r in rows if r['submitted']), None)
    for form in ('%b %d, %Y %H:%M', '%b %d, %Y'):
        try:
            date = datetime.strptime(submitted, form).date().isoformat()
            break
        except (ValueError, TypeError):
            pass
    return rows, dict(currency='EUR', date_ordered=date)


def api_data(db, number):
    client = BrickLink(db)
    headers = client.list_orders()
    header = next((r for r in headers if str(r['order_id']) == str(number)), None)
    if header is None:
        raise ValueError('Order is not in your BrickLink purchases')
    groups = client.order_items(number)
    entries = [e for group in groups for e in group] if groups and isinstance(groups[0], list) else groups
    rows = []
    for n, e in enumerate(entries, 1):
        item = e['item']
        letter = TYPE_IDS.get(item['type'])
        rows.append(dict(line_no=n, item_type=letter, item_no=item['no'], name=item.get('name'),
                         color_id=e.get('color_id') if letter == 'P' else None, condition=e.get('new_or_used'), qty=e['quantity'],
                         unit_price=e.get('unit_price'), remark=e.get('remarks', ''), raw_text=json.dumps(e, sort_keys=True)))
    cost = header.get('cost') or {}
    return rows, dict(bricklink_order_id=str(number), store=header.get('store_name'), seller=header.get('seller_name'),
                      date_ordered=header.get('date_ordered'), status=header.get('status'), cost=cost.get('grand_total'), currency=cost.get('currency_code'))


# ---------- placing lines ----------

def _label(db, item_id):
    label = items.label(db, item_id)
    return dict(item_id=item_id, label=(label.text + ' · ' if label.number else '') + label.name)


def _place(db, letter, number, colour_key):
    """`(item id, colour id, suggestions, why)` for a BrickLink key through the pooled inverse. A key that names several items, or a colour
    that does, places nothing: the candidates are returned for the person to choose from."""
    colour = None
    if letter == 'P':
        if colour_key in (None, ''):
            return None, None, [], 'The line has no colour'
        try:
            colour = identity._inverse_color(db, 'bricklink', str(colour_key))
        except AmbiguousIdentity:
            return None, None, [], 'The BrickLink colour matches several colours'
        if colour is None:
            return None, None, [], 'The BrickLink colour is not known'
    try:
        found = identity.resolve_inverse(db, letter, number, str(colour_key) if letter == 'P' else None, exhaustive=True)
    except AmbiguousIdentity as exc:
        return None, colour, [_label(db, i) for i in exc.items[:10]], 'The BrickLink number matches several items'
    if found is None:                                  # a local BrickLink-born item is its own BrickLink key (`items.bricklink_key`)
        born = [r[0] for r in db.execute("SELECT id FROM main.item WHERE born_provider='bricklink' AND born_namespace=? AND born_key=? AND merged_into IS NULL ORDER BY id",
                                         (letter, number))]
        if len(born) > 1:
            return None, colour, [_label(db, i) for i in born[:10]], 'The BrickLink number matches several items'
        if born:
            return born[0], colour, [], None
        return None, colour, [], 'The BrickLink number is not in the catalogue'
    return found[0], found[1] if letter == 'P' else None, [], None


def _names(db, queries):
    """`{lower name: set of item ids}` for exact names, from the catalogue's names and the BrickLink item list when it is loaded."""
    wanted = json.dumps(sorted(queries))
    found = defaultdict(set)
    for r in db.execute('SELECT id,lower(name) AS n FROM main.item WHERE merged_into IS NULL AND lower(name) IN (SELECT value FROM json_each(?))', (wanted,)):
        found[r['n']].add(('item', r['id']))
    if has_catalogue(db):
        for r in db.execute('''SELECT id,lower(name) AS n FROM catalogue.item WHERE retired_at IS NULL AND id NOT IN (SELECT id FROM main.item)
                               AND lower(name) IN (SELECT value FROM json_each(?))''', (wanted,)):
            found[r['n']].add(('item', r['id']))
        for r in db.execute('SELECT item_type,item_no,lower(name) AS n FROM catalogue.bricklink_item WHERE lower(name) IN (SELECT value FROM json_each(?))', (wanted,)):
            found[r['n']].add(('bricklink', r['item_type'], r['item_no']))
    return found


def _by_name(db, row, hits):
    """`(item id, colour id, suggestions, why)` of an e-mail line from its exact name (and BrickLink colour name)."""
    colour = None
    if row.get('color_id') is not None:
        try:
            colour = identity._inverse_color(db, 'bricklink', str(row['color_id']))
        except AmbiguousIdentity:
            colour = None
    ids = set()
    for hit in hits:
        if hit[0] == 'item':
            ids.add(hit[1])
        else:
            try:
                found = identity.resolve_inverse(db, hit[1], hit[2], str(row['color_id']) if hit[1] == 'P' and row.get('color_id') is not None else None, exhaustive=True)
            except AmbiguousIdentity as exc:
                ids.update(exc.items)
                continue
            if found:
                ids.add(found[0])
    ids = {items._merged_target(db, i) for i in ids}
    if len(ids) == 1:
        item_id = next(iter(ids))
        kind = items.label(db, item_id).kind
        if kind == 'part' and colour is None:
            return None, None, [_label(db, item_id)], 'The colour name is not known'
        return item_id, colour if kind == 'part' else None, [], None
    if ids:
        return None, colour, [_label(db, i) for i in sorted(ids)[:10]], 'The name matches several items'
    return None, colour, [], 'No item has exactly this name'


def _sticker_set(db, number):
    found = [h for h in items.find(db, 'set', number, limit=20) if h['matched_by'] == 'born']
    return found[0]['item_id'] if len(found) == 1 else None


def _project(db, item_id, colour):
    """The item (and colour) in the collection: a line points at a row of the collection, not at the catalogue."""
    items.ensure(db, item_id)
    if colour is not None:
        identity.project_color(db, colour)


# ---------- importing ----------

def import_document(db, source, text='', *, choice='new', number=None, label=None, prepared=None):
    """Import one document as a draft. Returns `dict(order_id, document_id, duplicate, event_id, placed, unplaced)`: how many lines were
    placed on an item and how many wait for hand matching. The same document again answers `duplicate` and writes nothing."""
    if source not in ('email', 'xml', 'api'):
        raise ValueError('Choose email, XML or BrickLink')
    if source == 'api':
        if not re.fullmatch('[0-9]{1,12}', str(number or '')):
            raise ValueError('Use a BrickLink order number')
        raw, header = prepared if prepared is not None else api_data(db, number)
    else:
        if not isinstance(text, str) or not text.strip() or len(text.encode()) > 1024 * 1024:
            raise ValueError('Choose a document up to 1 MiB')
        raw, header = parse_email(db, text) if source == 'email' else parse_xml(text)
    if not raw:
        raise ValueError('No order lines were found')
    number = str(number or header.get('bricklink_order_id') or '').strip() or None
    if number and not re.fullmatch('[0-9]{1,12}', number):
        raise ValueError('Use a BrickLink order number')
    if number and header.get('bricklink_order_id') and str(header['bricklink_order_id']) != number:
        raise ValueError('The document belongs to another BrickLink order')
    body = json.dumps(raw, sort_keys=True) if source == 'api' else '\n'.join(l.strip() for l in text.splitlines() if l.strip())
    digest = hashlib.sha256(body.encode()).hexdigest()
    with transaction(db):
        existing = db.execute('SELECT order_id,id FROM main.order_document WHERE source=? AND digest=?', (source, digest)).fetchone()
        if existing:
            if choice != 'new' and int(choice) != existing['order_id']:
                raise ValueError('This document already belongs to another order')
            return dict(order_id=existing['order_id'], document_id=existing['id'], duplicate=True, event_id=None, placed=0, unplaced=0)
        stamp = stamp_now()
        journal = Journal(db)
        cost = price(header.get('cost'))
        if not header.get('currency'):
            cost = None                                                       # a price and its currency are stored together
        if choice == 'new':
            if number and db.execute('SELECT 1 FROM main.purchase_order WHERE bricklink_order_id=?', (number,)).fetchone():
                raise ValueError('This BrickLink order exists · choose it in Link to order')
            order_id = db.execute('''INSERT INTO main.purchase_order(bricklink_order_id,store,seller,date_ordered,status,cost,currency,created_at,updated_at)
                                     VALUES(?,?,?,?,?,?,?,?,?)''',
                                  (number, header.get('store'), header.get('seller'), header.get('date_ordered'), header.get('status'), cost,
                                   header.get('currency') if cost is not None else None, stamp, stamp)).lastrowid
            journal.created('purchase_order', order_id)
        else:
            order_id = int(choice)
            order = get(db, order_id)
            if number and order['bricklink_order_id'] not in (None, number):
                raise ValueError('The chosen order has another BrickLink number')
            if header.get('currency') and order['currency'] not in (None, header['currency']):
                raise ValueError('The currencies differ · choose another order')
            supplied = dict(header, bricklink_order_id=number, cost=cost)
            updates = {key: value for key, value in supplied.items() if key in ('bricklink_order_id', 'store', 'seller', 'date_ordered', 'status') and value is not None and order[key] is None}
            if order['cost'] is None and cost is not None and header.get('currency'):         # a price and its currency are stored together
                updates.update(cost=cost, currency=header['currency'])
            if updates:
                journal.touch('purchase_order', order_id)
                db.execute('UPDATE main.purchase_order SET ' + ','.join(key + '=?' for key in updates) + ',updated_at=? WHERE id=?', (*updates.values(), stamp, order_id))
        payload = json.dumps(dict(header=header, lines=raw) if source == 'api' else dict(text=text), sort_keys=True)
        db.execute("INSERT OR IGNORE INTO main.source_record(source,kind,key,payload,digest,bytes,job_id,fetched_at,status) VALUES('bricklink',?,?,?,?,?,NULL,?,'imported')",
                   ('order_document:' + source, digest, payload, hashlib.sha256(payload.encode()).hexdigest(), len(payload.encode()), stamp))
        record = db.execute("SELECT id FROM main.source_record WHERE source='bricklink' AND kind=? AND key=? ORDER BY id LIMIT 1", ('order_document:' + source, digest)).fetchone()[0]
        document_id = db.execute('''INSERT INTO main.order_document(order_id,source,digest,label,phase,raw_record_id,created_at,updated_at) VALUES(?,?,?,?,'draft',?,?,?)''',
                                 (order_id, source, digest, label or source, record, stamp, stamp)).lastrowid
        journal.created('order_document', document_id)
        queries = {r['name_query'] for r in raw if r.get('name_query')}
        named = _names(db, queries) if queries else {}
        placed = unplaced = 0
        for raw_row in raw:
            row = dict(raw_row)
            qty = add.quantity(row['qty'])
            condition = CONDITIONS.get(row.get('condition'))
            if condition is None:
                raise ValueError(f"Line {row['line_no']} · choose New or Used")
            unit = price(row.get('unit_price'))
            total = price(row.get('line_total')) if row.get('line_total') is not None else (format(Decimal(unit) * qty, 'f') if unit is not None else None)
            letter, number_ = row.get('item_type'), row.get('item_no')
            try:
                colour_key = int(row['color_id']) if row.get('color_id') not in (None, '') else None
            except (TypeError, ValueError):
                raise ValueError(f"Line {row['line_no']} · the colour must be a BrickLink colour number") from None
            if letter and number_:
                item_id, colour, suggestions, why = _place(db, letter, number_, colour_key)
            elif row.get('name_query'):
                item_id, colour, suggestions, why = _by_name(db, row, named.get(row['name_query'], ()))
            else:
                item_id, colour, suggestions, why = None, None, [], 'The line names no item'
            sticker = _sticker_set(db, row['sticker_set_no']) if row.get('sticker_set_no') else None
            if item_id is not None:
                _project(db, item_id, colour)
            if sticker is not None:
                items.ensure(db, sticker)
            placed += item_id is not None
            unplaced += item_id is None
            line_id = db.execute('''INSERT INTO main.order_line(order_id,document_id,line_no,raw_item_type,raw_item_no,raw_color_id,raw_color_name,raw_name,raw_text,remark,
                                    item_id,color_id,sticker_set_item_id,condition,state,qty,unit_price,line_total,batch,submitted,suggestions_json,updated_at)
                                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                                 (order_id, document_id, row['line_no'], letter, number_, colour_key, row.get('colour_name'), row.get('name'), row.get('raw_text'),
                                  row.get('remark') or '', item_id, colour, sticker, condition, 'matched' if item_id is not None else 'by_hand', qty, unit, total,
                                  row.get('batch'), row.get('submitted'), json.dumps(suggestions) if suggestions else None, stamp)).lastrowid
            journal.created('order_line', line_id)
        journal.context(order_id=order_id, document_id=document_id, lines=len(raw), placed=placed, unplaced=unplaced)
        event = journal.write('import', order_id)
        return dict(order_id=order_id, document_id=document_id, duplicate=False, event_id=event, placed=placed, unplaced=unplaced)


def match(db, order_id, line_id, *, item_id=None, color_id=None, item_type=None, item_no=None):
    """Place a draft line by hand: the item the person chose (an id from the catalogue search or a candidate), or a typed number that
    names exactly one item. A part needs its colour."""
    if item_id is not None:
        found = add.lookup(db, item_id)
        if not found:
            raise ValueError('Choose an identity from the catalogue')
        item_id, kind = found['item_id'], found['kind']
        via = 'search'
    else:
        try:
            kind = items.kind_of_type(str(item_type or '').upper())
        except errors.ValidationFailed:
            raise ValueError('Choose an item type') from None
        number = str(item_no or '').strip()
        if not add.NUMBER.fullmatch(number):
            raise ValueError('Choose an identity from the catalogue')
        item_id = add._pick(db, kind, number)
        if item_id is None:
            raise ValueError('Choose an identity from the catalogue')
        via = 'number'
    colour = int(color_id) if kind == 'part' and color_id not in (None, '') else None
    if kind == 'part' and (colour is None or not add._colour_known(db, colour)):
        raise ValueError('Choose a colour')
    with transaction(db):
        row = db.execute('SELECT l.*,d.phase FROM main.order_line l JOIN main.order_document d ON d.id=l.document_id WHERE l.id=? AND l.order_id=?', (line_id, order_id)).fetchone()
        if not row or row['phase'] != 'draft':
            raise ValueError('Reopen this document before matching lines')
        _project(db, item_id, colour)
        journal = Journal(db)
        journal.touch('order_line', line_id)
        db.execute("UPDATE main.order_line SET item_id=?,color_id=?,state='confirmed',confirmed_via=?,suggestions_json=NULL,updated_at=? WHERE id=?",
                   (item_id, colour, via, stamp_now(), line_id))
        journal.context(order_id=order_id, line_id=line_id, item_id=item_id)
        return journal.write('match', order_id)


def line_key(row):
    return row['item_id'], row['color_id'], row['condition']


def phase(db, order_id, document_id, action, pairs=None):
    transitions = {'review': ('draft', 'reviewed'), 'reopen': ('reviewed', 'draft'), 'save': ('reviewed', 'saved')}
    if action not in transitions:
        raise ValueError('Choose a document action')
    before, after = transitions[action]
    with transaction(db):
        doc = db.execute('SELECT * FROM main.order_document WHERE id=? AND order_id=?', (document_id, order_id)).fetchone()
        if not doc or doc['phase'] != before:
            raise ValueError('The document phase changed · review it again')
        journal = Journal(db)
        rows = lines(db, order_id)
        current = {r['id']: r for r in rows if r['document_id'] == document_id}
        if action == 'review' and any(r['state'] not in ('matched', 'confirmed') or r['item_id'] is None or (r['kind'] == 'part' and r['color_id'] is None)
                                      for r in current.values()):
            raise ValueError('Match each unresolved line before finishing the review')
        if action == 'save':
            existing = {r['id']: r for r in rows if r['phase'] == 'saved' and r['paired_line_id'] is None}
            pairs = {int(k): int(v) for k, v in (pairs or {}).items() if v not in ('', None)}
            if len(set(pairs.values())) != len(pairs):
                raise ValueError('Pair an existing line only once')
            for new, old in pairs.items():
                if new not in current or old not in existing or line_key(current[new]) != line_key(existing[old]):
                    raise ValueError('Pairs must share item, colour and condition')
                journal.touch('order_line', new)
                db.execute('UPDATE main.order_line SET paired_line_id=?,updated_at=? WHERE id=?', (old, stamp_now(), new))
        journal.touch('order_document', document_id)
        db.execute('UPDATE main.order_document SET phase=?,updated_at=? WHERE id=?', (after, stamp_now(), document_id))
        journal.context(order_id=order_id, document_id=document_id)
        return journal.write(action, order_id)


def received(db, order_id, counts):
    with transaction(db):
        current = {r['id']: r for r in lines(db, order_id) if r['phase'] == 'saved' and r['paired_line_id'] is None}
        journal = Journal(db)
        total = 0
        for key, value in counts.items():
            key = int(key)
            if not re.fullmatch('[0-9]{1,5}', str(value)):
                raise ValueError('Received count must be a whole number')
            value = int(value)
            row = current.get(key)
            if not row or not row['allocated'] <= value <= row['qty']:
                raise ValueError('Received count must be between allocated and ordered')
            if value == row['received']:
                continue
            stamp = stamp_now()
            journal.touch('line_receipt', key)
            db.execute('INSERT INTO main.line_receipt(line_id,received,updated_at) VALUES(?,?,?) ON CONFLICT(line_id) DO UPDATE SET received=excluded.received,updated_at=excluded.updated_at',
                       (key, value, stamp))
            journal.created('line_receipt_log', db.execute('INSERT INTO main.line_receipt_log(line_id,at,old,new) VALUES(?,?,?,?)', (key, stamp, row['received'], value)).lastrowid)
            total += value - row['received']
        journal.context(order_id=order_id, quantity=total)
        return journal.write('received', order_id)


def destinations(db, saved):
    """For each saved line, the copy gaps it could fill: the Workbench's gaps (a loose figure's own parts are not an order's concern),
    matched by item and colour, a booklet or box by the set's BrickLink number."""
    kinds = [r for r in saved if r.get('kind') in w.BOOKLET_KIND.values() and r['item_id'] is not None]
    numbers = w._booklet_numbers(db, kinds) if kinds else {}
    index = defaultdict(list)
    for gap in w.gaps(db):
        if gap['target'] != 'stock-part':
            index[gap['key']].append(gap)
    result = {}
    for r in saved:
        usable = r['state'] in ('matched', 'confirmed') and r['item_id'] is not None
        key = w.stock_key(dict(kind=r['kind'], item_id=r['item_id'], color_id=r['color_id']), numbers) if usable else None
        result[r['id']] = index.get(key, []) if usable and not (key[1] is None and r['kind'] in w.BOOKLET_KIND.values()) else []
    return result


def allocate(db, order_id, chosen):
    if not chosen or len(chosen) > 1000:
        raise ValueError('Choose up to 1000 allocations')
    with transaction(db):
        saved = {r['id']: r for r in lines(db, order_id) if r['phase'] == 'saved' and r['paired_line_id'] is None}
        journal = Journal(db)
        confirm = uuid4().hex
        affected, total = set(), 0
        for choice in chosen:
            line = saved.get(int(choice['line_id']))
            amount = add.quantity(choice['quantity'])
            if not line or line['state'] not in ('matched', 'confirmed') or line['item_id'] is None:
                raise ValueError('Match the line before allocating')
            if amount > line['received'] - line['allocated']:
                raise ValueError('Received quantity changed · review the allocation')
            target = choice['target_type']
            values = dict(confirm_id=confirm, order_id=order_id, line_id=line['id'], qty=amount, state='applied', created_at=stamp_now(), applied_at=stamp_now(),
                          target_kind=target, item_id=line['item_id'], color_id=line['color_id'])
            if target == 'copy':
                gap = w.requested_gap(db, dict(kind=line['kind'], item_id=line['item_id'], color_id=line['color_id']), choice['copy_id'], choice['target'], choice['target_id'])
                if not gap or amount > gap['need']:
                    raise ValueError('The copy gap changed · review the allocation')
                w.reduce_gap(db, journal, gap, amount, update_completeness=False)
                affected.add(gap['copy_id'])
                values.update(kind=GAP_KINDS[gap['target']], copy_id=gap['copy_id'], intent_before=gap['need'], intent_after=gap['need'] - amount,
                              copy_part_id=gap['target_id'] if gap['target'] == 'part' else None,
                              copy_figure_id=gap['target_id'] if gap['target'] == 'figure' else None)
            elif target == 'stock':
                storage = choice.get('storage_id') or None
                lot = choice.get('lot_id') or None
                if storage:
                    from .ledger import require_storage
                    require_storage(db, storage)
                if lot and not db.execute('SELECT 1 FROM main.lot WHERE id=? AND archived_at IS NULL', (lot,)).fetchone():
                    raise ValueError('Lot is unavailable')
                change = stock_module.add_loose(db, item_id=line['item_id'], color_id=line['color_id'], quantity=amount, condition=line['condition'],
                                                storage_id=storage, lot_id=lot)
                w._note_added(journal, change)
                values.update(stock_id=change['id'], kind={'minifigure': 'loose_figure', 'part': 'loose_part'}.get(line['kind'], 'loose_other'))
            else:
                raise ValueError('Choose a copy gap or loose stock')
            journal.created('allocation', db.execute(f'INSERT INTO main.allocation({",".join(values)}) VALUES({",".join("?" * len(values))})', tuple(values.values())).lastrowid)
            line['allocated'] += amount
            total += amount
        for copy_id in sorted(affected):
            w._recompute(db, journal, copy_id)
        journal.guard(*affected)
        journal.context(order_id=order_id, quantity=total)
        return journal.write('allocate', order_id)


def reconcile(db, order_id):
    with transaction(db):
        data = detail(db, order_id)
        if not data['saved'] or any(r['state'] == 'held' or r['received'] != r['allocated'] for r in data['saved']) or any(d['phase'] in ('draft', 'reviewed') for d in data['documents']):
            raise ValueError('Finish reviews and allocate every received piece before reconciling')
        journal = Journal(db)
        journal.touch('purchase_order', order_id)
        db.execute("UPDATE main.purchase_order SET status='Reconciled',updated_at=? WHERE id=?", (stamp_now(), order_id))
        journal.context(order_id=order_id)
        return journal.write('reconcile', order_id)


def hold(db, order_id, line_id, held):
    if type(held) is not bool:
        raise ValueError('Choose hold or release')
    with transaction(db):
        row = next((r for r in lines(db, order_id) if r['id'] == line_id and r['phase'] == 'saved' and r['paired_line_id'] is None), None)
        if not row or row['state'] not in ('matched', 'confirmed', 'held'):
            raise ValueError('Choose a matched saved line')
        journal = Journal(db)
        journal.touch('order_line', line_id)
        db.execute('UPDATE main.order_line SET state=?,updated_at=? WHERE id=?', ('held' if held else 'confirmed', stamp_now(), line_id))
        journal.context(order_id=order_id, line_id=line_id)
        return journal.write('hold' if held else 'release', order_id)


def short_export(db, order_id):
    """The BrickLink wanted-list XML of what is still short: `dict(xml, skipped)`. A line the BrickLink key cannot name (no confirmed number
    or colour) is left out and listed."""
    get(db, order_id)
    root = ET.Element('INVENTORY')
    skipped = []
    for r in lines(db, order_id):
        if r['phase'] != 'saved' or r['paired_line_id'] is not None or r['received'] >= r['qty']:
            continue
        try:
            letter, number, colour = items.bricklink_key(db, r['item_id'], r['color_id'])
        except errors.Unidentified:
            skipped.append(dict(line_no=r['line_no'], raw_item_no=r['raw_item_no'], why='no BrickLink number'))
            continue
        if r['color_id'] is not None and colour is None:
            skipped.append(dict(line_no=r['line_no'], raw_item_no=r['raw_item_no'], why='no BrickLink colour'))
            continue
        item = ET.SubElement(root, 'ITEM')
        for key, value in (('ITEMTYPE', letter), ('ITEMID', number), ('COLOR', colour if letter == 'P' else None), ('MINQTY', r['qty'] - r['received']),
                           ('CONDITION', LETTERS.get(r['condition']))):
            if value is not None:
                ET.SubElement(item, key).text = str(value)
    return dict(xml=ET.tostring(root, encoding='unicode'), skipped=skipped)


def short_xml(db, order_id):
    return short_export(db, order_id)['xml']


def allocation_review(db, order_id):
    get(db, order_id)
    saved = [r for r in decorate_lines(db, lines(db, order_id)) if r['phase'] == 'saved' and r['paired_line_id'] is None]
    where = destinations(db, saved)
    return [dict(id=r['id'], line=r, available=r['received'] - r['allocated'], destinations=where[r['id']]) for r in saved]


def allocation_history(db, order_id):
    get(db, order_id)
    return allocation_rows(db, order_id, decorate_lines(db, lines(db, order_id)))


def retry_allocations(db, order_id, chosen):
    # Allocations are atomic: a failed confirm has no pending effects to resume.
    # A client retries its reviewed choices against the current counts and gaps.
    return allocate(db, order_id, chosen)


# ---------- undo ----------

def _current(db, table, rows):
    key = KEYS.get(table, 'id')
    return [dict(r) for r in db.execute(f'SELECT * FROM main.{table} WHERE {key} IN (SELECT value FROM json_each(?)) ORDER BY {key}',
                                       (json.dumps([r[key] for r in rows]),))]


def _undo(db, event, via, actor):
    """Put an order save back. Refused whole when an order row, a copy's status or any row the save changed differs from what it left."""
    before, after = json.loads(event['old_value']), json.loads(event['new_value'])
    pairs = list(zip(before, after))
    mine = [(o, n) for o, n in pairs if n['table'] in ORDER_TABLES]
    for old, new in mine:
        if _current(db, new['table'], new['rows']) != new['rows']:
            raise ValueError(CHANGED)
    for old, new in pairs:
        if new['table'] == 'guard' and copy_guard(db, [g['id'] for g in new['rows']]) != new['rows']:
            raise ValueError('The copy status changed after saving · review it before undoing')
    tables = {n['table']: (o, n) for o, n in mine}
    if 'line_receipt' in tables:                                     # a count cannot be taken back below what is allocated
        old, new = tables['line_receipt']
        was = {r['line_id']: r['received'] for r in old['rows']}
        for row in new['rows']:
            live = db.execute(f'SELECT coalesce(sum(qty),0) FROM main.allocation WHERE line_id=? AND state IN {LIVE}', (row['line_id'],)).fetchone()[0]
            if live > was.get(row['line_id'], 0):
                raise ValueError('Undo the allocations before the received count')
    if 'order_document' in tables:
        old, new = tables['order_document']
        was = {r['id']: r['phase'] for r in old['rows']}
        documents = sorted({r['id'] for r in new['rows'] if was.get(r['id']) != 'saved'})
        if documents:
            marks = json.dumps(documents)
            if db.execute(f'''SELECT 1 FROM main.allocation a JOIN main.order_line l ON l.id=a.line_id WHERE l.document_id IN (SELECT value FROM json_each(?))
                             AND a.state IN {LIVE}''', (marks,)).fetchone():
                raise ValueError('Undo allocations before undoing the document')
            if db.execute('''SELECT 1 FROM main.line_receipt r JOIN main.order_line l ON l.id=r.line_id WHERE l.document_id IN (SELECT value FROM json_each(?))
                             AND r.received>0''', (marks,)).fetchone():
                raise ValueError('Undo received counts before undoing the document')
            if db.execute('''SELECT 1 FROM main.order_line p JOIN main.order_line l ON l.id=p.paired_line_id JOIN main.order_document d ON d.id=p.document_id
                             WHERE l.document_id IN (SELECT value FROM json_each(?)) AND d.phase='saved' AND p.document_id NOT IN (SELECT value FROM json_each(?))''',
                          (marks, marks)).fetchone():
                raise ValueError('Undo the paired document first')
    if event['field'] == 'match' and 'order_line' in tables:                 # a match only comes back while the line is still in a draft
        marks = json.dumps([r['id'] for r in tables['order_line'][1]['rows']])
        if db.execute("""SELECT 1 FROM main.order_line l JOIN main.order_document d ON d.id=l.document_id WHERE l.id IN (SELECT value FROM json_each(?))
                         AND d.phase!='draft'""", (marks,)).fetchone():
            raise ValueError('Reopen the document before undoing a match')
        if db.execute(f"""SELECT 1 FROM main.allocation WHERE line_id IN (SELECT value FROM json_each(?)) AND state IN {LIVE}
                          UNION ALL SELECT 1 FROM main.line_receipt WHERE line_id IN (SELECT value FROM json_each(?)) AND received>0""", (marks, marks)).fetchone():
            raise ValueError('Undo the counts and allocations before undoing a match')
    rest = [(o, n) for o, n in pairs if n['table'] not in ORDER_TABLES and n['table'] != 'guard']
    stamp = stamp_now()
    for old, new in reversed(mine):
        table, key = new['table'], KEYS.get(new['table'], 'id')
        was = {r[key]: r for r in old['rows']}
        for row in new['rows']:
            previous = was.get(row[key])
            if previous is not None:
                names = [c for c in previous if c != key]
                db.execute(f'UPDATE main.{table} SET ' + ','.join(c + '=?' for c in names) + f' WHERE {key}=?', (*[previous[c] for c in names], row[key]))
            elif table == 'order_document':
                db.execute("UPDATE main.order_document SET phase='undone',updated_at=? WHERE id=?", (stamp, row['id']))
            elif table == 'allocation':
                db.execute("UPDATE main.allocation SET state='undone',undone_at=? WHERE id=?", (stamp, row['id']))
            elif table == 'line_receipt':
                db.execute('UPDATE main.line_receipt SET received=0,updated_at=? WHERE line_id=?', (stamp, row['line_id']))
            # An imported order, its lines, the raw record and the receipt log stay: undo deactivates the document, never erases it.
    return collection._undo_collection(db, dict(event, old_value=json.dumps([o for o, _ in rest]), new_value=json.dumps([n for _, n in rest])), via, actor)


for _field in ('import', 'match', 'review', 'reopen', 'save', 'received', 'allocate', 'hold', 'release', 'reconcile'):
    undoing.register(ENTITY, _field, _undo)


def undo(db, event_id):
    """Undo an order save by its event id; a second Undo of the same save does nothing."""
    row = db.execute('SELECT entity_kind FROM main.event WHERE id=?', (int(event_id),)).fetchone()
    if row is None or row['entity_kind'] != ENTITY:
        raise ValueError('Save is unavailable')
    return undoing.undo_event(db, int(event_id), via='app')


def undo_history(db, event_id):
    """Undo from the order's history list; a save already undone says so."""
    with transaction(db):
        if undo(db, event_id)['already_undone']:
            raise ValueError('This save has already been undone')
