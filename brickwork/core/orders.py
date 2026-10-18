"""Document review, receipts and explicit allocation on the BrickLink ledger."""
from contextlib import closing
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import sqlite3
from xml.etree import ElementTree as ET
from uuid import uuid4

from . import add, ledger, workbench as w
from .transaction import transaction
from .sources.bricklink import BrickLink, TYPE_IDS

LIVE = "('applied','pending','conflict','undoing')"


def price(value):
    if value in (None,''):
        return None
    try:
        number=Decimal(str(value))
        if not number.is_finite() or number<0 or number.as_tuple().exponent < -4:
            raise InvalidOperation()
    except InvalidOperation:
        raise ValueError('Use a non-negative price with up to four decimals') from None
    return format(number,'f')


def get(db, order_id):
    row=db.execute('SELECT * FROM orders WHERE id=?',(order_id,)).fetchone()
    if not row:
        raise ValueError('Order is unavailable')
    return dict(row)


def listing(db):
    rows=[dict(r) for r in db.execute("""WITH a AS (
      SELECT line_id,sum(qty) AS allocated FROM allocations WHERE state IN """+LIVE+""" GROUP BY line_id),
      l AS (SELECT l.order_id,count(*) AS lots,sum(l.qty) AS pieces,
      sum(coalesce(r.received,0)) AS received,sum(coalesce(a.allocated,0)) AS allocated,sum(l.state='held') AS held
      FROM order_lines l JOIN order_documents d ON d.id=l.document_id
      LEFT JOIN line_receipts r ON r.line_id=l.id LEFT JOIN a ON a.line_id=l.id
      WHERE d.phase='saved' AND l.paired_line_id IS NULL GROUP BY l.order_id),
      d AS (SELECT order_id,sum(phase='draft') AS drafts,sum(phase='reviewed') AS reviewed,count(*) AS documents
      FROM order_documents WHERE phase!='undone' GROUP BY order_id)
      SELECT o.*,coalesce(l.lots,0) AS lots,coalesce(l.pieces,0) AS pieces,
      coalesce(l.received,0) AS received,coalesce(l.allocated,0) AS allocated,coalesce(l.held,0) AS held,
      coalesce(d.drafts,0) AS drafts,coalesce(d.reviewed,0) AS reviewed
      FROM orders o LEFT JOIN l ON l.order_id=o.id LEFT JOIN d ON d.order_id=o.id
      ORDER BY coalesce(o.date_ordered,o.created_at) DESC,o.id DESC""")]
    for row in rows:
        row['phase']=('Draft' if row['drafts'] else 'Reviewed' if row['reviewed'] else
          'Held' if row['held'] else 'Reconciled' if row['status']=='Reconciled' else
          'Allocated' if row['received'] and row['received']==row['allocated'] else
          'Counting' if row['received'] else 'Open')
    return rows


def lines(db, order_id):
    return [dict(r) for r in db.execute('''SELECT l.*,d.phase,coalesce(r.received,0) AS received,
      coalesce(a.allocated,0) AS allocated FROM order_lines l JOIN order_documents d ON d.id=l.document_id
      LEFT JOIN line_receipts r ON r.line_id=l.id LEFT JOIN
      (SELECT line_id,sum(qty) AS allocated FROM allocations WHERE state IN '''+LIVE+'''
      GROUP BY line_id) a ON a.line_id=l.id WHERE l.order_id=? ORDER BY l.document_id,l.line_no''',(order_id,))]


def detail(db, order_id):
    order=get(db,order_id)
    rows=ledger.visuals(db,lines(db,order_id))
    saved=[r for r in rows if r['phase']=='saved' and r['paired_line_id'] is None]
    documents=[dict(r) for r in db.execute('SELECT * FROM order_documents WHERE order_id=? ORDER BY id',(order_id,))]
    history=[dict(r) for r in db.execute('SELECT * FROM allocations WHERE order_id=? ORDER BY id DESC',(order_id,))]
    return dict(order=order,documents=documents,lines=rows,saved=saved,allocations=history,
      ordered=sum(r['qty'] or 0 for r in saved),received=sum(r['received'] for r in saved),allocated=sum(r['allocated'] for r in saved),
      history=ledger.history(db,order_id=order_id))


def parse_xml(text):
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise ValueError('Choose XML without document declarations')
    try:
        root=ET.fromstring(text)
    except ET.ParseError:
        raise ValueError('The XML could not be read') from None
    if root.tag not in ('ORDER','ORDERS','INVENTORY'):
        raise ValueError('Choose a BrickLink order or inventory XML')
    if root.tag=='ORDERS':
        entries=root.findall('ORDER')
        if len(entries)!=1:
            raise ValueError('Choose exactly one order per file')
        root=entries[0]
    rows=[]
    for n,item in enumerate(root.findall('.//ITEM'),1):
        values={e.tag.upper():(e.text or '').strip() for e in item}
        kind=values.get('ITEMTYPE','').upper()
        if kind not in add.TYPES:
            raise ValueError(f'Line {n} · choose a BrickLink item type')
        rows.append(dict(line_no=n,item_type=kind,item_no=values.get('ITEMID',''),
          color_id=values.get('COLOR') if kind=='P' else None,condition=values.get('CONDITION',''),
          qty=values.get('QTY') or values.get('MINQTY'),unit_price=values.get('PRICE'),remark=values.get('REMARKS',''),raw_text=ET.tostring(item,encoding='unicode')))
    return rows, dict(bricklink_order_id=root.findtext('.//ORDERID'),store=root.findtext('STORENAME'),seller=root.findtext('SELLER'),date_ordered=root.findtext('ORDERDATE'),status=root.findtext('STATUS'),currency=root.findtext('CURRENCY'),cost=root.findtext('COST'))


def parse_email(db, text):
    path=add.catalogue_path(db)
    if not path.is_file():
        raise ValueError('Load the BrickLink catalogue in Tools & Admin first')
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as cat:
        catalogue=cat.execute('SELECT item_type,item_no,name FROM items').fetchall()
    names={}
    for kind,number,name in catalogue:
        if not isinstance(name,str):
            continue
        names.setdefault(' '.join(name.lower().split()),[]).append((kind,number,name))
    colors=sorted([dict(r) for r in db.execute('SELECT * FROM colors WHERE name IS NOT NULL')],key=lambda r:-len(r['name']))
    pattern=re.compile(r'^\[(New|Used)\] (.+?)\s+\(x(\d+)\) \.+ EUR ([\d.]+) each = EUR ([\d.]+)$')
    rows=[]
    batch=submitted=None
    for n,line in enumerate(text.splitlines(),1):
        head=re.fullmatch(r'\* Batch #(\d+) \(submitted (.+)\)',line.strip())
        if head:
            batch,submitted=int(head[1]),head[2]
            continue
        match=pattern.fullmatch(line.strip())
        if not match:
            if line.lstrip().startswith(('[New]','[Used]')):
                raise ValueError(f'Line {n} · the quantity or price could not be read')
            continue
        condition,raw,qty,unit,total=match.groups()
        cleaned=' '.join(raw.replace('<x>','').split())
        row=dict(line_no=n,condition='N' if condition=='New' else 'U',qty=qty,unit_price=unit,
          line_total=total,item_type=None,item_no=None,color_id=None,name=None,raw_text=raw,remark='',batch=batch,submitted=submitted)
        instr=re.match(r'^\(Instructions\) for Set ([A-Za-z0-9-]+)\b',cleaned)
        if instr:
            row.update(item_type='I',item_no=instr[1])
        else:
            rest=cleaned
            for color in colors:
                if rest.lower().startswith(color['name'].lower()+' '):
                    row.update(color_id=color['color_id'],colour_name=color['name'])
                    rest=rest[len(color['name']):].strip()
                    break
            # Exact names only. Ambiguous or qualified names remain visible for hand matching.
            fits=names.get(rest.lower(),[])
            if len(fits)==1:
                kind,number,name=fits[0]
                row.update(item_type=kind,item_no=number,name=name)
            sticker=re.search(r'\(Stickers?\) - Set ([A-Za-z0-9-]+)',cleaned)
            if sticker and add.lookup(db,'S',sticker[1]):
                row.update(sticker_set_type='S',sticker_set_no=sticker[1])
        rows.append(row)
    date=None
    submitted=next((r['submitted'] for r in rows if r['submitted']),None)
    for pattern in ('%b %d, %Y %H:%M','%b %d, %Y'):
        try:
            date=datetime.strptime(submitted,pattern).date().isoformat()
            break
        except (ValueError,TypeError):
            pass
    return rows,dict(currency='EUR',date_ordered=date)


def api_data(db, number):
    client=BrickLink(db)
    headers=client.list_orders()
    header=next((r for r in headers if str(r['order_id'])==str(number)),None)
    if header is None:
        raise ValueError('Order is not in your BrickLink purchases')
    groups=client.order_items(number)
    entries=[e for group in groups for e in group] if groups and isinstance(groups[0],list) else groups
    rows=[]
    for n,e in enumerate(entries,1):
        item=e['item']
        rows.append(dict(line_no=n,item_type=TYPE_IDS.get(item['type']),item_no=item['no'],name=item.get('name'),
          color_id=e.get('color_id'),condition=e.get('new_or_used'),qty=e['quantity'],unit_price=e.get('unit_price'),
          remark=e.get('remarks',''),raw_text=json.dumps(e,sort_keys=True)))
    cost=header.get('cost') or {}
    return rows,dict(bricklink_order_id=str(number),store=header.get('store_name'),seller=header.get('seller_name'),
      date_ordered=header.get('date_ordered'),status=header.get('status'),cost=cost.get('grand_total'),currency=cost.get('currency_code'))


def import_document(db, source, text='', *, choice='new', number=None, label=None, prepared=None):
    if source not in ('email','xml','api'):
        raise ValueError('Choose email, XML or BrickLink')
    if source=='api':
        if not re.fullmatch('[0-9]{1,12}',str(number or '')):
            raise ValueError('Use a BrickLink order number')
        raw,header=prepared if prepared is not None else api_data(db,number)
    else:
        if not isinstance(text,str) or not text.strip() or len(text.encode())>1024*1024:
            raise ValueError('Choose a document up to 1 MiB')
        raw,header=parse_email(db,text) if source=='email' else parse_xml(text)
    if not raw:
        raise ValueError('No order lines were found')
    number=str(number or header.get('bricklink_order_id') or '').strip() or None
    if number and not re.fullmatch('[0-9]{1,12}',number):
        raise ValueError('Use a BrickLink order number')
    if number and header.get('bricklink_order_id') and str(header['bricklink_order_id'])!=number:
        raise ValueError('The document belongs to another BrickLink order')
    digest=hashlib.sha256((json.dumps(raw,sort_keys=True) if source=='api' else '\n'.join(l.strip() for l in text.splitlines() if l.strip())).encode()).hexdigest()
    with transaction(db):
        existing=db.execute('SELECT order_id,id FROM order_documents WHERE source=? AND digest=?',(source,digest)).fetchone()
        if existing:
            if choice!='new' and int(choice)!=existing['order_id']:
                raise ValueError('This document already belongs to another order')
            ledger.finish(db, [], 'duplicate', order_id=existing['order_id'], document_id=existing['id'])
            return dict(order_id=existing['order_id'],document_id=existing['id'],duplicate=True,event_id=None)
        changes=[]
        if choice=='new':
            if number and db.execute('SELECT 1 FROM orders WHERE bricklink_order_id=?',(number,)).fetchone():
                raise ValueError('This BrickLink order exists · choose it in Link to order')
            order_id=ledger.insert(db,changes,'orders',dict(bricklink_order_id=number,store=header.get('store'),seller=header.get('seller'),
              date_ordered=header.get('date_ordered'),status=header.get('status'),cost=price(header.get('cost')),currency=header.get('currency'),created_at=w.stamp(),updated_at=w.stamp()))
        else:
            order_id=int(choice)
            order=get(db,order_id)
            if number and order['bricklink_order_id'] not in (None,number):
                raise ValueError('The chosen order has another BrickLink number')
            if header.get('currency') and order['currency'] not in (None,header['currency']):
                raise ValueError('The currencies differ · choose another order')
            supplied=dict(header,bricklink_order_id=number)
            updates={key:(price(value) if key=='cost' else value) for key,value in supplied.items() if key in ('bricklink_order_id','store','seller','date_ordered','status','cost','currency') and value is not None and order[key] is None}
            if updates:
                updates['updated_at']=w.stamp()
                w.record(db,changes,'orders',{'id':order_id},lambda:db.execute('UPDATE orders SET '+','.join(key+'=?' for key in updates)+' WHERE id=?',(*updates.values(),order_id)))
        document_id=ledger.insert(db,changes,'order_documents',dict(order_id=order_id,source=source,digest=digest,label=label or source,phase='draft',created_at=w.stamp(),updated_at=w.stamp()))
        raw_key=dict(source='bricklink',kind='order_document:'+source,source_id=digest)
        raw_payload=json.dumps(dict(header=header,lines=raw) if source=='api' else dict(text=text),sort_keys=True)
        w.record(db,changes,'source_records',raw_key,lambda:db.execute('INSERT INTO source_records(source,kind,source_id,payload,fetched_at,status) VALUES(?,?,?,?,NULL,?)',(*raw_key.values(),raw_payload,'imported')))
        for raw_row in raw:
            row=dict(raw_row)
            row['qty']=add.quantity(row['qty'])
            if row['condition'] not in ('N','U'):
                raise ValueError(f"Line {row['line_no']} · choose New or Used")
            row['unit_price']=price(row.get('unit_price'))
            row['line_total']=price(row.get('line_total')) if row.get('line_total') is not None else (format(Decimal(row['unit_price'])*row['qty'],'f') if row['unit_price'] is not None else None)
            kind,identifier=row.get('item_type'),row.get('item_no')
            found=add.lookup(db,kind,identifier)
            color=int(row['color_id']) if row.get('color_id') not in (None,'') and kind=='P' else None
            known_color=db.execute('SELECT name FROM colors WHERE color_id=?',(color,)).fetchone() if color is not None else None
            resolved=bool(found and (kind!='P' or known_color))
            # Unknown identities remain raw, not invented placeholders in items.
            row.update(item_type=kind if found else None,item_no=identifier if found else None,color_id=color if known_color else None,state='matched' if resolved else 'by_hand',name=found['name'] if found else row.get('name'))
            if found and not db.execute('SELECT 1 FROM items WHERE item_type=? AND item_no=?',(kind,identifier)).fetchone():
                w.record(db,changes,'items',{'item_type':kind,'item_no':identifier},lambda f=found:db.execute('INSERT INTO items(item_type,item_no,name) VALUES(?,?,?)',tuple(f.values())))
            if row.get('sticker_set_no'):
                reference=add.lookup(db,'S',row['sticker_set_no'])
                w.record(db,changes,'items',{'item_type':'S','item_no':row['sticker_set_no']},lambda f=reference:db.execute('INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES(?,?,?)',tuple(f.values())))
            row.update(order_id=order_id,document_id=document_id,source=source,updated_at=w.stamp())
            ledger.insert(db,changes,'order_lines',row)
        event=ledger.finish(db,changes,'import',order_id=order_id,document_id=document_id)
        return dict(order_id=order_id,document_id=document_id,duplicate=False,event_id=event)


def match(db, order_id, line_id, kind, number, color):
    found=add.lookup(db,kind,number)
    if not found:
        raise ValueError('Choose an identity from the BrickLink catalogue')
    color=int(color) if kind=='P' and color not in (None,'') else None
    with transaction(db):
        row=db.execute('SELECT l.*,d.phase FROM order_lines l JOIN order_documents d ON d.id=l.document_id WHERE l.id=? AND l.order_id=?',(line_id,order_id)).fetchone()
        if not row or row['phase']!='draft':
            raise ValueError('Reopen this document before matching lines')
        color_row=db.execute('SELECT name FROM colors WHERE color_id=?',(color,)).fetchone() if color is not None else None
        if kind=='P' and not color_row:
            raise ValueError('Choose a BrickLink colour')
        changes=[]
        w.record(db,changes,'items',{'item_type':kind,'item_no':number},lambda:db.execute('INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES(?,?,?)',(kind,number,found['name'])))
        w.record(db,changes,'order_lines',{'id':line_id},lambda:db.execute("UPDATE order_lines SET item_type=?,item_no=?,color_id=?,colour_name=?,name=?,state='confirmed',confirmed_via='search',updated_at=? WHERE id=?",(kind,number,color,color_row[0] if color_row else None,found['name'],w.stamp(),line_id)))
        return ledger.finish(db,changes,'match',order_id=order_id)


def line_key(row):
    return row['item_type'],row['item_no'],row['color_id'],row['condition']


def phase(db, order_id, document_id, action, pairs=None):
    transitions={'review':('draft','reviewed'),'reopen':('reviewed','draft'),'save':('reviewed','saved')}
    if action not in transitions:
        raise ValueError('Choose a document action')
    before,after=transitions[action]
    with transaction(db):
        doc=db.execute('SELECT * FROM order_documents WHERE id=? AND order_id=?',(document_id,order_id)).fetchone()
        if not doc or doc['phase']!=before:
            raise ValueError('The document phase changed · review it again')
        changes=[]
        rows=lines(db,order_id)
        current={r['id']:r for r in rows if r['document_id']==document_id}
        unresolved={(r[0],r[1]) for r in db.execute("SELECT item_type,item_no FROM id_match WHERE status='to_check'")}
        if action=='review' and any(r['state'] not in ('matched','confirmed') or not r['item_no'] or r['item_type']=='?' or (r['item_type'],r['item_no']) in unresolved for r in current.values()):
            raise ValueError('Match each unresolved line before finishing the review')
        if action=='save':
            existing={r['id']:r for r in rows if r['phase']=='saved' and r['paired_line_id'] is None}
            pairs={int(k):int(v) for k,v in (pairs or {}).items() if v not in ('',None)}
            if len(set(pairs.values()))!=len(pairs):
                raise ValueError('Pair an existing line only once')
            for new,old in pairs.items():
                if new not in current or old not in existing or line_key(current[new])!=line_key(existing[old]):
                    raise ValueError('Pairs must share item, colour and condition')
                w.record(db,changes,'order_lines',{'id':new},lambda n=new,o=old:db.execute('UPDATE order_lines SET paired_line_id=?,updated_at=? WHERE id=?',(o,w.stamp(),n)))
        w.record(db,changes,'order_documents',{'id':document_id},lambda:db.execute('UPDATE order_documents SET phase=?,updated_at=? WHERE id=?',(after,w.stamp(),document_id)))
        return ledger.finish(db,changes,action,order_id=order_id)


def received(db, order_id, counts):
    with transaction(db):
        current={r['id']:r for r in lines(db,order_id) if r['phase']=='saved' and r['paired_line_id'] is None}
        changes=[]
        for key,value in counts.items():
            key=int(key)
            if not re.fullmatch('[0-9]{1,5}',str(value)):
                raise ValueError('Received count must be a whole number')
            value=int(value)
            row=current.get(key)
            if not row or not row['allocated']<=value<=row['qty']:
                raise ValueError('Received count must be between allocated and ordered')
            if value==row['received']:
                continue
            w.record(db,changes,'line_receipts',{'line_id':key},lambda k=key,v=value:db.execute('INSERT INTO line_receipts VALUES(?,?,?) ON CONFLICT(line_id) DO UPDATE SET received=excluded.received,updated_at=excluded.updated_at',(k,v,w.stamp())))
            ledger.insert(db,changes,'line_receipt_log',dict(line_id=key,at=w.stamp(),old=row['received'],new=value))
        return ledger.finish(db,changes,'received',order_id=order_id)


def destinations(db, saved):
    # Shared gap semantics, but scope to identities that this order can supply.
    index={}
    for gap in w.gaps(db):
        if not gap['unresolved']:
            index.setdefault(w.identity(gap),[]).append(gap)
    return {r['id']:index.get(w.identity(r),[]) if r['state'] in ('matched','confirmed') and not r.get('unresolved') else [] for r in saved}


def allocate(db, order_id, chosen):
    if not chosen or len(chosen)>1000:
        raise ValueError('Choose up to 1000 allocations')
    with transaction(db):
        saved={r['id']:r for r in lines(db,order_id) if r['phase']=='saved' and r['paired_line_id'] is None}
        changes=[]
        confirm=uuid4().hex
        affected=set()
        for choice in chosen:
            line=saved.get(int(choice['line_id']))
            amount=add.quantity(choice['quantity'])
            if not line or line['state'] not in ('matched','confirmed') or not line['item_no'] or w.unresolved(db,line['item_type'],line['item_no']):
                raise ValueError('Match the line before allocating')
            if amount>line['received']-line['allocated']:
                raise ValueError('Received quantity changed · review the allocation')
            target=choice['target_type']
            values=dict(confirm_id=confirm,order_id=order_id,line_id=line['id'],qty=amount,state='applied',
              created_at=w.stamp(),applied_at=w.stamp(),target_type=target,part_type=line['item_type'],part=line['item_no'],color=line['color_id'])
            if target=='copy':
                gap=w.requested_gap(db,line,choice['copy_id'],choice['target'],choice['target_id'])
                if not gap or amount>gap['need']:
                    raise ValueError('The copy gap changed · review the allocation')
                w.reduce_gap(db,changes,gap,amount,update_completeness=False)
                affected.add(gap['copy_id'])
                values.update(kind={'part':'missing_part','figure':'missing_figure','instructions':'instructions','box':'box'}[gap['target']],
                  copy_id=gap['copy_id'],target_copy_id=gap['copy_id'],intent_before=gap['need'],intent_after=gap['need']-amount,
                  ref=str(gap['target_id']),figure_type=gap.get('parent_minifig_type'),figure=gap.get('parent_minifig'),spare=gap.get('spare'))
            elif target=='stock':
                storage=choice.get('storage_id') or None
                lot=choice.get('lot_id') or None
                if storage:
                    from .ledger import require_storage
                    require_storage(db, storage)
                if lot and not db.execute('SELECT 1 FROM lots WHERE id=? AND archived_at IS NULL',(lot,)).fetchone():
                    raise ValueError('Lot is unavailable')
                from .stock import add_loose
                identifier, _ = add_loose(db, changes, item_type=line['item_type'],
                  item_no=line['item_no'], color_id=line['color_id'], quantity=amount,
                  condition=line['condition'], storage_id=storage, lot_id=lot)
                values.update(kind='loose_figure' if line['item_type']=='M' else 'loose_part',target_stock_id=identifier,ref=identifier)
            else:
                raise ValueError('Choose a copy gap or loose stock')
            ledger.insert(db,changes,'allocations',values)
            line['allocated']+=amount
        guards=[]
        for copy_id in affected:
            w.recompute(db,changes,copy_id)
            for table,key in [('copies',{'id':copy_id}),('item_flags',{'entity_type':'copy','entity_id':copy_id})]:
                guards.append(dict(table=table,key=key,value=w.snapshot(db,table,key)))
        return ledger.finish(db,changes,'allocate',order_id=order_id,guards=guards)


def reconcile(db, order_id):
    with transaction(db):
        data=detail(db,order_id)
        if not data['saved'] or any(r['state']=='held' or r['received']!=r['allocated'] for r in data['saved']) or any(d['phase'] in ('draft','reviewed') for d in data['documents']):
            raise ValueError('Finish reviews and allocate every received piece before reconciling')
        changes=[]
        w.record(db,changes,'orders',{'id':order_id},lambda:db.execute("UPDATE orders SET status='Reconciled',updated_at=? WHERE id=?",(w.stamp(),order_id)))
        return ledger.finish(db,changes,'reconcile',order_id=order_id)


def short_xml(db, order_id):
    get(db,order_id)
    root=ET.Element('INVENTORY')
    for r in lines(db,order_id):
        if r['phase']!='saved' or r['paired_line_id'] is not None or r['received']>=r['qty']:
            continue
        item=ET.SubElement(root,'ITEM')
        for key,value in [('ITEMTYPE',r['item_type']),('ITEMID',r['item_no']),('COLOR',r['color_id']),('MINQTY',r['qty']-r['received']),('CONDITION',r['condition'])]:
            if value is not None:
                ET.SubElement(item,key).text=str(value)
    return ET.tostring(root,encoding='unicode')


def hold(db, order_id, line_id, held):
    if type(held) is not bool:
        raise ValueError('Choose hold or release')
    with transaction(db):
        row=next((r for r in lines(db,order_id) if r['id']==line_id and r['phase']=='saved' and r['paired_line_id'] is None),None)
        if not row or row['state'] not in ('matched','confirmed','held'):
            raise ValueError('Choose a matched saved line')
        changes=[]
        w.record(db,changes,'order_lines',{'id':line_id},lambda:db.execute('UPDATE order_lines SET state=?,updated_at=? WHERE id=?',('held' if held else 'confirmed',w.stamp(),line_id)))
        return ledger.finish(db,changes,'hold' if held else 'release',order_id=order_id)


def allocation_review(db, order_id):
    get(db, order_id)
    saved = [r for r in lines(db, order_id) if r['phase']=='saved' and r['paired_line_id'] is None]
    destinations_by_line = destinations(db, saved)
    return [dict(id=r['id'], line=r, available=r['received']-r['allocated'], destinations=destinations_by_line[r['id']]) for r in saved]


def allocation_history(db, order_id):
    get(db, order_id)
    return [dict(r) for r in db.execute('SELECT * FROM allocations WHERE order_id=? ORDER BY id DESC', (order_id,))]


def retry_allocations(db, order_id, chosen):
    # v3 allocations are atomic: a failed confirm has no pending effects to resume.
    # A client retries its reviewed choices against the current counts and gaps.
    return allocate(db, order_id, chosen)
