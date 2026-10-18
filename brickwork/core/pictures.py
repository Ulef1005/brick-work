"""Bulk picture refresh over canonical, colour-specific collection identities."""
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path

from . import admin
from .pipeline import Pipeline, TYPES, cooperative
from .sources import base, images

TYPE_LABELS = dict(S='Sets', M='Minifigures', P='Parts', I='Instructions', O='Boxes',
                   G='Gear', B='Books', C='Catalogs')
SOURCES = {'priority', 'bricklink', 'rebrickable', 'existing'}


# Shared deduplicated holdings, including colour-specific parts and placeholders.
HELD = '''WITH held(item_type,item_no,color_id) AS (
        SELECT item_type,set_no,NULL FROM copies WHERE archived_at IS NULL
        UNION SELECT p.item_type,p.item_no,p.color_id FROM copy_parts p JOIN copies c ON c.id=p.copy_id WHERE c.archived_at IS NULL
        UNION SELECT m.item_type,m.minifig_no,NULL FROM copy_minifigs m JOIN copies c ON c.id=m.copy_id WHERE c.archived_at IS NULL
        UNION SELECT item_type,item_no,color_id FROM loose_stock WHERE archived_at IS NULL
        UNION SELECT p.item_type,p.item_no,p.color_id FROM loose_minifig_parts p JOIN loose_stock s ON s.id=p.stock_id WHERE s.archived_at IS NULL
        UNION SELECT item_type,item_no,color_id FROM wishlist WHERE archived_at IS NULL)
'''


def state(db):
    """Coverage from database rows only (cache rows estimate presence without file I/O)."""
    # The holdings union is the expensive part: evaluate it once and aggregate in Python.
    held = db.execute(HELD + 'SELECT h.item_type,h.item_no,h.color_id FROM held h JOIN items i USING(item_type,item_no)').fetchall()
    unresolved_ids = {(r[0], r[1]) for r in db.execute(
        "SELECT DISTINCT item_type,item_no FROM id_match WHERE status IN ('to_check','unmatched')")}
    # A picture without a colour serves every colour of the identity.
    stored = defaultdict(set)
    for r in db.execute("""SELECT DISTINCT item_type,item_no,color_id,source FROM item_images
            WHERE copy_id IS NULL AND stock_id IS NULL AND local_path IS NOT NULL"""):
        stored[r[0], r[1]].add((r[2], r[3]))
    totals = defaultdict(lambda: defaultdict(int))
    source_found = set()
    for kind, number, colour in held:
        matching = [source for found, source in stored.get((kind, number), ()) if found is None or found == colour]
        present = bool(matching)
        unresolved = kind == '?' or (kind, number) in unresolved_ids
        unknown = kind == 'P' and colour is None and not unresolved
        t = totals[kind]
        t['total'] += 1
        t['with_picture'] += present
        t['missing'] += not present
        t['unresolved'] += unresolved
        t['missing_unresolved'] += unresolved and not present
        t['unknown_colour'] += unknown
        t['missing_unknown_colour'] += unknown and not present
        source_found.update((kind, number, colour, source) for source in matching)
    aggregates = [dict(item_type=kind, **t) for kind, t in totals.items()]
    source_counts = defaultdict(dict)
    counted = defaultdict(int)
    for kind, _, _, source in source_found:
        counted[kind, source] += 1
    for (kind, source), total in counted.items():
        source_counts[kind][source] = total
    matrix = {kind: {scope: dict(count=0, unresolved=0, unknown_colour=0)
                     for scope in ('missing', 'all')} for kind in (*TYPE_LABELS, '?')}
    by_kind = {row['item_type']: row for row in aggregates}
    summary = []
    for kind, scopes in matrix.items():
        row = by_kind.get(kind, {})
        for scope, counts in scopes.items():
            prefix = 'missing_' if scope == 'missing' else ''
            counts.update(count=row.get('missing' if scope == 'missing' else 'total', 0),
                          unresolved=row.get(prefix + 'unresolved', 0),
                          unknown_colour=row.get(prefix + 'unknown_colour', 0))
        if kind in TYPE_LABELS:
            summary.append(dict(kind=kind, label=TYPE_LABELS[kind],
                total=row.get('total', 0), with_picture=row.get('with_picture', 0),
                missing=row.get('missing', 0),
                sources={**dict(bricklink=0, rebrickable=0), **source_counts[kind]}))
    return dict(matrix=matrix, summary=summary,
                unresolved=sum(row['unresolved'] for row in aggregates))


def selection(db, source, scope, types):
    types = sorted(set(types))
    if source not in SOURCES or scope not in ('missing', 'all') or not types or set(types) - TYPES:
        raise ValueError('Choose a source, scope and item types')
    rows = [dict(r) for r in db.execute(HELD + '''
        SELECT h.*,i.name,c.name AS color_name FROM held h JOIN items i USING(item_type,item_no)
        LEFT JOIN colors c USING(color_id) ORDER BY h.item_type,h.item_no,h.color_id''')]
    from .media import media_root
    root = media_root(db)
    cached = defaultdict(set)
    for image in db.execute('SELECT item_type,item_no,color_id,source,local_path FROM item_images WHERE copy_id IS NULL AND stock_id IS NULL AND local_path IS NOT NULL'):
        path = (root / image['local_path']).resolve()
        if path.is_relative_to(root / 'data/images') and path.is_file():
            cached[image['item_type'], image['item_no'], image['color_id']].add(image['source'])
    unresolved = {(r[0], r[1]) for r in db.execute("SELECT item_type,item_no FROM id_match WHERE status IN ('to_check','unmatched')")}
    for row in rows:
        key = row['item_type'], row['item_no'], row['color_id']
        row['sources'] = sorted(cached[key] | cached[key[:2] + (None,)])
        row['unresolved'] = row['item_type'] == '?' or key[:2] in unresolved
    # Keep the physical-file selection and job snapshot unchanged at confirmation.
    return [r for r in rows if (r['item_type'] in types or r['item_type'] == '?')
            and (scope == 'all' or not r['sources'])]


def queue(db, source, scope, types, expected_count=None, via='app'):
    from .transaction import transaction
    pipeline = Pipeline(db)
    with transaction(db):
        rows = selection(db, source, scope, types)
        priority = admin.settings(db)['priority']['pictures']
        payload = dict(via=via, **({'actor': base.AUDIT_ACTOR.get()} if via == 'api' else {}), source=source, scope=scope, types=sorted(set(types)),
                       identities=rows, priority=priority)
        if expected_count is not None:
            payload['expected_count'] = int(expected_count)
        # A repeated confirmation must not duplicate active work.
        for active in db.execute("SELECT id,payload FROM jobs WHERE kind='picture_refresh' AND state IN ('queued','running','waiting_for_budget')"):
            previous = json.loads(active['payload'])
            previous.pop('expected_count', None)
            work = {k: v for k, v in payload.items() if k != 'expected_count'}
            if previous == work:
                return active['id'], len(rows)
        stamp = base.now().isoformat()
        job = db.execute('''INSERT INTO jobs(source,kind,state,payload,created_at,updated_at)
            VALUES('import','picture_refresh','queued',?,?,?)''', (json.dumps(payload), stamp, stamp)).lastrowid
        db.execute('''INSERT INTO import_steps(job_id,name,position,sources,total,updated_at)
            VALUES(?,'pictures',0,'["picture_refresh"]',?,?)''', (job, len(rows), stamp))
        admin.audit(db, 'job:' + str(job), 'queued', None, payload)
        return job, len(rows)


def legacy_files(db, root):
    """Use old RebrickableImage.id and bl_images.image_path conventions.

    Part names are opaque image_id values, never parsed into guessed identities.
    The migration's retained envelopes and matches supply the colour bridge.
    """
    from .importer import is_set_envelope
    matches = {(r['kind'], r['source_id']): dict(r) for r in db.execute(
        "SELECT * FROM id_match WHERE source='rebrickable' AND status IN ('matched','manual','inferred')")}
    known = {(r[0], r[1]) for r in db.execute('SELECT item_type,item_no FROM items')}
    mapping = defaultdict(set)
    for source in db.execute("SELECT kind,payload FROM source_records WHERE source='rebrickable' AND kind IN ('rebrickable_sets','rebrickable_parts','rebrickable_minifigures')"):
        for envelope in cooperative(db, json.loads(source['payload']).get('records', [])):
            row = envelope.get('record', {})
            table = envelope.get('table')
            if is_set_envelope(table):
                folder, name, kind, foreign = 'sets', row.get('set'), 'set', row.get('set')
            elif table == 'rebrickable_minifigures':
                folder, name, kind, foreign = 'minifigures', row.get('figure'), 'minifigure', row.get('figure')
            elif table == 'rebrickable_parts':
                folder, name, kind, foreign = 'parts', row.get('image_id'), 'part', row.get('part')
            else:
                continue
            if not name or Path(str(name)).name != name or not row.get('image'):
                continue
            match = matches.get((kind, str(foreign) + '/' + str(row.get('color_id')))) or matches.get((kind, foreign))
            key = (match['item_type'], match['item_no']) if match else ('S', foreign) if kind == 'set' and ('S', foreign) in known else None
            color = None
            if key and key[0] == 'P':
                bridge = matches.get(('color', str(row.get('color_id'))))
                color = bridge['color_id'] if bridge else match['color_id'] if match else None
                if color is None:
                    continue
            if key and key[0] != '?':
                mapping[folder + '/' + name + '.jpg'].add((*key, color, 'rebrickable'))
    result = defaultdict(list)
    issues = []
    # The deployed DB and old cache folders share data/. Fixture roots may contain data/.
    data_root = root if any((root / folder).is_dir() for folder in ('sets', 'parts', 'minifigures', 'bl-images')) else root / 'data'
    for folder in ('sets', 'parts', 'minifigures', 'bl-images'):
        directory = data_root / folder
        if directory.is_dir() and not directory.resolve().is_relative_to(data_root.resolve()):
            issues.append(dict(name=folder, reason='Folder is outside the cache'))
            continue
        for path in cooperative(db, directory.rglob('*') if directory.is_dir() else []):
            if not path.is_file() or path.suffix.lower() not in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
                continue
            relative = path.relative_to(data_root).as_posix()
            if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
                issues.append(dict(name=relative, reason='File is outside the cache'))
                continue
            candidates = mapping.get(relative, set())
            if folder == 'bl-images':
                pieces = path.relative_to(directory).parts
                kind = pieces[0]
                if kind in TYPES and (kind, path.stem) in known:
                    if kind == 'P' and len(pieces) == 3 and pieces[1].isdigit():
                        candidates = {(kind, path.stem, int(pieces[1]), 'bricklink')}
                    elif kind != 'P' and len(pieces) == 2:
                        candidates = {(kind, path.stem, None, 'bricklink')}
            if len(candidates) != 1:
                issues.append(dict(name=relative, reason='No unambiguous identity'))
                continue
            kind, number, color, provenance = next(iter(candidates))
            result[kind, number, color].append((path, provenance))
    return result, issues


def run(pipeline, job):
    """Checkpoint each identity, resume budget waits, retain a durable issue list."""
    db = pipeline.db
    payload = json.loads(job['payload'])
    rows = payload['identities']
    local, issues = legacy_files(db, pipeline.root) if payload['source'] == 'existing' else ({}, [])
    successes = 0
    checkpoints = {r['operation']: json.loads(r['result']) for r in db.execute(
        "SELECT operation,result FROM import_calls WHERE job_id=? AND step='pictures' AND result IS NOT NULL", (job['id'],))}
    for index, row in cooperative(db, enumerate(rows)):
        operation = 'picture_identity:' + str(index)
        saved = operation in checkpoints
        if saved:
            outcome = checkpoints[operation]
        else:
            outcome = dict(ok=False, name=row['item_no'], color_name=row['color_name'], file_issues=[])
            if row['unresolved']:
                outcome['reason'] = 'Unresolved identity · Tools & Admin → Unresolved figures'
            elif row['item_type'] == 'P' and row['color_id'] is None:
                outcome['reason'] = 'Unknown colour · no picture requested'
            elif payload['source'] == 'existing':
                candidates = local.get((row['item_type'], row['item_no'], row['color_id']), [])
                outcome['reason'] = 'No matching existing file'
                for path, provenance in cooperative(db, candidates):
                    try:
                        if path.stat().st_size > images.MAX_BYTES:
                            raise base.SourceError('Image is too large')
                        images.store(db, pipeline.root, provenance, row['item_type'], row['item_no'],
                                     path.read_bytes(), color=row['color_id'], image_kind=images.picture_kind(provenance, row['item_type']),
                                     fetched_at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat())
                        outcome['ok'] = True
                    except (OSError, base.SourceError):
                        outcome['file_issues'].append(dict(name=path.relative_to(pipeline.root).as_posix(), reason='Image could not be verified'))
                if not outcome['ok'] and candidates:
                    outcome['reason'] = 'Image could not be verified'
            else:
                order = payload['priority'].get(row['item_type'], payload['priority'].get('*', [])) if payload['source'] == 'priority' else [payload['source']]
                for source in cooperative(db, order):
                    failure_key = operation + ':failed:' + source
                    if failure_key in checkpoints:
                        outcome['reason'] = checkpoints[failure_key]
                        continue
                    child = {**job, 'item_type': row['item_type'], 'item_no': row['item_no'],
                             'payload': json.dumps({'picture_color': row['color_id'], 'picture_prefix': str(index) + ':'})}
                    try:
                        pipeline.perform(child, 'pictures', source)
                        outcome['ok'] = True
                        break
                    except base.WaitingForBudget:
                        pipeline.update_step(job['id'], 'pictures', 'running', count=index, total=len(rows))
                        raise
                    except base.SourceError as error:
                        outcome['reason'] = base.redact(error)
                        with db:
                            base.write(db, 'INSERT OR REPLACE INTO import_calls(job_id,step,operation,result) VALUES(?,?,?,?)',
                                       (job['id'], 'pictures', failure_key, json.dumps(outcome['reason'])))
                outcome.setdefault('reason', 'No picture source configured')
            with db:
                base.write(db, 'INSERT OR REPLACE INTO import_calls(job_id,step,operation,result) VALUES(?,?,?,?)',
                           (job['id'], 'pictures', operation, json.dumps(outcome)))
        issues.extend(outcome.get('file_issues', []))
        successes += outcome['ok']
        if not outcome['ok']:
            issues.append(outcome)
        if saved:
            continue
        pipeline.update_step(job['id'], 'pictures', 'running', source='picture_refresh', count=index + 1, total=len(rows))
        pipeline.progress(job['id'], 'pictures', 'progress', source='picture_refresh', count=index + 1, total=len(rows))
    with db:
        current = {**payload, 'issues': issues, 'stored': successes}
        base.write(db, 'UPDATE jobs SET payload=? WHERE id=?', (json.dumps(current), job['id']))
    return len(rows)
