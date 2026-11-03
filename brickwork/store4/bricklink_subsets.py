"""BrickLink `subsets` of a set as a fetched list (design 4.2, 4.5, 8.3; issue #107, M.5b).

`parse_subsets` validates a reply as the 3.3 adapter did and turns it into required lines (quantity - extra, BrickLink's
quantity includes the extras, § 8.5) and spare lines (extra). `load_subsets` resolves each line with the inverse of the
resolution function, with the set's catalogue inventories as context, and stores the result through `fetched.write_fetched`.
A line that cannot be settled never merges two items: it becomes a local BrickLink-born item, with a `to_check` link to
each candidate when there were several (the mint's collision rule, § 8.3). No network and no jobs here.

Like `fetched`, everything runs inside the caller's transaction with a savepoint: one fetch is all or nothing."""
from dataclasses import asdict, dataclass, field
import html
import re

from . import fetched, identity
from .bldigest import bl_digest
from .connect import has_catalogue
from .errors import AmbiguousIdentity
from .fetched import InventoryError
from .identity import _inverse_color, _savepoint
from .seeds import LOCAL_BASE

TYPES = {'PART': 'P', 'MINIFIG': 'M'}
KINDS = {'P': 'part', 'M': 'minifigure'}
NUMBER = re.compile('[A-Za-z0-9.-]{1,40}')               # 3.3 had no dot; real sticker-sheet numbers (312.3stk01) have one


@dataclass
class Parsed:
    part_lines: list = field(default_factory=list)           # (number, bricklink colour, is_spare, quantity)
    figure_lines: list = field(default_factory=list)         # (number, quantity)
    names: dict = field(default_factory=dict)                # (kind, number) -> name
    skipped: dict = field(default_factory=dict)              # counterpart / alternate / type:<TYPE> -> entries
    figure_extras_dropped: int = 0                           # the figure table has no spares
    bl_lines: list = field(default_factory=list)             # for bldigest.bl_digest


def _bad(why):
    raise InventoryError(f'invalid BrickLink subsets reply: {why}')


def parse_subsets(data):
    """The reply's `data` array -> `Parsed`; InventoryError for an invalid or empty reply."""
    if not isinstance(data, list):
        _bad('"data" is not a list')
    summed, names, skipped = {}, {}, {}
    for group in data:
        if not isinstance(group, dict) or not isinstance(group.get('entries'), list):
            _bad('a group has no entries list')
        for entry in group['entries']:
            if not isinstance(entry, dict) or not isinstance(entry.get('item'), dict):
                _bad('an entry has no item')
            for flag in ('is_counterpart', 'is_alternate'):
                if entry.get(flag):
                    skipped[flag[3:]] = skipped.get(flag[3:], 0) + 1
            if entry.get('is_counterpart') or entry.get('is_alternate'):
                continue
            item = entry['item']
            kind = TYPES.get(item.get('type')) if isinstance(item.get('type'), str) else None
            if kind is None:
                key = f"type:{item.get('type')}"
                skipped[key] = skipped.get(key, 0) + 1
                continue
            number, quantity = item.get('no'), entry.get('quantity')
            extra, colour = entry.get('extra_quantity', 0), entry.get('color_id')
            if not isinstance(number, str) or not NUMBER.fullmatch(number):
                _bad(f'item number {number!r}')
            if type(quantity) is not int or quantity <= 0:
                _bad(f'{number} has quantity {quantity!r}')
            if type(extra) is not int or not 0 <= extra <= quantity:
                _bad(f'{number} has extra quantity {extra!r} with quantity {quantity}')
            if kind == 'P' and (type(colour) is not int or colour < 0):
                _bad(f'{number} has colour {colour!r}')
            key = (kind, number, colour if kind == 'P' else None)
            old = summed.get(key, (0, 0))
            summed[key] = (old[0] + quantity, old[1] + extra)
            if isinstance(item.get('name'), str) and item['name']:
                names.setdefault((kind, number), html.unescape(item['name']))   # BrickLink sends HTML entities
    parsed = Parsed(names=names, skipped=dict(sorted(skipped.items())))
    for (kind, number, colour), (quantity, extra) in sorted(summed.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or 0)):
        required = quantity - extra
        if kind == 'P':
            # BrickLink colour 0 is "(Not Applicable)": the digest has no colour there, as the catalogue's no-colour lines do.
            bl_colour = None if colour == 0 else str(colour)
            for is_spare, q in ((0, required), (1, extra)):
                if q > 0:
                    parsed.part_lines.append((number, colour, is_spare, q))
                    parsed.bl_lines.append(('P', number, bl_colour, is_spare, q))
        else:
            parsed.figure_extras_dropped += extra
            if required > 0:
                parsed.figure_lines.append((number, required))
                parsed.bl_lines.append(('M', number, None, 0, required))
    if not parsed.part_lines and not parsed.figure_lines:
        raise InventoryError('the BrickLink subsets reply has no usable lines (empty, or only counterparts, alternates, other types or extras)')
    return parsed


@dataclass
class LoadResult:
    fetched_id: int
    seq: int
    digest: str
    required_lines: int
    spare_lines: int
    figure_lines: int
    required_total: int
    spare_total: int
    figure_total: int
    local_items_created: dict        # kind -> new local items made by this load
    local_items_reused: dict         # kind -> local items the list uses that already existed
    local_colours_created: int
    ambiguous_by_context: int        # distinct (kind, number, colour) keys settled by the set's inventories
    ambiguous_made_local: int        # ... that became a local item with to_check links
    skipped: dict
    figure_extras_dropped: int
    bl_digest: str
    bl_digest_matches: bool
    matches_version: int | None      # the catalogue inventory version whose bl_digest equals this reply's

    def as_dict(self):
        return asdict(self)


def _item_row(db, item_id):
    row = db.execute('SELECT born_provider, born_namespace, born_key, origin FROM main.item WHERE id=?', (item_id,)).fetchone()
    if row is None and has_catalogue(db):
        row = db.execute('SELECT born_provider, born_namespace, born_key, 0 AS origin FROM catalogue.item WHERE id=?', (item_id,)).fetchone()
    return row


class _Loader:
    def __init__(self, db, set_item_id, set_number, events):
        self.db, self.set_item_id, self.set_number, self.events = db, set_item_id, set_number, events
        self.colours, self.items, self.context = {}, {}, {}
        self.created, self.used = set(), set()
        self.local_colours = self.by_context = self.made_local = 0
        self.ambiguous_seen = set()

    def colour(self, bl):
        """(Rebrickable colour id in the collection, the key to resolve items with): BrickLink 0 falls back to colour 1."""
        if bl in self.colours:
            return self.colours[bl]
        key = str(bl)
        try:
            colour = _inverse_color(self.db, 'bricklink', key)
        except AmbiguousIdentity as exc:
            raise InventoryError(f'BrickLink colour {key} is shared by Rebrickable colours {list(exc.items)} and none is preferred; '
                                 f'the list is refused rather than guessing a colour') from exc
        resolve_key = key
        if colour is None and bl == 0:
            colour, resolve_key = 1, None
        elif colour is None:
            before = self.db.execute("SELECT 1 FROM main.color WHERE born_provider='bricklink' AND born_key=?", (key,)).fetchone()
            colour = fetched.create_local_color(self.db, bricklink_key=key, name=f'BrickLink colour {key}', events=self.events)
            self.local_colours += before is None
        identity.project_color(self.db, colour)
        # Projection can drop a link another collection colour already holds, and with it the answer just given: a reload
        # would then pick another colour. That state is reconcile's to settle; the list is refused rather than made unstable.
        if resolve_key is not None and _inverse_color(self.db, 'bricklink', key) != colour:
            raise InventoryError(f'BrickLink colour {key} resolves to colour {colour} only until it is projected; '
                                 f'run reconcile to settle which colour holds it')
        self.colours[bl] = colour, resolve_key
        return self.colours[bl]

    def in_context(self, kind):
        if kind not in self.context:
            found = set()
            if has_catalogue(self.db):
                table = 'inventory_part' if kind == 'P' else 'inventory_figure'
                found = {r[0] for r in self.db.execute(
                    f'SELECT DISTINCT l.item_id FROM catalogue.inventory i JOIN catalogue.{table} l ON l.inventory_id=i.id WHERE i.item_id=?',
                    (self.set_item_id,))}
            self.context[kind] = found
        return self.context[kind]

    def local(self, kind, number, name):
        existing = self.db.execute("SELECT 1 FROM main.item WHERE born_provider='bricklink' AND born_namespace=? AND born_key=?",
                                   (kind, number)).fetchone()
        item = fetched.create_local_item(self.db, kind=KINDS[kind], born_provider='bricklink', born_namespace=kind, born_key=number,
                                         name=name, events=self.events)
        if existing is None:
            self.created.add(item)
        fetched.add_item_link(self.db, item, provider='bricklink', provider_kind=kind, provider_key=number, status='matched',
                              method='bricklink_api', origin='api', events=self.events)
        return item

    def item(self, kind, number, colour_key, name):
        cache = (kind, number, colour_key)
        if cache in self.items:
            return self.items[cache]
        try:
            found = identity.resolve_inverse(self.db, kind, number, colour_key, exhaustive=True)
            item = None if found is None else found[0]
            if item is None:
                item = self.local(kind, number, name)
            else:
                identity.project(self.db, item)
        except AmbiguousIdentity as exc:
            item = self.ambiguous(kind, number, name, exc.items)
        self.used.add(item)
        self.items[cache] = item
        return item

    def ambiguous(self, kind, number, name, candidates):
        db = self.db
        first = (kind, number) not in self.ambiguous_seen
        self.ambiguous_seen.add((kind, number))
        # The local item an earlier list made for this number is no candidate: this set's context decides again, and a set the
        # context cannot settle gets that same item back (create_local_item is idempotent on the born key).
        rows = {c: _item_row(db, c) for c in candidates}
        candidates = [c for c in candidates if rows[c] is None or tuple(rows[c][:3]) != ('bricklink', kind, number)]
        settled = [c for c in candidates if c in self.in_context(kind)]
        if len(settled) == 1:
            self.by_context += first
            identity.project(db, settled[0])
            return settled[0]
        item = self.local(kind, number, name)
        self.made_local += first
        rows = [rows[c] for c in candidates if rows[c] is not None and rows[c]['born_key'] is not None]
        evidence = {'set': self.set_number, 'bricklink': f'{kind} {number}', 'candidates': [f"{r['born_namespace']} {r['born_key']}" for r in rows]}
        for r in rows:
            fetched.add_item_link(db, item, provider=r['born_provider'], provider_kind=r['born_namespace'], provider_key=r['born_key'],
                                  status='to_check', method='bricklink_api_ambiguous', origin='api', evidence=evidence, events=self.events)
        return item


def load_subsets(db, set_item_id, set_number, reply, *, job_id=None, events=None):
    """Store a BrickLink `subsets` reply for a set as the next `fetched_inventory(source='bricklink')`; returns a LoadResult.

    `reply` is the whole API reply (kept as the source record); the set must be in the collection or the catalogue."""
    if not isinstance(reply, dict):
        raise InventoryError('the BrickLink subsets reply is not an object')
    parsed = parse_subsets(reply.get('data'))
    _savepoint(db, 'load_subsets')
    try:
        row = db.execute('SELECT kind FROM main.item WHERE id=?', (set_item_id,)).fetchone()
        if row is None:
            if not has_catalogue(db) or not db.execute('SELECT 1 FROM catalogue.item WHERE id=?', (set_item_id,)).fetchone():
                raise InventoryError(f'item {set_item_id} is in neither the collection nor the catalogue')
            identity.project(db, set_item_id)
            row = db.execute('SELECT kind FROM main.item WHERE id=?', (set_item_id,)).fetchone()
        if row['kind'] != 'set':
            raise InventoryError(f'item {set_item_id} is a {row["kind"]}, not a set')
        record = fetched.store_source_record(db, source='bricklink', kind='subsets', key=set_number, payload=reply, job_id=job_id)
        loader = _Loader(db, set_item_id, set_number, events)
        parts, figures = [], []
        for number, colour, spare, q in parsed.part_lines:
            rb, key = loader.colour(colour)
            parts.append((loader.item('P', number, key, parsed.names.get(('P', number), number)), rb, spare, q))
        for number, q in parsed.figure_lines:
            figures.append((loader.item('M', number, None, parsed.names.get(('M', number), number)), q))
        fid = fetched.write_fetched(db, set_item_id, 'bricklink', parts, figures, job_id=job_id, source_record_id=record, events=events)
        seq, digest = db.execute('SELECT seq, digest FROM main.fetched_inventory WHERE id=?', (fid,)).fetchone()
        digest_bl = bl_digest(parsed.bl_lines)
        version = None
        if has_catalogue(db):
            hit = db.execute('SELECT version FROM catalogue.inventory WHERE item_id=? AND bl_digest=? ORDER BY is_latest DESC, version DESC',
                             (set_item_id, digest_bl)).fetchone()
            version = hit[0] if hit else None
        kinds = {i: db.execute('SELECT kind FROM main.item WHERE id=?', (i,)).fetchone()[0] for i in loader.used if i >= LOCAL_BASE}
        count = lambda ids: {k: sum(1 for i in ids if kinds[i] == k) for k in ('part', 'minifigure')}
        result = LoadResult(
            fetched_id=fid, seq=seq, digest=digest,
            required_lines=sum(1 for p in parsed.part_lines if not p[2]), spare_lines=sum(1 for p in parsed.part_lines if p[2]),
            figure_lines=len(parsed.figure_lines),
            required_total=sum(p[3] for p in parsed.part_lines if not p[2]), spare_total=sum(p[3] for p in parsed.part_lines if p[2]),
            figure_total=sum(f[1] for f in parsed.figure_lines),
            local_items_created=count(loader.created & kinds.keys()), local_items_reused=count(set(kinds) - loader.created),
            local_colours_created=loader.local_colours, ambiguous_by_context=loader.by_context, ambiguous_made_local=loader.made_local,
            skipped=parsed.skipped, figure_extras_dropped=parsed.figure_extras_dropped,
            bl_digest=digest_bl, bl_digest_matches=version is not None, matches_version=version)
    except BaseException:
        db.execute('ROLLBACK TO load_subsets')
        raise
    finally:
        db.execute('RELEASE load_subsets')
    return result
