"""Follow-up from the review of #59: forwarded headers that are not trusted are reported once."""
import logging

from tests.web_fixtures import app, apps  # noqa: F401


def test_forwarded_headers_without_trust_warn_once(app, caplog):  # noqa: F811
    caplog.set_level(logging.WARNING)
    client = app.test_client()
    for _ in range(2):
        client.get('/login', headers={'X-Forwarded-Proto': 'https'})
    assert caplog.text.count('BW_TRUSTED_PROXIES is 0') == 1
