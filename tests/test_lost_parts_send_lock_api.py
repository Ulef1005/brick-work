"""The Lost Parts send is locked (#469): the API refuses to switch it on and keeps reading it as off. MCP writes go through this API."""
from contextlib import closing

from brickwork.core.connect import connect
from brickwork.core.sync import lost_parts_send
from tests.api2 import call, v2, write  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401


def test_patch_settings_refuses_the_send_and_a_stored_value_reads_off(v2, world, pair):  # noqa: F811
    refused = write(v2, '/settings', 'patch', {'rebrickable_lost_parts_send': True})
    assert refused.status_code == 422 and lost_parts_send.LOCKED_MESSAGE in refused.get_data(as_text=True)
    with closing(connect(pair)) as db:
        db.execute("INSERT OR REPLACE INTO setting(key,value) VALUES(?, 'on')", (lost_parts_send.KEY,))
        db.commit()
    assert call(v2, '/settings').get_json()['data']['rebrickable_lost_parts_send'] is False
    assert write(v2, '/settings', 'patch', {'rebrickable_lost_parts_send': False}).status_code == 200
