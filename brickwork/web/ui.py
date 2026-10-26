"""Shared local browser shell and v3 navigation."""
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import request, url_for
from urllib.parse import urlsplit
from markupsafe import Markup, escape

from ..core.list_records import payload as bw_collection_records
from .formatting import short_age as bw_age
from .formatting import money, short_date, short_stamp, source_label, source_line, missing_counts, plural, difference, nowrap_tail, part_name, ratio

ROOT = Path(__file__).resolve().parents[2]
PREFIX = 'web/toni/'


def bw_price_order(prices):
    return sorted(prices, key=lambda p: {'used': 0, 'new': 1}.get(p.get('condition'), 2))


def install(app):
    app.extensions['web_ui'] = {'mode': 'toni'}
    env = app.jinja_env
    def toni_template(name):
        return PREFIX + name.removeprefix(PREFIX)

    def inline_icon(path):
        # Preserve provenance in the asset, without repeating its binary metadata
        # in every rail, tab and button in the HTML response.
        source = re.sub(r'<metadata>.*?</metadata>', '', path.read_text(), flags=re.S)
        return Markup(source.replace(' xmlns="http://www.w3.org/2000/svg"', '').replace(
            '<svg ', '<svg class="icon" aria-hidden="true" focusable="false" ', 1))

    icons = {p.stem: inline_icon(p) for p in (ROOT / 'static/web/toni/icons').glob('*.svg')}
    icons.update({p.stem: inline_icon(p) for p in (ROOT / 'static/brickwork/icons-ui').glob('*.svg')
                  if p.stem != 'sprite'})
    mapping = json.loads((ROOT / 'static/web/toni/icon-aliases.json').read_text())

    def icon(name):
        return icons.get(mapping.get(name, name), '')

    # Same-host links become relative; outbound links (Rebrickable, BrickLink) and content images
    # keep their real URLs. The offline rule covers what the shell loads (styles, scripts, fonts),
    # not where a user may navigate (review change 2026-10-05: no signed redirect indirection).
    def local_link(url):
        if not url:
            return ''
        parsed = urlsplit(url)
        if parsed.scheme in ('http', 'https') and parsed.netloc == request.host:
            return parsed.path + ('?' + parsed.query if parsed.query else '') + ('#' + parsed.fragment if parsed.fragment else '')
        return url

    def local_asset(url):
        # Content images keep their real URL, local or remote (USE_REMOTE_IMAGES), as upstream
        # shows them; the offline rule covers the shell's own styles, scripts and fonts only.
        return local_link(url)

    def date_value(value):
        # Individual items/lots store UNIX timestamps; set forms already supply
        # yyyy/mm/dd. Use the upstream writers' local datetime convention.
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value).strftime('%Y/%m/%d')
        return value or ''

    from ..core.collection import defects
    from .setup_state import key_missing

    def picture_attrs(image_id, sizes='160px'):
        # Thumbnail src/srcset/sizes plus the original for the lightbox (images.js reads data-full).
        from flask import url_for
        base = url_for('web.bw_image', image_id=image_id)
        return Markup(f'src="{base}?w=320" srcset="{base}?w=320 320w, {base}?w=640 640w" '
                      f'sizes="{escape(sizes)}" data-full="{base}"')

    env.globals.update(bw_picture_attrs=picture_attrs, bw_price_order=bw_price_order, bw_age=bw_age, bw_defects=defects, toni_template=toni_template, toni_icon=icon, bw_static=bw_static,
                       toni_link=local_link, toni_date=date_value, toni_asset=local_asset, toni_json=json.loads,
                       toni_ratio=ratio, toni_difference=difference, toni_nowrap_tail=nowrap_tail, toni_part_name=part_name, toni_money=money, toni_short_date=short_date, toni_stamp=short_stamp,
                       toni_source=source_label, toni_source_line=source_line,
                       toni_missing=missing_counts, toni_plural=plural, bw_key_missing=key_missing)
    def shell_context():
        groups = navigation()
        active = next((name for name, links in groups if any(link['active'] for link in links)), 'Manage')
        return dict(toni_navigation=groups, toni_active_group=active, tools_navigation=tools_navigation())

    app.context_processor(shell_context)


def bw_static(filename):
    """Version Brick Work assets using the deployed file's nanosecond mtime."""
    from flask import current_app
    try:
        version = (Path(current_app.static_folder) / filename).stat().st_mtime_ns
    except FileNotFoundError:
        return url_for('static', filename=filename)
    return url_for('static', filename=filename, v=str(version))



def _links(definitions):
    """Keep configured visibility and upstream permissions on every deep link."""
    from flask import current_app
    links = []
    for title, endpoint, icon, flags, args in definitions:
        if any(current_app.config.get(flag, False) for flag in flags):
            continue
        links.append(dict(title=title, endpoint=endpoint, url=url_for(endpoint, **args), icon=icon,
                          active=request.endpoint == endpoint))
    return links


def tools_navigation():
    return []


def passthrough_args(*route_params):
    """The request's query arguments, safe to hand to url_for(**args) (#68).

    url_for treats _external, _anchor, _method and _scheme as instructions and route parameters as the
    path, so a query argument of that name answered 500 or built a link to another host.
    """
    from flask import request
    return {k: v for k, v in request.args.to_dict(flat=False).items() if not k.startswith('_') and k not in route_params}


def navigation():
    groups = [
        ('Collection', [
            ('Sets', 'web.bw_sets', 'sets', ('HIDE_ALL_SETS',), {}),
            ('Minifigures', 'web.bw_collection', 'minifig', ('HIDE_ALL_MINIFIGURES',), {'kind':'M'}),
            ('Parts', 'web.bw_collection', 'parts', ('HIDE_ALL_PARTS',), {'kind':'P'}),
            ('Instructions', 'web.bw_collection', 'instr', (), {'kind':'I'}),
            ('Boxes', 'web.bw_collection', 'box', (), {'kind':'O'})]),
        ('Workbench', [
            ('Part to Inventory', 'web.bw_inventory', 'scan', (), {}),
            ('Part Picker', 'web.bw_picker', 'pick', (), {}),
            ('Matcher', 'web.bw_matcher', 'match', (), {}),
            ('Orders', 'web.bw_orders', 'orders', (), {}),
            ('Storage', 'web.bw_storages', 'storage', ('HIDE_ALL_STORAGES',), {})]),
        ('Planning', [
            ('Wishlist', 'web.bw_planning', 'wish', ('HIDE_WISHES',), {'screen':'wishlist'}),
            ('Prices', 'web.bw_planning', 'price', (), {'screen':'prices'}),
            ('Complete sets', 'web.bw_planning', 'done', ('HIDE_ALL_PROBLEMS_PARTS',), {'screen':'complete-sets'})]),
        ('Manage', [
            ('Add', 'web.bw_add', 'add', ('HIDE_ADD_SET',), {}),
            ('Tools & Admin', 'web.bw_tools', 'tools', (), {})])]
    endpoint = request.endpoint or ''
    area = endpoint.split('.')[0]
    if endpoint=='web.bw_planning':
        current={'wishlist':'Wishlist','prices':'Prices','complete-sets':'Complete sets'}.get((request.view_args or {}).get('screen'),'Wishlist')
    elif endpoint.startswith('web.bw_collection_wish'):
        current = 'Wishlist'
    elif endpoint in ('web.bw_collection','web.bw_collection_item'):
        from flask import g
        letter = (request.view_args or {}).get('kind') or g.get('bw_nav_type') or 'S'
        current = {'S':'Sets','M':'Minifigures','P':'Parts','I':'Instructions','O':'Boxes','G':'Gear','B':'Books','C':'Catalogs'}.get(letter.upper(),'Sets')
    elif endpoint in ('web.bw_sets','index.index','web.collection_legacy_home'):
        current = 'Sets'
    elif endpoint in ('web.bw_collection_lot','web.bw_collection_places'):
        current = 'Parts' if endpoint.endswith('lot') else 'Storage'
    elif endpoint.startswith('web.bw_add'):
        current = 'Add'
    elif endpoint in ('web.parts_scanner_page', 'web.bw_inventory'):
        current = 'Part to Inventory'
    elif endpoint in ('set.check', 'web.bw_check_parts', 'web.bw_check_copy', 'web.bw_check_write'):
        current = 'Check Set Parts'
    elif endpoint == 'web.bw_picker':
        current = 'Part Picker'
    elif endpoint in ('web.matcher_page', 'web.bw_matcher'):
        current = 'Matcher'
    elif endpoint.startswith('web.boxes') or endpoint in ('web.save_loose_boxes','web.assign_loose_boxes'):
        current = 'Boxes'
    elif endpoint == 'index.index':
        current = 'Sets'
    elif endpoint in ('part.problem', 'web.complete_sets'):
        current = 'Complete sets'
    elif endpoint == 'web.bricklink_page' or endpoint.startswith(('web.order', 'web.bw_order')):
        current = 'Orders'
    elif endpoint.startswith('web.bw_storage'):
        current = 'Storage'
    elif endpoint in ('web.index', 'web.prices'):
        current = 'Prices'
    elif endpoint in ('web.instructions_collection', 'web.save_loose_instructions',
                      'web.instructions_detail', 'web.assign_loose_instructions'):
        current = 'Instructions'
    else:
        current = {'set': 'Sets', 'minifigure': 'Minifigures', 'individual_minifigure': 'Minifigures',
                   'part': 'Parts', 'individual_part': 'Parts', 'storage': 'Storage',
                   'wish': 'Wishlist', 'add': 'Add'}.get(area, 'Tools & Admin')
    from .auth import LoginManager
    # Nothing about the collection shows before login (#66).
    counts = navigation_counts() if LoginManager.is_authenticated() else {}
    from flask import current_app
    for title,kind in [('Gear','G'),('Books','B'),('Catalogs','C')]:
        if counts.get(title):
            groups[0][1].append((title,'web.bw_collection','parts',(),{'kind':kind}))
    result = []
    for group, definitions in groups:
        links = _links(definitions)
        if group == 'Workbench' and not current_app.config.get('HIDE_ALL_SETS'):
            links.insert(1, dict(title='Check Set Parts', endpoint='web.bw_check_parts',
                                url=url_for('web.bw_check_parts'), icon='check'))
        for link in links:
            link['count'] = counts.get(link['title'])
            link['active'] = link['title'] == current
        if links:
            result.append((group, links))
    return result


def navigation_counts():
    """One read-only query, no BrickSQL setup, migration, fetch or cache writer.

    Missing/unavailable databases are normal on system-error pages. Keep the
    shell renderable there and omit counts rather than inventing zeroes.
    """
    from flask import g
    if hasattr(g, '_toni_nav_counts'):
        return g._toni_nav_counts
    counts = {}
    from .admin_ops import brickwork_path
    from ..core.admin import database
    path = brickwork_path()
    if path.is_file():
        try:
            with database(path, read_only=True) as db:
                counts = dict(db.execute("""SELECT 'Sets',count(DISTINCT item_id) FROM copy WHERE archived_at IS NULL
                    UNION ALL SELECT CASE kind WHEN 'minifigure' THEN 'Minifigures' WHEN 'part' THEN 'Parts'
                    WHEN 'instructions' THEN 'Instructions' WHEN 'box' THEN 'Boxes' END,sum(quantity)
                    FROM stock WHERE archived_at IS NULL AND kind IN ('minifigure','part','instructions','box') GROUP BY kind
                    UNION ALL SELECT CASE kind WHEN 'gear' THEN 'Gear' WHEN 'book' THEN 'Books' WHEN 'catalog' THEN 'Catalogs' END,count(DISTINCT item_id)
                    FROM stock WHERE archived_at IS NULL AND kind IN ('gear','book','catalog') GROUP BY kind
                    UNION ALL SELECT 'Wishlist',count(*) FROM wish WHERE archived_at IS NULL"""))
        except (sqlite3.Error, OSError, ValueError):
            pass
    g._toni_nav_counts = counts
    return counts
