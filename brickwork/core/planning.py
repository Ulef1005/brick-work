"""Planning on the 4.0 store (M.8f the Prices screen, M.8g the rest; issue #110; design 5 `copy.pinned`, `wish`, `price_*`, 3.8).

Complete sets ranks the live copies that have gaps by what a repair gains per unit spent (`ranking`, from the Workbench's gaps, the
cached BrickLink quotes and the repair settings in `setting`); the Wishlist screen reads the live wishes (`wishes`); Prices reads the
priced items (`priced_items`). Everything is by item id (`core/items`): a copy is a set item, a gap line an (item, colour). A retired
line is no line (design 4.4). Saves are audited events: a pin changes `copy.pinned`, the repair settings change `setting` rows, and
Undo (`undo`, registered with `core/undo`) puts them back unless a later save touched the same thing. The BrickLink XML export of
selected copies names every line through `core/gaps` (`items.bricklink_key`); a line with no confirmed BrickLink number is **skipped
and listed**, never exported under a made-up number."""
from .transaction import transaction
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import json

from . import collection, errors, gaps, items, workbench, collection_prices
from . import undo as undoing
from .admin import audit, origin
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


def _switch(value):
    """A stored on/off setting as 0 or 1: '1', '0', 'true', 'false' (price_settings stores a number, an old save may say a word)."""
    if isinstance(value, bool):
        return int(value)
    text = str(value).strip().lower()
    return int(text == 'true') if text in ('true', 'false') else int(Decimal(text))


def configuration(db):
    """The repair and price settings from `setting`, with the documented defaults for what is not stored."""
    from .price_settings import DEFAULTS
    config = {**DEFAULTS, **{k: v for k, v in db.execute('SELECT key,value FROM setting') if k in DEFAULTS}}
    config['incomplete_discount_pct'] = Decimal(str(config['incomplete_discount_pct']))
    config['repair_use_loose_stock'] = _switch(config['repair_use_loose_stock'])
    return config


def priced_items(db, kind=None):
    """Lean Prices projection (M.8f): one row per priced (item, colour), no observation lists.

    Four bounded reads, none of them per row. The row's stale flag is true when any current quote is past its source's freshness; the
    display price is chosen from each (condition, source, guide)'s freshest successful observation with Collection's own selection rules.
    The full observation list of one identity is `price_details`, loaded on demand. `kind` is a screen letter (S, P, M, ...): only
    that kind's items. Voided observations never show."""
    word = None
    if kind:
        try:
            word = items.kind_of_type(kind)
        except errors.BrickWorkError:
            return []                                           # '?' (a placeholder) is not a kind on 4.0: nothing is priced as one
    args = (word,) if word else ()
    where_kind = ' AND i.kind=?' if word else ''
    identities = db.execute("""SELECT p.item_id, p.color_id,
        max(coalesce(f.max_age_days IS NOT NULL AND coalesce(o.observed_at,'')!='' AND
            julianday(?)-julianday(o.observed_at) >= f.max_age_days+1,0)) AS stale
        FROM price_current p JOIN price_observation o ON o.id=p.observation_id JOIN item i ON i.id=p.item_id
        LEFT JOIN source_freshness f ON f.source=o.source AND f.kind='prices'
        WHERE o.voided_at IS NULL""" + where_kind + ' GROUP BY p.item_id, p.color_id', (now().isoformat(), *args)).fetchall()
    # One filtered scan of successful market observations picks each identity's best used and new quote and best overall with
    # Collection's own order (source priority, sold before listings, freshest, newest id); only the winners become dicts, so history
    # depth costs one pass and nothing per row after it.
    priorities = collection_prices.priority(db)
    ranks, best = {}, {}
    floor = datetime.min.replace(tzinfo=timezone.utc).timestamp()
    cursor = db.cursor()
    cursor.row_factory = None  # plain tuples: this loop runs once per observation
    cursor.execute("""SELECT o.id, i.kind, o.item_id, o.color_id, o.condition, o.guide, o.source, o.observed_at FROM price_observation o
        JOIN item i ON i.id=o.item_id WHERE o.guide IN ('sold','stock') AND coalesce(o.slot,'')!='boxed' AND coalesce(o.error,'')=''
        AND o.voided_at IS NULL AND o.price IS NOT NULL""" + where_kind, args)
    dated = collection_prices.dated
    # A quote with no recorded condition (migrated data) is a fallback only, and only from the current quotes, as Collection's choice
    # works on price_current; superseded or errored history never stands in for it.
    current = {r[0] for r in db.execute('SELECT observation_id FROM price_current' + (' WHERE item_id IN (SELECT id FROM item WHERE kind=?)' if word else ''), args)}
    for r in cursor:
        if r[4] not in ('used', 'new') and r[0] not in current:
            continue
        order, missing = ranks.get(r[1]) or ranks.setdefault(r[1], (lambda o: ({x: o.index(x) for x in o}, len(o)))(
            [x.split(':')[0] for x in priorities.get(r[1], priorities.get('*', ['bricklink']))]))
        moment = dated(r[7])
        rank = (order.get(r[6], missing), -(moment.timestamp() if moment else floor), -r[0])
        slots = best.get((r[2], r[3]))
        if slots is None:
            slots = best[r[2], r[3]] = [None, None, None]
        # Index 2 holds a quote with no recorded condition; it is read only when there is no used or new quote.
        index = 0 if r[4] == 'used' else 1 if r[4] == 'new' else 2
        candidate = (rank[0], r[5] != 'sold') + rank[1:] if index < 2 else rank
        if slots[index] is None or candidate < slots[index][0]:
            slots[index] = (candidate, rank, r[0])
    owned = {r[0] for r in db.execute("""SELECT item_id FROM copy WHERE archived_at IS NULL
        UNION SELECT item_id FROM stock WHERE archived_at IS NULL""")}
    wanted = {r[0] for r in db.execute('SELECT item_id FROM wish WHERE archived_at IS NULL')}
    rows = []
    for r in identities:
        key = (r['item_id'], r['color_id'])
        slots = best.get(key, [None, None, None])
        conditions = [s for s in slots[:2] if s]
        pick = min(conditions, key=lambda s: s[1]) if conditions else slots[2]
        rows.append(dict(item_id=key[0], color_id=key[1], stale=bool(r['stale']), owned=key[0] in owned, wanted=key[0] in wanted,
                         display_price=pick[2] if pick else None))
    # Winners only become full observation rows, in one read.
    full = {r['id']: dict(r) for r in db.execute("""SELECT o.*, i.kind, f.max_age_days FROM price_observation o JOIN item i ON i.id=o.item_id
        LEFT JOIN source_freshness f ON f.source=o.source AND f.kind='prices'
        WHERE o.id IN (SELECT value FROM json_each(?))""", (json.dumps([r['display_price'] for r in rows if r['display_price']]),))}
    for row in rows:
        row['display_price'] = full[row['display_price']] if row['display_price'] else None
    rows = collection.decorate(db, rows)
    for row in rows:
        if row['display_price']:
            row['display_price'] = collection.decorate_prices([row['display_price']])[0]
    return rows


PRICE_FIELDS = 'type number name colour color_id rgb ink image unresolved owned wanted stale price listings age observed price_stale item_id'.split()


def price_records(rows):
    """Compact positional Prices rows (see `PRICE_FIELDS`): identity, kind, owned/wanted, the display price as text with its age and
    stale flag, and the item id the page links and refreshes by. Refresh is available to every row that is not unresolved."""
    from ..web.formatting import money, short_age
    records = []
    for r in rows:
        p = r['display_price']
        records.append([r['item_type'], r.get('number_text') or r.get('name') or '', r.get('name') or r.get('number_text') or '', r.get('color_name') or '',
                        r['color_id'], r.get('rgb'), r.get('ink'), r.get('image'), bool(r.get('unresolved')), bool(r['owned']), bool(r['wanted']),
                        bool(r['stale']), money(p['price'], p.get('currency') or '', fixed=True) if p else None,
                        bool(p and p['guide'] == 'stock'), short_age(p['age']) if p else '',
                        (p['observed_at'] or '')[:10] if p else '', bool(p and p['stale']), r['item_id']])
    return dict(fields=PRICE_FIELDS, rows=records)


def price_details(db, item_id, colour=None):
    """One identity's observation list for the Prices Details disclosure, display text only."""
    from ..web.formatting import money, short_age
    item = db.execute('SELECT id, kind, category_name, year FROM item WHERE id=?', (item_id,)).fetchone()
    if item is None:
        return None
    kind = item['kind']
    records = collection.decorate_prices(db.execute("""SELECT o.*, i.kind, f.max_age_days FROM price_observation o JOIN item i ON i.id=o.item_id
        LEFT JOIN source_freshness f ON f.source=o.source AND f.kind='prices'
        WHERE o.item_id=? AND o.color_id IS ? AND o.voided_at IS NULL ORDER BY o.observed_at DESC, o.id DESC""", (item_id, colour)))
    priorities = collection_prices.priority(db)
    by_condition = collection_prices.condition_rows(records, kind, priorities)
    current = {r[0] for r in db.execute('SELECT observation_id FROM price_current WHERE item_id=? AND color_id IS ?', (item_id, colour))}
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
    return dict(context=' · '.join(str(x) for x in (item['category_name'], item['year']) if x),
                selected=(f"{chosen['label']}{' · avg' if chosen['guide'] == 'sold' else ''} · {amount(chosen['price'], chosen['currency'])}" if chosen else None),
                conditions=[f"{p['label']} · {amount(p['price'], p['currency'])} · {age(p)}" for p in by_condition],
                groups=[g for g in groups if g['quotes']], empty=not records)


def display_prices(db, rows):
    """One bulk observation read for the identities of `rows` (items with `item_id`, `color_id`); Collection's condition/source selection.

    Every row gets `price_records` (its observations, newest first, a voided one never), `condition_prices` and `display_price`: the
    price at the wish's condition when it names one, else the best overall."""
    if not rows:
        return rows
    priorities = collection_prices.priority(db)
    grouped = defaultdict(list)
    pairs = json.dumps(sorted({(r['item_id'], r.get('color_id') or 0) for r in rows}))
    observations = db.execute("""SELECT o.*,i.kind,f.max_age_days FROM price_observation o JOIN item i ON i.id=o.item_id
        LEFT JOIN source_freshness f ON f.source=o.source AND f.kind='prices'
        WHERE o.voided_at IS NULL AND (o.item_id, coalesce(o.color_id,0)) IN (SELECT json_extract(value,'$[0]'), json_extract(value,'$[1]') FROM json_each(?))
        ORDER BY o.observed_at DESC,o.id DESC""", (pairs,))
    for p in collection.decorate_prices(observations):
        grouped[p['item_id'], p['color_id']].append(p)
    for row in rows:
        records = grouped[row['item_id'], row.get('color_id')]
        row['price_records'] = records
        row['condition_prices'] = collection_prices.condition_rows(records, row['kind'], priorities)
        condition = row.get('condition') if row.get('condition') in ('new', 'used') else None
        row['display_price'] = collection_prices.choose(row['condition_prices'], row['kind'], priorities, condition)
        if not row['display_price']:
            row['display_price'] = collection_prices.choose(
                [p for p in row['prices'] if p['guide'] in ('sold', 'stock') and p.get('slot') != 'boxed'],
                row['kind'], priorities, condition)
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
    """The live wishes of every active list, as Collection lists them, with the price shown, the comparison with the max, how much is
    filled and the retail line of a set. Filled lines drop to the bottom (#35); the order within each part stays as listed."""
    from . import currency, retail, wish_progress
    rows = display_prices(db, collection.listing(db, 'S', wishes=True))
    table = currency.rates(db)
    for row in rows:
        row['max_state'], row['max_margin'] = max_comparison(row, table)
    wish_progress.annotate(db, rows)
    info = retail.lookup(db, [r['item_id'] for r in rows if r['kind'] == 'set'])
    for r in rows:
        r['retail'] = info.get(r['item_id']) if r['kind'] == 'set' else None
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
    """Complete sets: every live copy with a gap, grouped and ranked (`compute`), decorated for the screen: `rows` is the whole list in
    screen order (ranked, free repairs, outside break-even, needs evidence) and `settings` the configuration used."""
    config = configuration(db)
    stamp = now()
    rows = [dict(r) for r in db.execute('''SELECT c.*,i.year,i.theme_name AS theme,i.category_name AS category FROM copy c
        JOIN item i ON i.id=c.item_id WHERE c.archived_at IS NULL ORDER BY c.item_id,c.created_at,c.id''')]
    names = items.labels(db, {(r['item_id'], None) for r in rows})
    for c in rows:
        label = names[c['item_id'], None]
        c.update(color_id=None, items=[], name=label.name, set_num=label.number or str(c['item_id']))
    copies = {r['id']: r for r in rows}
    for copy_id, text in collection.copy_labels(db, list(copies)).items():
        copies[copy_id]['label'] = text
    gap_lines = [g for g in workbench.gaps(db) if g['target'] in ('part', 'figure') and g['copy_id'] in copies]
    pairs = {(c['item_id'], None) for c in rows} | {g['key'] for g in gap_lines}
    market = collection.prices(db, pairs=pairs)
    named = items.labels(db, {g['key'] for g in gap_lines})
    for c in rows:
        c['complete_quote'] = quote(market[c['item_id'], None], c['condition'] or 'used', config, stamp)
    pool = defaultdict(int)
    if config['repair_use_loose_stock']:
        defective = workbench.defective_figures(db)
        for r in db.execute("SELECT * FROM stock WHERE archived_at IS NULL AND kind='part'"):
            pool[r["item_id"], r["color_id"]] += workbench.available(db, r, defective=defective)
        for r in db.execute("SELECT item_id,color_id,sum(qty) FROM allocation WHERE state='pending' AND kind='missing_part' GROUP BY item_id,color_id"):
            pool[r[0], r[1]] = max(0, pool[r[0], r[1]] - (r[2] or 0))
    for gap in sorted(gap_lines, key=lambda g: (g['copy']['set_no'], g['copy_id'], g['item_no'], g['color_id'] or 0)):
        c = copies[gap['copy_id']]
        need, key = gap['need'], gap['key']
        take = min(need, pool[key]) if gap['item_type'] == 'P' else 0
        pool[key] -= take
        label = named.get(key)
        # Keep zero-buy lines: free repairs still have evidence and an original gap.
        c['items'].append(dict(gap, type=gap['item_type'], number=gap['number_text'] or gap['name'], missing=need - take, original_gap=need,
                               stock_used=take, figure=None, mapped=bool(label and label.bricklink),
                               quote=quote(market[key], c['condition'] or 'used', config, stamp)))
    data = compute(rows, config, stamp)
    for group in ('ranked', 'needs_evidence', 'outside', 'free_repairs'):
        for c in data[group]:
            c['missing_count'] = sum(r['missing'] for r in c['items'])
            c['original_gap'] = sum(r['original_gap'] for r in c['items'])
            c['stock_used'] = sum(r['stock_used'] for r in c['items'])
            c['group'] = group
    decorated = collection.decorate(db, [c for group in ('ranked', 'free_repairs', 'outside', 'needs_evidence') for c in data[group]])
    top_ratio = max((r['ratio'] for r in data['ranked']), default=None)
    for row in decorated:
        row['display_ratio_width'] = float(row['ratio'] / top_ratio * 100) if row['group'] == 'ranked' and top_ratio else None
    # #38: part-out value per copy, one batch for the whole list.
    from . import partout
    values = partout.values(db, [row['id'] for row in decorated])
    for row in decorated:
        row['partout'] = partout.compare(row, values.get(row['id']))
    data['rows'] = decorated
    return data


# ---------- saves, Undo and the export ----------

ENTITY = 'planning'
LATER = 'Item changed · undo the later save first'


def _written(db):
    return db.execute('SELECT last_insert_rowid()').fetchone()[0]


def _stored(db, keys):
    """`{key: stored text or None}` for setting keys, in one read."""
    found = dict(db.execute('SELECT key,value FROM setting WHERE key IN (SELECT value FROM json_each(?))', (json.dumps(sorted(keys)),)))
    return {k: found.get(k) for k in keys}


def save(db, action, data):
    """`pin` (`id`, `pinned`: a boolean) sets `copy.pinned`; `settings` (`values`: all five repair settings) writes them to `setting`.
    One audited event each; returns its id."""
    with transaction(db):
        if action == 'pin':
            if type(data.get('pinned')) is not bool:
                raise ValueError('Choose pinned or unpinned')
            copy = db.execute('SELECT id,pinned,archived_at FROM copy WHERE id=?', (str(data.get('id')),)).fetchone()
            if copy is None or copy['archived_at']:
                raise ValueError('Copy is unavailable')
            db.execute('UPDATE copy SET pinned=? WHERE id=?', (int(data['pinned']), copy['id']))
            audit(db, f"{ENTITY}:{copy['id']}", 'pin', [dict(id=copy['id'], pinned=copy['pinned'])], [dict(id=copy['id'], pinned=int(data['pinned']))])
        elif action == 'settings':
            values = data.get('values')
            if not isinstance(values, dict) or set(values) != set(REPAIR_KEYS):
                raise ValueError('Choose all repair settings')
            for k, v in values.items():
                try:
                    n = Decimal(str(v))
                except InvalidOperation as exc:
                    raise ValueError('Use a non-negative number') from exc
                if not n.is_finite() or n < 0 or (k == 'incomplete_discount_pct' and n > 100) or (k == 'repair_use_loose_stock' and n not in (0, 1)):
                    raise ValueError('Repair setting is out of range')
            before = _stored(db, REPAIR_KEYS)
            after = {k: str(v) for k, v in values.items()}
            db.executemany('INSERT OR REPLACE INTO setting(key,value) VALUES(?,?)', sorted(after.items()))
            audit(db, ENTITY, 'settings', before, after)
        else:
            raise ValueError('Unknown planning action')
        return _written(db)


def _undo_save(db, event, via, actor):
    """Put a pin or the repair settings back. Refused whole when a later save changed them since (undo that one first)."""
    before, after = json.loads(event['old_value']), json.loads(event['new_value'])
    if event['field'] == 'pin':
        current = db.execute('SELECT id,pinned,archived_at FROM copy WHERE id=?', (after[0]['id'],)).fetchone()
        if current is None or current['archived_at'] or current['pinned'] != after[0]['pinned']:
            raise ValueError(LATER)
        db.execute('UPDATE copy SET pinned=? WHERE id=?', (before[0]['pinned'], current['id']))
    else:
        current = _stored(db, list(after))
        if current != after:
            raise ValueError(LATER)
        for key, value in before.items():
            if value is None:
                db.execute('DELETE FROM setting WHERE key=?', (key,))
            else:
                db.execute('INSERT OR REPLACE INTO setting(key,value) VALUES(?,?)', (key, value))
    audit(db, ENTITY, 'undo', None, dict(undoes=event['id']), via=via, actor=actor)
    undo_id = _written(db)
    db.execute('INSERT INTO event_undo(event_id, undo_event_id) VALUES(?, ?)', (event['id'], undo_id))
    return {'event_id': undo_id}


for _field in ('pin', 'settings'):
    undoing.register(ENTITY, _field, _undo_save)


def undo(db, event_id):
    """Undo a pin or a settings save by its event id; a second Undo of the same event does nothing."""
    via, actor = origin()
    return undoing.undo_event(db, int(event_id), via=via, actor=actor)


def export(db, ids):
    """The BrickLink Wanted List of the chosen copies' repair lines: `dict(xml, lines, skipped)` as `gaps.export`, but the quantity of
    a line is what is still to buy (the gap less the loose stock the repair settings let it use). A copy with no gap is not on the list."""
    if not isinstance(ids, list) or not ids or len(ids) > 2000 or len(set(ids)) != len(ids):
        raise ValueError('Choose copies to export')
    chosen = [r for r in ranking(db)['rows'] if r['id'] in ids]
    if len(chosen) != len(ids):
        raise ValueError('Copy is unavailable')
    total = defaultdict(int)
    for c in chosen:
        for r in c['items']:
            if r['missing']:
                total[r['item_id'], r['color_id'], gaps.CONDITION.get(c['condition'], 'U')] += r['missing']
    return gaps.export_lines(db, total)
