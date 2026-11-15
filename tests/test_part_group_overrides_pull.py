"""The pull list uses your category moves (#315, part 3)."""
from bs4 import BeautifulSoup  # noqa: F401
from brickwork.core import admin
from tests.app4 import app4, client, csrf, make_pair, Coll  # noqa: F401 (fixtures)
from tests.stickers_world import World, coll, db, pair, world  # noqa: F401 (fixtures)
from tests.test_part_groups_pull import sections, soup_of


def test_pull_list_uses_the_move(client, world, coll):
    before = [s[0] for s in sections(soup_of(client, world, '?show=all'))]
    assert before == ['Plates', 'Decoration and extras']
    admin.patch_settings(coll.db, {'part_group_overrides': {'Stickers': 'Tiles'}})
    assert [s[0] for s in sections(soup_of(client, world, '?show=all'))] == ['Plates', 'Tiles']
    admin.patch_settings(coll.db, {'part_list_grouping': 'bricklink'})
    assert [s[0] for s in sections(soup_of(client, world, '?show=all'))] == ['Plates', 'Stickers']
