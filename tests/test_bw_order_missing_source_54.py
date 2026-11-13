"""Order missing parts, the source of each line (#54): BrickLink or Pick a Brick, the totals per source and the two files.

Core (`order_missing.split`, `pick_a_brick_csv`) and the route. The element ids are invented rows in the fixture catalogue; prices are
cached quotes of today. Invented data, no network."""
from decimal import Decimal
import sqlite3
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from brickwork.core import order_missing, planning
from brickwork.core.sources.base import now
from tests.app4 import app4, client, coll, csrf, pair, read  # noqa: F401 (fixtures)
from tests.test_bw_order_missing_225 import URL, page, scene

RED_3001 = ('3001', '4')


def elements(pair, coll, *rows):
    """Add `(part key, colour key, element id)` rows to the fixture catalogue."""
    with sqlite3.connect(pair.parent / 'catalogue.db') as db:
        for part, colour, element in rows:
            db.execute('INSERT INTO element(element_id,item_id,color_id) VALUES(?,?,?)', (element, coll.item('parts', part), coll.colour(colour)))


def quote(coll, part, colour, price, condition='used'):
    coll.price(coll.item('parts', part), price, colour=coll.colour(colour), condition=condition, source='bricklink', guide='sold', region='eu', currency='EUR',
               observed=now().isoformat(), minimum='0.01', maximum='9', sold=10, qty=10)


def placed(read, ids, **choices):
    with read() as db:
        order = order_missing.order_list(db, order_missing.candidates(db), set(ids))
        return order_missing.split(db, order, prefer=choices.get('prefer', False), chosen=choices.get('chosen', {}), config=planning.configuration(db))


def by_part(order):
    return {l['number_text']: l for l in order['lines']}


# ---------- the placement ----------

def test_a_part_and_colour_with_several_element_ids_gets_the_lowest_one(coll, pair, read):
    s = scene(coll)
    elements(pair, coll, (*RED_3001, '4140000'), (*RED_3001, '300126'))
    line = by_part(placed(read, [s['first']]))['3001']
    assert line['element_id'] == '300126'


def test_every_line_starts_on_bricklink_and_the_switch_moves_the_ones_with_an_element_id(coll, pair, read):
    s = scene(coll)
    elements(pair, coll, (*RED_3001, '300126'))
    ids = [s['first'], s['gate_new']]
    plain = by_part(placed(read, ids))
    assert plain['3001']['source'] == 'bl' and plain['3023']['source'] == 'bl'
    preferred = by_part(placed(read, ids, prefer=True))
    assert preferred['3001']['source'] == 'pab' and preferred['3023']['source'] == 'bl' and preferred['3023']['element_id'] is None


def test_a_line_placed_by_hand_beats_the_switch_and_a_line_with_no_element_id_cannot_go_to_pick_a_brick(coll, pair, read):
    s = scene(coll)
    elements(pair, coll, (*RED_3001, '300126'))
    ids = [s['first'], s['gate_new']]
    red, white = by_part(placed(read, ids))['3001'], by_part(placed(read, ids))['3023']
    hand = order_missing.parse_choices([order_missing.choice_value(red['key'], 'pab'), order_missing.choice_value(white['key'], 'pab')])
    order = by_part(placed(read, ids, chosen=hand))
    assert order['3001']['source'] == 'pab' and order['3023']['source'] == 'bl'              # no element id: the choice is ignored
    back = by_part(placed(read, ids, prefer=True, chosen={red['key']: 'bl'}))
    assert back['3001']['source'] == 'bl'


def test_choices_in_the_query_are_read_strictly():
    assert order_missing.parse_choices(['12.4.U.p', '12.4.N.b', 'x', '.p', '12.4.U.z']) == {'12.4.U': 'pab', '12.4.N': 'bl'}


# ---------- the totals ----------

def test_the_bricklink_part_is_priced_with_its_shipping_and_pick_a_brick_has_no_price(coll, pair, read):
    s = scene(coll)
    elements(pair, coll, (*RED_3001, '300126'))
    quote(coll, '3001', '4', '0.40')
    order = placed(read, [s['first'], s['second'], s['gate_new']], prefer=True)
    sp = order['split']
    assert sp['pab'] == dict(lines=1, pieces=3) and sp['bl']['lines'] == 1 and sp['bl']['pieces'] == 1
    assert sp['bl']['total'] == 0 and sp['bl']['no_sales'] == 1 and sp['shipping'] == Decimal(3) and sp['estimate'] == Decimal(3)
    every = placed(read, [s['first'], s['second'], s['gate_new']])['split']
    assert every['bl']['total'] == Decimal('1.20') and every['bl']['no_sales'] == 1 and every['estimate'] == Decimal('4.20')
    assert [l['number_text'] for l in every['no_element']] == ['3023']


def test_no_shipping_is_added_when_nothing_is_on_bricklink(coll, pair, read):
    s = scene(coll)
    elements(pair, coll, (*RED_3001, '300126'))
    sp = placed(read, [s['first']], prefer=True)['split']
    assert sp['bl']['lines'] == 0 and sp['shipping'] is None and sp['estimate'] == 0


# ---------- the file ----------

def test_the_pick_a_brick_file_is_element_id_and_quantity_of_its_lines(coll, pair, read):
    s = scene(coll)
    elements(pair, coll, (*RED_3001, '300126'))
    order = placed(read, [s['first'], s['second'], s['gate']], prefer=True)
    assert order_missing.pick_a_brick_csv(order) == 'elementId,quantity\r\n300126,4\r\n'
    assert order_missing.pick_a_brick_csv(placed(read, [s['first']])) == 'elementId,quantity\r\n'


# ---------- the page and its two files ----------

def copies(s, *keys):
    return [s[k] for k in keys]


def test_the_page_places_the_lines_and_the_chips_and_tabs_are_links(coll, pair, client):
    s = scene(coll)
    elements(pair, coll, (*RED_3001, '300126'))
    quote(coll, '3001', '4', '0.40')
    soup = page(client, sel='1', copy=copies(s, 'first', 'gate_new'), step='review')
    assert soup.select_one('.oo-prefer')['aria-checked'] == 'false'
    assert [t.text.split() for t in soup.select('.oo-tabs a')] == [['All', '2'], ['BrickLink', '2'], ['Pick', 'a', 'Brick', '0']]
    [red] = [l for l in soup.select('.oo-line') if '3001' in l.text]
    chips = red.select('.oo-sc')
    assert chips[0].select_one('b').text == 'BrickLink' and 'on' in chips[0]['class'] and '€0.40' in chips[0].text
    assert 'src=' in chips[1]['href'] and chips[1]['href'].endswith('.p') or '.p' in chips[1]['href']
    [white] = [l for l in soup.select('.oo-line') if '3023' in l.text]
    assert white.select('.oo-sc')[0].select_one('i').text == 'no sales'
    assert 'dis' in white.select('.oo-sc')[1]['class'] and 'no element id' in white.select('.oo-sc')[1].text
    assert 'Shipping, estimate' in soup.select_one('.oo-tots').text and '€3.00' in soup.select_one('.oo-tots').text
    assert 'no element id' in soup.select_one('.oo-warn').text
    assert soup.select_one('.oo-export .button.primary').text == 'Download BrickLink XML'


def test_the_default_switch_and_a_chip_move_lines_to_pick_a_brick_and_the_files_follow(coll, pair, client):
    s = scene(coll)
    elements(pair, coll, (*RED_3001, '300126'))
    ids = copies(s, 'first', 'second', 'gate_new')
    soup = page(client, sel='1', copy=ids, step='review', prefer='1')
    assert soup.select_one('.oo-prefer')['aria-checked'] == 'true'
    assert [t.text.split()[-1] for t in soup.select('.oo-tabs a')] == ['2', '1', '1']
    [pab] = soup.select('.oo-export a.button:not(.primary)')
    assert pab['download'] == 'pick-a-brick.csv' and pab.text == 'Download Pick a Brick CSV'
    assert client.get(pab['href']).get_data(as_text=True) == 'elementId,quantity\r\n300126,3\r\n'
    xml = ET.fromstring(client.get(soup.select_one('.oo-export a.primary')['href']).data)
    assert [(i.find('ITEMID').text, i.find('MINQTY').text) for i in xml.findall('ITEM')] == [('3023', '1')]
    only = page(client, sel='1', copy=ids, step='review', prefer='1', tab='pab')
    assert len(only.select('.oo-line')) == 1 and 'Prices and availability are not looked up.' in only.select_one('.oo-tots').text
    assert 'Shipping' not in only.select_one('.oo-tots').text


def test_with_nothing_on_pick_a_brick_its_file_is_disabled_with_the_reason(coll, client):
    s = scene(coll)
    soup = page(client, sel='1', copy=copies(s, 'first'), step='review')
    button = soup.select('.oo-export .button')[1]
    assert button['aria-disabled'] == 'true' and 'no line is set to Pick a Brick' in soup.select_one('.oo-export').text


def test_with_every_line_on_pick_a_brick_the_xml_is_disabled_with_the_reason(coll, pair, client):
    s = scene(coll)
    elements(pair, coll, (*RED_3001, '300126'))
    soup = page(client, sel='1', copy=copies(s, 'first'), step='review', prefer='1')
    assert soup.select('.oo-export .button')[0]['aria-disabled'] == 'true' and 'every line is set to Pick a Brick' in soup.select_one('.oo-export').text


def test_the_copy_form_keeps_the_source_choices(coll, pair, client):
    s = scene(coll)
    elements(pair, coll, (*RED_3001, '300126'))
    soup = page(client, sel='1', copy=copies(s, 'first'), prefer='1', tab='pab', src=['1.2.U.b'])
    form = soup.select_one('[data-oo-form]')
    assert [(i['name'], i['value']) for i in form.select('input[type=hidden]') if i['name'] in ('prefer', 'tab', 'src')] == [('prefer', '1'), ('tab', 'pab'), ('src', '1.2.U.b')]


def test_the_files_refuse_a_copy_that_is_not_in_the_list(coll, client):
    scene(coll)
    for path in ('missing-parts.xml', 'pick-a-brick.csv'):
        assert client.get(f'{URL}/{path}', query_string=dict(copy=['nope'])).status_code == 400
        assert client.get(f'{URL}/{path}').status_code == 400


def test_the_copy_list_reads_missing_and_never_a_minus(coll, client):
    scene(coll)
    text = page(client).select_one('[data-oo-rows]').text
    assert 'missing' in text and '−' not in text and '-' not in text.replace('1000-1', '').replace('1000-2', '')
