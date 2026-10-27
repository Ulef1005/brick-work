"""The audit log and the collection counts (M.11b, issue #113): `/events`, `/events/{id}` and `/statistics`.

An event is a row of the append-only `event` log (design 5): who changed what, from where. A receipt is undoable when its
`(entity_kind, field)` has a registered undoer and no undo record yet (`core/undo.py`); the write that undoes one is M.11c's.
Credential material and the replay receipts of the API never leave through here."""
import json

from ..core import admin, errors, undo
from . import route
from .prices import sql_page
from .read import arguments, flag, integer_id, reading, respond

HIDDEN_KINDS = ('source_key', 'source_key_previous')


def decoded(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def event_body(r):
    entity = r['entity_kind'] + (':' + r['entity_id'] if r['entity_id'] else '')
    hidden = (r['entity_kind'] == 'bw_api' and (r['field'].startswith('op:') or r['field'] == 'receipt')) or r['entity_kind'].startswith(HIDDEN_KINDS)
    return {'actor': r['actor'], 'id': r['id'], 'entity': entity, 'field': r['field'], 'old_value': None if hidden else decoded(r['old_value']),
            'new_value': None if hidden else decoded(r['new_value']), 'at': r['at'], 'via': r['via'],
            'undoable': bool(r['undoable']) and not r['undone'], 'undone': bool(r['undone'])}


def select():
    # The registry of undoers fills as modules import, so the predicate is built when asked, never at import.
    return f'SELECT e.*, {undo.undone_sql()} AS undone, {undo.undoable_sql()} AS undoable FROM main.event e WHERE 1=1'


@route('/events')
@reading
def get_events(db):
    args = arguments()
    direction = args.get('direction', 'desc')
    if direction not in ('asc', 'desc'):
        raise errors.UnknownFilter('direction is asc or desc')
    where, params = '', []
    if args.get('entity'):
        where, params = where + " AND substr(e.entity_kind || coalesce(':' || e.entity_id, ''), 1, length(?))=?", params + [args['entity'], args['entity']]
    if args.get('field'):
        where, params = where + ' AND e.field=?', params + [args['field']]
    if args.get('via'):
        if args['via'] not in ('app', 'cli', 'api', 'import', 'migration'):
            raise errors.UnknownFilter('via is app, cli, api, import or migration')
        where, params = where + ' AND e.via=?', params + [args['via']]
    if args.get('since'):
        where, params = where + ' AND e.at>=?', params + [args['since']]
    wanted = flag(args, 'undoable')
    if wanted is not None:
        where += f' AND ({undo.undoable_sql()} AND NOT {undo.undone_sql()})=' + ('1' if wanted else '0')
    signature = json.dumps([sorted((k, v) for k, v in args.items() if k not in ('cursor', 'limit'))])
    rows, after, limit = sql_page(db, select() + where, params, direction=direction, signature=signature, cursor=args.get('cursor'), limit=args.get('limit', 50), identity='e.id')
    return respond([event_body(r) for r in rows], page={'next_cursor': after, 'limit': limit, 'total': None})


@route('/events/<id>')
@reading
def get_events_by_id(db, id):
    arguments()
    row = db.execute(select() + ' AND e.id=?', (integer_id(id, 'event'),)).fetchone()
    if row is None:
        raise errors.NotFound('No such event')
    return respond(event_body(row))


@route('/statistics')
@reading
def get_statistics(db):
    arguments()
    found = admin.statistics(db)
    return respond({key: found[key] for key in ('completeness', 'theme', 'storage', 'purchase place')})
