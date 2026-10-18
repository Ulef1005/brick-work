"""/health names the running app version, without a token (App Standard: one visible version)."""
from brickwork.core import meta
from brickwork.version import __version__
from tests.web_fixtures import app, apps  # noqa: F401  (fixtures)
from tests.test_bw_collection import bw  # noqa: F401  (fixture)
from tests.importer.test_importer import legacy  # noqa: F401  (fixture)


def test_health_carries_the_app_version(app, bw):
    response = app.test_client().get('/api/v1/health')
    assert response.status_code == 200
    data = response.json['data']
    assert data['status'] == 'ok' and data['app'] == __version__


def test_version_and_health_agree():
    class Db:
        def execute(self, sql):
            return type('R', (), {'fetchone': lambda self: ['3.3']})()
    assert meta.version(Db())['app'] == meta.health(Db())['app'] == __version__
