"""The two API transports. Neither calls domain services."""
import requests


class InProcessClient:
    def __init__(self, app, token, remote_addr=None):
        # The caller's address, so the token back-off counts each MCP client on its own (#59).
        self.app, self.token, self.remote_addr = app, token, remote_addr

    def request(self, method, path, *, query=None, body=None, headers=None):
        with self.app.test_client() as client:
            extra = {'environ_base': {'REMOTE_ADDR': self.remote_addr}} if self.remote_addr else {}
            response = client.open('/api/v1' + path, method=method,
                query_string=query, json=body, **extra,
                headers={'Authorization': 'Bearer ' + self.token, **(headers or {})})
            return response.status_code, response.get_json(silent=True) if response.is_json else response.get_data(as_text=True)


class HTTPClient:
    def __init__(self, base_url, token):
        self.base_url, self.token = base_url.rstrip('/'), token

    def request(self, method, path, *, query=None, body=None, headers=None):
        try:
            response = requests.request(method, self.base_url + path, params=query,
                json=body, headers={'Authorization': 'Bearer ' + self.token, **(headers or {})},
                timeout=30, allow_redirects=False)
            try:
                value = response.json()
            except ValueError:
                value = response.text
            return response.status_code, value
        except requests.RequestException:
            # Transport exceptions can include URLs or credentials. Keep them private.
            return 503, {'code': 'api_unavailable', 'status': 503, 'detail': 'API unavailable'}
