"""Invented rendered HTML and bounded transport, without any live host."""
from io import BytesIO
import pytest
from brickwork.core.official_instructions import Official, parse_page, valid_pdf_url, NEEDS_RENDERER
from brickwork.core import instruction_sources as src, instructions as ins
from brickwork.core import admin
from tests.app4 import coll, pair  # noqa: F401

BASE = 'https://www.lego.com/cdn/product-assets/'


def card(title, url, size='4.69MB (PDF)'):
    return f'<li><div data-test="bi-card"><h3>{title}</h3><p>{size}</p><a data-test="bi-card-link" href="{url}">PDF</a></div></li>'


def page(cards):
    return '<section data-test="building-instructions-list"><ul>' + ''.join(cards) + '</ul></section>'


def test_invented_groups_locale_and_extra_file():
    extra = BASE + 'product.bi.additional.extra.pdf/1000_X_Alex%204th%20Model.pdf'
    html = page([card(f'Alex ({n}/3)', BASE + f'product.bi.core.pdf/{n}.pdf') for n in (2, 3, 1)] + [card('Sam (1/1)', extra)])
    calls = []
    adapter = Official(page_fetch=lambda url: calls.append(url) or html)
    rows = adapter.find('1000-1', 'DE')
    assert [r.booklet for r in rows] == [1, 2, 3, 1]
    assert [r.booklets for r in rows] == [3, 3, 3, 1]
    assert rows[-1].url == extra
    assert all(r.region == 'de-de' and ins.matches_region(vars(r), 'DE') for r in rows)
    assert all(r.size == int(4.69 * 1024 * 1024) for r in rows)
    assert calls == ['https://www.lego.com/de-de/service/building-instructions/1000?age-gate=grown_up']
    assert adapter.unavailable is None
    assert parse_page(page([]), 'de-de') == []


@pytest.mark.parametrize('url', ['http://www.lego.com/cdn/product-assets/product.bi.core.pdf/1.pdf', BASE + 'product.bi.core.pdf/1.pdf?next=evil', BASE + 'product.bi.additional.extra.pdf/1000_X_%2e%2e%2fsecret.pdf', 'https://evil.test/1.pdf', 'https://[bad'])
def test_untrusted_links_rejected(url):
    assert not valid_pdf_url(url)
    assert parse_page(page([card('Alex (1/1)', url)]), 'en-us') == []
    with pytest.raises(ValueError):
        Official().fetch(url, 100)


def test_registered_renderer_notice_and_invalid_set():
    assert src.registry.adapters['official'].unavailable == NEEDS_RENDERER
    with pytest.raises(ValueError, match='renderer'):
        Official().find('1000-1', 'DE')
    with pytest.raises(ValueError, match='supported'):
        Official(page_fetch=lambda _: pytest.fail('must not fetch')).find('../other', 'DE')


def test_stream_checks_length_header_and_actual_bytes():
    class Response(BytesIO):
        headers = {}
    calls = []
    def fetch(data, limit, length=None):
        response = Response(data)
        response.headers = {} if length is None else {'Content-Length': str(length)}
        def opener(request, timeout):
            calls.append(request)
            return response
        return src.fetch_pdf(BASE + 'product.bi.core.pdf/1.pdf', limit, opener=opener)
    with fetch(b'%PDF-1.4 Alex', 100) as stream:
        assert stream.read() == b'%PDF-1.4 Alex'
    assert calls[0].get_header('User-agent') == src.USER_AGENT
    for data, limit, length in [(b'%PDF-Alex', 5, 9), (b'%PDF-Alex', 5, None), (b'Alex', 100, None)]:
        with pytest.raises(ValueError):
            fetch(data, limit, length)


def test_separate_limit_settings_and_total_defaults(coll):
    assert ins.download_limit(coll.db, 'official') == 500 * 1024 * 1024
    settings = admin.settings(coll.db)
    admin.save_settings(coll.db, settings['retail_country'], settings['priority'], [], official_download_limit_mb='350')
    assert ins.download_limit(coll.db, 'official') == 350 * 1024 * 1024
    assert ins.download_limit(coll.db, 'peeron') == 20 * 1024 * 1024
    files = [dict(id=i, source='official', region='de-de', size=size * 1024 * 1024, file_id=None) for i, size in enumerate((348, 200, 501), 1)]
    assert ins.tick_defaults(files, 'DE') == [1]
    with pytest.raises(ValueError):
        admin.save_settings(coll.db, 'DE', settings['priority'], [], official_download_limit_mb='0')


def test_official_discovery_order_and_download_limit(coll, tmp_path):
    from tests.test_find_instructions import discover, download
    from brickwork.core.transaction import transaction
    html = page([card(f'Alex ({n}/3)', BASE + f'product.bi.core.pdf/{n}.pdf', '30MB (PDF)') for n in (2, 3, 1)])
    calls = []
    adapter = Official(page_fetch=lambda _: html, pdf_fetch=lambda url, limit: calls.append((url, limit)) or b'%PDF-1.4 Alex')
    reg = src.Registry({'official': adapter})
    _, rows = discover(coll, reg)
    assert [r['booklet'] for r in rows] == [1, 2, 3]
    assert all(r['region'] == 'en-gb' for r in rows)
    job = download(coll, rows[:1])
    assert ins.Downloads(coll.db, registry=reg, root=tmp_path).run(job)['state'] == 'done'
    assert calls[0][1] == 500 * 1024 * 1024
    with transaction(coll.db):
        coll.db.execute('UPDATE instruction_candidate SET size=? WHERE id=?', (501 * 1024 * 1024, rows[1]['id']))
    with transaction(coll.db), pytest.raises(ValueError, match='limit'):
        ins.queue_download(coll.db, [rows[1]['id']])


def test_transport_retry_after():
    from urllib.error import HTTPError
    def opener(request, timeout):
        raise HTTPError(request.full_url, 429, 'wait', {'Retry-After': '120'}, BytesIO())
    with pytest.raises(src.RetryAfter) as error:
        src.fetch_pdf(BASE + 'product.bi.core.pdf/1.pdf', opener=opener)
    assert error.value.value == '120'


def test_download_has_a_total_time_limit():
    class Response(BytesIO):
        headers = {}
    now = [0.0]
    class Slow(Response):
        def read1(self, size=-1):
            now[0] += 100  # a throttled source: each read stays inside the socket timeout
            return super().read1(1)
    def opener(request, timeout):
        return Slow(b'%PDF-' + b'x' * 1000)
    with pytest.raises(ValueError, match='too long'):
        src.fetch_pdf(BASE + 'product.bi.core.pdf/1.pdf', 10000, opener=opener, monotonic=lambda: now[0])


def test_deadline_is_checked_per_received_chunk():
    """A server dripping a byte at a time must hit the deadline: the fetch uses read1, never a blocking read(n)."""
    now = [0.0]
    class Drip(BytesIO):
        headers = {}
        def read(self, size=-1):
            raise AssertionError('read(n) blocks until n bytes; use read1')
        def read1(self, size=-1):
            now[0] += 19
            return super().read1(1)
    with pytest.raises(ValueError, match='too long'):
        src.fetch_pdf(BASE + 'product.bi.core.pdf/1.pdf', 10000, opener=lambda r, timeout: Drip(b'%PDF-' + b'x' * 1000), monotonic=lambda: now[0])


def test_a_non_numeric_content_length_gives_the_fixed_message():
    class Response(BytesIO):
        headers = {'Content-Length': 'secret-header-value'}
    with pytest.raises(ValueError) as error:
        src.fetch_pdf(BASE + 'product.bi.core.pdf/1.pdf', 100, opener=lambda r, timeout: Response(b'%PDF-1.4'))
    assert str(error.value) == 'The source could not download this file'
