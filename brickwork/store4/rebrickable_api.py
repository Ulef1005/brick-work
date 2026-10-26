"""A set newer than the catalogue, fetched through the Rebrickable API (design 3.1, 4.2, 4.5, 6.5; issue #107, M.5c).

Two phases, so the job runner can do the network outside the write transaction:

1. `fetch_set_replies` makes the calls (`/sets/{num}/`, `/sets/{num}/parts/`, `/sets/{num}/minifigs/`, and `/minifigs/{fig}/parts/`
   for every figure the catalogue lacks: 3 + n calls when nothing pages) and returns the raw replies. `Replies.to_json` /
   `from_json` keep them for offline replay.
2. `load_rebrickable_set` stores them in the caller's transaction, in one savepoint: a local Rebrickable-born set, its part
   lines (catalogue parts projected, others local), its figure lines, and one `fetched_inventory(source='rebrickable_api')` for the
   set and one per figure the catalogue lacks. A set the catalogue already has is refused: its own list is used instead.

Set part lines come with `inc_minifig_parts=0`: a figure's parts come from the figure's own list (design 4.5). No item links are
written for the new local items; the next dump that holds them adopts the local ids and brings the catalogue's links."""
from dataclasses import asdict, dataclass, field
import http.client
import json
import re
import time
import urllib.error
import urllib.request

from . import fetched, identity, keys
from .connect import has_catalogue
from .errors import Store4Error
from .fetched import InventoryError
from .identity import _savepoint

BASE = 'https://rebrickable.com/api/v3/lego'
KEY_ENV = 'BW_REBRICKABLE_API_KEY'
SOURCE = 'rebrickable_api'
NUMBER = re.compile('[A-Za-z0-9-]{1,64}')
PART_NUMBER = re.compile('[A-Za-z0-9._-]{1,64}')
PAGE_SIZE = 1000                                           # the API's maximum
MAX_PAGES = 200                                            # a runaway `next` chain stops here


class FetchError(Store4Error):
    """A Rebrickable call that failed; `.status` is the HTTP status when there was one."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class NotFound(FetchError):
    """Rebrickable has no such set (job error code `not_found`)."""


class KeyRefused(FetchError):
    """The source refused the key (HTTP 401/403; job error code `source_not_configured`)."""


class InvalidReply(FetchError):
    """A call that succeeded with a reply the fetch cannot use (job error code `invalid_reply`): another try gives the same."""


class Throttled(FetchError):
    """HTTP 429: wait `retry_seconds` (60 when the reply names none) before the next call; a rate wait, not the daily budget."""

    def __init__(self, message, retry_seconds=None):
        super().__init__(message, 429)
        self.retry_seconds = retry_seconds if retry_seconds else 60


def throttle_seconds(body):
    """Seconds named by a throttle reply ("Expected available in 25 seconds."), clamped to 1 s .. 1 day; None when it names none."""
    match = re.search(r'available in ([0-9]+) seconds?', str(body.get('detail', '')) if isinstance(body, dict) else '', re.IGNORECASE)
    return max(1, min(86400, int(match[1]))) if match else None


class SetInCatalogue(Store4Error):
    """The catalogue (or the collection, as a catalogue item) already holds the set: use the catalogue's list."""


@dataclass
class Replies:
    set_num: str
    pages: dict = field(default_factory=dict)              # endpoint path -> list of page payloads
    calls: int = 0

    def to_json(self):
        return json.dumps({'set_num': self.set_num, 'calls': self.calls, 'pages': self.pages}, indent=1, sort_keys=True)

    @classmethod
    def from_json(cls, text):
        data = json.loads(text)
        return cls(set_num=data['set_num'], pages=data['pages'], calls=data.get('calls', 0))


def _number(value, what):
    if not isinstance(value, str) or not NUMBER.fullmatch(value):
        raise FetchError(f'{what} {value!r} is not a Rebrickable number')
    return value


class UrllibHttp:
    """The default `http(url, headers) -> (status, json)`: stdlib urllib, the key from the environment, calls at least a second apart."""

    def __init__(self, spacing=1.0, timeout=60, clock=time.monotonic, sleep=time.sleep):
        self.spacing, self.timeout, self.clock, self.sleep = spacing, timeout, clock, sleep
        self.last = None

    def __call__(self, url, headers):
        if self.last is not None:
            wait = self.spacing - (self.clock() - self.last)
            if wait > 0:
                self.sleep(wait)
        self.last = self.clock()
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read())
            except (ValueError, OSError, http.client.HTTPException):
                body = None
            return exc.code, body
        except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as exc:   # IncompleteRead included
            raise FetchError(f'Rebrickable call failed: {exc.__class__.__name__}') from exc


def _headers():
    key = keys.get(KEY_ENV)
    if not key:
        raise FetchError(f'{KEY_ENV} is not set; a Rebrickable key is needed to fetch a set')
    return {'Authorization': f'key {key}', 'Accept': 'application/json'}


def fetch_set_replies(set_num, *, http=None, catalogue_has_figure, headers=None):
    """Make the 3 + n calls for a set; returns `Replies`. `catalogue_has_figure(fig_num) -> bool` says which figures need their own call."""
    _number(set_num, 'set')
    http = http or UrllibHttp()
    headers = headers if headers is not None else _headers()
    replies = Replies(set_num)

    def get(url, path):
        replies.calls += 1
        status, body = http(url, headers)
        if status == 404:
            raise NotFound(f'Rebrickable has no {path}', 404)
        if status in (401, 403):
            raise KeyRefused('Rebrickable refused the key', status)
        if status == 429:
            raise Throttled('Rebrickable throttled the call', throttle_seconds(body))
        if status != 200:
            raise FetchError(f'Rebrickable answered {status} for {path}', status)
        if not isinstance(body, dict):
            raise InvalidReply(f'Rebrickable answered {path} with no JSON object', status)
        return body

    def one(path, query=''):
        replies.pages[path] = [get(BASE + path + query, path)]

    def paged(path, query=''):
        url, pages = f'{BASE}{path}?page_size={PAGE_SIZE}{query}', []
        while url:
            if len(pages) >= MAX_PAGES:
                raise InvalidReply(f'Rebrickable paged {path} more than {MAX_PAGES} times')
            page = get(url, path)
            if not isinstance(page.get('results'), list):
                raise InvalidReply(f'Rebrickable answered {path} without a results list')
            pages.append(page)
            url = page.get('next')
            if url is not None and (not isinstance(url, str) or not url.startswith(BASE + '/')):
                raise InvalidReply(f'Rebrickable sent an unexpected next link for {path}')
        replies.pages[path] = pages

    one(f'/sets/{set_num}/')
    paged(f'/sets/{set_num}/parts/', '&inc_minifig_parts=0')
    paged(f'/sets/{set_num}/minifigs/')
    for fig in _figure_numbers(replies.pages[f'/sets/{set_num}/minifigs/']):
        if not catalogue_has_figure(fig):
            paged(f'/minifigs/{fig}/parts/')
    return replies


def catalogue_figure_check(db):
    """A `catalogue_has_figure` over an open connection: the attached catalogue holds the figure's Rebrickable born key."""
    def has(fig):
        return has_catalogue(db) and db.execute("SELECT 1 FROM catalogue.item WHERE born_provider='rebrickable' AND born_namespace='minifigs' "
                                                'AND born_key=?', (fig,)).fetchone() is not None
    return has


# ---------- parsing ----------

def _results(pages, path):
    # Replayed pages are checked as fetched ones are: a page without a results list would silently drop lines.
    if not isinstance(pages, list) or not all(isinstance(p, dict) and isinstance(p.get('results'), list) for p in pages):
        raise InventoryError(f'invalid Rebrickable reply for {path}: a page has no results list')
    rows = [r for page in pages for r in page['results']]
    if not all(isinstance(r, dict) for r in rows):
        raise InventoryError(f'invalid Rebrickable reply for {path}: a result is not an object')
    return rows


def _figure_numbers(pages):
    seen = []
    for row in _results(pages, 'minifigs'):
        fig = row.get('set_num')
        if isinstance(fig, str) and fig not in seen:
            seen.append(fig)
    return seen


def _positive(value, what):
    if type(value) is not int or value <= 0:
        raise InventoryError(f'invalid Rebrickable reply: {what} has quantity {value!r}')
    return value


def parse_part_lines(pages, path):
    """Part lines of a parts reply -> {(part_num, colour id, is_spare): quantity}, names, colour names, rows summed away."""
    lines, names, colours, summed = {}, {}, {}, 0
    for row in _results(pages, path):
        part, colour = row.get('part'), row.get('color')
        if not isinstance(part, dict) or not isinstance(colour, dict):
            raise InventoryError(f'invalid Rebrickable reply for {path}: a line has no part or colour')
        num, colour_id, spare = part.get('part_num'), colour.get('id'), row.get('is_spare')
        if not isinstance(num, str) or not PART_NUMBER.fullmatch(num):
            raise InventoryError(f'invalid Rebrickable reply for {path}: part number {num!r}')
        if type(colour_id) is not int:
            raise InventoryError(f'invalid Rebrickable reply for {path}: {num} has colour {colour_id!r}')
        if type(spare) is not bool:
            raise InventoryError(f'invalid Rebrickable reply for {path}: {num} has is_spare {spare!r}')
        key = (num, colour_id, int(spare))
        summed += key in lines
        lines[key] = lines.get(key, 0) + _positive(row.get('quantity'), f'{num} in colour {colour_id}')
        if isinstance(part.get('name'), str) and part['name']:
            names.setdefault(num, part['name'])
        if isinstance(colour.get('name'), str):
            colours.setdefault(colour_id, colour['name'])
    return lines, names, colours, summed


def parse_figure_lines(pages, path):
    """Figure lines of a minifigs reply -> ({fig_num: quantity}, {fig_num: name})."""
    lines, names = {}, {}
    for row in _results(pages, path):
        fig = row.get('set_num')
        if not isinstance(fig, str) or not NUMBER.fullmatch(fig):
            raise InventoryError(f'invalid Rebrickable reply for {path}: figure number {fig!r}')
        lines[fig] = lines.get(fig, 0) + _positive(row.get('quantity'), fig)
        if isinstance(row.get('set_name'), str) and row['set_name']:
            names.setdefault(fig, row['set_name'])
    return lines, names


def _joined(pages):
    """One payload for a paged reply: the first page's fields with every page's results."""
    if len(pages) == 1:
        return pages[0]
    joined = {k: v for k, v in pages[0].items() if k not in ('next', 'previous')}
    joined['results'] = [r for page in pages for r in page['results']]
    return joined


# ---------- loading ----------

@dataclass
class FigureList:
    fig_num: str
    item_id: int
    fetched_id: int | None
    seq: int | None
    digest: str | None
    part_lines: int
    matches_version: int | None


@dataclass
class LoadResult:
    set_item_id: int
    fetched_id: int
    seq: int
    digest: str
    provider_version: int | None
    part_lines: int
    spare_lines: int
    part_total: int
    spare_total: int
    figure_lines: int
    figure_total: int
    duplicates_summed: int
    figure_lists: list                   # FigureList per figure the catalogue lacks
    local_items_created: dict            # kind -> new local items made by this load
    local_items_reused: dict             # kind -> local items the lists use that already existed
    items_projected: int                 # catalogue items copied into the collection by this load
    colours_projected: int
    calls: int
    matches_version: int | None          # the catalogue inventory version of the set with an equal digest (normally none before adoption)

    def as_dict(self):
        return asdict(self)


def _catalogue_item(db, namespace, key):
    if not has_catalogue(db):
        return None
    row = db.execute("SELECT id FROM catalogue.item WHERE born_provider='rebrickable' AND born_namespace=? AND born_key=?", (namespace, key)).fetchone()
    return row[0] if row else None


def _catalogue_version(db, item_id, digest):
    if not has_catalogue(db):
        return None
    row = db.execute('SELECT version FROM catalogue.inventory WHERE item_id=? AND digest=? ORDER BY is_latest DESC, version DESC',
                     (item_id, digest)).fetchone()
    return row[0] if row else None


class _Loader:
    def __init__(self, db, events):
        self.db, self.events = db, events
        self.items, self.colours = {}, {}
        self.created, self.used = set(), set()
        self.projected = self.projected_colours = 0

    def item(self, namespace, key, kind, name):
        """The collection item for a Rebrickable key: the catalogue's, projected, else a local Rebrickable-born one."""
        cache = (namespace, key)
        if cache in self.items:
            return self.items[cache]
        catalogue_id = _catalogue_item(self.db, namespace, key)
        if catalogue_id is not None:
            self.projected += not self.db.execute('SELECT 1 FROM main.item WHERE id=?', (catalogue_id,)).fetchone()
            item = identity.project(self.db, catalogue_id)
        else:
            existing = self.db.execute("SELECT 1 FROM main.item WHERE born_provider='rebrickable' AND born_namespace=? AND born_key=?",
                                       (namespace, key)).fetchone()
            item = fetched.create_local_item(self.db, kind=kind, born_provider='rebrickable', born_namespace=namespace, born_key=key,
                                             name=name, events=self.events)
            if existing is None:
                self.created.add(item)
            self.used.add(item)
        self.items[cache] = item
        return item

    def colour(self, rb_id, name):
        if rb_id in self.colours:
            return self.colours[rb_id]
        row = self.db.execute("SELECT id FROM main.color WHERE born_provider='rebrickable' AND born_key=?", (str(rb_id),)).fetchone()
        if row is None and has_catalogue(self.db):
            row = self.db.execute("SELECT id FROM catalogue.color WHERE born_provider='rebrickable' AND born_key=?", (str(rb_id),)).fetchone()
        if row is None:
            raise InventoryError(f'Rebrickable colour {rb_id} ({name}) is not in the catalogue; download today\'s catalogue first. '
                                 f'(Local colours are BrickLink-only, so the list is refused.)')
        had = self.db.execute('SELECT 1 FROM main.color WHERE id=?', (row[0],)).fetchone()
        identity.project_color(self.db, row[0])
        self.projected_colours += not had
        self.colours[rb_id] = row[0]
        return row[0]

    def part_rows(self, lines, names, colour_names):
        return [(self.item('parts', num, 'part', names.get(num, num)), self.colour(colour, colour_names.get(colour, str(colour))), spare, q)
                for (num, colour, spare), q in lines.items()]


def load_rebrickable_set(db, set_num, replies, *, job_id=None, events=None):
    """Store fetched `Replies` for a set as the next `fetched_inventory(source='rebrickable_api')`; returns a `LoadResult`.

    All or nothing in one savepoint. The set must not be in the catalogue or the collection as a catalogue item; a figure the
    catalogue lacks needs its parts reply, else the load is refused."""
    _number(set_num, 'set')
    path = f'/sets/{set_num}/'
    for needed in (path, path + 'parts/', path + 'minifigs/'):
        if not replies.pages.get(needed):
            raise InventoryError(f'the replies for {set_num} lack {needed}')
    info = replies.pages[path][0]
    if info.get('set_num') != set_num or not isinstance(info.get('name'), str) or not info['name']:
        raise InventoryError(f'the reply for {path} does not describe set {set_num}')
    year, num_parts = info.get('year'), info.get('num_parts')
    year = year if type(year) is int else None
    num_parts = num_parts if type(num_parts) is int else None
    part_lines, names, colour_names, duplicates = parse_part_lines(replies.pages[path + 'parts/'], path + 'parts/')
    figure_lines, figure_names = parse_figure_lines(replies.pages[path + 'minifigs/'], path + 'minifigs/')
    figure_parts = {}
    _savepoint(db, 'load_rebrickable_set')
    try:
        if _catalogue_item(db, 'sets', set_num) is not None or db.execute(
                "SELECT 1 FROM main.item WHERE origin='catalogue' AND born_provider='rebrickable' AND born_namespace='sets' AND born_key=?",
                (set_num,)).fetchone():
            raise SetInCatalogue(f'the catalogue already has set {set_num}; use the catalogue\'s part list instead of fetching one')
        loader = _Loader(db, events)
        # Figure lists first: a figure the catalogue lacks must have its parts reply before anything is written.
        local_figures = [f for f in figure_lines if _catalogue_item(db, 'minifigs', f) is None]
        for fig in local_figures:
            fig_path = f'/minifigs/{fig}/parts/'
            if not replies.pages.get(fig_path):
                raise InventoryError(f'figure {fig} is not in the catalogue and the replies lack {fig_path}')
            figure_parts[fig] = parse_part_lines(replies.pages[fig_path], fig_path)
        set_existing = db.execute("SELECT 1 FROM main.item WHERE born_provider='rebrickable' AND born_namespace='sets' AND born_key=?",
                                  (set_num,)).fetchone() is not None
        set_item = fetched.create_local_item(db, kind='set', born_provider='rebrickable', born_namespace='sets', born_key=set_num,
                                             name=info['name'], year=year, num_parts=num_parts, events=events)
        parts = loader.part_rows(part_lines, names, colour_names)
        figures = [(loader.item('minifigs', fig, 'minifigure', figure_names.get(fig, fig)), q) for fig, q in figure_lines.items()]
        records = {}
        for kind, pages_path in (('set', path), ('set_parts', path + 'parts/'), ('set_minifigs', path + 'minifigs/')):
            records[pages_path] = fetched.store_source_record(db, source='rebrickable', kind=kind, key=set_num,
                                                              payload=_joined(replies.pages[pages_path]), job_id=job_id)
        fid = fetched.write_fetched(db, set_item, SOURCE, parts, figures, job_id=job_id, source_record_id=records[path + 'parts/'], events=events)
        seq, digest = db.execute('SELECT seq, digest FROM main.fetched_inventory WHERE id=?', (fid,)).fetchone()
        lists = []
        for fig, (lines, fnames, fcolours, _) in figure_parts.items():
            fig_path = f'/minifigs/{fig}/parts/'
            fig_item = loader.items[('minifigs', fig)]
            record = fetched.store_source_record(db, source='rebrickable', kind='minifig_parts', key=fig,
                                                 payload=_joined(replies.pages[fig_path]), job_id=job_id)
            rows = loader.part_rows(lines, fnames, fcolours)
            ffid = fetched.write_fetched(db, fig_item, SOURCE, rows, job_id=job_id, source_record_id=record, events=events)
            fseq, fdigest = db.execute('SELECT seq, digest FROM main.fetched_inventory WHERE id=?', (ffid,)).fetchone()
            lists.append(FigureList(fig, fig_item, ffid, fseq, fdigest, len(lines), _catalogue_version(db, fig_item, fdigest)))
        kinds = {i: db.execute('SELECT kind FROM main.item WHERE id=?', (i,)).fetchone()[0] for i in loader.used | {set_item}}
        used = loader.used | {set_item}
        created = loader.created | (set() if set_existing else {set_item})
        count = lambda ids: {k: sum(1 for i in ids if kinds[i] == k) for k in ('set', 'part', 'minifigure')}
        result = LoadResult(
            set_item_id=set_item, fetched_id=fid, seq=seq, digest=digest, provider_version=None,
            part_lines=sum(1 for k in part_lines if not k[2]), spare_lines=sum(1 for k in part_lines if k[2]),
            part_total=sum(q for k, q in part_lines.items() if not k[2]), spare_total=sum(q for k, q in part_lines.items() if k[2]),
            figure_lines=len(figure_lines), figure_total=sum(figure_lines.values()), duplicates_summed=duplicates, figure_lists=lists,
            local_items_created=count(created), local_items_reused=count(used - created),
            items_projected=loader.projected, colours_projected=loader.projected_colours, calls=replies.calls,
            matches_version=_catalogue_version(db, set_item, digest))
    except BaseException:
        db.execute('ROLLBACK TO load_rebrickable_set')
        raise
    finally:
        db.execute('RELEASE load_rebrickable_set')
    return result
