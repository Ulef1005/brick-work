"""The BrickLink `subsets` call for the job runner (design 4.2, 6.5; issue #107, M.5d).

One signed GET, `/items/SET/{no}/subsets?break_minifigs=false` (figures stay figure lines, as the design's `M` lines expect), made
through an injectable `http(url, headers) -> (status, json)`, the same seam as the Rebrickable client. Signing is the 3.3 code
(`core.sources.bricklink.signed_request`); the four credentials come from the environment, never from a file or a log line.
The reply is returned whole: `bricklink_subsets.load_subsets` validates and stores it."""
import os
import re

from ..core.sources.bricklink import signed_request
from .errors import Store4Error
from .rebrickable_api import FetchError, InvalidReply, KeyRefused, NotFound, Throttled, UrllibHttp

SOURCE = 'bricklink'
KEY_ENVS = tuple('BW_BRICKLINK_' + name for name in ('CONSUMER_KEY', 'CONSUMER_SECRET', 'TOKEN_VALUE', 'TOKEN_SECRET'))
NUMBER = re.compile('[A-Za-z0-9-]{1,32}')                   # as the 3.3 endpoint check; a dotted set number does not exist
IP_MISMATCH = 'BrickLink token IP mismatch (the public IP changed? Register the new address for the API token)'


def credentials():
    """The four values in signing order, else a Store4Error naming only the missing variable names."""
    values = [os.environ.get(name) for name in KEY_ENVS]
    missing = [name for name, v in zip(KEY_ENVS, values) if not v]
    if missing:
        raise Store4Error('BrickLink key is not configured: ' + ', '.join(missing) + ' not set')
    return tuple(values)


def key_configured():
    return all(os.environ.get(name) for name in KEY_ENVS)


def fetch_subsets(number, *, http=None, creds=None):
    """Make the one call for a BrickLink set number; returns the whole reply (`{'meta': ..., 'data': [...]}`)."""
    if not isinstance(number, str) or not NUMBER.fullmatch(number):
        raise FetchError(f'{number!r} is not a BrickLink set number')
    http = http or UrllibHttp()
    path = f'/items/SET/{number}/subsets'
    request = signed_request(path, {'break_minifigs': 'false'}, creds or credentials())
    status, body = http(request.full_url, dict(request.header_items()))
    meta = body.get('meta') if isinstance(body, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    code = meta.get('code') if status == 200 and isinstance(meta.get('code'), int) else status       # BrickLink also answers inside a 200
    if code == 404:
        raise NotFound(f'BrickLink has no set {number}', 404)
    if code == 429:
        raise Throttled('BrickLink throttled the call', None)
    if code in (401, 403):
        text = str(meta)
        if 'TOKEN_IP_MISMATCHED' in text:
            raise KeyRefused(IP_MISMATCH, code)
        if re.search(r'IP_MISMATCH|BAD_OAUTH|TIMESTAMP|NONCE', text, re.IGNORECASE):
            raise FetchError('BrickLink rejected the request signature or the clock (a retry may help)', None)
        raise KeyRefused('BrickLink refused the key', code)
    if code != 200:
        raise FetchError(f'BrickLink answered {code} for {path}', code if isinstance(code, int) else None)
    if not isinstance(body, dict):
        raise InvalidReply(f'BrickLink answered {path} with no JSON object', code)
    return body
