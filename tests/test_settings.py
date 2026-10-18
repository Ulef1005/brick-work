import os

import pytest
from flask import Flask

from brickwork import settings


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    # setenv then delenv records "absent" as the value to restore, so variables
    # that load_env_file() writes into os.environ are removed again after the test.
    for name in ['BW_' + n for n in settings.SETTINGS] + ['BW_SOMETHING_ELSE', 'UNPREFIXED']:
        monkeypatch.setenv(name, '')
        monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


def test_defaults():
    values = settings.load()
    assert values['AUTHENTICATION_PASSWORD'] == ''
    assert values['AUTHENTICATION_KEY'] == ''
    assert values['HOST'] == '0.0.0.0'
    assert values['PORT'] == 3333 and isinstance(values['PORT'], int)
    assert values['DEBUG'] is False and values['DARK_MODE'] is False
    assert not any(v for k, v in values.items() if k.startswith('HIDE_'))


@pytest.mark.parametrize('raw,expected', [('true', True), ('TRUE', True), ('Yes', True), ('1', True),
                                          ('false', False), ('0', False), ('', False), ('on', False)])
def test_boolean_conversion(monkeypatch, raw, expected):
    monkeypatch.setenv('BW_HIDE_ALL_SETS', raw)
    assert settings.load()['HIDE_ALL_SETS'] is expected


def test_integer_and_text_conversion(monkeypatch):
    monkeypatch.setenv('BW_PORT', '8080')
    monkeypatch.setenv('BW_HOST', '127.0.0.1')
    values = settings.load()
    assert values['PORT'] == 8080 and values['HOST'] == '127.0.0.1'


def test_bad_integer_is_an_error(monkeypatch):
    monkeypatch.setenv('BW_PORT', 'abc')
    with pytest.raises(ValueError):
        settings.load()


def test_unknown_and_unprefixed_keys_are_ignored(monkeypatch):
    monkeypatch.setenv('BW_SOMETHING_ELSE', 'x')
    monkeypatch.setenv('HIDE_ALL_SETS', 'true')
    monkeypatch.setenv('BW_HIDE_MISSING_PARTS', 'true')
    values = settings.load()
    assert 'SOMETHING_ELSE' not in values and set(values) == set(settings.SETTINGS)
    assert values['HIDE_ALL_SETS'] is False and values['HIDE_ALL_PROBLEMS_PARTS'] is False


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_env_file_quotes_comments_and_blank_lines(tmp_path):
    write(tmp_path / 'data/.env', '# comment\n\nBW_HOST="10.0.0.1"\nBW_PORT = \'4000\'\nUNPREFIXED=plain value\nno equals sign\nBW_AUTHENTICATION_KEY=a=b=c\n')
    settings.load_env_file()
    values = settings.load()
    assert values['HOST'] == '10.0.0.1' and values['PORT'] == 4000
    assert values['AUTHENTICATION_KEY'] == 'a=b=c'
    assert os.environ['UNPREFIXED'] == 'plain value'


def test_environment_beats_data_env_beats_root_env(monkeypatch, tmp_path):
    write(tmp_path / 'data/.env', 'BW_HOST=from-data\nBW_PORT=1111\n')
    write(tmp_path / '.env', 'BW_HOST=from-root\nBW_PORT=2222\nBW_DEBUG=true\n')
    monkeypatch.setenv('BW_PORT', '9999')
    settings.load_env_file()
    values = settings.load()
    assert values['PORT'] == 9999        # environment
    assert values['HOST'] == 'from-data'  # data/.env
    assert values['DEBUG'] is False       # data/.env exists: the root file is not read


def test_root_env_is_the_fallback(monkeypatch, tmp_path):
    write(tmp_path / '.env', "BW_HOST='from-root'\n")
    settings.load_env_file()
    assert settings.load()['HOST'] == 'from-root'


def test_apply_fills_the_flask_config(monkeypatch, tmp_path):
    write(tmp_path / 'data/.env', 'BW_DARK_MODE=yes\n')
    app = Flask('settings-test')
    settings.apply(app)
    assert app.config['DARK_MODE'] is True and app.config['PORT'] == 3333
