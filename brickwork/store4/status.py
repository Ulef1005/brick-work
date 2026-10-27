"""Read-only status of the catalogue lifecycle for Tools & Admin (design 3.3, 6.1, 6.2, 6.4, 6.6; M.10c).

Everything here reads: the catalogue file, the collection file, the download manifests, the mapping files and the BrickLink list folders.
Nothing writes and nothing opens a download file (the manifests only). The build and reconcile calls themselves stay in `cli`."""
from contextlib import closing
import json
from pathlib import Path

from .cli import MANIFEST, _ro, newest_download, newest_lists, part_list_summary, summary
from .mappings import MAPPINGS_DIR, read_mapping

UNRESOLVED = ('manual', 'matched', 'inferred')          # the link statuses that give a BrickLink key (to_check is a guess)


def _counts(row):
    try:
        counts = json.loads(row['counts_json'] or '{}')
    except ValueError:
        return {}
    return counts if isinstance(counts, dict) else {}


def catalogue_build(paths):
    """The current catalogue build: its date, the Rebrickable download it came from, what it holds, when the collection was last
    reconciled with it, and whether a reconcile is still due. None when there is no catalogue file."""
    if not paths.catalogue.exists():
        return None
    with closing(_ro(paths.catalogue)) as db:
        dump = db.execute("SELECT id, finished_at, mapping_version, counts_json, files_json FROM build WHERE kind='rebrickable_dump' "
                          'ORDER BY id DESC LIMIT 1').fetchone()
        newest = db.execute('SELECT id, kind, finished_at FROM build ORDER BY id DESC LIMIT 1').fetchone()
        counts = _counts(dump) if dump else {}
        out = dict(path=str(paths.catalogue), bytes=paths.catalogue.stat().st_size, build_id=newest['id'] if newest else None,
                   built_at=(dump or newest or {})['finished_at'] if (dump or newest) else None,
                   last_change_kind=newest['kind'] if newest else None, last_change_at=newest['finished_at'] if newest else None,
                   mapping_version=dump['mapping_version'] if dump else None,
                   items=counts.get('live_items', counts.get('items', 0)), colours=counts.get('colours', 0),
                   retired_items=counts.get('retired_items', 0), retired_colours=counts.get('retired_colours', 0),
                   retired_inventories=counts.get('retired_inventories', 0), previous=paths.catalogue.with_name('catalogue.db.prev').exists())
    found = newest_download(paths)
    out['download_date'] = found[1].get('date', found[0].name) if found else None
    out['download_files'] = len(found[1].get('files', [])) if found else 0
    out.update(reconciled_at=None, reconciled=None, builds_pending=0, last_reconcile=None, part_lists=None)
    if paths.collection.exists():
        with closing(_ro(paths.collection)) as db:
            builds = db.execute('SELECT id, reconciled_at, counts_json FROM catalogue_build ORDER BY id').fetchall()
            known = {r['id'] for r in builds}
        with closing(_ro(paths.catalogue)) as db:
            unactivated = [r[0] for r in db.execute('SELECT id FROM build ORDER BY id') if r[0] not in known]
        pending = [b for b in builds if not b['reconciled_at']]
        out.update(reconciled_at=max((b['reconciled_at'] for b in builds if b['reconciled_at']), default=None),
                   reconciled=bool(builds) and not pending and not unactivated, builds_pending=len(pending) + len(unactivated))
        last = next((b for b in reversed(builds) if b['reconciled_at']), None)
        rec = _counts(last).get('reconcile') if last else None
        out['last_reconcile'] = summary(rec) if rec else None
        out['part_lists'] = part_list_summary(paths)
    return out


def changed_copies(db, limit=12):
    """The copies whose part list changed against the catalogue (`copies.part_list_changes`), one row per copy with the set they are
    of: `[{copy_id, item_id, label, number, name, entries, kinds}]` (`label` is the copy's "Set N" as the set page's copy chooser numbers
    it), at most `limit`, and the total as the second value."""
    from . import copies
    grouped = {}
    for e in copies.part_list_changes(db):
        g = grouped.setdefault(e['copy_id'], dict(copy_id=e['copy_id'], item_id=e['item_id'], entries=0, kinds=set()))
        g['entries'] += 1
        g['kinds'].add(e['kind'])
    rows = []
    shown = list(grouped.values())[:limit]
    # "Set N": the copy's position among the live copies of its set, numbered as the set page's copy chooser numbers them
    labels = {r[0]: f'Set {r[1]}' for r in db.execute('''SELECT c.id, (SELECT count(*) FROM main.copy d WHERE d.archived_at IS NULL AND d.item_id=c.item_id
                                                       AND (d.created_at, d.id) <= (c.created_at, c.id)) FROM main.copy c
                                                       WHERE c.archived_at IS NULL AND c.id IN (SELECT value FROM json_each(?))''',
                                                    (json.dumps([g['copy_id'] for g in shown]),))}
    for g in shown:
        item = db.execute('SELECT born_key, name FROM main.item WHERE id=?', (g['item_id'],)).fetchone()
        rows.append(dict(g, kinds=sorted(g['kinds']), label=labels.get(g['copy_id'], 'Copy'), number=item['born_key'] if item else None,
                         name=item['name'] if item else None))
    rows.sort(key=lambda r: (r['number'] or '', r['label']))
    return rows, len(grouped)


def bricklink_lists(paths):
    """The optional BrickLink item lists (design 6.6): the folders under `bricklink-lists/` with the files in each, whether the catalogue
    holds a load, and what that load did (links upgraded, candidates to check, kinds corrected)."""
    folders = []
    if paths.lists.is_dir():
        for d in sorted((p for p in paths.lists.iterdir() if p.is_dir()), reverse=True):
            xml = sorted(p for p in d.glob('*.xml') if not p.name.startswith('.'))
            folders.append(dict(name=d.name, files=len(xml), bytes=sum(p.stat().st_size for p in xml)))
    newest = newest_lists(paths)
    out = dict(directory=f'{paths.data.name}/{paths.lists.name}/', folders=folders, newest=newest.name if newest else None, loaded=None, built=paths.catalogue.exists())
    if not paths.catalogue.exists():
        return out
    with closing(_ro(paths.catalogue)) as db:
        row = db.execute("SELECT id, started_at, finished_at, counts_json, files_json FROM build WHERE kind='bricklink_list' ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            return out
        counts = _counts(row)
        try:
            files = json.loads(row['files_json'] or '[]')
        except ValueError:
            files = []
        out['loaded'] = dict(build_id=row['id'], at=row['finished_at'] or row['started_at'], items=counts.get('items', 0),
                             by_type=counts.get('by_type', {}), colours=counts.get('colours', 0), links_upgraded=counts.get('links_upgraded', 0),
                             candidates=counts.get('same_number', 0), kinds_corrected=counts.get('kinds_corrected', 0),
                             kinds_ambiguous=counts.get('kinds_ambiguous', 0), files=[f.get('name') for f in files if isinstance(f, dict)])
    return out


def _mapping_file(path):
    meta, rows = read_mapping(path)
    return dict(name=path.name, rows=len(rows), version=meta.get('mapping_version'), dump_date=meta.get('dump_date'))


def mapping_layers(paths):
    """The shipped and the local mapping files with their row counts (design 3.3). A local file that cannot be read is listed with its error."""
    shipped = [_mapping_file(p) for p in sorted(MAPPINGS_DIR.glob('*.csv'))]
    local = []
    if paths.mappings.is_dir():
        for p in sorted(paths.mappings.glob('*.csv')):
            try:
                row = _mapping_file(p)
            except (ValueError, OSError) as exc:
                row = dict(name=p.name, rows=0, version=None, dump_date=None, error=str(exc))
            manifest = p.with_name(p.stem + '.manifest.json')
            row['manifest'] = manifest.is_file()
            local.append(row)
    return dict(shipped=shipped, local=local, local_dir=f'{paths.data.name}/{paths.mappings.name}/')


def coverage(paths):
    """Two figures for Tools & Admin (design 6.4 `coverage`, 6.8), each `{have, total}`:
    `items`: the collection's projected items with a BrickLink key a link or the mappings can resolve (reconcile's per-kind coverage, to_check
    not counted); `pictures`: the part-colour pairs the collection holds (set lines and loose parts) that have a stored picture address.
    None for a figure the files cannot give (no reconcile yet, no collection)."""
    out = dict(items=None, pictures=None, by_kind={})
    if not paths.collection.exists():
        return out
    with closing(_ro(paths.collection)) as db:
        row = db.execute('SELECT counts_json FROM catalogue_build WHERE reconciled_at IS NOT NULL ORDER BY id DESC LIMIT 1').fetchone()
        rec = _counts(row).get('reconcile') if row else None
        if rec and rec.get('coverage'):
            by_kind = rec['coverage']
            total = sum(sum(v.values()) for v in by_kind.values())
            have = sum(sum(v.get(k, 0) for k in UNRESOLVED) for v in by_kind.values())
            out.update(items=dict(have=have, total=total), by_kind=by_kind)
    if paths.catalogue.exists():
        from .connect import connect
        with closing(connect(paths.collection, paths.catalogue, read_only=True)) as db:
            pairs = ('SELECT item_id, color_id FROM main.copy_part WHERE retired_at IS NULL UNION '
                     "SELECT item_id, color_id FROM main.stock WHERE kind='part' AND color_id IS NOT NULL")
            total, have = db.execute(f'SELECT count(*), count(p.item_id) FROM ({pairs}) q LEFT JOIN catalogue.picture_url p '
                                     'ON p.item_id=q.item_id AND p.color_id=q.color_id').fetchone()
            out['pictures'] = dict(have=have, total=total)
    return out
