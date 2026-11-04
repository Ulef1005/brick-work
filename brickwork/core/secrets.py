"""Shared credential discovery for redaction and export checks."""
import os
import threading


SECRET_WORDS = ('KEY', 'SECRET', 'TOKEN', 'PASSWORD')
# Stored source keys decrypted by this process: redaction must know them like environment keys.
REMEMBERED = set()
_LOCK = threading.Lock()


def remember(*values):
    with _LOCK:
        REMEMBERED.update(str(v) for v in values if v)


def forget():
    with _LOCK:
        REMEMBERED.clear()


def secret_values(values=None):
    """Return secret values of at least eight characters, longest first.

    Ignore variable prefixes. Default to the live environment; callers may also
    supply app configuration.
    """
    extra = set()
    if values is None:
        values = os.environ
        with _LOCK:  # iterate a snapshot: other threads remember keys while redact() runs
            extra = {v for v in tuple(REMEMBERED) if len(v) >= 8}
    return sorted({str(value) for key, value in values.items()
                   if value and len(str(value)) >= 8
                   and any(word in key for word in SECRET_WORDS)} | extra,
                  key=len, reverse=True)


KEY_FILE = 'secret.key'
GENERATE = 'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
DISABLED = ('Key entry is disabled: Brick Work cannot create or read its key file (' + KEY_FILE + ') in the data folder. '
            'Set BW_SECRET_KEY to a key made with ' + GENERATE + ', or make the data folder writable.')


def key_file():
    """`secret.key` beside the collection (the data folder that holds brickwork.db)."""
    from .pipeline import database_path
    return database_path().parent / KEY_FILE


def _sync_dir(folder):
    """fsync a folder so a new file name in it survives a power cut (POSIX; a no-op where folders can't be opened)."""
    try:
        fd = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _file_key():
    """The key in `secret.key`; made on first need. Several workers may race: the file is written whole under a private name, then
    linked into place, so it never exists half written and the first writer's key is the one everybody reads."""
    from .errors import SourceNotConfigured
    path = key_file()
    try:
        return path.read_bytes().decode('ascii', 'replace').strip()
    except FileNotFoundError:
        pass
    except (OSError, UnicodeError):
        raise SourceNotConfigured(DISABLED) from None
    from cryptography.fernet import Fernet
    temp = path.with_name(f'.{KEY_FILE}.{os.getpid()}.{threading.get_ident()}.tmp')
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'wb') as out:
                out.write(Fernet.generate_key() + b'\n')
                out.flush()
                os.fsync(out.fileno())             # the key is on disk before anything can be encrypted with it
            os.link(temp, path)
            _sync_dir(path.parent)                 # and so is its name
        except FileExistsError:
            _sync_dir(path.parent)                 # a racing writer's key may not be durable yet either
        finally:
            temp.unlink(missing_ok=True)
        return path.read_bytes().decode('ascii', 'replace').strip()
    except (OSError, UnicodeError):
        raise SourceNotConfigured(DISABLED) from None


def _secret():
    """The Fernet key: BW_SECRET_KEY when set (it always wins), otherwise the key file."""
    key = os.environ.get('BW_SECRET_KEY')
    if key:
        return key, 'BW_SECRET_KEY must be a valid Fernet key'
    key = _file_key()
    remember(key)  # the key must never reach a log or an error either
    return key, 'The key file secret.key is not a valid key'


def _fernet():
    from .errors import ValidationFailed
    key, invalid = _secret()
    from cryptography.fernet import Fernet
    try:
        return Fernet(key.encode('ascii'))
    except (ValueError, UnicodeError):
        raise ValidationFailed(invalid) from None


def encrypt(value):
    """Encrypt a source credential or JSON bundle; the caller stores only ciphertext."""
    from .errors import ValidationFailed
    if not isinstance(value, str) or not value:
        raise ValidationFailed('Enter a source key')
    return _fernet().encrypt(value.encode('utf-8')).decode('ascii')


def decrypt(ciphertext):
    """Fail closed with fixed text when the secret changed or ciphertext is invalid."""
    from cryptography.fernet import InvalidToken
    from .errors import ValidationFailed
    try:
        return _fernet().decrypt(ciphertext.encode('ascii')).decode('utf-8')
    except (InvalidToken, UnicodeError, AttributeError):
        raise ValidationFailed('Stored source key cannot be decrypted') from None


def entry_available():
    """True when a secret key (BW_SECRET_KEY or secret.key) can encrypt; never reveals why a bad value is bad."""
    try:
        _fernet()
    except Exception:
        return False
    return True


def fingerprint(value):
    """Keyed digest of a JSON-able secret payload, for idempotent replay without storing a plain hash."""
    import hashlib
    import hmac
    import json
    secret = _secret()[0]
    data = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    return hmac.new(b'brickwork-key-replay:' + secret.encode(), data, hashlib.sha256).hexdigest()
