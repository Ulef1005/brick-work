"""Planning projections on Brick Work, with bounded bulk reads and audited saves."""
from .transaction import transaction
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import json
from xml.etree import ElementTree as ET

from . import add, collection, workbench, collection_prices
from .admin import audit
from .sources.base import now

REPAIR_KEYS = ('repair_shipping', 'repair_fees', 'repair_min_order',
               'repair_use_loose_stock', 'incomplete_discount_pct')

def D(value):
    return Decimal(str(value))

def ratio_cap(ratios):
    """Linear-interpolated 90th percentile, rounded up to a whole multiple."""
    ratios = sorted(ratios)
    if not ratios:
        return Decimal(5)
    position = Decimal(len(ratios) - 1) * Decimal('0.9')
    lower = int(position)
    percentile = ratios[lower]
    if lower + 1 < len(ratios):
        percentile += (ratios[lower + 1] - percentile) * (position - lower)
    return max(Decimal(5), percentile.to_integral_value(rounding=ROUND_CEILING))

def usable(quote, config, now):
    if not quote or quote.get('price') is None:
        return 'no cached price'
    if quote.get('currency') != config['bricklink_currency']:
        return 'Currency mismatch'
    if quote.get('region') != config['bricklink_region']:
        return 'unsuitable region'
    if quote.get('source') not in ('bricklink', 'bricklink_stock') or quote.get('qty', 1) == 0:
        return 'unsuitable quote'
    try:
        observed = datetime.fromisoformat(quote['observed_at'])
        if observed.utcoffset() is None or observed < now - timedelta(days=7) or observed > now:
            return 'stale quote'
    except (KeyError, TypeError, ValueError):
        return 'stale quote'
    return None

def ranking_sort_key(copy, group='ranked', *, include_pins=True):
    """One ordering rule for planning, its public list and value cursors."""
    pin = not copy.get('pinned', False) if include_pins else False
    evidence = (-D(copy['ratio']), -D(copy['net_gain']), copy['unresolved_items']) if group == 'ranked' else (Decimal(0), Decimal(0), 0)
    return (pin, *evidence, copy['set_num'], copy['id'])


def ranking_cursor_key(copy):
    group = copy['group']
    key = ranking_sort_key(copy, group)
    return [('ranked', 'free_repairs', 'outside', 'needs_evidence').index(group),
            int(key[0]), str(key[1]), str(key[2]), key[3], key[4], key[5]]


def compute(copies, config, now):
    """Pure projection. Inputs are copy records, complete quote and missing lines.

    Lines already carry the shared Workbench gap and stock projection.
    Decimal values retain precision; no currency conversion.
    """
    groups = dict(ranked=[], needs_evidence=[], outside=[], free_repairs=[])
    for original in copies:
        c = dict(original, rank=None, reasons=[], listing=False)
        lines = [dict(r) for r in c['items']]
        if not lines:
            continue
        c['missing_count'] = sum(r['missing'] for r in lines)
        c['missing_parts'] = sum(r['missing'] for r in lines if r['type'] == 'P')
        c['missing_figures'] = sum(r['missing'] for r in lines if r['type'] == 'M')
        value = c.get('complete_quote')
        reason = usable(value, config, now)
        if reason:
            c['reasons'].append('no complete value' if reason == 'no cached price' else reason + ' · complete value')
        override = c.get('current_value')
        if override is not None and c.get('current_value_currency') != config['bricklink_currency']:
            c['reasons'].append('Currency mismatch · current-value override')
        total = Decimal(0)
        for r in lines:
            if not r['missing']:
                continue
            error = ('unmapped figure' if r['type'] == 'M' and not r.get('mapped') else
                     usable(r.get('quote'), config, now))
            if error:
                c['reasons'].append(error + ' · ' + r['number'])
            else:
                total += D(r['quote']['price']) * r['missing']
                c['listing'] |= r['quote']['source'] == 'bricklink_stock'
        c['unresolved_items'] = len(c['reasons'])
        if c['reasons']:
            groups['needs_evidence'].append(c)
            continue
        c['listing'] |= value['source'] == 'bricklink_stock'
        c['value_when_complete'] = D(value['price'])
        c['current_value'] = D(override) if override is not None else D(value['price']) * (100 - config['incomplete_discount_pct']) / 100
        c['valuation_basis'] = 'copy override' if override is not None else 'default discount estimate'
        c['breakdown'] = dict(items=total, shipping=D(config['repair_shipping']), fees=D(config['repair_fees']),
                              minimum_order_extra=max(Decimal(0), D(config['repair_min_order']) - total))
        c['repair_cost'] = sum(c['breakdown'].values())
        c['gross_gain'] = c['value_when_complete'] - c['current_value']
        c['net_gain'] = c['gross_gain'] - c['repair_cost']
        c['ratio'] = c['gross_gain'] / c['repair_cost'] if c['repair_cost'] else None
        groups['outside' if c['net_gain'] <= 0 else 'free_repairs' if not c['repair_cost'] else 'ranked'].append(c)
    groups['ranked'].sort(key=lambda c: ranking_sort_key(c, include_pins=False))
    for rank, c in enumerate(groups['ranked'], 1):
        c['rank'] = rank
    groups['ranked'].sort(key=ranking_sort_key)
    for group in ('needs_evidence', 'outside', 'free_repairs'):
        groups[group].sort(key=lambda c, group=group: ranking_sort_key(c, group))
    scale = ratio_cap([c['ratio'] for c in groups['ranked']])
    for c in groups['ranked']:
        c['ratio_width'] = float(min(c['ratio'] / scale, Decimal(1)) * 100)
        c['ratio_overflow'] = c['ratio'] > scale
    return dict(groups, settings=config, ratio_scale=scale)


def configuration(db):
    from .price_settings import DEFAULTS
    config = {**DEFAULTS, **dict(db.execute('SELECT key,value FROM settings'))}
    for key in ('incomplete_discount_pct', 'repair_use_loose_stock'):
        config[key] = (int(Decimal(config[key])) if key=='repair_use_loose_stock' else Decimal(config[key])) if key in config else None
    return config


def priced_items(db, kind=None):
    """Lean Prices projection: one row per priced identity, no observation lists.

    Four bounded reads, none of them per row. The row's stale flag is true when any current
    quote is past its source's freshness; the display price is chosen from each (condition,
    source, guide)'s freshest successful observation with Collection's own selection rules.
    The full observation list of one identity is `price_details`, loaded on demand.
    """
    args = (kind,) if kind else ()
    identities = db.execute("""SELECT p.item_type,p.item_no,p.color_id,
        max(coalesce(f.max_age_days IS NOT NULL AND coalesce(o.observed_at,'')!='' AND
            julianday(?)-julianday(o.observed_at) >= f.max_age_days+1,0)) AS stale
        FROM price_current p JOIN price_observations o ON o.id=p.observation_id
        LEFT JOIN source_freshness f ON f.source=o.source AND f.kind='prices'
        """ + ('WHERE p.item_type=? ' if kind else '') + 'GROUP BY p.item_type,p.item_no,p.color_id',
        (now().isoformat(), *args)).fetchall()
    # One filtered scan of successful market observations picks each identity's best U and N quote and
    # best overall with Collection's own order (source priority, sold before listings, freshest, newest id);
    # only the winners become dicts, so history depth costs one pass and nothing per row after it.
    priorities = collection_prices.priority(db)
    ranks, best = {}, {}
    floor = datetime.min.replace(tzinfo=timezone.utc).timestamp()
    cursor = db.cursor()
    cursor.row_factory = None  # plain tuples: this loop runs once per observation
    cursor.execute("""SELECT id,item_type,item_no,color_id,condition,guide,source,observed_at FROM price_observations o
        WHERE guide IN ('sold','stock') AND coalesce(slot,'')!='boxed' AND coalesce(error,'')='' AND price IS NOT NULL""" +
        (' AND item_type=?' if kind else ''), args)
    dated = collection_prices.dated
    # A quote with no recorded condition (migrated data) is a fallback only, and only from the current quotes,
    # as Collection's choice works on price_current; superseded or errored history never stands in for it.
    current = {r[0] for r in db.execute('SELECT observation_id FROM price_current' + (' WHERE item_type=?' if kind else ''), args)}
    for r in cursor:
        if r[4] not in ('U', 'N') and r[0] not in current:
            continue
        order, missing = ranks.get(r[1]) or ranks.setdefault(r[1], (lambda o: ({x: o.index(x) for x in o}, len(o)))(
            [x.split(':')[0] for x in priorities.get(r[1], priorities.get('*', ['bricklink']))]))
        moment = dated(r[7])
        base = (order.get(r[6], missing), -(moment.timestamp() if moment else floor), -r[0])
        slots = best.get((r[1], r[2], r[3]))
        if slots is None:
            slots = best[r[1], r[2], r[3]] = [None, None, None]
        # Index 2 holds a quote with no recorded condition; it is read only when there is no U or N quote.
        index = 0 if r[4] == 'U' else 1 if r[4] == 'N' else 2
        candidate = (base[0], r[5] != 'sold') + base[1:] if index < 2 else base
        if slots[index] is None or candidate < slots[index][0]:
            slots[index] = (candidate, base, r[0])
    names = {(r['item_type'], r['item_no']): dict(r) for r in db.execute('SELECT * FROM items' + (' WHERE item_type=?' if kind else ''), args)}
    owned = {(r[0], r[1]) for r in db.execute("""SELECT item_type,set_no FROM copies WHERE archived_at IS NULL
        UNION SELECT item_type,item_no FROM loose_stock WHERE archived_at IS NULL""")}
    wanted = {(r[0], r[1]) for r in db.execute('SELECT item_type,item_no FROM wishlist WHERE archived_at IS NULL')}
    rows = []
    for r in identities:
        key = (r['item_type'], r['item_no'], r['color_id'])
        slots = best.get(key, [None, None, None])
        conditions = [s for s in slots[:2] if s]
        pick = min(conditions, key=lambda s: s[1]) if conditions else slots[2]
        rows.append(dict(names[key[:2]], color_id=key[2], stale=bool(r['stale']), owned=key[:2] in owned,
                         wanted=key[:2] in wanted, display_price=pick[2] if pick else None))
    # Winners only become full observation rows, in one read.
    full = {r['id']: dict(r) for r in db.execute("""SELECT o.*,f.max_age_days FROM price_observations o
        LEFT JOIN source_freshness f ON f.source=o.source AND f.kind='prices'
        WHERE o.id IN (SELECT value FROM json_each(?))""", (json.dumps([r['display_price'] for r in rows if r['display_price']]),))}
    for row in rows:
        row['display_price'] = full[row['display_price']] if row['display_price'] else None
    rows = add.decorate_many(db, rows)
    for row in rows:
        if row['display_price']:
            row['display_price'] = collection.decorate_prices([row['display_price']])[0]
    return rows


PRICE_FIELDS = 'type number name colour color_id rgb ink image unresolved owned wanted stale price listings age observed price_stale'.split()


def price_records(rows):
    """Compact positional Prices rows (see `PRICE_FIELDS`): identity, kind, owned/wanted, the display
    price as text with its age and stale flag. Refresh is available to every row that is not unresolved."""
    from ..web.formatting import money, short_age
    records = []
    for r in rows:
        p = r['display_price']
        records.append([r['item_type'], r['item_no'], r.get('name') or r['item_no'], r.get('color_name') or '', r['color_id'],
                        r.get('rgb'), r.get('ink'), r.get('image'), bool(r.get('unresolved')), bool(r['owned']), bool(r['wanted']),
                        bool(r['stale']), money(p['price'], p.get('currency') or '', fixed=True) if p else None,
                        bool(p and p['guide'] == 'stock'), short_age(p['age']) if p else '',
                        (p['observed_at'] or '')[:10] if p else '', bool(p and p['stale'])])
    return dict(fields=PRICE_FIELDS, rows=records)


def price_details(db, kind, number, colour=None):
    """One identity's observation list for the Prices Details disclosure, display text only."""
    from ..web.formatting import money, short_age
    item = db.execute('SELECT * FROM items WHERE item_type=? AND item_no=?', (kind, number)).fetchone()
    if item is None:
        return None
    records = collection.decorate_prices(db.execute("""SELECT o.*,f.max_age_days FROM price_observations o
        LEFT JOIN source_freshness f ON f.source=o.source AND f.kind='prices'
        WHERE o.item_type=? AND o.item_no=? AND o.color_id IS ? ORDER BY o.observed_at DESC,o.id DESC""", (kind, number, colour)))
    priorities = collection_prices.priority(db)
    by_condition = collection_prices.condition_rows(records, kind, priorities)
    current = {r[0] for r in db.execute('SELECT observation_id FROM price_current WHERE item_type=? AND item_no=? AND color_id IS ?',
                                        (kind, number, colour))}
    chosen = collection_prices.choose(by_condition, kind, priorities) or collection_prices.choose(
        [p for p in records if p['id'] in current and p['guide'] in ('sold', 'stock') and p.get('slot') != 'boxed'], kind, priorities)
    amount = lambda value, currency: money(value, currency or '', fixed=True)
    def age(p):
        return short_age(p['age']) + (' · stale' if p['stale'] else '')
    def quote(p):
        guide = 'avg' if p['guide'] == 'sold' else 'listings' if p['guide'] == 'stock' else p['guide']
        meta = [age(p), p['source']]
        if p['region']: meta.append(p['region'])
        if p['guide'] == 'sold': meta += [f"{p['sold'] if p['sold'] is not None else 'Count not recorded'} sold", 'Window not recorded']
        if p['error']: meta.append(p['error'])
        out = dict(label=p['label'], head=amount(p['price'], p['currency']) + ' · ' + guide + ('' if p['currency'] else ' · Currency not recorded'),
                   meta=' · '.join(meta))
        if p['range'] is not None:
            out.update(range=p['range'], min=amount(p['min'], p['currency']), max=amount(p['max'], p['currency']),
                       aria=f"Minimum {amount(p['min'], p['currency'])}, average {amount(p['price'], p['currency'])}, maximum {amount(p['max'], p['currency'])}")
        return out
    market = lambda p: p['source'] in ('bricklink', 'bricklink_stock') and p['guide'] in ('sold', 'stock')
    retail = lambda p: p['source'] == 'brickset' and p['guide'] == 'retail'
    groups = [dict(label=label, quotes=[quote(p) for p in records if test(p)]) for label, test in (
        ('Market · BrickLink', market), ('Retail · Brickset', retail),
        ('Other valuations', lambda p: not market(p) and not retail(p)))]
    return dict(context=' · '.join(str(x) for x in (item['category'], item['year']) if x),
                selected=(f"{chosen['label']}{' · avg' if chosen['guide'] == 'sold' else ''} · {amount(chosen['price'], chosen['currency'])}" if chosen else None),
                conditions=[f"{p['label']} · {amount(p['price'], p['currency'])} · {age(p)}" for p in by_condition],
                groups=[g for g in groups if g['quotes']], empty=not records)


def display_prices(db, rows, kind=None, number=None, *, scoped=False):
    """One bulk observation read; use Collection's condition/source selection.

    `kind` (and `number`) narrow the read to one type or item; `scoped` reads only the
    observations of the given rows' identities.
    """
    priorities = collection_prices.priority(db)
    grouped = defaultdict(list)
    observations = db.execute("""SELECT o.*,f.max_age_days FROM price_observations o
        LEFT JOIN source_freshness f ON f.source=o.source AND f.kind='prices'""" +
        (' WHERE o.item_type=?' + (' AND o.item_no=?' if number else '') if kind else
         ' WHERE ' + collection.identity_filter('o') if scoped else '')
        + ' ORDER BY o.observed_at DESC,o.id DESC',
        ((kind, number) if number else (kind,)) if kind else
        (json.dumps(sorted({(r['item_type'], r['item_no'], r['color_id']) for r in rows}, key=str)),) if scoped else ())
    for p in collection.decorate_prices(observations):
        grouped[p['item_type'],p['item_no'],p['color_id']].append(p)
    for row in rows:
        records = grouped[row['item_type'],row['item_no'],row['color_id']]
        row['price_records'] = records
        row['condition_prices'] = collection_prices.condition_rows(records, row['item_type'], priorities)
        condition = {'new':'N','used':'U'}.get(row.get('condition'))
        row['display_price'] = collection_prices.choose(row['condition_prices'], row['item_type'], priorities, condition)
        if not row['display_price']:
            row['display_price'] = collection_prices.choose(
                [p for p in row['prices'] if p['guide'] in ('sold', 'stock') and p.get('slot') != 'boxed'],
                row['item_type'], priorities, condition)
    return rows


def max_comparison(row, rates=None):
    """Compare the price shown on a wish with its max; only when both are in the same currency.

    State is 'under' (price at or below the max), 'over', 'differs' (both currencies known and
    different, never compared) or None (no max, no price or a max without a recorded currency).
    margin = max minus price, only for a real comparison. No conversion.
    """
    maximum, price = row.get('max_price'), row.get('display_price')
    limit_currency = (row.get('max_price_currency') or '').upper()
    if maximum is None or not price or price.get('price') is None or not limit_currency:
        return None, None
    price_currency = (price.get('currency') or '').upper()
    if not price_currency:
        return None, None
    if price_currency != limit_currency:
        # #39: with rates for both currencies, compare the price converted into the max's currency
        # and keep the conversion for the "≈" mark; without them it stays 'differs'.
        from .currency import convert
        conversion = convert(price['price'], price_currency, limit_currency, rates) if rates else None
        if conversion is None:
            return 'differs', None
        row['max_conversion'] = dict(conversion, amount=str(conversion['amount']), rate=str(conversion['rate']), currency=limit_currency)
        margin = D(maximum) - conversion['amount']
        return ('under' if margin >= 0 else 'over'), margin
    margin = D(maximum) - D(price['price'])
    return ('under' if margin >= 0 else 'over'), margin


def wishes(db):
    from . import wish_progress
    from . import currency
    rows = display_prices(db, collection.listing(db, 'S', wishes=True), scoped=True)
    table = currency.rates(db)
    for row in rows:
        row['max_state'], row['max_margin'] = max_comparison(row, table)
    wish_progress.annotate(db, rows)
    from . import retail
    info = retail.lookup(db, [r['item_no'] for r in rows if r['item_type'] == 'S'])
    for r in rows:
        r['retail'] = info.get(r['item_no']) if r['item_type'] == 'S' else None
    # #35: filled lines drop to the bottom; the order within each part stays as listed.
    return sorted(rows, key=lambda r: r['filled'])


def quote(quotes, condition, config, stamp):
    candidates = []
    for original in quotes:
        if original['condition'] != condition or original['guide'] not in ('sold','stock') or original['error'] or original['stale']:
            continue
        q = dict(original, source='bricklink_stock' if original['source']=='bricklink' and original['guide']=='stock' else original['source'])
        if usable(q, config, stamp) is None:
            candidates.append(q)
    return max(candidates, key=lambda q:(q['guide']=='sold',q['observed_at']), default=None)


def ranking(db):
    config = configuration(db)
    required = ('bricklink_currency','bricklink_region', *REPAIR_KEYS)
    if any(config.get(k) is None for k in required):
        raise ValueError('Repair settings are missing · open Tools & Admin')
    stamp = now()
    market = collection.prices(db)
    rows = [dict(r, item_no=r['set_no'],color_id=None,items=[],set_num=r['set_no']) for r in db.execute('''SELECT c.*,i.name,i.category,i.year FROM copies c
        JOIN items i ON (i.item_type,i.item_no)=(c.item_type,c.set_no) WHERE c.archived_at IS NULL ORDER BY c.set_no,c.id''')]
    copies = {r['id']:r for r in rows}
    labels = defaultdict(int)
    for c in rows:
        labels[c['set_no']] += 1
        c['label'] = 'Set '+str(labels[c['set_no']])
        c['complete_quote'] = quote(market[c['item_type'],c['set_no'],None], c['condition'] or 'U',config,stamp)
    pool = defaultdict(int)
    if config['repair_use_loose_stock']:
        pending = {(r[0],r[1]) for r in db.execute("SELECT item_type,item_no FROM id_match WHERE status='to_check'")}
        defective = {r[0] for r in db.execute('SELECT DISTINCT stock_id FROM loose_minifig_parts WHERE coalesce(missing,0)>0 OR coalesce(damaged,0)>0')}
        for r in db.execute("SELECT * FROM loose_stock WHERE archived_at IS NULL AND item_type='P'"):
            pool[workbench.identity(r)] += workbench.available(db,r,unresolved_keys=pending,defective_figures=defective)
        for r in db.execute("SELECT part_type,part,color,sum(qty) FROM allocations WHERE state='pending' AND kind='missing_part' GROUP BY part_type,part,color"):
            key = tuple(r[:3]);pool[key] = max(0,pool[key]-(r[3] or 0))
    gaps = workbench.gaps(db)
    for gap in sorted(gaps,key=lambda g:(g['copy']['set_no'],g['copy_id'],g['item_no'],g['color_id'] or 0)):
        if gap['target'] not in ('part','figure') or gap['copy_id'] not in copies:
            continue
        c = copies[gap['copy_id']]
        need = gap['need']; key = workbench.identity(gap)
        take = min(need,pool[key]) if not gap['unresolved'] and gap['item_type']=='P' else 0
        pool[key] -= take
        # Keep zero-buy lines: free repairs still have evidence and an original gap.
        c['items'].append(dict(gap,type=gap['item_type'],number=gap['item_no'],
            missing=need-take,original_gap=need,stock_used=take,figure=None,
            mapped=not gap['unresolved'],quote=None if gap['unresolved'] else quote(market[key],c['condition'] or 'U',config,stamp)))
    data = compute(rows,config,stamp)
    for group in ('ranked','needs_evidence','outside','free_repairs'):
        for c in data[group]:
            c['missing_count'] = sum(r['missing'] for r in c['items'])
            c['original_gap'] = sum(r['original_gap'] for r in c['items'])
            c['stock_used'] = sum(r['stock_used'] for r in c['items'])
            c['group'] = group
    decorated = add.decorate_many(db, [c for group in ('ranked','free_repairs','outside','needs_evidence') for c in data[group]])
    top_ratio = max((r['ratio'] for r in data['ranked']), default=None)
    for row in decorated:
        row['display_ratio_width'] = float(row['ratio'] / top_ratio * 100) if row['group']=='ranked' and top_ratio else None
    # #38: part-out value per copy, one batch for the whole list.
    from . import partout
    values = partout.values(db, [row['id'] for row in decorated])
    for row in decorated:
        row['partout'] = partout.compare(row, values.get(row['id']))
    data['rows'] = decorated
    return data


def save(db, action, data):
    with transaction(db):
        if action=='pin':
            if type(data.get('pinned')) is not bool: raise ValueError('Choose pinned or unpinned')
            old = collection.snapshot(db,'copies',[data.get('id')])
            if not old or old[0]['archived_at']: raise ValueError('Copy is unavailable')
            db.execute('UPDATE copies SET pinned=? WHERE id=?',(int(data['pinned']),data['id']))
            before, after = old,collection.snapshot(db,'copies',[data['id']])
        elif action=='settings':
            values = data.get('values')
            if not isinstance(values,dict) or set(values)!=set(REPAIR_KEYS): raise ValueError('Choose all repair settings')
            for k,v in values.items():
                try: n=Decimal(str(v))
                except InvalidOperation as exc: raise ValueError('Use a non-negative number') from exc
                if not n.is_finite() or n<0 or (k=='incomplete_discount_pct' and n>100) or (k=='repair_use_loose_stock' and n not in (0,1)):
                    raise ValueError('Repair setting is out of range')
            before = [dict(r) for r in db.execute('SELECT * FROM settings WHERE key IN (SELECT value FROM json_each(?)) ORDER BY key',(json.dumps(REPAIR_KEYS),))]
            if len(before)!=len(REPAIR_KEYS): raise ValueError('Repair settings are missing')
            db.execute('UPDATE settings SET value=j.value FROM json_each(?) AS j WHERE settings.key=j.key',
                       (json.dumps({k:str(v) for k,v in values.items()}),))
            after = [dict(r) for r in db.execute('SELECT * FROM settings WHERE key IN (SELECT value FROM json_each(?)) ORDER BY key',(json.dumps(REPAIR_KEYS),))]
        else: raise ValueError('Unknown planning action')
        audit(db,'bw_planning',action,before,after)
        return db.execute('SELECT last_insert_rowid()').fetchone()[0]


def undo(db, identifier, *, receipt=None):
    with transaction(db):
        event=receipt if receipt is not None else db.execute("SELECT * FROM events WHERE id=? AND entity='bw_planning' AND field IN ('pin','settings')",(identifier,)).fetchone()
        if not event: raise ValueError('Save is unavailable')
        if db.execute("SELECT 1 FROM events WHERE entity='bw_planning' AND field='undo' AND new_value=?",(json.dumps(identifier),)).fetchone(): return
        before,after=json.loads(event['old_value']),json.loads(event['new_value'])
        if event['field']=='pin':
            current=collection.snapshot(db,'copies',[after[0]['id']])
        else:
            current=[dict(r) for r in db.execute('SELECT * FROM settings WHERE key IN (SELECT value FROM json_each(?)) ORDER BY key',(json.dumps([r['key'] for r in after]),))]
        if current!=after: raise ValueError('Item changed · undo the later save first')
        if event['field']=='pin': db.execute('UPDATE copies SET pinned=? WHERE id=?',(before[0]['pinned'],before[0]['id']))
        else: db.execute('UPDATE settings SET value=j.value FROM json_each(?) AS j WHERE settings.key=j.key',
                         (json.dumps({r['key']:r['value'] for r in before}),))
        audit(db,'bw_planning','undo',after,identifier)


def export(db, ids):
    if not isinstance(ids,list) or not ids or len(ids)>2000 or len(set(ids))!=len(ids): raise ValueError('Choose copies to export')
    data=ranking(db)
    chosen=[r for r in data['rows'] if r['id'] in ids]
    if len(chosen)!=len(ids): raise ValueError('Copy is unavailable')
    lines=defaultdict(int)
    for c in chosen:
        for r in c['items']:
            if not r['missing']: continue
            if r['unresolved'] or r['item_type']=='?' or (r['item_type']=='P' and r['color_id'] is None):
                raise ValueError('Resolve figures and colours before exporting')
            lines[r['item_type'],r['item_no'],r['color_id'],c['condition'] or 'U']+=r['missing']
    root=ET.Element('INVENTORY')
    for (kind,number,colour,condition),qty in sorted(lines.items(),key=lambda pair:str(pair[0])):
        item=ET.SubElement(root,'ITEM')
        for key,value in [('ITEMTYPE',kind),('ITEMID',number),('COLOR',colour),('MINQTY',qty),('CONDITION',condition)]:
            if value is not None: ET.SubElement(item,key).text=str(value)
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)
