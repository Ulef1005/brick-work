"""BrickLink Store API request signing (OAuth 1.0a, HMAC-SHA1), shared by the 3.3 source client and the 4.0 job runner.

Lives in store4 because store4 must not import `core` (M.8a, issue #110)."""
import base64
import hashlib
import hmac
import time
import uuid
from urllib.parse import quote, urlencode
from urllib.request import Request

BASE = 'https://api.bricklink.com/api/store/v1'


def q(value):
    return quote(str(value), safe='~')


def signed_request(path, params, credentials, *, timestamp=None, nonce=None):
    url = BASE + path
    ck, cs, tv, ts = credentials
    oauth = dict(oauth_consumer_key=ck, oauth_token=tv, oauth_signature_method='HMAC-SHA1',
                 oauth_timestamp=str(int(time.time()) if timestamp is None else timestamp),
                 oauth_nonce=nonce or uuid.uuid4().hex, oauth_version='1.0')
    pairs = sorted({**params, **oauth}.items())
    base = '&'.join(['GET', q(url), q('&'.join(f'{q(k)}={q(v)}' for k, v in pairs))])
    key = q(cs) + '&' + q(ts)
    oauth['oauth_signature'] = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    auth = 'OAuth ' + ','.join(f'{k}="{q(v)}"' for k, v in oauth.items())
    return Request(url + ('?' + urlencode(params) if params else ''), headers={'Authorization': auth})
