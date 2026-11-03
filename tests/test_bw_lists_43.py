"""#43 printable lists and CSV on the 4.0 store (M.8e, issue #110): missing parts, Part Picker results, wishlist. Invented data.

Split out to later pieces: the API exports (`test_bw_lists_43_api.py`, M.11) and the entry points on the planning screens
(`test_bw_lists_43_later.py`, M.8g).
"""
import csv
import io

from bs4 import BeautifulSoup

from brickwork.core import list_exports
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401 (fixtures)


def rows(response):
    assert response.status_code == 200, response.data[:300]
    assert response.mimetype == 'text/csv'
    return list(csv.reader(io.StringIO(response.get_data(as_text=True))))


def test_missing_picker_and_wishlist_rows_and_csv(world, coll, client):
    coll.mark(world.copy_a, '3001', '4', missing=2, damaged=1)
    coll.mark(world.copy_b, '3001', '4', missing=1)
    coll.mark(world.copy_a, '3023', '15', missing=1)
    ids = [world.copy_a, world.copy_b]
    missing = rows(client.get(f'/lists/missing.csv?copy={ids[0]}&copy={ids[1]}'))
    assert missing[0] == ['Item type', 'Item number', 'Name', 'Colour', 'Colour id', 'Condition', 'Quantity', 'Note']
    brick = [r for r in missing[1:] if r[1] == '3001']
    # 2 missing + 1 damaged of the used copy, as the XML export counts; the new copy is its own line.
    assert sorted((r[5], r[6]) for r in brick) == [('New', '1'), ('Used', '3')] and brick[0][:5] == ['P', '3001', 'Brick 2 x 4', 'Red', str(world.red)]
    picker = rows(client.get(f'/lists/picker.csv?copy={ids[0]}&copy={ids[1]}'))
    assert picker[0][0] == 'Rank' and picker[1][:3] == ['1', 'P', '3001'] and picker[1][6] == '4' and '1000-1' in picker[1][7]
    wishes = rows(client.get('/lists/wishlist.csv'))
    assert wishes[0][0] == 'List' and [r[:3] for r in wishes[1:]] == [['Wishlist', 'P', '3023'], ['Wishlist', 'S', '1000-2']] and wishes[1][8:10] == ['0.50', 'EUR']
    assert client.get('/lists/missing.csv').status_code == 400
    assert client.get('/lists/wishlist.csv?list=nope').status_code == 400
    assert client.get('/lists/nonsense.csv').status_code == 404


def test_an_item_without_a_bricklink_number_stays_on_the_missing_list_marked(world, coll):
    unnamed = coll.local('part', 'Mystery part')
    copy = world.copy_b
    coll.sql("INSERT INTO copy_part(copy_id,item_id,color_id,is_spare,quantity,missing,damaged,checked) VALUES(?,?,?,0,1,1,0,0)", (copy, unnamed, world.red))
    lines = list_exports.missing(coll.db, [copy])
    mystery = next(r for r in lines if r['item_id'] == unnamed)
    assert mystery['unresolved'] and mystery['name'] == 'Mystery part'
    assert list_exports.to_csv('missing', lines).count('Not matched yet') == 1


def test_print_view_and_entry_points(world, coll, client):
    coll.mark(world.copy_a, '3001', '4', missing=1)
    page = BeautifulSoup(client.get(f'/lists/missing/print?copy={world.copy_a}').data, 'html.parser')
    assert page.h1.get_text() == 'Missing parts' and page.select_one('[data-pr-print]')
    assert page.select_one('a[href*="/lists/missing.csv"]') and 'pictures=0' in page.find('a', string='Hide pictures')['href']
    assert page.select_one('.pr-head p').get_text().startswith(f"{len(page.select('tbody tr'))} line")
    assert page.select_one('.pr-no').get_text() == '3001' and 'Red' in page.select_one('.pr-colour').get_text()
    off = BeautifulSoup(client.get(f'/lists/missing/print?copy={world.copy_a}&pictures=0').data, 'html.parser')
    assert not off.select('.pr-pic')
    assert BeautifulSoup(client.get('/lists/missing/print').data, 'html.parser').select_one('.pr-error')
    picked = BeautifulSoup(client.get(f'/lists/picker/print?copy={world.copy_a}').data, 'html.parser')
    assert picked.h1.get_text() == 'Part Picker' and picked.select_one('td.pr-num').get_text() == '1'
    wishlist = BeautifulSoup(client.get('/lists/wishlist/print').data, 'html.parser')
    assert wishlist.h1.get_text() == 'Wishlist' and len(wishlist.select('tbody tr')) == 2
    assert client.get('/lists/wishlist.csv').mimetype == 'text/csv'
    picker_page = BeautifulSoup(client.get(f'/workbench/part-picker?copy={world.copy_a}&pick=1').data, 'html.parser')
    assert picker_page.select_one('a.bw-print-list')['href'].startswith('/lists/picker/print')
