"""The 3.3 -> 4.0 migration writer (design 8.1, 8.2, 8.4, 8.5, 8.9, 8.10; issue #109, M.7b).

`Migration(src_path, catalogue_path, out_path)` reads a 3.3 store read-only and writes a new 4.0 collection file beside `out_path`
under a temporary name. `write()` does all of it in ONE transaction with deferred foreign keys: the mint (`mint.mint`, run first,
against the new collection), the activation of the catalogue (builds, binding, high-water marks, every catalogue colour), the
local colours and items of the mint plan, every referenced catalogue item (projected on first reference, as the store does
elsewhere), then the tables of 8.4 one by one, the settings (8.10) and exactly one migration event. It returns a `MigrationResult`
with everything M.7c's report and proof need.

The seam for M.7c (attach, proof, report files, publish on PASS): after `write()` the file is committed but still under its
temporary name, and `m.db` is the open 4.0 collection (catalogue attached read-only), `m.src` the open 3.3 store. M.7c may write more
inside its own transaction (attaching part lists), run its read-back proof and the report, then `m.finish(report_digest)` (puts the
digest into `meta.migrated_from`) and `m.publish()`, which is the only call that creates `out_path`. Nothing but `publish()` makes the
file visible, and it refuses to replace an existing `out_path`. `m.abort()` removes the temporary file. The 3.3 file is opened immutable,
which ignores its WAL: the 3.3 app must be stopped (or the file be a copy) for the whole run, and `check_inputs()` (also run by
`write()` and `publish()`) refuses a non-empty `-wal`. The inputs are never written; `check_inputs()` compares their sha256 with the start (and `publish()` does it again).

`migrate(...)` is `Migration(...)` followed by `write()`; it returns the open `Migration`.

Where a 3.3 row cannot be carried by the 4.0 constraints the writer does not guess: a count that breaks its bounds, a component row
without its figure line, a photo or instruction path outside its folder raise `NeedsDecision` with the rows listed, and nothing is
published. What is dropped on purpose is in the result, never silent."""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

from . import identity
from .activate import apply_activation
from .audit import Events, transaction
from .bldigest import bl_digest, inventory_digest
from .connect import connect, now
from .errors import Store4Error
from .mint import NO_COLOUR, TYPE_KIND, MintResult, _kind_by_number, mint
from .seeds import LOCAL_BASE

VIA = 'migration'
SAMPLE_ROWS = 5                                              # rows shown per not-carried table
CONDITION = {'N': 'new', 'U': 'used'}
STOCK_CONDITION = {'N': 'new', 'U': 'used', 'D': 'damaged'}
COMPLETENESS = {'S': 'sealed', 'C': 'complete', 'I': 'incomplete'}
STORAGE_TYPES = ('Box', 'Shelf', 'Drawer', 'Bin', 'Bag', 'Case', 'Cabinet', 'Room', 'Other')
PLACE_KINDS = ('BrickLink store', 'Online shop', 'Shop', 'Market', 'Fair', 'Private', 'Other')
# The 3.3 default of source_priority (importer/projection.py PRIORITY), to tell a default from a changed step in the report.
PRIORITY_33 = {'identity': {'*': ['bricklink:local', 'bricklink:api']}, 'inventory': {'*': ['bricklink:subsets']},
               'matching': {'*': ['rebrickable', 'part_resolutions', 'manual']}, 'pictures': {'P': ['rebrickable', 'bricklink'], '*': ['bricklink', 'rebrickable']},
               'metadata': {'S': ['brickset']}, 'market_price': {'*': ['bricklink']}}
CARRIED_PRIORITY_STEPS = ('pictures', 'metadata', 'market_price')    # the other steps change meaning in 4.0 (design 8.10)
# The 4.0 picture sources (design 6.8) and their defaults per kind. 3.3 had two: `rebrickable` (the API, for parts and sets) and `bricklink`.
PICTURES_40 = {'part': ['rebrickable_dump', 'bricklink', 'rebrickable_api'], '*': ['bricklink', 'rebrickable_dump']}


def translate_pictures(kind, order, was_default):
    """A 3.3 picture order for one kind in 4.0's source names (M.8f): the 3.3 default becomes the 4.0 default of that kind; any other
    order keeps its sequence with `rebrickable` replaced by `rebrickable_dump` and `rebrickable_api` (the dump first, at its place)."""
    if was_default:
        return list(PICTURES_40[kind if kind in PICTURES_40 else '*'])
    out = []
    for source in order:
        for new in (['rebrickable_dump', 'rebrickable_api'] if source == 'rebrickable' else [source]):
            if new not in out:
                out.append(new)
    return out
CARRIED_SETTINGS = re.compile(r'bricklink_region|bricklink_currency|incomplete_discount_pct|repair_\w+|retail_country|display_currency')
# A 3.3 event names its row as `<table>:<id>` or, from the 3.2 import, `<table>:{"id": ...}`.
EVENT_KINDS = {'copy': 'copy', 'copies': 'copy', 'stock': 'stock', 'loose_stock': 'stock', 'flags': 'flag', 'flag': 'flag',
               'storages': 'storage', 'storage': 'storage', 'purchase_locations': 'place', 'lot': 'lot', 'lots': 'lot',
               'wishlist': 'wish', 'wishlists': 'wishlist', 'copy_minifigs': 'copy_figure'}
# 3.3 tables read only for the report (design 8.1 "not carried"): name -> (SELECT of the rows, why)
NOT_CARRIED = {
    'events': ('SELECT * FROM events ORDER BY id', 'the audit log; 4.0 starts a fresh one (this file stays in Borg)'),
    'fetch_log': ('SELECT * FROM fetch_log ORDER BY id', 'the fetch log'),
    'import_receipts': ('SELECT * FROM import_receipts', 'import receipts'),
    'source_records': ('SELECT source, kind, source_id, status, fetched_at, length(payload) AS payload_bytes FROM source_records',
                       'raw API replies'),
    'jobs': ('SELECT * FROM jobs ORDER BY id', 'jobs'),
    'import_steps': ('SELECT * FROM import_steps', 'import steps'),
    'import_calls': ('SELECT * FROM import_calls', 'import calls'),
    'import_owners': ('SELECT * FROM import_owners', 'import owners'),
    'inventory_lines': ('SELECT * FROM inventory_lines ORDER BY id', 'the BrickLink-sourced lists (re-choosing BrickLink costs one call each) '
                        'and the Rebrickable-translated ones'),
    'id_match': ('SELECT * FROM id_match', 'identity decisions; the manual ones are listed in full (manual_decisions)'),
    'orders': ('SELECT * FROM orders ORDER BY id', 'orders (decision B)'),
    'order_documents': ('SELECT * FROM order_documents ORDER BY id', 'order documents (B)'),
    'order_lines': ('SELECT * FROM order_lines ORDER BY id', 'order lines (B)'),
    'line_receipts': ('SELECT * FROM line_receipts', 'line receipts (B)'),
    'line_receipt_log': ('SELECT * FROM line_receipt_log ORDER BY id', 'line receipt log (B)'),
    'allocations': ('SELECT * FROM allocations ORDER BY id', 'allocations (B)'),
    'identifications': ('SELECT * FROM identifications', 'identifications (B)'),
    'identification_actions': ('SELECT * FROM identification_actions ORDER BY id', 'identification actions (B)'),
    'match_history': ('SELECT * FROM match_history ORDER BY id', 'Take/Give history (B)'),
    'item_images': ("SELECT * FROM item_images WHERE kind!='own' ORDER BY id", 'cached pictures: plain downloads, re-fetched by jobs'),
    'item_properties': ('SELECT * FROM item_properties', 'item properties: re-fetched by jobs'),
    'exchange_rates': ('SELECT * FROM exchange_rates', 'exchange rates: ECB rates are re-fetched, manual ones are listed to re-enter'),
    'part_check sessions (settings checker:*)': ("SELECT key, substr(value, 1, 120) AS value FROM settings WHERE key LIKE 'checker:%'",
                                                 'check sessions restart'),
    'budget counters (settings source:*)': ("SELECT key, value FROM settings WHERE key LIKE 'source:%'",
                                            'budget counters and last attempts: BrickLink starts the cutover day at 0'),
    'sync baselines and counters (settings sync:*)': ("SELECT key, substr(value, 1, 120) AS value FROM settings WHERE key LIKE 'sync:%' "
                                                       "AND key NOT LIKE 'sync:%:link'",
                                                       'sync baseline, last pull and last send: the first sync shows a full comparison'),
}


class MigrationError(Store4Error):
    """The migration cannot proceed or publish."""


class NeedsDecision(MigrationError):
    """3.3 rows the 4.0 constraints cannot take as they are; `.rows` lists them (dicts). Nothing is published."""

    def __init__(self, message, rows):
        super().__init__(message)
        self.rows = rows


@dataclass
class MigrationResult:
    migrated_at: str = None
    source: dict = field(default_factory=dict)               # file name, sha256, bytes
    catalogue: dict = field(default_factory=dict)            # file name, sha256, catalogue_id
    install_id: str = None
    mint: MintResult = None
    activation: dict = field(default_factory=dict)
    tables: list = field(default_factory=list)               # [{'from', 'to', 'rows_33', 'rows_40', 'note'}]
    summed_lines: list = field(default_factory=list)         # Q7: rows summed into one line
    extras: list = field(default_factory=list)               # 8.5: every changed row before and after
    extras_skipped_foreign_ref: list = field(default_factory=list)   # rows whose source_ref is no BrickLink line of their set: not corrected
    timestamp_rules: dict = field(default_factory=lambda: defaultdict(Counter))
    money_fills: list = field(default_factory=list)          # 8.9: price without currency, filled
    money_currency_dropped: list = field(default_factory=list)   # currency without a price, set to NULL
    count_fixes: list = field(default_factory=list)          # 8.9: quantity NULL read as 0
    non_part_lines: list = field(default_factory=list)       # copy_parts rows of a non-part kind that copy_part cannot take
    type_crossed: list = field(default_factory=list)         # rule 6 of the mint: part-table rows filed under G/B/C/I/O, carried as the part
    figure_lines_retained_duplicate: list = field(default_factory=list)   # copy_parts figure lines dropped because copy_minifigs has the figure
    figure_lines_from_parts: list = field(default_factory=list)   # copy_parts rows of a minifigure carried as copy_figure lines
    value_fixes: list = field(default_factory=list)          # a value the 4.0 constraint does not allow, changed (listed)
    sources_added: list = field(default_factory=list)
    settings: list = field(default_factory=list)             # 8.10: every key carried / translated / dropped
    not_carried: dict = field(default_factory=dict)          # name -> {'count', 'samples', 'why'}
    manual_decisions: list = field(default_factory=list)     # 8.1 C: the manual id_match rows in full
    to_check: list = field(default_factory=list)
    unmatched: list = field(default_factory=list)
    wish_ids: dict = field(default_factory=dict)             # 3.3 integer wish id -> 4.0 uuid
    price_current: dict = field(default_factory=dict)        # recomputed vs 3.3
    attach: list = field(default_factory=list)               # 8.6: one record per copy, figure line and loose figure: attached or migrated, and why
    foreign_key_check: list = field(default_factory=list)
    integrity_check: str = None
    inputs_unchanged: bool = None
    seconds: float = None

    def counts(self):
        return {t['to']: t['rows_40'] for t in self.tables}

    def attach_counts(self):
        """{kind: {'total', 'attached', 'reasons': {reason: n}}} over the attach records (kinds copy, figure, loose_figure)."""
        out = {}
        for a in self.attach:
            c = out.setdefault(a['kind'], {'total': 0, 'attached': 0, 'reasons': {}})
            c['total'] += 1
            if a['status'] == 'attached':
                c['attached'] += 1
            else:
                c['reasons'][a['reason']] = c['reasons'].get(a['reason'], 0) + 1
        return out


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def open_source(path):
    """The 3.3 store, read-only and immutable (plain `-readonly` did not work on the real copy); only ever SELECTed."""
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    db.row_factory = sqlite3.Row
    try:
        version = db.execute('SELECT version FROM schema_meta').fetchone()
    except sqlite3.DatabaseError as error:
        db.close()
        raise MigrationError(f'{path} is not a Brick Work 3.3 store: {error}') from None
    if version is None or version[0] != '3.3':
        db.close()
        raise MigrationError(f'{path} is schema {version and version[0]!r}, not 3.3: open it with the 3.3 app to upgrade it first')
    return db


def _normal(at):
    """An event time in the form 4.0 stamps (UTC, milliseconds, Z)."""
    try:
        parsed = datetime.fromisoformat(at.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return at
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def _event_key(entity):
    m = re.fullmatch(r'(\w+):(.*)', entity, re.S)
    if not m or m.group(1) not in EVENT_KINDS:
        return None
    kind, rest = EVENT_KINDS[m.group(1)], m.group(2)
    if rest.startswith('{'):
        try:
            data = json.loads(rest)
        except ValueError:
            return None
        rest = (data['copy_id'], data['item_type'], data['minifig_no']) if kind == 'copy_figure' else data.get('id')
    return (kind, rest if isinstance(rest, tuple) else str(rest))


def _short(value, n=200):
    return value if value is None or len(value) <= n else value[:n] + '...'


class Migration:
    def __init__(self, src_path, catalogue_path, out_path, *, actor='migration'):
        self.src_path, self.catalogue_path, self.out_path = Path(src_path), Path(catalogue_path), Path(out_path)
        self.actor = actor
        self.result = MigrationResult()
        self.db = self.src = self.temp_path = None
        self._hashes = {}
        self._published = False
        self._written = False
        self._begin()

    # ---- life cycle ----

    def _begin(self):
        for name, path in (('3.3 file', self.src_path), ('catalogue', self.catalogue_path)):
            if not path.is_file():
                raise MigrationError(f'the {name} {path} does not exist')
        if self.out_path.exists() or self.out_path.is_symlink():
            raise FileExistsError(f'{self.out_path} exists: the migration creates its output exclusively')
        for name, path in (('3.3 file', self.src_path), ('catalogue', self.catalogue_path)):
            if path.resolve() == self.out_path.resolve():
                raise MigrationError(f'the output is the {name}')
            self._hashes[name] = sha256_file(path)
        self._check_wal()
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self.temp_path = self.out_path.with_name(f'.{self.out_path.name}.{uuid.uuid4().hex}.migrating')
        self.src = open_source(self.src_path)
        try:
            self.db = connect(self.temp_path, self.catalogue_path)
        except BaseException:
            self.abort()
            raise
        self.result.source = {'name': self.src_path.name, 'sha256': self._hashes['3.3 file'], 'bytes': self.src_path.stat().st_size}
        self.result.catalogue = {'name': self.catalogue_path.name, 'sha256': self._hashes['catalogue']}

    def _check_wal(self):
        wal = Path(str(self.src_path) + '-wal')
        if wal.exists() and wal.stat().st_size:
            raise MigrationError(f'{wal} holds changes that are not in {self.src_path.name}, and the read-only immutable open cannot see them: '
                                 'the 3.3 app must be stopped (or the file be a copy) for the whole run')

    def check_inputs(self):
        """The two input files are byte-identical to the start of the run."""
        self._check_wal()
        same = all(sha256_file(p) == self._hashes[n] for n, p in (('3.3 file', self.src_path), ('catalogue', self.catalogue_path)))
        self.result.inputs_unchanged = same
        if not same:
            raise MigrationError('an input file changed during the migration')
        return same

    def write(self, *, record_event=True):
        """All of the migration in one transaction. `record_event=False` leaves the migration event to `record_event()` (M.7c, when the
        event should carry the report digest; an event cannot be edited afterwards)."""
        if self._written:
            raise MigrationError('write() runs once')
        self._check_wal()
        started = time.monotonic()
        try:
            _Writer(self, record_event).run()
        except BaseException:
            self.abort()
            raise
        self._written = True
        self.check_inputs()
        self.result.seconds = time.monotonic() - started
        return self.result

    def record_event(self, report_digest=None):
        """The one migration event, written after the fact (only with `write(record_event=False)`)."""
        with transaction(self.db, 'the migration event'):
            _write_event(self, report_digest)

    def finish(self, report_digest):
        """Put the report digest (summary.md and proof.json) into `meta.migrated_from`."""
        with transaction(self.db, 'the migration digest'):
            value = json.loads(self.db.execute("SELECT value FROM meta WHERE key='migrated_from'").fetchone()[0])
            value['report_digest'] = report_digest
            self.db.execute("UPDATE meta SET value=? WHERE key='migrated_from'", (json.dumps(value, sort_keys=True),))

    def publish(self):
        """Make the file visible as `out_path` (exclusive: an existing file is never replaced). M.7c calls it only on PASS."""
        if not self._written or self._published:
            raise MigrationError('nothing to publish' if not self._written else 'already published')
        self.check_inputs()
        self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        self.db.close()
        self.src.close()
        try:
            os.link(self.temp_path, self.out_path)           # exclusive: raises FileExistsError if the output appeared meanwhile
        finally:
            self._cleanup()
        self._published = True
        return self.out_path

    def abort(self):
        for db in (self.db, self.src):
            if db is not None:
                try:
                    db.close()
                except sqlite3.Error:
                    pass
        self._cleanup()

    def _cleanup(self):
        if self.temp_path is not None:
            for suffix in ('', '-wal', '-shm', '-journal'):
                Path(str(self.temp_path) + suffix).unlink(missing_ok=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if not self._published:
            self.abort()


def migrate(src_path, catalogue_path, out_path, *, actor='migration', record_event=True):
    """Begin a migration and run `write()`. Returns the open `Migration`; the caller publishes (or aborts) it."""
    m = Migration(src_path, catalogue_path, out_path, actor=actor)
    m.write(record_event=record_event)
    return m


def _write_event(m, report_digest):
    r = m.result
    Events(m.db, VIA, m.actor).write('migration', r.install_id, 'migrated_from', None, {
        'file': r.source['name'], 'sha256': r.source['sha256'], 'catalogue_sha256': r.catalogue['sha256'],
        'report_digest': report_digest, 'rows': r.counts()})


class _Writer:
    def __init__(self, m, record_event):
        self.m, self.src, self.db, self.r = m, m.src, m.db, m.result
        self.record_event = record_event
        self.migrated_at = self.r.migrated_at = now()
        self.decisions = []                                   # rows that need Ulf's decision: raised together
        self.projected = set()
        self._kinds = {}
        self.currency = None
        self.bl_figure_lines = {}                             # (copy, figure item) -> its component lines in BrickLink space
        self.bl_copy_lines = {}                               # copy -> its lines in BrickLink space
        self.bl_stock_lines = {}                              # stock id -> a loose figure's component lines in BrickLink space
        self.figure_rows = {}                                 # (copy, figure item) -> copy_figure id, own digest, 3.3 reference

    # ---- driver ----

    def run(self):
        db, r = self.db, self.r
        with transaction(db, 'the migration'):
            db.execute('PRAGMA defer_foreign_keys=ON')
            r.install_id = db.execute("SELECT value FROM meta WHERE key='install_id'").fetchone()[0]
            self.mint = r.mint = mint(self.src, db)           # first, against the new collection, before anything is written
            r.activation, _ = apply_activation(db)
            self.first_event = self._first_events()
            self.currency = (self.src.execute("SELECT value FROM settings WHERE key='bricklink_currency'").fetchone() or [None])[0] or 'EUR'
            self._local_colours()
            self._local_items()
            self._sources()
            self._storage_place_lot_flag()
            self._wishlists()
            self._copies()
            self._stock()
            self._attach()
            self._flags()
            self._wishes()
            self._photos_instructions()
            self._prices()
            self._keys_tokens()
            self._settings()
            self._not_carried()
            self._meta()
            if self.decisions:
                raise NeedsDecision(f'{len(self.decisions)} 3.3 row(s) need a decision before they can be migrated: '
                                    f'{self.decisions[0]["why"]} (first); see .rows', self.decisions)
            self._counts()
            r.foreign_key_check = [tuple(row) for row in db.execute('PRAGMA foreign_key_check')]
            if r.foreign_key_check:
                raise MigrationError(f'foreign_key_check found {len(r.foreign_key_check)} violation(s), first {r.foreign_key_check[0]}')
            if self.record_event:
                _write_event(self.m, None)
        r.integrity_check = db.execute('PRAGMA integrity_check').fetchone()[0]
        if r.integrity_check != 'ok':
            raise MigrationError(f'integrity_check: {r.integrity_check}')

    # ---- helpers ----

    def _first_events(self):
        out = {}
        for entity, at in self.src.execute('SELECT entity, min(at) FROM events GROUP BY entity'):
            key = _event_key(entity)
            if key is not None and at is not None:
                at = _normal(at)
                if key not in out or at < out[key]:
                    out[key] = at
        return out

    def stamp(self, label, value, kind=None, ident=None, *fallbacks):
        """A NOT NULL timestamp (design 8.9). A carried value is kept; else the earliest 3.3 event of the row, then the named own
        fallbacks in order, then the migration time. Counted per rule."""
        counter = self.r.timestamp_rules[label]
        if value is not None:
            counter['carried'] += 1
            return value
        event = self.first_event.get((kind, ident if isinstance(ident, tuple) else str(ident))) if kind else None
        if event:
            counter['event'] += 1
            return event
        for name, v in fallbacks:
            if v is not None:
                counter[name] += 1
                return v
        counter['migration_time'] += 1
        return self.migrated_at

    def stamp_event_first(self, label, kind, ident, own):
        """The six fields design 8.9 names: the earliest event first, even where the row has an own `updated_at`."""
        return self.stamp(label, None, kind, ident, ('updated_at', own))

    def money(self, label, ref, price, currency):
        if price is None:
            if currency is not None:
                self.r.money_currency_dropped.append({'table': label, 'row': ref, 'currency': currency})
            return None, None
        if currency is None:
            self.r.money_fills.append({'table': label, 'row': ref, 'price': price, 'currency': self.currency})
            return price, self.currency
        return price, currency

    def counts(self, label, ref, quantity, missing, damaged=0):
        """Today's bounds (design 8.9): a NULL quantity is 0 when nothing is missing or damaged, else a decision."""
        m_, d_ = missing or 0, damaged or 0
        if quantity is None:
            if m_ == 0 and d_ == 0:
                self.r.count_fixes.append({'table': label, 'row': ref, 'quantity': None, 'to': 0})
                return 0, m_, d_
            self.decisions.append({'table': label, 'row': ref, 'why': f'{label} {ref}: quantity is NULL but missing={missing} damaged={damaged}'})
            return 0, 0, 0
        if quantity < 0 or m_ < 0 or d_ < 0 or m_ > quantity or d_ > quantity:
            self.decisions.append({'table': label, 'row': ref, 'why': f'{label} {ref}: quantity={quantity} missing={missing} damaged={damaged} break the bounds'})
            return 0, 0, 0
        return quantity, m_, d_

    def tgt(self, item_type, item_no, color=None, kind=None, holder=None):
        """The 4.0 (item, colour) of a 3.3 row; the item is in the collection (projected on first reference) afterwards."""
        if item_type == '?' and kind is None:
            kind = _kind_by_number(item_no)
        t = self.mint.target(item_type, item_no, color, kind=kind, holder=holder)
        if t.item_id < LOCAL_BASE and t.item_id not in self.projected:
            identity.project(self.db, t.item_id)
            self.projected.add(t.item_id)
        return t

    def item_kind(self, item_id):
        if item_id not in self._kinds:
            self._kinds[item_id] = self.db.execute('SELECT kind FROM main.item WHERE id=?', (item_id,)).fetchone()[0]
        return self._kinds[item_id]

    def kind_of(self, item_type, item_no, kind=None):
        if item_type == '?':
            return kind or _kind_by_number(item_no)
        return TYPE_KIND[item_type]

    def set_key(self, item_type, set_no):
        return MintResult.key_of(item_type, set_no, None, 'set')

    def colour_or_none(self, kind, target):
        return target.color_id if kind == 'part' else None

    def insert(self, table, columns, rows):
        rows = list(rows)
        if rows:
            self.db.executemany(f'INSERT INTO main.{table}({", ".join(columns)}) VALUES({", ".join("?" * len(columns))})', rows)
        return len(rows)

    def note(self, src_table, dst_table, rows_33, note=''):
        self.r.tables.append({'from': src_table, 'to': dst_table, 'rows_33': rows_33, 'rows_40': None, 'note': note})

    # ---- local colours and items (the mint plan) ----

    def _local_colours(self):
        stamp = self.migrated_at
        for c in self.mint.local_colours:
            self.db.execute('''INSERT INTO main.color(id, origin, name, rgb, is_trans, born_provider, born_key, created_at, updated_at)
                               VALUES(?, 'local', ?, ?, ?, 'bricklink', ?, ?, ?)''', (c.local_id, c.name, c.rgb, c.is_trans, str(c.bl_id), stamp, stamp))
            # the colour must be found again from the BrickLink id: the local colour holds the inverse preference of its key
            self.db.execute('''INSERT INTO main.color_link(color_id, provider, provider_key, provider_name, status, method, inverse_preferred,
                               decided_at, decided_by) VALUES(?, 'bricklink', ?, ?, 'matched', 'migration', 1, ?, 'migration')''',
                            (c.local_id, str(c.bl_id), c.name, stamp))
        self.note('colors', 'color, color_link', self.src.execute('SELECT count(*) FROM colors').fetchone()[0],
                  f'{len(self.mint.local_colours)} local colours; every catalogue colour projected by the activation')

    def _local_items(self):
        stamp = self.migrated_at
        category = {(t, n): c for t, n, c in self.src.execute('SELECT item_type, item_no, category FROM items')}
        for item in self.mint.local_items:
            if item.plan_key[0] == 'bl':
                old = (item.plan_key[1], item.plan_key[2])
            elif item.plan_key[0] == 'rb':
                old = ('?', 'rebrickable:' + item.plan_key[2])
            else:
                old = ('?', item.plan_key[1][1])
            self.db.execute('''INSERT INTO main.item(id, origin, kind, kind_source, name, year, category_name, born_provider, born_namespace,
                               born_key, created_at, updated_at) VALUES(?, 'local', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                            (item.local_id, item.kind, item.kind_source, item.name or old[1], item.year, category.get(old), item.born_provider,
                             item.born_namespace, item.born_key, stamp, stamp))
            for link in item.links.values():
                self.db.execute('''INSERT INTO main.item_link(item_id, color_id, provider, provider_kind, provider_key, status, method, origin,
                                   preferred, decided_at, decided_by) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 'migration')''',
                                (item.local_id, link.color_id, link.provider, link.provider_kind, link.provider_key, link.status, link.method,
                                 link.origin, stamp))
            for provider, status, reason in sorted(item.provider_status):
                self.db.execute('INSERT INTO main.item_provider_status(item_id, provider, status, reason, checked_at) VALUES(?, ?, ?, ?, ?)',
                                (item.local_id, provider, status, reason, stamp))
        self.note('items', 'item, item_link, item_provider_status', self.src.execute('SELECT count(*) FROM items').fetchone()[0],
                  f'{len(self.mint.local_items)} local items; every referenced catalogue item projected on first reference')

    def _sources(self):
        """3.3 source ids the 4.0 seed does not know, if a carried row names them."""
        have = {r[0] for r in self.db.execute('SELECT id FROM main.source')}
        used = {r[0] for r in self.src.execute('SELECT DISTINCT source FROM price_observations')}
        used |= {r[0] for r in self.src.execute('SELECT DISTINCT source FROM source_freshness')}
        used |= {m.group(1) for (k,) in self.src.execute("SELECT key FROM settings WHERE key LIKE 'sync:%:link'")
                 if (m := re.fullmatch(r'sync:(.+):link', k))}
        for source, name, kind, enabled in self.src.execute('SELECT source, name, kind, enabled FROM sources ORDER BY source'):
            if source in used and source not in have:
                self.db.execute('INSERT INTO main.source(id, name, kind, enabled) VALUES(?, ?, ?, ?)', (source, name, kind, enabled))
                self.r.sources_added.append({'id': source, 'name': name, 'kind': kind})

    # ---- storage, place, lot, flag ----

    def _checked_enum(self, table, ref, field_name, value, allowed):
        if value is not None and value not in allowed:
            self.r.value_fixes.append({'table': table, 'row': ref, 'field': field_name, 'was': value, 'now': 'Other'})
            return 'Other'
        return value

    def _storage_place_lot_flag(self):
        src = self.src
        rows = src.execute('SELECT * FROM storages ORDER BY id').fetchall()
        self.insert('storage', ['id', 'name', 'type', 'parent_id', 'note', 'created_at', 'archived_at'], (
            (s['id'], s['name'] if s['name'] is not None else s['id'], self._checked_enum('storage', s['id'], 'type', s['type'], STORAGE_TYPES),
             s['parent_id'], s['note'], self.stamp_event_first('storage.created_at', 'storage', s['id'], None), s['archived_at']) for s in rows))
        self.note('storages', 'storage', len(rows))
        rows = src.execute('SELECT * FROM purchase_locations ORDER BY id').fetchall()
        self.insert('place', ['id', 'name', 'kind', 'created_at', 'archived_at'], (
            (p['id'], p['name'] if p['name'] is not None else p['id'], self._checked_enum('place', p['id'], 'kind', p['kind'], PLACE_KINDS),
             self.stamp_event_first('place.created_at', 'place', p['id'], None), p['archived_at']) for p in rows))
        self.note('purchase_locations', 'place', len(rows))
        rows = src.execute('SELECT * FROM lots ORDER BY id').fetchall()
        out = []
        for l in rows:
            price, currency = self.money('lot', l['id'], l['purchase_price'], l['purchase_currency'])
            created = self.stamp('lot.created_at', l['created_date'], 'lot', l['id'])
            out.append((l['id'], l['name'] if l['name'] is not None else l['id'], l['note'], l['storage_id'], l['purchase_location_id'],
                        l['purchase_date'], price, currency, created, self.stamp_event_first('lot.updated_at', 'lot', l['id'], None),
                        l['archived_at']))
        self.insert('lot', ['id', 'name', 'note', 'storage_id', 'place_id', 'purchase_date', 'purchase_price', 'purchase_currency',
                            'created_at', 'updated_at', 'archived_at'], out)
        self.note('lots', 'lot', len(rows))
        rows = src.execute('SELECT * FROM flags ORDER BY id').fetchall()
        self.insert('flag', ['id', 'name', 'kind', 'shown_on_grid', 'system', 'created_at', 'archived_at'], (
            (f['id'], f['name'] if f['name'] is not None else f['id'], f['kind'], f['shown_on_grid'], 0,
             self.stamp_event_first('flag.created_at', 'flag', f['id'], None), f['archived_at']) for f in rows))
        self.note('flags', 'flag', len(rows))

    def _wishlists(self):
        rows = self.src.execute('SELECT * FROM wishlists ORDER BY id').fetchall()
        for w in rows:                                        # the 4.0 schema seeds 'default'
            self.db.execute('''INSERT INTO main.wishlist(id, name, note, sort, bricklink_id, created_at, archived_at) VALUES(?, ?, ?, ?, ?, ?, ?)
                               ON CONFLICT(id) DO UPDATE SET name=excluded.name, note=excluded.note, sort=excluded.sort,
                               bricklink_id=excluded.bricklink_id, created_at=excluded.created_at, archived_at=excluded.archived_at''',
                            (w['id'], w['name'], w['note'], w['sort'], w['bricklink_id'],
                             self.stamp('wishlist.created_at', w['created_at'], 'wishlist', w['id']), w['archived_at']))
        self.note('wishlists', 'wishlist', len(rows))

    # ---- copies ----

    def _copies(self):
        src, r = self.src, self.r
        copies = src.execute('SELECT * FROM copies ORDER BY id').fetchall()
        copy_set = {c['id']: (c['item_type'], c['set_no']) for c in copies}
        # copy_minifigs -> figure lines, keyed (copy, item id)
        figures = {}
        for f in src.execute('SELECT * FROM copy_minifigs ORDER BY copy_id, item_type, minifig_no'):
            copy_id = f['copy_id']
            holder = self.set_key(*copy_set[copy_id])
            t = self.tgt(f['item_type'], f['minifig_no'], None, 'minifigure', holder)
            ref = f'copy {copy_id} figure {f["item_type"]}:{f["minifig_no"]}'
            q, m_, _ = self.counts('copy_minifigs', ref, f['quantity'], f['missing'])
            figures[(copy_id, t.item_id)] = {'quantity': q, 'missing': m_, 'old': (copy_id, f['item_type'], f['minifig_no']),
                                              'updated_at': f['updated_at'], 'rows': 1, 'canonical': True}
        parts = self._copy_part_lines(copy_set)
        # lines
        figure_parts = defaultdict(list)                       # (copy, figure item) -> [line dict]
        set_parts = defaultdict(list)
        for line in parts:
            if line['figure_item'] is None:
                set_parts[line['copy_id']].append(line)
            else:
                figure_parts[(line['copy_id'], line['figure_item'])].append(line)
        # M lines of a BrickLink list in copy_parts are figure lines in 4.0
        bl_other = defaultdict(list)                          # BrickLink-space lines of rows copy_part cannot hold (they keep a copy from attaching)
        bl_figure_other = defaultdict(list)
        for copy_id, lines in list(set_parts.items()):
            kept = []
            for line in lines:
                if line['kind'] == 'minifigure':
                    self._figure_from_part(figures, line)
                    if line['spare']:
                        bl_other[copy_id].append(self._bl_line(line))
                elif line['kind'] != 'part':
                    r.non_part_lines.append(self._describe(line, f'a {line["kind"]} line: copy_part holds parts only'))
                    bl_other[copy_id].append(self._bl_line(line))
                else:
                    kept.append(line)
            set_parts[copy_id] = kept
        for key in sorted(figure_parts):
            if key in figures:                                 # a component that copy_part cannot hold is listed and out of the digest
                kept = []
                for l in figure_parts[key]:
                    if l['kind'] != 'part':
                        r.non_part_lines.append(self._describe(l, f'a {l["kind"]} line inside a figure: copy_part holds parts only'))
                        bl_figure_other[key].append(self._bl_line(l))
                    else:
                        kept.append(l)
                figure_parts[key] = kept
            if key not in figures:
                self.decisions.append({'table': 'copy_parts', 'row': key, 'why': f'copy {key[0]}: component rows of a figure that has no figure line'})
        copy_rows = []
        for c in copies:
            t = self.tgt(c['item_type'], c['set_no'], None, 'set')
            lines = set_parts.get(c['id'], [])
            digest = inventory_digest([(l['item_id'], l['color_id'], l['spare'], l['quantity']) for l in lines if l['quantity'] > 0],
                                      [(i, f['quantity']) for (cid, i), f in figures.items() if cid == c['id'] and f['quantity'] > 0])
            self.bl_copy_lines[c['id']] = ([self._bl_line(l) for l in lines] + bl_other.get(c['id'], [])
                                           + [self._bl_figure_line(f, i) for (cid, i), f in sorted(figures.items()) if cid == c['id']])
            price, currency = self.money('copy.purchase', c['id'], c['purchase_price'], c['purchase_currency'])
            value, value_currency = self.money('copy.current_value', c['id'], c['current_value'], c['current_value_currency'])
            created = self.stamp_event_first('copy.created_at', 'copy', c['id'], c['updated_at'])
            copy_rows.append((c['id'], t.item_id, 'migrated', None, None, digest, None, None, None, CONDITION.get(c['condition']),
                              COMPLETENESS.get(c['completeness']), c['completeness_source'], c['storage_id'], c['purchase_location_id'],
                              c['purchase_date'], price, currency, c['note'], value, value_currency, c['pinned'], created,
                              c['updated_at'] if c['updated_at'] is not None else created, c['archived_at']))
        self.insert('copy', ['id', 'item_id', 'inventory_source', 'inventory_version', 'fetched_inventory_id', 'inventory_digest',
                             'materialised_at', 'inventory_pending', 'pending_job_id', 'condition', 'completeness', 'completeness_source',
                             'storage_id', 'place_id', 'purchase_date', 'purchase_price', 'purchase_currency', 'note', 'current_value',
                             'current_value_currency', 'pinned', 'created_at', 'updated_at', 'archived_at'], copy_rows)
        self.note('copies', 'copy', len(copies), "'migrated', then attached to Rebrickable versions where equal in BrickLink space (_attach)")
        # figure lines
        ids = {}
        for (copy_id, item_id) in sorted(figures):
            f = figures[(copy_id, item_id)]
            comp = [(l['item_id'], l['color_id'], l['spare'], l['quantity']) for l in figure_parts.get((copy_id, item_id), []) if l['quantity'] > 0]
            updated = self.stamp_event_first('copy_figure.updated_at', 'copy_figure', f['old'], f['updated_at'])
            ids[(copy_id, item_id)] = self.db.execute(
                '''INSERT INTO main.copy_figure(copy_id, item_id, inventory_source, inventory_digest, quantity, missing, updated_at)
                   VALUES(?, ?, 'migrated', ?, ?, ?, ?)''', (copy_id, item_id, inventory_digest(comp), f['quantity'], f['missing'], updated)).lastrowid
            self.figure_rows[(copy_id, item_id)] = {'id': ids[(copy_id, item_id)], 'own_digest': inventory_digest(comp), 'old': f['old']}
            self.bl_figure_lines[(copy_id, item_id)] = ([self._bl_line(l) for l in figure_parts.get((copy_id, item_id), [])]
                                                        + bl_figure_other.get((copy_id, item_id), []))
        self.note('copy_minifigs', 'copy_figure', src.execute('SELECT count(*) FROM copy_minifigs').fetchone()[0],
                  f'{len(r.figure_lines_from_parts)} more from copy_parts lines of a minifigure')
        rows = []
        for copy_id in sorted(set_parts):
            rows += [(copy_id, None, l['item_id'], l['color_id'], l['spare'], l['quantity'], l['missing'], l['damaged'], l['checked'], l['first'])
                     for l in set_parts[copy_id]]
        for key, lines in figure_parts.items():
            if key not in ids:
                continue
            rows += [(key[0], ids[key], l['item_id'], l['color_id'], l['spare'], l['quantity'], l['missing'], l['damaged'], l['checked'], l['first'])
                     for l in lines]
        rows.sort(key=lambda x: x[-1])                         # in 3.3 row order
        self.insert('copy_part', ['copy_id', 'copy_figure_id', 'item_id', 'color_id', 'is_spare', 'quantity', 'missing', 'damaged', 'checked'],
                    (row[:-1] for row in rows))
        self.note('copy_parts', 'copy_part', src.execute('SELECT count(*) FROM copy_parts').fetchone()[0],
                  'Q7 sums, extras corrected, colour NULL -> 1, element_id and source_ref dropped')

    # ---- BrickLink space (design 8.6) ----

    def _bl_key(self, item_id, color_id):
        """The BrickLink (type, number) the catalogue's own links give an item: what the catalogue's bl_digest projects it to."""
        best = identity.best_item_link(identity.confirmed_item_links(self.db, item_id, 'bricklink'), color_id)
        return None if best is None else (best['provider_kind'], best['provider_key'])

    def _bl_line(self, line):
        """A part-table line of 3.3 as BrickLink lists it: `(type, number, colour, is_spare, quantity)`, the line shape of `bldigest`.
        Colour NULL and 0 are both "no colour". A gear/book/... line the mint carried as a part (`type_crossed`) is a `P` line, because that
        is how the catalogue lists it; a line copy_part cannot hold keeps its own type, so its copy never equals a catalogue list. A `?`
        placeholder is projected through the catalogue's link of the item it resolved to; without one the line is type `?`."""
        t = line['item_type']
        colour = None if line['bl_color'] in (None, 0) else str(line['bl_color'])
        if t == '?':
            key = self._bl_key(line['item_id'], line['color_id'])
            return (key[0] if key else '?', key[1] if key else line['item_no'], colour, line['spare'], line['quantity'])
        return ('P' if line['kind'] == 'part' else t, line['item_no'], colour, line['spare'], line['quantity'])

    def _bl_figure_line(self, f, item_id):
        """A copy's figure line as the catalogue lists a figure in a set: `('M', number, None, 0, quantity)`."""
        t, no = f['old'][1], f['old'][2]
        if t == '?':
            key = self._bl_key(item_id, None)
            return (key[0] if key else '?', key[1] if key else no, None, 0, f['quantity'])
        return (t, no, None, 0, f['quantity'])

    def _describe(self, line, why):
        return {'copy_id': line['copy_id'], 'copy_part_ids': line['ids'], 'item_type': line['item_type'], 'item_no': line['item_no'],
                'color_id': line['bl_color'], 'spare': line['spare'], 'quantity': line['quantity'], 'missing': line['missing'],
                'damaged': line['damaged'], 'checked': line['checked'], 'why': why}

    def _figure_from_part(self, figures, line):
        r = self.r
        key = (line['copy_id'], line['item_id'])
        if line['spare']:
            r.non_part_lines.append(self._describe(line, 'a spare minifigure line: copy_figure has no spare'))
            return
        if figures.get(key, {}).get('canonical'):
            # a manual figure line the 3.2 -> 3.3 import retained beside the canonical copy_minifigs row: 0.5.x prefers the canonical row
            r.figure_lines_retained_duplicate.append(self._describe(line, 'a copy_parts figure line beside the copy_minifigs row of the same figure: '
                                                                    'not added, the canonical row stands'))
            return
        entry = figures.setdefault(key, {'quantity': 0, 'missing': 0, 'old': (line['copy_id'], line['item_type'], line['item_no']),
                                         'updated_at': None, 'rows': 0})
        entry['quantity'] += line['quantity']
        entry['missing'] = min(entry['quantity'], entry['missing'] + line['missing'])
        entry['rows'] += 1
        r.figure_lines_from_parts.append(self._describe(line, 'copy_parts line of a minifigure carried as a copy_figure line'))
        if line['damaged'] or line['checked']:
            r.value_fixes.append({'table': 'copy_parts', 'row': line['ids'], 'field': 'damaged/checked',
                                  'was': f'damaged={line["damaged"]} checked={line["checked"]}', 'now': 'dropped (copy_figure has neither)'})

    def _copy_part_lines(self, copy_set):
        """copy_parts -> unique 4.0 lines: extras corrected (8.5), then Q7-summed. Each: dict with the 4.0 target and the counts."""
        src, r = self.src, self.r
        bl_lines = {}
        by_key = defaultdict(list)
        for l in src.execute("SELECT * FROM inventory_lines WHERE source='bricklink' ORDER BY id"):
            bl_lines[l['id']] = l
            by_key[(l['parent_item_type'], l['parent_item_no'], l['child_item_type'], l['child_item_no'], l['color_id'])].append(l)
        has_extras = {(l['parent_item_type'], l['parent_item_no']) for l in bl_lines.values() if l['extra_quantity'] > 0}
        budget = {}                                            # ('ref', copy, line id) | ('key', copy, key) -> extras still to take
        rows = src.execute('SELECT * FROM copy_parts ORDER BY id').fetchall()
        grouped = {}
        for p in rows:
            copy_id = p['copy_id']
            set_type, set_no = copy_set[copy_id]
            ref = f'copy_parts {p["id"]} (copy {copy_id} {p["item_type"]}:{p["item_no"]})'
            quantity, missing, damaged = self.counts('copy_parts', ref, p['quantity'], p['missing'], p['damaged'])
            spare = p['spare'] or 0
            before = (quantity, missing, damaged)
            via = line = None
            if p['parent_minifig'] is None and spare == 0:
                sr = bl_lines.get(p['source_ref'])
                if (sr is not None and (sr['parent_item_type'], sr['parent_item_no']) == (set_type, set_no)
                        and (sr['child_item_type'], sr['child_item_no']) == (p['item_type'], p['item_no']) and sr['color_id'] == p['color_id']):
                    via, line = 'source_ref', sr
                else:
                    keyed = by_key.get((set_type, set_no, p['item_type'], p['item_no'], p['color_id']))
                    if p['source_ref'] is None:                # design 8.5: only rows without a source_ref are matched by key
                        if keyed:
                            via, line = 'key', keyed[0]
                    elif (set_type, set_no) in has_extras:     # a Rebrickable inventory id of the 3.2 -> 3.3 import: left alone, listed
                        r.extras_skipped_foreign_ref.append({'copy_id': copy_id, 'copy_part_id': p['id'], 'item_type': p['item_type'],
                                                             'item_no': p['item_no'], 'color_id': p['color_id'], 'source_ref': p['source_ref'],
                                                             'quantity': p['quantity']})
            if line is not None and line['extra_quantity'] > 0:
                if via == 'source_ref':
                    bkey = ('ref', copy_id, line['id'])
                    total = line['extra_quantity']
                else:
                    bkey = ('key', copy_id, line['parent_item_type'], line['parent_item_no'], line['child_item_type'], line['child_item_no'], line['color_id'])
                    total = sum(k['extra_quantity'] for k in by_key[(set_type, set_no, p['item_type'], p['item_no'], p['color_id'])])
                left = budget.setdefault(bkey, total)
                take = min(left, quantity)
                budget[bkey] = left - take
                if take:
                    quantity -= take
                    missing, damaged = min(missing, quantity), min(damaged, quantity)
                    r.extras.append({'copy_id': copy_id, 'copy_part_id': p['id'], 'item_type': p['item_type'], 'item_no': p['item_no'],
                                     'color_id': p['color_id'], 'matched_by': via, 'inventory_line_id': line['id'],
                                     'extra_quantity': line['extra_quantity'], 'taken': take,
                                     'before': {'quantity': before[0], 'missing': before[1], 'damaged': before[2]},
                                     'after': {'quantity': quantity, 'missing': missing, 'damaged': damaged},
                                     'action': 'dropped' if quantity == 0 else 'reduced'})
                    if quantity == 0:
                        continue                                # a row that reaches 0 is dropped (and listed above)
                    # (a shortfall, extra_quantity above the row's quantity, is visible as taken < extra_quantity in the listing)
            figure_type = p['parent_minifig_type']
            holder = self.set_key(set_type, set_no)
            if figure_type is not None:
                figure_item = self.tgt(figure_type, p['parent_minifig'], None, 'minifigure', holder).item_id
                holder = (MintResult.key_of(figure_type, p['parent_minifig'], None, 'minifigure'), holder)
            else:
                figure_item = None
            t = self.tgt(p['item_type'], p['item_no'], p['color_id'], 'part' if p['item_type'] == '?' else None, holder)
            colour = t.color_id
            kind = self.item_kind(t.item_id)                   # not the 3.3 type: a G line the mint crossed to a part is a part
            if kind == 'part' and p['item_type'] not in ('P', '?'):
                r.type_crossed.append({'table': 'copy_parts', 'copy_part_id': p['id'], 'copy_id': copy_id, 'item_type': p['item_type'],
                                       'item_no': p['item_no'], 'holder': holder, 'item_id': t.item_id})
            key = (copy_id, figure_item, t.item_id, colour, spare)
            entry = grouped.get(key)
            row = {'copy_id': copy_id, 'figure_item': figure_item, 'item_id': t.item_id, 'color_id': colour, 'spare': spare, 'kind': kind,
                   'quantity': quantity, 'missing': missing, 'damaged': damaged, 'checked': int(bool(p['checked'])), 'first': p['id'], 'ids': [p['id']],
                   'item_type': p['item_type'], 'item_no': p['item_no'], 'bl_color': p['color_id'], 'sources': [(p['id'], quantity, missing, damaged)]}
            if entry is None:
                grouped[key] = row
            else:
                entry['quantity'] += quantity
                entry['missing'] += missing
                entry['damaged'] += damaged
                entry['checked'] = min(entry['checked'], row['checked'])
                entry['ids'].append(p['id'])
                entry['sources'].append((p['id'], quantity, missing, damaged))
        out = sorted(grouped.values(), key=lambda l: l['first'])
        for l in out:
            if len(l['ids']) > 1:
                r.summed_lines.append({'table': 'copy_parts', 'copy_id': l['copy_id'], 'item_type': l['item_type'], 'item_no': l['item_no'],
                                       'color_id': l['bl_color'], 'spare': l['spare'], 'rows': l['ids'], 'sources': l['sources'],
                                       'quantity': l['quantity'], 'missing': l['missing'], 'damaged': l['damaged'], 'checked': l['checked']})
        return out

    # ---- stock ----

    def _stock(self):
        src, r = self.src, self.r
        stocks = src.execute('SELECT * FROM loose_stock ORDER BY id').fetchall()
        kinds = {}
        for s in stocks:
            kinds[s['id']] = self.kind_of(s['item_type'], s['item_no'])
        part_lines = defaultdict(dict)                          # stock id -> {(item, colour, spare): line}
        for p in src.execute('SELECT rowid AS rid, * FROM loose_minifig_parts ORDER BY rowid'):
            s = src.execute('SELECT item_type, item_no, color_id FROM loose_stock WHERE id=?', (p['stock_id'],)).fetchone()
            holder = MintResult.key_of(s['item_type'], s['item_no'], s['color_id'], 'minifigure')
            ref = f'loose_minifig_parts {p["rid"]} (stock {p["stock_id"]})'
            quantity, missing, damaged = self.counts('loose_minifig_parts', ref, p['quantity'], p['missing'], p['damaged'])
            t = self.tgt(p['item_type'], p['item_no'], p['color_id'], 'part' if p['item_type'] == '?' else None, holder)
            spare = p['spare'] or 0
            self.bl_stock_lines.setdefault(p['stock_id'], []).append(self._bl_line(
                {'item_type': p['item_type'], 'item_no': p['item_no'], 'bl_color': p['color_id'], 'color_id': t.color_id, 'item_id': t.item_id,
                 'spare': spare, 'quantity': quantity, 'kind': self.item_kind(t.item_id)}))
            if self.item_kind(t.item_id) != 'part':
                r.non_part_lines.append({'table': 'loose_minifig_parts', 'stock_id': p['stock_id'], 'item_type': p['item_type'], 'item_no': p['item_no'],
                                         'color_id': p['color_id'], 'spare': spare, 'quantity': quantity, 'missing': missing, 'damaged': damaged,
                                         'checked': p['checked'], 'why': 'a non-part line: stock_part holds parts only'})
                continue
            if p['item_type'] not in ('P', '?'):
                r.type_crossed.append({'table': 'loose_minifig_parts', 'stock_id': p['stock_id'], 'item_type': p['item_type'],
                                       'item_no': p['item_no'], 'holder': holder, 'item_id': t.item_id})
            key = (t.item_id, t.color_id, spare)
            lines = part_lines[p['stock_id']]
            if key not in lines:
                lines[key] = {'quantity': quantity, 'missing': missing, 'damaged': damaged, 'checked': int(bool(p['checked'])), 'ids': [p['rid']],
                              'first': p['rid'], 'sources': [(p['rid'], quantity, missing, damaged)], 'old': p}
            else:
                e = lines[key]
                e['quantity'] += quantity
                e['missing'] += missing
                e['damaged'] += damaged
                e['checked'] = min(e['checked'], int(bool(p['checked'])))
                e['ids'].append(p['rid'])
                e['sources'].append((p['rid'], quantity, missing, damaged))
        rows = []
        for s in stocks:
            kind = kinds[s['id']]
            ref = f'loose_stock {s["id"]}'
            quantity, missing, damaged = self.counts('loose_stock', ref, s['quantity'], s['missing'], s['damaged'])
            # the figure state summary keeps its NULL (never recorded)
            t = self.tgt(s['item_type'], s['item_no'], s['color_id'], kind if s['item_type'] == '?' else None)
            colour = t.color_id if kind == 'part' else None
            price, currency = self.money('stock', s['id'], s['purchase_price'], s['purchase_currency'])
            created = self.stamp('stock.created_at', s['created_at'], 'stock', s['id'])
            updated = self.stamp('stock.updated_at', s['updated_at'], 'stock', s['id'], ('created_at', created))
            if kind == 'minifigure':
                lines = part_lines.get(s['id'], {})
                source, digest = 'migrated', inventory_digest([(i, c, sp, l['quantity']) for (i, c, sp), l in lines.items() if l['quantity'] > 0])
            else:
                source = digest = None
            rows.append((s['id'], kind, t.item_id, colour, quantity, STOCK_CONDITION.get(s['condition']), s['storage_id'], s['lot_id'],
                         s['purchase_location_id'], s['purchase_date'], price, currency, s['note'],
                         None if s['missing'] is None else missing, None if s['damaged'] is None else damaged, s['checked'],
                         source, digest, created, updated, s['archived_at']))
        self.insert('stock', ['id', 'kind', 'item_id', 'color_id', 'quantity', 'condition', 'storage_id', 'lot_id', 'place_id', 'purchase_date',
                              'purchase_price', 'purchase_currency', 'note', 'missing', 'damaged', 'checked', 'inventory_source', 'inventory_digest',
                              'created_at', 'updated_at', 'archived_at'], rows)
        self.note('loose_stock', 'stock', len(stocks), "loose figures 'migrated'")
        out = []
        for stock_id in sorted(part_lines):
            for (item, colour, spare), l in sorted(part_lines[stock_id].items(), key=lambda kv: kv[1]['first']):
                out.append((stock_id, item, colour, spare, l['quantity'], l['missing'], l['damaged'], l['checked']))
                if len(l['ids']) > 1:
                    p = l['old']
                    r.summed_lines.append({'table': 'loose_minifig_parts', 'stock_id': stock_id, 'item_type': p['item_type'], 'item_no': p['item_no'],
                                           'color_id': p['color_id'], 'spare': spare, 'rows': l['ids'], 'sources': l['sources'],
                                           'quantity': l['quantity'], 'missing': l['missing'], 'damaged': l['damaged'], 'checked': l['checked']})
        self.insert('stock_part', ['stock_id', 'item_id', 'color_id', 'is_spare', 'quantity', 'missing', 'damaged', 'checked'], out)
        self.note('loose_minifig_parts', 'stock_part', src.execute('SELECT count(*) FROM loose_minifig_parts').fetchone()[0])

    # ---- attaching lists (design 8.6, Q12) ----

    def _versions(self, item_id, latest_only=False):
        """The catalogue's part lists of a set or figure, newest first (latest, then the highest version)."""
        return self.db.execute(
            'SELECT version, digest, bl_digest, is_latest FROM catalogue.inventory WHERE item_id=? AND retired_at IS NULL'
            + (' AND is_latest=1' if latest_only else '') + ' ORDER BY is_latest DESC, version DESC', (item_id,)).fetchall()

    def _compare(self, kind, row, ref, label, item_id, lines, own_digest, *, latest_only=False):
        """Does a migrated list equal a Rebrickable list in BrickLink space? Returns the record and the matching (version, digest) or None.
        Every record says why a list stayed `migrated`: no_catalogue_list (a local item, or the catalogue has no list of it),
        no_bl_digest (none of its lists has a BrickLink-space digest), placeholder_without_bricklink_key (a `?` line the catalogue cannot
        project), digest_differs, ids_differ (equal in BrickLink space, but lines on other 4.0 items than the catalogue list's)."""
        lines = [l for l in lines if l[4] > 0]
        record = {'kind': kind, 'row': row, 'ref': ref, 'label': label, 'item_id': item_id, 'lines': len(lines), 'status': 'migrated', 'reason': None,
                  'version': None, 'versions_tried': 0, 'bl_digest': None, 'catalogue_digest': None, 'ids_equal': None}
        versions = self._versions(item_id, latest_only) if item_id < LOCAL_BASE else []
        record['versions_tried'] = len(versions)
        if not versions:
            record['reason'] = 'no_catalogue_list'
        elif any(l[0] == '?' for l in lines):
            record['reason'] = 'placeholder_without_bricklink_key'
        else:
            record['bl_digest'] = want = bl_digest(lines)
            usable = [v for v in versions if v['bl_digest'] is not None]
            hits = [v for v in usable if v['bl_digest'] == want]
            exact = next((v for v in hits if v['digest'] == own_digest), None)
            if exact is not None:
                record.update(status='attached', version=exact['version'], catalogue_digest=exact['digest'], ids_equal=True)
            elif hits:
                # equal in BrickLink space, but some lines sit on other 4.0 items (a rule-4 tie made them local): a `rebrickable` list
                # must hold the catalogue list's own lines, or change detection and the switch see a list that is not the catalogue's
                record.update(reason='ids_differ', version=hits[0]['version'], catalogue_digest=hits[0]['digest'], ids_equal=False)
            else:
                record['reason'] = 'digest_differs' if usable else 'no_bl_digest'
        self.r.attach.append(record)
        return record

    def _attach(self):
        """Design 8.6: a migrated list that equals a Rebrickable list in BrickLink space becomes that list (`rebrickable`, its version and
        digest); the lines stay as written, so check state is untouched. Everything else stays `migrated`. Runs inside the migration's
        transaction. A copy is compared with every version of its set; a figure line and a loose figure with the figure's latest list."""
        db, r = self.db, self.r
        for c in db.execute('SELECT c.id, c.item_id, c.inventory_digest FROM main.copy c ORDER BY c.id').fetchall():
            rec = self._compare('copy', c['id'], c['id'], self.mint_label(c['item_id']), c['item_id'], self.bl_copy_lines.get(c['id'], []), c['inventory_digest'])
            if rec['status'] == 'attached':
                db.execute("UPDATE main.copy SET inventory_source='rebrickable', inventory_version=?, inventory_digest=? WHERE id=?",
                           (rec['version'], rec['catalogue_digest'], c['id']))
        for (copy_id, item_id), f in sorted(self.figure_rows.items()):
            rec = self._compare('figure', f['id'], f'{copy_id} {f["old"][1]}:{f["old"][2]}', self.mint_label(item_id), item_id,
                                self.bl_figure_lines.get((copy_id, item_id), []), f['own_digest'], latest_only=True)
            if rec['status'] == 'attached':
                db.execute("UPDATE main.copy_figure SET inventory_source='rebrickable', inventory_version=?, inventory_digest=? WHERE id=?",
                           (rec['version'], rec['catalogue_digest'], f['id']))
        for s in db.execute("SELECT id, item_id, inventory_digest FROM main.stock WHERE kind='minifigure' ORDER BY id").fetchall():
            rec = self._compare('loose_figure', s['id'], s['id'], self.mint_label(s['item_id']), s['item_id'], self.bl_stock_lines.get(s['id'], []),
                                s['inventory_digest'], latest_only=True)
            if rec['status'] == 'attached':
                db.execute("UPDATE main.stock SET inventory_source='rebrickable', inventory_version=?, inventory_digest=? WHERE id=?",
                           (rec['version'], rec['catalogue_digest'], s['id']))

    def mint_label(self, item_id):
        row = self.db.execute('SELECT born_namespace, born_key FROM main.item WHERE id=?', (item_id,)).fetchone()
        return f'{row[0]}:{row[1]}' if row else ''

    # ---- flags, wishes ----

    def _flags(self):
        """item_flags is split by entity type once the wishes have their uuids (see _wishes)."""
        self._flag_rows = self.src.execute('SELECT * FROM item_flags ORDER BY entity_type, entity_id, flag_id').fetchall()

    def _wishes(self):
        src, r = self.src, self.r
        rows = src.execute('SELECT * FROM wishlist ORDER BY id').fetchall()
        out = []
        for w in rows:
            kind = self.kind_of(w['item_type'], w['item_no'])
            t = self.tgt(w['item_type'], w['item_no'], w['color_id'], kind if w['item_type'] == '?' else None)
            wish_id = r.wish_ids[w['id']] = str(uuid.uuid4())
            price, currency = self.money('wish', w['id'], w['max_price'], w['max_price_currency'])
            added = self.stamp('wish.added_at', w['added_at'], 'wish', w['id'])
            out.append((wish_id, w['list_id'], kind, t.item_id, t.color_id if kind == 'part' else None, w['quantity'], w['condition'], price, currency,
                        w['qty_filled_manual'], w['note'], added, self.stamp('wish.updated_at', w['updated_at'], 'wish', w['id'], ('added_at', added)),
                        w['archived_at']))
        self.insert('wish', ['id', 'wishlist_id', 'kind', 'item_id', 'color_id', 'quantity', 'condition', 'max_price', 'max_price_currency',
                             'qty_filled_manual', 'note', 'added_at', 'updated_at', 'archived_at'], out)
        self.note('wishlist', 'wish', len(rows), 'ids became uuids (result.wish_ids)')
        split = {'copy': ('copy_flag', 'copy_id'), 'stock': ('stock_flag', 'stock_id'), 'wishlist': ('wish_flag', 'wish_id')}
        counts = Counter()
        for f in self._flag_rows:
            table, column = split[f['entity_type']]
            entity = r.wish_ids.get(int(f['entity_id'])) if f['entity_type'] == 'wishlist' and f['entity_id'].isdigit() else f['entity_id']
            if entity is None:
                self.decisions.append({'table': 'item_flags', 'row': tuple(f), 'why': f'flag link {tuple(f)}: its wish does not exist'})
                continue
            self.db.execute(f'INSERT INTO main.{table}({column}, flag_id) VALUES(?, ?)', (entity, f['flag_id']))
            counts[table] += 1
        self.note('item_flags', 'copy_flag, stock_flag, wish_flag', len(self._flag_rows), ', '.join(f'{k} {v}' for k, v in sorted(counts.items())))

    # ---- photos, instruction files ----

    def _photos_instructions(self):
        src = self.src
        rows = src.execute("SELECT * FROM item_images WHERE kind='own' ORDER BY id").fetchall()
        out = []
        for i in rows:
            ref = f'item_images {i["id"]}'
            if not (i['local_path'].startswith('data/images/own/') and '..' not in i['local_path']):
                self.decisions.append({'table': 'item_images', 'row': i['id'], 'why': f'{ref}: path {i["local_path"]!r} is not under data/images/own/'})
                continue
            kind = self.kind_of(i['item_type'], i['item_no'])
            t = self.tgt(i['item_type'], i['item_no'], i['color_id'], kind if i['item_type'] == '?' else None)
            out.append((str(uuid.uuid4()), t.item_id, t.color_id if i['color_id'] is not None or kind == 'part' else None, i['copy_id'], i['stock_id'],
                        i['local_path'], i['width'], i['height'], i['caption'], i['taken_at'],
                        self.stamp('photo.created_at', i['fetched_at'], None, None)))
        self.insert('photo', ['id', 'item_id', 'color_id', 'copy_id', 'stock_id', 'local_path', 'width', 'height', 'caption', 'taken_at', 'created_at'], out)
        self.note('item_images (own)', 'photo', len(rows), 'paths unchanged')
        rows = src.execute('SELECT * FROM instruction_files ORDER BY id').fetchall()
        out = []
        for f in rows:
            if not (f['path'].startswith('data/instructions/') and '..' not in f['path']):
                self.decisions.append({'table': 'instruction_files', 'row': f['id'], 'why': f'instruction_files {f["id"]}: path {f["path"]!r} is not under data/instructions/'})
                continue
            t = self.tgt(f['item_type'], f['set_no'], None, 'set' if f['item_type'] == '?' else None)
            out.append((f['id'], t.item_id, f['path'], f['label'] if f['label'] is not None else os.path.basename(f['path']),
                        self.stamp('instruction_file.added_at', f['added_at'], None, None), f['archived_at']))
        self.insert('instruction_file', ['id', 'item_id', 'path', 'label', 'added_at', 'archived_at'], out)
        self.note('instruction_files', 'instruction_file', len(rows))

    # ---- prices ----

    @staticmethod
    def provider_key(item_type, item_no, color_id):
        """The 3.3 BrickLink key and colour, exactly (the shape of design 5's example `P:970c00/11`)."""
        return f'{item_type}:{item_no}' + ('' if color_id is None else f'/{color_id}')

    def _price_target(self, item_type, item_no, color_id):
        kind = self.kind_of(item_type, item_no)
        t = self.tgt(item_type, item_no, color_id, kind if item_type == '?' else None)
        return t.item_id, (t.color_id if (kind == 'part' or color_id is not None) else None)

    def _prices(self):
        src, r = self.src, self.r
        rows = src.execute('SELECT * FROM price_observations ORDER BY id').fetchall()
        out = []
        for o in rows:
            item, colour = self._price_target(o['item_type'], o['item_no'], o['color_id'])
            undone = o['error'] == 'undone'
            observed = self.stamp('price_observation.observed_at', o['observed_at'], None, None)
            out.append((o['id'], item, colour, CONDITION.get(o['condition']), o['guide'], o['slot'], o['region'], o['currency'], o['price'], o['qty'],
                        o['sold'], o['min'], o['max'], o['source'], self.provider_key(o['item_type'], o['item_no'], o['color_id']), observed,
                        None if undone else o['error'], self.migrated_at if undone else None))
        self.insert('price_observation', ['id', 'item_id', 'color_id', 'condition', 'guide', 'slot', 'region', 'currency', 'price', 'qty', 'sold', 'min',
                                          'max', 'source', 'provider_key', 'observed_at', 'error', 'voided_at'], out)
        self.note('price_observations', 'price_observation', len(rows), "'undone' rows got voided_at = the migration time")
        # price_current is recomputed: the newest observation of each key that is not voided (3.3: the newest one written, an undo
        # puts the previous one back), then compared with the 3.3 table.
        current = {}
        for id_, item, colour, condition, guide, slot, region, currency in self.db.execute(
                'SELECT id, item_id, color_id, condition, guide, slot, region, currency FROM main.price_observation '
                'WHERE voided_at IS NULL ORDER BY id'):
            current[(item, colour, condition, guide, slot, region, currency)] = id_
        self.insert('price_current', ['item_id', 'color_id', 'condition', 'guide', 'slot', 'region', 'currency', 'observation_id'],
                    ((*k, v) for k, v in sorted(current.items(), key=lambda kv: kv[1])))
        before = {}
        for p in src.execute('SELECT * FROM price_current'):
            item, colour = self._price_target(p['item_type'], p['item_no'], p['color_id'])
            before[(item, colour, CONDITION.get(p['condition']), p['guide'], p['slot'], p['region'], p['currency'])] = p['observation_id']
        diff = [{'key': k, 'in_33': before.get(k), 'recomputed': current.get(k)} for k in sorted(set(before) | set(current), key=str)
                if before.get(k) != current.get(k)]
        r.price_current = {'rows_33': len(before), 'rows_40': len(current), 'differences': diff}
        self.note('price_current', 'price_current', len(before), f'recomputed; {len(diff)} difference(s) from 3.3')
        rows = src.execute('SELECT * FROM price_watch').fetchall()
        out = []
        for w in rows:
            item, colour = self._price_target(w['item_type'], w['item_no'], w['color_id'])
            out.append((item, colour, CONDITION.get(w['condition']), w['origin'], w['first_seen'], w['last_fetch_at'], w['last_error'],
                        w['last_error_at'], w['last_attempt_at']))
        self.insert('price_watch', ['item_id', 'color_id', 'condition', 'origin', 'first_seen', 'last_fetch_at', 'last_error', 'last_error_at',
                                    'last_attempt_at'], out)
        self.note('price_watch', 'price_watch', len(rows))

    # ---- keys, tokens, settings ----

    def _keys_tokens(self):
        src = self.src
        for src_table, dst in (('source_keys', 'source_key'), ('source_key_previous', 'source_key_previous')):
            rows = src.execute(f'SELECT source, ciphertext, saved_at, archived_at FROM {src_table} ORDER BY source').fetchall()
            self.insert(dst, ['source', 'ciphertext', 'saved_at', 'archived_at'], (tuple(x) for x in rows))
            self.note(src_table, dst, len(rows), 'ciphertext copied unchanged')
        rows = src.execute('SELECT id, name, hash, scopes, created_at, expires_at, last_used_at, revoked_at FROM api_tokens ORDER BY id').fetchall()
        self.insert('api_token', ['id', 'name', 'hash', 'scopes', 'created_at', 'expires_at', 'last_used_at', 'revoked_at'], (tuple(x) for x in rows))
        self.note('api_tokens', 'api_token', len(rows))
        rows = src.execute('SELECT source, kind, max_age_days FROM source_freshness ORDER BY source, kind').fetchall()
        have = {x[0] for x in self.db.execute('SELECT id FROM main.source')}
        kept = [tuple(x) for x in rows if x['source'] in have]
        self.insert('source_freshness', ['source', 'kind', 'max_age_days'], kept)
        self.note('source_freshness', 'source_freshness', len(rows), f'{len(rows) - len(kept)} for a source 4.0 does not know' if len(kept) != len(rows) else '')

    def _setting(self, key, kind, value, key40=None, value40=None, note=''):
        self.r.settings.append({'key': key, 'classification': kind, 'value': _short(value), 'key40': key40, 'value40': _short(value40), 'note': note})

    def _settings(self):
        r, src = self.r, self.src
        rows = src.execute('SELECT key, value FROM settings ORDER BY key').fetchall()
        carried = []
        links = []
        for key, value in rows:
            m = re.fullmatch(r'sync:(.+):link', key)
            kinds = TYPE_KIND
            if CARRIED_SETTINGS.fullmatch(key):
                carried.append((key, value))
                self._setting(key, 'carried', value, key, value)
            elif key.startswith('import_order:') and key[len('import_order:'):] in kinds:
                new = 'import_order:' + kinds[key[len('import_order:'):]]
                carried.append((new, value))
                self._setting(key, 'translated', value, new, value, 'BrickLink type code -> kind')
            elif key == 'source_priority':
                kept, listed = self._priority(value)
                if kept:
                    carried.append((key, json.dumps(kept)))
                self._setting(key, 'translated', value, key, json.dumps(kept) if kept else None,
                              'pictures, metadata and market_price carried with type codes translated; ' + '; '.join(listed))
            elif m:
                links.append((m.group(1), value))
                self._setting(key, 'carried', value, f'sync_state.link_json[{m.group(1)}]', value)
            else:
                self._setting(key, 'dropped', value, None, None, self._why_dropped(key))
        self.insert('setting', ['key', 'value'], carried)
        self.insert('sync_state', ['source', 'link_json', 'updated_at'], ((s, v, self.migrated_at) for s, v in links))
        self.note('settings', 'setting, sync_state', len(rows), f'{len(carried)} setting(s), {len(links)} sync link(s)')
        for s, _ in links:
            if not self.db.execute('SELECT 1 FROM main.source WHERE id=?', (s,)).fetchone():
                raise MigrationError(f'the sync link of {s!r} names a source 4.0 does not know')

    @staticmethod
    def _why_dropped(key):
        if key.startswith('checker:'):
            return 'check session; sessions restart (8.1)'
        if key.startswith('source:'):
            return 'budget counter or last attempt; BrickLink starts the cutover day at 0 (8.1)'
        if key.startswith('sync:'):
            return 'sync baseline, last pull/send or day counter; the first sync shows a full comparison (8.1)'
        if key.startswith('plan_applied:'):
            return 'import plan state of 3.3'
        if key.startswith('maintenance:'):
            return 'state of the 3.3 database check; 4.0 starts its own'
        return 'unknown key: not in 8.10'

    def _priority(self, value):
        """Translate source_priority (8.10): the three steps that keep their meaning, type codes -> kinds; the rest takes the 4.0 default."""
        kinds = TYPE_KIND
        try:
            data = json.loads(value)
        except ValueError:
            return {}, ['not valid JSON: dropped']
        kept, listed = {}, []
        for step, types in data.items():
            if step == 'pictures':
                kept[step] = {kinds.get(t, t): translate_pictures(kinds.get(t, t), v, PRIORITY_33['pictures'].get(t) == v) for t, v in types.items()}
                changed = [t for t, v in types.items() if PRIORITY_33['pictures'].get(t) != v]
                listed.append('pictures: ' + ('the 3.3 default became the 4.0 default (design 6.8)' if not changed else
                              f'NON-DEFAULT 3.3 order for {", ".join(sorted(changed))} translated: rebrickable -> rebrickable_dump, rebrickable_api'))
            elif step in CARRIED_PRIORITY_STEPS:
                kept[step] = {kinds.get(t, t): v for t, v in types.items()}
            else:
                default = PRIORITY_33.get(step) == types
                listed.append(f'{step} {json.dumps(types)} takes the 4.0 default ({"was the 3.3 default" if default else "NON-DEFAULT in 3.3"})')
        return kept, listed

    # ---- not carried, manual decisions ----

    def _not_carried(self):
        r, src = self.r, self.src
        have = {x[0] for x in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for name, (sql, why) in NOT_CARRIED.items():
            table = re.search(r'FROM (\w+)', sql).group(1)
            if table not in have:
                continue
            count = src.execute(f'SELECT count(*) FROM ({sql})').fetchone()[0]
            if name == 'exchange_rates':
                samples = [dict(x) for x in src.execute("SELECT * FROM exchange_rates WHERE source='manual'")]
                why += f' ({len(samples)} manual rate(s) listed in full)'
            else:
                samples = [dict(x) for x in src.execute(f'{sql} LIMIT {SAMPLE_ROWS}')]
            r.not_carried[name] = {'count': count, 'samples': samples, 'why': why}
        r.manual_decisions = [dict(x) for x in src.execute(
            "SELECT * FROM id_match WHERE status='manual' OR method='manual' OR method LIKE 'ulf-%' ORDER BY source, kind, source_id")]
        r.to_check = [dict(x) for x in src.execute("SELECT * FROM id_match WHERE status='to_check' ORDER BY source, kind, source_id")]
        r.unmatched = [dict(x) for x in src.execute("SELECT * FROM id_match WHERE status='unmatched' ORDER BY source, kind, source_id")]

    # ---- meta, counts ----

    def _meta(self):
        r = self.r
        self.db.execute("INSERT INTO main.meta(key, value) VALUES('migrated_from', ?)", (json.dumps(
            {'file': r.source['name'], 'sha256': r.source['sha256'], 'report_digest': None, 'migrated_at': self.migrated_at}, sort_keys=True),))

    def _counts(self):
        for t in self.r.tables:
            names = [n.strip() for n in t['to'].split(',')]
            t['rows_40'] = sum(self.db.execute(f'SELECT count(*) FROM main.{n}').fetchone()[0] for n in names)
