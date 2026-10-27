"""#35 wishlist progress in the API's wish PATCH: split out of test_bw_wish_progress_35.py in M.8g (issue #110); still the 3.3 text, waits for the
writes of API v2 (M.11c). The read half of this test is tests/test_api2_read_money.py."""
from contextlib import closing
import os

from brickwork.core.connect import connect
from tests.test_bw_api_m1 import app  # noqa: F401
from tests.test_bw_api_m2 import populated  # noqa: F401

H = {'Authorization': 'Bearer synthetic-bootstrap'}


def store():
    return closing(connect(os.environ['BW_DB_PATH']))


def test_api_fields_and_patch(populated):
    c = populated.test_client()
    etag = c.get('/api/v1/wishes/1', headers=H).headers.get('ETag')
    patched = c.patch('/api/v1/wishes/1', json={'qty_filled_manual': 1}, headers=dict(H, **{'Idempotency-Key': 'wf-1', 'If-Match': etag or '*'}))
    assert patched.status_code == 200, patched.json
    wish = c.get('/api/v1/wishes/1', headers=H).json['data']
    assert (wish['qty_filled'], wish['qty_filled_source']) == (1, 'manual')
