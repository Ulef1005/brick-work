"""#43 printable lists and CSV, the API exports: split out of test_bw_lists_43.py in M.8e (issue #110); still the 3.3 text, waits for M.11 (API v2)."""
import csv
import io

from tests.test_bw_api_m1 import app  # noqa: F401
from tests.test_bw_api_m2 import populated  # noqa: F401

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
