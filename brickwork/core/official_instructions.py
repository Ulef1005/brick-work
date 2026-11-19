"""Verified rendered-page structure only; no browser dependency or shell execution."""
import re
from decimal import Decimal
from urllib.parse import unquote, urlsplit
from bs4 import BeautifulSoup
from .instruction_types import Candidate

NEEDS_RENDERER = 'Official needs a page renderer: not set up'
LOCALES = {'AT': 'en-gb', 'DE': 'de-de', 'GB': 'en-gb', 'UK': 'en-gb', 'US': 'en-us',
           'FR': 'fr-fr', 'CA': 'en-ca', 'AU': 'en-au'}


class NeedsRenderer(ValueError):
    pass


def page_url(set_no, region):
    """The fixed URL of a set's instructions page on lego.com: the number without its -N suffix, the locale of `region`. The one place that
    builds it, for the renderer-backed finder below and for the link-out (`instruction_links.py`)."""
    number = re.fullmatch(r'(\d+)(?:-\d+)?', set_no) if isinstance(set_no, str) else None
    if not number or region not in LOCALES:
        raise ValueError('Choose a supported set number and region')
    return f'https://www.lego.com/{LOCALES[region]}/service/building-instructions/{number[1]}?age-gate=grown_up'


def valid_pdf_url(url):
    try:
        parsed = urlsplit(url)
    except (ValueError, TypeError):
        return False
    decoded = unquote(parsed.path)
    return (parsed.scheme == 'https' and parsed.netloc == 'www.lego.com'
            and parsed.path.startswith('/cdn/product-assets/')
            and not parsed.query and not parsed.fragment
            and not any(part in ('.', '..') for part in decoded.split('/'))
            and not any(char in decoded for char in ('\\', '\x00', '\r', '\n'))
            and decoded.count('/') == parsed.path.count('/')
            and re.fullmatch(r'/cdn/product-assets/(?:product\.bi\.core\.pdf/\d+\.pdf|product\.bi\.additional\.extra\.pdf/\d+_X_[^/]+\.pdf)', parsed.path) is not None)


def parse_page(html, region):
    """Treat titles and links as untrusted data. Never follow page links."""
    soup = BeautifulSoup(html, 'html.parser')
    found = []
    for card in soup.select('section[data-test="building-instructions-list"] > ul > li > div[data-test="bi-card"]'):
        heading, size, link = card.find('h3'), card.find('p'), card.select_one('a[data-test="bi-card-link"]')
        if not heading or not link or not valid_pdf_url(link.get('href', '')):
            continue
        title = heading.get_text(' ', strip=True)
        counter = re.search(r'\((\d+)/(\d+)\)\s*$', title)
        number, count = map(int, counter.groups()) if counter else (1, 1)
        if not 1 <= number <= count <= 1000:
            continue
        group = title[:counter.start()].strip() if counter else title
        size_match = re.fullmatch(r'\s*([\d.]+)\s*(KB|MB|GB)\s*\(PDF\)\s*', size.get_text() if size else '', re.I)
        length = None
        if size_match:
            try:
                length = int(Decimal(size_match[1]) * 1024 ** {'KB': 1, 'MB': 2, 'GB': 3}[size_match[2].upper()])
            except ArithmeticError:
                pass
        if title and len(title) <= 120:
            found.append((group, Candidate('official', number, count, None, region, length, link['href'], title)))
    return [candidate for _, candidate in sorted(found, key=lambda entry: (entry[0].casefold(), entry[1].booklet))]


class Official:
    """page_fetch(url) must return rendered HTML and honour host rates and Retry-After.

    No production renderer exists. The interface deliberately performs no shell GET.
    Only a chosen set's fixed page URL is passed to the injected renderer.
    """
    def __init__(self, page_fetch=None, pdf_fetch=None):
        self.page_fetch, self.pdf_fetch = page_fetch, pdf_fetch

    @property
    def unavailable(self):
        return NEEDS_RENDERER if self.page_fetch is None else None

    def find(self, set_no, region):
        if self.page_fetch is None:
            raise NeedsRenderer(NEEDS_RENDERER)
        return parse_page(self.page_fetch(page_url(set_no, region)), LOCALES[region])

    def fetch(self, url, limit):
        if not valid_pdf_url(url):
            raise ValueError('Choose an Official PDF URL')
        from .instruction_sources import fetch_pdf
        return (self.pdf_fetch or fetch_pdf)(url, limit)
