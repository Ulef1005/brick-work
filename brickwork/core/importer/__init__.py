"""Read-only import from BrickTracker; historical schemas are isolated here."""
from .migrate import migrate, ProofError, file_hash


def is_set_envelope(table):
    return table in ('rebrickable_sets', 'bricktracker_wishes')


def import_collection(app_db, extras_db, decisions, catalogues, out_db, report_dir, *, replace=False, catalogue_src=None):
    """Run the preserved migration, supplying an empty extras input when omitted."""
    if extras_db is not None:
        return migrate(app_db, extras_db, decisions, catalogues, out_db, report_dir, replace=replace, catalogue_src=catalogue_src)
    import sqlite3
    from tempfile import TemporaryDirectory
    from pathlib import Path
    with TemporaryDirectory(prefix='brickwork-import-') as directory:
        empty = Path(directory) / 'extras.db'
        with sqlite3.connect(empty) as db:
            db.executescript(Path(__file__).with_name('empty-extras.sql').read_text())
        return migrate(app_db, empty, decisions, catalogues, out_db, report_dir, replace=replace, catalogue_src=catalogue_src)
