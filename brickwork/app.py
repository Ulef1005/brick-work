"""Standalone application initialization."""
import logging
import time
from flask import Flask, g, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix
from . import settings
from .web.auth import LoginManager
from .version import __version__


def setup_app(app: Flask) -> None:
    settings.apply(app)
    from .limits import install as install_body_limits
    install_body_limits(app)
    logging.basicConfig(level=logging.DEBUG if app.config['DEBUG'] else logging.INFO)
    LoginManager(app)
    # Session cookies are never sent on cross-site POSTs (CSRF defence in depth).
    for name in ('SESSION_COOKIE_SAMESITE', 'REMEMBER_COOKIE_SAMESITE'):
        if not app.config.get(name):
            app.config[name] = 'Lax'
    if app.config['SECURE_COOKIES']:
        app.config['SESSION_COOKIE_SECURE'] = app.config['REMEMBER_COOKIE_SECURE'] = True
    # Forwarded headers decide the client address (login and token back-off), scheme and host. They are
    # trusted only for the proxy hops the operator names (#59); a client reaching the app directly cannot set them.
    hops = max(0, app.config['TRUSTED_PROXIES'])
    if hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops, x_port=hops, x_prefix=hops)
    else:
        warned = []

        @app.before_request
        def forwarded_but_untrusted():
            # Behind a proxy without BW_TRUSTED_PROXIES the scheme and client address are the proxy's:
            # same-origin checks refuse browser writes and every client shares one back-off counter.
            if not warned and (request.headers.get('X-Forwarded-For') or request.headers.get('X-Forwarded-Proto')):
                warned.append(True)
                logging.warning('Requests carry X-Forwarded-* headers, but BW_TRUSTED_PROXIES is 0: behind a reverse '
                                'proxy, set BW_TRUSTED_PROXIES=1, or browser writes are refused and all clients share one back-off.')
    from .web.views import web_page, bw_sets, web_manifest, shell_worker
    from .web import ported
    from .web.auth import login_page
    app.register_blueprint(web_page)
    app.register_blueprint(login_page)
    app.add_url_rule('/', 'index.index', bw_sets)
    app.add_url_rule('/manifest.webmanifest', 'web.web_manifest', web_manifest)
    app.add_url_rule('/sw.js', 'web.shell_worker', shell_worker)
    @app.errorhandler(404)
    def missing(error):
        return render_template('web/toni/error.html', error='Page not found', status=404), 404

    @app.errorhandler(500)
    def failed(error):
        # Exception details (class, message and traceback) only in debug as in the 7f exception frame.
        import traceback
        cause = getattr(error, 'original_exception', None)
        debug = bool(cause) and app.config['DEBUG']
        detail = f'{type(cause).__name__} · {cause}' if debug else 'server'
        trace = ''.join(traceback.format_exception(cause)).strip() if debug else ''
        return render_template('web/toni/error.html', error=detail, status=500, trace=trace), 500

    # The API chains to this handler for non-API paths, so it is registered first.
    from .api import register
    register(app)

    from .core import admin as core_admin, keys as core_keys
    from .core.connect import connect as open_collection
    from .core.pipeline import database_path
    # The 4.0 fetchers read credentials through the app's key store: the environment first, then `source_key` (M.8a).
    core_keys.install(database_path)
    # A collection that is not a 4.0 file stops the start with the fix named. Read-only and without the catalogue, so a first
    # run (no catalogue yet) still boots; a missing file is the setup page's business. Inside the app context, so a path set in
    # the app's config (BRICKWORK_DB_PATH) is the one checked.
    with app.app_context():
        startup_path = database_path()
    if startup_path.is_file():
        open_collection(startup_path, read_only=True, require_catalogue=False).close()

    @app.before_request
    def before_request():
        core_admin.begin_operation()      # every event of this request shares one operation key
        g.login = LoginManager
        g.request_start_time = time.monotonic()
        g.request_time = lambda: f'{(time.monotonic() - g.request_start_time) * 1000:.0f}ms'
        g.version = __version__

    @app.teardown_request
    def end_operation(error):
        core_admin.end_operation()

    @app.after_request
    def security_headers(response):
        # Basic hardening for every response (#66); a route can still set its own value.
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        response.headers.setdefault('Referrer-Policy', 'same-origin')
        return response

    @app.after_request
    def cache_versioned_static(response):
        # bw_static() puts the file's mtime in ?v=, so that URL never changes content:
        # cache it for a year without revalidating, and keep the session out of it.
        if request.endpoint == 'static' and request.args.get('v') and response.status_code == 200:
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
            response.bw_static_immutable = True
        return response

    ported.install(app)      # screens not yet ported to the 4.0 store answer 503 (M.8a); after the request setup above, which it renders with

    from flask.sessions import SecureCookieSessionInterface

    class StaticSafeSessions(SecureCookieSessionInterface):
        """Versioned static responses carry neither Vary: Cookie nor a refreshed session cookie."""
        def save_session(self, app, session, response):
            if getattr(response, 'bw_static_immutable', False):
                return None
            return super().save_session(app, session, response)

    app.session_interface = StaticSafeSessions()

    from .core import drainer
    if drainer.enabled():
        from .web.views import bw_resume_imports
        bw_resume_imports(app)
