"""Offline migration into a new file; legacy inputs are strictly read-only."""
from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3
import time
import warnings
import xml.etree.ElementTree as ET

from . import idmatch
from . import proof
from .projection import project, read


class ProofError(ValueError):
    """The output did not satisfy the mapping; inspect the proof report."""


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_decisions(decisions, catalogue, catalogue_src=None):
    import json
    data = json.loads(Path(decisions).read_text())
    gear = {r['item_no'] for r in data.get('manual', []) if r['item_type'] == 'G'}
    directory = Path(catalogue)
    dbpath = directory / 'blcat.db' if directory.is_dir() else directory
    if directory.is_dir() or (catalogue_src is None and dbpath.name == 'blcat.db'):
        warnings.warn('--catalogue DIR/blcat.db is deprecated; use --catalogue bricklink-catalog.db '
                      '--catalogue-src DIR', FutureWarning, stacklevel=2)
    gearpath = (Path(catalogue_src) if catalogue_src is not None else dbpath.parent) / 'Gear.xml'
    with closing(idmatch.open_readonly(dbpath)) as db:
        has_gear = db.execute("SELECT 1 FROM items WHERE item_type='G' LIMIT 1").fetchone()
        if gear and not has_gear:
            found = set()
            for _, node in ET.iterparse(gearpath, events=('end',)):
                if node.tag == 'ITEM':
                    if node.findtext('ITEMTYPE') == 'G' and node.findtext('ITEMID') in gear:
                        found.add(node.findtext('ITEMID'))
                    node.clear()
            if gear != found:
                raise ValueError('A manual Gear decision is absent from Gear.xml')
        for row in data.get('manual', []) + data.get('minifigs', []):
            if row['item_type'] == '?' or (row['item_type'] == 'G' and not has_gear):
                continue
            if not db.execute('SELECT 1 FROM items WHERE item_type=? AND item_no=?',
                              (row['item_type'], row['item_no'])).fetchone():
                raise ValueError('A decided identity is absent from the BrickLink catalogue')
    return dbpath


def migrate(app_db, web_db, decisions, catalogues, out_db, report_dir, *, replace=False, catalogue_src=None):
    """Migrate atomically and fail closed on count, content or integrity drift.

    Deterministic ids derive from source rowid/history id/JSON ordinal; the
    baseline timestamp is the decision date at UTC midnight. A candidate file
    is published only after the independent proof passes. --replace never
    authorizes replacing an input or following an output symlink.
    """
    started = time.monotonic()
    out_db = Path(out_db)
    catalogue = validate_decisions(decisions, catalogues, catalogue_src)
    inputs = [Path(p).resolve() for p in (app_db, web_db, decisions, catalogue)]
    gear = (Path(catalogue_src) if catalogue_src is not None else catalogue.parent) / 'Gear.xml'
    if gear.is_file():
        inputs.append(gear.resolve())
    if out_db.is_symlink() or out_db.resolve() in inputs:
        raise ValueError('Output must be a new file distinct from every input')
    if out_db.exists() and not replace:
        raise FileExistsError('Output exists; use --replace to replace it')
    if replace and any(Path(str(out_db) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise ValueError('Output has SQLite sidecars; close its connections before replacing it')
    if out_db.resolve() in Path(report_dir).resolve().parents or out_db.resolve() == Path(report_dir).resolve():
        raise ValueError('Report directory must be distinct from the output file')
    for name in ('proof.md', 'proof.json'):
        if (Path(report_dir) / name).resolve() in inputs + [out_db.resolve()]:
            raise ValueError('Report would overwrite an input')
    hashes = {str(p): file_hash(p) for p in inputs}
    drops = proof.dropped_columns(app_db, web_db)
    expected, _ = project(app_db, web_db, decisions, catalogue)
    out_db.parent.mkdir(parents=True, exist_ok=True)
    candidate = out_db.with_name(out_db.name + '.migrating')
    # Exclusive creation: never use or delete someone else's candidate file.
    with candidate.open('xb'):
        pass
    db = None
    try:
        db = sqlite3.connect(candidate)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('BEGIN IMMEDIATE;\n' + (Path(__file__).parents[1] / 'schema.sql').read_text())
        db.execute('PRAGMA defer_foreign_keys=ON')
        for table, rows in expected.items():
            if not rows or table in ('search_index', 'sources', 'source_freshness'):
                continue
            columns = list(rows[0])
            if table == 'wishlists':
                db.execute('UPDATE wishlists SET '+','.join(c+'=?' for c in columns if c!='id')+' WHERE id=?',
                           (*[rows[0][c] for c in columns if c!='id'], rows[0]['id']))
                continue
            db.executemany(f'INSERT INTO "{table}" ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})',
                           [tuple(r[c] for c in columns) for r in rows])
        # Re-read the inputs and rebuild expected content independently of the
        # insertion buffer. Read-back hashes cover every target column.
        rebuilt, listings = project(app_db, web_db, decisions, catalogue)
        source = read(app_db)
        approved = len(source['bricktracker_sets']) == 195 and len(source['bricktracker_parts']) == 21832
        report = proof.verify(db, rebuilt, listings, approved=approved)
        report['dropped_columns'] = drops
        report['inputs_sha256'] = {p.name: hashes[str(p)] for p in inputs}
        report['derived_copy_check_state_verified'] = len(read(web_db)['copy_check_state'])
        report['input_hashes_unchanged'] = all(file_hash(p) == hashes[str(p)] for p in inputs)
        report['ok'] &= report['input_hashes_unchanged']
        if not report['ok']:
            report.update(runtime_seconds=time.monotonic() - started, output_bytes=0)
            proof.write(report, report_dir)
            failures = [table for table, row in report['tables'].items() if not (row['count_ok'] and row['checksum_ok'])]
            raise ProofError(f'Migration proof failed: {len(report["foreign_key_check"])} foreign-key violations; '
                             f'count/checksum failures: {failures}; candidate rolled back; '
                             f'see {Path(report_dir) / "proof.md"}')
        db.commit()
        db.execute('PRAGMA optimize')  # plan statistics for the freshly loaded tables
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        db.close(); db = None
        # Publishing is the only operation allowed to replace the old output.
        if out_db.exists() and not replace:
            raise FileExistsError('Output appeared during migration')
        if out_db.is_symlink():
            raise ValueError('Output became a symlink during migration')
        if replace:
            candidate.replace(out_db)
        else:
            # Exclusive publication, including another process appearing after
            # the last existence check. Both paths are on the same filesystem.
            os.link(candidate, out_db)
            candidate.unlink()
        report.update(runtime_seconds=time.monotonic() - started, output_bytes=out_db.stat().st_size)
        proof.write(report, report_dir)
        return report
    finally:
        if db is not None:
            db.rollback()
            db.close()
        candidate.unlink(missing_ok=True)
        for suffix in ('-wal', '-shm'):
            Path(str(candidate) + suffix).unlink(missing_ok=True)
