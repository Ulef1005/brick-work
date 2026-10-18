"""Local API metadata; no source transports or legacy stores."""
from ..version import __version__


def health(db):
    # The app version is here too, so one call tells monitors and update checks what runs (App Standard).
    return {'status': 'ok', 'api': '1.0.0', 'app': __version__,
            'schema': db.execute('SELECT version FROM schema_meta').fetchone()[0]}


def version(db, read_only=False):
    return {**health(db), 'app': __version__, 'read_only': bool(read_only),
            'features': ['tokens']}
