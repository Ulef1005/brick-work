"""Value and gain on the pages (#57): the Value module of a set's detail, Paid vs value on Statistics and the insurance report (screen, print view, CSV).

The figures themselves (`core/valuation.py`) are tested in test_valuation_57.py; here the pages that show them. Invented data on the rich fixture catalogue."""
import csv
from datetime import datetime, timezone
import io
import re
import sqlite3
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
import pytest

from brickwork.core import collection, valuation
from brickwork.web import valuation_views
from tests import rendered
from tests.app4 import STAMP, app4, client, coll, pair, read, world  # noqa: F401  (the fixtures)

ROOT = Path(__file__).resolve().parents[1]
TODAY = datetime(2026, 10, 27, tzinfo=timezone.utc)
OCT_9 = '2026-10-09T08:00:00.000Z'


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(collection, 'now', lambda: TODAY)
    monkeypatch.setattr(valuation, 'now', lambda: TODAY)


def rate(coll, currency, per_eur, day='2026-10-09'):
    coll.sql('INSERT OR REPLACE INTO exchange_rate(currency, per_eur, as_of, source) VALUES(?,?,?,?)', (currency, per_eur, day, 'manual'))


def quote(coll, price='61.00', set_key='1000-1', condition='used', sold=14, observed=OCT_9):
    coll.price(coll.item('sets', set_key), price, condition=condition, sold=sold, observed=observed)


def soup(client, url):
    response = client.get(url)
    assert response.status_code == 200, url
    return BeautifulSoup(response.data, 'html.parser')


def words(node):
    return re.sub(r'\s+', ' ', node.get_text(' ', strip=True))


def module(client, coll, copy_id, set_key='1000-1'):
    """The Value module's text on the set's detail, the selected copy `copy_id`."""
    page = soup(client, f"/collection/item/{coll.item('sets', set_key)}?copy={copy_id}")
    found = page.select('[data-module=value]')
    return (words(found[0]), found[0]) if found else (None, None)


# ---- A. the Value module on a set's detail ----

def test_the_module_shows_paid_worth_and_gain_after_the_prices_card(coll, client):
    quote(coll)
    copy = coll.add_copy('1000-1', condition='used', completeness='complete', price='24.00', currency='EUR', date='2025-03-09')
    text, node = module(client, coll, copy)
    assert text == 'Value · Set 1 Paid €24.00 9 Mar 2025 Worth now €61.00 9 Oct Gain €37.00 · 154% Used sold average · 14 sales · 9 Oct'
    page = soup(client, f"/collection/item/{coll.item('sets', '1000-1')}?copy={copy}")
    modules = [m['data-module'] for m in page.select('aside [data-module]')]
    assert modules.index('value') == modules.index('prices') + 1
    assert node.select_one('.bc-value-gain b').get_text() == '€37.00 · 154%'


def test_a_loss_is_written_with_a_word_and_no_sign(coll, client):
    quote(coll, price='790.00', condition='new', sold=6)
    copy = coll.add_copy('1000-1', condition='new', completeness='sealed', price='849.99', currency='EUR', date='2023-05-04')
    text, node = module(client, coll, copy)
    assert 'Loss €59.99 · 7%' in text and 'New sold average · 6 sales · 9 Oct' in text
    assert not re.search(r'[-−–]\s?[€$£]?\d', text) and 'Gain' not in text


def test_a_copy_with_no_price_paid_shows_the_worth_alone(coll, client):
    quote(coll)
    copy = coll.add_copy('1000-1', condition='used', completeness='complete')
    text, node = module(client, coll, copy)
    assert text == 'Value · Set 1 Paid No price paid Worth now €61.00 9 Oct Used sold average · 14 sales · 9 Oct'
    assert not node.select('.bc-value-gain')


def test_a_copy_with_no_quote_reads_no_sales_and_hides_the_gain(coll, client):
    copy = coll.add_copy('1000-1', condition='used', completeness='complete', price='24.00', currency='EUR', date='2025-03-09')
    text, node = module(client, coll, copy)
    assert text == 'Value · Set 1 Paid €24.00 9 Mar 2025 Worth now no sales Used · no sales'
    assert not node.select('.bc-value-gain')


def test_an_override_reads_your_value(coll, client):
    quote(coll)
    copy = coll.add_copy('1000-1', condition='used', completeness='complete', price='119.90', currency='EUR', date='2023-11-18', current_value='142.00', current_value_currency='EUR')
    text, node = module(client, coll, copy)
    assert text == 'Value · Set 1 Paid €119.90 18 Nov 2023 Worth now €142.00 your value Gain €22.10 · 18% Your value'


def test_a_stale_quote_is_marked_stale_in_ink(coll, client):
    coll.sql("INSERT OR REPLACE INTO source_freshness(source, kind, max_age_days) VALUES('bricklink', 'prices', 30)")
    quote(coll, observed='2026-08-21T08:00:00.000Z')
    copy = coll.add_copy('1000-1', condition='used', completeness='complete', price='24.00', currency='EUR', date='2025-03-09')
    text, node = module(client, coll, copy)
    assert 'Worth now €61.00 21 Aug' in text and text.endswith('Used sold average · 14 sales · 21 Aug · stale')
    assert node.select_one('.bc-value-source em').get_text() == 'stale'


def test_a_price_paid_in_another_currency_is_converted_with_its_rate_and_date(coll, client):
    quote(coll)
    rate(coll, 'USD', '1.08')
    copy = coll.add_copy('1000-1', condition='used', completeness='complete', price='50.00', currency='USD', date='2025-03-09')
    text, node = module(client, coll, copy)
    assert 'Paid €46.30 9 Mar 2025' in text and 'Gain €14.70 · 32%' in text
    assert node.select_one('.bc-value-note').get_text() == 'Paid $50.00, shown as €46.30 at the rate of 9 Oct'


def test_a_missing_rate_says_needs_a_rate_and_never_guesses(coll, client):
    quote(coll)
    copy = coll.add_copy('1000-1', condition='used', completeness='complete', price='50.00', currency='USD', date='2025-03-09')
    text, node = module(client, coll, copy)
    assert 'Paid needs a rate' in text and 'Worth now €61.00 9 Oct' in text
    assert not node.select('.bc-value-gain') and 'USD' in node.select_one('.bc-value-note').get_text()


def test_a_gain_with_no_percent_shows_the_amount_only(coll, client):
    quote(coll)
    copy = coll.add_copy('1000-1', condition='used', completeness='complete', price='0.001', currency='EUR')    # rounds to 0.00 once shown
    text, node = module(client, coll, copy)
    assert node.select_one('.bc-value-gain b').get_text() == '€61.00' and '%' not in text


def test_only_a_copy_of_a_set_has_the_module(coll, client, world):
    assert module(client, coll, world.copy_a)[0] is not None
    for url in (f'/collection/item/{world.brick}?colour={world.red}', f'/collection/item/{world.figure}', f'/collection/wishes/{world.wish_set}'):
        assert not soup(client, url).select('[data-module=value]'), url


def test_a_failed_read_is_the_error_state_with_retry_not_a_broken_page(coll, client, monkeypatch):
    copy = coll.add_copy('1000-1', condition='used', completeness='complete', price='24.00', currency='EUR')

    def broken(db, *args):
        raise sqlite3.OperationalError('boom')
    monkeypatch.setattr(valuation, 'copies', broken)
    text, node = module(client, coll, copy)
    assert 'The value did not load.' in text and node.select_one('a.button').get_text() == 'Retry'
    assert node['data-state'] == 'error' and node.select_one('a.button')['href'].endswith(f'copy={copy}')


# ---- B. Paid vs value on Statistics ----

def paid_copy(coll, key, price, set_key='1000-1', **fields):
    return coll.add_copy(set_key, condition='used', completeness='complete', price=price, currency='EUR', date=fields.pop('date', '2024-05-01'), **fields)


def section(client):
    found = soup(client, '/manage/statistics').select_one('.bw-value-stats')
    return found, (words(found) if found else None)


def themed(coll, set_key, theme):
    coll.prop(coll.item('sets', set_key), 'theme', theme)


def test_statistics_has_paid_vs_value_under_spent_vs_retail(coll, client):
    quote(coll, '40.00')
    themed(coll, '1000-1', 'Castle')
    for price in ('20.00', '25.00', '30.00'):
        paid_copy(coll, '1000-1', price)
    paid_copy(coll, '1000-1', None)
    page = soup(client, '/manage/statistics')
    classes = [s.get('class')[1] for s in page.select('section.bw-card')]
    assert classes.index('bw-retail-stats') + 1 == classes.index('bw-value-stats')
    node, text = section(client)
    assert node.select_one('.bv-title').get_text() == 'Worth €120.00 against €75.00 paid'
    assert text.startswith('Paid vs value Insurance report Worth €120.00 against €75.00 paid Gain €45.00 · 60% · used and new sold averages')
    cells = {c.select_one('.bv-k').get_text(): c.select_one('.bv-v').get_text() for c in node.select('.bv-cell')}
    assert cells == {'Total paid': '€75.00', 'Worth now': '€120.00', 'Gain': '€45.00 · 60%', 'Without a price paid': '1 copy'}
    assert 'not in the paid total' in text and node.select_one('.bw-outline')['href'] == '/manage/insurance-report'
    assert [h.get_text() for h in node.select('.bv-list h3')] == ['By theme', 'By purchase year']
    assert 'Gain compares the 3 copies with a price paid · amounts in EUR' in text


def test_the_bar_lists_start_at_zero_on_one_scale_and_write_the_gain_at_the_row_end(coll, client):
    quote(coll, '40.00')
    themed(coll, '1000-1', 'Castle')
    for price in ('20.00', '25.00', '30.00'):
        paid_copy(coll, '1000-1', price)
    node, _ = section(client)
    row = node.select('.bv-list')[0].select_one('.bv-row')
    paid, worth = (float(re.search(r'width:([\d.]+)%', b['style'])[1]) for b in row.select('.bv-bar i'))
    assert row.select_one('.bv-name').get_text() == 'Castle' and worth == pytest.approx(valuation_views.BAR_SCALE) and paid == pytest.approx(worth * 75 / 120, abs=0.2)
    assert 'o' in row.select('.bv-bar i')[0]['class'] and 's' in row.select('.bv-bar i')[1]['class']
    assert row.select_one('.bv-gain').get_text() == 'Gain €45.00 · 60%' and not row.find('a')


def test_fewer_than_three_comparable_copies_say_charts_need_more_data(coll, client):
    quote(coll)
    paid_copy(coll, '1000-1', '20.00')
    paid_copy(coll, '1000-1', '25.00')
    node, text = section(client)
    assert node['data-state'] == 'few' and 'Charts need more data Paid against value needs 3 copies with a price paid and a quote. You have 2.' in text
    assert not node.select('.bv-bars')


def test_all_copies_without_a_price_paid_show_the_worth_only_with_the_count(coll, client):
    quote(coll, '40.00')
    themed(coll, '1000-1', 'Castle')
    for _ in range(3):
        coll.add_copy('1000-1', condition='used', completeness='complete')
    node, text = section(client)
    assert node['data-state'] == 'no_price' and node.select_one('.bv-title').get_text() == 'Worth €120.00 across 3 copies'
    assert 'No copy has a price paid, so there is no gain' in text and 'Without a price paid 3 copies no gain to show' in text
    assert not node.select('.bv-bar .o') and node.select('.bv-bar .s') and "Add a price paid in a copy's Edit sheet to compare." in text


def test_no_quotes_at_all_say_no_worth_yet_and_offer_update_prices(coll, client):
    paid_copy(coll, '1000-1', '20.00')
    coll.add_copy('1000-1', condition='used', completeness='complete')
    node, text = section(client)
    assert node['data-state'] == 'no_quotes' and node.select_one('.bv-title').get_text() == 'No worth yet for 2 copies'
    assert 'No sold prices are stored, so gain is hidden' in text and 'Total paid €20.00 Worth now no sales' in text
    assert node.select_one('a.bw-outline[href="/manage/refresh"]').get_text() == 'Update prices'


def test_converted_currencies_carry_a_note_with_the_rates_date_and_a_missing_rate_is_counted(coll, client):
    quote(coll, '40.00')
    rate(coll, 'USD', '1.08')
    for price in ('20.00', '25.00'):
        paid_copy(coll, '1000-1', price)
    coll.add_copy('1000-1', condition='used', completeness='complete', price='30.00', currency='USD')
    coll.add_copy('1000-1', condition='used', completeness='complete', price='30.00', currency='GBP')          # no rate for it
    node, text = section(client)
    assert 'Converted to EUR at the rates of 9 Oct · 1 copy paid in USD' in text and '1 copy needs a rate · left out of the totals' in text


def test_a_collection_with_no_copy_has_no_paid_vs_value(client, coll):
    assert section(client)[0] is None


def test_a_failed_read_is_the_error_state_with_retry(coll, client, monkeypatch):
    paid_copy(coll, '1000-1', '20.00')

    def broken(db, *args):
        raise sqlite3.OperationalError('boom')
    monkeypatch.setattr(valuation, 'copies', broken)
    node, text = section(client)
    assert 'Paid against value did not load.' in text and node.select_one('a.button').get_text() == 'Retry'
    assert node.select_one('.bw-outline[aria-disabled=true]').get_text() == 'Insurance report'


# ---- C. the insurance report ----

def photo(coll, copy_id, photo_id, n=0):
    item = coll.db.execute('SELECT item_id FROM copy WHERE id=?', (copy_id,)).fetchone()[0]
    coll.sql('INSERT INTO photo(id,item_id,copy_id,local_path,created_at,archived_at) VALUES(?,?,?,?,?,?)',
             (photo_id, item, copy_id, f'data/images/own/{photo_id}.jpg', f'2026-10-0{n + 1}T00:00:00.000Z', None))


def many(coll, count):
    quote(coll, '40.00')
    return [coll.add_copy('1000-1', condition='used', completeness='complete', price=f'{10 + n}.00', currency='EUR', date='2024-05-01') for n in range(count)]


def rows(page):
    return page.select('[data-copy-row]')


def test_the_report_page_has_the_header_the_proposal_note_and_the_two_outputs(coll, client):
    ids = many(coll, 3)
    coll.add_copy('1000-1', condition='used', completeness='complete')
    page = soup(client, '/manage/insurance-report')
    assert page.select_one('h1').get_text() == 'Insurance report' and words(page.select_one('.br-title p')) == 'One row per copy, as it will print · 4 copies'
    facts = {words(d.select_one('dt')): words(d.select_one('dd')) for d in page.select('.br-facts div')}
    assert facts == {'Generated': '27 Oct 2026', 'Copies': '4', 'Total paid': '€33.00', 'Total worth': '€120.00'}
    assert 'Totals count the 3 copies with a price paid · 1 copy has no price paid and is listed without one' in words(page.select_one('.br-foot'))
    assert words(page.select_one('.br-proposal')).startswith('Proposal The column set is provisional.')
    csv_link, print_link = page.select_one('.br-actions a.bw-outline'), page.select_one('.br-actions a.primary')
    assert csv_link['href'] == '/manage/insurance-report.csv' and csv_link.get_text(strip=True) == 'Download CSV'
    assert print_link['href'] == '/manage/insurance-report?print=1' and print_link.get_text() == 'Print' and print_link['target'] == '_blank'
    assert page.select_one('.bw-back')['href'] == '/manage/statistics'
    assert len(ids) == 3


def test_a_row_has_its_columns_and_the_copys_own_photos_never_the_set_cover(coll, client):
    quote(coll)
    copy = coll.add_copy('1000-1', condition='used', completeness='complete', price='24.00', currency='EUR', date='2025-03-09')
    for n in range(6):
        photo(coll, copy, f'p{n}' * 8, n)
    row = rows(soup(client, '/manage/insurance-report'))[0]
    assert [words(c) for c in row.select('.br-line > span')[:2]] == ['1000-1', 'Syn Castle Keep']
    assert words(row.select_one('.br-meta')) == '1990 Used Complete'
    assert words(row.select_one('.br-purchased')) == '9 Mar 2025' and words(row.select_one('.br-paid')) == '€24.00'
    assert words(row.select_one('.br-worth')) == '€61.00 9 Oct Used sold average'
    tiles = row.select('.br-tile img')
    assert len(tiles) == valuation_views.SHOWN_PHOTOS and words(row.select_one('.br-more')) == '2 more'
    assert [urlsplit(t['src']).path for t in tiles] == [f'/manage/images/' + f'p{n}' * 8 for n in range(4)]
    assert not any('?w=' in t['src'] for t in tiles)


def test_copies_without_photos_price_or_quote_have_their_own_words(coll, client):
    quote(coll)
    plain = coll.add_copy('1000-1', condition='used', completeness='complete')
    quiet = coll.add_copy('1000-2', condition='used', completeness='complete', price='9.00', currency='EUR')
    page = soup(client, '/manage/insurance-report')
    first, second = rows(page)
    assert words(first.select_one('.br-paid')) == 'No price paid' and first.select_one('.br-tile.br-empty').get_text() == 'No photo'
    assert not first.select('.br-tile img')
    assert words(second.select_one('.br-worth')) == 'no sales' and plain and quiet


def test_the_screen_pages_at_fifteen_while_print_and_csv_cover_every_copy(coll, client):
    many(coll, 19)
    first = soup(client, '/manage/insurance-report')
    assert len(rows(first)) == 15
    pager = first.select_one('nav.bc-pager')
    assert words(pager.select_one('p')) == '1 to 15 of 19 · Download and Print cover all 19'
    assert [a.get_text() for a in pager.select('.bc-page-number')] == ['1', '2'] and pager.select_one('[aria-current=page]').get_text() == '1'
    assert pager.select_one('.bc-page-next')['href'] == '/manage/insurance-report?page=2' and pager.select_one('.bc-page-prev').get('href') is None
    second = soup(client, '/manage/insurance-report?page=2')
    assert len(rows(second)) == 4 and words(second.select_one('nav.bc-pager p')).startswith('16 to 19 of 19')
    assert second.select_one('.bc-page-prev')['href'] == '/manage/insurance-report' and second.select_one('.bc-page-next').get('href') is None
    assert len(rows(soup(client, '/manage/insurance-report?page=99'))) == 4 and len(rows(soup(client, '/manage/insurance-report?page=x'))) == 15
    printing = soup(client, '/manage/insurance-report?print=1')
    assert len(printing.select('tbody.rp-copy')) == 19 and not printing.select('nav.bc-pager')
    body = client.get('/manage/insurance-report.csv').get_data(as_text=True)
    assert len(list(csv.reader(io.StringIO(body)))) == 20


def test_the_print_view_is_a_light_a4_document_that_prints_itself(coll, client):
    many(coll, 2)
    response = client.get('/manage/insurance-report?print=1')
    page = BeautifulSoup(response.data, 'html.parser')
    assert page.html['class'] == ['tw-light'] and page.body.has_attr('data-rp-auto') and page.select_one('script[src*=bw-report-print]')
    assert not page.select_one('.header, .rail') and words(page.select_one('.rp-title')) == 'Insurance report'
    assert {words(d) for d in page.select('.rp-facts dt')} == {'Generated', 'Copies', 'Total paid', 'Total worth'}
    assert [words(th) for th in page.select('.rp-table thead th')][:3] == ['Set', 'Name', 'Year']
    style = page.select_one('style').get_text()
    assert 'content:"27 Oct 2026 · 2 copies"' in style and 'content:"Insurance report · 27 Oct 2026"' in style
    css = (ROOT / 'static/web/toni/bw-report-print.css').read_text()
    for rule in ('size:A4 portrait', 'counter(page)', 'counter(pages)', '.rp-copy { break-inside:avoid', '@page :first', 'Insurance report, continued'):
        assert rule in css
    script = (ROOT / 'static/web/toni/bw-report-print.js').read_text()
    assert "addEventListener('load', () => window.print())" in script and not page.select('.rp-copy img[loading=lazy]')


def test_the_csv_is_the_cores_report_with_the_api_file_name(coll, client, read):
    many(coll, 2)
    response = client.get('/manage/insurance-report.csv')
    assert response.status_code == 200 and response.mimetype == 'text/csv'
    assert response.headers['Content-Disposition'] == 'attachment; filename=brickwork-insurance-report.csv'
    with read() as db:
        assert response.get_data(as_text=True) == valuation.report_csv(db)


def test_an_empty_collection_disables_both_outputs_and_offers_add_a_set(client):
    page = soup(client, '/manage/insurance-report')
    assert words(page.select_one('.br-title p')) == '0 copies'
    assert [(b.get_text(), b.has_attr('disabled')) for b in page.select('.br-actions button')] == [('Download CSV', True), ('Print', True)]
    empty = page.select_one('.br-nodata')
    assert words(empty).startswith('No copies to report The report lists one row per copy.') and empty.select_one('a.button')['href'] == '/manage/add'
    assert not page.select('[data-copy-row], .br-proposal')
    printing = BeautifulSoup(client.get('/manage/insurance-report?print=1').data, 'html.parser')
    assert not printing.body.has_attr('data-rp-auto') and 'No copies to report' in printing.get_text()


def test_the_report_needs_a_login_and_a_failed_read_is_an_error_not_a_trace(coll, client, monkeypatch):
    def broken(db, *args):
        raise sqlite3.OperationalError('boom')
    many(coll, 1)
    monkeypatch.setattr(valuation, 'report', broken)
    page = soup(client, '/manage/insurance-report')
    assert page.select_one('[role=alert]') and [b.has_attr('disabled') for b in page.select('.br-actions button')] == [True, True]


# ---- the files ----

def test_the_new_files_are_in_the_service_workers_shell_and_use_no_literal_colour():
    worker = (ROOT / 'static/web/toni/sw.js').read_text()
    for name in ('bw-value.css', 'bw-report-print.css', 'bw-report-print.js'):
        assert f'/static/web/toni/{name}' in worker and (ROOT / 'static/web/toni' / name).is_file()
    for name in ('bw-value.css', 'bw-report-print.css'):
        css = (ROOT / 'static/web/toni' / name).read_text()
        literals = set(re.findall(r'#[0-9a-fA-F]{3,8}\b', css)) - {'#fff', '#1A1816'}               # the white photo tile and the action ink fallback, as everywhere
        assert not literals and not re.search(r'box-shadow|gradient', css), name


# ---- rendered geometry, one per new screen, at 1440 and 390 ----

def inline(client, url, tmp_path, name):
    page = BeautifulSoup(client.get(url).data, 'html.parser')
    for link in page.select('link[rel=stylesheet]'):
        path = ROOT / urlsplit(link['href']).path.lstrip('/')
        if path.is_file():
            style = page.new_tag('style')
            style.string = path.read_text()
            link.replace_with(style)
    for script in page.select('script'):
        script.decompose()
    (tmp_path / f'{name}.html').write_text(str(page))


@rendered.group
def test_value_screens_geometry(coll, client, tmp_path):
    chrome = rendered.chrome()
    quote(coll, '40.00')
    themed(coll, '1000-1', 'Castle')
    themed(coll, '1000-2', 'Town')
    copy = paid_copy(coll, '1000-1', '20.00')
    for price in ('25.00', '30.00', '35.00'):
        paid_copy(coll, '1000-1', price, date='2023-02-02')
    paid_copy(coll, '1000-1', None)
    for n in range(14):
        paid_copy(coll, '1000-1', f'{40 + n}.00', date='2022-02-02')
    photo(coll, copy, 'a' * 32)
    inline(client, f"/collection/item/{coll.item('sets', '1000-1')}?copy={copy}", tmp_path, 'detail')
    inline(client, '/manage/statistics', tmp_path, 'statistics')
    inline(client, '/manage/insurance-report', tmp_path, 'report')
    result = subprocess.run(['node', 'tests/toni_bw_value_geometry.cjs', chrome, str(tmp_path)], capture_output=True, text=True, timeout=240, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
