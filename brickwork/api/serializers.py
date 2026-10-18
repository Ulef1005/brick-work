"""Public API field selection and adapters; browser projections stay unchanged."""
import json

from ..core.api_reads import serialize
from ..core.collection_prices import dated
from ..core.sources.base import now


# Explicit allowlists prevent browser-only decorations from becoming API fields.
FIELDS = {
    'Created': ['ids'],
    'BulkResult': 'applied skipped dry_run event_id'.split(),
    'LooseFigureParts': ['parts'],
    'Receipt': ['event_id','message'],
    'ImportPlan': 'id created_at source schema fresh summary unresolved rows'.split(),
    'ImportApplied': 'already_applied counts'.split(),
    'Deleted': ['id','archived'],
    'CatalogueItem': 'item_type item_no name year owned wished category'.split(),
    'CatalogueStatus': 'loaded imported_at items'.split(),
    'Color': 'color_id name type rgb'.split(),
    'Item': 'item_type item_no name category year updated_at image_id unresolved owned properties'.split(),
    'ItemDetail': 'item properties counts copies stock wishes prices inventory matches'.split(),
    'InventoryLine': 'child_item_type child_item_no name color_id quantity extra_quantity source'.split(),
    'UsedIn': 'copy_id item_type item_no name quantity missing color_id'.split(),
    'Image': 'id item_type item_no color_id source kind width height fetched_at copy_id stock_id caption content_url'.split(),
    'Copy': 'id item_type item_no name condition completeness completeness_source storage_id purchase_location_id purchase_date purchase_price purchase_currency note current_value current_value_currency pinned flags missing damaged partout updated_at archived_at etag image_id'.split(),
    'Stock': 'id item_type item_no name color_id quantity condition storage_id lot_id purchase_location_id purchase_date purchase_price purchase_currency note created_at updated_at archived_at missing damaged flags merged_ids etag image_id'.split(),
    'Wishlist': 'id name note sort archived_at created_at bricklink_id count'.split(),
    'Wish': 'id list_id item_type item_no name color_id quantity qty_filled qty_filled_source qty_filled_manual max_price max_price_currency condition note added_at updated_at archived_at under_max current_price flags etag image_id'.split(),
    'CopyPart': 'id copy_id parent_minifig_type parent_minifig item_type item_no name color_id spare quantity missing damaged checked'.split(),
    'CopyFigure': 'item_type minifig_no name quantity missing parts_lines parts_missing'.split(),
    'LooseFigurePart': 'stock_id item_type item_no color_id spare quantity missing damaged checked'.split(),
    'Completeness': 'stored completeness_source derived checked missing damaged missing_figures'.split(),
    'CheckState': 'session rows'.split(),
    'Gap': 'copy_id item_type item_no name color_id target target_id need unresolved'.split(),
    'Match': 'source_id copy_id target target_id item_type item_no color_id have suggested completes'.split(),
    'MinifigureRow': 'item_no name theme year quantity in_sets missing damaged image_id'.split(),
    'Unresolved': 'source kind source_id item_type item_no candidates reference_url image'.split(),
    'IdMatch': 'source kind source_id item_type item_no color_id method status decided_at'.split(),
    'InstructionFile': 'id item_type item_no name label added_at content_url archived_at'.split(),
    'PriceObservation': 'id item_type item_no color_id condition guide slot region currency price qty sold min max source observed_at error'.split(),
    'PriceCurrent': 'observation age_days stale'.split(),
    'ItemPrices': 'current records'.split(),
    'StaleItem': 'item_type item_no name color_id condition source_table'.split(),
    'Storage': 'id name type parent_id parent_name note copies entries pieces lots figures part_lots archived_at'.split(),
    'StorageDetail': 'location rows'.split(),
    'Lot': 'id name note created_date storage_id purchase_location_id purchase_date purchase_price purchase_currency archived_at entries quantity'.split(),
    'LotDetail': 'lot rows'.split(),
    'Place': 'archived_at id name kind count totals orders last_used'.split(),
    'Flag': 'archived_at id name kind shown_on_grid count'.split(),
    'OrderImportResult': 'order_id document_id duplicate event_id'.split(),
    'OrderReview': 'id line available destinations'.split(),
    'Allocation': 'id confirm_id order_id line_id qty state target_type kind copy_id target_copy_id target_stock_id part_type part color ref figure_type figure spare intent_before intent_after created_at applied_at undone_at hold_reason error'.split(),
    'OrderHistory': 'id receipt undone undo_available at via actor'.split(),
    'Order': 'id bricklink_order_id store seller date_ordered status cost currency lines received'.split(),
    'OrderDetail': 'order documents lines'.split(),
    'Event': 'actor id entity field old_value new_value at via undoable undone'.split(),
    'Job': 'id source kind item_type item_no state attempts retry_at error created_at updated_at steps interrupted'.split(),
    'JobStep': 'name position state source error error_code retry_at'.split(),
    'Source': 'source name kind enabled key budget used_today last_success last_error'.split(),
    'KeyState': 'configured origin saved_at'.split(),
    'Settings': 'retail_country bricklink_region bricklink_currency incomplete_discount_pct source_priority import_order freshness repair display_currency'.split(),
    'ExchangeRate': 'currency per_eur as_of source'.split(),
    'EcbResult': 'as_of updated kept_manual'.split(),
    'Statistics': ['completeness', 'theme', 'storage', 'purchase place'],
    'DatabaseCheck': 'integrity_check foreign_key_check row_counts'.split(),
    'Identification': 'id created_at has_thumb missing_count candidates archived_at'.split(),
    'RankingRow': 'id group items rank reasons missing_count missing_figures missing_parts original_gap stock_used unresolved_items display_ratio_width complete_quote listing value_when_complete valuation_basis breakdown repair_cost gross_gain net_gain ratio ratio_width ratio_overflow item_type item_no name condition completeness completeness_source storage_id purchase_location_id purchase_date purchase_price purchase_currency note current_value current_value_currency pinned missing damaged updated_at archived_at'.split(),
    'Version': 'api app schema read_only features'.split(),
    'ColorSyncResult': ['colors', 'added'],
    'JobList': ['jobs', 'skipped'],
    'KeyTest': 'source ok checked_at'.split(),
    'SyncStatus': 'source label credentials link last_pull last_send waiting'.split(),
    'SyncList': 'id name sets'.split(),
    'SyncPlan': 'id created_at direction source link rows unmatched summary note'.split(),
    'SyncApplied': 'already_applied counts'.split(),
    'SyncSent': 'plan counts rows note'.split(),
    'SyncCredentials': 'source user key'.split(),
    'UndoResult': 'undone_event_id event_id already_undone'.split(),
}

NESTED = {
    'LooseFigureParts': {'parts': ['LooseFigurePart']},
    'ItemDetail': {'item': 'Item', 'copies': ['Copy'], 'stock': ['Stock'], 'wishes': ['Wish'], 'prices': ['PriceCurrent'], 'inventory': ['InventoryLine'], 'matches': ['IdMatch']},
    'PriceCurrent': {'observation': 'PriceObservation'},
    'ItemPrices': {'current': ['PriceCurrent'], 'records': ['PriceObservation']},
    'StorageDetail': {'location': 'Storage'},
    'LotDetail': {'lot': 'Lot', 'rows': ['Stock']},
    'OrderDetail': {'order': 'Order'},
    'Job': {'steps': ['JobStep']},
    'JobList': {'jobs': ['Job']},
    'Source': {'key': 'KeyState'},
}


def public(value, shape, secrets=None):
    """Select declared fields after adapting meanings, then serialize primitives.

    The secret list is read once per response and passed to every row and nested shape.
    """
    if value is None:
        return None
    if secrets is None:
        from ..core.secrets import secret_values
        secrets = secret_values()
    if isinstance(shape, list):
        return [public(row, shape[0], secrets) for row in value]
    row = dict(value)
    if 'image_id' in FIELDS[shape]:
        row['image_id'] = row.get('image')
    if shape == 'CatalogueItem' and isinstance(row.get('owned'), bool):
        row['owned'] = int(row['owned'])
    if shape == 'Wish':
        state = row.get('max_state')
        row['under_max'] = state == 'under' if state in ('under', 'over') else None
        row['current_price'] = (row.get('display_price') or {}).get('price')
    elif shape == 'PriceCurrent':
        observation = dict(row, id=row['observation_id'])
        stamp = dated(row.get('observed_at'))
        row = dict(observation=observation,
                   age_days=(now() - stamp).days if stamp else None,
                   stale=row.get('stale', False))
    elif shape == 'ItemPrices':
        row['records'] = row.pop('observations', row.get('records', []))
    elif shape == 'LotDetail':
        row = dict(lot=row, rows=row['rows'])
    elif shape == 'Settings':
        if row.get('incomplete_discount_pct') is not None:
            row['incomplete_discount_pct'] = float(row['incomplete_discount_pct'])
        row['source_priority'] = row.get('priority', row.get('source_priority', {}))
        if isinstance(row['source_priority'], str):
            row['source_priority'] = json.loads(row['source_priority'])
        row['repair'] = {key.removeprefix('repair_'): row[key] for key in
                         ('repair_shipping', 'repair_fees', 'repair_min_order', 'repair_use_loose_stock')
                         if key in row}
    children = NESTED.get(shape, {})
    return serialize({key: public(row[key], children[key], secrets) if key in children else row[key]
                      for key in FIELDS[shape] if key in row}, secrets)
