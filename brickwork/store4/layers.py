"""The mapping layers of the catalogue builder (design 3.2, 3.3, 3.7, 4.1): colour links, part / figure / set links, the
FTS link keys' source rows and `bl_digest`. Each layer is `layer(db, ctx)`; `ctx.report` collects what goes into counts_json.

Links are loaded for every item and colour of the new file, retired ones included: a retired part keeps the mapping the
CSV still lists, so carried inventories keep their `bl_digest`.

Precedence (3.3): local > shipped and rule. A local row replaces every shipped or rule row of the same (item, provider,
provider_kind, colour scope), so those are never loaded. The leg rule replaces all parts.csv rows of the parts it covers.
The set-number rule (decision 7) applies to items of kind `set` only: a zero-part set classified as gear, book or catalog
by its theme gets no `S` link, because BrickLink does not list it as a set (the design is silent; reported)."""
from collections import defaultdict
import hashlib
import itertools
import json
from pathlib import Path

from .bldigest import bl_digest
from .identity import color_link_order, item_link_order
from .mappings import COLUMNS, MAPPINGS_DIR, leg_rule, read_mapping

RANK = {'matched': 0, 'inferred': 1}
CONFIRMED = tuple(RANK)
LOCAL_FILES = {'parts.csv': 'parts', 'minifigs.csv': 'minifigs'}
ITEM_LINK_COLS = ('item_id', 'color_id', 'provider', 'provider_kind', 'provider_key', 'status', 'method', 'origin', 'preferred',
                  'evidence_digest', 'build_id')
COLOR_LINK_COLS = ('color_id', 'provider', 'provider_key', 'provider_name', 'status', 'method', 'origin', 'inverse_preferred', 'build_id')


def _evidence(*fields):
    return hashlib.sha256('\x1f'.join(str(f) for f in fields).encode()).hexdigest()


def _count(report, section, key, n=1):
    report.setdefault(section, {})
    report[section][key] = report[section].get(key, 0) + n


def shipped_version(mappings_dir):
    """The shipped mapping_version (every shipped file carries the same one)."""
    return read_mapping(Path(mappings_dir) / 'parts.csv')[0]['mapping_version']


def colour_links(db, ctx):
    """colors.csv -> color_link. Colours absent from the new file (live and retired ones are both in it) are skipped and counted; one inverse_preferred per provider key."""
    _, rows = read_mapping(ctx.mappings_dir / 'colors.csv')
    seen, flagged, out = set(), defaultdict(list), []
    for r in rows:
        color_id = ctx.color_ids.get(r['rb_color_id'])
        if color_id is None:
            _count(ctx.report, 'mapping_skipped', 'colour_links_colour_not_in_file')
            continue
        k = (r['provider'], r['provider_key'], color_id)
        if k in seen:
            _count(ctx.report, 'mapping_skipped', 'colour_links_duplicate')
            continue
        seen.add(k)
        row = dict(color_id=color_id, provider=r['provider'], provider_key=r['provider_key'], provider_name=r['provider_name'] or None,
                   status='matched', method='external_ids', origin='shipped', inverse_preferred=int(r['inverse_preferred'] == '1'),
                   build_id=ctx.build_id)
        out.append(row)
        if row['inverse_preferred']:
            flagged[(row['provider'], row['provider_key'])].append(row)
    for group in flagged.values():
        for row in sorted(group, key=lambda r: r['color_id'])[1:]:        # the unique index allows one per provider key: the lowest id
            row['inverse_preferred'] = 0
            _count(ctx.report, 'mapping_skipped', 'colour_inverse_preferred_dropped')
    db.executemany(f"INSERT INTO color_link({','.join(COLOR_LINK_COLS)}) VALUES({','.join(':' + c for c in COLOR_LINK_COLS)})", out)
    ctx.report['colour_links'] = len(out)


def _link(item_id, color_id, provider, kind, key, status, method, origin, preferred, evidence, build_id):
    return dict(item_id=item_id, color_id=color_id, provider=provider, provider_kind=kind, provider_key=key, status=status,
                method=method, origin=origin, preferred=int(preferred), evidence_digest=evidence, build_id=build_id)


def _read_rows(ctx, path, name, namespace, origin, report_key):
    """Rows of a parts.csv-shaped file as link dicts for live items of `namespace`; the rest is skipped and counted."""
    _, rows = read_mapping(path)
    out = []
    for r in rows:
        item_id = ctx.item_ids.get((namespace, r['rb_part_num']))
        if item_id is None:
            _count(ctx.report, 'mapping_skipped', f'{report_key}_item_not_in_file')
            continue
        color_id = None
        if r['rb_color_id'] != '':
            color_id = ctx.color_ids.get(r['rb_color_id'])
            if color_id is None:
                _count(ctx.report, 'mapping_skipped', f'{report_key}_colour_not_in_file')
                continue
        out.append(_link(item_id, color_id, r['provider'], r['provider_kind'], r['provider_key'], r['status'], r['method'], origin,
                         r['preferred'] == '1', _evidence(*(r[c] for c in COLUMNS[name])), ctx.build_id))
    return out


def item_links(db, ctx):
    """parts.csv + the rules + the local layer -> item_link, with the precedence of design 3.3."""
    shipped_dir = ctx.mappings_dir
    shipped = _read_rows(ctx, shipped_dir / 'parts.csv', 'parts.csv', 'parts', 'shipped', 'parts_csv')
    external = defaultdict(set)
    for r in shipped:
        if r['provider'] == 'bricklink' and r['provider_kind'] == 'P' and r['method'] == 'external_ids':
            external[ctx.part_num[r['item_id']]].add(r['provider_key'])
    # ---- rule: the leg rule replaces every parts.csv row of the parts it covers ----
    _, colour_rows = read_mapping(shipped_dir / 'colors.csv')
    rule = []
    for r in leg_rule(ctx.parts, colour_rows, external):
        item_id = ctx.item_ids[('parts', r['rb_part_num'])]
        color_id = None
        if r['rb_color_id'] != '':
            color_id = ctx.color_ids.get(r['rb_color_id'])
            if color_id is None:
                _count(ctx.report, 'mapping_skipped', 'leg_rule_colour_not_in_file')
                continue
        rule.append(_link(item_id, color_id, r['provider'], r['provider_kind'], r['provider_key'], r['status'], 'leg_rule', 'rule', True,
                          _evidence('leg_rule', r['rb_part_num'], r['rb_color_id'], r['provider_key'], r['status']), ctx.build_id))
    leg_parts = {r['item_id'] for r in rule}
    kept = [r for r in shipped if r['item_id'] not in leg_parts]
    if len(shipped) > len(kept):
        _count(ctx.report, 'mapping_skipped', 'parts_csv_replaced_by_leg_rule', len(shipped) - len(kept))
    # ---- rule: the set-number rule and the set exceptions ----
    _, exception_rows = read_mapping(shipped_dir / 'set_exceptions.csv')
    exceptions = defaultdict(list)
    for r in exception_rows:
        item_id = ctx.item_ids.get(('sets', r['rb_set_num']))
        if item_id is None:
            _count(ctx.report, 'mapping_skipped', 'set_exceptions_item_not_in_file')
            continue
        exceptions[item_id].append(_link(item_id, None, 'bricklink', r['provider_kind'], r['provider_key'], 'matched', 'set_exception',
                                         'shipped', True, _evidence(*(r[c] for c in COLUMNS['set_exceptions.csv'])), ctx.build_id))
    sets = []
    for set_num, item_id in ctx.set_ids:
        if item_id in exceptions:
            sets.extend(exceptions[item_id])
        else:
            sets.append(_link(item_id, None, 'bricklink', 'S', set_num, 'inferred', 'set_number', 'rule', True,
                              _evidence('set_number', set_num), ctx.build_id))
    # ---- local layer ----
    local, manifests = [], {}
    if ctx.local_dir:
        for name, namespace in LOCAL_FILES.items():
            path = Path(ctx.local_dir) / name
            if not path.is_file():
                continue
            rows = _read_rows(ctx, path, name, namespace, 'local', f'local_{name[:-4]}')
            local.extend(rows)
            meta_path = path.with_name(name[:-4] + '.manifest.json')
            manifests[name] = dict(rows=len(rows), mapping_version=read_mapping(path)[0]['mapping_version'],
                                   manifest=json.loads(meta_path.read_text()) if meta_path.is_file() else None)
    scope = {(r['item_id'], r['provider'], r['provider_kind'], r['color_id']) for r in local}
    rest = []
    for r in kept + rule + sets:
        if (r['item_id'], r['provider'], r['provider_kind'], r['color_id']) in scope:
            _count(ctx.report, 'mapping_skipped', 'replaced_by_local')
        else:
            rest.append(r)
    # ---- one row per unique key, then at most one preferred per (item, provider, colour scope) ----
    unique, links = set(), []
    for r in local + rest:
        k = (r['provider'], r['provider_kind'], r['provider_key'], r['item_id'], r['color_id'] or 0)
        if k in unique:
            _count(ctx.report, 'mapping_skipped', 'item_links_duplicate')
            continue
        unique.add(k)
        links.append(r)
    flagged = defaultdict(list)
    for r in links:
        if r['preferred']:
            flagged[(r['item_id'], r['provider'], r['color_id'] or 0)].append(r)
    for group in flagged.values():
        for r in sorted(group, key=lambda r: (r['provider_kind'], r['provider_key']))[1:]:
            r['preferred'] = 0
            _count(ctx.report, 'mapping_skipped', 'preferred_resolved')
    db.executemany(f"INSERT INTO item_link({','.join(ITEM_LINK_COLS)}) VALUES({','.join(':' + c for c in ITEM_LINK_COLS)})", links)
    by = {}
    for r in links:
        k = f"{r['origin']}/{r['method']}/{r['status']}"
        by[k] = by.get(k, 0) + 1
    ctx.report['item_links'] = dict(total=len(links), by_origin_method_status=dict(sorted(by.items())))
    if manifests:
        ctx.report['local_mappings'] = manifests


def bl_digests(db, ctx):
    """inventory.bl_digest: every line projected through the catalogue's own links (design 3.2's resolution function)."""
    unscoped, scoped = {}, {}
    pools = defaultdict(list)
    for r in db.execute(f"SELECT item_id, color_id, provider_kind, provider_key, status, preferred FROM item_link"
                        f" WHERE provider='bricklink' AND status IN ({','.join('?' * len(CONFIRMED))})", CONFIRMED):
        pools[(r[0], r[1])].append(r)
    for (item_id, color_id), rows in pools.items():
        best = min(rows, key=lambda r: item_link_order(r[5], r[4], r[2], r[3]))
        (unscoped if color_id is None else scoped)[(item_id, color_id) if color_id is not None else item_id] = (best[2], best[3])
    colour = {}
    for color_id, key, status in db.execute(f"SELECT color_id, provider_key, status FROM color_link WHERE provider='bricklink'"
                                            f" AND status IN ({','.join('?' * len(CONFIRMED))})", CONFIRMED):
        if color_id not in colour or color_link_order(status, key) < colour[color_id][0]:
            colour[color_id] = (color_link_order(status, key), key)
    colour = {c: v[1] for c, v in colour.items()}
    no_colour = ctx.color_ids.get('9999')

    def link(item_id, color_id):
        return scoped.get((item_id, color_id)) or unscoped.get(item_id)

    component = {'inventory_figure': 'M', 'inventory_set': 'S'}
    extra = defaultdict(list)                                  # figure and set lines, few: kept per inventory
    broken = set()
    for table, kind in component.items():
        for inv, item_id, qty in db.execute(f'SELECT inventory_id, item_id, quantity FROM {table}'):
            found = unscoped.get(item_id)
            if found is None:
                broken.add(inv)
            else:
                extra[inv].append((found[0], found[1], None, 0, qty))
    broken |= ctx.incomplete_inventories                       # a skipped dump line: the list is not what Rebrickable has
    digests = {}
    cursor = db.execute('SELECT inventory_id, item_id, color_id, is_spare, quantity FROM inventory_part ORDER BY inventory_id')
    for inv, group in itertools.groupby(cursor, key=lambda r: r[0]):
        lines = list(extra.get(inv, ()))
        ok = inv not in broken
        for _, item_id, color_id, spare, qty in group:
            if not ok:
                break
            found = link(item_id, color_id)
            if found is None:
                ok = False
            elif color_id == no_colour:
                lines.append((found[0], found[1], None, spare, qty))
            elif color_id not in colour:
                ok = False
            else:
                lines.append((found[0], found[1], colour[color_id], spare, qty))
        digests[inv] = bl_digest(lines) if ok else None
    for (inv,) in db.execute('SELECT id FROM inventory').fetchall():
        if inv not in digests:                                 # no part lines: figure and set lines only
            digests[inv] = None if inv in broken else bl_digest(extra.get(inv, ()))
    db.executemany('UPDATE inventory SET bl_digest=? WHERE id=?', [(d, i) for i, d in digests.items()])
    have = sum(1 for d in digests.values() if d)
    ctx.report['bl_digest'] = dict(with_digest=have, null=len(digests) - have)
    ctx.report['bl_digest_incomplete'] = len(ctx.incomplete_inventories)


DEFAULT_LAYERS = [colour_links, item_links, bl_digests]

# FTS keys: the born key plus every linked provider key (all statuses: a to_check candidate is searchable too). The builder
# fills it for every live item; the BrickLink list import refreshes the rows of the items it changed (`AND i.id IN (...)`).
FTS_INSERT = """INSERT INTO item_fts(item_id, kind, name, keys)
                SELECT i.id, i.kind, i.name, i.born_key || coalesce(' ' || (SELECT group_concat(k, ' ') FROM
                    (SELECT DISTINCT provider_key AS k FROM item_link l WHERE l.item_id=i.id ORDER BY provider_key)), '')
                FROM item i WHERE i.retired_at IS NULL"""
