"""#43 printable lists and CSV: missing parts, Part Picker results, wishlist. Invented data."""
import csv
import io

from bs4 import BeautifulSoup

from tests.test_bw_api_m1 import app  # noqa: F401
from tests.test_bw_api_m2 import populated  # noqa: F401
from tests.test_bw_collection import bw, legacy, reset_shell_metadata_after_test  # noqa: F401
from tests.web_fixtures import apps, logged_in  # noqa: F401
from tests import web_fixtures

H = {'Authorization': 'Bearer synthetic-bootstrap'}


def rows(response):
    assert response.status_code == 200, response.data[:300]
    assert response.mimetype == 'text/csv'
    return list(csv.reader(io.StringIO(response.get_data(as_text=True))))


def test_api_missing_picker_and_wishlist_csv(populated):
    c = populated.test_client()
    missing = rows(c.get('/api/v1/export/missing.csv?copy_id=c1', headers=H))
    assert missing[0] == ['Item type', 'Item number', 'Name', 'Colour', 'Colour id', 'Condition', 'Quantity', 'Note']
    part = next(r for r in missing[1:] if r[1] == '3001')
    assert part[:5] == ['P', '3001', 'Synthetic brick', 'Synthetic red', '4'] and part[6] == '3'  # 2 missing + 1 damaged, as the XML export counts
    picker = rows(c.get('/api/v1/export/picker.csv?copy_id=c1', headers=H))
    assert picker[0][0] == 'Rank' and picker[1][:3] == ['1', 'P', '3001']
    wishes = rows(c.get('/api/v1/export/wishlist.csv', headers=H))
    assert wishes[0][0] == 'List' and wishes[1][:3] == ['Wishlist', 'P', '3001']
    assert c.get('/api/v1/export/missing.csv', headers=H).status_code == 422
    assert c.get('/api/v1/export/wishlist.csv?list=nope', headers=H).status_code == 404
    assert c.get('/api/v1/export/wishlist.csv?bogus=1', headers=H).status_code == 400


def test_print_view_and_entry_points(bw, apps):
    web = apps('toni')
    client = logged_in(web)
    page = BeautifulSoup(client.get('/lists/missing/print?copy=copy').data, 'html.parser')
    assert page.h1.get_text() == 'Missing parts' and page.select_one('[data-pr-print]')
    assert page.select_one('a[href*="/lists/missing.csv"]') and 'pictures=0' in page.find('a', string='Hide pictures')['href']
    assert page.select_one('.pr-head p').get_text().startswith(f"{len(page.select('tbody tr'))} line")
    off = BeautifulSoup(client.get('/lists/missing/print?copy=copy&pictures=0').data, 'html.parser')
    assert not off.select('.pr-pic')
    empty = BeautifulSoup(client.get('/lists/missing/print').data, 'html.parser')
    assert empty.select_one('.pr-error')
    wl = BeautifulSoup(client.get('/lists/wishlist/print').data, 'html.parser')
    assert wl.h1.get_text() == 'Wishlist'
    assert client.get('/lists/wishlist.csv').mimetype == 'text/csv'
    complete = BeautifulSoup(client.get('/planning/complete-sets').data, 'html.parser')
    assert complete.select_one('[data-bp-print][aria-disabled=true]')
    wishlist = BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser')
    assert wishlist.find('a', href=lambda h: h and h.startswith('/lists/wishlist/print'))
