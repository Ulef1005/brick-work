"""Read-back checks against an independently rebuilt read-only projection."""
from collections import Counter
import hashlib
import json
from pathlib import Path

from .projection import packed

# The reviewed live collection, re-pinned for the 4.6 cutover (2026-10-18): two BrickLink set price lookups
# since the 13 Oct review (6274-1, 6276-1, 14 Oct) each added an item, a price, a source record and a search row.
APPROVED_COUNTS = dict(colors=216, items=4619, inventory_lines=457, id_match=5060,
 copies=195, copy_parts=21832, copy_minifigs=449, loose_stock=355, loose_minifig_parts=1287,
 lots=0, storages=2, purchase_locations=1, flags=8, item_flags=278, wishlist=182, wishlists=1,
 price_observations=3625, price_current=3208, price_watch=506, fetch_log=374, settings=9,
 jobs=0, orders=0, order_documents=0, order_lines=0, line_receipts=0, line_receipt_log=0,
 allocations=0, identifications=5, identification_actions=1, import_receipts=273,
 instruction_files=0, match_history=0, sources=6, source_records=14091,
 item_properties=9171, item_images=8976, search_index=4619, events=24595,
 source_freshness=18, schema_meta=1)


def checksum(rows):
    # JSON distinguishes NULL, strings, integers and floats; byte lengths delimit
    # rows and strings unambiguously. Sorting preserves duplicate multiplicity.
    digest = hashlib.sha256()
    for data in sorted(packed(row).encode('utf-8') for row in rows):
        digest.update(len(data).to_bytes(8, 'big'))
        digest.update(data)
    return digest.hexdigest()


def verify(db, expected, transformations, *, approved=False):
    expected = dict(expected, schema_meta=[dict(version='3.2')])
    cache_rows = [r for r in transformations if r['rule'] == 'cache rows carried']
    cache_additions = Counter(table for table, source, kind, sid in {
        (r['target_table'], r['source'], r['kind'], r['source_id']) for r in cache_rows})
    absent_images = sum(r['rule'] == 'image URL retained raw; local file absent' for r in transformations)
    tables = {}
    entities = {}
    for table, rows in sorted(expected.items()):
        actual = [dict(r) for r in db.execute(f'SELECT * FROM "{table}"')]
        source_hash, target_hash = checksum(rows), checksum(actual)
        count = APPROVED_COUNTS[table] + cache_additions[table] if approved else len(rows)
        if approved and table == 'item_properties':
            count += sum(r['rule'] == 'name mapped' for r in transformations)
        if approved and table == 'item_images':
            count -= absent_images
        tables[table] = dict(expected=count, projected=len(rows), actual=len(actual),
            source_checksum=source_hash, target_checksum=target_hash,
            checksum_ok=source_hash == target_hash, count_ok=count == len(rows) == len(actual),
            source_non_null={k: sum(r.get(k) is not None for r in rows) for k in (rows[0] if rows else {})},
            target_non_null={k: sum(r.get(k) is not None for r in actual) for k in (actual[0] if actual else {})},
            source_state_sums={k: sum(r[k] for r in rows if isinstance(r.get(k), int))
                               for k in ('quantity', 'missing', 'damaged', 'checked') if rows and k in rows[0]},
            target_state_sums={k: sum(r[k] for r in actual if isinstance(r.get(k), int))
                               for k in ('quantity', 'missing', 'damaged', 'checked') if actual and k in actual[0]})
        if table in ('copies', 'copy_parts', 'copy_minifigs', 'loose_stock', 'loose_minifig_parts',
                     'price_observations', 'price_current', 'wishlist', 'flags', 'item_flags'):
            # Anonymous row digests are the content proofs; no private values
            # (notes, prices, UUIDs) are reproduced in the human report.
            entities[table] = {'source': sorted(checksum([r]) for r in rows),
                               'target': sorted(checksum([r]) for r in actual)}
    integrity = [r[0] for r in db.execute('PRAGMA integrity_check')]
    foreign_keys = [dict(r) for r in db.execute('PRAGMA foreign_key_check')]
    reviews = [r for r in expected['id_match'] if r['status'] in ('to_check', 'unmatched')]
    review_counts = Counter((r['kind'], r['status']) for r in reviews)
    return dict(ok=integrity == ['ok'] and not foreign_keys and all(
        r['count_ok'] and r['checksum_ok'] for r in tables.values()), tables=tables,
        unnamed_items={kind: sum(r['item_type'] == kind and not r['name'] for r in expected['items'])
                       for kind in sorted({r['item_type'] for r in expected['items']})},
        integrity_check=integrity, foreign_key_check=foreign_keys,
        entity_checksums=entities, transformations=transformations, reviews=reviews,
        cache_rows_carried=cache_rows,
        wishlist_mapping=dict(legacy=len(expected['wishlist']), migrated=tables['wishlist']['actual'],
                              part_colour_keys=sum(r['color_id'] is not None for r in expected['wishlist']),
                              checksum_columns=list(expected['wishlist'][0]) if expected['wishlist'] else []),
        colors_added_from_evidence=[r for r in transformations if r['rule'] == 'colour added from evidence'],
        review_counts=[dict(kind=k, status=s, count=n) for (k, s), n in sorted(review_counts.items())],
        count_basis='approved mapping, with 18 freshness defaults, two evidence colours and two evidence records; absent local images omitted; cache rows carried' if approved else 'synthetic input projection',
        drops={'empty_tables': ['rebrickable_colors', 'sets_old', 'wishlist_old', 'minifigures_old', 'inventory_old',
                               'missing_old', 'house_loose_transfers'],
               'process': ['schema_version', 'color_map_refresh', 'price_settings.id', 'price_settings.changed_at'],
               'derived': ['copy_check_state']})


def write(report, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'proof.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    lines = ['# Brick Work migration proof', '', 'Result: ' + ('PASS' if report['ok'] else 'FAIL'), '',
             report['count_basis'], '', '| Table | Expected | Actual | Checksum OK |', '|---|---:|---:|:---:|']
    lines.extend(f'| {t} | {r["expected"]} | {r["actual"]} | {r["checksum_ok"]} |' for t, r in report['tables'].items())
    lines += ['', f'Wishlist mapping: {report["wishlist_mapping"]["legacy"]} legacy → {report["wishlist_mapping"]["migrated"]} rows; {report["wishlist_mapping"]["part_colour_keys"]} colour keys. Checksums include id, colour and quantity.', f'Integrity: {report["integrity_check"]}; FK violations: {len(report["foreign_key_check"])}.',
              f'Runtime: {report["runtime_seconds"]:.3f} seconds; output: {report["output_bytes"]} bytes.',
              '', '| Kind | Status | Count |', '|---|---|---:|']
    lines.extend(f'| {r["kind"]} | {r["status"]} | {r["count"]} |' for r in report['review_counts'])
    lines += ['', 'Names mapped: BrickLink catalogue first, unambiguous retained Rebrickable name second.',
              '', '| Type | Still without a name |', '|---|---:|']
    lines.extend(f'| {kind} | {count} |' for kind, count in report['unnamed_items'].items())
    lines += ['', '## Colours added from evidence', '',
              '| BrickLink colour | Name | Colour-map rows | Part-cache rows | Evidence record |',
              '|---|---|---:|---:|---|']
    lines.extend(f'| {r["color_id"]} | {r["name"] if r["name"] is not None else "NULL"} | '
                 f'{r["color_map_rows"]} | {r["rebrickable_parts_rows"]} | '
                 f'rebrickable / migration / {r["evidence_source_id"]} |'
                 for r in report['colors_added_from_evidence'])
    lines += ['', '## Cache rows carried', '',
              '| Source table | Lineage | Target | Source | Kind | Source id |',
              '|---|---:|---|---|---|---|']
    lines.extend(f'| {r["table"]} | {r["lineage"]} | {r["target_table"]} | {r["source"]} | '
                 f'{r["kind"]} | {r["source_id"]} |' for r in report['cache_rows_carried'])
    lines += ['', 'Full row checksums, transformed lineages, every review and approved drops are in proof.json.',
              'Raw legacy envelopes preserve SQLite field types and NULLs; original API replies and absent picture bytes are not claimed reconstructed.',
              'Freshness defaults add 18 new configuration rows to the mapping’s historical zero.', '']
    (directory / 'proof.md').write_text('\n'.join(lines))


def dropped_columns(app_path, web_path):
    """Measure every approved drop without publishing source field values."""
    from contextlib import closing
    from .idmatch import open_readonly
    register=[]
    specs = [('app', app_path, {t: None for t in ('rebrickable_colors', 'sets_old', 'wishlist_old', 'minifigures_old', 'inventory_old', 'missing_old')}),
             ('web', web_path, {'house_loose_transfers': None,
                'copy_check_state': None, 'color_map_refresh': None, 'schema_version': None,
                'price_settings': ('id', 'changed_at')})]
    for name, path, tables in specs:
        with closing(open_readonly(path)) as db:
            for table, columns in tables.items():
                columns = columns or tuple(r['name'] for r in db.execute(f'PRAGMA table_info("{table}")'))
                total=db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                for column in columns:
                    fill=db.execute(f'SELECT count("{column}") FROM "{table}"').fetchone()[0]
                    reason='derived, independently verified' if table=='copy_check_state' else 'process' if table in ('color_map_refresh','schema_version','price_settings') else 'empty'
                    if reason=='empty' and total:
                        raise ValueError('Approved empty drop now contains data: ' + table)
                    register.append(dict(database=name,table=table,column=column,rows=total,non_null=fill,reason=reason))
    return register
