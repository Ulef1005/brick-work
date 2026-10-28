"""Writes on prices and settings (M.11c, issue #113): manual price observations and the whitelisted settings.

A manual observation is `core/manual_prices.py`'s (one receipt, Undo voids it and puts the previous price back); the settings are
`admin.patch_settings`' (the retail country, the display currency, the BrickLink region and currency, the discount for an incomplete set,
the source order of the pipeline steps, the freshness rules, the repair settings and, since M.11c, the BrickLink part-list preference)."""
from ..core import admin, manual_prices
from . import route
from .items import for_write
from .prices import observation
from .read import bodies, reading, respond
from .writes import Done, color_of, identified, write


# ---------- manual prices ----------

def entry(item_id, color_id, body):
    return {'item_id': item_id, 'color_id': color_id, 'condition': body['condition'], 'guide': body['guide'], 'price': body['price'],
            'currency': body['currency'], 'slot': body.get('slot'), 'observed_at': body.get('observed_at')}


@route('/items/<id>/prices', 'POST')
@write
def post_items_by_id_prices(db, body, id):
    item_id = for_write(db, id)
    (observed,) = manual_prices.record(db, [entry(item_id, color_of(db, {'id': item_id}, body.get('color')), body)])
    row = db.execute('SELECT * FROM main.price_observation WHERE id=?', (observed,)).fetchone()
    return Done(observation(bodies(db, items=[item_id], colors=[row['color_id']]), row), status=201)


@route('/prices/observations', 'POST')
@write
def post_prices_observations(db, body):
    entries = []
    for each in body['items']:
        item_id, color_id = identified(db, each['item'], each.get('color'))
        entries.append(entry(item_id, color_id, each))
    manual_prices.record(db, entries)
    event = db.execute("SELECT max(id) FROM main.event WHERE entity_kind='manual_prices' AND field='receipt'").fetchone()[0]
    return Done({'applied': len(entries), 'skipped': [], 'dry_run': False, 'event_id': event}, event)


# ---------- settings ----------

def settings_body(db):
    """`Settings`: what `admin.settings` reads, under the contract's names."""
    s = admin.settings(db)
    row = db.execute("SELECT value FROM main.setting WHERE key='prefer_bricklink_inventory'").fetchone()
    return {'display_currency': s['display_currency'], 'retail_country': s['retail_country'], 'bricklink_region': s['bricklink_region'],
            'bricklink_currency': s['bricklink_currency'], 'incomplete_discount_pct': s['incomplete_discount_pct'], 'source_priority': s['priority'],
            'import_order': s['import_order'],
            'freshness': [{'source': r['source'], 'kind': r['kind'], 'max_age_days': r['max_age_days']} for r in s['freshness']],
            'repair': {'shipping': s['repair_shipping'], 'fees': s['repair_fees'], 'min_order': s['repair_min_order'], 'use_loose_stock': s['repair_use_loose_stock']},
            'prefer_bricklink_inventory': bool(row and row['value'] == 'true')}


@route('/settings')
@reading
def get_settings(db):
    from .read import arguments
    arguments()
    return respond(settings_body(db))


@route('/settings', 'PATCH')
@write
def patch_settings(db, body):
    admin.patch_settings(db, body)
    return Done(settings_body(db))
