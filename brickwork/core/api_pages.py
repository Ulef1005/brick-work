"""Bounded SQL pages for append-only histories and growing operational tables."""
import base64
import hashlib
import json
from . import api_reads as read, collection, errors


def page(db, resource, args):
    allowed = {'cursor', 'limit', 'direction', 'sort'}
    filters = {'events': {'entity','field','via','since','undoable'},
               'jobs': {'state','failed','source'},
               'prices': {'item_type','item_no','color_id','condition','guide','source'},
               'price-history': {'item_type','item_no','color_id','condition','guide','source'}}[resource]
    if set(args) - allowed - filters or args.get('sort', 'index' if resource != 'prices' else 'number') not in ('index','number'):
        raise errors.UnknownFilter()
    direction = args.get('direction', 'asc' if resource == 'prices' else 'desc')
    if direction not in ('asc','desc'): raise errors.UnknownFilter()
    try:
        limit = int(args.get('limit', 50))
        if not 1 <= limit <= 200: raise ValueError()
    except (TypeError, ValueError): raise errors.BadRequest('Invalid limit') from None
    signature = hashlib.sha256(json.dumps([resource, {k:v for k,v in args.items() if k not in ('cursor','limit')}], sort_keys=True).encode()).hexdigest()
    clauses, params = [], []
    has_steps = resource == 'jobs' and db.execute("SELECT 1 FROM sqlite_master WHERE name='import_steps'").fetchone()
    if resource == 'events':
        select = f'SELECT e.*, {read.undone_sql()} undone, {read.undoable_sql()} undoable FROM events e'
        identity = 'e.id'
    elif resource == 'jobs':
        select, identity = 'SELECT e.* FROM jobs e', 'e.id'
    elif resource == 'price-history':
        select, identity = 'SELECT e.* FROM price_observations e', 'e.id'
    else:
        select = """SELECT e.rowid _page_id,e.*,o.source,o.price,o.min,o.max,o.qty,o.sold,o.observed_at,o.error,
            f.max_age_days FROM price_current e JOIN price_observations o ON o.id=e.observation_id
            LEFT JOIN source_freshness f ON f.source=o.source AND f.kind='prices'"""
        identity = 'e.rowid'
    for key in filters:
        if key not in args: continue
        value = args[key]
        if key in ('undoable','failed'):
            if value not in ('true','false'): raise errors.UnknownFilter()
            expr = f'({read.undoable_sql()} AND NOT {read.undone_sql()})' if key == 'undoable' else "(e.state='failed' OR EXISTS(SELECT 1 FROM import_steps s WHERE s.job_id=e.id AND s.state='failed'))"
            if key == 'failed' and not has_steps: expr = "(e.state='failed')"
            clauses.append(expr + ('=1' if value == 'true' else '=0'))
        elif key == 'since': clauses.append('e.at>=?'); params.append(value)
        elif key == 'entity': clauses.append('substr(e.entity,1,length(?))=?'); params.extend([value,value])
        else:
            col = 'o.source' if key == 'source' and resource == 'prices' else 'e.'+key
            if key == 'condition': value = {'new':'N','used':'U','damaged':'D'}.get(value,value)
            clauses.append(col+' IS ?'); params.append(None if value == 'null' else value)
    if args.get('cursor'):
        try:
            cursor = json.loads(base64.urlsafe_b64decode(args['cursor'] + '='*(-len(args['cursor'])%4)))
            if cursor['signature'] != signature or type(cursor['after']) is not int: raise ValueError()
            clauses.append(identity+('>?' if direction == 'asc' else '<?')); params.append(cursor['after'])
        except (ValueError, TypeError, KeyError): raise errors.BadRequest('Invalid cursor') from None
    values = read.rows(db, select + (' WHERE '+' AND '.join(clauses) if clauses else '') + ' ORDER BY '+identity+' '+direction+' LIMIT ?', (*params,limit+1))
    after = None
    if len(values)>limit:
        values = values[:limit]
        after = base64.urlsafe_b64encode(json.dumps(dict(signature=signature,after=values[-1]['_page_id' if resource=='prices' else 'id'])).encode()).decode().rstrip('=')
    if resource == 'events': values = read.event_values(values)
    elif resource == 'prices': values = collection.decorate_prices(values)
    elif resource == 'jobs':
        steps = {}
        for r in (db.execute('SELECT * FROM import_steps WHERE job_id IN (SELECT value FROM json_each(?)) ORDER BY job_id,position', (json.dumps([r['id'] for r in values]),)) if has_steps else []):
            steps.setdefault(r['job_id'], []).append(dict(r))
        values = [dict(r,steps=steps.get(r['id'],[])) for r in values]
    return dict(data=values,page=dict(next_cursor=after,limit=limit,total=None))
