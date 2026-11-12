"""Sets versus a pile of parts (#199): one read-only scoring engine over the catalogue's inventories.

Given a parts multiset `{(item id, colour id): quantity}` (a figure is `(item id, None)`), the engine ranks the catalogue's sets by how
much of the pile each set explains. Features built on it (set detection in a lot, Buildable sets) call `score`; nothing here writes.

Three layers, so the scale test and the benchmark can use the middle one without a database:

* the loader (`load_rows`) reads the attached `catalogue` file into plain rows;
* `build_index(rows)` turns rows into inverted lists: per (part, colour), the sets whose inventory holds it with the quantity, kept as
  two `array('I')` per key in set order. A query touches only the sets that share a part with the input;
* `rank` / `page` score an input against an index.

Semantics (ADR 0026):

* A candidate is a set item with a live latest inventory (`is_latest`, not retired) that has at least one line. Spare lines are left out
  (ADR 0011). A figure counts twice over: its own inventory's parts are lines of the set (quantity times the figure's quantity in the
  set) and the figure itself is a whole line `(figure, None)`. They are separate lines of the set, so a loose figure and a loose pile of
  its parts each give their own evidence, and a set's line and quantity totals count both. A sub-set (`inventory_set`) is expanded into
  its parent with its quantity multiplied, recursively, with a cycle guard.
* Rarity weight of a line: `w = ln(N / df)`, N the number of candidate sets, df the number of candidate sets that hold the line.
  A line every set holds weighs 0; a line in two sets of 25,000 weighs about 9.4.
* Per set: `evidence = sum over matched lines of w * min(have, need) / need`; `coverage = evidence / sum of w over all the set's lines`.
  The ranking is by `evidence`, ties by `coverage`, then by set id.
* **Stickers** (#201): a line flagged `Sticker` is a hint that the print on the part comes from a sticker sheet, and the catalogue does not say which
  part a sticker goes on. An *unconfirmed* sticker raises, for each set that holds the line and a sticker sheet (a part of the category named
  `Stickers`), that line's evidence by `HINT_FACTOR - 1` (a quarter): the line then counts 1.25 times its own weight, never more than 1.5. A *confirmed*
  sticker (the person chose the set; `sticker:<set item id>` joins the line's flags) is near-certain evidence for that set: the line's evidence for it is
  `CONFIRMED_FACTOR` times `ln N`, the largest weight any line can carry (one set holds it), instead of its own share; the other sets get nothing extra
  from that line. The adjustment is applied after the cached ranking (`apply_stickers`), so the cache key stays the parts.
* Swaps (the same part in another colour, an alternate mould by `part_relationship` types A and M, in either direction) are listed per
  returned set, from what the exact match left over, and never enter any number above.
"""
from array import array
from collections import OrderedDict, defaultdict
import hashlib
import json
import math
import os
import threading

DISTINCTIVE_MAX = 25            # a line held by at most this many candidate sets is "distinctive"
STICKER_CATEGORY = 'Stickers'   # the part category whose items are sticker sheets, found by name (ids differ between catalogues)
STICKER_FLAG = 'sticker'        # a stock flag named Sticker (any case) is read as this
CONFIRMED_PREFIX = 'sticker:'   # a confirmed sticker adds `sticker:<set item id>` to the line's flags
HINT_FACTOR = 1.25              # an unconfirmed sticker: the line counts this many times its own weight in a set with a sticker sheet (at most 1.5)
CONFIRMED_FACTOR = 2.0          # a confirmed sticker: the line's evidence for the chosen set is this times ln N
ALTERNATE_TYPES = ('A', 'M')    # part_relationship types read as an alternate mould (Rebrickable: A alternate, M mold variation)
MAX_LIMIT = 500
MAX_DETAIL = 100
CACHE_SIZE = 8                  # ranked results kept per process
UNMATCHED_SHOWN = 50
SWAPS_SHOWN = 20

_SHIFT = 32                     # a line key is `item << 32 | colour` (colour 0: a figure or any line without a colour)


def key_of(item_id, colour_id):
    return (int(item_id) << _SHIFT) | int(colour_id or 0)


def unkey(key):
    return key >> _SHIFT, (key & ((1 << _SHIFT) - 1)) or None


# ---------- layer 1: the loader ----------

class Rows:
    """What the index is built from; plain Python values, so a test or the benchmark can make them without a catalogue."""
    __slots__ = ('sets', 'figures', 'subsets', 'figure_parts', 'relations', 'key', 'stickers')

    def __init__(self, sets, figures=(), subsets=(), figure_parts=(), relations=(), key=None, stickers=()):
        self.sets = sets                # iterable of (set item id, [(part, colour, quantity), ...]) of the set's own parts
        self.figures = figures          # iterable of (set item id, figure item id, quantity)
        self.subsets = subsets          # iterable of (parent set item id, child set item id, quantity)
        self.figure_parts = figure_parts    # iterable of (figure item id, [(part, colour, quantity), ...])
        self.relations = relations      # iterable of (rel_type, child part, parent part)
        self.key = key
        self.stickers = stickers        # iterable of the item ids of sticker sheets


def build_key(db):
    """What names the attached catalogue build: its id space, its newest build, the file's stamp and the collection's activations.
    A rebuild, a new download or a swapped file changes it."""
    meta = {r[0]: r[1] for r in db.execute("SELECT key,value FROM catalogue.meta WHERE key IN ('catalogue_id','created_at')")}
    newest = db.execute('SELECT max(id),max(finished_at),count(*) FROM catalogue.build').fetchone()
    file = next((r[2] for r in db.execute('PRAGMA database_list') if r[1] == 'catalogue'), '')
    try:
        stamp = os.stat(file)
        stamp = (stamp.st_mtime_ns, stamp.st_size)
    except OSError:
        stamp = None
    try:
        active = tuple(db.execute('SELECT max(id),count(*) FROM main.catalogue_build').fetchone())
    except Exception:           # the benchmark opens the catalogue alone
        active = None
    return (file, meta.get('catalogue_id'), meta.get('created_at'), tuple(newest), stamp, active)


def load_rows(db):
    """The catalogue's set and figure inventories (latest, live, spares left out) as `Rows`. `db` has the file attached as `catalogue`."""
    cur = db.cursor()
    cur.row_factory = None
    sets = {r[0]: [] for r in cur.execute(
        """SELECT i.item_id FROM catalogue.inventory i JOIN catalogue.item t ON t.id=i.item_id
           WHERE i.is_latest=1 AND i.retired_at IS NULL AND t.retired_at IS NULL AND t.kind='set'""")}
    figures = [tuple(r) for r in cur.execute(
        """SELECT i.item_id,f.item_id,f.quantity FROM catalogue.inventory i JOIN catalogue.inventory_figure f ON f.inventory_id=i.id
           WHERE i.is_latest=1 AND i.retired_at IS NULL""") if r[0] in sets]
    subsets = [tuple(r) for r in cur.execute(
        """SELECT i.item_id,s.item_id,s.quantity FROM catalogue.inventory i JOIN catalogue.inventory_set s ON s.inventory_id=i.id
           WHERE i.is_latest=1 AND i.retired_at IS NULL""") if r[0] in sets and r[1] in sets]
    wanted = {f[1] for f in figures}
    figure_parts = defaultdict(list)
    for fig, part, colour, quantity in cur.execute(
            """SELECT i.item_id,p.item_id,p.color_id,p.quantity FROM catalogue.inventory i
               JOIN catalogue.item t ON t.id=i.item_id AND t.kind='minifigure'
               JOIN catalogue.inventory_part p ON p.inventory_id=i.id
               WHERE i.is_latest=1 AND i.retired_at IS NULL AND p.is_spare=0"""):
        if fig in wanted:
            figure_parts[fig].append((part, colour, quantity))
    for inventory_item, part, colour, quantity in cur.execute(
            """SELECT i.item_id,p.item_id,p.color_id,p.quantity FROM catalogue.inventory i
               JOIN catalogue.item t ON t.id=i.item_id AND t.kind='set'
               JOIN catalogue.inventory_part p ON p.inventory_id=i.id
               WHERE i.is_latest=1 AND i.retired_at IS NULL AND t.retired_at IS NULL AND p.is_spare=0"""):
        sets[inventory_item].append((part, colour, quantity))
    relations = [tuple(r) for r in cur.execute(
        f"SELECT rel_type,child_item_id,parent_item_id FROM catalogue.part_relationship WHERE rel_type IN ({','.join('?' * len(ALTERNATE_TYPES))})",
        ALTERNATE_TYPES)]
    stickers = [r[0] for r in cur.execute(
        '''SELECT i.id FROM catalogue.item i JOIN catalogue.part_category c ON c.id=i.category_id
           WHERE i.kind='part' AND i.retired_at IS NULL AND c.name=?''', (STICKER_CATEGORY,))]
    return Rows(sets.items(), figures, subsets, figure_parts.items(), relations, build_key(db), stickers)


# ---------- layer 2: the index ----------

class Index:
    """Inverted lists over the candidate sets of one catalogue build."""

    def __init__(self):
        self.key = None
        self.set_item = array('I')      # position -> set item id
        self.set_lines = array('I')     # distinct lines of the set (parts in a colour, plus whole figures)
        self.set_quantity = array('Q')  # pieces of the set over those lines
        self.set_weight = array('d')    # sum of w over the set's lines
        self.set_distinctive = array('I')
        self.set_keys = []              # position -> array of the set's line keys, and
        self.set_needs = []             # position -> array of their quantities (the forward side: a page reads its sets' lines from here)
        self.posting = {}               # key -> (array of set positions, array of quantities), positions ascending
        self.weight = {}                # key -> w
        self.alternates = {}            # part id -> part ids it swaps with as another mould
        self.position = {}              # set item id -> position
        self.set_sticker = array('B')   # position -> 1 when the set holds a sticker sheet (a part of the Stickers category)
        self.total = 0                  # N, the candidate sets

    def describe(self):
        return dict(sets=self.total, lines=len(self.posting), postings=sum(len(p[0]) for p in self.posting.values()),
                    distinctive_max=DISTINCTIVE_MAX)


def _resolve(item, own, children, memo, trail):
    """A set's lines: its own plus every sub-set's times the quantity (recursive). A cycle is cut at the edge that closes it, so the set that
    refers back adds nothing; a result that had an edge cut is not memoised, since it depends on where the walk started. Returns `(lines, cut)`."""
    if item in memo:
        return memo[item], False
    if item in trail:
        return {}, True
    lines = dict(own.get(item, {}))
    cut = False
    for child, quantity in children.get(item, ()):
        sub, sub_cut = _resolve(child, own, children, memo, trail | {item})
        cut = cut or sub_cut
        for key, amount in sub.items():
            lines[key] = lines.get(key, 0) + amount * quantity
    if not cut:
        memo[item] = lines
    return lines, cut


def build_index(rows):
    """`Index` from `Rows`. Memory is two small arrays per line, not a tuple per posting."""
    index = Index()
    index.key = rows.key
    figure_parts = dict(rows.figure_parts)
    figures = defaultdict(list)
    for set_id, figure, quantity in rows.figures:
        figures[set_id].append((figure, quantity))
    children = defaultdict(list)
    for parent, child, quantity in rows.subsets:
        children[parent].append((child, quantity))
    own = {}
    for set_id, parts in rows.sets:
        lines = {}
        for part, colour, quantity in parts:
            k = key_of(part, colour)
            lines[k] = lines.get(k, 0) + quantity
        for figure, quantity in figures.get(set_id, ()):
            k = key_of(figure, None)
            lines[k] = lines.get(k, 0) + quantity                       # the whole figure ...
            for part, colour, amount in figure_parts.get(figure, ()):   # ... and its parts, each a line of the set
                k = key_of(part, colour)
                lines[k] = lines.get(k, 0) + amount * quantity
        own[set_id] = lines
    memo = {}
    postings = {}
    for set_id in sorted(own):
        lines = _resolve(set_id, own, children, memo, frozenset())[0] if set_id in children else own[set_id]
        if not lines:
            continue
        position = len(index.set_item)
        index.position[set_id] = position
        index.set_item.append(set_id)
        index.set_lines.append(len(lines))
        index.set_quantity.append(sum(lines.values()))
        index.set_keys.append(array('Q', lines))
        index.set_needs.append(array('I', lines.values()))
        for k, quantity in lines.items():
            slot = postings.get(k)
            if slot is None:
                slot = postings[k] = (array('I'), array('I'))
            slot[0].append(position)
            slot[1].append(quantity)
    index.posting = postings
    index.total = n = len(index.set_item)
    index.set_sticker = array('B', [0]) * n
    sheets = set(rows.stickers)
    if sheets:
        for k, (positions, _) in postings.items():
            if k >> _SHIFT in sheets:
                for position in positions:
                    index.set_sticker[position] = 1
    index.set_weight = array('d', [0.0]) * n
    index.set_distinctive = array('I', [0]) * n
    weight = index.weight
    for k, (positions, _) in postings.items():
        df = len(positions)
        w = weight[k] = math.log(n / df)
        distinctive = df <= DISTINCTIVE_MAX
        for position in positions:
            index.set_weight[position] += w
            if distinctive:
                index.set_distinctive[position] += 1
    for _, child, parent in rows.relations:
        index.alternates.setdefault(child, set()).add(parent)
        index.alternates.setdefault(parent, set()).add(child)
    return index


_INDEXES = {}
_LOCK = threading.Lock()


def index_for(db):
    """The index of the attached catalogue, built once per catalogue build and process (a new build replaces it)."""
    key = build_key(db)
    with _LOCK:
        held = _INDEXES.get(key[0])
        if held is not None and held.key == key:
            return held, False
        index = build_index(load_rows(db))
        _INDEXES[key[0]] = index
        _RESULTS.clear()
        return index, True


# ---------- layer 3: scoring ----------

_RESULTS = OrderedDict()        # (build key, input digest) -> ranked rows


def digest(parts):
    h = hashlib.sha1()
    for k in sorted(parts):
        h.update(f'{k}:{parts[k]};'.encode())
    return h.hexdigest()


def clean(parts):
    """`{line key: quantity}` from `{(item id, colour id or None): quantity}`; a quantity below 1 is no line."""
    lines = {}
    for (item, colour), quantity in dict(parts).items():
        quantity = int(quantity)
        if quantity < 0:
            raise ValueError('A quantity is a whole number from 0')
        if quantity:
            k = key_of(item, colour)
            lines[k] = lines.get(k, 0) + quantity
    return lines


def rank(index, lines):
    """`(ranked rows, matched line count)`: one `(position, evidence, covered quantity, covered lines, complete lines, distinctive found)`
    per set that shares a line with the input, best first."""
    n = index.total
    evidence, quantity, covered, complete, distinctive = [0.0] * n, [0] * n, [0] * n, [0] * n, [0] * n
    weight, matched = index.weight, 0
    for k, have in lines.items():
        found = index.posting.get(k)
        if found is None:
            continue
        matched += 1
        w = weight[k]
        rare = len(found[0]) <= DISTINCTIVE_MAX
        for position, need in zip(*found):
            if have >= need:
                take = need
                complete[position] += 1
                evidence[position] += w
            else:
                take = have
                evidence[position] += w * have / need
            quantity[position] += take
            covered[position] += 1
            if rare:
                distinctive[position] += 1
    set_weight, item = index.set_weight, index.set_item
    rows = [(p, evidence[p], quantity[p], covered[p], complete[p], distinctive[p]) for p in range(n) if covered[p]]
    rows.sort(key=lambda r: (-r[1], -(r[1] / set_weight[r[0]] if set_weight[r[0]] else 0.0), item[r[0]]))
    return rows, matched


def _line_of(k, have, need=None, w=None, flags=None):
    item, colour = unkey(k)
    body = {'item_id': item, 'color_id': colour, 'quantity': have}
    if need is not None:
        body.update(need=need, covered=min(have, need), weight=round(w, 4))
    if flags:
        body['flags'] = sorted(flags)
    return body


def _swaps(index, position, lines, needs, by_item):
    """What the exact match leaves over, listed as swaps: the same part in another colour, or an alternate mould in the same colour.
    A swap uses the input line's leftover (its quantity less what this set takes of it) against the set's unmet need; the same input
    line may appear in several swaps, none of them is taken from the numbers of the set. `needs` is the set's `{line key: quantity}`,
    `by_item` the pile's `{item id: [(colour, line key, quantity)]}`."""
    found = []

    def offer(kind, target, gap, other, key, have):
        spare = have - min(have, needs.get(key, 0))
        if spare > 0:
            found.append((kind, key, target, min(gap, spare)))

    for target, need in needs.items():
        gap = need - min(lines.get(target, 0), need)
        item, colour = unkey(target)
        if gap <= 0 or colour is None:
            continue
        for other, key, have in by_item.get(item, ()):
            if other != colour:
                offer('colour', target, gap, other, key, have)
        for alternate in index.alternates.get(item, ()):
            for other, key, have in by_item.get(alternate, ()):
                if other == colour:
                    offer('mould', target, gap, other, key, have)
    found.sort(key=lambda s: (-s[3] * index.weight.get(s[2], 0.0), s[0], s[1], s[2]))
    items = [dict(kind=kind, have=_line_of(k, lines[k]), wanted=_line_of(t, needs[t]), quantity=q) for kind, k, t, q in found[:SWAPS_SHOWN]]
    return dict(lines=len(found), quantity=sum(s[3] for s in found), items=items)


def by_item_of(lines):
    found = defaultdict(list)
    for k, have in lines.items():
        item, colour = unkey(k)
        found[item].append((colour, k, have))
    return found


def _detail(index, row, lines, flags, detail, by_item=None, stickers=None):
    position, ev, quantity, covered, complete, distinctive = row
    needs = dict(zip(index.set_keys[position], index.set_needs[position]))
    seen, by_flag = [], {}
    for k, need in needs.items():
        have = lines.get(k)
        if not have:
            continue
        w = index.weight[k]
        share = w * min(have, need) / need
        if stickers and k in stickers:
            share += sticker_extra(index, position, share, stickers[k])
        seen.append((share, k, have, need, w))
        for flag in (flags or {}).get(k, ()):
            slot = by_flag.setdefault(flag, dict(lines=0, covered_quantity=0, evidence=0.0))
            slot['lines'] += 1
            slot['covered_quantity'] += min(have, need)
            slot['evidence'] += share
    seen.sort(key=lambda s: (-s[0], s[1]))
    total = index.set_weight[position]
    return dict(set_item_id=index.set_item[position], evidence=round(ev, 4), coverage=round(min(1.0, ev / total), 4) if total else 0.0,
                covered_quantity=quantity, set_quantity=index.set_quantity[position], covered_lines=covered, complete_lines=complete,
                set_lines=index.set_lines[position], distinctive_found=distinctive, distinctive_total=index.set_distinctive[position],
                matched=[_line_of(k, have, need, w, (flags or {}).get(k)) for _, k, have, need, w in seen[:detail]],
                flags={f: dict(v, evidence=round(v['evidence'], 4)) for f, v in sorted(by_flag.items())},
                swaps=_swaps(index, position, lines, needs, by_item if by_item is not None else by_item_of(lines)))


def marks_of(lines, flags):
    """`{line key: {flag name, ...}}` for the flags that sit on a line of the (cleaned) input (a sticker confirmation, `sticker:<id>`, is not a flag a
    person sees: `stickers_of` reads it)."""
    marks = defaultdict(set)
    for (item, colour), names in (flags or {}).items():
        if key_of(item, colour) in lines:
            marks[key_of(item, colour)].update(n for n in names if not n.startswith(CONFIRMED_PREFIX))
    return {k: v for k, v in marks.items() if v}


def stickers_of(lines, flags):
    """`{line key: frozenset of the set item ids the sticker is confirmed for}` for the lines flagged Sticker (the empty set: not chosen yet)."""
    found = {}
    for (item, colour), names in (flags or {}).items():
        k = key_of(item, colour)
        if k in lines and any(n.casefold() == STICKER_FLAG for n in names):
            confirmed = {int(n[len(CONFIRMED_PREFIX):]) for n in names if n.startswith(CONFIRMED_PREFIX) and n[len(CONFIRMED_PREFIX):].isdigit()}
            found[k] = frozenset(found.get(k, frozenset()) | confirmed)
    return found


def sticker_extra(index, position, share, confirmed):
    """What a sticker-flagged line adds to a set's evidence on top of its own `share` there (can be negative: a confirmed sticker replaces the share)."""
    if confirmed:
        if index.set_item[position] in confirmed:
            return CONFIRMED_FACTOR * math.log(max(index.total, 2)) - share
        return 0.0
    return share * (HINT_FACTOR - 1) if index.set_sticker[position] else 0.0


def apply_stickers(index, ranked, lines, stickers):
    """The ranked rows with the sticker evidence added and sorted again (the cached ranking itself is never changed)."""
    if not stickers:
        return ranked
    extra = defaultdict(float)
    for k, confirmed in stickers.items():
        found = index.posting.get(k)
        if found is None:
            continue
        have, w = lines[k], index.weight[k]
        for position, need in zip(*found):
            extra[position] += sticker_extra(index, position, w * min(have, need) / need, confirmed)
    if not any(extra.values()):
        return ranked
    set_weight, item = index.set_weight, index.set_item
    rows = [(r[0], r[1] + extra.get(r[0], 0.0), *r[2:]) for r in ranked]
    rows.sort(key=lambda r: (-r[1], -(r[1] / set_weight[r[0]] if set_weight[r[0]] else 0.0), item[r[0]]))
    return rows


def ranking(db, lines):
    """`(index, (ranked rows, matched line count), index built now, ranking from the cache)` for cleaned input lines: the whole ranking, not a
    page, so a caller that filters the sets itself (candidate sets, #200) can page after it. Cached per catalogue build and input."""
    index, built = index_for(db)
    token = (index.key, digest(lines))
    with _LOCK:
        held = _RESULTS.get(token)
        if held is not None:
            _RESULTS.move_to_end(token)
    cached = held is not None
    if not cached:
        held = rank(index, lines)
        with _LOCK:
            _RESULTS[token] = held
            while len(_RESULTS) > CACHE_SIZE:
                _RESULTS.popitem(last=False)
    return index, held, built, cached


def score(db, parts, flags=None, *, limit=20, offset=0, detail=10):
    """The ranked sets for a parts multiset, `dict(catalogue, input, total, limit, offset, cached, results)`.

    `parts` is `{(item id, colour id or None): quantity}`; `flags` optionally `{(item id, colour id or None): {flag name, ...}}`, passed
    through to each set's matched lines and summed per flag. Results are cached per input and catalogue build (the ranking; the page's
    detail is rebuilt, it is cheap). Read-only."""
    if not 1 <= limit <= MAX_LIMIT or offset < 0 or not 0 <= detail <= MAX_DETAIL:
        raise ValueError(f'limit is 1 to {MAX_LIMIT}, offset from 0, detail 0 to {MAX_DETAIL}')
    lines = clean(parts)
    marks = marks_of(lines, flags)
    stickers = stickers_of(lines, flags)
    index, held, built, cached = ranking(db, lines)
    ranked, matched = held
    ranked = apply_stickers(index, ranked, lines, stickers)
    grouped = by_item_of(lines)
    unmatched = [k for k in lines if k not in index.posting]
    return dict(catalogue=index.describe(),
                input=dict(lines=len(lines), quantity=sum(lines.values()), matched_lines=matched, unmatched_lines=len(unmatched),
                           unmatched=[_line_of(k, lines[k]) for k in sorted(unmatched)[:UNMATCHED_SHOWN]]),
                total=len(ranked), limit=limit, offset=offset, cached=cached, index_built=built,
                results=[dict(rank=offset + i + 1, **_detail(index, row, lines, marks, detail, grouped, stickers)) for i, row in enumerate(ranked[offset:offset + limit])])


# ---------- builders of the input ----------

def _gather(rows):
    parts, flags = {}, defaultdict(set)
    for item, colour, quantity, kind, names, confirmed in rows:
        k = (item, None if kind == 'minifigure' else (colour or 1))
        parts[k] = parts.get(k, 0) + quantity
        if names:
            flags[k].update(names.split('\x1f'))
            if confirmed is not None and any(n.casefold() == STICKER_FLAG for n in names.split('\x1f')):
                flags[k].add(f'{CONFIRMED_PREFIX}{int(confirmed)}')       # a confirmed sticker (core/stickers.py); a cleared one reads null
    return parts, dict(flags)


def _stock_rows(db, where, params):
    return _gather(db.execute(
        f"""SELECT s.item_id,s.color_id,s.quantity,s.kind,
              (SELECT group_concat(f.name,char(31)) FROM main.stock_flag x JOIN main.flag f ON f.id=x.flag_id AND f.archived_at IS NULL WHERE x.stock_id=s.id),
              (SELECT json_extract(e.new_value,'$.set_item_id') FROM main.event e WHERE e.entity_kind='stock_sticker' AND e.entity_id=s.id
                 AND e.field IN ('confirm','clear') AND NOT EXISTS(SELECT 1 FROM main.event_undo u WHERE u.event_id=e.id) ORDER BY e.id DESC LIMIT 1)
            FROM main.stock s WHERE s.archived_at IS NULL AND s.quantity>0 AND s.kind IN ('part','minifigure') {where}""", params))


def from_lot(db, lot_id):
    """`(parts, flags)` of the live loose stock in a lot (its flags are the stock rows' tags). `ValueError` when there is no such lot."""
    if not db.execute('SELECT 1 FROM main.lot WHERE id=? AND archived_at IS NULL', (lot_id,)).fetchone():
        raise ValueError('No such lot')
    return _stock_rows(db, 'AND s.lot_id=?', (lot_id,))


def from_storage(db, storage_id, *, below=True):
    """`(parts, flags)` of the live loose stock kept in a storage, and in the storages inside it unless `below` is false."""
    if not db.execute('SELECT 1 FROM main.storage WHERE id=? AND archived_at IS NULL', (storage_id,)).fetchone():
        raise ValueError('No such storage')
    if not below:
        return _stock_rows(db, 'AND s.storage_id=?', (storage_id,))
    return _stock_rows(db, '''AND s.storage_id IN (WITH RECURSIVE t(id) AS (SELECT ? UNION SELECT c.id FROM main.storage c JOIN t ON c.parent_id=t.id
                              WHERE c.archived_at IS NULL) SELECT id FROM t)''', (storage_id,))


def from_loose(db):
    """`(parts, flags)` of all live loose parts and figures."""
    return _stock_rows(db, '', ())


def from_stock(db, stock_ids):
    """`(parts, flags)` of a saved selection of stock rows (ids of live rows; a missing or archived one is `ValueError`)."""
    ids = list(dict.fromkeys(stock_ids))
    found = _stock_rows(db, 'AND s.id IN (SELECT value FROM json_each(?))', (json.dumps(ids),))
    live = db.execute("SELECT count(*) FROM main.stock WHERE archived_at IS NULL AND kind IN ('part','minifigure') AND id IN (SELECT value FROM json_each(?))",
                      (json.dumps(ids),)).fetchone()[0]
    if live != len(ids):
        raise ValueError('Choose live loose parts or figures')
    return found
