"""Identify on the 4.0 store (M.8h, issue #110; design 5 `identification`, 3.2, 3.8): photo recognition mapped to item ids, and its history.

**Recognition.** Brickognize (`core/sources/brickognize.py`, budgeted and audited like every source) answers with BrickLink-style type
letters and numbers. `candidates` turns each prediction into an item of the collection or catalogue, by the rules every number a person
or a provider gives follows: the Rebrickable (born) number first, then the items a confirmed BrickLink link names (the pooled
`store4.identity.candidate_items`: collection and catalogue together), then the catalogue's search index. A number that still names
several items is **listed apart as ambiguous, never guessed**; a number that names none is listed apart as unknown.
`recognise` is the one call the screens make (Part to Inventory, What is this?, Add's photo mode): photo → choices and the unlisted.

**History.** `store` keeps one result in `identification` (candidates with their names and scores, a clean 256 px thumbnail under
`data/identifications/`; the original photo stays in memory); `archive` hides it. Both write an `identification:<id>` event
(`create`, `archive`) that `undo` reverses: created → archived, archived → restored, refused when the record changed since. The
Part to Inventory batch writes its own records inside its batch receipt (`core/part_inventory.py`) and is undone with the batch.
"""
from io import BytesIO
import json
from pathlib import Path
from uuid import uuid4
import warnings

from PIL import Image, ImageOps

from ..store4 import identity
from ..store4.connect import has_catalogue, now as stamp_now
from ..store4.seeds import LOCAL_BASE
from . import errors, items
from . import undo as undoing
from .admin import audit
from .transaction import on_rollback, transaction

PREDICTED_KINDS = {'P': 'part', 'M': 'minifigure', 'S': 'set'}
ENDPOINTS = {'part': 'parts', 'minifigure': 'figs'}           # the endpoint of a person's part / minifigure choice; anything else asks the general one


def thumbnail(data):
    """A clean JPEG thumbnail (EXIF, ICC and other metadata dropped), or None if unreadable."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                oriented = ImageOps.exif_transpose(source)
                oriented.thumbnail((256, 256), Image.Resampling.LANCZOS)
                clean = Image.new('RGB', oriented.size)
                clean.paste(oriented.convert('RGB'))
                output = BytesIO()
                clean.save(output, format='JPEG', quality=80)
                return output.getvalue()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return None


# ---------- recognition → items ----------

def _linked(db, letter, number):
    """Every item a confirmed BrickLink link names by this number, whatever colour the link is scoped to: a photo has no reliable colour, so
    a number that names different items in different colours is as ambiguous as one that names two in all colours."""
    found = set()
    marks = ','.join('?' * len(identity.CONFIRMED))
    for store in ('main', 'catalogue') if has_catalogue(db) else ('main',):
        owned = '' if store == 'main' else 'AND item_id NOT IN (SELECT id FROM main.item)'
        found.update(r[0] for r in db.execute(f"""SELECT item_id FROM {store}.item_link WHERE provider='bricklink' AND provider_kind=? AND provider_key=?
                                                 AND status IN ({marks}) {owned}""", (letter, number, *identity.CONFIRMED)))
    return found


def pick(db, kind, number):
    """`(item id or None, why)` for a number a provider gave: the born match, else the one item a confirmed BrickLink link names, else the
    one item the search index finds. Several candidates at the same step place nothing (`why` says so)."""
    hits = items.find(db, kind, number, limit=20)
    born = [h['item_id'] for h in hits if h['matched_by'] == 'born']
    if born:
        usual = [i for i in born if i < LOCAL_BASE] or born            # the Rebrickable-born item before a local BrickLink-born one of the same number
        return (usual[0], None) if len(usual) == 1 else (None, 'Several catalogue items have this number')
    linked = sorted({items._merged_target(db, i) for i in _linked(db, items.type_of_kind(kind), number)})
    if len(linked) == 1:
        return linked[0], None
    if linked:
        return None, 'Several catalogue items share this BrickLink number'
    if len(hits) == 1:
        return hits[0]['item_id'], None
    if hits:
        return None, 'Several catalogue items match this number'
    return None, 'Unknown catalogue identity'


def candidates(db, predictions, *, kinds=('part', 'minifigure')):
    """`(choices, unresolved)` for recognition predictions `[dict(item_type 'P'|'M'|'S', item_no, score)]`.

    A choice is the item decorated for a screen (`collection.decorate`) with `score` and what you already hold of it (`owned_summary`). A
    prediction of another kind than `kinds` is left out; one that names no item, several items, or an item still to check is listed in
    `unresolved` with its reason."""
    from . import collection, ownership
    result, unresolved, named, looked = [], [], [], {}
    for prediction in predictions[:9]:
        kind = PREDICTED_KINDS.get(prediction['item_type'])
        if kind not in kinds:
            continue
        if (kind, prediction['item_no']) not in looked:
            looked[kind, prediction['item_no']] = pick(db, kind, prediction['item_no'])
        item_id, why = looked[kind, prediction['item_no']]
        if item_id is None:
            unresolved.append(dict(**prediction, reason=why))
        else:
            named.append((prediction, item_id))
    for (prediction, _), row in zip(named, collection.decorate(db, [dict(item_id=item_id, score=p['score']) for p, item_id in named])):
        if row['unresolved']:
            unresolved.append(dict(**prediction, reason='To check'))
        else:
            result.append(row)
    # What you already hold of each candidate, across colours, and which copies need it.
    owned = ownership.summary(db, [r['item_id'] for r in result])
    for row in result:
        info = owned.get(row['item_id'])
        row['owned_summary'] = dict(info, text=ownership.text(info)) if info else dict(total=0, colours=[], needed_by=[], needed_count=0, text=ownership.text(None))
    return result, unresolved


def recognise(db, photo, kind=None, *, kinds=('part', 'minifigure'), http=None):
    """Ask Brickognize about a photo and map the answer: `(choices, unresolved)`. `kind` (`part`, `minifigure` or None) picks the endpoint. The
    source counts the call against the daily budget and keeps the reply; a failure is a `SourceError` with no key in it."""
    from .sources.brickognize import Brickognize
    return candidates(db, Brickognize(db, http=http).predict(photo, ENDPOINTS.get(kind)), kinds=kinds)


# ---------- the history ----------

def store(db, root, photo, candidate_rows):
    """Record one result and its thumbnail in the caller's transaction; audited for Undo."""
    identifier = str(uuid4())
    shown = []
    for row in candidate_rows:
        row = dict(row)
        if row.get('item_id') is not None and not row.get('name'):
            try:
                row['name'] = items.label(db, row['item_id']).name
            except errors.NotFound:
                row['name'] = None
        shown.append(row)
    thumb = thumbnail(photo)
    stamp = stamp_now()
    with transaction(db):
        db.execute('INSERT INTO main.identification(id,created_at,has_thumb,candidates,missing_count) VALUES(?,?,?,?,0)',
                   (identifier, stamp, int(thumb is not None), json.dumps(shown)))
        if thumb is not None:
            target = Path(root).resolve() / 'data/identifications' / (identifier + '.jpg')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(thumb)
            on_rollback(db, lambda: target.unlink(missing_ok=True))
        audit(db, 'identification:' + identifier, 'create', new=dict(id=identifier, archived_at=None))
    return dict(id=identifier, created_at=stamp, has_thumb=thumb is not None, missing_count=0, candidates=shown, archived_at=None)


def archive(db, identifier):
    """Archive a record (thumbnail kept); Undo restores it."""
    with transaction(db):
        row = db.execute('SELECT archived_at FROM main.identification WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise errors.NotFound()
        if row[0] is not None:
            raise errors.Archived()
        stamp = stamp_now()
        db.execute('UPDATE main.identification SET archived_at=? WHERE id=?', (stamp, identifier))
        audit(db, 'identification:' + identifier, 'archive', new=dict(id=identifier, archived_at=stamp))


def _undo(db, event, via, actor):
    """Created → archived, archived → restored; refuses when the record changed since."""
    value = json.loads(event['new_value'])
    identifier = value['id']
    row = db.execute('SELECT archived_at FROM main.identification WHERE id=?', (identifier,)).fetchone()
    if row is None:
        raise errors.NotUndoable()
    if event['field'] == 'create':
        if row[0] is not None:
            raise ValueError('Item changed · undo the later save first')
        db.execute('UPDATE main.identification SET archived_at=? WHERE id=?', (stamp_now(), identifier))
    else:
        if row[0] != value['archived_at']:
            raise ValueError('Item changed · undo the later save first')
        db.execute('UPDATE main.identification SET archived_at=NULL WHERE id=?', (identifier,))
    audit(db, 'identification:' + identifier, 'undo', None, dict(undoes=event['id']), via=via, actor=actor)
    undo_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.execute('INSERT INTO main.event_undo(event_id, undo_event_id) VALUES(?, ?)', (event['id'], undo_id))
    return {'event_id': undo_id}


undoing.register('identification', 'create', _undo)
undoing.register('identification', 'archive', _undo)


def undo(db, event_id):
    """Undo a stored or archived record by its event id; a second Undo does nothing."""
    row = db.execute('SELECT entity_kind FROM main.event WHERE id=?', (int(event_id),)).fetchone()
    if row is None or row['entity_kind'] != 'identification':
        raise ValueError('Choose an identification')
    return undoing.undo_event(db, int(event_id), via='app')
