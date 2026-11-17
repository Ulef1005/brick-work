"""Pictures of guesses on the Unresolved screen (issue #459): a BrickLink number a link only guesses is not an item, so its picture cannot
live in the `picture` table. It lives in a small cache under the media root instead, `data/images/guess/<type>/<number>~<colour>.<ext>`.

The page never fetches. `lookup` only reads the cache (a file, a recent "no picture" marker, or neither); `fetch` is called by one small
endpoint per card and does a plain GET of `img.bricklink.com` through the picture client of `sources/images` (https, the host allow-list, no
redirect, size cap). A failure is cached as a marker file for `RETRY_AFTER` seconds, so a guess BrickLink has no picture for is not asked again
at every page load. Calls are spaced by `MIN_GAP` seconds in one process."""
from pathlib import Path
import os
import re
import threading
import time
import uuid
from io import BytesIO
from urllib.parse import urlsplit
from urllib.request import Request

from PIL import Image

from .sources import images
from .sources.base import SourceError, USER_AGENT

SOURCE = 'bricklink'
URL = 'https://img.bricklink.com/ItemImage/{type}N/{colour}/{number}.png'
RETRY_AFTER = 24 * 3600
MIN_GAP = 0.25
EXTENSIONS = ('png', 'jpg', 'gif', 'webp')
MIMETYPES = {'png': 'image/png', 'jpg': 'image/jpeg', 'gif': 'image/gif', 'webp': 'image/webp'}
_TYPE = re.compile(r'[A-Z]')
_NUMBER = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,59}')
_gate = threading.Lock()
_last = [0.0]


def valid(letter, number, colour):
    return bool(_TYPE.fullmatch(letter or '') and _NUMBER.fullmatch(number or '') and isinstance(colour, int) and 0 <= colour < 100000)


def _stem(root, letter, number, colour):
    if not valid(letter, number, colour):
        raise ValueError('not a picture key')
    return Path(root) / 'data/images/guess' / letter / f'{number}~{colour}'


def lookup(root, letter, number, colour, *, now=None):
    """`('ready', path)`, `('none', None)` (looked lately, nothing there) or `('missing', None)` (never asked, or the marker is old). Reads files only."""
    stem = _stem(root, letter, number, colour)
    for extension in EXTENSIONS:
        path = Path(f'{stem}.{extension}')
        if path.is_file():
            return 'ready', path
    marker = Path(f'{stem}.none')
    try:
        if (now or time.time()) - marker.stat().st_mtime < RETRY_AFTER:
            return 'none', None
    except OSError:
        pass
    return 'missing', None


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def fetch(root, letter, number, colour, *, http=None, now=None):
    """Fetch the picture of one guess unless the cache already answers. Returns the state `lookup` would. `http(request) -> bytes` stands in for the
    network; with none, the real client runs after the gap since the last call."""
    found = lookup(root, letter, number, colour, now=now)
    if found[0] != 'missing':
        return found
    stem = _stem(root, letter, number, colour)
    url = URL.format(type=letter, colour=colour, number=number)
    try:
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname not in images.HOSTS[SOURCE]:
            raise SourceError('unsupported image URL')
        if http is None:
            with _gate:
                wait = _last[0] + MIN_GAP - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                try:
                    data = images.transport(Request(url, headers={'User-Agent': USER_AGENT}))
                finally:
                    _last[0] = time.monotonic()
        else:
            data = http(Request(url, headers={'User-Agent': USER_AGENT}))
        if len(data) > images.MAX_BYTES:
            raise ValueError('oversized')
        with Image.open(BytesIO(data)) as image:
            extension = {'PNG': 'png', 'JPEG': 'jpg', 'GIF': 'gif', 'WEBP': 'webp'}.get(image.format)
            if extension is None:
                raise ValueError('unsupported image format')
            image.verify()
    except Exception:
        _write(Path(f'{stem}.none'), b'')
        return 'none', None
    path = Path(f'{stem}.{extension}')
    _write(path, data)
    Path(f'{stem}.none').unlink(missing_ok=True)
    return 'ready', path
