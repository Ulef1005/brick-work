"""#45 identification shows whether and where you own the part, on the 4.0 store (M.8h, issue #110). Invented data, no network."""
from bs4 import BeautifulSoup

from brickwork.core import identify, ownership, part_inventory
from tests.app4 import app4, client, coll, csrf, pair, read, world  # noqa: F401 (fixtures)


def test_summary_text_and_candidates(world, coll):
    black = coll.colour('0')
    coll.add_stock('part', world.brick, colour=black, quantity=14, storage=world.shelf)
    db = coll.db
    info = ownership.summary(db, [world.brick, world.local_part, 424242])
    part = info[world.brick]
    names = {c['color_id']: c['name'] for c in part['colours']}
    assert part['total'] == 19 and [c['quantity'] for c in part['colours']] == [14, 5]                      # most held first
    assert part['colours'][0]['storages'] == ['Shelf A'] and part['colours'][1]['storages'] == ['Shelf A']
    assert part['needed_count'] == 1 and part['needed_by'][0]['set_no'] == '1000-1' and part['needed_by'][0]['gap'] == 1
    assert ownership.text(part) == f"You have 19 in 2 colours: {names[black]} 14 (Shelf A), {names[world.red]} 5 (Shelf A)"
    assert info[world.local_part]['total'] == 5 and info[424242]['total'] == 0
    assert ownership.text(info[424242]) == ownership.text(None) == 'Not in your collection'
    rows, unresolved = part_inventory.candidates(db, [dict(item_type='P', item_no='3001', score=.9), dict(item_type='P', item_no='nowhere', score=.4)])
    assert [r['item_id'] for r in rows] == [world.brick] and rows[0]['owned_summary']['total'] == 19 and rows[0]['owned_summary']['text'].startswith('You have 19')
    assert unresolved == [dict(item_type='P', item_no='nowhere', score=.4, reason='Unknown catalogue identity')]
    same, _ = identify.candidates(db, [dict(item_type='P', item_no='3001', score=.9)])
    assert same[0]['owned_summary']['total'] == 19


def test_page_jump_link_and_script(world, client):
    page = BeautifulSoup(client.get('/workbench/what-is-this').data, 'html.parser')
    root = page.select_one('[data-wi-root]')
    assert root['data-url'] == '/workbench/part-to-inventory/detect' and root.select_one('input[type=file][accept="image/*"]')
    # Frame 3f capture: live preview with a guide, one primary that enables the camera, a saved photo as the quiet way in.
    assert root.select_one('[data-wi-viewfinder][hidden] video[playsinline]') and root.select_one('[data-wi-viewfinder] .wi-guide')
    assert root.select_one('button.wi-primary[data-wi-capture]').get_text(strip=True) == 'Enable camera'
    assert root.select_one('label.wi-link').get_text(strip=True) == 'Choose a saved photo'
    assert not root.select_one('input[capture]')  # the live camera replaces the picker's capture hint
    assert page.select_one('#global-jump a.jump-whatis')['href'] == '/workbench/what-is-this'
