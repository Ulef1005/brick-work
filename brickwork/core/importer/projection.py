"""Pure legacy-to-v3.2 projection, shared by the writer and the read-only proof.

No collection values are logged here. Raw cache envelopes retain SQLite types,
NULLs and JSON array order. Only typed referenced identities become items.
"""
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

from . import idmatch
from ..sources.images import picture_kind
from ..names import catalogue_names, choose_names

SOURCES = [('bricklink', 'BrickLink', 'api'), ('rebrickable', 'Rebrickable', 'api'),
           ('brickset', 'Brickset', 'api'), ('brickognize', 'Brickognize', 'api'),
           ('peeron', 'Peeron', 'file'), ('manual', 'Manual', 'manual')]
PRIORITY = {
    'identity': {'*': ['bricklink:local', 'bricklink:api']},
    'inventory': {'*': ['bricklink:subsets']},
    'matching': {'*': ['rebrickable', 'part_resolutions', 'manual']},
    'pictures': {'P': ['rebrickable', 'bricklink'], '*': ['bricklink', 'rebrickable']},
    'metadata': {'S': ['brickset']}, 'market_price': {'*': ['bricklink']},
}
AUDITED = ('copies', 'copy_parts', 'copy_minifigs', 'loose_stock',
           'loose_minifig_parts', 'wishlist', 'flags', 'item_flags', 'settings', 'lots')
PRICE_KEY = ('item_type', 'item_no', 'color_id', 'condition', 'guide', 'slot', 'region', 'currency')
EMPTY = ('orders', 'order_documents', 'order_lines', 'line_receipts', 'line_receipt_log',
         'allocations', 'instruction_files', 'match_history', 'jobs')


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def money(value):
    if value is None:
        return None
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError('Non-finite legacy money')
    return value if isinstance(value, str) else format(number, 'f')


def date(value):
    if value is None or isinstance(value, str):
        return value
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def read(path):
    with closing(idmatch.open_readonly(path)) as db:
        db.execute('PRAGMA query_only=ON')
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {t: [dict(r) for r in db.execute(f'SELECT rowid AS _lineage,* FROM "{t}" ORDER BY rowid')] for t in tables}


def original(row):
    return {k: v for k, v in row.items() if k != '_lineage'}


def project(app_path, web_path, decisions_path, catalogue):
    app, web = read(app_path), read(web_path)
    decisions = json.loads(Path(decisions_path).read_text())
    matches = idmatch.match(app_path, web_path, catalogue)
    out = defaultdict(list)
    transformations = []
    items = set()
    evidence = defaultdict(list)
    targets = {}
    contexts = defaultdict(set)
    decided = {}
    cache = {}
    cached_targets = defaultdict(set)
    for r in app['rebrickable_parts']:
        cache[r['part'], r['color_id']] = r
        if r['bricklink_part_num']:
            cached_targets[r['part']].add(r['bricklink_part_num'])
    figure_decisions = defaultdict(list)
    for r in decisions.get('minifigs', []):
        figure_decisions[r['source_id']].append(r)
    manual = {(r['kind'], r['source_id']): r for r in decisions.get('manual', []) + decisions.get('to_check', [])}
    copies = {r['id']: r['set'] for r in app['bricktracker_sets']}
    validate_joins(app, web, copies)
    source_sets = {r['set'] for t in ('rebrickable_sets', 'bricktracker_wishes') for r in app[t]}
    forward = {r['figure']: r for r in web['minifig_bricklink']}
    figure_base = {r['figure']: r for r in matches['minifigures']}
    parts_base = {(r['part'], r['color']): r for r in matches['parts'] + matches['loose_parts']}
    colors = defaultdict(set)
    for r in web['color_map']:
        colors[r['color_id']].add(r['bricklink_color_id'])
        evidence['color', str(r['color_id'])].append({'table': 'color_map', 'record': original(r)})
    resolutions = defaultdict(list)
    for r in web['part_resolutions']:
        for candidate in json.loads(r['parts']):
            resolutions[candidate['part_num']].append(r)
            evidence['part', candidate['part_num']].append({'table': 'part_resolutions', 'record': original(r)})
            match_key = ('part', candidate['part_num'])
            decided[match_key] = max(decided.get(match_key) or '', r['resolved_at'] or '') or None
    for r in web['minifig_bricklink']:
        evidence['minifigure', r['figure']].append({'table': 'minifig_bricklink', 'record': original(r)})
        decided['minifigure', r['figure']] = r['resolved_at']
        if r['set_num']:
            contexts['minifigure', r['figure']].add(r['set_num'])
    for r in web['bricklink_figures']:
        if r['figure']:
            evidence['minifigure', r['figure']].append({'table': 'bricklink_figures', 'record': original(r)})
    for r in decisions.get('minifigs', []):
        evidence['minifigure', r['source_id']].append({'table': 'matching-decisions', 'record': r})
        contexts['minifigure', r['source_id']].add(r['context'])
        decided['minifigure', r['source_id']] = decisions.get('decided')
    for r in decisions.get('manual', []) + decisions.get('to_check', []):
        kind = 'minifigure' if r['kind'] == 'minifig' else r['kind']
        sid = r['source_id'].split('/')[0] if kind == 'part' else r['source_id']
        evidence[kind, sid].append({'table': 'matching-decisions', 'record': r})
        decided[kind, sid] = decisions.get('decided')

    def record_match(kind, sid, key, color=None, method=None, status='matched'):
        targets[kind, str(sid)] = (key, color, method, status)
        return key, color

    def ref(key):
        items.add(key)
        return key

    def set_key(number):
        m = manual.get(('set', number))
        key = (m['item_type'], m['item_no']) if m else ('S', number)
        if number in source_sets:
            record_match('set', number, key, method=m['method'] if m else 'set_number', status=m['status'] if m else 'matched')
        return key

    def wish_key(number):
        # Legacy part wishes encode the Rebrickable part and colour as JSON.
        if isinstance(number, str) and number.startswith('['):
            pair = json.loads(number)
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError('Invalid legacy part wish key')
            key, color = part_key(pair[0], pair[1])
            if color is None:
                raise ValueError('Legacy part wish colour needs matching')
            return key, color
        return set_key(number), None

    def figure_key(number, context=None):
        entries = figure_decisions.get(number, [])
        chosen = next((r for r in entries if r['context'] == context), None)
        if chosen is None and entries:
            distinct = {(r['item_type'], r['item_no'], r['status']) for r in entries}
            if len(distinct) != 1:
                raise ValueError('Inconsistent figure decisions without a context')
            chosen = entries[0]
        base = figure_base.get(number, {})
        if chosen:
            key, method, status = (chosen['item_type'], chosen['item_no']), chosen['method'], chosen['status']
        elif base.get('status') == 'matched':
            key, method, status = ('M', base['bricklink_item_no']), base['method'], 'matched'
            if number in forward:
                method = forward[number]['source']
                status = 'manual' if method == 'manual' else 'matched'
        elif number in forward:
            key, method, status = ('M', forward[number]['bricklink_id']), 'minifig_bricklink', forward[number]['source'].replace('match', 'matched')
        else:
            key, method, status = ('?', 'rebrickable:' + number), 'review', 'unmatched'
        record_match('minifigure', number, key, method=method, status=status)
        return key

    def color_key(number):
        candidates = colors[number]
        color = next(iter(candidates)) if len(candidates) == 1 else None
        record_match('color', str(number), None, color, 'color_map', 'matched' if color is not None else 'to_check' if candidates else 'unmatched')
        return color

    def part_key(number, color=None):
        # Actual inventory decisions come from the existing matcher, including
        # its catalogue and colour-disagreement checks. Cache-only projections
        # use the stored bridge, never a speculative new identity.
        m = manual.get(('part', f'{number}/{color}'))
        if m:
            key, mapped_color = (m['item_type'], m['item_no']), m.get('color_id')
            status, method = m['status'], m['method']
        elif (number, color) in parts_base:
            b = parts_base[number, color]
            key = ('P', b['bricklink_item_no']) if b['status'] == 'matched' else ('?', 'rebrickable:' + number)
            mapped_color = b['bricklink_color_id'] if b['status'] == 'matched' else color_key(color)
            status, method = ('to_check' if b['status'] == 'conflict' else b['status']), b['method']
        else:
            direct = cache.get((number, color), {}).get('bricklink_part_num')
            candidates = cached_targets[number] if color is None else {direct} if direct else set()
            if not candidates:
                candidates = {r['bricklink'] for r in resolutions[number]}
            key = ('P', next(iter(candidates))) if len(candidates) == 1 else ('?', 'rebrickable:' + number)
            mapped_color = color_key(color) if color is not None else None
            status = 'matched' if len(candidates) == 1 else 'to_check' if candidates else 'unmatched'
            method = 'rebrickable_parts' if (direct or (color is None and cached_targets[number])) else 'part_resolutions'
        if method == 'part_resolutions':
            methods = {r['source'] for r in resolutions[number] if r['source'] is not None}
            if len(methods) == 1:
                method = next(iter(methods))
        # Different colours are evidence of one part identity. A single match
        # colour exists only if all its recorded colours agree.
        old = targets.get(('part', number))
        if old and old[0] != key:
            evidence['part', number].append({'context_color': color, 'target': key, 'status': status})
        record_match('part', number, key, mapped_color if old is None or old[1] == mapped_color else None, method, status)
        return key, mapped_color

    def raw(source, table, sid, row, fetched=None):
        out['source_records'].append(dict(source=source, kind=table, source_id=str(sid),
            payload=packed({'records': [{'table': table, 'record': original(row)}]}), fetched_at=fetched, status='legacy'))

    def purchase(row):
        return dict(storage_id=row.get('storage'), purchase_location_id=row.get('purchase_location'),
                    purchase_date=date(row.get('purchase_date')), purchase_price=money(row.get('purchase_price')),
                    purchase_currency=None, note=row.get('description', row.get('note')))

    out['sources'] = [dict(source=s, name=n, kind=k, enabled=1, priority_settings=None) for s, n, k in SOURCES]
    out['source_freshness'] = [dict(source=s, kind=k, max_age_days=days) for s, _, _ in SOURCES
                              for k, days in (('prices', 30), ('metadata', 365), ('pictures', None))]
    out['colors'] = [dict(color_id=r['id'], name=r['name'], type=r['type'], rgb=None) for r in web['bricklink_colors']]
    for name in ('storages', 'purchase_locations'):
        out[name] = [dict(original(r), **({'archived_at': None} if name == 'storages' else {}))
                     for r in app['bricktracker_metadata_' + name]]
    for r in app['bricktracker_individual_part_lots']:
        out['lots'].append(dict(id=r['id'], name=r['name'], created_date=date(r['created_date']), archived_at=None, **purchase(r)))
    statuses = {r['copy_id']: r for r in web['copy_status']}
    valuations = {r['copy_id']: r for r in web['copy_valuation']}
    missing = {(r['copy_id'], r['figure']): r for r in web['minifig_missing']}
    for r in app['bricktracker_sets']:
        s, v = statuses.get(r['id'], {}), valuations.get(r['id'], {})
        key = ref(set_key(r['set']))
        out['copies'].append(dict(id=r['id'], item_type=key[0], set_no=key[1], condition=s.get('condition'),
            completeness=s.get('completeness'), completeness_source='manual' if s.get('completeness') is not None else None,
            current_value=money(v.get('current_value')), current_value_currency=v.get('current_value_currency'),
            pinned=v.get('pinned', 0), updated_at=s.get('updated_at'), archived_at=None, **purchase(r)))
    for r in app['bricktracker_minifigures']:
        key = ref(figure_key(r['figure'], copies[r['id']]))
        m = missing.get((r['id'], r['figure']), {})
        out['copy_minifigs'].append(dict(copy_id=r['id'], item_type=key[0], minifig_no=key[1], quantity=r['quantity'],
            missing=m.get('missing', 0), updated_at=m.get('updated_at')))
    state_fields = ('spare', 'quantity', 'missing', 'damaged', 'checked')
    for table, target in (('bricktracker_parts', 'copy_parts'), ('bricktracker_individual_minifigure_parts', 'loose_minifig_parts')):
        for r in app[table]:
            key, color = part_key(r['part'], r['color']); ref(key)
            row = dict(item_type=key[0], item_no=key[1], color_id=color, element_id=r['element'], source_ref=r['rebrickable_inventory'],
                       **{k: r[k] for k in state_fields})
            if target == 'copy_parts':
                parent = ref(figure_key(r['figure'], copies[r['id']])) if r['figure'] else (None, None)
                row.update(id=r['_lineage'], copy_id=r['id'], parent_minifig_type=parent[0], parent_minifig=parent[1])
            else:
                row['stock_id'] = r['id']
            out[target].append(row)
    loose_status = {r['individual_id']: r for r in web['loose_minifig_status']}
    receipts = {r['individual_id']: r for r in web['loose_minifig_imports']}
    for table, subtype in (('bricktracker_individual_parts', 'P'), ('bricktracker_individual_minifigures', 'M')):
        for r in app[table]:
            key, color = part_key(r['part'], r['color']) if subtype == 'P' else (figure_key(r['figure']), None)
            ref(key)
            s = loose_status.get(r['id'], {})
            out['loose_stock'].append(dict(id=r['id'], item_type=key[0], item_no=key[1], color_id=color, quantity=r['quantity'],
                condition='U' if subtype == 'P' else s.get('condition'), lot_id=r.get('lot_id'),
                created_at=receipts.get(r['id'], {}).get('created_at'), updated_at=s.get('updated_at'), archived_at=None,
                **{k: r.get(k) for k in ('missing', 'damaged', 'checked')}, **purchase(r)))
    for table, kind in (('loose_instructions', 'I'), ('loose_boxes', 'O')):
        for r in web[table]:
            key = ref((kind, r['set_num']))
            out['loose_stock'].append(dict(id=r['id'], item_type=key[0], item_no=key[1], color_id=None, quantity=r['quantity'],
                condition=r['condition'], lot_id=None, created_at=r['created_at'], updated_at=None, archived_at=None,
                missing=None, damaged=None, checked=None, **purchase(r)))
    for r in web['loose_minifig_imports']:
        key = ref(figure_key(r['figure']))
        out['import_receipts'].append(dict(import_key=r['import_key'], individual_id=r['individual_id'], item_type=key[0],
            figure=key[1], quantity=r['quantity'], created_at=r['created_at']))
    wishmeta = {r['set']: r for r in web['wish_meta']}
    wish_ids = {}
    # Same rule as the upgrade for older outputs: a wish limit takes the configured BrickLink currency (default EUR).
    limit_currency = next((str(r['bricklink_currency']) for r in web['price_settings'] if r.get('bricklink_currency')), 'EUR')
    for r in app['bricktracker_wishes']:
        key, color = wish_key(r['set']); ref(key)
        m = wishmeta.get(r['set'], {})
        identifier = r['_lineage']
        wish_ids[r['set']] = str(identifier)
        out['wishlist'].append(dict(id=identifier, list_id='default', item_type=key[0], item_no=key[1], color_id=color, quantity=1, max_price=money(m.get('max_price')), max_price_currency=limit_currency if money(m.get('max_price')) is not None else None,
            condition=m.get('condition'), note=None, added_at=None, updated_at=m.get('updated_at'), archived_at=None))
    for plural, kind in (('statuses', 'status'), ('tags', 'tag'), ('owners', 'owner')):
        metadata = app['bricktracker_metadata_' + plural]
        out['flags'].extend(dict(id=r['id'], name=r['name'], kind=kind, shown_on_grid=r.get('displayed_on_grid', 1)) for r in metadata)
        for table in ['bricktracker_set_' + plural] + (['bricktracker_wish_owners'] if kind == 'owner' else []):
            for r in app[table]:
                assertions = []
                for flag in metadata:
                    column = kind + '_' + flag['id'].replace('-', '_')
                    if r[column] == 1:
                        entity = r.get('id') if 'id' in r else wish_ids[r['set']]
                        if 'id' in r and entity not in copies:
                            raise ValueError('True orphan flag assertion')
                        assertions.append(dict(entity_type='copy' if 'id' in r else 'wishlist', entity_id=entity, flag_id=flag['id']))
                out['item_flags'].extend(assertions)
                if not assertions and 'id' in r and r['id'] not in copies:
                    transformations.append(dict(table=table, lineage=r['_lineage'], rule='false-only orphan dropped'))
    # Stable history-family ordering, then numeric original id.
    observations, envelopes, equivalent = [], {}, {}
    for table, kind in (('price_history', 'S'), ('minifig_price_history', 'M'), ('part_price_history', None),
                        ('price_slots', 'S'), ('minifig_prices', 'M'), ('part_prices', None)):
        history = table.endswith('history')
        for r in sorted(web[table], key=lambda r: r.get('id', r['_lineage'])):
            row = price(r, kind, set_key)
            ref((row['item_type'], row['item_no']))
            sig = packed(row)
            if history or sig not in equivalent:
                row['id'] = len(observations) + 1
                observations.append(row)
                source_id = r.get('id', r['_lineage'])
                envelope = dict(source=row['source'], kind=table, source_id=str(source_id),
                    payload=packed({'records': [{'table': table, 'record': original(r)}]}), fetched_at=None, status='legacy')
                out['source_records'].append(envelope)
                equivalent.setdefault(sig, row['id'])
                envelopes[row['id']] = envelope
            if not history:
                envelope = envelopes[equivalent[sig]]
                payload = json.loads(envelope['payload'])
                payload['records'].append({'table': table, 'record': original(r)})
                envelope['payload'] = packed(payload)
    out['price_observations'] = observations
    latest = {}
    for r in observations:
        key = tuple(r[k] for k in PRICE_KEY)
        if key not in latest or (r['observed_at'] or '', r['id']) > (latest[key]['observed_at'] or '', latest[key]['id']):
            latest[key] = r
    out['price_current'] = [dict(**{k: r[k] for k in PRICE_KEY}, observation_id=r['id']) for r in latest.values()]
    for r in web['price_tracking']:
        key = ref(set_key(r['set_num']))
        out['price_watch'].append(dict(item_type=key[0], item_no=key[1], color_id=None, condition=None,
            **{k: r[k] for k in ('origin', 'first_seen', 'last_fetch_at', 'last_error', 'last_error_at')}, last_attempt_at=None))
    attempts = {}
    for r in web['part_price_history'] + web['part_prices']:
        key = (r['item_type'], r['item_no'], r['color_id'], r['condition'])
        if key not in attempts or (r['last_attempt_at'] or '') > (attempts[key]['last_attempt_at'] or ''):
            attempts[key] = r
    for key, r in attempts.items():
        ref(key[:2])
        out['price_watch'].append(dict(item_type=key[0], item_no=key[1], color_id=key[2], condition=key[3], origin=None,
            first_seen=None, last_fetch_at=None, last_error=None, last_error_at=None, last_attempt_at=r['last_attempt_at']))
    for r in web['fetch_log']:
        key = ref(set_key(r['set_num'])) if r['set_num'] else (None, None)
        out['fetch_log'].append(dict(id=r['id'], item_type=key[0], item_no=key[1], **{k: r[k] for k in ('source', 'at', 'ok', 'detail')}))
    for r in web['price_settings']:
        out['settings'].extend(dict(key=k, value=None if v is None else str(v)) for k, v in original(r).items() if k not in ('id', 'changed_at'))
    out['settings'].extend([dict(key='retail_country', value='DE'), dict(key='source_priority', value=packed(PRIORITY))])
    for r in web['minifig_parts_bl']:
        parent = ref(figure_key(r['figure']))
        for ordinal, child in enumerate(json.loads(r['parts_json'])):
            candidates = child['bricklink']
            if len(candidates) == 1:
                key = ref(('P', candidates[0]))
            else:
                sid = f'{r["figure"]}:{ordinal}'
                key = ref(('?', 'rebrickable:' + sid))
                record_match('inventory-child', sid, key, child['color_id'], 'review', 'to_check')
                evidence['inventory-child', sid].append({'table': 'minifig_parts_bl', 'ordinal': ordinal, 'record': original(r)})
            out['inventory_lines'].append(dict(id=len(out['inventory_lines']) + 1, parent_item_type=parent[0], parent_item_no=parent[1],
                child_item_type=key[0], child_item_no=key[1], color_id=child['color_id'], quantity=child['quantity'], extra_quantity=0,
                source='rebrickable-translated', fetched_at=r['fetched_at']))
        raw('rebrickable', 'minifig_parts_bl', r['figure'], r, r['fetched_at'])
    for r in web['identifications']:
        candidates = json.loads(r['candidates'])
        for c in candidates:
            if c.get('bricklink'):
                ref(('P', c['bricklink']))
            for n, part in enumerate(c.get('parts', [])):
                number = part['part_num'] if isinstance(part, dict) else part
                key, _ = part_key(number); ref(key)
                c['parts'][n] = dict(part, item_type=key[0], part_num=key[1]) if isinstance(part, dict) else key[1]
                evidence['part', number].append({'table': 'identifications', 'record': original(r)})
        out['identifications'].append(dict(id=r['id'], created_at=r['created_at'], has_thumb=r['has_thumb'],
            candidates=packed(candidates), missing_count=r['missing_count']))
        raw('brickognize', 'identifications', r['id'], r)
    for r in web['identification_actions']:
        key, color = part_key(r['part_num'], r['color_id']); ref(key)
        setref = ref(set_key(r['set_num'])) if r['set_num'] else (None, None)
        out['identification_actions'].append(dict(**{k: r[k] for k in ('id', 'identification_id', 'kind', 'at', 'color_name', 'quantity', 'copy_id', 'storage')},
            item_type=key[0], part_num=key[1], color_id=color, set_type=setref[0], set_num=setref[1]))
    # Lossless cache records, overlapping set/wish variants merged by source key.
    setrecords = {}
    projections = []
    for table, kind in (('rebrickable_sets', 'set'), ('bricktracker_wishes', 'set'), ('rebrickable_minifigures', 'minifigure'), ('rebrickable_parts', 'part')):
        for r in app[table]:
            number = r['set'] if kind == 'set' else r['figure'] if kind == 'minifigure' else r['part']
            key, color = wish_key(number) if table == 'bricktracker_wishes' else (set_key(number), None) if kind == 'set' else (figure_key(number), None) if kind == 'minifigure' else part_key(number, r['color_id'])
            sid = packed([number, r['color_id']]) if kind == 'part' else number
            evidence[kind, number].append({'table': table, 'record': original(r)})
            if kind == 'set' and sid in setrecords:
                envelope = setrecords[sid]; payload = json.loads(envelope['payload'])
                payload['records'].append({'table': table, 'record': original(r)})
                envelope['payload'] = packed(payload)
            else:
                raw('rebrickable', 'rebrickable_sets' if kind == 'set' else table, sid, r)
                if kind == 'set':
                    setrecords[sid] = out['source_records'][-1]
            projections.append((table, r, key, color))
    for number in resolutions:
        if ('part', number) not in targets:
            part_key(number)
    for number in colors:
        color_key(number)
    # The exceptional colour with no bridge still needs its evidence row.
    for r in app['bricktracker_parts'] + app['bricktracker_individual_parts'] + app['bricktracker_individual_minifigure_parts']:
        color_key(r['color'])
    for table, source, sidfield in (('part_resolutions', 'rebrickable', 'bricklink'), ('bricklink_figures', 'bricklink', 'bricklink_id'),
                                     ('bricklink_colors', 'bricklink', 'id')):
        for r in web[table]:
            raw(source, table, r[sidfield], r)
    properties = defaultdict(set)
    names, years = {}, {}
    name_candidates = defaultdict(set)
    propmap = {'version': 'version', 'theme_id': 'rebrickable.theme_id', 'number_of_parts': 'pieces',
               'url': 'url', 'last_modified': 'source_modified_at', 'category': 'rebrickable.category'}
    for table, r, key, color in projections:
        if key not in items:
            continue
        if key[0] == 'S':
            years[key] = r.get('year')
        if r.get('name'):
            name_candidates[key].add(r['name'])
        for column, prop in propmap.items():
            if r.get(column) is not None:
                properties[key + (prop,)].add(str(r[column]))
        if r.get('image') is not None:
            local = local_picture(r, table, Path(app_path).parent)
            if local is None:
                transformations.append(dict(table='item_images', lineage=r['_lineage'],
                    source_table=table, rule='image URL retained raw; local file absent'))
                continue
            out['item_images'].append(dict(id=len(out['item_images']) + 1, item_type=key[0], item_no=key[1], color_id=color,
                source='rebrickable', kind=picture_kind('rebrickable', key[0]), local_path=local, url=r['image'], width=None, height=None, fetched_at=None,
                copy_id=None, stock_id=None, caption=None, taken_at=None))
    for (kind, number, prop), values in sorted(properties.items()):
        if len(values) == 1:
            out['item_properties'].append(dict(item_type=kind, item_no=number, key=prop, source='rebrickable',
                value=next(iter(values)), unit='count' if prop == 'pieces' else None, fetched_at=None))
        else:
            transformations.append(dict(table='item_properties', item_type=kind, item_no=number, key=prop, rule='conflicting projection omitted; raw retained'))
    for key, (name, source) in choose_names(items, catalogue_names(Path(catalogue)), name_candidates).items():
        names[key] = name
        out['item_properties'].append(dict(item_type=key[0], item_no=key[1], key='name',
            source=source, value=name, unit=None, fetched_at=None))
        transformations.append(dict(table='item_properties', item_type=key[0], item_no=key[1],
            rule='name mapped', source=source))
    out['items'] = [dict(item_type=k[0], item_no=k[1], name=names.get(k), category=None, year=years.get(k), updated_at=None) for k in sorted(items)]
    for (kind, sid), (key, color, method, status) in sorted(targets.items()):
        entries = evidence[kind, sid]
        if key and key not in items:
            entries = entries + [{'evidence_only_target': {'item_type': key[0], 'item_no': key[1]}}]
            key = None
        out['id_match'].append(dict(source='rebrickable', kind=kind, source_id=sid, item_type=key[0] if key else None,
            item_no=key[1] if key else None, color_id=color, method=method, status=status,
            context=(next(iter(contexts[kind, sid])) if len(contexts[kind, sid]) == 1 else packed(sorted(contexts[kind, sid]))) if contexts[kind, sid] else None,
            evidence_json=packed(entries), decided_at=decided.get((kind, sid))))
    carry_cache(out, web, items, transformations)
    out['item_images']  # Include an empty local image projection in the proof.
    add_evidence_colors(out, app, web, transformations)
    for table in EMPTY:
        if web.get(table):
            raise ValueError(f'{table} is no longer empty: this migration gate needs a new mapping')
        out[table] = []
    out['lots']  # Include empty lots in proof.
    search_properties = defaultdict(list)
    for p in sorted(out['item_properties'], key=lambda p: (p['key'], p['source'])):
        search_properties[p['item_type'], p['item_no']].append(p['value'])
    out['search_index'] = [dict(item_type=r['item_type'], item_no=r['item_no'], name=r['name'],
        properties=' '.join(search_properties[r['item_type'], r['item_no']]) or None) for r in out['items']]
    # Deterministic baseline time: the explicit decision date, never wall time.
    epoch = decisions.get('decided', '1970-01-01') + 'T00:00:00+00:00'
    out['wishlists'] = [dict(id='default', name='Wishlist', note=None, sort=0, archived_at=None, created_at=epoch, bricklink_id=None)]
    entity_keys = {
        'copies': ('id',), 'copy_parts': ('id',),
        'copy_minifigs': ('copy_id', 'item_type', 'minifig_no'),
        'loose_stock': ('id',), 'loose_minifig_parts': ('stock_id', 'item_type', 'item_no', 'color_id', 'spare'),
        'wishlist': ('id',), 'flags': ('id',),
        'item_flags': ('entity_type', 'entity_id', 'flag_id'), 'settings': ('key',), 'lots': ('id',),
    }
    for table in AUDITED:
        for row in out[table]:
            identity = {k: row[k] for k in entity_keys[table]}
            out['events'].append(dict(id=len(out['events']) + 1, entity=table + ':' + packed(identity), field='record',
                old_value=None, new_value=packed(row), at=epoch, via='migration'))
    for table, rows in app.items():
        for r in rows:
            if table in ('bricktracker_sets', 'bricktracker_individual_parts', 'bricktracker_individual_minifigures', 'bricktracker_individual_part_lots'):
                for column in ('purchase_date', 'created_date', 'purchase_price'):
                    if r.get(column) is not None:
                        transformations.append(dict(table=table, lineage=r['_lineage'], column=column, rule='UTC date' if 'date' in column else 'decimal text'))
    listing_rules = {
        'bricktracker_parts': 'typed child/colour/parent identity; source row retained',
        'bricktracker_minifigures': 'typed figure identity; missing joined before re-key',
        'bricktracker_individual_parts': 'typed identity; used condition; explicit state retained',
        'bricktracker_individual_minifigures': 'typed figure identity; status and receipt joined',
        'bricktracker_individual_minifigure_parts': 'typed child/colour identity; source_ref retained',
        'bricktracker_wishes': 'stable rowid; typed item/colour matching; quantity 1; metadata joined before re-key',
    }
    for table, rule in listing_rules.items():
        transformations.extend(dict(table=table, lineage=r['_lineage'], rule=rule) for r in app[table])
    for table in ('price_history', 'minifig_price_history', 'part_price_history', 'price_slots', 'minifig_prices', 'part_prices'):
        transformations.extend(dict(table=table, lineage=r['_lineage'], rule='decimal money; full slot/source/guide; NULL currency kept') for r in web[table])
    return dict(out), transformations


def carry_cache(out, web, items, transformations):
    """Carry the mapping's empty cache without promoting it to collection state."""
    grouped = defaultdict(list)
    for row in web.get('part_image_mappings', []):
        sid = row['part_num']
        if sid:
            grouped[sid].append(row)
            target = 'id_match'
        else:
            sid = str(row['_lineage'])
            out['source_records'].append(dict(source='rebrickable', kind='part-image', source_id=sid,
                payload=packed({'records': [{'table': 'part_image_mappings', 'record': original(row)}]}),
                fetched_at=None, status='legacy'))
            target = 'source_records'
        transformations.append(dict(table='part_image_mappings', lineage=row['_lineage'],
            rule='cache rows carried', target_table=target, source='rebrickable',
            kind='part-image', source_id=sid))
    for sid, rows in sorted(grouped.items()):
        candidates = {r['bricklink_part'] for r in rows if r['bricklink_part']}
        key = ('P', next(iter(candidates))) if len(candidates) == 1 else None
        entries = [{'table': 'part_image_mappings', 'record': original(r)} for r in rows]
        if key and key not in items:
            entries.append({'evidence_only_target': {'item_type': key[0], 'item_no': key[1]}})
            key = None
        timestamps = [date(r['checked_at']) for r in rows if r['checked_at'] is not None]
        out['id_match'].append(dict(source='rebrickable', kind='part-image', source_id=sid,
            item_type=key[0] if key else None, item_no=key[1] if key else None, color_id=None,
            method='part_image_mappings', status='matched' if len(candidates) == 1 else 'to_check' if candidates else 'unmatched',
            context=None, evidence_json=packed(entries), decided_at=max(timestamps) if timestamps else None))


def add_evidence_colors(out, app, web, transformations):
    """Apply the two approved missing-colour definitions, retaining evidence.

    These are BrickLink bridge targets, never numeric Rebrickable fallbacks.
    Other missing colours still fail the final foreign-key proof.
    """
    present = {r['color_id'] for r in out['colors']}
    referenced = {r['color_id'] for rows in out.values() for r in rows
                  if r.get('color_id') is not None}
    for color, source_color in ((0, 9999), (117, 76)):
        if color in present or color not in referenced:
            continue
        bridges = [original(r) for r in web['color_map']
                   if r['bricklink_color_id'] == color]
        if not any(r['color_id'] == source_color for r in bridges):
            raise ValueError(f'Missing approved bridge evidence for BrickLink colour {color}')
        parts = [original(r) for r in app['rebrickable_parts']
                 if r['bricklink_color_id'] == color]
        name = None
        if color == 0:
            if not parts or {r['bricklink_color_name'] for r in parts} != {'(Not Applicable)'}:
                raise ValueError('Missing or conflicting name evidence for BrickLink colour 0')
            name = '(Not Applicable)'
        records = ([dict(table='color_map', record=r) for r in bridges] +
                   [dict(table='rebrickable_parts', record=r) for r in parts])
        sid = f'colors:{color}'
        out['colors'].append(dict(color_id=color, name=name, type=None, rgb=None))
        out['source_records'].append(dict(source='rebrickable', kind='migration', source_id=sid,
            payload=packed(dict(color_id=color, name=name, rule='approved referenced-but-missing colour',
                                records=records)), fetched_at=None, status='evidence'))
        transformations.append(dict(table='colors', color_id=color, name=name,
            rule='colour added from evidence', evidence_source='rebrickable',
            evidence_kind='migration', evidence_source_id=sid,
            color_map_rows=len(bridges), rebrickable_parts_rows=len(parts)))


def price(r, kind, set_key):
    if kind:
        number = r['set_num'] if kind == 'S' else r['bricklink_id']
        key = set_key(number) if kind == 'S' else (kind, number)
    else:
        key = (r['item_type'], r['item_no'])
    slot = r.get('slot')
    condition = r.get('condition') if not kind else 'N' if slot in ('new', 'bricklink_new') else 'U' if slot in ('used', 'bricklink_used') else None
    source = r['source']
    guide = 'valuation' if source == 'brickset' else r.get('guide_type') or {'bricklink_stock': 'stock', 'bricklink': 'sold', 'manual': 'manual'}[source]
    return dict(item_type=key[0], item_no=key[1], color_id=r.get('color_id'), condition=condition, guide=guide,
        slot=slot, region=r.get('region'), currency=r.get('currency'), price=money(r.get('price')), qty=r.get('qty'),
        sold=r.get('sold'), min=money(r.get('min')), max=money(r.get('max')), source='bricklink' if source == 'bricklink_stock' else source,
        observed_at=r.get('observed_at'), error=r.get('last_error'))


def local_picture(row, table, root):
    """Associate named, verified files inside the managed data/images tree.

    Old Rebrickable caches use <set/figure/image_id>.jpg. No URL filename
    inference, filesystem walks, moves or mtime-derived fetch dates.
    """
    candidates = [row.get(column) for column in ('image', 'image_id')]
    folder, identity = {
        'rebrickable_sets': ('sets', 'set'), 'bricktracker_wishes': ('sets', 'set'),
        'rebrickable_minifigures': ('minifigures', 'figure'),
        'rebrickable_parts': ('parts', 'image_id'),
    }[table]
    name = row.get(identity)
    if isinstance(name, str) and name and Path(name).name == name and '..' not in name:
        candidates.append(f'data/images/{folder}/{name}.jpg')
    for value in candidates:
        if not isinstance(value, str) or not value.startswith('data/images/') or '..' in value:
            continue
        path = root / value
        if path.is_file() and path.resolve().is_relative_to((root / 'data/images').resolve()):
            return value
    return None


def validate_joins(app, web, copies):
    """Joins may enrich an entity, never silently discard orphaned user state."""
    figures = {(r['id'], r['figure']) for r in app['bricktracker_minifigures']}
    loose = {r['id'] for r in app['bricktracker_individual_minifigures']}
    wishes = {r['set'] for r in app['bricktracker_wishes']}
    for table, key, available in (
        ('copy_status', 'copy_id', copies), ('copy_valuation', 'copy_id', copies),
        ('loose_minifig_status', 'individual_id', loose), ('loose_minifig_imports', 'individual_id', loose),
        ('wish_meta', 'set', wishes),
    ):
        if any(r[key] not in available for r in web[table]):
            raise ValueError('Orphaned user state in ' + table)
    if any((r['copy_id'], r['figure']) not in figures for r in web['minifig_missing']):
        raise ValueError('Orphaned whole-figure missing state')
    # Verify the approved derived-state drop with the original source identities
    # before any re-keying. This is status.py's sorted, non-spare convention.
    missing = defaultdict(list)
    for r in sorted(app['bricktracker_parts'], key=lambda r: (r['id'], r['figure'] or '', r['part'], r['color'], r['spare'])):
        if r['missing'] and not r['spare']:
            missing[r['id']].append([r[k] for k in ('figure', 'part', 'color', 'spare', 'missing')])
    for r in sorted(web['minifig_missing'], key=lambda r: (r['copy_id'], r['figure'])):
        missing[r['copy_id']].append(['figure', r['figure'], r['missing']])
    checked = {r['id']: bool(r.get('status_set_checked')) for r in app['bricktracker_set_statuses']}
    for r in web['copy_check_state']:
        if r['copy_id'] not in copies or bool(r['checked']) != checked.get(r['copy_id'], False) or json.loads(r['missing']) != missing[r['copy_id']]:
            raise ValueError('Derived copy_check_state differs from user inventory state')
