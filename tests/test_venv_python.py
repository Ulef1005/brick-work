"""scripts/venv_python.py: the scripts that import the app find the same venv python that scripts/check.sh would use."""
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent / 'scripts'))
import venv_python  # noqa: E402


def make(path):
    (path / 'bin').mkdir(parents=True)
    (path / 'bin' / 'python').write_text('')
    return str(path / 'bin' / 'python')


def test_app_venv_comes_first(tmp_path):
    app, own = make(tmp_path / 'app'), make(tmp_path / 'checkout' / '.venv')
    assert venv_python.find(tmp_path / 'checkout', {'APP_VENV': str(tmp_path / 'app')}) == app
    assert venv_python.find(tmp_path / 'checkout', {}) == own


def test_a_missing_app_venv_falls_through(tmp_path):
    own = make(tmp_path / 'checkout' / '.venv')
    assert venv_python.find(tmp_path / 'checkout', {'APP_VENV': str(tmp_path / 'nowhere')}) == own


def test_no_venv_is_none(tmp_path):
    assert venv_python.find(tmp_path / 'plain', {}) is None


def test_ensure_does_nothing_inside_a_venv():
    assert sys.prefix != sys.base_prefix        # the tests run in the venv
    venv_python.ensure()
