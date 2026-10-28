"""Sources, their keys and the catalogue import (M.11d, issue #113).

A source is a row of `source` and a client class (`core/source_ops.py`). Its key is the encrypted store of `core/keys.py` (environment first;
write-only: only `configured`, `origin` and `saved_at` ever leave), a user token or hash for the collection sync is the same store under the
`<source>_user` name. A call that reaches the network (a key test, a connect) runs outside any transaction (`write(detached=True)`); an
exhausted budget answers `429` with `Retry-After`. `POST /catalogue/import` loads the BrickLink item lists into the catalogue as the Tools &
Admin page does (`web/catalogue_jobs.py`). `POST /colors/sync` is gone: the colours come with the catalogue builds (M.8f)."""
from contextlib import closing

from ..core import errors, keys, source_ops, sync
from ..core.sources.base import now
from . import route
from .read import arguments, page, reading, record, respond
from .writes import Done, write


# ---------- the Source body ----------

def source_body(db, source):
    """`Source`: the switch, the key state (never a value), the day's budget and use, the last success and the last error."""
    shown = source_ops.view(db, source)
    failed = db.execute('SELECT error FROM main.job WHERE source=? AND error IS NOT NULL ORDER BY updated_at DESC, id DESC LIMIT 1', (source,)).fetchone()
    return {'source': source, 'name': shown['name'], 'kind': shown['kind'], 'enabled': shown['enabled'], 'key': shown['key_state'],
            'budget': shown['budget'], 'used_today': shown['used_today'], 'last_success': shown['last_success'], 'last_error': failed['error'] if failed else None}


@route('/sources')
@reading
def get_sources(db):
    args = arguments()
    direction = args.get('direction', 'asc')
    if direction not in ('asc', 'desc'):
        raise errors.UnknownFilter('direction is asc or desc')
    records = [record(name, name, name=name, _body=source_body(db, name)) for name in sorted(source_ops.clients())]
    return page(records, {k: v for k, v in args.items() if k in ('cursor', 'limit', 'direction')}, default_sort='number')


@route('/sources/<source>', 'PATCH')
@write
def patch_sources_by_source(db, body, source):
    source_ops.known(source)
    source_ops.toggle(db, source, body['enabled'])
    return Done(source_body(db, source))


# ---------- keys ----------

@route('/sources/<source>/key', 'PUT')
@write
def put_sources_by_source_key(db, body, source):
    keys.known(source)
    keys.save(db, source, body)
    return Done(source_body(db, source))


@route('/sources/<source>/key', 'DELETE')
@write
def delete_sources_by_source_key(db, body, source):
    keys.known(source)
    keys.archive(db, source)
    return Done(source_body(db, source))


@route('/sources/<source>/key/test', 'POST')
@write(detached=True)
def post_sources_by_source_key_test(db, body, source):
    keys.known(source)
    return Done(keys.check(db, source))


# ---------- the user credential of the collection sync ----------

@route('/sources/<source>/user', 'PUT')
@write
def put_sources_by_source_user(db, body, source):
    return Done(sync.paste(db, source, body['value']))


@route('/sources/<source>/user', 'DELETE')
@write
def delete_sources_by_source_user(db, body, source):
    return Done(sync.remove(db, source))


@route('/sources/<source>/user/connect', 'POST')
@write(detached=True)
def post_sources_by_source_user_connect(db, body, source):
    from ..core import secrets
    secrets.remember(body['password'])                       # the password is redacted from anything this request says
    return Done(sync.connect(db, source, body['username'], body['password']))


@route('/sources/<source>/user/test', 'POST')
@write(detached=True)
def post_sources_by_source_user_test(db, body, source):
    return Done(sync.test(db, source))


# ---------- the catalogue ----------

def catalogue_status(paths):
    """`CatalogueStatus`: whether a catalogue is loaded, what it holds, its builds, the link coverage and the last reconcile."""
    from ..store4 import status
    from ..store4.connect import connect
    build = status.catalogue_build(paths)
    if build is None:
        return {'loaded': False}
    builds, coverage = [], {}
    if paths.collection.exists():
        with closing(connect(paths.collection, paths.catalogue, read_only=True)) as db:
            builds = [{'id': r['id'], 'built_at': r['activated_at'], 'dump_date': None, 'mapping_version': r['mapping_version'],
                       'local_mapping_manifest': None, 'bricklink_list': None, 'activated': True}
                      for r in db.execute('SELECT id, activated_at, mapping_version FROM main.catalogue_build ORDER BY id')]
            coverage = {r[0]: r[1] for r in db.execute('SELECT status, count(*) FROM main.item_link GROUP BY status')}
    last = build.get('last_reconcile')
    return {'loaded': True, 'items': build['items'], 'builds': builds,
            'coverage': {k: coverage.get(k, 0) for k in ('matched', 'inferred', 'manual', 'to_check')},
            'last_reconcile': {'at': build['reconciled_at'], 'summary': last} if last else None}


@route('/catalogue/import', 'POST')
@write(detached=True)
def post_catalogue_import(db, body):
    """Load the newest folder of BrickLink item lists into the catalogue and reconcile the collection with it (the page's Load lists)."""
    from ..web import admin_ops, catalogue_jobs
    paths = admin_ops.store4_paths()
    state = catalogue_jobs.start(paths, 'lists', background=False)
    if state['state'] != 'done':
        raise errors.ValidationFailed(state.get('error') or 'The lists could not be loaded')
    return Done(catalogue_status(paths))
