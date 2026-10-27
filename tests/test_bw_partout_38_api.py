"""#38 the part-out value in the API's copy read: split out of test_bw_partout_38.py in M.8g (issue #110); still the 3.3 text, waits for API v2 (M.11)."""
from contextlib import closing
import os

from brickwork.core.connect import connect
from tests.test_bw_api_m1 import app  # noqa: F401
from tests.test_bw_api_m2 import populated  # noqa: F401

H = {'Authorization': 'Bearer synthetic-bootstrap'}


def test_api_copy_read_has_partout(populated):
    data = populated.test_client().get('/api/v1/copies/c1', headers=H).json['data']
    assert set(data['partout']) >= {'value', 'currency', 'lines', 'priced', 'unpriced_count'}
