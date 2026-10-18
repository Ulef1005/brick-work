"""Browser authentication: one admin user, switched off when the password is empty."""
import logging
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit
import hashlib
import hmac

from flask import Blueprint, current_app, Flask, redirect, render_template, request, session, url_for
from flask_login import current_user, login_manager, login_user, logout_user, UserMixin


class LoginManager(object):
    class User(UserMixin):
        def __init__(self, name: str, password: str, /):
            self.id = name
            self.password = password

    def __init__(self, app: Flask, /):
        app.secret_key = app.config['AUTHENTICATION_KEY'] or session_key()

        manager = login_manager.LoginManager()
        manager.login_view = 'login.login'  # type: ignore
        manager.init_app(app)

        @manager.user_loader
        def user_loader(*arg):
            # A session belongs to the password it was opened with: changing the password ends it (#66).
            password = app.config['AUTHENTICATION_PASSWORD']
            if not app.config.get('LOGIN_DISABLED') and session.get(SESSION_PASSWORD) != password_mark(password):
                return None
            return self.User('admin', password)

        # An empty password switches login off for every route.
        app.config['LOGIN_DISABLED'] = app.config['AUTHENTICATION_PASSWORD'] == ''

    # True when login is switched off or the user is logged in.
    @staticmethod
    def is_authenticated() -> bool:
        return current_app.config['LOGIN_DISABLED'] or current_user.is_authenticated

    @staticmethod
    def is_enabled() -> bool:
        return not current_app.config['LOGIN_DISABLED']


SESSION_PASSWORD = 'bw_password'


def password_mark(password):
    """What the session keeps of the password: a keyed digest, never the password itself."""
    return hmac.new(current_app.secret_key.encode(), b'bw-session:' + password.encode(), hashlib.sha256).hexdigest()


def session_key():
    """The signing key for browser sessions when BW_AUTHENTICATION_KEY is not set (#60).

    Generated once and kept beside the database (mode 600), so sessions survive a restart. Without a
    writable database folder the key lives in memory only: sessions then end at every restart, but the
    app never runs with an empty key.
    """
    folder = Path(os.environ.get('BW_DB_PATH') or 'data/brickwork.db').parent
    path = folder / 'session.key'

    def stored():
        value = path.read_bytes().decode('ascii', 'replace').strip()
        if len(value) < 32:
            return None
        if path.stat().st_mode & 0o077:
            try:
                path.chmod(0o600)
            except OSError:
                logging.warning('The session key %s is readable by others; make it mode 600', path)
        return value

    def publish(replace):
        # Written to a private temp file first, so no worker ever reads a half-written key.
        value = secrets.token_urlsafe(48)
        temporary = folder / f'.session.key.{os.getpid()}.{secrets.token_hex(4)}'
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(value + '\n')
        try:
            if replace:
                os.replace(temporary, path)
            else:
                os.link(temporary, path)  # fails if another worker published first
        except FileExistsError:
            return stored()
        finally:
            temporary.unlink(missing_ok=True)
        logging.info('Created a browser session key in %s', path)
        return value
    try:
        if path.is_file():
            value = stored()
            if value:
                return value
            logging.warning('The session key %s was damaged; it is replaced and open sessions end', path)
            return publish(replace=True)
        if folder.is_dir():
            return publish(replace=False)
    except (OSError, ValueError) as exc:
        logging.warning('Could not use a session key in %s (%s); set BW_AUTHENTICATION_KEY, or sessions end at restart',
                        folder, getattr(exc, 'strerror', None) or exc)
    return secrets.token_urlsafe(48)


login_page = Blueprint('login', __name__)


@login_page.get('/login')
def login():
    from ..core.throttle import LOGIN
    wait = LOGIN.wait(request.remote_addr)
    return render_template('web/toni/login.html', next=request.args.get('next'), wrong_password=request.args.get('wrong_password'),
                           wait=wait), 429 if wait else 200


@login_page.post('/login')
def do_login():
    import hmac
    from ..core.throttle import LOGIN
    client = request.remote_addr
    if LOGIN.wait(client):
        return login()
    user = LoginManager.User('admin', current_app.config['AUTHENTICATION_PASSWORD'])
    password = request.form.get('password', '')
    if not password or not hmac.compare_digest(password.encode(), str(user.password).encode()):
        LOGIN.fail(client)
        return redirect(url_for('login.login', wrong_password=True, next=request.args.get('next')))
    LOGIN.succeed(client)
    login_user(user)
    session[SESSION_PASSWORD] = password_mark(password)
    target = request.args.get('next', '/')
    parsed = urlsplit(target)
    if not target.startswith('/') or target.startswith('//') or parsed.scheme or parsed.netloc:
        target = '/'
    return redirect(target)


@login_page.route('/logout', methods=['GET', 'POST'])
def logout():
    # A link from another site cannot log you out (#66): browsers mark such requests cross-site.
    if request.headers.get('Sec-Fetch-Site') not in (None, 'same-origin', 'none'):
        return redirect(url_for('index.index'))
    logout_user()
    session.pop(SESSION_PASSWORD, None)
    return redirect(url_for('index.index'))
