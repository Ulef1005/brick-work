"""PDF source interface with injectable provider adapters.

Adapters own verified discovery and HTTP fetching, including passing USER_AGENT and
surfacing HTTP Retry-After as RetryAfter. Tests inject registries, never global adapters.
"""
from typing import Protocol, BinaryIO

LIMIT = 20 * 1024 * 1024
TOTAL_TIMEOUT = 300  # seconds for one whole download: the socket timeout of 20 s only bounds a single read
USER_AGENT = 'BrickWork/1 instruction-download (+https://github.com/Ulef1005/brick-work)'
DISPLAY_NAMES = {'rebrickable': 'Rebrickable', 'peeron': 'Peeron', 'official': 'Official'}


from .instruction_types import Candidate

class Adapter(Protocol):
    def find(self, set_no: str, region: str) -> list[Candidate]: ...
    def fetch(self, url: str, limit: int) -> bytes | BinaryIO: ...


class RetryAfter(Exception):
    """A source asks the runner to pause; seconds or an HTTP date string."""
    def __init__(self, value):
        self.value = value
        super().__init__('The source asked us to wait')


class Registry:
    def __init__(self, adapters=None):
        self.adapters = dict(adapters or {})

    def register(self, source, adapter):
        if source not in DISPLAY_NAMES:
            raise ValueError('Unknown instruction source')
        self.adapters[source] = adapter

    def names(self):
        return [DISPLAY_NAMES[s] for s in self.adapters]




def fetch_pdf(url, limit=LIMIT, *, opener=None, monotonic=None):
    """Shared bounded HTTP transport for future verified adapters; no redirect guessing."""
    from urllib.request import Request, build_opener
    from urllib.error import HTTPError
    from urllib.parse import urlsplit
    from .sources.base import NoRedirect
    if urlsplit(url).scheme != 'https' or not 0 < limit:
        raise ValueError('Choose an HTTPS PDF within the download limit')
    request = Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/pdf'})
    open_request = opener or build_opener(NoRedirect()).open
    import time
    clock = monotonic or time.monotonic
    deadline = clock() + TOTAL_TIMEOUT
    try:
        with open_request(request, timeout=20) as response:
            size = response.headers.get('Content-Length')
            try:
                too_big = bool(size) and int(size) > limit
            except ValueError:
                raise ValueError('The source could not download this file') from None
            if too_big:
                raise ValueError('File exceeds the download limit')
            from tempfile import TemporaryFile
            content = TemporaryFile()
            try:
                total = 0
                while True:
                    if clock() > deadline:
                        raise ValueError('Download took too long')
                    # read1 returns what one receive delivered, so the deadline above is checked per chunk, not per 64 KiB
                    chunk = response.read1(min(65536, limit + 1 - total))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > limit:
                        raise ValueError('File exceeds the download limit')
                    content.write(chunk)
                content.seek(0)
                if content.read(5) != b'%PDF-':
                    raise ValueError('Choose a PDF file')
                content.seek(0)
                return content
            except BaseException:
                content.close()
                raise
    except HTTPError as error:
        try:
            if error.code in (429, 503) and error.headers.get('Retry-After'):
                raise RetryAfter(error.headers['Retry-After']) from None
            raise ValueError('The source could not download this file') from None
        finally:
            error.close()


from .official_instructions import Official  # noqa: E402
registry = Registry({'official': Official()})
