"""The secret store and the redaction registry on the 4.0 store (ported from test_bw_api_m0 and test_bw_api_m5 by M.11d, issue #113): what is
encrypted never reaches a file in plain text, a wrong or missing secret key fails closed, and the registry of values to redact is thread-safe.
Invented values."""
from contextlib import closing
import threading

from cryptography import fernet
import pytest

from brickwork.core import errors, secrets
from brickwork.core.connect import connect
from brickwork.core.sources import base
from tests.app4 import make_pair


def fernet_key(monkeypatch):
    key = fernet.Fernet.generate_key().decode()
    monkeypatch.setenv('BW_SECRET_KEY', key)
    return fernet


def test_a_secret_round_trips_and_no_plain_text_reaches_a_file(tmp_path, monkeypatch):
    fernet_key(monkeypatch)
    path = make_pair(tmp_path)
    plaintext = 'synthetic-credential-never-persist'
    ciphertext = secrets.encrypt(plaintext)
    assert secrets.decrypt(ciphertext) == plaintext and plaintext not in ciphertext
    with closing(connect(path)) as db:
        with db:
            db.execute("INSERT INTO source_key(source,ciphertext,saved_at) VALUES('brickset',?,'2026-01-01T00:00:00.000Z')", (ciphertext,))
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    for file in tmp_path.rglob('*'):
        if file.is_file():
            assert plaintext.encode() not in file.read_bytes(), file.name


def test_a_wrong_secret_key_fails_safely(monkeypatch):
    module = fernet_key(monkeypatch)
    ciphertext = secrets.encrypt('synthetic-credential')
    monkeypatch.setenv('BW_SECRET_KEY', module.Fernet.generate_key().decode())
    with pytest.raises(errors.ValidationFailed, match='cannot be decrypted'):
        secrets.decrypt(ciphertext)


def test_a_missing_secret_key_disables_entry(monkeypatch):
    monkeypatch.delenv('BW_SECRET_KEY', raising=False)
    with pytest.raises(errors.SourceNotConfigured, match='Key entry is disabled'):
        secrets.encrypt('synthetic-credential')


def test_the_redaction_registry_is_thread_safe():
    stop, failures = threading.Event(), []

    def churn():
        n = 0
        while not stop.is_set():
            n += 1
            secrets.remember(*[f'value-{n}-{i}-xxxxxxxx' for i in range(20)])
            if n % 50 == 0:
                secrets.forget()

    def read():
        try:
            for _ in range(3000):
                base.redact('text value-1-1-xxxxxxxx')
        except RuntimeError as error:
            failures.append(error)
    writers = [threading.Thread(target=churn) for _ in range(3)]
    readers = [threading.Thread(target=read) for _ in range(3)]
    for t in writers + readers:
        t.start()
    for t in readers:
        t.join(30)
    stop.set()
    for t in writers:
        t.join(10)
    secrets.forget()
    assert not failures
