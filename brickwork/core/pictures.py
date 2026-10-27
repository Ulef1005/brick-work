"""Pictures and their source order on the 4.0 store (M.8f, issue #110; design 6.8, 3.2).

Three sources, in the order of the setting `source_priority.pictures` (per kind, `*` for the rest; Settings edits it, the migration
translates 3.3's):

- `rebrickable_dump`: the catalogue's `picture_url` for (item, colour), a plain download. The dump carries one for a part in a colour some
  inventory uses; sets and figures have none, and a part in another colour has none (the order then falls through).
- `bricklink`: `img.bricklink.com` by the resolved BrickLink key and colour (`items.bricklink_key`), a plain download, no key.
- `rebrickable_api`: `GET /parts/{num}/colors/{id}/` (sets and figures: their own record), needs a key and is budgeted.

Defaults: parts `rebrickable_dump`, `bricklink`, `rebrickable_api`; everything else `bricklink`, `rebrickable_dump`.

The pipeline's `pictures` step runs one handler per source in that order (`handler(source)`); each serves the colours of the item that
still have no picture and raises `StepFailed` when some remain, so the next source gets a go. A colour is served by a `picture` row of
the item with that colour or none. `picture_known` answers what the Add review asks before confirming (design 6.8, last paragraph).

The bulk refresh (Settings, Tools & Admin) is `state`, `selection` and `queue`: one `pictures` job per held item that lacks a picture
(scope `missing`) or every held item (scope `all`)."""
from collections import defaultdict
import json

from ..store4 import keys as store_keys
from ..store4.connect import has_catalogue
from . import errors, items, pipeline
from .media import media_root
from .pipeline import StepDone, StepFailed, StepWait
from .sources import base, images
from .transaction import transaction

SOURCES = images.SOURCES
DEFAULT_ORDER = {'part': ['rebrickable_dump', 'bricklink', 'rebrickable_api'], '*': ['bricklink', 'rebrickable_dump']}
BRICKLINK_IMAGE = 'https://img.bricklink.com/ItemImage/{type}N/{colour}/{number}.png'
API_PATH = {'parts': 'part', 'sets': 'set', 'minifigs': 'minifigure'}
KIND_LABELS = {'set': 'Sets', 'minifigure': 'Minifigures', 'part': 'Parts', 'instructions': 'Instructions', 'box': 'Boxes',
               'gear': 'Gear', 'book': 'Books', 'catalog': 'Catalogs'}
NO_COLOUR = 1                                       # the colour of "[No Color/Any Color]"; a part with none takes the dump's row of this colour


class NoPicture(Exception):
    """This source has no picture for the item and colour (the reason is the message): the order moves on."""


# ---------- the order ----------

def order(db, kind):
    """The picture sources to try for an item of `kind`, in order: the stored setting (`kind`, else `*`), else design 6.8's default.
    A source this module does not know is ignored, so an old value never breaks a job."""
    row = db.execute("SELECT value FROM main.setting WHERE key='source_priority'").fetchone()
    try:
        stored = (json.loads(row[0]) if row else {}).get('pictures') or {}
    except (TypeError, ValueError):
        stored = {}
    wanted = stored.get(kind) or stored.get('*') or DEFAULT_ORDER.get(kind, DEFAULT_ORDER['*'])
    names = (n for s in wanted for n in (pipeline.LEGACY_PICTURE_SOURCES.get(str(s).split(':')[0]) or (str(s).split(':')[0],)))
    return [s for s in dict.fromkeys(names) if s in SOURCES]


# ---------- what an item's pictures are for ----------

def _item(db, item_id):
    row = db.execute('SELECT id, kind, name, born_provider, born_namespace, born_key FROM main.item WHERE id=?', (item_id,)).fetchone()
    if row is None:
        row = db.execute('SELECT id, kind, name, born_provider, born_namespace, born_key FROM catalogue.item WHERE id=?', (item_id,)).fetchone() \
            if has_catalogue(db) else None
    if row is None:
        raise errors.NotFound(f'No item {item_id}')
    return row


colours_of = items.colours_held


def served(db, item_id, color_id):
    """A picture of the item for this colour exists: one of that colour, or one with no colour (it serves every colour)."""
    return db.execute('SELECT 1 FROM main.picture WHERE item_id=? AND (color_id IS NULL OR color_id=?) LIMIT 1', (item_id, color_id)).fetchone() is not None


# ---------- what each source can name ----------

def dump_url(db, item_id, color_id):
    """The catalogue's picture URL for (item, colour); a part with no colour takes the "no colour" row. Raises NoPicture."""
    if not has_catalogue(db):
        raise NoPicture('no catalogue is attached')
    row = db.execute('SELECT url FROM catalogue.picture_url WHERE item_id=? AND color_id=?', (item_id, NO_COLOUR if color_id is None else color_id)).fetchone()
    if row is None:
        raise NoPicture('the catalogue has no picture for this colour')
    return row[0]


def bricklink_url(db, item_id, color_id):
    """`img.bricklink.com` for the item's resolved BrickLink key and colour. Raises NoPicture without a confirmed BrickLink number."""
    try:
        letter, number, colour = items.bricklink_key(db, item_id, color_id)
    except items.Unidentified:
        raise NoPicture('the item has no BrickLink number') from None
    if letter == 'P' and color_id is not None and color_id != NO_COLOUR and colour is None:
        raise NoPicture('the colour has no BrickLink number')
    return BRICKLINK_IMAGE.format(type=letter, colour=colour if letter == 'P' and colour is not None else 0, number=number)


def api_target(db, item_id, color_id):
    """(path, key in the answer) for the Rebrickable API picture of the item, or NoPicture: only a Rebrickable-born item has a number
    there, and a colour is asked by its Rebrickable colour number (a local, BrickLink-born colour has none)."""
    row = _item(db, item_id)
    if row['born_provider'] != 'rebrickable' or row['born_namespace'] not in API_PATH:
        raise NoPicture('the item has no Rebrickable number')
    number = row['born_key']
    if row['born_namespace'] == 'sets':
        return f'/sets/{number}/', 'set_img_url'
    if row['born_namespace'] == 'minifigs':
        return f'/minifigs/{number}/', 'set_img_url'
    if color_id is None or color_id == NO_COLOUR:
        return f'/parts/{number}/', 'part_img_url'
    colour = colour_row(db, color_id)
    if colour is None or colour['born_provider'] != 'rebrickable' or colour['born_key'] == '-1':
        raise NoPicture('Rebrickable has no number for this colour')
    return f'/parts/{number}/colors/{colour["born_key"]}/', 'part_img_url'


def colour_row(db, color_id):
    for store in ('main', 'catalogue'):
        if store == 'catalogue' and not has_catalogue(db):
            break
        row = db.execute(f'SELECT id, born_provider, born_key FROM {store}.color WHERE id=?', (color_id,)).fetchone()
        if row is not None:
            return row
    return None


def can_serve(db, item_id, color_id, source):
    """Could `source` serve this item and colour right now? (a URL it can name; for the API also a key, since it is a budgeted call)"""
    try:
        if source == 'rebrickable_dump':
            dump_url(db, item_id, color_id)
        elif source == 'bricklink':
            bricklink_url(db, item_id, color_id)
        elif source == 'rebrickable_api':
            api_target(db, item_id, color_id)
            return bool(store_keys.get('BW_REBRICKABLE_API_KEY'))
        else:
            return False
    except (NoPicture, errors.NotFound):
        return False
    return True


def picture_known(db, item_id, color_id=None):
    """Is a picture of this item in this colour stored, or could one source of the order fetch it? The Add review warns "no picture
    known for this colour" when not (design 6.8): no `picture_url`, no resolvable BrickLink key and no Rebrickable key."""
    if served(db, item_id, color_id):
        return True
    return any(can_serve(db, item_id, color_id, s) for s in order(db, _item(db, item_id)['kind']))


# ---------- the pipeline step ----------

def _failure(error):
    """(StepFailed code, message) of a source failure."""
    if isinstance(error, (base.SourceNotConfigured, base.SourceDisabled, base.KeyRejected)):
        return 'source_not_configured', str(error)
    if isinstance(error, NoPicture):
        return 'not_found', str(error)
    if isinstance(error, base.NotFoundAtSource):
        return 'not_found', str(error)
    if isinstance(error, base.InvalidReply):
        return 'invalid_reply', str(error)
    return 'source_error', str(error)


def fetch(db, job, source, *, http=None, image_http=None, root=None):
    """Serve the item's colours that have no picture from `source`. Returns the number of pictures stored; raises `StepDone`
    (`unidentified`: nothing can picture an item that has no number), `StepWait` (budget) or `StepFailed` (some colours remain)."""
    from .sources.rebrickable import Rebrickable
    item_id = job['item_id']
    row = _item(db, item_id)
    if row['born_key'] is None:
        raise StepDone('unidentified', 'The item has no number from any provider, so no picture can be asked for')
    payload = json.loads(job['payload'] or '{}')
    root = root or media_root(db)
    tracked = job['id'] is not None and db.execute("SELECT 1 FROM main.job_step WHERE job_id=? AND name='pictures'", (job['id'],)).fetchone() is not None
    refreshed = {r[0] for r in db.execute("SELECT operation FROM main.job_call WHERE job_id=? AND step='pictures'", (job['id'],))} if tracked else set()
    # a refresh fetches each colour once per job: after a budget wait it resumes with the colours not yet refreshed
    todo = [c for c in colours_of(db, item_id)
            if (f'picture:{c or 0}' not in refreshed if payload.get('refresh') else not served(db, item_id, c))]
    stored, failed = 0, []
    for color_id in todo:
        try:
            if source == 'rebrickable_dump':
                url = dump_url(db, item_id, color_id)
            elif source == 'bricklink':
                url = bricklink_url(db, item_id, color_id)
            elif source == 'rebrickable_api':
                path, key = api_target(db, item_id, color_id)
                url = Rebrickable(db, http=http).picture_url(path, key, item_id=item_id, job_id=job['id'])
            else:
                raise NoPicture(f'{source} is not a picture source')
            images.download(db, root, source, item_id, row['kind'], url, color_id=color_id, http=image_http)
            stored += 1
            if tracked:
                with transaction(db):
                    db.execute("INSERT OR REPLACE INTO main.job_call(job_id, step, operation, result) VALUES(?, 'pictures', ?, ?)",
                               (job['id'], f'picture:{color_id or 0}', json.dumps({'source': source})))
        except base.WaitingForBudget as wait:
            raise StepWait(wait.retry_at, 'waiting for budget') from None
        except (NoPicture, base.SourceError) as error:
            failed.append((color_id, error))
    if failed:
        code, message = _failure(failed[0][1])
        raise StepFailed(code, message if len(todo) == 1 else f'{len(failed)} of {len(todo)} colours have no picture: {message}')
    return stored


def handler(source, *, http=None, image_http=None, root=None):
    """The pipeline handler `(db, job, step)` of one picture source; `http` and `image_http` are the test seams for the API and the
    image downloads."""
    def run(db, job, step):
        with base.audit_origin(job['via'], job.get('actor')):
            fetch(db, job, source, http=http, image_http=image_http, root=root)
    return run


def handlers(**options):
    """`{('pictures', source): handler}` for the three sources."""
    return {('pictures', source): handler(source, **options) for source in SOURCES}


def register(**options):
    for (step, source), function in handlers(**options).items():
        pipeline.register(step, source, function)


# ---------- the bulk refresh (Settings) ----------

# Every (item, colour) the collection holds or wants: set copies, their lines, loose stock, loose figures' parts and wishes.
HELD = '''WITH held(item_id, color_id) AS (
    SELECT c.item_id, NULL FROM main.copy c WHERE c.archived_at IS NULL
    UNION SELECT p.item_id, p.color_id FROM main.copy_part p JOIN main.copy c ON c.id=p.copy_id WHERE c.archived_at IS NULL AND p.retired_at IS NULL
    UNION SELECT f.item_id, NULL FROM main.copy_figure f JOIN main.copy c ON c.id=f.copy_id WHERE c.archived_at IS NULL AND f.retired_at IS NULL
    UNION SELECT item_id, color_id FROM main.stock WHERE archived_at IS NULL
    UNION SELECT p.item_id, p.color_id FROM main.stock_part p JOIN main.stock s ON s.id=p.stock_id WHERE s.archived_at IS NULL AND p.retired_at IS NULL
    UNION SELECT item_id, color_id FROM main.wish WHERE archived_at IS NULL)
'''


def _held(db):
    return db.execute(HELD + '''SELECT h.item_id, h.color_id, i.kind, i.born_key IS NULL AS unidentified FROM held h JOIN main.item i ON i.id=h.item_id
                                WHERE i.merged_into IS NULL ORDER BY h.item_id, h.color_id''').fetchall()


def state(db):
    """Coverage from database rows only (no file is opened): per kind how many held (item, colour) pairs have a picture, which
    sources they came from, and how many are unidentified (no source can name them)."""
    stored = defaultdict(set)
    for r in db.execute('SELECT item_id, color_id, source FROM main.picture'):
        stored[r['item_id']].add((r['color_id'], r['source']))
    totals = defaultdict(lambda: defaultdict(int))
    sources = defaultdict(lambda: defaultdict(set))
    for item_id, color_id, kind, unidentified in _held(db):
        found = [s for c, s in stored.get(item_id, ()) if c is None or c == color_id]
        t = totals[kind]
        t['total'] += 1
        t['with_picture'] += bool(found)
        t['missing'] += not found
        t['unidentified'] += bool(unidentified)
        for s in found:
            sources[kind][s].add((item_id, color_id))
    summary = [dict(kind=kind, label=label, total=totals[kind]['total'], with_picture=totals[kind]['with_picture'],
                    missing=totals[kind]['missing'], unidentified=totals[kind]['unidentified'],
                    sources={s: len(sources[kind].get(s, ())) for s in SOURCES})
               for kind, label in KIND_LABELS.items()]
    return dict(summary=summary, unidentified=sum(t['unidentified'] for t in totals.values()))


def _per_item(db):
    """One entry per held item: its kind, whether it is unidentified and whether some colour of it has no picture."""
    stored = defaultdict(set)
    for r in db.execute('SELECT item_id, color_id FROM main.picture'):
        stored[r['item_id']].add(r['color_id'])
    per_item = {}
    for item_id, color_id, kind, unidentified in _held(db):
        entry = per_item.setdefault(item_id, dict(kind=kind, unidentified=bool(unidentified), missing=False))
        have = stored.get(item_id, set())
        entry['missing'] |= not (None in have or color_id in have)
    return per_item


def selection(db, scope, kinds):
    """The items a refresh would queue: one entry per item (not per colour) of the chosen kinds, `missing` those with a colour that has
    no picture, `all` every held item. Unidentified items are left out (no source can name them) and counted separately."""
    kinds = sorted(set(kinds))
    if scope not in ('missing', 'all') or not kinds or set(kinds) - set(KIND_LABELS):
        raise ValueError('Choose a scope and item kinds')
    per_item = {i: e for i, e in _per_item(db).items() if e['kind'] in kinds}
    ids = [i for i, e in per_item.items() if not e['unidentified'] and (scope == 'all' or e['missing'])]
    return dict(item_ids=ids, unidentified=sum(e['unidentified'] for e in per_item.values()))


def matrix(db):
    """What the refresh dialog adds up (`bw-pictures.js`): per kind and scope how many items a refresh would queue, how many unidentified
    ones it would leave out (`unresolved`), and `unknown_colour`, which 4.0 has none of. The dialog also asks for the kind `?`."""
    empty = lambda: {scope: dict(count=0, unresolved=0, unknown_colour=0) for scope in ('missing', 'all')}
    result = {kind: empty() for kind in KIND_LABELS}
    result['?'] = empty()
    for entry in _per_item(db).values():
        for scope in ('missing', 'all'):
            if entry['unidentified']:
                result[entry['kind']][scope]['unresolved'] += 1
            elif scope == 'all' or entry['missing']:
                result[entry['kind']][scope]['count'] += 1
    return result


def queue(db, scope, kinds, expected_count=None, via='app', actor=None):
    """Queue a `pictures` job for each selected item that has no live pictures job. Returns `(job ids, selected count)`; with
    `expected_count` the call refuses when the estimate on the page no longer matches, so a confirmation is never a surprise."""
    pipe = pipeline.Pipeline(db)
    with transaction(db):
        chosen = selection(db, scope, kinds)['item_ids']
        if expected_count is not None and int(expected_count) != len(chosen):
            raise ValueError(f'{len(chosen)} items now match, not {int(expected_count)} · review the count and confirm again')
        busy = {r[0] for r in db.execute("""SELECT DISTINCT j.item_id FROM main.job j JOIN main.job_step s ON s.job_id=j.id
            WHERE j.kind=? AND s.name='pictures' AND s.state IN ('queued','running','waiting_for_budget') AND j.state IN ('queued','running','waiting_for_budget')""",
                                  (pipeline.KIND,))}
        jobs = [pipe.queue_steps(i, ['pictures'], via=via, actor=actor, refresh=scope == 'all') for i in chosen if i not in busy]
    return jobs, len(chosen)
