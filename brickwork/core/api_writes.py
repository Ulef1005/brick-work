"""API write orchestration; domain mutations remain in their existing core owners."""
from datetime import datetime, timedelta
import hashlib
import json
import re
import uuid

from . import add, admin, api_reads as read, collection, errors, identify, keys, ledger, planning, source_ops, tokens, workbench, checker, manual_prices, part_inventory
from .sources.base import now
from .receipts import is_receipt
from .transaction import transaction
from .audit_bundle import capture, latest

CLAIM_SECONDS = 900  # a crashed request's claim expires after this
TABLES = dict(copies='copies', stock='loose_stock', wishes='wishlist', lots='lots',
              places='purchase_locations', flags='flags', storages='storages', **{'instruction-files':'instruction_files'})
ENTITIES = dict(copies='copy', stock='stock', wishes='wish', lots='lot')


def _checked_key(key, required):
    if not key and required: raise errors.IdempotencyKeyRequired()
    if key is not None and not re.fullmatch(r'[A-Za-z0-9-]{1,80}', key): raise errors.BadRequest('Invalid Idempotency-Key')


def _digest(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',',':')).encode()).hexdigest()


def _replay(db, key, method, path, digest, token_name):
    """The stored response for a repeated key within 30 days, else None."""
    if not key: return None
    old = db.execute("SELECT new_value FROM events WHERE entity='bw_api' AND field=? AND actor IS ? AND at>=? ORDER BY id DESC LIMIT 1",
                     ('op:'+key, token_name, (now()-timedelta(days=30)).isoformat())).fetchone()
    if not old: return None
    saved = json.loads(old[0])
    if (saved['method'], saved['path'], saved['body_sha256'], saved['token_name']) != (method,path,digest,token_name):
        raise errors.IdempotencyConflict()
    return dict(saved['response'],idempotent_replay=True), saved['status']


def execute(db, *, method, path, body, key, required, token_name, action, serialize=lambda x:x, self_audited=False):
    """Lock, replay/check, mutate, and persist the complete response atomically."""
    _checked_key(key, required)
    digest = _digest(body)
    with transaction(db):
        replay = _replay(db, key, method, path, digest, token_name)
        if replay: return replay
        before = db.execute('SELECT coalesce(max(id),0) FROM events').fetchone()[0]
        preview = body.get('dry_run') is True
        if preview: db.execute('SAVEPOINT api_preview')
        with capture() as captured:
            data, status = action()
        if preview:
            db.execute('ROLLBACK TO api_preview')
            db.execute('RELEASE api_preview')
            return dict(data=serialize(data),event_id=None,undo_url=None,idempotent_replay=False),status
        # An action either hands its audit rows to the bundle or writes its own event (#63). A self-audited
        # action (the checker) may also write nothing when it answers a repeated operation from its own receipt.
        own = db.execute('SELECT coalesce(max(id),0) FROM events').fetchone()[0]
        if not captured and own == before and not self_audited: raise RuntimeError('Mutation did not emit a receipt')
        event = own + 1
        if isinstance(data,dict) and (set(data)=={'message'} or 'document_id' in data): data=dict(data,event_id=event)
        # Core receipts are embedded, never replayed as SQL. Undo still calls their owners.
        receipts = [r for r in captured if is_receipt(r)]
        # Queued work and source calls are audited but cannot be reversed: no undo link.
        result = dict(data=serialize(data),event_id=event,undo_url=f'/api/v1/events/{event}/undo' if receipts else None,idempotent_replay=False)
        if not captured:
            # The action's own event is the one to undo (the events dispatcher undoes checker events).
            last = own if own > before else None
            undoable = bool(last) and bool(read.events(db, last)) and read.events(db, last)[0]['undoable']
            result.update(event_id=last, undo_url=f'/api/v1/events/{last}/undo' if undoable else None)
        saved = dict(method=method,path=path,body_sha256=digest,status=status,response=result,event_id=event,token_name=token_name,receipts=receipts)
        if isinstance(data,dict) and 'undone_event_id' in data:
            saved['undone_event_id'] = data['undone_event_id']
        admin.audit(db,'bw_api','op:'+key if key else 'receipt',new=saved)
        return result,status


def detached(db, *, method, path, body, key, required, token_name, action, serialize=lambda x:x):
    """Run network or long work outside any transaction, then record one event for it.

    The action manages its own transactions (source clients and the pipeline do) and may
    return (data, status) or (data, status, receipts) when part of the work is undoable.
    The action may instead return a callable: its domain mutation and captured
    receipts then run in the final transaction, together with the API event.
    A failed action records no operation event, so the same key can be retried.
    """
    _checked_key(key, required)
    digest = _digest(body)
    claim = None
    with transaction(db):
        replay = _replay(db, key, method, path, digest, token_name)
        if replay: return replay
        if key:
            # The first transaction is serialised by BEGIN IMMEDIATE: a concurrent duplicate sees
            # this claim and is refused instead of running the action a second time.
            claim = f'api:claim:{token_name}:{key}'
            held = db.execute('SELECT value FROM settings WHERE key=?', (claim,)).fetchone()
            if held and (now() - datetime.fromisoformat(held[0])).total_seconds() < CLAIM_SECONDS:
                raise errors.IdempotencyConflict('This Idempotency-Key is still being processed')
            db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)', (claim, now().isoformat()))
    try:
        outcome = action()
        with transaction(db):
            if callable(outcome):
                with capture() as captured:
                    data, status = outcome()
                receipts = [r for r in captured if is_receipt(r)]
            else:
                data, status, receipts = outcome if len(outcome) == 3 else (*outcome, [])
            event = db.execute('SELECT coalesce(max(id),0)+1 FROM events').fetchone()[0]
            if isinstance(data,dict) and 'document_id' in data: data=dict(data,event_id=event)
            result = dict(data=serialize(data),event_id=event,undo_url=f'/api/v1/events/{event}/undo' if receipts else None,idempotent_replay=False)
            saved = dict(method=method,path=path,body_sha256=digest,status=status,response=result,event_id=event,token_name=token_name,receipts=receipts)
            admin.audit(db,'bw_api','op:'+key if key else 'receipt',new=saved)
            if claim: db.execute('DELETE FROM settings WHERE key=?', (claim,))
    except BaseException:
        if claim:
            # A failed action releases the claim so a retry can run.
            with transaction(db):
                db.execute('DELETE FROM settings WHERE key=?', (claim,))
        raise
    return result,status


def check_record(db, resource, identifier, expect=None, *, archived=False):
    saved = read.one(db, 'SELECT * FROM '+TABLES[resource]+' WHERE id=?', (identifier,))
    if expect is not None and resource in ('copies','stock','wishes'):
        if '*' not in expect and read.entity_etag(db, ENTITIES[resource], identifier) not in expect:
            raise errors.PreconditionFailed()
    if saved.get('archived_at') and not archived: raise errors.Archived()
    return saved


def codes(data, entity):
    data = dict(data)
    if entity != 'wish' and 'condition' in data:
        data['condition'] = {'new':'N','used':'U','damaged':'D'}.get(data['condition'], data['condition'])
    if 'completeness' in data:
        data['completeness'] = {'sealed':'S','complete':'C','incomplete':'I'}.get(data['completeness'], data['completeness'])
    return data


def create(db, resource, data):
    entity = ENTITIES[resource]
    kind = 'S' if resource == 'copies' else data.get('item_type')
    if not add.catalogue_path(db).is_file(): raise errors.CatalogueNotLoaded()
    item = add.lookup(db, kind, data.get('item_no'))
    if item is None: raise errors.ValidationFailed('Unknown catalogue identity')
    row = dict(item,where='wishlist' if entity=='wish' else 'owned' if entity=='copy' else 'loose',
               quantity=data.get('quantity',1),color_id=data.get('color_id'),condition={'new':'N','damaged':'D'}.get(data.get('condition'),'U') if entity=='stock' else 'N' if data.get('condition')=='new' else 'U',
               completeness={'sealed':'S','complete':'C','incomplete':'I'}.get(data.get('completeness'),''),
               decision=data.get('decision','another' if entity=='stock' else ''),note=data.get('note'))
    if entity=='wish':row.update(list_id=data.get('list_id','default'), condition={'new':'N','used':'U','any':'X'}.get(data.get('condition'),'X'))
    if entity=='stock':row.update({k:data.get(k) for k in ('storage_id','lot_id')})
    try: validated = add.validate_edits(db,[row],[row])
    except ValueError as exc:
        if 'Already owned' in str(exc): raise errors.Conflict(str(exc)) from None
        raise
    batch = uuid.uuid4().hex  # API replay is scoped per token, unlike the web batch.
    receipts = add.confirm(db,validated,batch=batch,guard=True)
    if not receipts: raise errors.ValidationFailed('No item selected')
    receipt = receipts[0]
    ids = receipt['copies'] if entity=='copy' else receipt['stock'] if entity=='stock' else [receipt['wishlist_id']]
    edits = {k:v for k,v in data.items() if k in ({'storage_id','purchase_location_id','purchase_date','purchase_price','purchase_currency'} if entity=='copy' else set() if entity=='stock' else {'max_price','max_price_currency','note','condition'})}
    if edits: collection.save(db,entity,ids,codes(edits,entity))
    return dict(ids=ids),201


def mutate(db, resource, identifier, action, data, expect=None, content=None, values=None):
    values = values or {}
    if resource == 'wishlists':
        from . import wishlists
        if action == 'transfer':
            event = wishlists.transfer(db, data['ids'], identifier, copy=data.get('copy', False))
            return dict(message='Copied' if data.get('copy') else 'Moved'), 200
        identifier, _ = wishlists.save(db, identifier, data, action={'archive':'archive','restore':'restore'}.get(action, 'save'))
        return dict(db.execute('SELECT * FROM wishlists WHERE id=?', (identifier,)).fetchone()), 201 if action=='create' else 200
    if resource in ('items','prices'):
        entries = [dict(data,item_type=values['type'],item_no=values['no'])] if resource=='items' else data['items']
        ids = manual_prices.record(db,entries)
        if resource=='prices': return dict(applied=len(ids),skipped=[],dry_run=False),200
        return dict(db.execute('SELECT * FROM price_observations WHERE id=?',(ids[0],)).fetchone()),201
    if resource=='copies' and action in ('checked','part','bulk','figure') or resource=='stock' and action=='parts':
        payload = dict(data,action={'part':'mark','figure':'mark_figure','parts':'loose_parts'}.get(action,action))
        if action=='part': payload.update(part_id=values['part_id'],fields=data)
        if action=='figure': payload.update(type=values['type'],no=values['no'])
        result = checker.write(db,identifier,payload,read.root(db))
        if action=='checked': result = read.completeness_read(db,identifier)
        if action=='parts': result = dict(parts=result)
        return result,200
    if resource=='orders':
        from .api_orders import mutate
        return mutate(db,identifier,action,data,values)
    entity = ENTITIES.get(resource)
    if action == 'create' and resource in ('copies','stock','wishes'): return create(db,resource,data)
    if identifier is not None and not (resource=='storages' and identifier=='unstored' and action=='contents'):
        saved = check_record(db,resource,identifier,expect,archived=action=='restore')
    if action == 'photos':
        collection.photo(db,read.root(db),entity,identifier,content,data.get('caption',''))
    elif action == 'restore':
        collection.restore(db,TABLES[resource],identifier)
    elif resource in ENTITIES and action in ('patch','archive','flags'):
        collection.save(db,entity,[identifier],codes(data,entity),archive=action=='archive',expect=expect)
    elif resource == 'copies' and action == 'pin': planning.save(db,'pin',dict(data,id=identifier))
    elif resource == 'copies' and action == 'take':
        if data['item_type']=='M' and data.get('color_id') is not None:
            raise errors.ValidationFailed('A minifigure has no colour · leave color_id out')
        if data['item_type']=='P' and data.get('color_id') is None:
            raise errors.ValidationFailed('Choose the part colour')
        workbench.take_for_gap(db,identifier,data['item_type'],data['item_no'],data.get('color_id'),data['quantity'])
    elif resource == 'stock' and action == 'give':
        workbench.transfer(db,identifier,data['copy_id'],data['target'],data['target_id'],data['quantity'])
    elif resource == 'wishes' and action == 'to-owned':
        incoming = {k:saved[k] for k in ('item_type','item_no','color_id')}
        incoming.update(data,quantity=data.get('quantity',saved['quantity']),decision='another')
        incoming['quantity']=add.quantity(incoming['quantity'])
        if incoming['quantity']>saved['quantity']: raise errors.Conflict('Wished quantity changed')
        created,_ = create(db,'copies' if saved['item_type']=='S' else 'stock',incoming)
        collection.save(db,'wish',[identifier],{'quantity':saved['quantity']-incoming['quantity']} if incoming['quantity']<saved['quantity'] else {},archive=incoming['quantity']==saved['quantity'])
        return created,200
    elif resource == 'storages':
        if action in ('create','patch'): identifier,_ = ledger.storage_save(db,identifier,data['name'],**{k:data[k] for k in ('type','parent_id','note') if k in data})
        elif action == 'archive': ledger.storage_archive(db,identifier,move_to_unstored=data.get('move_to_unstored',False))
        elif action == 'contents': ledger.move(db,None if identifier=='unstored' else identifier,data['selections'])
    elif resource == 'lots' and action == 'create':
        collection.new_lot(db,data['stock_ids'],data)
        identifier = json.loads(latest('bw_collection')['new_value'])[0]['rows'][0]['id']
    elif resource in ('places','flags'):
        group = 'purchase-places' if resource=='places' else {'owner':'owners','status':'statuses','tag':'tags'}[data.get('kind') if action=='create' else saved['kind']]
        admin.value_write(db,group,{'create':'add','patch':'rename','archive':'delete'}[action],identifier,data.get('name'),confirmed=True)
        if identifier is None: identifier = json.loads(latest('bw_collection')['new_value'])[0]['rows'][0]['id']
    elif resource == 'instruction-files':
        if action == 'create': identifier = admin.instruction_upload(db,read.root(db),data['item_type'],data['item_no'],data['label'],content,undoable=True)
        elif action == 'patch': admin.instruction_rename(db,identifier,data['label'],undoable=True)
        elif action == 'archive': admin.instruction_archive(db,identifier)
    elif resource == 'found':
        if not add.lookup(db,data['item_type'],data['item_no']): raise errors.ValidationFailed('Unknown catalogue identity')
        workbench.found(db,data['item_type'],data['item_no'],data['color_id'],data['destination'],data.get('assignments'),data['quantity'])
    elif resource == 'booklets': workbench.booklets(db,data['text'],data.get('quantity',1))
    else: raise errors.ValidationFailed('Unsupported action')
    if resource in ('copies','stock','wishes') and action in ('patch','restore','flags','pin','archive','photos'):
        value = read.entity(db,entity,identifier)
        if entity=='stock':
            value['merged_ids'] = [r['id'] for r in collection.merge_result(db,receipt=latest('bw_collection'))] if action=='patch' else []
    elif action == 'contents': value = dict(message='Saved')
    elif resource == 'instruction-files': value = read.record(db,'instruction-files',identifier)
    elif resource in ('places','flags','storages','lots'): value = dict(db.execute('SELECT * FROM '+TABLES[resource]+' WHERE id=?',(identifier,)).fetchone())
    else: value = dict(message='Saved')
    if action=='archive': value['archived']=True
    return value,201 if action=='create' and resource not in ('found','booklets') else 200


def undo_receipt(db, receipt, identifier):
    entity=receipt['entity']
    if not is_receipt(receipt) and not (entity.startswith('checker:') and receipt['field'].startswith('checker:')):
        raise errors.NotUndoable()
    if entity.startswith('part_inventory:'): part_inventory.undo(db,identifier,receipt=receipt)
    elif entity.startswith('checker:'): checker.write(db,None,dict(action='undo_event',event_id=identifier,receipt=receipt),read.root(db))
    elif entity=='bw_collection': collection.undo(db,identifier,receipt=receipt)
    elif entity=='bw_workbench': workbench.undo(db,identifier,receipt=receipt)
    elif entity=='bw_ledger': ledger.undo(db,identifier,receipt=receipt)
    elif entity=='bw_planning': planning.undo(db,identifier,receipt=receipt)
    elif entity=='bw_manual_prices': manual_prices.undo(db,receipt)
    elif entity.startswith('source_key:'): keys.undo(db,identifier,receipt)
    elif entity.startswith('source:'): source_ops.undo_toggle(db,identifier,receipt)
    elif entity.startswith('identification:'): identify.undo(db,identifier,receipt)
    elif entity=='bw_sync':
        from . import sync
        sync.undo(db,identifier,receipt=json.loads(receipt['new_value']))
    elif entity=='bw_import':
        from .importer import bricktracker
        bricktracker.undo(db,identifier,receipt=json.loads(receipt['new_value']))
    elif entity=='bw_add':
        value=json.loads(receipt['new_value'])
        add.undo(db,value['batch'],saved_receipts=[value])
    else: raise errors.NotUndoable()


ADMIN_ENTITIES = ('bw_token', 'source_key:', 'source:', 'bw_import')


def _admin_entity(entity):
    return any(entity==e if not e.endswith(':') else entity.startswith(e) for e in ADMIN_ENTITIES)


def _needs_admin(db, event, identifier):
    """Undoing a token, key or source change needs the admin scope, as making it did; so does an API
    event that bundles one of them."""
    if _admin_entity(event['entity']): return True
    if event['entity']!='bw_api': return False
    row=db.execute('SELECT new_value FROM events WHERE id=?',(identifier,)).fetchone()
    try: receipts=json.loads(row[0]).get('receipts') or []
    except (TypeError, ValueError, AttributeError): return False
    return any(isinstance(r,dict) and _admin_entity(str(r.get('entity',''))) for r in receipts)


def undo_event(db, identifier, identity, operation):
    event = read.events(db,identifier)
    if not event: raise errors.NotFound()
    event = event[0]
    if _needs_admin(db,event,identifier) and not tokens.permits(identity,'admin'): raise errors.Forbidden()
    if not event['undoable'] and not event['undone']: raise errors.NotUndoable()
    if event['undone']:
        result = dict(undone_event_id=identifier,already_undone=True)
        admin.audit(db,'bw_api','undo',new=result)
        return result
    try:
        if event['entity']=='bw_token':
            result,_,_ = tokens.undo(db,identifier,operation)
            return result
        elif event['entity']=='bw_api':
            raw=json.loads(db.execute('SELECT new_value FROM events WHERE id=?',(identifier,)).fetchone()[0])
            for receipt in reversed(raw['receipts']): undo_receipt(db,receipt,identifier)
        else:
            raw=dict(db.execute('SELECT * FROM events WHERE id=?',(identifier,)).fetchone())
            undo_receipt(db,raw,identifier)
    except errors.BrickWorkError: raise
    except ValueError as exc: raise errors.UndoBlocked(str(exc)) from None
    result = dict(undone_event_id=identifier,already_undone=False)
    admin.audit(db,'bw_api','undo',new=result)
    return result
