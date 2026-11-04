"""#144: without BW_SECRET_KEY the app keeps its own Fernet key in `secret.key` beside the database, so key entry works on a fresh install."""
import os
import stat
import subprocess
import sys

from cryptography.fernet import Fernet
import pytest

from brickwork.core import errors, keys, secrets
from tests.app4 import coll, pair  # noqa: F401 (fixtures)
from tests.sources4 import unkeyed

KEY = 'synthetic-key-0001'


@pytest.fixture
def folder(tmp_path, monkeypatch):
    """No BW_SECRET_KEY; the data folder is a new, empty one."""
    unkeyed(monkeypatch)
    monkeypatch.delenv('BW_SECRET_KEY', raising=False)
    monkeypatch.setenv('BW_DB_PATH', str(tmp_path / 'brickwork.db'))
    secrets.forget()
    yield tmp_path
    secrets.forget()


def test_the_key_file_is_made_on_first_use_with_mode_600(folder):
    path = folder / 'secret.key'
    assert not path.exists() and secrets.entry_available()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    Fernet(path.read_bytes().strip())  # a valid Fernet key
    assert [p.name for p in folder.iterdir()] == ['secret.key']  # no temporary file is left


def test_the_same_key_is_reused_across_calls_and_processes(folder):
    ciphertext = secrets.encrypt('synthetic-credential')
    first = (folder / 'secret.key').read_bytes()
    assert secrets.decrypt(ciphertext) == 'synthetic-credential' and secrets.fingerprint({'a': 1}) == secrets.fingerprint({'a': 1})
    code = 'from brickwork.core import secrets; import sys; sys.stdout.write(secrets.decrypt(sys.argv[1]))'
    other = subprocess.run([sys.executable, '-c', code, ciphertext], capture_output=True, text=True,
                           env={**os.environ, 'BW_DB_PATH': str(folder / 'brickwork.db')})
    assert other.stdout == 'synthetic-credential', other.stderr
    assert (folder / 'secret.key').read_bytes() == first


def test_the_environment_key_wins_and_makes_no_file(folder, monkeypatch):
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    assert secrets.decrypt(secrets.encrypt('synthetic-credential')) == 'synthetic-credential'
    secrets.fingerprint({'a': 1})
    assert list(folder.iterdir()) == []


def test_an_unwritable_folder_keeps_entry_disabled_and_says_what_to_do(tmp_path, monkeypatch):
    unkeyed(monkeypatch)
    monkeypatch.delenv('BW_SECRET_KEY', raising=False)
    monkeypatch.setenv('BW_DB_PATH', str(tmp_path / 'absent' / 'brickwork.db'))
    assert not secrets.entry_available()
    for call in (lambda: secrets.encrypt('synthetic-credential'), lambda: secrets.fingerprint({'a': 1})):
        with pytest.raises(errors.SourceNotConfigured) as caught:
            call()
        text = str(caught.value)
        assert text.startswith('Key entry is disabled') and 'BW_SECRET_KEY' in text and 'make the data folder writable' in text
        assert 'Fernet.generate_key().decode()' in text
    assert not (tmp_path / 'absent').exists()


def test_a_read_only_folder_is_the_same(folder):
    folder.chmod(0o500)
    try:
        if os.access(folder, os.W_OK):
            pytest.skip('the folder stays writable (running as root)')
        assert not secrets.entry_available()
        with pytest.raises(errors.SourceNotConfigured, match='make the data folder writable'):
            secrets.encrypt('synthetic-credential')
    finally:
        folder.chmod(0o700)


@pytest.mark.parametrize('content', [b'', b'not-a-fernet-key-but-long-enough-xx', b'\xff\xfe\x00junk'])
def test_a_malformed_key_file_fails_closed_without_echoing_it(folder, content):
    (folder / 'secret.key').write_bytes(content)
    assert not secrets.entry_available()
    with pytest.raises(errors.BrickWorkError) as caught:
        secrets.encrypt('synthetic-credential')
    assert str(caught.value) == 'The key file secret.key is not a valid key'
    assert (folder / 'secret.key').read_bytes() == content  # not replaced either


def test_a_stored_key_reads_back_through_the_generated_file(coll, folder):  # noqa: F811
    keys.save(coll.db, 'rebrickable', {'key': KEY})
    assert (folder / 'secret.key').is_file()
    secrets.forget()
    assert keys.credentials(coll.db, 'rebrickable', ('BW_REBRICKABLE_API_KEY',)) == (KEY,)
    (folder / 'secret.key').write_text(Fernet.generate_key().decode())  # another key cannot read it
    with pytest.raises(errors.BrickWorkError):
        keys.credentials(coll.db, 'rebrickable', ('BW_REBRICKABLE_API_KEY',))
