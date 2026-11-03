"""One Brick Work admin CLI; services live in admin_ops."""
import argparse
from contextlib import contextmanager
import json
import sys

from flask import Flask

from .. import settings
from . import admin_ops

READ_OPERATIONS = set()
SETTING_KEYS = ('bricklink_region', 'bricklink_currency', 'incomplete_discount_pct', 'retail_country')


def build_parser():
    def parser(parent, name, operation=None):
        sub = parent.add_parser(name)
        sub.add_argument('--json', action='store_true', default=argparse.SUPPRESS,
                         help='print the service result as JSON')
        if operation:
            sub.set_defaults(operation=operation)
        return sub

    root = argparse.ArgumentParser(prog='brickwork', description=__doc__)
    root.add_argument('--json', action='store_true')
    commands = root.add_subparsers(required=True)
    mcp = parser(commands, 'mcp', 'mcp')
    mcp.add_argument('--transport', choices=('stdio', 'http'), default='stdio')
    mcp.add_argument('--in-process', action='store_true')
    mcp.add_argument('--api-url', default='http://127.0.0.1:5000/api/v2')
    mcp.add_argument('--token-file')
    mcp.add_argument('--allow-write', action='store_true')
    mcp.add_argument('--host', default='127.0.0.1')
    mcp.add_argument('--port', type=int, default=5000)
    token = parser(commands, 'token').add_subparsers(required=True)
    sub = parser(token, 'create', 'token_create')
    sub.add_argument('--name', required=True)
    sub.add_argument('--scope', default='read')
    sub.add_argument('--expires')
    parser(token, 'list', 'token_list')
    parser(token, 'revoke', 'token_revoke').add_argument('id')
    parser(commands, 'setup', 'setup')
    parser(commands, 'check', 'brickwork_check')
    parser(commands, 'worker', 'jobs_worker')
    # The 3.3 -> 4.0 migration is store4's; this is the name the design gives it (`brickwork migrate4`, data-model-design 8.2).
    migrate4 = parser(commands, 'migrate4', 'migrate4')
    migrate4.add_argument('--in', dest='src', required=True, help='the 3.3 collection file (read-only; stop the 3.3 app or give a copy)')
    migrate4.add_argument('--catalogue', required=True, help='the catalogue.db the mint resolves against')
    migrate4.add_argument('--mappings', required=True, help='the mappings directory the catalogue was built with')
    migrate4.add_argument('--out', required=True, help='the 4.0 file to create (must not exist)')
    migrate4.add_argument('--report', required=True, help='the report folder (new or empty)')
    migrate4.add_argument('--pin', help='proof.json or summary.md of an earlier run to pin the catalogue and mappings to')
    catalogue = parser(commands, 'catalogue').add_subparsers(required=True)
    parser(catalogue, 'status', 'catalogue_status')
    sources = parser(catalogue, 'import').add_subparsers(required=True)
    bl = parser(sources, 'bricklink', 'catalogue_import_bricklink')
    bl.add_argument('--from', dest='directory', required=True)
    source_commands = parser(commands, 'sources').add_subparsers(required=True)
    parser(source_commands, 'status', 'sources_status')
    brickset_commands = parser(commands, 'brickset').add_subparsers(required=True)
    parser(brickset_commands, 'refresh', 'brickset_refresh').add_argument('sets', nargs='*')
    sub = parser(commands, 'import', 'import_item')
    sub.add_argument('item_type', choices=tuple('SPMGBCIO'))
    sub.add_argument('item_no')
    sub = parser(commands, 'import-bricktracker', 'import_bricktracker')
    sub.add_argument('source', nargs='?', help='BrickTracker app.db (opened read-only)')
    sub.add_argument('--plan-only', action='store_true', help='make the plan and stop')
    sub.add_argument('--apply', dest='plan_id', help='apply a stored plan')
    sub.add_argument('--decisions', help='JSON file mapping row keys to add or skip')
    sub = parser(commands, 'sync', 'sync_command')
    sub.add_argument('source', choices=('rebrickable', 'brickset'))
    sub.add_argument('action', choices=('status', 'lists', 'link', 'pull', 'send', 'connect', 'paste', 'remove', 'test'))
    sub.add_argument('--apply', dest='plan_id', help='apply a stored pull or send plan')
    sub.add_argument('--tick', action='append', help='a row key to tick (repeat); default: the suggested rows')
    sub.add_argument('--owned', type=int, action='append', help='link: an owned Rebrickable set list id (repeat)')
    sub.add_argument('--wishlist', type=int, help='link: the Rebrickable wishlist set list id')
    sub.add_argument('--send-to', type=int, help='link: the owned list that receives sends')
    sub.add_argument('--wish-list', help='link: the Brick Work wishlist id (default: default)')
    sub.add_argument('--username', help='connect: your username on the site (the password is asked for)')
    jobs = parser(commands, 'jobs', 'jobs_list')
    jobs.add_argument('--failed', action='store_true')
    job_commands = jobs.add_subparsers()
    sub = parser(job_commands, 'retry', 'jobs_retry')
    sub.add_argument('job', type=int)
    sub.add_argument('step', nargs='?')
    prices = parser(commands, 'prices').add_subparsers(required=True)
    parser(prices, 'refresh', 'prices_refresh').add_argument('set_num')
    settings = parser(commands, 'settings').add_subparsers(required=True)
    parser(settings, 'show', 'settings_show')
    sub = parser(settings, 'set', 'settings_set')
    from ..core.items import KINDS
    sub.add_argument('key', choices=SETTING_KEYS + ('source_priority',) + tuple('import_order:' + kind for kind in KINDS))
    sub.add_argument('value')
    wishes = parser(commands, 'wishlist').add_subparsers(required=True)
    parser(wishes, 'list', 'wishlist_list').add_argument('--archived', action='store_true')
    parser(wishes, 'create', 'wishlist_create').add_argument('name')
    sub = parser(wishes, 'rename', 'wishlist_rename'); sub.add_argument('list'); sub.add_argument('name')
    for action in ('archive','restore'):
        parser(wishes, action, 'wishlist_'+action).add_argument('list')
    for action in ('move','copy'):
        sub = parser(wishes, action, 'wishlist_'+action)
        sub.add_argument('list'); sub.add_argument('ids', nargs='+', help='wish ids (see the item page or `wishlist list`)')
    sub = parser(wishes, 'export', 'wishlist_export')
    sub.add_argument('list', help='Wishlist id, exact name, or all')
    sub.add_argument('--format', choices=('bricklink','rebrickable'), required=True)
    sub.add_argument('--kind', choices=('sets','parts'), default='parts')
    parser(wishes, 'undo', 'wishlist_undo').add_argument('event_id', type=int)
    return root


@contextmanager
def application_context(operation):
    app = Flask(__name__)
    settings.apply(app)
    with app.app_context():
        yield


def _safe_error(error):
    # Fetcher exceptions may contain credential-bearing URLs. Never echo keys.
    from flask import current_app, has_app_context
    from ..core.secrets import secret_values
    message = str(error)
    # The wishlist commands report after their application context has closed: the environment's secrets still apply.
    secrets = (secret_values(current_app.config) if has_app_context() else []) + secret_values()
    for secret in sorted(secrets, key=len, reverse=True):
        message = message.replace(secret, '[set]')
    return message


def _human(result, indent=0):
    if isinstance(result, dict):
        for key, value in result.items():
            if isinstance(value, (dict, list)):
                print(' ' * indent + str(key) + ':')
                _human(value, indent + 2)
            else:
                print(' ' * indent + str(key) + ': ' + str(value))
    elif isinstance(result, list):
        if not result:
            print(' ' * indent + '(none)')
        for value in result:
            if isinstance(value, (dict, list)):
                _human(value, indent + 2)
            else:
                print(' ' * indent + str(value))


def _print_check(result):
    """`brickwork check`: the SQLite results as before, then one line per cross-file check, a failure with its message and fix."""
    for name, db in result.items():
        cross = db.get('cross_checks', [])
        print(name + ':')
        _human({k: v for k, v in db.items() if k != 'cross_checks'}, 2)
        if cross:
            print('  cross_checks:')
        for c in cross:
            print(f"    {'ok  ' if c['ok'] else 'FAIL'} {c['name']} · {c['title']}")
            print(f"         {c['message']}")


def main(argv=None):
    parser = build_parser()
    args = vars(parser.parse_args(argv))
    operation = args.pop('operation')
    as_json = args.pop('json')
    if operation == 'mcp':
        from ..core.errors import BrickWorkError
        from ..core.mcp.server import run
        try:
            run(**args)
        except BrickWorkError as error:
            print(f'MCP error: {error}', file=sys.stderr)
            return 1
        return 0
    if operation.startswith('wishlist_'):
        from contextlib import closing
        from ..core import wishlists, collection
        from ..core.connect import connect
        from ..core.sources.base import audit_origin
        try:
            with application_context(operation):
                from ..api import read_only
                reading = operation in ('wishlist_list','wishlist_export')
                if not reading and read_only(): raise ValueError('Read only instance')
                path = admin_ops.brickwork_path()
                if not path.is_file(): raise ValueError("Run 'brickwork setup' first")
                with closing(connect(path, read_only=reading)) as db, audit_origin('cli'):
                    identifier = args.get('list')
                    if identifier and identifier != 'all':
                        matches = [r for r in wishlists.listing(db, archived=True) if r['id']==identifier or r['name']==identifier]
                        if len(matches)!=1: raise ValueError('Choose an unambiguous wishlist id or name')
                        identifier = matches[0]['id']
                    if operation=='wishlist_export':
                        result = wishlists.export(db,identifier,format=args['format'],kind=args['kind'])
                        if not as_json:
                            print(result['content'],end='')
                            print(json.dumps(result['summary']),file=sys.stderr)
                            return 0
                    elif operation=='wishlist_list': result=wishlists.listing(db,archived=args['archived'])
                    elif operation=='wishlist_undo':
                        collection.undo(db,args['event_id']); result=dict(message='Undone')
                    elif operation in ('wishlist_move','wishlist_copy'):
                        result=dict(event_id=wishlists.transfer(db,args['ids'],identifier,copy=operation=='wishlist_copy'))
                    else:
                        target,event=wishlists.save(db,identifier,dict(name=args['name']) if 'name' in args else {},action=operation.removeprefix('wishlist_') if operation in ('wishlist_archive','wishlist_restore') else 'save')
                        result=dict(id=target,event_id=event)
                    if as_json: print(json.dumps(result,indent=2))
                    else: _human(result)
            return 0
        except Exception as error:
            print('Wishlist error: '+_safe_error(error),file=sys.stderr)
            return 1
    if operation.startswith('token_'):

        from contextlib import closing
        from datetime import timedelta
        from ..core import tokens
        from ..core.connect import connect
        from ..core.sources.base import audit_origin, now, redact
        try:
            with application_context(operation):
                from ..api import read_only
                if operation != 'token_list' and read_only():
                    raise ValueError('Read only instance')
                path = admin_ops.brickwork_path()
                if not path.is_file():
                    raise ValueError("Run 'brickwork setup' first")
                with closing(connect(path)) as db, audit_origin('cli'):
                    if operation == 'token_create':
                        expires = args.get('expires')
                        if expires:
                            if not expires.endswith('d') or not expires[:-1].isdigit():
                                raise ValueError('Expiry must be a duration such as 90d')
                            expires = (now() + timedelta(days=int(expires[:-1]))).isoformat()
                        result, _ = tokens.create(db, args['name'], args['scope'].split(','), expires)
                    elif operation == 'token_revoke':
                        result, _ = tokens.revoke(db, args['id'])
                    else:
                        result = tokens.listing(db)
                    print(json.dumps(result, indent=2))
            return 0
        except Exception as error:
            print(f'Token error: {redact(error)}', file=sys.stderr)
            return 1
    if operation == 'migrate4':
        argv = ['--in', args['src'], '--catalogue', args['catalogue'], '--mappings', args['mappings'], '--out', args['out'], '--report', args['report']]
        argv += ['--pin', args['pin']] if args.get('pin') else []
        return admin_ops.migrate4(argv + (['--json'] if as_json else []))
    if operation == 'import_bricktracker' and bool(args.get('source')) == bool(args.get('plan_id')):
        parser.error('give either an app.db or --apply PLAN')
    if args.get('limit') is not None and args['limit'] < 0:
        parser.error('--limit must be non-negative')
    for key in ('box', 'instructions'):
        if key in args and args[key] is not None:
            args[key] = args[key] == 'yes'
    try:
        with application_context(operation):
            try:
                service = getattr(admin_ops, operation)
                if operation in ('import_item', 'jobs_retry'):
                    args.pop('failed', None)
                    if not as_json:
                        args['progress'] = lambda event, payload: print(payload['message'], flush=True)
                result = service(**args)
                if as_json:
                    print(json.dumps(result, indent=2))
                elif operation == 'brickwork_check':
                    _print_check(result)
                elif operation in ('import_item', 'jobs_retry', 'jobs_list'):
                    rows = result if isinstance(result, list) else [result]
                    if not rows:
                        print('(none)')
                    for job in rows:
                        key = f"item {job['item_id']}" if job.get('item_id') else ''
                        state = job['state'].replace('_', ' ')
                        print(' · '.join(part for part in (f"Job {job.get('id', '?')}", key, state) if part))
                else:
                    _human(result)
                if operation in ('import_item', 'jobs_retry') and result['state'] == 'failed':
                    return 1
                if operation in ('check', 'brickwork_check') and any(
                        db['integrity_check'] != ['ok'] or db['foreign_key_check'] or db.get('catalogue_integrity_check', ['ok']) != ['ok']
                        or not all(c['ok'] for c in db.get('cross_checks', ()))
                        for db in result.values()):
                    return 1
                if (
                        (operation == 'prices_refresh' and result.get('ok') is False) or
                        (operation == 'prices_refresh_due' and any(value is False for value in result.values()))):
                    return 1
                return 0
            except Exception as error:
                print(f'Web error: {_safe_error(error)}', file=sys.stderr)
                return 1
    except Exception:
        print('Web error: could not initialize application context', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
