"""Reconcile: bring the collection's projected rows in line with the attached catalogue (design 6.4).

Writes only the collection, in one transaction, an event per change under one operation key. What would override a
user's decision or drop a line is reported and left alone."""
from collections import defaultdict
import hashlib
import json
import sqlite3

from .audit import Events, need_catalogue, transaction
from .connect import check_compatible, now
from .errors import AmbiguousIdentity, NotActivated
from . import identity
from .bricklink_list import TYPE_OF_KIND, same_number_key
from .identity import project_color

PROVIDER = 'bricklink'
RANK = {'manual': 0, 'matched': 1, 'inferred': 2, 'to_check': 3}
CATALOGUE_ORIGINS = ('shipped', 'local', 'rule', 'bricklink_list')       # link origins that come from a catalogue build
ITEM_FIELDS = (('name', 'name'), ('year', 'year'), ('num_parts', 'num_parts'), ('theme_name', 'theme'), ('category_name', 'category'),
               ('size_key', 'size_key'))


def reconcile(db, *, via='cli', actor=None, operation_key=None):
    """Run reconcile against the attached catalogue; every build of it must be activated first. Returns the report, which
    is also stored under `reconcile` in the newest activated build's counts_json. A second run changes nothing."""
    need_catalogue(db, 'reconcile')
    with transaction(db, 'reconcile'):
        check_compatible(db)
        have = {r[0] for r in db.execute('SELECT id FROM main.catalogue_build')}
        missing = [r[0] for r in db.execute('SELECT id FROM catalogue.build ORDER BY id') if r[0] not in have]
        if missing:
            raise NotActivated(f'catalogue builds {missing} are not activated in this collection; activate first')
        events = Events(db, via, actor, operation_key)
        report = dict(operation_key=events.operation_key, changes=defaultdict(int), not_applied=defaultdict(list))
        run = _Run(db, events, report['changes'])
        _adopt(run, report)
        _items(run, report)
        _item_links(run, report)
        _colours(run, report)
        _colour_links(run, report)
        _same_number_pass(run, report)
        _bricklink_names(run, report)
        _merge_report(run, report)
        _inventory_report(run, report)
        report['coverage'] = _coverage(db)
        report['changes'] = dict(report['changes'])
        report['not_applied'] = {k: v for k, v in report['not_applied'].items() if v}
        report['events'] = run.events.count
        newest = db.execute('SELECT id, counts_json FROM main.catalogue_build ORDER BY id DESC LIMIT 1').fetchone()
        counts = json.loads(newest['counts_json'])
        counts['reconcile'] = report
        db.execute('UPDATE main.catalogue_build SET counts_json=? WHERE id=?', (json.dumps(counts, sort_keys=True), newest['id']))
        db.execute('UPDATE main.catalogue_build SET reconciled_at=? WHERE reconciled_at IS NULL', (run.stamp,))
    return report


class _Run:
    def __init__(self, db, events, changes):
        self.db, self.events, self.changes, self.stamp = db, events, changes, now()

    def event(self, *args):
        self.events.write(*args)



def _list_loaded(db):
    return db.execute('SELECT 1 FROM catalogue.bricklink_item LIMIT 1').fetchone() is not None


def _same_number_pass(run, report):
    """The `same_number` candidate pass (design 6.4, Q20, decision 8), when the catalogue has a BrickLink list: every projected
    Rebrickable-born item that has no BrickLink link of any status, and whose born key is a BrickLink number of the type for its
    kind, gets a `to_check` link. Never `matched`. The catalogue's own pass has done this for its items already (their links
    were mirrored above); this one reaches the rest, such as a local item the dump does not number yet."""
    db = run.db
    if not _list_loaded(db):
        report['same_number'] = None
        return
    list_build = db.execute("SELECT max(id) FROM catalogue.build WHERE kind='bricklink_list'").fetchone()[0]
    added = []
    for r in db.execute("""SELECT m.id, m.kind, m.born_namespace, m.born_key FROM main.item m
                           WHERE m.born_provider='rebrickable' AND m.merged_into IS NULL AND m.catalogue_retired_at IS NULL
                             AND NOT EXISTS(SELECT 1 FROM main.item_link l WHERE l.item_id=m.id AND l.provider=?) ORDER BY m.id""", (PROVIDER,)).fetchall():
        item_type = TYPE_OF_KIND[r['kind']]
        number = same_number_key(item_type, r['born_namespace'], r['born_key'])      # the same rule as the catalogue's own pass
        if number is None or not db.execute('SELECT 1 FROM catalogue.bricklink_item WHERE item_type=? AND item_no=?', (item_type, number)).fetchone():
            continue
        link_id = db.execute("""INSERT INTO main.item_link(item_id, provider, provider_kind, provider_key, status, method, origin, preferred,
                                evidence_digest, catalogue_build_id, decided_at, decided_by) VALUES(?, ?, ?, ?, 'to_check', 'same_number',
                                'bricklink_list', 0, ?, ?, ?, ?) RETURNING id""",
                             (r['id'], PROVIDER, item_type, number, _evidence('same_number', item_type, number), list_build,
                              run.stamp, run.events.actor)).fetchone()[0]
        run.event('item_link', link_id, 'inserted', None, dict(item_id=r['id'], provider=PROVIDER, provider_kind=item_type,
                                                               provider_key=number, status='to_check', method='same_number'))
        added.append(r['id'])
    if added:
        run.changes['same_number_added'] = len(added)
    report['same_number'] = dict(list_build=list_build, added=sorted(added))


def _evidence(*fields):
    return hashlib.sha256('\x1f'.join(str(f) for f in fields).encode()).hexdigest()


def _bricklink_names(run, report):
    """BrickLink's name of every item whose links resolve (design 3.2, unscoped) to a BrickLink list entry, as
    item_property(key='name', source='bricklink'); added, and refreshed when the list's name changes."""
    db = run.db
    if not _list_loaded(db):
        report['bricklink_names'] = None
        return
    rows = defaultdict(list)
    for r in db.execute(f"""SELECT l.item_id, l.provider_kind, l.provider_key, l.color_id, l.preferred, l.status FROM main.item_link l
                            JOIN main.item m ON m.id=l.item_id WHERE m.merged_into IS NULL AND l.provider=? AND l.status IN ({','.join('?' * len(identity.CONFIRMED))})
                            ORDER BY l.item_id""", (PROVIDER, *identity.CONFIRMED)):
        rows[r['item_id']].append(dict(r))
    unresolved = 0
    for item_id, links in sorted(rows.items()):
        best = identity.best_item_link(links, None)
        named = db.execute('SELECT name FROM catalogue.bricklink_item WHERE item_type=? AND item_no=?',
                           (best['provider_kind'], best['provider_key'])).fetchone() if best else None
        if named is None:
            unresolved += 1
            continue
        old = db.execute("SELECT value FROM main.item_property WHERE item_id=? AND key='name' AND source=?", (item_id, PROVIDER)).fetchone()
        if old is None:
            db.execute("INSERT INTO main.item_property(item_id, key, source, value, fetched_at) VALUES(?, 'name', ?, ?, ?)",
                       (item_id, PROVIDER, named[0], run.stamp))
            run.changes['bricklink_names_added'] += 1
        elif old[0] != named[0]:
            db.execute("UPDATE main.item_property SET value=?, fetched_at=? WHERE item_id=? AND key='name' AND source=?",
                       (named[0], run.stamp, item_id, PROVIDER))
            run.changes['bricklink_names_refreshed'] += 1
        else:
            continue
        run.event('item', item_id, 'property.name.bricklink', old and old[0], named[0])
    report['bricklink_names'] = dict(unresolved=unresolved)


# ---------- adoption (rule 5) ----------

def _adopt(run, report):
    db = run.db
    flip = db.execute('''SELECT m.id FROM main.item m JOIN catalogue.item c ON c.id=m.id AND c.born_namespace=m.born_namespace AND c.born_key=m.born_key
                         WHERE m.origin='local' AND m.born_provider='rebrickable' AND c.adopted=1 AND m.merged_into IS NULL ORDER BY m.id''').fetchall()
    for (item_id,) in flip:
        db.execute("UPDATE main.item SET origin='catalogue', updated_at=? WHERE id=?", (run.stamp, item_id))
        run.event('item', item_id, 'origin', 'local', 'catalogue')
    report['adopted'] = [r[0] for r in flip]
    if flip:
        run.changes['adopted'] = len(flip)
    report['adoption_skipped_merged'] = [dict(item_id=r['id'], namespace=r['born_namespace'], born_key=r['born_key'], merged_into=r['merged_into'])
                                         for r in db.execute('''SELECT m.id, m.born_namespace, m.born_key, m.merged_into FROM main.item m
                              JOIN catalogue.item c ON c.born_provider=m.born_provider AND c.born_namespace=m.born_namespace AND c.born_key=m.born_key
                              WHERE m.origin='local' AND m.born_provider='rebrickable' AND m.merged_into IS NOT NULL ORDER BY m.id''')]


# ---------- names, properties, kinds, retirement (rules 1, 2, 4) ----------

def _items(run, report):
    db, changes = run.db, run.changes
    rows = db.execute('''SELECT m.*, c.kind AS c_kind, c.kind_source AS c_kind_source, c.name AS c_name, c.year AS c_year,
                                c.num_parts AS c_num_parts, t.name AS c_theme, pc.name AS c_category, c.size_key AS c_size_key,
                                c.digest AS c_digest, c.build_id AS c_build, c.retired_at AS c_retired
                         FROM main.item m JOIN catalogue.item c ON c.id=m.id AND c.born_provider=m.born_provider
                              AND c.born_namespace=m.born_namespace AND c.born_key=m.born_key
                         LEFT JOIN catalogue.theme t ON t.id=c.theme_id LEFT JOIN catalogue.part_category pc ON pc.id=c.category_id
                         WHERE m.origin='catalogue' AND m.merged_into IS NULL ORDER BY m.id''').fetchall()
    report['id_mismatch'] = [dict(item_id=r['id'], born_key=r['born_key']) for r in db.execute(
        '''SELECT m.id, m.born_key FROM main.item m WHERE m.origin='catalogue' AND m.merged_into IS NULL AND NOT EXISTS(
           SELECT 1 FROM catalogue.item c WHERE c.id=m.id AND c.born_provider=m.born_provider AND c.born_namespace=m.born_namespace
           AND c.born_key=m.born_key) ORDER BY m.id''')]
    for r in rows:
        # 1. names and properties: when the digest differs (or a projected name, such as a renamed theme, does)
        fields = [(col, r[col], r['c_' + src]) for col, src in ITEM_FIELDS if r[col] != r['c_' + src]]
        if fields or r['digest'] != r['c_digest']:
            sets = ', '.join(f'{col}=?' for col, _, _ in fields)
            db.execute(f'UPDATE main.item SET {sets + ", " if sets else ""}digest=?, catalogue_build_id=?, updated_at=? WHERE id=?',
                       (*[new for _, _, new in fields], r['c_digest'], r['c_build'], run.stamp, r['id']))
            for col, old, new in fields:
                run.event('item', r['id'], col, old, new)
            changes['items_refreshed'] += 1
        # 2. kinds (3.5); kind_source='manual' is the user's and is never touched
        if r['kind_source'] != 'manual':
            _kind(run, report, r)
        # 4. retirement, set and cleared
        if (r['catalogue_retired_at'] or None) != (r['c_retired'] or None):
            db.execute('UPDATE main.item SET catalogue_retired_at=?, updated_at=? WHERE id=?', (r['c_retired'], run.stamp, r['id']))
            run.event('item', r['id'], 'catalogue_retired_at', r['catalogue_retired_at'], r['c_retired'])
            changes['retirement_set' if r['c_retired'] else 'retirement_cleared'] += 1


def _kind(run, report, r):
    db, changes = run.db, run.changes
    if r['kind'] != r['c_kind']:
        try:
            db.execute('UPDATE main.item SET kind=?, kind_source=?, updated_at=? WHERE id=?', (r['c_kind'], r['c_kind_source'], run.stamp, r['id']))
        except sqlite3.IntegrityError as e:                              # item_kind_guard: referenced as its current kind
            if 'kind change refused' not in str(e):
                raise
            evidence = json.dumps({'from': r['kind'], 'to': r['c_kind']}, sort_keys=True)
            old = db.execute("SELECT evidence_json FROM main.item_provider_status WHERE item_id=? AND provider=? AND reason='kind_differs'",
                             (r['id'], PROVIDER)).fetchone()
            if old is None:
                db.execute('''INSERT INTO main.item_provider_status(item_id, provider, status, reason, evidence_json, checked_at)
                              VALUES(?, ?, 'to_check', 'kind_differs', ?, ?)''', (r['id'], PROVIDER, evidence, run.stamp))
            elif old[0] != evidence:
                db.execute("UPDATE main.item_provider_status SET evidence_json=?, checked_at=? WHERE item_id=? AND provider=? AND reason='kind_differs'",
                           (evidence, run.stamp, r['id'], PROVIDER))
            if old is None or old[0] != evidence:
                run.event('item', r['id'], 'provider_status.kind_differs', old and old[0], evidence)
                changes['kind_differs'] += 1
            report['not_applied']['kind_differs'].append(dict(item_id=r['id'], born_key=r['born_key'], kind=r['kind'], catalogue_kind=r['c_kind']))
            return
        run.event('item', r['id'], 'kind', r['kind'], r['c_kind'])
        changes['kinds_changed'] += 1
    elif r['kind_source'] != r['c_kind_source']:
        db.execute('UPDATE main.item SET kind_source=?, updated_at=? WHERE id=?', (r['c_kind_source'], run.stamp, r['id']))
        run.event('item', r['id'], 'kind_source', r['kind_source'], r['c_kind_source'])
        changes['kind_sources_changed'] += 1
    # the kinds agree now: an earlier kind_differs row has done its work
    gone = db.execute("DELETE FROM main.item_provider_status WHERE item_id=? AND provider=? AND reason='kind_differs' RETURNING evidence_json",
                      (r['id'], PROVIDER)).fetchone()
    if gone:
        run.event('item', r['id'], 'provider_status.kind_differs', gone[0], None)
        changes['kind_differs_cleared'] += 1


# ---------- links (rule 3) ----------
#
# One rule for every automatic change to a link (insert, upgrade, to_check replacement). Protection comes only from decisions
# that existed before this reconcile started: a baseline answer (forward: the key an item or colour resolves to in a scope;
# inverse: the one item or colour a provider key resolves to) whose winning link is manual or matched. A change is applied
# unless it would alter such a baseline answer; then it is reported as would_change_resolution and rolled back. Everything
# else follows the catalogue's ranking, in any order the changes are applied. The answers come from identity's own ranking
# helpers and resolve_inverse, run on the real rows inside a savepoint, so the guard and the resolver cannot disagree.

CERTAIN = ('manual', 'matched')


def _guarded(run, apply, check):
    """Run `apply` (the write) inside a savepoint; keep it only if `check()` finds no protected answer changed."""
    db = run.db
    db.execute('SAVEPOINT guard')
    try:
        result = apply()
        refusal = check()
        if refusal:
            db.execute('ROLLBACK TO guard')
            return None, refusal
        return result, None
    finally:
        db.execute('RELEASE guard')


def _pick(row):
    return row and [row.get('provider_kind'), row['provider_key'], row['status']]


def _item_forward(db, base_rows, c):
    """Forward baseline: the scope's answer before the run, if it was manual or matched, must be the same now."""
    scope = c['color_id']
    before = identity.best_item_link(base_rows, scope)
    if before is None or before['status'] not in CERTAIN:
        return None
    after = identity.best_item_link(identity.confirmed_item_links(db, c['item_id'], c['provider']), scope)
    if after is None or (after['provider_kind'], after['provider_key']) != (before['provider_kind'], before['provider_key']):
        return dict(direction='forward', before=_pick(before), after=_pick(after))
    return None


def _generic_colour(db, provider, scopes):
    """(colour id, provider colour key) of a projected colour that is none of `scopes`, not colour 1, and that its own key
    resolves back to; None if there is none."""
    for (colour,) in db.execute('SELECT id FROM main.color WHERE id>2 ORDER BY id'):
        if colour in scopes:
            continue
        best = identity.best_color_link(identity.confirmed_color_links(db, colour, provider))
        if best is None:
            continue
        try:
            if identity._inverse_color(db, provider, best['provider_key']) == colour:
                return colour, best['provider_key']
        except AmbiguousIdentity:
            continue
    return None


def _inverse_state(db, provider, kind, key):
    """{colour or None: (item_id | 'ambiguous', status) | None}: what the identity resolves to, over the colours that can
    matter for it (colours its rows or its items' rows are scoped to, plus any other colour as None)."""
    rows = [dict(r) for r in db.execute('''SELECT item_id, color_id, preferred, status FROM main.item_link
                                          WHERE provider=? AND provider_kind=? AND provider_key=? AND status IN ('manual', 'matched', 'inferred')''',
                                       (provider, kind, key))]
    items = {r['item_id'] for r in rows}
    scopes = {r['color_id'] for r in rows if r['color_id'] is not None}
    for item in items:
        scopes |= {r['color_id'] for r in identity.confirmed_item_links(db, item, provider) if r['color_id'] is not None}
    out = {}
    # None stands for every colour without an explicit scope. It is probed through a real projected colour outside the scopes
    # and not colour 1 ("no colour", which the resolver reads from a None colour key and which can have scoped rows of its own).
    generic = _generic_colour(db, provider, scopes)
    for colour in sorted(scopes) + ([None] if generic else []):
        if colour is None:
            ckey = generic[1]
        elif colour == 1:
            ckey = None
        else:
            best = identity.best_color_link(identity.confirmed_color_links(db, colour, provider))
            if best is None:
                continue
            ckey = best['provider_key']
        try:
            found = identity.resolve_inverse(db, kind, key, ckey, provider)
        except AmbiguousIdentity:
            out[colour] = ('ambiguous', None)
            continue
        if found is None:
            out[colour] = None
            continue
        applying = [r for r in rows if r['item_id'] == found[0] and r['color_id'] in (found[1], None)]
        out[colour] = (found[0], min(applying, key=lambda r: identity._RANK[r['status']])['status'] if applying else 'catalogue')
    return out


def _item_inverse(db, provider, kind, key, base):
    after = _inverse_state(db, provider, kind, key)
    for colour in set(base) | set(after):
        before = base.get(colour, base.get(None))
        if before is None or before[0] == 'ambiguous' or before[1] not in CERTAIN:
            continue
        now_ = after.get(colour, after.get(None))
        if now_ is None or now_[0] != before[0]:
            return dict(direction='inverse', colour=colour, before=list(before), after=now_ and list(now_))
    return None


def _item_links(run, report):
    db, changes = run.db, run.changes
    live = "m.origin='catalogue' AND m.merged_into IS NULL"
    theirs, mine = defaultdict(dict), defaultdict(dict)
    for r in db.execute(f'SELECT l.* FROM catalogue.item_link l JOIN main.item m ON m.id=l.item_id WHERE {live} ORDER BY l.id'):
        theirs[r['item_id']][_key(r)] = dict(r)
    for r in db.execute(f'SELECT l.* FROM main.item_link l JOIN main.item m ON m.id=l.item_id WHERE {live} ORDER BY l.id'):
        mine[r['item_id']][_key(r)] = dict(r)
    out = report['not_applied']['links']
    baseline = {i: [dict(r) for r in rows.values() if r['status'] in identity.CONFIRMED] for i, rows in mine.items()}
    # the baseline inverse answers, for the identities a candidate change touches, before anything is written
    inverse = {}
    for item_id, links in theirs.items():
        for key, c in links.items():
            m = mine[item_id].get(key)
            if m is None or (m['status'] != 'manual' and c['status'] == 'matched' and m['status'] != 'matched'):
                idents = [(c['provider'], c['provider_kind'], c['provider_key'])]
                if c['color_id'] is not None:      # a scoped row suppresses the item's unscoped rows in that colour: their inverse answers are at stake too
                    idents += [(r['provider'], r['provider_kind'], r['provider_key']) for r in baseline.get(item_id, [])
                               if r['color_id'] is None and r['provider'] == c['provider']]
                for ident in idents:
                    if ident not in inverse:
                        inverse[ident] = _inverse_state(db, *ident)

    def refuse(item_id, c, refusal, **extra):
        out.append(dict(reason='would_change_resolution', item_id=item_id, provider=c['provider'], color_id=c['color_id'], provider_kind=c['provider_kind'],
                        catalogue_key=c['provider_key'], catalogue_status=c['status'], **refusal, **extra))

    def check(item_id, c):
        base = [r for r in baseline.get(item_id, []) if r['provider'] == c['provider']]
        found = _item_forward(db, base, dict(c, item_id=item_id))
        idents = [(c['provider'], c['provider_kind'], c['provider_key'])]
        if c['color_id'] is not None:
            idents += [(r['provider'], r['provider_kind'], r['provider_key']) for r in base if r['color_id'] is None]
        for ident in idents:
            found = found or _item_inverse(db, *ident, inverse[ident])
        return found

    for item_id in sorted(set(theirs) | set(mine)):
        for key, c in theirs[item_id].items():
            m = mine[item_id].get(key)
            if m is None:
                insert = lambda: db.execute('''INSERT INTO main.item_link(item_id, color_id, provider, provider_kind, provider_key, status, method, origin,
                                       preferred, evidence_digest, catalogue_build_id, decided_at, decided_by) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                       RETURNING id''', (item_id, c['color_id'], c['provider'], c['provider_kind'], c['provider_key'], c['status'],
                                                         c['method'], c['origin'], 0, c['evidence_digest'], c['build_id'], run.stamp,
                                                         run.events.actor)).fetchone()[0]
                new_id, refusal = _guarded(run, insert, lambda: check(item_id, c))
                if refusal:
                    refuse(item_id, c, refusal, action='insert')
                    continue
                run.event('item_link', new_id, 'inserted', None, dict(item_id=item_id, provider=c['provider'], provider_kind=c['provider_kind'],
                                                                      provider_key=c['provider_key'], color_id=c['color_id'], status=c['status']))
                changes['links_inserted'] += 1
                if c['status'] == 'matched':
                    _clear_provider_status(run, item_id, c['provider'])
            elif m['status'] != 'manual' and c['status'] != m['status']:
                if c['status'] == 'matched':                           # inferred -> matched, or matched replaces a to_check of the same key
                    evidence = dict(was=m['status'], method=c['method'], origin=c['origin'], evidence_digest=c['evidence_digest'], build_id=c['build_id'])
                    upgrade = lambda: db.execute('''UPDATE main.item_link SET status='matched', method=?, origin=?, evidence_digest=?, evidence_json=?,
                                  catalogue_build_id=?, decided_at=?, decided_by=? WHERE id=?''',
                                                 (c['method'], c['origin'], c['evidence_digest'], json.dumps(evidence, sort_keys=True), c['build_id'],
                                                  run.stamp, run.events.actor, m['id']))
                    _, refusal = _guarded(run, upgrade, lambda: check(item_id, c))
                    if refusal:
                        refuse(item_id, c, refusal, action='upgrade', link_id=m['id'])
                        continue
                    run.event('item_link', m['id'], 'status', m['status'], 'matched')
                    changes['links_upgraded' if m['status'] == 'inferred' else 'links_replaced'] += 1
                    _clear_provider_status(run, item_id, c['provider'])
                elif RANK[c['status']] > RANK[m['status']]:            # a downgrade is never applied
                    out.append(dict(reason='downgrade', item_id=item_id, link_id=m['id'], provider=c['provider'],
                                    provider_kind=c['provider_kind'], provider_key=c['provider_key'], color_id=c['color_id'],
                                    collection_status=m['status'], catalogue_status=c['status']))
        _preferred(run, report, item_id, [c for c in theirs[item_id].values() if c['preferred']], baseline)
        for key, m in mine[item_id].items():
            if key not in theirs[item_id] and m['catalogue_build_id'] is not None and m['origin'] in CATALOGUE_ORIGINS:
                out.append(dict(reason='vanished', item_id=item_id, link_id=m['id'], provider=m['provider'],
                                provider_kind=m['provider_kind'], provider_key=m['provider_key'], color_id=m['color_id'],
                                collection_status=m['status']))


def _preferred(run, report, item_id, preferred, baseline):
    """The catalogue's preferred flag per (item, provider, colour scope) moves the collection's, unless the collection's
    current preferred row is a user decision (reported). A move is an automatic change and runs under the resolution guard."""
    db, out = run.db, report['not_applied']['links']
    for c in preferred:
        row = db.execute('SELECT * FROM main.item_link WHERE item_id=? AND provider=? AND provider_kind=? AND provider_key=? AND coalesce(color_id,0)=?',
                         (item_id, c['provider'], c['provider_kind'], c['provider_key'], c['color_id'] or 0)).fetchone()
        if row is None:                                                   # its insert was refused
            continue
        cur = db.execute('SELECT * FROM main.item_link WHERE item_id=? AND provider=? AND coalesce(color_id,0)=? AND preferred=1',
                         (item_id, c['provider'], c['color_id'] or 0)).fetchone()
        if cur and cur['id'] == row['id']:
            continue
        if cur and (cur['origin'] == 'user' or cur['status'] == 'manual'):
            out.append(dict(reason='preferred_differs', item_id=item_id, provider=c['provider'], color_id=c['color_id'], link_id=cur['id'],
                            collection_key=cur['provider_key'], catalogue_kind=c['provider_kind'], catalogue_key=c['provider_key']))
            continue

        def move():
            if cur:
                db.execute('UPDATE main.item_link SET preferred=0 WHERE id=?', (cur['id'],))
            db.execute('UPDATE main.item_link SET preferred=1 WHERE id=?', (row['id'],))

        base = [r for r in baseline.get(item_id, []) if r['provider'] == c['provider']]
        _, refusal = _guarded(run, move, lambda: _item_forward(db, base, dict(c, item_id=item_id)))
        if refusal:
            out.append(dict(reason='would_change_resolution', item_id=item_id, provider=c['provider'], color_id=c['color_id'], provider_kind=c['provider_kind'],
                            catalogue_key=c['provider_key'], catalogue_status=c['status'], action='prefer', **refusal))
            continue
        if cur:
            run.event('item_link', cur['id'], 'preferred', 1, 0)
        run.event('item_link', row['id'], 'preferred', 0, 1)
        run.changes['preferred_moved'] += 1


def _key(r):
    return r['provider'], r['provider_kind'], r['provider_key'], r['color_id']


def _clear_provider_status(run, item_id, provider):
    """New matched evidence replaces "looked, nothing found" and "no candidate" for that provider."""
    for reason, status in run.db.execute("DELETE FROM main.item_provider_status WHERE item_id=? AND provider=? AND reason IN ('no_match', 'no_candidate') "
                                         "RETURNING reason, status", (item_id, provider)).fetchall():
        run.event('item', item_id, f'provider_status.{reason}', status, None)
        run.changes['provider_status_replaced'] += 1


# ---------- colours ----------

def _colours(run, report):
    db = run.db
    for r in db.execute('''SELECT m.id, m.name, m.rgb, m.is_trans, c.name AS c_name, c.rgb AS c_rgb, c.is_trans AS c_is_trans FROM main.color m
                           JOIN catalogue.color c ON c.id=m.id AND c.born_key=m.born_key WHERE m.origin='catalogue' ORDER BY m.id''').fetchall():
        fields = [(f, r[f], r['c_' + f]) for f in ('name', 'rgb', 'is_trans') if r[f] != r['c_' + f]]
        if fields:
            db.execute(f'UPDATE main.color SET {", ".join(f + "=?" for f, _, _ in fields)}, updated_at=? WHERE id=?',
                       (*[new for _, _, new in fields], run.stamp, r['id']))
            for f, old, new in fields:
                run.event('color', r['id'], f, old, new)
            run.changes['colours_refreshed'] += 1
    # a colour the catalogue gained since activation has no row yet (activation projects them, so this is a safety net)
    for (color_id,) in db.execute('SELECT id FROM catalogue.color WHERE id NOT IN (SELECT id FROM main.color)').fetchall():
        project_color(db, color_id)
        run.event('color', color_id, 'projected', None, color_id)
        run.changes['colours_projected'] += 1


def _color_inverse(db, provider, key):
    """(colour, status) the provider colour key names, ('ambiguous', None), or None."""
    try:
        colour = identity._inverse_color(db, provider, key)
    except AmbiguousIdentity:
        return 'ambiguous', None
    if colour is None:
        return None
    row = db.execute('SELECT status FROM main.color_link WHERE color_id=? AND provider=? AND provider_key=?', (colour, provider, key)).fetchone()
    return colour, row[0] if row else 'catalogue'


def _colour_links(run, report):
    db = run.db
    theirs, mine = defaultdict(dict), defaultdict(dict)
    for r in db.execute("SELECT l.* FROM catalogue.color_link l JOIN main.color m ON m.id=l.color_id WHERE m.origin='catalogue' ORDER BY l.id"):
        theirs[r['color_id']][(r['provider'], r['provider_key'])] = dict(r)
    for r in db.execute("SELECT l.* FROM main.color_link l JOIN main.color m ON m.id=l.color_id WHERE m.origin='catalogue' ORDER BY l.id"):
        mine[r['color_id']][(r['provider'], r['provider_key'])] = dict(r)
    out = report['not_applied']['colour_links']
    baseline = {c: [r for r in rows.values() if r['status'] in identity.CONFIRMED] for c, rows in mine.items()}
    inverse = {}                                                          # baseline inverse answers of the keys a candidate touches
    for color_id, links in theirs.items():
        for key, c in links.items():
            m = mine[color_id].get(key)
            if m is None or (m['status'] != 'manual' and c['status'] == 'matched' and m['status'] != 'matched'):
                inverse.setdefault(key, _color_inverse(db, *key))

    def check(color_id, c):
        rows = [r for r in baseline.get(color_id, []) if r['provider'] == c['provider']]
        before = identity.best_color_link(rows)
        if before and before['status'] in CERTAIN:
            after = identity.best_color_link(identity.confirmed_color_links(db, color_id, c['provider']))
            if after is None or after['provider_key'] != before['provider_key']:
                return dict(direction='forward', before=_pick(before), after=_pick(after))
        before = inverse[(c['provider'], c['provider_key'])]
        if before and before[0] != 'ambiguous' and before[1] in CERTAIN:
            after = _color_inverse(db, c['provider'], c['provider_key'])
            if after is None or after[0] != before[0]:
                return dict(direction='inverse', before=list(before), after=after and list(after))
        return None

    def refuse(color_id, c, refusal, **extra):
        out.append(dict(reason='would_change_resolution', color_id=color_id, provider=c['provider'], catalogue_key=c['provider_key'],
                        catalogue_status=c['status'], **refusal, **extra))

    for color_id in sorted(set(theirs) | set(mine)):
        for key, c in theirs[color_id].items():
            m = mine[color_id].get(key)
            if m is None:
                flag = c['inverse_preferred'] and not db.execute('SELECT 1 FROM main.color_link WHERE provider=? AND provider_key=? AND inverse_preferred=1',
                                                                 (c['provider'], c['provider_key'])).fetchone()
                insert = lambda: db.execute('''INSERT INTO main.color_link(color_id, provider, provider_key, provider_name, status, method, inverse_preferred,
                                       catalogue_build_id, decided_at, decided_by) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id''',
                                           (color_id, c['provider'], c['provider_key'], c['provider_name'], c['status'], c['method'], int(bool(flag)),
                                            c['build_id'], run.stamp, run.events.actor)).fetchone()[0]
                new_id, refusal = _guarded(run, insert, lambda: check(color_id, c))
                if refusal:
                    refuse(color_id, c, refusal, action='insert')
                    continue
                run.event('color_link', new_id, 'inserted', None, dict(color_id=color_id, provider=c['provider'], provider_key=c['provider_key'],
                                                                       status=c['status']))
                run.changes['colour_links_inserted'] += 1
                if bool(flag) != bool(c['inverse_preferred']):    # the collection's holder keeps the preference: the move is reported, not applied
                    out.append(dict(reason='inverse_preferred_differs', color_id=color_id, link_id=new_id, provider=c['provider'],
                                    provider_key=c['provider_key'], collection=0, catalogue=1))
                continue
            if m['status'] != 'manual' and c['status'] != m['status']:
                if c['status'] == 'matched':
                    upgrade = lambda: db.execute("UPDATE main.color_link SET status='matched', method=?, catalogue_build_id=?, decided_at=?, decided_by=? WHERE id=?",
                                                 (c['method'], c['build_id'], run.stamp, run.events.actor, m['id']))
                    _, refusal = _guarded(run, upgrade, lambda: check(color_id, c))
                    if refusal:
                        refuse(color_id, c, refusal, action='upgrade', link_id=m['id'])
                    else:
                        run.event('color_link', m['id'], 'status', m['status'], 'matched')
                        run.changes['colour_links_upgraded'] += 1
                elif RANK[c['status']] > RANK[m['status']]:
                    out.append(dict(reason='downgrade', color_id=color_id, link_id=m['id'], provider=c['provider'], provider_key=c['provider_key'],
                                    collection_status=m['status'], catalogue_status=c['status']))
            if m['inverse_preferred'] != c['inverse_preferred'] and m['status'] in ('manual', 'matched'):
                out.append(dict(reason='inverse_preferred_differs', color_id=color_id, link_id=m['id'], provider=c['provider'],
                                provider_key=c['provider_key'], collection=m['inverse_preferred'], catalogue=c['inverse_preferred']))
        for key, m in mine[color_id].items():
            if key not in theirs[color_id] and m['catalogue_build_id'] is not None:
                out.append(dict(reason='vanished', color_id=color_id, link_id=m['id'], provider=m['provider'], provider_key=m['provider_key'],
                                collection_status=m['status']))


# ---------- report only: merges (rule 6) ----------

def _merge_report(run, report):
    db = run.db
    carried = {}
    for (counts,) in db.execute('SELECT counts_json FROM catalogue.build ORDER BY id DESC'):
        data = json.loads(counts)
        if 'shadowed_local' in data:
            carried = data                                              # the newest build that recorded them
            break
    for name in ('shadowed_local', 'merged_local', 'merged_returning'):
        report[name] = carried.get(name, [])
    # invariant 4: a live catalogue row must never name a merged collection id (the merge race, issue 104)
    report['merged_live_in_catalogue'] = [dict(item_id=r['id'], born_key=r['born_key'], merged_into=r['merged_into']) for r in db.execute(
        '''SELECT c.id, c.born_key, m.merged_into FROM catalogue.item c JOIN main.item m ON m.id=c.id
           WHERE m.merged_into IS NOT NULL AND c.retired_at IS NULL ORDER BY c.id''')]


# ---------- report only: part lists whose digest changed (rule 7) ----------

def _inventory_report(run, report):
    db = run.db
    queries = ('''SELECT 'copy' AS tbl, x.id, x.item_id, x.inventory_version, x.inventory_digest FROM main.copy x
                  WHERE x.inventory_source='rebrickable' AND x.archived_at IS NULL''',
               '''SELECT 'copy_figure' AS tbl, x.id, x.item_id, x.inventory_version, x.inventory_digest FROM main.copy_figure x
                  JOIN main.copy c ON c.id=x.copy_id WHERE x.inventory_source='rebrickable' AND x.retired_at IS NULL AND c.archived_at IS NULL''',
               '''SELECT 'stock' AS tbl, x.id, x.item_id, x.inventory_version, x.inventory_digest FROM main.stock x
                  WHERE x.inventory_source='rebrickable' AND x.archived_at IS NULL''')
    listed = []
    for sql in queries:
        for r in db.execute(sql).fetchall():
            inv = db.execute('SELECT digest, retired_at FROM catalogue.inventory WHERE item_id=? AND version=?', (r['item_id'], r['inventory_version'])).fetchone()
            if inv is None:
                reasons = ['version_missing']
            else:
                reasons = (['version_retired'] if inv['retired_at'] else []) + (['digest_changed'] if inv['digest'] != r['inventory_digest'] else [])
            if reasons:
                listed.append(dict(table=r['tbl'], id=r['id'], item_id=r['item_id'], inventory_version=r['inventory_version'], reasons=reasons))
    report['inventory_changes'] = listed


# ---------- coverage (Q20, G8) ----------

def _coverage(db):
    """Per kind, the projected items by the best BrickLink link they hold."""
    names = {0: 'manual', 1: 'matched', 2: 'inferred', 3: 'to_check'}
    out = {}
    for r in db.execute('''SELECT m.kind, (SELECT min(CASE l.status WHEN 'manual' THEN 0 WHEN 'matched' THEN 1 WHEN 'inferred' THEN 2 ELSE 3 END)
                                           FROM main.item_link l WHERE l.item_id=m.id AND l.provider=?) AS best
                           FROM main.item m WHERE m.origin='catalogue' AND m.merged_into IS NULL''', (PROVIDER,)):
        kind = out.setdefault(r['kind'], dict(manual=0, matched=0, inferred=0, to_check=0, none=0))
        kind['none' if r['best'] is None else names[r['best']]] += 1
    return dict(sorted(out.items()))
