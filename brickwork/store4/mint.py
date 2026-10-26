"""The migration mint (design 8.3, issue #109 M.7a): every 3.3 key -> its 4.0 item and colour. Decides, writes nothing.

`mint(src, db)` reads a 3.3 store (`src`, opened read-only by the caller; it is only ever SELECTed) and a fresh 4.0 collection
`db` with the catalogue attached, and returns a `MintResult`: a decision for every BrickLink key `(type, number, colour)` that any
carried 3.3 row names, a plan for the local items and local colours the writer (M.7b) has to create, the collisions and the
colour table. The local ids in the plan are the ones the writer should use (running from the collection's local range), so the
mint table, the collision list and the plan agree before anything is written.

Rule numbers are those of design 8.3: 1 `?` placeholders, 2 the candidate search (all catalogue links, scoped to the minted colour,
`identity.candidate_items`; it leads to 3, 4 or 5), 3 one candidate, 4 several candidates and the context breaks the tie, 5 none
(or the tie stays): a local BrickLink-born item. The injectivity pass then keeps one key per 4.0 target; the others get a local
item and a `to_check` link to the shared catalogue item (`collision` on the decision).

Rule 4 is decided per holder, as design 8.3 words it: the context of a row is its holder, the set (or figure) whose catalogue list the
row belongs to. For a key with several candidates the rows under each holder go to the one candidate that holder's list holds, else to
the key's local BrickLink-born item (every candidate a `to_check` `migration_candidate` link); rows without a holder (loose stock, wishes,
prices, instruction files, images) take the key-level answer, which is that local item. A local item exists only if some row lands on it.
`MintResult.target(..., holder=...)` answers per row. One key may thus land on several items; two different keys may not share a target.

A collision loser keeps its own BrickLink number, so its local item carries a `matched/migration` BrickLink link: until the local item
is merged into the shared catalogue item, `resolve_inverse` finds both for that number and raises AmbiguousIdentity (design 8.3: the
resolution is the merge).

A mint key is `(item_type, item_no, bl_color_id)`. `bl_color_id` is the 3.3 colour id (None for rows without one). A `?` placeholder
carries the kind of the table that names it as a second letter of its type: `?S`, `?M`, `?P`."""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import csv
import re

from ..core import csv_safe
from .connect import has_catalogue
from .errors import AmbiguousIdentity, CatalogueError, Store4Error
from .identity import CONFIRMED, _inverse_color, best_item_link, candidate_items
from .seeds import LOCAL_BASE

TYPE_KIND = {'S': 'set', 'M': 'minifigure', 'P': 'part', 'G': 'gear', 'B': 'book', 'C': 'catalog', 'I': 'instructions', 'O': 'box'}
KIND_LETTER = {'set': 'S', 'minifigure': 'M', 'part': 'P'}
NAMESPACE = {'set': 'sets', 'part': 'parts', 'minifigure': 'minifigs'}
NO_COLOUR = 1                                              # "no colour" (design 3.7)
_IN = ','.join('?' * len(CONFIRMED))
PLACEHOLDER = re.compile(r'rebrickable:(.+)')
COLOURLESS = ('S', 'M', '?S', '?M')                       # sets and figures have no colour: BrickLink 0 ("not applicable") is NULL


def _key_colour(item_type, color_id):
    return None if item_type in COLOURLESS else color_id

# (table, SELECT of type, number, colour, rows; the kind a `?` placeholder in it stands for, None = decided by the number)
SWEEP = (
    ('copies', 'SELECT item_type, set_no, NULL, count(*) FROM copies GROUP BY 1, 2', 'set'),
    ('copy_parts', 'SELECT item_type, item_no, color_id, count(*) FROM copy_parts GROUP BY 1, 2, 3', 'part'),
    ('copy_parts.parent', 'SELECT parent_minifig_type, parent_minifig, NULL, count(*) FROM copy_parts '
                          'WHERE parent_minifig IS NOT NULL GROUP BY 1, 2', 'minifigure'),
    ('copy_minifigs', 'SELECT item_type, minifig_no, NULL, count(*) FROM copy_minifigs GROUP BY 1, 2', 'minifigure'),
    ('loose_stock', 'SELECT item_type, item_no, color_id, count(*) FROM loose_stock GROUP BY 1, 2, 3', None),
    ('loose_minifig_parts', 'SELECT item_type, item_no, color_id, count(*) FROM loose_minifig_parts GROUP BY 1, 2, 3', 'part'),
    ('wishlist', 'SELECT item_type, item_no, color_id, count(*) FROM wishlist GROUP BY 1, 2, 3', None),
    ('price_observations', 'SELECT item_type, item_no, color_id, count(*) FROM price_observations GROUP BY 1, 2, 3', None),
    ('price_current', 'SELECT item_type, item_no, color_id, count(*) FROM price_current GROUP BY 1, 2, 3', None),
    ('price_watch', 'SELECT item_type, item_no, color_id, count(*) FROM price_watch GROUP BY 1, 2, 3', None),
    ('instruction_files', 'SELECT item_type, set_no, NULL, count(*) FROM instruction_files GROUP BY 1, 2', 'set'),
    ("item_images(own)", "SELECT item_type, item_no, color_id, count(*) FROM item_images WHERE kind='own' GROUP BY 1, 2, 3", None),
)


@dataclass
class ColourDecision:
    bl_id: object                                          # the 3.3 colour id, None for "no colour on the row"
    color_id: int                                          # the 4.0 colour (a planned local id for a local colour)
    origin: str                                            # 'catalogue' | 'local'
    rule: str                                              # null | link | inverse_preferred | local | local_ambiguous
    candidates: tuple = ()                                 # catalogue colours the BrickLink id links to
    name: str = None
    note: str = ''


@dataclass
class LocalColour:
    local_id: int
    bl_id: int
    name: str
    rgb: str
    is_trans: int
    reason: str


@dataclass
class LinkPlan:
    provider: str
    provider_kind: str
    provider_key: str
    status: str
    method: str
    origin: str = 'migration'
    color_id: int = None


@dataclass
class LocalItem:
    """An item the writer creates in the collection (origin 'local'). `local_id` is its planned id."""
    plan_key: tuple
    kind: str
    kind_source: str
    name: str
    year: int
    born_provider: str                                     # 'bricklink' | 'rebrickable' | None (unidentified)
    born_namespace: str
    born_key: str
    reasons: set = field(default_factory=set)              # no_candidate | ambiguous | placeholder | collision
    links: dict = field(default_factory=dict)              # (provider, kind, key) -> LinkPlan
    provider_status: set = field(default_factory=set)      # (provider, status, reason) rows for item_provider_status
    local_id: int = None



class MintInvariantError(Store4Error):
    """The mint's own plan broke an invariant (a shared target, a born key that already exists): a bug or an unexpected input."""


@dataclass
class Outcome:
    """What the rows under one holder of a key land on (rule 4: one candidate in the holder's context, else the local item)."""
    rule: int
    rows: int
    item_id: int = None
    origin: str = 'catalogue'
    plan_key: tuple = None
    collision: str = None
    note: str = ''


@dataclass
class ItemDecision:
    """The decision for one key. `item_id`, `origin`, `plan_key` and `collision` are the key-level answer, the one for rows that
    have no holder. A key with several candidates (`rule` 4) also has `holders`: its answer per holder. `item_id` is None when no
    row lands on the key-level answer."""
    key: tuple
    kind: str
    rule: int                                              # 1, 3, 4 (several candidates: decided per holder), 5 (none) or 6 (type_crossed)
    item_id: int = None                                    # catalogue id, or the planned local id
    origin: str = 'catalogue'
    candidates: tuple = ()                                 # item ids found by rule 2
    note: str = ''
    rows: int = 0                                          # all rows naming the key
    tables: tuple = ()
    collision: str = None                                  # None | 'keeper' | 'loser'
    plan_key: tuple = None                                 # the local item behind a local target
    colour_id: int = None
    free_rows: int = 0                                     # rows without a holder
    holders: dict = field(default_factory=dict)            # holder mint key -> Outcome (rule 4 and 6 keys)
    crossed: bool = False                                  # rule 6: a G/B/C/I/O key in a part table, looked up as BrickLink type P


@dataclass
class Collision:
    loser: tuple
    keeper: tuple
    shared_item_id: int
    color_id: int
    reason: str                                            # preferred_link | most_rows | lowest_number
    loser_rows: int
    keeper_rows: int
    loser_local_id: int = None
    holders: tuple = ()                                    # holders under which the loser hit the shared target ('' = rows without one)
    loser_plan_key: tuple = None


@dataclass(frozen=True)
class Target:
    item_id: int
    color_id: int


# Tables whose rows have a holder (the set or figure whose list is the context) per kind of key; every other table is context-free.
PART_TABLES = ('copy_parts', 'loose_minifig_parts')       # tables whose rows are parts of a set or figure
HOLDER_TABLES = {'part': ('copy_parts', 'loose_minifig_parts'), 'minifigure': ('copy_minifigs',)}


def holder_label(holder):
    if holder is None:
        return ''
    if isinstance(holder[0], tuple):                       # (figure key, set key): a figure's part inside a copy of that set
        return f'{holder_label(holder[0])}@{holder_label(holder[1])}'
    return f'{holder[0]}:{holder[1]}' + ('' if holder[2] is None else f':{holder[2]}')


class MintResult:
    def __init__(self):
        self.items = {}                                    # mint key -> ItemDecision
        self.colours = {}                                  # 3.3 colour id (or None) -> ColourDecision
        self.local_items = []                              # [LocalItem], by planned id
        self.local_colours = []                            # [LocalColour], by planned id
        self.collisions = []                               # [Collision]
        self.unresolved = []                               # collisions the mint cannot resolve (see mint())
        self.composition_file = False
        self.names = {}                                    # catalogue/local item id -> born label, for the reports

    @property
    def case(self):
        return ('with the figure composition file (local-layer M links present in the catalogue)' if self.composition_file
                else 'without the figure composition file: every minifigure that no catalogue link names is a local BrickLink-born item (rule 5)')

    @staticmethod
    def key_of(item_type, item_no, color_id=None, kind=None):
        """The mint key of a 3.3 row's item; `kind` ('set', 'part', 'minifigure') is required for a `?` placeholder."""
        item_type = '?' + KIND_LETTER[kind] if item_type == '?' else item_type
        return (item_type, item_no, _key_colour(item_type, color_id))

    def target(self, item_type, item_no, color_id=None, kind=None, holder=None):
        """The 4.0 (item, colour) of a 3.3 row. `holder` is the mint key (see `key_of`) of the set or figure holding the row: the
        copy's set for a copy line or a figure row, the loose figure for its parts, and for a part of a figure inside a copy the pair
        `(figure mint key, set mint key)`, because the figure's own outcome can differ per set. It matters only for a key with several
        candidates (rule 4) and is None for a row with no holder (loose stock, wishes, prices...)."""
        d = self.items[key := self.key_of(item_type, item_no, color_id, kind)]
        if d.holders and holder is not None:
            if holder not in d.holders:
                raise LookupError(f'{d.key} was not seen under holder {holder}')
            o = d.holders[holder]
        elif d.item_id is None:
            raise LookupError(f'{d.key} has several candidates and every row of it has a holder: pass the holder')
        else:
            o = d
        return Target(o.item_id, self.colour_for(key[2]))

    def colour_for(self, bl_color):
        return self.colours[bl_color].color_id

    def shared_targets(self):
        """[(sorted keys)] of every 4.0 target (item, colour) that two or more different 3.3 keys land on, any holder."""
        groups = defaultdict(set)
        for key, d in self.items.items():
            colour = d.colour_id if d.kind == 'part' else None
            for o in [*d.holders.values(), *([d] if d.item_id is not None else [])]:
                groups[(o.item_id, colour)].add(key)
        return [tuple(sorted(keys, key=_key_sort)) for _, keys in sorted(groups.items(), key=lambda g: str(g[0])) if len(keys) > 1]

    def check_injective(self):
        """The shared targets that are not reported in `unresolved`: empty for every plan the mint returns."""
        known = {frozenset(k) for k in self.unresolved}
        return [keys for keys in self.shared_targets() if frozenset(keys) not in known]

    def counts(self):
        """Keys per rule, holders resolved vs tied, collisions, local items by reason, placeholders."""
        by_rule = Counter(d.rule for d in self.items.values())
        placeholders = [d for d in self.items.values() if d.rule == 1]
        multi = [d for d in self.items.values() if d.rule == 4]
        holders = [o for d in multi for o in d.holders.values()]
        resolved_h = sum(1 for o in holders if o.rule == 4)
        per_key = Counter('all resolved' if all(o.rule == 4 for o in d.holders.values()) and d.holders else
                          'none resolved' if not any(o.rule == 4 for o in d.holders.values()) else 'some resolved' for d in multi)
        out = {'keys': len(self.items), **{f'rule {r}': by_rule.get(r, 0) for r in (1, 3, 4, 5, 6)},
               'placeholders resolved': sum(1 for d in placeholders if d.origin == 'catalogue'),
               'placeholders local': sum(1 for d in placeholders if d.origin == 'local'),
               'rule 4 holders': len(holders), 'rule 4 holders resolved': resolved_h, 'rule 4 holders tied': len(holders) - resolved_h,
               'rule 4 keys, every holder resolved': per_key['all resolved'], 'rule 4 keys, some holders resolved': per_key['some resolved'],
               'rule 4 keys, no holder resolved': per_key['none resolved'],
               'rule 4 keys with context-free rows': sum(1 for d in multi if d.free_rows),
               'collisions': len(self.collisions), 'unresolved collisions': len(self.unresolved),
               'local items': len(self.local_items), 'local colours': len(self.local_colours), 'colours': len(self.colours)}
        out['type_crossed holders'] = sum(1 for d in self.items.values() if d.crossed for o in d.holders.values() if o.rule == 6)
        out['type_crossed holders without context support'] = sum(1 for d in self.items.values() if d.crossed for o in d.holders.values() if o.rule != 6)
        for reason, n in sorted(Counter(r for i in self.local_items for r in i.reasons).items()):
            out[f'local items ({reason})'] = n         # an item can carry several reasons: one BrickLink number, several colours
        return out

    # ---- the report files of design 8.8 (data only; write_report() writes them) ----
    def mint_rows(self):
        header = ('item_type', 'item_no', 'bl_color_id', 'holder', 'kind', 'rows', 'tables', 'rule', 'collision', 'target_item_id',
                  'target_origin', 'target_color_id', 'candidates', 'note')
        rows = []
        for key in sorted(self.items, key=_key_sort):
            d = self.items[key]
            cands = ' | '.join(f'{c}={self.names.get(c, "")}' for c in d.candidates)
            colour = self.colour_for(key[2])
            blank = '' if key[2] is None else key[2]
            if d.holders:
                for holder in sorted(d.holders, key=holder_label):
                    o = d.holders[holder]
                    rows.append((key[0], key[1], blank, holder_label(holder), d.kind, o.rows, ' '.join(d.tables), o.rule, o.collision or '',
                                 o.item_id, o.origin, colour, cands, o.note))
            if not d.holders or d.item_id is not None:
                rows.append((key[0], key[1], blank, '', d.kind, d.free_rows if d.holders else d.rows, ' '.join(d.tables),
                             5 if d.holders else d.rule, d.collision or '', d.item_id, d.origin, colour, cands, d.note))
        return header, rows

    def crossed_rows(self):
        """Rule 6 (type_crossed): a part-table row filed under BrickLink type G/B/C/I/O, carried as the Rebrickable part of the same number
        that the holder's catalogue list holds. One row per (key, holder)."""
        header = ('item_type', 'item_no', 'bl_color_id', 'holder', 'rows', 'part_item_id', 'part')
        rows = [(*key[:2], '' if key[2] is None else key[2], holder_label(h), o.rows, o.item_id, self.names.get(o.item_id, ''))
                for key, d in sorted(self.items.items(), key=lambda kv: _key_sort(kv[0])) if d.crossed
                for h, o in sorted(d.holders.items(), key=lambda kv: holder_label(kv[0])) if o.rule == 6]
        return header, rows

    def collision_rows(self):
        header = ('loser_item_type', 'loser_item_no', 'loser_bl_color_id', 'keeper_item_type', 'keeper_item_no', 'keeper_bl_color_id',
                  'shared_item_id', 'shared_item', 'color_id', 'keeper_reason', 'loser_rows', 'keeper_rows', 'loser_local_id', 'holders')
        rows = [(*c.loser[:2], '' if c.loser[2] is None else c.loser[2], *c.keeper[:2], '' if c.keeper[2] is None else c.keeper[2],
                 c.shared_item_id, self.names.get(c.shared_item_id, ''), c.color_id, c.reason, c.loser_rows, c.keeper_rows, c.loser_local_id,
                 ' '.join(holder_label(h) or '(none)' for h in c.holders))
                for c in sorted(self.collisions, key=lambda c: _key_sort(c.loser))]
        return header, rows

    def local_item_rows(self):
        header = ('local_id', 'kind', 'born_provider', 'born_namespace', 'born_key', 'name', 'reasons', 'links')
        rows = [(i.local_id, i.kind, i.born_provider or '', i.born_namespace or '', i.born_key or '', i.name or '', ' '.join(sorted(i.reasons)),
                 ' '.join(f'{l.provider}/{l.provider_kind}/{l.provider_key}:{l.status}:{l.method}' for l in i.links.values()))
                for i in self.local_items]
        return header, rows

    def colour_rows(self):
        header = ('bl_color_id', 'name', 'color_id', 'origin', 'rule', 'candidates', 'note')
        rows = [(d.bl_id if d.bl_id is not None else '', d.name or '', d.color_id, d.origin, d.rule, ' '.join(map(str, d.candidates)), d.note)
                for d in sorted(self.colours.values(), key=lambda d: (d.bl_id is None, d.bl_id or 0))]
        return header, rows

    def report_files(self):
        return {'mint.csv': self.mint_rows(), 'collisions.csv': self.collision_rows(), 'local-items.csv': self.local_item_rows(),
                'colours.csv': self.colour_rows()}


def _key_sort(key):
    return tuple('' if part is None else part for part in key[:2]) + (-1 if key[2] is None else key[2],)


def write_report(result, directory):
    """Write mint.csv, collisions.csv, local-items.csv and colours.csv (design 8.8) into `directory`; returns the paths."""
    from pathlib import Path
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, (header, rows) in result.report_files().items():
        path = directory / name
        with open(path, 'w', newline='', encoding='utf-8') as f:
            w = csv_safe.writer(f)
            w.writerow(header)
            w.writerows(rows)
        paths.append(path)
    return paths


# ---------------------------------------------------------------------------------------------------------------------------------


def _kind_by_number(item_no):
    """Only for a `?` placeholder in a table that does not say what it holds: Rebrickable's own number shapes."""
    n = item_no[len('rebrickable:'):] if item_no.startswith('rebrickable:') else item_no
    if n.startswith('fig-'):
        return 'minifigure'
    return 'set' if re.search(r'-\d+$', n) else 'part'




def _sweep(src):
    """{mint key: [rows, tables, rows per table]} over every carried table that names an item."""
    refs = {}
    for table, sql, kind in SWEEP:
        for item_type, item_no, color, n in src.execute(sql):
            if item_type == '?':
                item_type = '?' + KIND_LETTER[kind or _kind_by_number(item_no)]
            row = refs.setdefault((item_type, item_no, _key_colour(item_type, color)), [0, [], {}])
            row[0] += n
            if table not in row[1]:
                row[1].append(table)
            row[2][table] = row[2].get(table, 0) + n
    return refs


class _Catalogue:
    """The few catalogue lookups the mint needs, cached."""

    def __init__(self, db):
        self.db = db
        self._kind, self._born, self._links = {}, {}, {}

    def kind(self, item_id):
        if item_id not in self._kind:
            row = self.db.execute('SELECT kind FROM catalogue.item WHERE id=? UNION ALL SELECT kind FROM main.item WHERE id=?',
                                  (item_id, item_id)).fetchone()
            self._kind[item_id] = row[0] if row else None
        return self._kind[item_id]

    def born(self, item_id):
        if item_id not in self._born:
            row = self.db.execute('SELECT born_namespace, born_key, name FROM catalogue.item WHERE id=? UNION ALL '
                                  'SELECT born_namespace, born_key, name FROM main.item WHERE id=?', (item_id, item_id)).fetchone()
            self._born[item_id] = tuple(row) if row else None
        return self._born[item_id]

    def by_born(self, namespace, born_key):
        row = self.db.execute('SELECT id FROM catalogue.item WHERE born_provider=\'rebrickable\' AND born_namespace=? AND born_key=? '
                              'UNION ALL SELECT id FROM main.item WHERE born_provider=\'rebrickable\' AND born_namespace=? AND born_key=?',
                              (namespace, born_key, namespace, born_key)).fetchone()
        return row[0] if row else None

    def bricklink_links(self, item_id):
        if item_id not in self._links:
            rows = []
            for store in ('main', 'catalogue'):
                rows += [dict(provider_kind=k, provider_key=n, color_id=c, preferred=p, status=s) for k, n, c, p, s in self.db.execute(
                    f"SELECT provider_kind, provider_key, color_id, preferred, status FROM {store}.item_link "
                    f"WHERE item_id=? AND provider='bricklink' AND status IN ({_IN})", (item_id, *CONFIRMED))]
            self._links[item_id] = rows
        return self._links[item_id]

    def inventory_items(self, item_id, kind):
        """The part items (kind 'part') or figure items of every catalogue inventory of a set or figure, any version."""
        table = 'inventory_part' if kind == 'part' else 'inventory_figure'
        return {r[0] for r in self.db.execute(f'SELECT DISTINCT l.item_id FROM catalogue.inventory i JOIN catalogue.{table} l '
                                              'ON l.inventory_id=i.id WHERE i.item_id=?', (item_id,))}




def mint(src, db):
    """Decide the 4.0 target of every 3.3 key `src` names. `src`: the 3.3 store, read only; `db`: a fresh 4.0 collection with the
    catalogue attached. Nothing is written to either."""
    if not has_catalogue(db):
        raise CatalogueError('the mint needs the catalogue attached')
    result = MintResult()
    cat = _Catalogue(db)
    refs = _sweep(src)
    names = {(t, n): (name, year) for t, n, name, year in src.execute('SELECT item_type, item_no, name, year FROM items')}
    result.composition_file = bool(db.execute("SELECT 1 FROM catalogue.item_link WHERE origin='local' AND provider_kind='M' "
                                              "AND status IN ('matched', 'inferred') LIMIT 1").fetchone())
    local_base = max(LOCAL_BASE - 1, db.execute('SELECT coalesce(max(id), 0) FROM main.item WHERE id>=?', (LOCAL_BASE,)).fetchone()[0]) + 1
    colour_base = max(LOCAL_BASE - 1, db.execute('SELECT coalesce(max(id), 0) FROM main.color WHERE id>=?', (LOCAL_BASE,)).fetchone()[0]) + 1
    _colours(src, db, result, {k[2] for k in refs if k[2] is not None}, colour_base)
    plans = {}                                             # plan_key -> LocalItem

    def local(plan_key, kind, kind_source, name, year, born, reason):
        item = plans.get(plan_key)
        if item is None:
            item = plans[plan_key] = LocalItem(plan_key, kind, kind_source, name, year, *born)
        item.reasons.add(reason)
        return item

    def bl_born(item_type, item_no, reason):
        name, year = names.get((item_type, item_no), (None, None))
        kind = TYPE_KIND[item_type]
        item = local(('bl', item_type, item_no), kind, 'namespace' if item_type in 'PM' else 'bricklink', name or f'{item_type} {item_no}',
                     year, ('bricklink', item_type, item_no), reason)
        item.links[('bricklink', item_type, item_no)] = LinkPlan('bricklink', item_type, item_no, 'matched', 'migration')
        return item

    def candidate_links(item, candidates):
        for c in candidates:
            ns, born_key, _ = cat.born(c)
            item.links[('rebrickable', ns, born_key)] = LinkPlan('rebrickable', ns, born_key, 'to_check', 'migration_candidate')

    def land_local(target, d):
        """Rows of a multi-candidate key that no single candidate claims land on the key's BrickLink-born local item."""
        item = bl_born(d.key[0], d.key[1], 'ambiguous')
        candidate_links(item, d.candidates)
        target.origin, target.plan_key, target.item_id = 'local', item.plan_key, None

    # ---- passes A (rules 1, 2, 3, 5) and B (rule 4) ----
    pending = []
    for key in sorted(refs, key=_key_sort):
        item_type, item_no, color = key
        rows, tables, by_table = refs[key]
        placeholder = item_type.startswith('?')
        kind = {'S': 'set', 'M': 'minifigure', 'P': 'part'}[item_type[1]] if placeholder else TYPE_KIND[item_type]
        d = result.items[key] = ItemDecision(key, kind, 0, rows=rows, tables=tuple(tables), colour_id=result.colour_for(color))
        d.free_rows = rows - sum(by_table.get(t, 0) for t in HOLDER_TABLES.get(kind, ()))
        if placeholder:                                    # rule 1
            d.rule = 1
            number = PLACEHOLDER.fullmatch(item_no).group(1) if PLACEHOLDER.fullmatch(item_no) else item_no
            found = cat.by_born(NAMESPACE[kind], number)
            wrong = None
            if found is not None and cat.kind(found) != kind:
                d.note = f'the catalogue item {found} is a {cat.kind(found)}, the row needs a {kind}: not a hit'
                wrong, found = found, None
            if found is not None:
                d.item_id, d.candidates = found, (found,)
            elif wrong is not None:
                # The born key belongs to the catalogue item: an unidentified local item, with a to_check link to it.
                name, year = names.get((item_type[0], item_no), (None, None))
                item = local(('un', key), kind, 'namespace' if kind != 'set' else 'bricklink', name or number, year, (None, None, None),
                             'wrong_kind')
                ns, born_key, _ = cat.born(wrong)
                item.links[('rebrickable', ns, born_key)] = LinkPlan('rebrickable', ns, born_key, 'to_check', 'migration_wrong_kind')
                item.provider_status.add(('bricklink', 'to_check', 'migration'))
                d.origin, d.plan_key = 'local', item.plan_key
            else:
                name, year = names.get((item_type[0], item_no), (None, None))
                item = local(('rb', NAMESPACE[kind], number), kind, 'namespace', name or number, year,
                             ('rebrickable', NAMESPACE[kind], number), 'placeholder')
                item.provider_status.add(('bricklink', 'to_check', 'migration'))
                d.origin, d.plan_key = 'local', item.plan_key
            continue
        if item_type not in ('P', 'M') and set(tables) <= set(PART_TABLES):
            # rule 6: BrickLink files some parts of a set as gear/book/...; the catalogue has them as parts linked under type P
            crossed = tuple(_candidates(db, cat, 'P', item_no, 'part', result.colour_for(color)))
            if crossed:
                d.kind, d.rule, d.candidates, d.crossed = 'part', 6, crossed, True
                d.free_rows = rows - sum(by_table.get(t, 0) for t in HOLDER_TABLES['part'])
                pending.append(d)
                continue
        d.candidates = tuple(_candidates(db, cat, item_type, item_no, kind, result.colour_for(color)))
        if len(d.candidates) == 1:                         # rule 3
            d.rule, d.item_id = 3, d.candidates[0]
        elif not d.candidates:                             # rule 5
            d.rule, d.origin = 5, 'local'
            d.plan_key = bl_born(item_type, item_no, 'no_candidate').plan_key
        else:
            d.rule = 4
            pending.append(d)
    contexts = _Contexts(src, result, cat)
    for d in sorted(pending, key=lambda d: ({'S': 0, 'M': 1}.get(d.key[0], 2), _key_sort(d.key))):   # sets, then figures, then the rest
        # Rule 4 per holder: exactly one candidate in the holder's context -> that item for the rows under it; else the local item.
        for holder, n in contexts.holders(d).items():
            found = [c for c in d.candidates if c in contexts.items_of(d, holder)]
            if len(found) == 1 and d.crossed:
                d.holders[holder] = Outcome(6, n, found[0], note=f'type_crossed: P {d.key[1]} in the context of {holder_label(holder)}')
            elif d.crossed:
                o = d.holders[holder] = Outcome(5, n, note=f'type_crossed: {len(found)} of {len(d.candidates)} P candidates in the context of {holder_label(holder)}')
                item = bl_born(d.key[0], d.key[1], 'no_context')
                o.origin, o.plan_key, o.item_id = 'local', item.plan_key, None
            elif len(found) == 1:
                d.holders[holder] = Outcome(4, n, found[0], note='context: ' + holder_label(holder))
            else:
                o = d.holders[holder] = Outcome(5, n, note=f'{len(d.candidates)} candidates, {len(found)} in the context of {holder_label(holder)}')
                land_local(o, d)
        d.origin, d.item_id = 'local', None                # the key-level answer, for rows without a holder
        if d.free_rows and d.crossed:
            item = bl_born(d.key[0], d.key[1], 'no_context')
            d.origin, d.plan_key, d.item_id = 'local', item.plan_key, None
        elif d.free_rows:
            land_local(d, d)
            d.note = f'{len(d.candidates)} candidates, no context for the {d.free_rows} row(s) without a holder'
        else:
            d.origin = None
    # ---- pass C: injectivity, over every (key, holder) target ----
    def outcome(key, holder):
        d = result.items[key]
        return d if holder is None else d.holders[holder]

    entries = []                                           # (key, holder)
    for key, d in result.items.items():
        entries += [(key, h) for h in d.holders]
        if not d.holders or d.item_id is not None:
            entries.append((key, None))
    groups = defaultdict(list)
    for key, holder in entries:
        o = outcome(key, holder)
        groups[(o.item_id if o.origin == 'catalogue' else o.plan_key, (result.items[key].colour_id if result.items[key].kind == 'part' else None))].append((key, holder))
    for (target, colour), members in sorted(groups.items(), key=lambda g: _key_sort(min((m[0] for m in g[1]), key=_key_sort))):
        keys = sorted({k for k, _ in members}, key=_key_sort)
        if len(keys) < 2:
            continue
        if isinstance(target, tuple) and target[0] == 'bl':     # one BrickLink-born local item: nothing to choose between
            result.unresolved.append(tuple(keys))
            continue
        shared = target if isinstance(target, int) else None
        total = {k: sum(_entry_rows(result.items[k], h) for kk, h in members if kk == k) for k in keys}
        preferred = None
        if shared is not None:
            # "the item's preferred link in that colour": the link the resolution function picks, if it carries the preferred flag
            best = best_item_link(cat.bricklink_links(shared), colour if colour is not None else NO_COLOUR)
            preferred = (best['provider_kind'], best['provider_key']) if best and best['preferred'] else None
        ranked = sorted(keys, key=lambda k: (not (preferred and (k[0], k[1]) == preferred), -total[k], k[1], k[0], _key_sort(k)))
        keeper, losers = ranked[0], ranked[1:]
        if preferred and (keeper[0], keeper[1]) == preferred:
            reason = 'preferred_link'
        elif total[keeper] > max(total[k] for k in losers):
            reason = 'most_rows'
        else:
            reason = 'lowest_number'
        for key, holder in members:
            if key == keeper:
                outcome(key, holder).collision = 'keeper'
        for key in losers:
            d = result.items[key]
            if key[0].startswith('?'):                     # no BrickLink number to be born from: an unidentified local item
                item = local(('un', key), d.kind, 'namespace' if d.kind != 'set' else 'bricklink',
                             names.get((key[0][0], key[1]), (None,))[0] or key[1], names.get((key[0][0], key[1]), (None, None))[1],
                             (None, None, None), 'collision')
            else:
                item = bl_born(key[0], key[1], 'collision')
            if shared is not None:
                ns, born_key, _ = cat.born(shared)
                item.links[('rebrickable', ns, born_key)] = LinkPlan('rebrickable', ns, born_key, 'to_check', 'migration_collision')
            hit = [h for kk, h in members if kk == key]
            for holder in hit:
                o = outcome(key, holder)
                o.collision, o.origin, o.plan_key, o.item_id = 'loser', 'local', item.plan_key, None
            result.collisions.append(Collision(key, keeper, shared if shared is not None else -1, colour if colour is not None else NO_COLOUR,
                                               reason, total[key], total[keeper], holders=tuple(sorted(hit, key=lambda h: (h is not None, holder_label(h)))),
                                               loser_plan_key=item.plan_key))
    # ---- a local item must not carry a born key that exists already (the unique item_born index would refuse the write) ----
    for item in plans.values():
        if item.born_provider is None:
            continue
        clash = db.execute('SELECT id FROM catalogue.item WHERE born_provider=? AND born_namespace=? AND born_key=? UNION ALL '
                           'SELECT id FROM main.item WHERE born_provider=? AND born_namespace=? AND born_key=?',
                           (item.born_provider, item.born_namespace, item.born_key) * 2).fetchone()
        if clash:
            raise MintInvariantError(f'the plan has a local item born {item.born_provider} {item.born_namespace} {item.born_key}, '
                                     f'which item {clash[0]} already has')
    # ---- ids: BrickLink-born by key, Rebrickable-born by key, unidentified by key; only items some row lands on exist ----
    order = {'bl': 0, 'rb': 1, 'un': 2}
    for n, item in enumerate(sorted(plans.values(), key=lambda i: (order[i.plan_key[0]], str(i.plan_key[1:]))), local_base):
        item.local_id = n
        result.local_items.append(item)
        result.names[n] = f'{item.born_provider or "unidentified"} {item.born_namespace or ""} {item.born_key or item.name}'.replace('  ', ' ')
    for d in result.items.values():
        for o in [d, *d.holders.values()]:
            if o.origin == 'local':
                o.item_id = plans[o.plan_key].local_id
    for c in result.collisions:
        c.loser_local_id = plans[c.loser_plan_key].local_id
    # Every (key, holder) target again, local ones included: two 3.3 keys left on one target (losers of one BrickLink number in
    # two colours that map to one) cannot be told apart without merging them, which the mint never does: they are reported.
    known = {frozenset(k) for k in result.unresolved}
    for keys in result.shared_targets():
        if frozenset(keys) not in known:
            result.unresolved.append(keys)
            known.add(frozenset(keys))
    if result.check_injective():
        raise MintInvariantError(f'the plan is not injective: {result.check_injective()[:3]}')
    for d in result.items.values():
        for c in d.candidates:
            if c not in result.names and cat.born(c):
                result.names[c] = f'{cat.born(c)[0]}/{cat.born(c)[1]}'
    for c in result.collisions:
        if c.shared_item_id not in result.names and cat.born(c.shared_item_id):
            result.names[c.shared_item_id] = f'{cat.born(c.shared_item_id)[0]}/{cat.born(c.shared_item_id)[1]}'
    return result


def _entry_rows(d, holder):
    return d.holders[holder].rows if holder is not None else (d.free_rows if d.holders else d.rows)



def _candidates(db, cat, item_type, item_no, kind, colour):
    """Rule 2: every catalogue item the BrickLink key stands for in this colour, of the kind the row needs. G, B, C, I and O also
    find the catalogue set of the same number when the theme-kind table gave it that kind (the set-number rule only links `set`s)."""
    found = set(candidate_items(db, item_type, item_no, colour))
    if item_type in ('G', 'B', 'C', 'I', 'O'):
        by_number = cat.by_born('sets', item_no)
        if by_number is not None:
            found.add(by_number)
    return sorted(i for i in found if cat.kind(i) == kind)




class _Contexts:
    """Rule 4's context of a row: its holder's catalogue list, any version (design 8.3)."""

    def __init__(self, src, result, cat):
        self.src, self.result, self.cat = src, result, cat
        self._holders, self._items = {}, {}

    def holders(self, d):
        """{holder mint key: rows} of a part or figure key. A copy line's holder is the copy's set, a part inside a figure inside a
        copy has (figure, set), a loose figure's part has the loose figure, a figure row has the copy's set. Other tables have none."""
        if d.key in self._holders:
            return self._holders[d.key]
        item_type, item_no, color = d.key
        raw = item_type[0] if item_type.startswith('?') else item_type
        # a colourless key (a set line crossed by rule 6) stands for the rows with colour NULL and 0 alike (see _key_colour)
        same_colour = 'coalesce(p.color_id, 0) = coalesce(?, 0)' if item_type in COLOURLESS else 'p.color_id IS ?'
        out = Counter()
        if d.kind == 'part':
            for t, n, pt, pn, k in self.src.execute(
                    'SELECT c.item_type, c.set_no, p.parent_minifig_type, p.parent_minifig, count(*) FROM copy_parts p JOIN copies c '
                    'ON c.id=p.copy_id WHERE p.item_type=? AND p.item_no=? AND ' + same_colour + ' GROUP BY 1, 2, 3, 4', (raw, item_no, color)):
                set_key = (_typed(t, n, 'S'), n, None)
                out[((_typed(pt, pn, 'M'), pn, None), set_key) if pn is not None else set_key] += k
            for t, n, c, k in self.src.execute(
                    'SELECT s.item_type, s.item_no, s.color_id, count(*) FROM loose_minifig_parts p JOIN loose_stock s ON s.id=p.stock_id '
                    'WHERE p.item_type=? AND p.item_no=? AND ' + same_colour + ' GROUP BY 1, 2, 3', (raw, item_no, color)):
                out[(_typed(t, n, 'M'), n, _key_colour(_typed(t, n, 'M'), c))] += k
        elif d.kind == 'minifigure':
            for t, n, k in self.src.execute('SELECT c.item_type, c.set_no, count(*) FROM copy_minifigs m JOIN copies c ON c.id=m.copy_id '
                                            'WHERE m.item_type=? AND m.minifig_no=? GROUP BY 1, 2', (raw, item_no)):
                out[(_typed(t, n, 'S'), n, None)] += k
        self._holders[d.key] = dict(out)
        return self._holders[d.key]

    def items_of(self, d, holder):
        """The part items (or figure items) of every catalogue inventory of the holder; empty for a holder that is not a catalogue item."""
        if (d.kind, holder) not in self._items:
            if isinstance(holder[0], tuple):               # a figure inside a copy: the figure item that this set resolved it to
                figure, copy_set = holder
                decision = self.result.items.get(figure)
                target = decision and decision.holders.get(copy_set, decision)
            else:
                target = self.result.items.get(holder)
            ok = target is not None and target.origin == 'catalogue' and target.item_id is not None
            self._items[(d.kind, holder)] = self.cat.inventory_items(target.item_id, d.kind) if ok else set()
        return self._items[(d.kind, holder)]


def _typed(item_type, item_no, kind_letter=None):
    """The mint-key type of a 3.3 (type, number): a `?` placeholder carries the kind letter."""
    return '?' + kind_letter if item_type == '?' else item_type


def _colours(src, db, result, ids, local_base):
    """The colour rule: color_link preferring inverse_preferred; an unlinked BrickLink colour is a local colour; NULL is colour 1."""
    result.colours[None] = ColourDecision(None, NO_COLOUR, 'catalogue', 'null', name='[No Color/Any Color]', note='NULL on the row')
    info = {c: (n, t, rgb) for c, n, t, rgb in src.execute('SELECT color_id, name, type, rgb FROM colors')}
    local = []
    for bl in sorted(ids):
        rows = {}
        for store in ('main', 'catalogue'):
            for color_id, flag in db.execute(f"SELECT color_id, inverse_preferred FROM {store}.color_link WHERE provider='bricklink' "
                                             f"AND provider_key=? AND status IN ({_IN})", (str(bl), *CONFIRMED)):
                rows[color_id] = max(rows.get(color_id, 0), flag)
        candidates = tuple(sorted(rows))
        name = info.get(bl, (None,))[0]
        try:
            found = _inverse_color(db, 'bricklink', str(bl))
        except AmbiguousIdentity:
            found = None
            note = 'several colours share this BrickLink colour and none is inverse_preferred: kept apart as a local colour'
            rule = 'local_ambiguous'
        else:
            note, rule = '', 'local'
        if found is not None:
            rule = 'inverse_preferred' if len(candidates) > 1 else 'link'
            result.colours[bl] = ColourDecision(bl, found, 'catalogue', rule, candidates, name,
                                                f'shared with {[c for c in candidates if c != found]}' if len(candidates) > 1 else '')
        else:
            local.append((bl, candidates, name, rule, note))
    for n, (bl, candidates, name, rule, note) in enumerate(local, local_base):
        _, kind_type, rgb = info.get(bl, (None, None, None))
        result.colours[bl] = ColourDecision(bl, n, 'local', rule, candidates, name, note)
        result.local_colours.append(LocalColour(n, bl, name or f'BrickLink colour {bl}', rgb, int(bool(kind_type) and kind_type.startswith('Trans')),
                                                rule))

