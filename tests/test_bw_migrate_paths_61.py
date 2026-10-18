"""#61: the browser migrate form reads and writes only inside the database folder."""
import pytest
from werkzeug.datastructures import MultiDict

from brickwork.web.import_views import data_paths
from tests.web_fixtures import app, apps  # noqa: F401


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv('BW_DB_PATH', str(tmp_path / 'data' / 'brickwork.db'))
    (tmp_path / 'data').mkdir()
    return (tmp_path / 'data').resolve()


def test_relative_paths_are_taken_from_the_data_folder(base):
    paths = data_paths(MultiDict({'app': 'imports/app.db', 'out': 'new.db', 'report': 'proof', 'decisions': 'd.json', 'catalogue': 'c.db'}))
    assert paths['app'] == str(base / 'imports' / 'app.db')
    assert paths['out'] == str(base / 'new.db')
    assert paths['extras'] is None and paths['catalogue_src'] is None


def test_absolute_paths_inside_are_accepted(base):
    assert data_paths(MultiDict({'app': str(base / 'old.db')}))['app'] == str(base / 'old.db')


@pytest.mark.parametrize('field,value', [('app', '/etc/passwd'), ('out', '../outside.db'), ('report', 'imports/../../x'),
                                         ('catalogue_src', '/'), ('decisions', '~/d.json/../../../../etc')])
def test_paths_outside_are_refused(base, field, value):
    with pytest.raises(ValueError, match='inside the data folder'):
        data_paths(MultiDict({field: value}))


def test_the_form_refuses_outside_paths_without_touching_them(app, tmp_path, monkeypatch):
    from tests.web_fixtures import logged_in
    client = logged_in(app)
    page = client.get('/manage/import-legacy').get_data(as_text=True)
    token = page.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]
    outside = tmp_path.parent / (tmp_path.name + '-outside')  # beside the data folder, not in it
    for field in ('out', 'report'):
        data = {'csrf_token': token, 'app': 'old.db', 'decisions': 'd.json', 'catalogue': 'c.db', 'out': 'new.db', 'report': 'proof'}
        data[field] = str(outside / field)
        refused = client.post('/manage/import-legacy/migrate', data=data)
        assert 'inside the data folder' in refused.get_data(as_text=True), field
    response = client.post('/manage/import-legacy/migrate', data={'csrf_token': token, 'app': '/etc/hosts', 'decisions': 'd.json',
        'catalogue': 'c.db', 'out': str(outside / 'new.db'), 'report': str(outside)})
    assert response.status_code == 200
    assert 'inside the data folder' in response.get_data(as_text=True)
    assert not outside.exists()
