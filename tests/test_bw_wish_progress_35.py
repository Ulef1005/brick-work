"""#35 wishlist progress on the 4.0 store (M.8g, issue #110): derived filled quantity, manual override, QTYFILLED export and page. Invented data.

The API's wish read and PATCH (M.11) are in test_bw_wish_progress_35_api.py, which waits for them."""
from bs4 import BeautifulSoup

from brickwork.core import collection, planning, wishlists
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401 (fixtures)


def setup(coll):
    """Wish 1: 2 used red 3001, and 9 used red 3001 in loose stock (filled). Wish 2: 3 of the set 1000-2, one copy of it (not filled)."""
    brick, red, gate = coll.item('parts', '3001'), coll.colour('4'), coll.item('sets', '1000-2')
    part = coll.add_wish(brick, colour=red, quantity=2, condition='used')
    coll.add_stock('part', brick, colour=red, quantity=9, condition='used')
    coll.add_stock('part', brick, colour=red, quantity=4, condition='new')                       # a new part does not fill a wish for a used one
    kit = coll.add_wish(gate, quantity=3, condition='any')
    coll.add_copy('1000-2')
    return part, kit


def test_derived_manual_and_order(coll, read):
    part, kit = setup(coll)
    with read() as db:
        rows = {r['id']: r for r in planning.wishes(db)}
        assert (rows[part]['qty_filled'], rows[part]['qty_filled_source'], rows[part]['filled']) == (9, 'derived', True)
        assert (rows[kit]['qty_filled'], rows[kit]['filled']) == (1, False)
        assert [r['id'] for r in planning.wishes(db)] == [kit, part]                      # filled lines last
    collection.save(coll.db, 'wish', [kit], {'qty_filled_manual': '3'})
    with read() as db:
        row = next(r for r in planning.wishes(db) if r['id'] == kit)
        assert (row['qty_filled'], row['qty_filled_source'], row['filled']) == (3, 'manual', True)
    collection.save(coll.db, 'wish', [kit], {'qty_filled_manual': ''})
    with read() as db:
        assert next(r for r in planning.wishes(db) if r['id'] == kit)['qty_filled_source'] == 'derived'


def test_an_archived_copy_and_a_new_part_do_not_fill(coll, read):
    part, kit = setup(coll)
    coll.sql("UPDATE copy SET archived_at='2026-10-27T00:00:00.000Z'")
    coll.sql("UPDATE stock SET archived_at='2026-10-27T00:00:00.000Z' WHERE condition='used'")
    with read() as db:
        rows = {r['id']: r for r in planning.wishes(db)}
    assert rows[kit]['qty_filled'] == 0 and rows[part]['qty_filled'] == 0 and rows[part]['filled'] is False


def test_export_writes_qtyfilled_capped(coll, read):
    setup(coll)
    with read() as db:
        content = wishlists.export(db, 'default', format='bricklink')['content']
    assert '<QTYFILLED>2</QTYFILLED>' in content          # 9 in stock, capped at the wanted 2
    assert '<QTYFILLED>1</QTYFILLED>' in content          # one copy of three wanted sets


def test_wishlist_page_progress_and_chip(coll, client):
    part, kit = setup(coll)
    soup = BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser')
    line = soup.select_one('.bp-filled')
    assert line['data-filled'] == 'false' and line.select_one('.mono').get_text() == '1 of 3'
    done = soup.select('.bp-filled[data-filled=true]')[0]
    assert done.select_one('.mono').get_text() == '2 of 2' and 'Filled' in done.get_text()
    chip = soup.select_one('[data-bp-pick=filled][data-value=false]')
    assert chip and chip.get_text(' ', strip=True).startswith('Not yet filled')
