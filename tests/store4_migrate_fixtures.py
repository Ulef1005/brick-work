"""A synthetic 3.3 store for the migration writer (design 8.11, issue #109 M.7b), built at test time from the real 3.3 schema.

Nothing here comes from a real collection. It is meant to be migrated against the fixture catalogue of `store4_mint_fixtures`
(`build_catalogue`): sets `2070-1`, parts `3001`, `3023`, `970c03` (BrickLink `970c00`), the sticker sheet `003402` with its three
BrickLink ids, the figure `fig-000004` (BrickLink `syn-fig-0004` through the composition row), colours 0, 1, 3, 5, 8, 11, 72, 77.
Everything else (set `5008074-1`, figure `cas999`, gear `gear01`, colour 86) has no catalogue candidate: a local item or colour.

`build_33(path)` returns the ids the tests refer to."""
import json
from pathlib import Path
import sqlite3

from brickwork.core.connect import connect

BL_LINE = 466                                                 # inventory_lines.id of the BrickLink line the Rebrickable source_ref equals


def ins(db, table, **columns):
    cursor = db.execute(f'INSERT INTO {table}({", ".join(columns)}) VALUES({", ".join("?" * len(columns))})', tuple(columns.values()))
    return cursor.lastrowid


def build_33(path):
    path = Path(path)
    db = connect(path)
    db.row_factory = sqlite3.Row

    def item(item_type, item_no, name=None, category=None, year=None):
        db.execute('INSERT OR IGNORE INTO items(item_type, item_no, name, category, year) VALUES(?, ?, ?, ?, ?)',
                   (item_type, item_no, name, category, year))

    for color_id, name, kind, rgb in ((0, '(Not Applicable)', 'Solid', None), (1, 'White', 'Solid', 'FFFFFF'), (3, 'Yellow', 'Solid', 'F2CD37'),
                                      (5, 'Red', 'Solid', 'C91A09'), (11, 'Black', 'Solid', '05131D'), (86, 'Light Bluish Gray', 'Solid', 'A0A5A9'),
                                      (87, 'Trans-Clear Syn', 'Transparent', 'EEEEEE')):
        ins(db, 'colors', color_id=color_id, name=name, type=kind, rgb=rgb)
    for key in (('S', '2070-1', 'Ring Me Rabbit', None, 1987), ('S', '5008074-1', 'Syn BrickLink set', 'Syn category', 2026),
                ('P', '3001', 'Brick 2 x 4'), ('P', '3023', 'Plate 1 x 2'), ('P', '970c00', 'Hips and Legs'), ('P', '3626ap01', 'Head'),
                ('P', '310.3stk01', 'Sticker sheet A'), ('P', '311.1stk01', 'Sticker sheet B'), ('M', 'syn-fig-0004', 'Man'),
                ('M', 'cas999', 'Syn figure'), ('G', 'gear01', 'Syn gear'), ('G', 'gear02', 'Syn gear in a figure'), ('G', '3001', 'Syn gear 3001'), ('G', '2071c01pb01', 'Syn card'), ('I', 'syn-i1', 'Syn instructions'),
                ('?', 'rebrickable:3023'), ('?', 'rebrickable:fig-999999')):
        item(*key)
    # ---- places ----
    ins(db, 'storages', id='st1', name='Shelf A', type='Shelf')
    ins(db, 'storages', id='st2', name='Weird box', type='Weird', parent_id='st1', note='inside A')
    ins(db, 'purchase_locations', id='p1', name='Corner shop', kind='Shop')
    ins(db, 'lots', id='l1', name='Lot one', created_date='2026-03-01T10:00:00+00:00', storage_id='st1', purchase_location_id='p1',
        purchase_price='5.00')                                        # a price without a currency
    ins(db, 'lots', id='l2', name='Lot two', purchase_currency='USD')  # a currency without a price
    for flag_id, name, kind in (('f_status', 'Checked', 'status'), ('f_tag', 'for sale', 'tag'), ('f_owner', 'Ulf', 'owner')):
        ins(db, 'flags', id=flag_id, name=name, kind=kind, shown_on_grid=1)
    # ---- copies ----
    ins(db, 'copies', id='copy-bl', item_type='S', set_no='5008074-1', condition='U', completeness='C', completeness_source='manual',
        storage_id='st1', purchase_location_id='p1', purchase_date='2026-01-01', purchase_price='9.99', purchase_currency='EUR',
        current_value='20.00', current_value_currency='EUR', pinned=1, updated_at='2026-10-14T18:00:57+00:00')
    ins(db, 'copies', id='copy-proj', item_type='S', set_no='2070-1', condition='N', completeness='S', purchase_price='12.50',
        current_value='30.00', note='imported', updated_at='2026-10-12T00:00:00+00:00')          # prices without a currency
    ins(db, 'copies', id='copy-upd', item_type='S', set_no='2070-1', updated_at='2026-08-08T08:00:00+00:00')   # no event, an own updated_at
    ins(db, 'copies', id='copy-none', item_type='S', set_no='2070-1')                                          # no event, no updated_at
    ins(db, 'copies', id='copy-imp', item_type='S', set_no='5008074-1', updated_at='2026-10-12T00:00:00+00:00')   # imported from Rebrickable
    ins(db, 'copies', id='copy-m', item_type='S', set_no='2070-1', updated_at='2026-09-09T09:00:00+00:00')
    # BrickLink lines: the extras of design 8.5 (466 is the id a Rebrickable source_ref equals below)
    for line_id, parent, child, color, quantity, extra, source in (
            (BL_LINE, '5008074-1', '3001', 5, 5, 1, 'bricklink'), (467, '5008074-1', '3001', 11, 4, 2, 'bricklink'),
            (468, '5008074-1', '3023', 5, 3, 1, 'bricklink'), (469, '5008074-1', '3023', 11, 2, 2, 'bricklink'),
            (470, '2070-1', '3001', 5, 1, 1, 'rebrickable-translated')):
        ins(db, 'inventory_lines', id=line_id, parent_item_type='S', parent_item_no=parent, child_item_type='P', child_item_no=child,
            color_id=color, quantity=quantity, extra_quantity=extra, source=source, fetched_at='2026-10-14T18:00:58+00:00')

    def part(copy_id, item_type, item_no, color, quantity=1, *, spare=0, missing=0, damaged=0, checked=0, parent=None, source_ref=None):
        return ins(db, 'copy_parts', copy_id=copy_id, parent_minifig_type=parent and parent[0], parent_minifig=parent and parent[1],
                   item_type=item_type, item_no=item_no, color_id=color, spare=spare, quantity=quantity, missing=missing, damaged=damaged,
                   checked=checked, source_ref=source_ref)

    ids = {}
    ids['bl_ref'] = part('copy-bl', 'P', '3001', 5, 5, source_ref=BL_LINE)
    ids['bl_spare'] = part('copy-bl', 'P', '3001', 5, 1, spare=1, source_ref=BL_LINE)             # the spare row stays
    ids['bl_cap'] = part('copy-bl', 'P', '3001', 11, 4, missing=3, damaged=1, checked=1, source_ref=467)   # missing is capped at 2
    ids['bl_key'] = part('copy-bl', 'P', '3023', 5, 3)                                            # no source_ref: matched by key
    ids['bl_drop'] = part('copy-bl', 'P', '3023', 11, 2, missing=1, source_ref=469)               # reaches 0: dropped
    ids['proj_ref'] = part('copy-proj', 'P', '3001', 5, 2, source_ref=BL_LINE)                    # a Rebrickable id that equals line 466
    ids['dup1'] = part('copy-proj', 'P', '3023', 5, 1, missing=1)
    ids['dup2'] = part('copy-proj', 'P', '3023', 5, 1, checked=1)                                 # the duplicate line (Q7)
    ids['stk_a'] = part('copy-proj', 'P', '310.3stk01', None, 1)
    ids['stk_b'] = part('copy-proj', 'P', '311.1stk01', None, 1)                                  # the sticker-sheet pair in one copy
    ids['q_part'] = part('copy-proj', '?', 'rebrickable:3023', 1, 2)                              # a ? part
    ids['legs'] = part('copy-proj', 'P', '970c00', 11, 1)
    ids['head_null'] = part('copy-proj', 'P', '3626ap01', None, 1)                                # colour NULL -> 1
    ids['comp1'] = part('copy-proj', 'P', '3626ap01', 3, 1, checked=1, parent=('M', 'syn-fig-0004'))   # figure component rows
    ids['comp2'] = part('copy-proj', 'P', '970c00', 11, 1, parent=('M', 'syn-fig-0004'))
    ids['comp_gear'] = part('copy-proj', 'G', 'gear02', None, 1, parent=('M', 'syn-fig-0004'))       # a component copy_part cannot hold
    ids['m_dup'] = part('copy-proj', 'M', 'syn-fig-0004', None, 1)                               # a manual figure line beside the canonical row
    ins(db, 'copy_minifigs', copy_id='copy-proj', item_type='M', minifig_no='syn-fig-0004', quantity=1, missing=0)
    ins(db, 'copy_minifigs', copy_id='copy-proj', item_type='?', minifig_no='rebrickable:fig-999999', quantity=2, missing=1,
        updated_at='2026-10-01T00:00:00+00:00')                                                    # a ? figure
    ids['m_line'] = part('copy-m', 'M', 'cas999', 0, 2, missing=1)                                # a figure as a copy_parts line
    ids['g_line'] = part('copy-m', 'G', 'gear01', None, 1)
    ids['g_nosupport'] = part('copy-m', 'G', '3001', None, 1)                                      # P 3001 exists, but not in 2070-1's list
    ids['g_crossed'] = part('copy-proj', 'G', '2071c01pb01', None, 1)                              # filed as gear, a part of 2070-1 (rule 6)
    ids['imp_a'] = part('copy-imp', 'P', '3001', 5, 5, source_ref=9001)                            # Rebrickable inventory ids of the 3.2 -> 3.3 import
    ids['imp_b'] = part('copy-imp', 'P', '3023', 5, 3, source_ref=BL_LINE + 1000)
    part('copy-upd', 'P', '3001', 5, 1)
    # ---- loose stock ----
    ins(db, 'loose_stock', id='s-part', item_type='P', item_no='3001', color_id=5, quantity=10, condition='U', storage_id='st1', lot_id='l1',
        purchase_location_id='p1', purchase_price='2.00', note='loose')                            # a price without a currency, no timestamps
    ins(db, 'loose_stock', id='s-null', item_type='P', item_no='3001', color_id=None, quantity=3, condition='D',
        created_at='2026-05-05T05:00:00+00:00', updated_at='2026-05-06T05:00:00+00:00')
    ins(db, 'loose_stock', id='s-fig', item_type='M', item_no='syn-fig-0004', quantity=1, missing=1, damaged=0, checked=0,
        created_at='2026-06-06T06:00:00+00:00')
    ins(db, 'loose_stock', id='s-ins', item_type='I', item_no='syn-i1', quantity=1, condition='N')
    for item_type, item_no, color, spare in (('P', '3626ap01', 3, 0), ('P', '970c00', 11, 0)):
        ins(db, 'loose_minifig_parts', stock_id='s-fig', item_type=item_type, item_no=item_no, color_id=color, spare=spare, quantity=1,
            missing=0, damaged=0, checked=0)
    # ---- wishes, flags ----
    ins(db, 'wishlists', id='w2', name='Second list', sort=1, created_at='2026-04-04T04:00:00+00:00')
    w1 = ins(db, 'wishlist', item_type='P', item_no='3001', color_id=5, quantity=2, max_price='1.00', condition='new', note='want',
             added_at='2026-02-02T02:00:00+00:00')                                                # a limit without a currency
    w2 = ins(db, 'wishlist', item_type='S', item_no='2070-1', quantity=1, list_id='w2')
    ids['wishes'] = (w1, w2)
    db.execute("INSERT INTO item_flags(entity_type, entity_id, flag_id) VALUES('copy', 'copy-bl', 'f_status'), ('stock', 's-part', 'f_tag'), "
               "('wishlist', ?, 'f_owner')", (str(w1),))
    # ---- own photo, instruction file ----
    ins(db, 'item_images', item_type='S', item_no='2070-1', source='manual', kind='own', local_path='data/images/own/a.jpg', width=10, height=20,
        copy_id='copy-proj', caption='front', fetched_at='2026-07-07T07:00:00+00:00')
    ins(db, 'item_images', item_type='S', item_no='2070-1', source='bricklink', kind='photo', local_path='data/images/bricklink/x.jpg')
    ins(db, 'instruction_files', item_type='S', set_no='2070-1', path='data/instructions/a.pdf')
    # ---- prices ----
    def obs(item_type, item_no, color, guide, price, currency, observed, *, condition='N', error=None, source='bricklink'):
        return ins(db, 'price_observations', item_type=item_type, item_no=item_no, color_id=color, condition=condition, guide=guide, slot='6',
                   region='eu', currency=currency, price=price, qty=3, sold=2, min='0.05', max='0.20', source=source, observed_at=observed, error=error)

    o1 = obs('P', '3001', 5, 'sold', '0.10', None, '2026-10-01T00:00:00+00:00')                 # a price without a currency
    o2 = obs('P', '3001', 5, 'sold', '0.12', 'EUR', '2026-10-02T00:00:00+00:00')
    o3 = obs('P', '3001', 5, 'sold', '0.13', 'EUR', '2026-10-03T00:00:00+00:00', source='manual', error='undone')
    o4 = obs('P', '3023', None, 'stock', None, 'EUR', None, error='SIGNATURE_INVALID: Invalid Signature')
    o5 = obs('S', '2070-1', None, 'sold', '9.00', 'EUR', '2026-10-04T00:00:00+00:00', condition='U')
    for observation, key in ((o1, ('P', '3001', 5, 'N', 'sold', '6', 'eu', None)), (o2, ('P', '3001', 5, 'N', 'sold', '6', 'eu', 'EUR')),
                             (o4, ('P', '3023', None, 'N', 'stock', '6', 'eu', 'EUR')), (o5, ('S', '2070-1', None, 'U', 'sold', '6', 'eu', 'EUR'))):
        db.execute('INSERT INTO price_current VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)', (*key, observation))
    ids['obs'] = (o1, o2, o3, o4, o5)
    ins(db, 'price_watch', item_type='P', item_no='3001', color_id=5, condition='N', origin='copy', first_seen='2026-09-01', last_fetch_at='2026-10-02')
    # ---- keys, tokens, freshness ----
    ins(db, 'source_keys', source='bricklink', ciphertext='v1:AAAA', saved_at='2026-01-01T00:00:00Z')
    ins(db, 'source_key_previous', source='bricklink', ciphertext='v1:BBBB', saved_at='2025-12-01T00:00:00Z')
    ins(db, 'api_tokens', id='tok1', name='cli', hash='hash1', scopes='read', created_at='2026-01-01T00:00:00Z')
    # ---- settings ----
    priority = {'identity': {'*': ['bricklink:local', 'bricklink:api']}, 'inventory': {'*': ['bricklink:subsets', 'rebrickable']},
                'matching': {'*': ['rebrickable', 'part_resolutions', 'manual']}, 'pictures': {'P': ['rebrickable'], 'M': ['bricklink'], '*': ['bricklink']},
                'metadata': {'S': ['brickset']}, 'market_price': {'*': ['bricklink']}}
    for key, value in (('bricklink_currency', 'USD'), ('bricklink_region', 'us'), ('incomplete_discount_pct', '25'), ('display_currency', 'GBP'),
                       ('repair_shipping', '4.00'), ('retail_country', 'AT'), ('import_order:P', '["metadata", "identity"]'),
                       ('import_order:M', '["identity"]'), ('source_priority', json.dumps(priority)),
                       ('checker:copy-bl', '{"id": "x", "order": ["p:1"]}'), ('source:used:bricklink:2026-10-14', '77'),
                       ('source:budget:brickset', '100'), ('sync:rebrickable:link', '{"user": "ulf", "list": "7"}'),
                       ('sync:rebrickable:baseline', '{"remote": {}}'), ('maintenance:database_check', '2026-10-01'), ('mystery_key', 'x')):
        db.execute('INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))
    # ---- identity decisions, orders, history (listed, not carried) ----
    for kind, source_id, status, method in (('part', 'p1', 'manual', 'manual'), ('minifig', 'fig1', 'manual', 'ulf-2026-10-12'),
                                            ('part', 'p2', 'to_check', 'review'), ('part', 'p3', 'unmatched', 'review'), ('part', 'p4', 'matched', 'match')):
        ins(db, 'id_match', source='rebrickable', kind=kind, source_id=source_id, item_type='P', item_no='3001', color_id=5, method=method,
            status=status, evidence_json='{}')
    order = ins(db, 'orders', bricklink_order_id='123', store='Shop', cost='10.00', currency='EUR')
    document = ins(db, 'order_documents', order_id=order, source='xml', digest='d1', phase='saved')
    line = ins(db, 'order_lines', order_id=order, document_id=document, line_no=1, item_type='P', item_no='3001', color_id=5, qty=2, state='confirmed')
    ins(db, 'allocations', order_id=order, line_id=line, kind='loose_part', qty=2, state='applied', target_type='stock', target_stock_id='s-part',
        part_type='P', part='3001', color=5)
    ins(db, 'match_history', at='2026-10-05T00:00:00Z', kind='take', source_stock_id='s-part', copy_id='copy-bl', quantity=1)
    ins(db, 'identifications', id='ident1', created_at='2026-10-06T00:00:00Z', has_thumb=0, candidates='[]')
    ins(db, 'exchange_rates', currency='CHF', per_eur='0.95', as_of='2026-10-01', source='manual')
    # ---- events: the earliest one per row names the timestamp (design 8.9) ----
    for entity, field, at in (('copy:copy-bl', 'created', '2026-10-14T18:00:57.398845+00:00'), ('copy:copy-bl', 'edit', '2026-10-20T00:00:00+00:00'),
                              ('copies:{"id":"copy-proj"}', 'record', '2026-10-12T00:00:00+00:00'),
                              ('flags:{"id":"f_status"}', 'record', '2026-10-12T00:00:00+00:00'),
                              ('storages:{"id":"st1"}', 'record', '2026-10-12T00:00:00+00:00'),
                              ('lots:{"id":"l1"}', 'record', '2026-10-12T00:00:00+00:00'),
                              ('loose_stock:{"id":"s-part"}', 'record', '2026-10-12T00:00:00+00:00'),
                              ('wishlist:{"id":%d}' % w2, 'record', '2026-10-12T00:00:00+00:00'),
                              ('copy_minifigs:{"copy_id":"copy-proj","item_type":"M","minifig_no":"syn-fig-0004"}', 'record', '2026-10-12T00:00:00+00:00'),
                              ('bw_add', 'receipt', '2026-10-01T00:00:00+00:00')):
        db.execute("INSERT INTO events(entity, field, new_value, at, via) VALUES(?, ?, '{}', ?, 'app')", (entity, field, at))
    db.commit()
    db.execute('PRAGMA journal_mode=DELETE')
    db.close()
    return ids
