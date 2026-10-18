"""#66: sessions follow the password, logout is not cross-site, headers, nothing before login."""
from flask import Flask

from brickwork.app import setup_app
from tests.web_fixtures import ROOT, app, apps  # noqa: F401


def login(client, password='synthetic-password'):
    return client.post('/login', data={'password': password})


def test_changing_the_password_ends_the_session(app):  # noqa: F811
    client = app.test_client()
    assert login(client).status_code == 302
    assert client.get('/collection/sets').status_code == 200
    app.config['AUTHENTICATION_PASSWORD'] = 'a-new-password'
    assert client.get('/collection/sets').status_code == 302  # back to the login page
    assert login(client, 'a-new-password').status_code == 302
    assert client.get('/collection/sets').status_code == 200


def test_a_session_from_before_this_release_must_log_in_again(app):  # noqa: F811
    client = app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = 'admin'
        session['_fresh'] = True
    assert client.get('/collection/sets').status_code == 302


def test_cross_site_logout_is_ignored_and_post_works(app):  # noqa: F811
    client = app.test_client()
    login(client)
    client.get('/logout', headers={'Sec-Fetch-Site': 'cross-site'})
    assert client.get('/collection/sets').status_code == 200
    client.post('/logout', headers={'Sec-Fetch-Site': 'same-origin'})
    assert client.get('/collection/sets').status_code == 302


def test_security_headers(app):  # noqa: F811
    response = app.test_client().get('/login')
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['X-Frame-Options'] == 'SAMEORIGIN'
    assert response.headers['Referrer-Policy'] == 'same-origin'


def test_no_counts_before_login(app):  # noqa: F811
    page = app.test_client().get('/login').get_data(as_text=True)
    assert 'nav-count' not in page


def test_secure_cookies_opt_in(apps, monkeypatch):  # noqa: F811
    monkeypatch.setenv('BW_SECURE_COOKIES', '1')
    secure = apps('toni')
    assert secure.config['SESSION_COOKIE_SECURE'] is True
    response = login(secure.test_client())
    assert 'Secure' in response.headers.get('Set-Cookie', '')
