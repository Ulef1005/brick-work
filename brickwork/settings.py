"""Runtime settings: BW_* environment variables, with data/.env or .env as fallback."""
import logging
import os
from pathlib import Path


def _flag(value):
    return value.lower() in ('true', 'yes', '1')


# name -> (default, conversion of a string value). Read as BW_<name>.
SETTINGS = {
    'AUTHENTICATION_PASSWORD': ('', str),
    'AUTHENTICATION_KEY': ('', str),
    # Run without a password on purpose; otherwise the server refuses to start without one (#60).
    'ALLOW_NO_LOGIN': (False, _flag),
    # Session cookies only over HTTPS (#66): set behind a TLS proxy or when serving HTTPS.
    'SECURE_COOKIES': (False, _flag),
    'DEBUG': (False, _flag),
    'HOST': ('0.0.0.0', str),
    'PORT': (3333, int),
    # Reverse proxies in front of the app whose X-Forwarded-* headers are trusted; 0 trusts none.
    'TRUSTED_PROXIES': (0, int),
    'DARK_MODE': (False, _flag),
    # Navigation entries hidden from the shell.
    'HIDE_ADD_SET': (False, _flag),
    'HIDE_ALL_MINIFIGURES': (False, _flag),
    'HIDE_ALL_PARTS': (False, _flag),
    'HIDE_ALL_PROBLEMS_PARTS': (False, _flag),
    'HIDE_ALL_SETS': (False, _flag),
    'HIDE_ALL_STORAGES': (False, _flag),
    'HIDE_WISHES': (False, _flag),
}


def load_env_file():
    """Add the variables of data/.env (else .env) to os.environ without overriding it.

    Lines are KEY=value; blank lines and # comments are skipped and one pair of
    surrounding single or double quotes is removed.
    """
    data_env = Path('data/.env')
    root_env = Path('.env')
    if data_env.exists():
        env_file = data_env
        logging.info(f'Loading environment from: {data_env}')
    elif root_env.exists():
        env_file = root_env
        logging.info(f'Loading environment from: {root_env} (consider migrating to data/.env)')
    else:
        return
    with open(env_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip()
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            elif value.startswith("'") and value.endswith("'"):
                value = value[1:-1]
            if key not in os.environ:
                os.environ[key] = value


def load(environ=None):
    """Return every setting, converted, from BW_<name> or its default."""
    environ = os.environ if environ is None else environ
    values = {}
    for name, (default, convert) in SETTINGS.items():
        raw = environ.get('BW_' + name)
        values[name] = default if raw is None else convert(raw)
    return values


def exposure_problem(config):
    """Why the server must not start with this configuration, or None (#60).

    Without a password anyone who can reach the app can edit it, export the database and mint admin
    API tokens, so that needs an explicit BW_ALLOW_NO_LOGIN.
    """
    if config.get('AUTHENTICATION_PASSWORD') or config.get('ALLOW_NO_LOGIN'):
        return None
    return ('No BW_AUTHENTICATION_PASSWORD is set, so anyone who can reach Brick Work could edit it. '
            'Set a password, or set BW_ALLOW_NO_LOGIN=1 to run without login on purpose.')


def apply(app):
    """Load the env file, then store the settings in the Flask config."""
    load_env_file()
    app.config.update(load())
