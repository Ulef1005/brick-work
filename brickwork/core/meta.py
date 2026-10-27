"""Local API metadata; no source transports or legacy stores."""
from ..version import __version__

API_V1 = '1.0.0'
API_V2 = '2.0.0'


def health(db, api=API_V1):
    # The app version is here too, so one call tells monitors and update checks what runs (App Standard).
    return {'status': 'ok', 'api': api, 'app': __version__,
            'schema': db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]}


def version(db, read_only=False, api=API_V1):
    return {**health(db, api), 'app': __version__, 'read_only': bool(read_only),
            'features': ['tokens']}
