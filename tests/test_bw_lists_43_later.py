"""#43 printable lists, the entry points on the planning screens: split out of test_bw_lists_43.py in M.8e (issue #110); still the 3.3 text,
waits for the planning screens (M.8g)."""
from bs4 import BeautifulSoup

from tests.test_bw_collection import bw, legacy, reset_shell_metadata_after_test  # noqa: F401
from tests.web_fixtures import apps, logged_in  # noqa: F401


def test_planning_entry_points_to_the_print_views(bw, apps):
    web = apps('toni')
    client = logged_in(web)
    complete = BeautifulSoup(client.get('/planning/complete-sets').data, 'html.parser')
    assert complete.select_one('[data-bp-print][aria-disabled=true]')
    wishlist = BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser')
    assert wishlist.find('a', href=lambda h: h and h.startswith('/lists/wishlist/print'))
