"""The independent read-back proof of the 3.3 -> 4.0 migration (design 8.7, issue #109 M.7c).

`prove(temp_path, catalogue_path, src_path, result)` runs after the writer's transaction has committed. It opens the written file
read-only on its own connection (the catalogue attached read-only), opens the 3.3 store again on its own, and compares them. From the
writer it takes only what the design allows: the mint table (`result.mint`, the documented map from every 3.3 key to its 4.0 target,
inverted here) and the lists of transformations (`result`): Q7 sums, the extras correction, the colour-NULL rule, count fixes, money
fills, the figure lines taken from `copy_parts`, retained duplicates, rows copy_part cannot hold, the gear carried as parts. None of the
writer's in-memory row structures are reused.

Five parts as in design 8.7, plus one the attach step of 8.6 needs:
1. `lists`: per copy, per loose figure, per loose stock row and per wish, the multiset of lines in BrickLink space
   `(type, number, colour, spare, figure) -> (quantity, missing, damaged, checked)`, read from 4.0 through the inverted mint table, equals
   the 3.3 one apart from the listed transformations;
2. `prices`: per `(BrickLink key, colour, condition, guide, slot, region, currency)` the observations equal field by field, and
   `price_current` is recomputed from the 4.0 observations and equals both the 4.0 table and the 3.3 one (apart from the differences the
   writer listed); the watch list equals;
3. `plain`: counts and checksums of storage, places, lots, flags and flag links, wishlists, keys, tokens, freshness, settings, the sync
   link, photos and instruction files;
4. `structure`: `foreign_key_check`, `integrity_check`, and every `origin='catalogue'` item and colour exists in the catalogue with the
   same born key;
5. `injectivity`: no two 3.3 keys share a 4.0 target, and every target exists in the output;
6. `attach`: every copy, figure line and loose figure the writer attached equals the catalogue's list it names, recomputed from the lines
   of the output in BrickLink space, and the ones in the file are exactly the ones the writer recorded.

BrickLink space here is the mint key `(type, number, colour)` with two normalisations, both the writer's documented rules: colour NULL and
0 are "no colour", and a key the mint carried as a part (`type_crossed`) is a `P` key. A part-table row of a kind copy_part cannot hold
is not in 4.0; the writer lists it and the proof skips it by the listing."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sqlite3

from . import identity
from .bldigest import bl_digest
from .connect import connect
from .migrate import CONDITION, PLACE_KINDS, STOCK_CONDITION, STORAGE_TYPES, CARRIED_PRIORITY_STEPS, CARRIED_SETTINGS, COMPLETENESS, open_source
from .mint import TYPE_KIND, MintResult, _kind_by_number

FIRST = 20                                                    # differences kept per part


class Part:
    def __init__(self, name, what):
        self.name, self.what = name, what
        self.checked = 0
        self.differences = 0
        self.first = []

    def eq(self, label, want, got):
        self.checked += 1
        if want != got:
            self.differences += 1
            if len(self.first) < FIRST:
                self.first.append({'what': label, '3.3': want, '4.0': got})

    def maps(self, label, want, got):
        for key in sorted(set(want) | set(got), key=str):
            self.eq(f'{label} {key}', want.get(key), got.get(key))

    def fail(self, label, detail):
        self.eq(label, 'ok', detail)

    def as_dict(self):
        return {'result': 'PASS' if self.differences == 0 else 'FAIL', 'what': self.what, 'checked': self.checked,
                'differences': self.differences, 'first_differences': self.first}


def checksum(rows):
    return hashlib.sha256(json.dumps(sorted(map(list, rows), key=str), default=str, separators=(',', ':')).encode()).hexdigest()


class _Space:
    """The inverted mint table: 4.0 (item, colour) -> BrickLink key, and the normalisation of keys."""

    def __init__(self, mint, kinds):
        self.mint, self.kinds = mint, kinds
        self.inverse = defaultdict(set)
        self.targets = defaultdict(set)                       # nkey -> {(item, colour)}
        for key, d in mint.items.items():
            items = {o.item_id for o in d.holders.values() if o.item_id is not None}
            if d.item_id is not None:
                items.add(d.item_id)
            nkey = self.norm(key)
            for item_id in items:
                target = self.target(item_id, mint.colour_for(key[2]))
                self.inverse[target].add(nkey)
                self.targets[nkey].add(target)

    def target(self, item_id, colour):
        return (item_id, colour if self.kinds.get(item_id) == 'part' else None)

    def norm(self, key):
        """The mint key as BrickLink space names it: a crossed key is a `P` key, colour only on parts, NULL and 0 the same."""
        item_type, number, colour = key
        d = self.mint.items.get(key)
        if d is not None and d.crossed:
            item_type = 'P'
        if item_type not in ('P', '?P') or colour == 0:
            colour = None
        return (item_type, number, colour)

    def key33(self, item_type, number, colour=None, kind=None):
        if item_type == '?' and kind is None:
            kind = _kind_by_number(number)
        return self.norm(MintResult.key_of(item_type, number, colour, kind))

    def back(self, item_id, colour):
        """The BrickLink key of a 4.0 (item, colour); an unmapped target is named as such, so it shows up as a difference."""
        keys = self.inverse.get(self.target(item_id, colour))
        return min(keys, key=str) if keys else ('<unmapped>', item_id, colour)


def prove(temp_path, catalogue_path, src_path, result):
    """The proof document: {'result': 'PASS'|'FAIL', 'parts': {name: {...}}}. Reads only; never raises for a difference."""
    db = connect(temp_path, catalogue_path, read_only=True)
    src = open_source(src_path)
    try:
        return _Proof(db, src, result).run()
    finally:
        db.close()
        src.close()


class _Proof:
    def __init__(self, db, src, result):
        self.db, self.src, self.r = db, src, result
        self.mint = result.mint
        self.kinds = {i: k for i, k in db.execute('SELECT id, kind FROM main.item')}
        self.space = _Space(self.mint, self.kinds)
        self.currency = (src.execute("SELECT value FROM settings WHERE key='bricklink_currency'").fetchone() or [None])[0] or 'EUR'
        self.parts = {}

    def part(self, name, what):
        self.parts[name] = Part(name, what)
        return self.parts[name]

    def run(self):
        for step in (self.lists, self.prices, self.plain, self.structure, self.injectivity, self.attach):
            step()
        verdict = 'PASS' if all(p.differences == 0 for p in self.parts.values()) else 'FAIL'
        return {'result': verdict, 'parts': {n: p.as_dict() for n, p in self.parts.items()}}

    # ---- helpers ----

    def money(self, price, currency):
        """The currency 4.0 should hold: the money-pair rule of 8.9 (a price without one gets the migrated currency; none without a price)."""
        if price is None:
            return None, None
        return price, currency if currency is not None else self.currency

    def count_rule(self, quantity, missing, damaged):
        """The listed count fix of 8.9: a NULL quantity (with nothing missing or damaged) is 0."""
        return (0, 0, 0) if quantity is None else (quantity, missing or 0, damaged or 0)

    # ---- 1. lists ----

    def lists(self):
        part = self.part('lists', 'per copy, loose figure, loose stock row and wish: lines in BrickLink space equal 3.3 apart from the listed transformations')
        self.copies(part)
        self.loose_figures(part)
        self.stock_rows(part)
        self.wishes(part)

    def copies(self, part):
        r, src, db, sp = self.r, self.src, self.db, self.space
        skip = {i for x in r.figure_lines_retained_duplicate for i in x['copy_part_ids']}
        skip |= {i for x in r.non_part_lines if 'copy_part_ids' in x for i in x['copy_part_ids']}
        from_parts = {i for x in r.figure_lines_from_parts for i in x['copy_part_ids']}
        extras = {e['copy_part_id']: e for e in r.extras}
        want_lines, want_figs = {}, {}
        for p in src.execute('SELECT * FROM copy_parts ORDER BY id'):
            if p['id'] in skip:
                continue
            q, m_, d_ = self.count_rule(p['quantity'], p['missing'], p['damaged'])
            e = extras.get(p['id'])
            if e is not None:
                if e['action'] == 'dropped':
                    continue
                q, m_, d_ = e['after']['quantity'], e['after']['missing'], e['after']['damaged']
            if p['id'] in from_parts:
                k = (p['copy_id'], sp.key33(p['item_type'], p['item_no'], None, 'minifigure'))
                old = want_figs.get(k, (0, 0))
                want_figs[k] = (old[0] + q, old[1] + m_)
                continue
            figure = None if p['parent_minifig'] is None else sp.key33(p['parent_minifig_type'], p['parent_minifig'], None, 'minifigure')
            k = (p['copy_id'], figure, sp.key33(p['item_type'], p['item_no'], p['color_id'], 'part' if p['item_type'] == '?' else None), p['spare'] or 0)
            old = want_lines.get(k)
            checked = int(bool(p['checked']))
            want_lines[k] = (q, m_, d_, checked) if old is None else (old[0] + q, old[1] + m_, old[2] + d_, min(old[3], checked))
        for f in src.execute('SELECT * FROM copy_minifigs'):
            q, m_, _ = self.count_rule(f['quantity'], f['missing'], 0)
            want_figs[(f['copy_id'], sp.key33(f['item_type'], f['minifig_no'], None, 'minifigure'))] = (q, m_)
        got_lines, got_figs = {}, {}
        figure_of = {}
        for f in db.execute('SELECT id, copy_id, item_id, quantity, missing FROM main.copy_figure WHERE retired_at IS NULL'):
            figure_of[f['id']] = sp.back(f['item_id'], None)
            got_figs[(f['copy_id'], figure_of[f['id']])] = (f['quantity'], f['missing'])
        for l in db.execute('SELECT * FROM main.copy_part WHERE retired_at IS NULL'):
            figure = None if l['copy_figure_id'] is None else figure_of.get(l['copy_figure_id'], ('<no figure line>', l['copy_figure_id'], None))
            k = (l['copy_id'], figure, sp.back(l['item_id'], l['color_id']), l['is_spare'])
            old = got_lines.get(k)
            row = (l['quantity'], l['missing'], l['damaged'], l['checked'])
            got_lines[k] = row if old is None else (old[0] + row[0], old[1] + row[1], old[2] + row[2], min(old[3], row[3]))
        part.maps('copy line', want_lines, got_lines)
        part.maps('copy figure line', want_figs, got_figs)
        # the copies themselves
        want, got = {}, {}
        for c in src.execute('SELECT * FROM copies'):
            price, currency = self.money(c['purchase_price'], c['purchase_currency'])
            value, value_currency = self.money(c['current_value'], c['current_value_currency'])
            want[c['id']] = (sp.key33(c['item_type'], c['set_no'], None, 'set'), CONDITION.get(c['condition']), COMPLETENESS.get(c['completeness']),
                             c['completeness_source'], c['storage_id'], c['purchase_location_id'], c['purchase_date'], price, currency, c['note'],
                             value, value_currency, c['pinned'], c['archived_at'])
        for c in db.execute('SELECT * FROM main.copy'):
            got[c['id']] = (sp.back(c['item_id'], None), c['condition'], c['completeness'], c['completeness_source'], c['storage_id'], c['place_id'],
                            c['purchase_date'], c['purchase_price'], c['purchase_currency'], c['note'], c['current_value'], c['current_value_currency'],
                            c['pinned'], c['archived_at'])
        part.maps('copy', want, got)

    def loose_figures(self, part):
        r, src, db, sp = self.r, self.src, self.db, self.space
        skipped = {(x['stock_id'], x['item_type'], x['item_no'], x['color_id'], x['spare']) for x in r.non_part_lines if x.get('table') == 'loose_minifig_parts'}
        want, got = {}, {}
        for p in src.execute('SELECT * FROM loose_minifig_parts'):
            spare = p['spare'] or 0
            if (p['stock_id'], p['item_type'], p['item_no'], p['color_id'], spare) in skipped:
                continue
            q, m_, d_ = self.count_rule(p['quantity'], p['missing'], p['damaged'])
            k = (p['stock_id'], sp.key33(p['item_type'], p['item_no'], p['color_id'], 'part' if p['item_type'] == '?' else None), spare)
            old = want.get(k)
            checked = int(bool(p['checked']))
            want[k] = (q, m_, d_, checked) if old is None else (old[0] + q, old[1] + m_, old[2] + d_, min(old[3], checked))
        for l in db.execute('SELECT * FROM main.stock_part WHERE retired_at IS NULL'):
            k = (l['stock_id'], sp.back(l['item_id'], l['color_id']), l['is_spare'])
            row = (l['quantity'], l['missing'], l['damaged'], l['checked'])
            old = got.get(k)
            got[k] = row if old is None else (old[0] + row[0], old[1] + row[1], old[2] + row[2], min(old[3], row[3]))
        part.maps('loose figure line', want, got)

    def stock_rows(self, part):
        src, db, sp = self.src, self.db, self.space
        want, got = {}, {}
        for s in src.execute('SELECT * FROM loose_stock'):
            price, currency = self.money(s['purchase_price'], s['purchase_currency'])
            q = 0 if s['quantity'] is None else s['quantity']
            want[s['id']] = (sp.key33(s['item_type'], s['item_no'], s['color_id']), q, STOCK_CONDITION.get(s['condition']), s['storage_id'], s['lot_id'],
                             s['purchase_location_id'], s['purchase_date'], price, currency, s['note'], s['missing'], s['damaged'], s['checked'],
                             s['archived_at'])
        for s in db.execute('SELECT * FROM main.stock'):
            got[s['id']] = (sp.back(s['item_id'], s['color_id']), s['quantity'], s['condition'], s['storage_id'], s['lot_id'], s['place_id'],
                            s['purchase_date'], s['purchase_price'], s['purchase_currency'], s['note'], s['missing'], s['damaged'], s['checked'],
                            s['archived_at'])
        part.maps('stock', want, got)

    def wishes(self, part):
        r, src, db, sp = self.r, self.src, self.db, self.space
        want, got = {}, {}
        for w in src.execute('SELECT * FROM wishlist'):
            price, currency = self.money(w['max_price'], w['max_price_currency'])
            want[r.wish_ids.get(w['id'], f'<no uuid for wish {w["id"]}>')] = (
                w['list_id'], sp.key33(w['item_type'], w['item_no'], w['color_id']), w['quantity'], w['condition'], price, currency,
                w['qty_filled_manual'], w['note'], w['archived_at'])
        for w in db.execute('SELECT * FROM main.wish'):
            got[w['id']] = (w['wishlist_id'], sp.back(w['item_id'], w['color_id']), w['quantity'], w['condition'], w['max_price'], w['max_price_currency'],
                            w['qty_filled_manual'], w['note'], w['archived_at'])
        part.maps('wish', want, got)

    # ---- 2. prices ----

    def prices(self):
        part = self.part('prices', 'per (BrickLink key, colour, condition, guide, slot, region, currency): observations and price_current')
        src, db, sp = self.src, self.db, self.space
        want, got, want_key, got_key = {}, {}, {}, {}
        for o in src.execute('SELECT * FROM price_observations'):
            undone = o['error'] == 'undone'
            key = sp.key33(o['item_type'], o['item_no'], o['color_id'])
            k = (key, CONDITION.get(o['condition']), o['guide'], o['slot'], o['region'], o['currency'])
            want_key[o['id']] = k
            want[o['id']] = (k, o['price'], o['qty'], o['sold'], o['min'], o['max'], o['source'], f'{o["item_type"]}:{o["item_no"]}'
                             + ('' if o['color_id'] is None else f'/{o["color_id"]}'), o['observed_at'], None if undone else o['error'], undone)
        for o in db.execute('SELECT * FROM main.price_observation'):
            k = (sp.back(o['item_id'], o['color_id']), o['condition'], o['guide'], o['slot'], o['region'], o['currency'])
            got_key[o['id']] = k
            got[o['id']] = (k, o['price'], o['qty'], o['sold'], o['min'], o['max'], o['source'], o['provider_key'], o['observed_at'], o['error'],
                            o['voided_at'] is not None)
        for i, w in want.items():                                  # a 3.3 row without a timestamp got one by the 8.9 rule: only the fact is checked
            if w[8] is None and i in got and got[i][8] is not None:
                want[i] = w[:8] + (got[i][8],) + w[9:]
        part.maps('observation', want, got)
        # per-key counts, the unit design 8.7 names
        count = lambda keys: {k: sum(1 for x in keys.values() if x == k) for k in set(keys.values())}
        part.maps('observations per key', count(want_key), count(got_key))
        # price_current: recomputed from the output's own observations
        newest = {}
        for o in db.execute('SELECT id, item_id, color_id, condition, guide, slot, region, currency FROM main.price_observation WHERE voided_at IS NULL ORDER BY id'):
            newest[(sp.back(o['item_id'], o['color_id']), o['condition'], o['guide'], o['slot'], o['region'], o['currency'])] = o['id']
        stored = {(sp.back(p['item_id'], p['color_id']), p['condition'], p['guide'], p['slot'], p['region'], p['currency']): p['observation_id']
                  for p in db.execute('SELECT * FROM main.price_current')}
        part.maps('price_current stored vs recomputed', newest, stored)
        before = {}
        for p in src.execute('SELECT * FROM price_current'):
            before[(sp.key33(p['item_type'], p['item_no'], p['color_id']), CONDITION.get(p['condition']), p['guide'], p['slot'], p['region'], p['currency'])] = p['observation_id']
        listed = set()
        for d in self.r.price_current.get('differences', []):
            item_id, colour, *rest = d['key']
            listed.add((sp.back(item_id, colour), *rest))
        for k in sorted(set(before) | set(newest), key=str):
            if k not in listed:
                part.eq(f'price_current {k}', before.get(k), newest.get(k))
        watch_want = {}
        for w in src.execute('SELECT * FROM price_watch'):
            watch_want[(sp.key33(w['item_type'], w['item_no'], w['color_id']), CONDITION.get(w['condition']))] = (
                w['origin'], w['first_seen'], w['last_fetch_at'], w['last_error'], w['last_error_at'], w['last_attempt_at'])
        watch_got = {(sp.back(w['item_id'], w['color_id']), w['condition']): (w['origin'], w['first_seen'], w['last_fetch_at'], w['last_error'],
                                                                              w['last_error_at'], w['last_attempt_at'])
                     for w in db.execute('SELECT * FROM main.price_watch')}
        part.maps('price_watch', watch_want, watch_got)

    # ---- 3. plain tables ----

    def plain(self):
        part = self.part('plain', 'counts and checksums of the tables that carry no key')
        src, db, r = self.src, self.db, self.r

        def table(name, want, got):
            part.eq(f'{name} count', len(want), len(got))
            part.eq(f'{name} checksum', checksum(want), checksum(got))

        table('storage', [(s['id'], s['name'] if s['name'] is not None else s['id'], s['type'] if s['type'] in STORAGE_TYPES or s['type'] is None else 'Other',
                           s['parent_id'], s['note'], s['archived_at']) for s in src.execute('SELECT * FROM storages')],
              [tuple(x) for x in db.execute('SELECT id, name, type, parent_id, note, archived_at FROM main.storage')])
        table('place', [(s['id'], s['name'] if s['name'] is not None else s['id'], s['kind'] if s['kind'] in PLACE_KINDS or s['kind'] is None else 'Other',
                         s['archived_at']) for s in src.execute('SELECT * FROM purchase_locations')],
              [tuple(x) for x in db.execute('SELECT id, name, kind, archived_at FROM main.place')])
        lots = []
        for l in src.execute('SELECT * FROM lots'):
            price, currency = self.money(l['purchase_price'], l['purchase_currency'])
            lots.append((l['id'], l['name'] if l['name'] is not None else l['id'], l['note'], l['storage_id'], l['purchase_location_id'], l['purchase_date'],
                         price, currency, l['archived_at']))
        table('lot', lots, [tuple(x) for x in db.execute('SELECT id, name, note, storage_id, place_id, purchase_date, purchase_price, purchase_currency, '
                                                         'archived_at FROM main.lot')])
        table('flag', [(f['id'], f['name'] if f['name'] is not None else f['id'], f['kind'], f['shown_on_grid'], f['archived_at'])
                       for f in src.execute('SELECT * FROM flags')],
              [tuple(x) for x in db.execute('SELECT id, name, kind, shown_on_grid, archived_at FROM main.flag')])
        links = []
        for f in src.execute('SELECT * FROM item_flags'):
            if f['entity_type'] == 'wishlist':
                entity = r.wish_ids.get(int(f['entity_id'])) if str(f['entity_id']).isdigit() else f['entity_id']
                links.append(('wish_flag', entity, f['flag_id']))
            else:
                links.append((f'{f["entity_type"]}_flag', f['entity_id'], f['flag_id']))
        got = []
        for t, c in (('copy_flag', 'copy_id'), ('stock_flag', 'stock_id'), ('wish_flag', 'wish_id')):
            got += [(t, a, b) for a, b in db.execute(f'SELECT {c}, flag_id FROM main.{t}')]
        table('flag links', links, got)
        ids = {w['id'] for w in src.execute('SELECT id FROM wishlists')}
        table('wishlist', [(w['id'], w['name'], w['note'], w['sort'], w['bricklink_id'], w['archived_at']) for w in src.execute('SELECT * FROM wishlists')],
              [tuple(x) for x in db.execute('SELECT id, name, note, sort, bricklink_id, archived_at FROM main.wishlist') if x[0] in ids])
        for src_table, dst, cols in (('source_keys', 'source_key', 'source, ciphertext, saved_at, archived_at'),
                                     ('source_key_previous', 'source_key_previous', 'source, ciphertext, saved_at, archived_at'),
                                     ('api_tokens', 'api_token', 'id, name, hash, scopes, created_at, expires_at, last_used_at, revoked_at')):
            table(dst, [tuple(x) for x in src.execute(f'SELECT {cols} FROM {src_table}')], [tuple(x) for x in db.execute(f'SELECT {cols} FROM main.{dst}')])
        known = {x[0] for x in db.execute('SELECT id FROM main.source')}
        table('source_freshness', [tuple(x) for x in src.execute('SELECT source, kind, max_age_days FROM source_freshness') if x[0] in known],
              [tuple(x) for x in db.execute('SELECT source, kind, max_age_days FROM main.source_freshness')])
        self.settings(part)
        want = {}
        for k, v in src.execute("SELECT key, value FROM settings WHERE key LIKE 'sync:%:link'"):
            want[k[len('sync:'):-len(':link')]] = v
        part.maps('sync link', want, {s: l for s, l in db.execute('SELECT source, link_json FROM main.sync_state WHERE link_json IS NOT NULL')})
        table('photo', [(i['local_path'], i['width'], i['height'], i['caption'], i['taken_at'], i['copy_id'], i['stock_id'])
                        for i in src.execute("SELECT * FROM item_images WHERE kind='own'")],
              [tuple(x) for x in db.execute('SELECT local_path, width, height, caption, taken_at, copy_id, stock_id FROM main.photo')])
        table('instruction_file', [(f['id'], f['path'], f['label'] if f['label'] is not None else Path(f['path']).name, f['archived_at'])
                                   for f in src.execute('SELECT * FROM instruction_files')],
              [tuple(x) for x in db.execute('SELECT id, path, label, archived_at FROM main.instruction_file')])
        part.eq('files named by photos exist in the 3.3 sense (paths unchanged)', 0,
                sum(1 for (p,) in db.execute('SELECT local_path FROM main.photo') if not p.startswith('data/images/own/')))

    def settings(self, part):
        """Per-key equality after the 8.10 translation. The classification of each 3.3 key is the writer's list; the values come from 3.3."""
        src, db, r = self.src, self.db, self.r
        values = dict(src.execute('SELECT key, value FROM settings'))
        part.eq('every 3.3 setting is classified', sorted(values), sorted(s['key'] for s in r.settings))
        want = {}
        for s in r.settings:
            key = s['key']
            if s['classification'] == 'carried' and CARRIED_SETTINGS.fullmatch(key):
                want[key] = values[key]
            elif s['classification'] == 'translated' and key.startswith('import_order:'):
                want[s['key40']] = values[key]
            elif s['classification'] == 'translated' and key == 'source_priority':
                try:
                    data = json.loads(values[key])
                except ValueError:
                    continue
                kept = {step: {TYPE_KIND.get(t, t): v for t, v in types.items()} for step, types in data.items() if step in CARRIED_PRIORITY_STEPS}
                if kept:
                    want[key] = kept
        got = dict(db.execute('SELECT key, value FROM main.setting').fetchall())
        got = {k: (json.loads(v) if k == 'source_priority' else v) for k, v in got.items()}
        part.maps('setting', want, got)

    # ---- 4. structure ----

    def structure(self):
        part = self.part('structure', 'foreign_key_check, integrity_check, every origin=catalogue id exists in the catalogue with the same born key')
        db = self.db
        fk = [tuple(x) for x in db.execute('PRAGMA foreign_key_check')]
        part.eq('foreign_key_check', [], fk[:5])
        part.eq('integrity_check', 'ok', db.execute('PRAGMA integrity_check').fetchone()[0])
        bad = [tuple(x) for x in db.execute('''SELECT i.id, i.born_provider, i.born_namespace, i.born_key FROM main.item i LEFT JOIN catalogue.item c ON c.id=i.id
                                              WHERE i.origin='catalogue' AND (c.id IS NULL OR c.born_provider IS NOT i.born_provider
                                                    OR c.born_namespace IS NOT i.born_namespace OR c.born_key IS NOT i.born_key) LIMIT 5''')]
        part.eq('catalogue items with the same born key', [], bad)
        bad = [tuple(x) for x in db.execute('''SELECT i.id, i.born_provider, i.born_key FROM main.color i LEFT JOIN catalogue.color c ON c.id=i.id
                                              WHERE i.origin='catalogue' AND (c.id IS NULL OR c.born_provider IS NOT i.born_provider
                                                    OR c.born_key IS NOT i.born_key) LIMIT 5''')]
        part.eq('catalogue colours with the same born key', [], bad)
        part.eq('schema_version', '4.0', db.execute("SELECT value FROM main.meta WHERE key='schema_version'").fetchone()[0])

    # ---- 5. injectivity ----

    def injectivity(self):
        part = self.part('injectivity', 'no two 3.3 keys share a 4.0 target; every target exists in the output')
        sp, db = self.space, self.db
        for target, keys in sorted(sp.inverse.items(), key=str):
            if len(keys) > 1:
                part.eq(f'target {target} is reached by one BrickLink key', 1, sorted(map(list, keys)))
        part.eq('mint.unresolved', [], [list(map(list, k)) for k in self.mint.unresolved][:5])
        part.eq('mint plan injective', [], [list(map(list, k)) for k in self.mint.check_injective()][:5])
        colours = {c for (c,) in db.execute('SELECT id FROM main.color')}
        missing = []
        for nkey, targets in sp.targets.items():
            for item_id, colour in targets:
                if item_id not in self.kinds or (colour is not None and colour not in colours):
                    missing.append((nkey, item_id, colour))
        part.eq('every target exists in the output', [], sorted(missing, key=str)[:5])

    # ---- 6. attach ----

    def attach(self):
        part = self.part('attach', 'every attached list equals the catalogue list it names, in BrickLink space, recomputed from the output')
        db, r, sp = self.db, self.r, self.space

        def bl_line(item_id, colour, spare, quantity):
            key = sp.back(item_id, colour)
            if key[0] in ('?P', '?M', '?S') or key[0] == '<unmapped>':       # a placeholder: through the output's own links, as the catalogue projects it
                found = identity.resolve(db, item_id, colour)
                if found is None:
                    return ('?', str(key[1]), None, spare, quantity)
                return (found[0], found[1], None if found[2] in (None, '0') else found[2], spare, quantity)
            return (key[0], key[1], None if key[2] is None else str(key[2]), spare, quantity)

        def catalogue_list(item_id, version):
            return db.execute('SELECT digest, bl_digest FROM catalogue.inventory WHERE item_id=? AND version=?', (item_id, version)).fetchone()

        recorded = {(a['kind'], str(a['row'])) for a in r.attach if a['status'] == 'attached'}
        found = set()
        figure_lines = defaultdict(list)
        for l in db.execute('SELECT copy_figure_id, item_id, color_id, is_spare, quantity FROM main.copy_part WHERE copy_figure_id IS NOT NULL AND quantity>0 '
                            'AND retired_at IS NULL'):
            figure_lines[l['copy_figure_id']].append(bl_line(l['item_id'], l['color_id'], l['is_spare'], l['quantity']))
        set_lines = defaultdict(list)
        for l in db.execute('SELECT copy_id, item_id, color_id, is_spare, quantity FROM main.copy_part WHERE copy_figure_id IS NULL AND quantity>0 '
                            'AND retired_at IS NULL'):
            set_lines[l['copy_id']].append(bl_line(l['item_id'], l['color_id'], l['is_spare'], l['quantity']))
        for f in db.execute('SELECT copy_id, item_id, quantity FROM main.copy_figure WHERE quantity>0 AND retired_at IS NULL'):
            key = sp.back(f['item_id'], None)
            link = identity.best_item_link(identity.confirmed_item_links(db, f['item_id'], 'bricklink'), None) if key[0].startswith('?') else None
            set_lines[f['copy_id']].append((link['provider_kind'], link['provider_key'], None, 0, f['quantity']) if link else
                                           ('?' if key[0].startswith('?') else key[0], str(key[1]), None, 0, f['quantity']))
        for c in db.execute("SELECT id, item_id, inventory_version, inventory_digest FROM main.copy WHERE inventory_source='rebrickable'"):
            found.add(('copy', c['id']))
            cat = catalogue_list(c['item_id'], c['inventory_version'])
            part.eq(f'copy {c["id"]} names a catalogue list', True, cat is not None)
            if cat is not None:
                part.eq(f'copy {c["id"]} digest is the catalogue\'s', cat['digest'], c['inventory_digest'])
                part.eq(f'copy {c["id"]} lines equal the list in BrickLink space', cat['bl_digest'], bl_digest(set_lines[c['id']]))
        for f in db.execute("SELECT id, copy_id, item_id, inventory_version, inventory_digest FROM main.copy_figure WHERE inventory_source='rebrickable'"):
            found.add(('figure', str(f['id'])))
            cat = catalogue_list(f['item_id'], f['inventory_version'])
            part.eq(f'figure line {f["id"]} names a catalogue list', True, cat is not None)
            if cat is not None:
                part.eq(f'figure line {f["id"]} digest is the catalogue\'s', cat['digest'], f['inventory_digest'])
                part.eq(f'figure line {f["id"]} lines equal the list in BrickLink space', cat['bl_digest'], bl_digest(figure_lines[f['id']]))
        loose = defaultdict(list)
        for l in db.execute('SELECT stock_id, item_id, color_id, is_spare, quantity FROM main.stock_part WHERE quantity>0 AND retired_at IS NULL'):
            loose[l['stock_id']].append(bl_line(l['item_id'], l['color_id'], l['is_spare'], l['quantity']))
        for s in db.execute("SELECT id, item_id, inventory_version, inventory_digest FROM main.stock WHERE inventory_source='rebrickable'"):
            found.add(('loose_figure', s['id']))
            cat = catalogue_list(s['item_id'], s['inventory_version'])
            part.eq(f'loose figure {s["id"]} names a catalogue list', True, cat is not None)
            if cat is not None:
                part.eq(f'loose figure {s["id"]} digest is the catalogue\'s', cat['digest'], s['inventory_digest'])
                part.eq(f'loose figure {s["id"]} lines equal the list in BrickLink space', cat['bl_digest'], bl_digest(loose[s['id']]))
        part.eq('the attached lists are the ones the writer recorded', sorted(recorded), sorted(found))
