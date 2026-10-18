"""Local API metadata; no source transports or legacy stores."""
from ..version import __version__


def health(db):
    return {'status': 'ok', 'api': '1.0.0',
            'schema': db.execute('SELECT version FROM schema_meta').fetchone()[0]}


def version(db, read_only=False):
    return {**health(db), 'app': __version__, 'read_only': bool(read_only),
            'features': ['tokens']}
