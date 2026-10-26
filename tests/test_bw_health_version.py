"""/health names the running app version and the 4.0 schema, without a token (App Standard: one visible version).

The one v1 route that answers on the 4.0 line (M.8a); it needs the collection file alone, not the catalogue."""
from brickwork.core import meta
from brickwork.store4.connect import connect
from brickwork.version import __version__
from tests.web_fixtures import app, apps  # noqa: F401  (fixtures)


def test_health_carries_the_app_version_and_schema(app, tmp_path):
    connect(tmp_path / 'brickwork.db', tmp_path / 'catalogue.db').close()           # a 4.0 collection, no catalogue
    response = app.test_client().get('/api/v1/health')
    assert response.status_code == 200
    data = response.json['data']
    assert data['status'] == 'ok' and data['app'] == __version__ and data['schema'] == '4.0'


def test_health_without_a_collection_says_to_set_up(app):
    response = app.test_client().get('/api/v1/health')
    assert response.status_code == 503 and response.json['code'] == 'not_set_up'


def test_version_and_health_agree():
    class Db:
        def execute(self, sql):
            return type('R', (), {'fetchone': lambda self: ['4.0']})()
    assert meta.version(Db())['app'] == meta.health(Db())['app'] == __version__
    assert meta.health(Db())['schema'] == '4.0'
