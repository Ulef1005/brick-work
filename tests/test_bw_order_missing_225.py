"""Order missing parts (#225): the copies with gaps, a choice among them, the combined order list with its sources, and the file.

The list is `planning.ranking`'s, so the preview and `planning.export` agree for the same copies by construction; the tests pin that, the
loose-stock subtraction, the lines the file leaves out, the totals of a partial choice, the leave-out filter and the URL as the only state.
Invented data, no network."""
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from brickwork.core import order_missing, planning
from brickwork.core.sources.base import now
from tests.app4 import coll, pair, read  # noqa: F401 (fixtures)

SETTINGS = dict(bricklink_region='eu', bricklink_currency='EUR', incomplete_discount_pct='30', repair_shipping='3', repair_fees='0.5',
                repair_min_order='10', repair_use_loose_stock='0')
URL = '/planning/order-missing-parts'


def scene(coll):
    """Three copies lacking red 3001 (2 in Set 1 of 1000-1, 1 in its Set 2, 1 in 1000-2) and a fourth, 1000-2 new, lacking one white 3023."""
    for key, value in SETTINGS.items():
        coll.setting(key, value)
    first, second = coll.add_copy('1000-1', condition='used'), coll.add_copy('1000-1', condition='used')
    gate, gate_new = coll.add_copy('1000-2', condition='used'), coll.add_copy('1000-2', condition='new')
    coll.mark(first, '3001', '4', missing=2)
    coll.mark(second, '3001', '4', missing=1)
    coll.mark(gate, '3001', '4', missing=1)
    coll.mark(gate_new, '3023', '15', missing=1)
    return dict(first=first, second=second, gate=gate, gate_new=gate_new)


def rows(read):
    with read() as db:
        return order_missing.candidates(db)


def page(client, **query):
    r = client.get(URL, query_string=query)
    assert r.status_code == 200, r.get_data(as_text=True)
    return BeautifulSoup(r.data, 'html.parser')


def ticked(soup):
    return [c['value'] for c in soup.select('[data-oo-copy]') if c.has_attr('checked')]


def test_the_same_part_colour_and_condition_is_combined_with_its_sources(coll, read):
    s = scene(coll)
    with read() as db:
        candidates = order_missing.candidates(db)
        order = order_missing.order_list(db, candidates, {s['first'], s['second'], s['gate']})
    [line] = [l for l in order['lines'] if l['number_text'] == '3001']
    assert line['quantity'] == 4 and line['condition'] == 'U' and line['color_name']
    assert [(x['label'], x['quantity']) for x in line['sources']] == [('1000-1 · Set 1', 2), ('1000-1 · Set 2', 1), ('1000-2 · Set 1', 1)]
    assert order['pieces'] == 4 and not order['skipped']


def test_a_condition_makes_another_line(coll, read):
    s = scene(coll)
    with read() as db:
        order = order_missing.order_list(db, order_missing.candidates(db), {s['gate'], s['gate_new']})
    assert {(l['number_text'], l['condition'], l['quantity']) for l in order['lines']} == {('3001', 'U', 1), ('3023', 'N', 1)}


def test_the_totals_count_the_chosen_copies_only(coll, read):
    s = scene(coll)
    with read() as db:
        every = order_missing.candidates(db)
        part = order_missing.order_list(db, every, {s['first'], s['gate_new']})
        none = order_missing.order_list(db, every, set())
    assert part['pieces'] == 3 and len(part['lines']) == 2
    assert none == dict(lines=[], skipped=[], pieces=0)


def test_loose_stock_comes_off_the_quantity_and_the_sources(coll, read):
    s = scene(coll)
    coll.setting('repair_use_loose_stock', '1')
    coll.add_stock('part', coll.item('parts', '3001'), colour=coll.colour('4'), quantity=3, condition='used')
    with read() as db:
        every = order_missing.candidates(db)
        order = order_missing.order_list(db, every, {s['first'], s['second'], s['gate']})
    [line] = order['lines']
    assert line['quantity'] == 1 and sum(x['quantity'] for x in line['sources']) == 1       # 4 missing, 3 in the pile, in set-number order


def test_the_preview_is_the_file(coll, read):
    s = scene(coll)
    chosen = [s['second'], s['gate'], s['gate_new']]
    with read() as db:
        order = order_missing.order_list(db, order_missing.candidates(db), set(chosen))
        file = ET.fromstring(planning.export(db, chosen)['xml'])
    in_file = sorted((i.findtext('ITEMID'), i.findtext('COLOR'), i.findtext('CONDITION'), i.findtext('MINQTY')) for i in file.findall('ITEM'))
    shown = sorted((l['bricklink'][1], str(l['bricklink'][2]), l['condition'], str(l['quantity'])) for l in order['lines'])
    assert in_file == shown and len(in_file) == 2


def test_a_line_with_no_bricklink_number_is_left_out_and_named(coll, read):
    s = scene(coll)
    local = coll.local('part', 'Mystery plate')
    coll.sql('INSERT INTO copy_part(copy_id,item_id,color_id,quantity,missing) VALUES(?,?,?,?,?)', (s['first'], local, coll.colour('4'), 2, 2))
    with read() as db:
        order = order_missing.order_list(db, order_missing.candidates(db), {s['first']})
        file = ET.fromstring(planning.export(db, [s['first']])['xml'])
    [skipped] = order['skipped']
    assert skipped['name'] == 'Mystery plate' and skipped['why'] == 'no BrickLink number' and skipped['sources'][0]['quantity'] == 2
    assert [l['number_text'] for l in order['lines']] == ['3001'] and len(file.findall('ITEM')) == 1
    assert order['pieces'] == 2                                                              # the line left out is not in the pieces


def test_a_copy_to_sell_or_part_out_is_left_out_by_its_flag(coll, read):
    s = scene(coll)
    for name, kind, copy in (('To sell', 'status', s['first']), ('part-out donor', 'tag', s['gate']), ('collection', 'tag', s['second'])):
        coll.tag('copy', copy, coll.flag(name, kind))
    by = {r['id']: r for r in rows(read)}
    assert by[s['first']]['to_sell'] == 'To sell' and by[s['gate']]['to_sell'] == 'part-out donor'
    assert by[s['second']]['to_sell'] is None and by[s['gate_new']]['to_sell'] is None
    assert order_missing.left_out(by[s['first']], sell=True, gain=False) == 'To sell'
    assert order_missing.left_out(by[s['first']], sell=False, gain=False) is None
    for name in ('Parted out', 'For sale', 'selling', 'Part out'):
        assert order_missing.sell_flag(name)
    for name in ('collection', 'Set is checked', 'Box present', 'Sealed', 'Counterpart'):
        assert not order_missing.sell_flag(name)


def test_only_sets_that_gain_value_counts_a_copy_without_a_price_as_no_gain(coll, read):
    s = scene(coll)
    keep = coll.item('sets', '1000-1')
    coll.price(keep, '100', condition='used', source='bricklink', guide='sold', region='eu', currency='EUR', observed=now().isoformat(), minimum='1', maximum='101', sold=10, qty=10)
    coll.price(coll.item('parts', '3001'), '0.1', colour=coll.colour('4'), condition='used', source='bricklink', guide='sold', region='eu', currency='EUR',
               observed=now().isoformat(), minimum='1', maximum='2', sold=10, qty=10)
    by = {r['id']: r for r in rows(read)}
    assert by[s['first']]['gain'] and by[s['first']]['gain'] > 0
    assert by[s['gate']]['gain'] is None and by[s['gate_new']]['gain'] is None
    assert order_missing.left_out(by[s['gate']], sell=False, gain=True) == 'no value gain'
    assert order_missing.left_out(by[s['first']], sell=False, gain=True) is None
