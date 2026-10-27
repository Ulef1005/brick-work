"""Collection tests of the Workbench's reach into the item page (M.8e, issue #110): Matching on the item page, Take and Give, loose-figure
gaps, the scanner note. Moved out of test_bw_collection.py in M.8d; rewritten on 4.0 fixtures with the workbench.

Premise gone: `test_46s_merged_part_transfers_keep_every_row_and_undo` merged four rows of one part into a line; a copy holds one line per
part and colour now (`copy_part_key`), so there is nothing to merge (the per-line rows of a figure are separate lines).
"""
from bs4 import BeautifulSoup

from brickwork.core import collection, workbench
from tests.app4 import app4, client, coll, csrf, pair, post, read, world  # noqa: F401 (fixtures)


def derived_copy(coll):
    copy = coll.add_copy('1000-1', condition='used', completeness='incomplete', completeness_source='derived')
    for name in ('Set is checked', 'Instructions present', 'Box present'):
        coll.tag('copy', copy, coll.flag(name, 'status'))
    return copy


def soup(client, url):
    response = client.get(url)
    assert response.status_code == 200, url
    return BeautifulSoup(response.data, 'html.parser')


def test_matching_transfer_completes_and_undo(world, coll, client):
    copy = derived_copy(coll)
    coll.mark(copy, '3001', '4', missing=1)
    line = coll.db.execute('SELECT id FROM copy_part WHERE copy_id=? AND item_id=? AND color_id=?', (copy, world.brick, world.red)).fetchone()[0]
    token = csrf(client)
    r = client.get(f'/collection/item/{world.brick}?colour={world.red}')
    assert r.status_code == 200 and b'Completes set' in r.data
    r = post(client, token, 'transfer', source_id=world.stock_brick, copy_id=copy, target='part', target_id=line, quantity=1)
    assert r.status_code == 200, r.json
    assert coll.db.execute('SELECT completeness FROM copy WHERE id=?', (copy,)).fetchone()[0] == 'complete'
    assert post(client, token, 'undo', event_id=r.json['event_id']).status_code == 200
    assert coll.db.execute('SELECT missing FROM copy_part WHERE id=?', (line,)).fetchone()[0] == 1


def test_loose_minifigure_gaps_share_transfer_and_undo(world, coll, client):
    db = coll.db
    coll.sql('UPDATE stock_part SET missing=1 WHERE id=1')
    part = db.execute('SELECT item_id,color_id FROM stock_part WHERE id=1').fetchone()
    source = coll.add_stock('part', part['item_id'], colour=part['color_id'], quantity=2)
    assert any(r['target'] == 'stock-part' for r in workbench.matches(db)), workbench.gaps(db)
    token = csrf(client)
    r = client.get(f'/collection/item/{world.figure}?stock={world.stock_figure}')
    assert r.status_code == 200 and b'Loose minifigure' in r.data and b'Take 1' in r.data
    payload = dict(source_id=source, copy_id=world.stock_figure, target='stock-part', target_id=1, quantity=1)
    r = post(client, token, 'transfer', **payload)
    assert r.status_code == 200, r.json
    assert db.execute('SELECT missing FROM stock_part WHERE id=1').fetchone()[0] == 0
    assert db.execute("SELECT copy_id FROM stock_transfer WHERE kind='stock-part'").fetchone()[0] is None
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert post(client, token, 'transfer', **payload).status_code == 400
    assert post(client, token, 'undo', event_id=r.json['event_id']).status_code == 200
    assert db.execute('SELECT missing FROM stock_part WHERE id=1').fetchone()[0] == 1


def test_matching_and_jump_queries_are_bounded(world, coll):
    db = coll.db

    def measured(call):
        queries = []
        db.set_trace_callback(queries.append)
        try:
            call()
        finally:
            db.set_trace_callback(None)
        return len(queries)
    small = measured(lambda: workbench.matches(db))
    search_small = measured(lambda: collection.search(db, 'part'))
    for n in range(60):
        coll.add_stock('part', world.brick, colour=world.red, quantity=1, condition='used', lot=coll.lot(f'bounded-{n}'))
    assert measured(lambda: workbench.matches(db)) == small
    assert measured(lambda: collection.search(db, 'part')) == search_small
    assert small < 40 and search_small < 20


def test_part_facts_matching_and_quantity(world, coll, client):
    scanner = 'Parts inventory scanner event e5f5a61a-bdc7-41eb-a325-18af6d86de13'
    coll.sql("UPDATE stock SET note=? WHERE kind='part' AND item_id=?", (scanner, world.brick))
    detail = collection.detail(coll.db, world.brick, colour=world.red)
    assert detail['matches']
    page = soup(client, f'/collection/item/{world.brick}?colour={world.red}')
    assert [n.get_text() for n in page.select('[data-module=info] dt')][:3] == ['Condition', 'Damaged', 'Quantity']
    assert page.select_one('.bc-quantity-pill:not(.bc-condition-pill)').get_text() == '×' + str(sum(r['quantity'] for r in detail['instances']))
    matching = page.select_one('[data-module=matching]')
    assert matching.h3.get_text() == detail['matching_headline']
    assert 'Loose stock against recorded gaps' not in matching.get_text()
    assert scanner not in matching.get_text()
    assert matching.select_one('[data-bc-row][title]')['title'] == scanner
    assert collection.matching_note(scanner + ' · Keep in drawer') == 'Keep in drawer'
    assert collection.matching_note(scanner) == ''
    assert collection.matching_note('Parts inventory scanner event e5f5a61abdc741eba32518af6d86de13a1b2 · Note') == 'Note'
    assert collection.matching_note('Parts inventory scanner event e5f5a61abdc741eba32518af6d86de13a1b2.') == ''
    assert collection.matching_note('Keep in drawer') == 'Keep in drawer'


def test_matching_leaves_set_detail_and_edit_panel_holds_instances_and_photos(world, coll, client):
    set_page = soup(client, f'/collection/item/{world.keep}?copy={world.copy_a}')
    assert not set_page.select('[data-module=matching]')
    for url, has_matching in ((f'/collection/item/{world.keep}?copy={world.copy_a}', False), (f'/collection/item/{world.brick}?colour={world.red}', True),
                              (f'/collection/item/{world.figure}?stock={world.stock_figure}', True)):
        page = soup(client, url)
        assert bool(page.select('[data-module=matching]')) == has_matching, url
        layout = page.select_one('.bc-detail-layout')
        assert not layout.select('.bc-own-photos') and not [h for h in layout.select('h2') if h.get_text().startswith('Instances')]
        panel = page.select_one('dialog#bc-edit')
        headings = [h.get_text() for h in panel.select('.bc-edit-section > h3')]
        assert any(h.startswith('Instances') for h in headings) and 'Own photos' in headings
        assert panel.select_one('form[data-bc-action=save]') and panel.select_one('.bc-own-photos form[data-bc-action=photo]')
        assert panel.select_one('.bc-edit-section[data-bc-list] [data-bc-rows]')


def test_a_booklet_page_lists_the_copies_that_miss_it_and_gives_it(world, coll, client):
    page = soup(client, f'/collection/item/{world.local_booklet}')
    matching = page.select_one('[data-module=matching]')
    rows = matching.select('[data-bc-row]')
    assert len(rows) == 2 and all('Instructions missing' in ' '.join(r.get_text().split()) for r in rows)
    form = rows[0].select_one('form[data-bc-action=transfer]')
    assert form and 'Give 1' in form.get_text()
    token = csrf(client)
    response = post(client, token, 'transfer', source_id=world.stock_booklet, copy_id=world.copy_a, target='instructions', target_id=world.copy_a, quantity=1)
    assert response.status_code == 200
    again = soup(client, f'/collection/item/{world.local_booklet}')
    assert len(again.select('[data-module=matching] [data-bc-row]')) == 0 or not again.select_one('[data-module=matching] form')
