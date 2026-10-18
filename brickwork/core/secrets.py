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


def _fernet():
    from .errors import SourceNotConfigured, ValidationFailed
    key = os.environ.get('BW_SECRET_KEY')
    if not key:
        raise SourceNotConfigured('Key entry is disabled: configure BW_SECRET_KEY')
    from cryptography.fernet import Fernet
    try:
        return Fernet(key.encode('ascii'))
    except (ValueError, UnicodeError):
        raise ValidationFailed('BW_SECRET_KEY must be a valid Fernet key') from None


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
    """True when BW_SECRET_KEY can encrypt; never reveals why a bad value is bad."""
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
    secret = os.environ.get('BW_SECRET_KEY')
    if not secret:
        from .errors import SourceNotConfigured
        raise SourceNotConfigured('Key entry is disabled: configure BW_SECRET_KEY')
    data = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    return hmac.new(b'brickwork-key-replay:' + secret.encode(), data, hashlib.sha256).hexdigest()
