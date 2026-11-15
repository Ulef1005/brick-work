"""#401 · The set page's part list: Edit parts, the edit mode, Save missing, Found all and the Set is checked switch.

Same fixture copy as the Set Inspector tests: a copy of `1000-1` with two required parts (3001 red x4, 3023 white x2), one spare part and a
figure line. Invented data, no network."""
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from brickwork.core import checker
from tests.app4 import app4, client, coll, csrf, pair, read  # noqa: F401 (fixtures)

ROOT = Path(__file__).resolve().parents[1]
SAVE = '/collection/save/'


@pytest.fixture
def copy(coll):
    return coll.add_copy('1000-1', condition='used', completeness='incomplete', completeness_source='derived')


def lines(db, copy_id):
    return {r['quantity']: r for r in db.execute(
        'SELECT * FROM copy_part WHERE copy_id=? AND copy_figure_id IS NULL AND is_spare=0 AND retired_at IS NULL', (copy_id,))}


def soup(client, db, copy_id):
    item = db.execute('SELECT item_id FROM copy WHERE id=?', (copy_id,)).fetchone()[0]
    response = client.get(f'/collection/item/{item}?copy={copy_id}')
    assert response.status_code == 200
    return BeautifulSoup(response.get_data(as_text=True), 'html.parser')


def flag_on(db, copy_id):
    return checker.checked(db, copy_id)


def test_the_header_offers_edit_parts_beside_check_parts_and_the_switch(coll, copy, client):
    page = soup(client, coll.db, copy)
    buttons = page.select_one('.bc-pl-buttons')
    assert [b.get_text(strip=True) for b in buttons.find_all(['a', 'button'])] == ['Check parts', 'Edit parts']
    assert 'primary' in buttons.select_one('a')['class'] and 'bc-outline' in buttons.select_one('button')['class']
    switch = page.select_one('[data-bc-pl-checked]')
    assert switch['role'] == 'switch' and switch['aria-checked'] == 'false' and switch['data-copy'] == copy
    assert page.select_one('[data-bc-pl-rule]').get_text(strip=True) == 'Complete needs Set is checked and nothing missing.'
    assert not page.select_one('.bc-pl-missing-only')                        # no parts missing, no link
    assert page.select_one('[data-bc-pl-mode][hidden]') and page.select_one('[data-bc-pl-bar][hidden]')
    slot = page.select_one('[data-bc-pl-receipt]')
    assert slot and not slot.select('p, button')                            # the page's own receipt line moves in here by script
    assert page.select_one('script[src*="bw-part-edit.js"]')


def test_check_missing_only_is_a_text_link_under_the_buttons_when_parts_are_missing(coll, copy, client):
    db = coll.db
    part = lines(db, copy)[4]
    checker.mark(db, copy, [(f'p:{part["id"]}', dict(missing=2))])
    page = soup(client, db, copy)
    box = page.select_one('.bc-check-actions')
    assert [c.name for c in box.find_all(recursive=False)] == ['div', 'form']
    link = box.select_one('form.bc-pl-missing-only button')
    assert link.get_text(strip=True) == 'Check missing only' and 'bc-pl-link' in link['class'] and 'bc-outline' not in link['class']
    assert box.select_one('form input[name=scope]')['value'] == 'missing'


def test_a_read_only_instance_has_no_controls(coll, copy, client, app4):
    app4.config['BW_READ_ONLY'] = True
    try:
        page = soup(client, coll.db, copy)
    finally:
        app4.config['BW_READ_ONLY'] = False
    for hidden in ('.bc-check-actions', '[data-bc-pl-edit]', '[data-bc-pl-checked]', '[data-bc-pl-row]', '[data-bc-pl-bar]', '[data-bc-pl-ticked]',
                   '[data-bc-found-one]', '[data-bc-found-all]'):
        assert not page.select_one(hidden), hidden
    assert 'Check parts' not in page.get_text()
    assert 'Editing is switched off on this instance' in page.get_text()
    assert page.select_one('.bc-pl-flag').get_text(' ', strip=True) == 'Set is checked No'
    assert not page.select_one('script[src*="bw-part-edit.js"]')


def test_edit_mode_markup_has_a_tick_per_part_a_stepper_for_more_than_one_and_opens_pre_ticked(coll, copy, client):
    db = coll.db
    four, two = lines(db, copy)[4], lines(db, copy)[2]
    checker.mark(db, copy, [(f'p:{four["id"]}', dict(missing=3))])
    page = soup(client, db, copy)
    rows = {int(r['data-bc-pl-row']): r for r in page.select('[data-bc-pl-row]')}
    assert set(rows) == {four['id'], two['id']}                              # required part lines only: no spare, no figure
    for row in rows.values():
        box = row.select_one('button[data-bc-pl-box][role=checkbox]')
        assert box['aria-checked'] == 'false' and box['aria-label'].startswith('Missing')
        assert row.select_one('[data-bc-pl-need-text]')
        assert row.select_one('[data-bc-pl-line]').has_attr('hidden')
        assert row.find().name == 'span' and 'bc-pl-tick' in row.find()['class']          # the tick is the row's first item
    assert rows[four['id']]['data-bc-pl-need'] == '4' and rows[four['id']]['data-bc-pl-missing'] == '3'
    assert rows[two['id']]['data-bc-pl-missing'] == '0'
    steppers = {i: r.select_one('.bc-pl-stepper') for i, r in rows.items()}
    assert steppers[four['id']] and steppers[four['id']].select_one('output').get_text() == '1'
    assert 'of 4 missing' in rows[four['id']].get_text()
    assert len(steppers[four['id']].select('button')) == 2
    assert page.select('[data-bc-pl-ticked][hidden]')                       # one counter per section, hidden until ticks exist


def test_a_part_needed_once_has_no_stepper(coll, copy, client):
    db = coll.db
    part = lines(db, copy)[2]
    db.execute('UPDATE copy_part SET quantity=1 WHERE id=?', (part['id'],))
    db.commit()
    row = soup(client, db, copy).select_one(f'[data-bc-pl-row="{part["id"]}"]')
    assert not row.select_one('.bc-pl-stepper') and '1 missing' in row.get_text()


def test_missing_rows_are_plain_rows_with_found_one_and_found_all(coll, copy, client):
    db = coll.db
    four, two = lines(db, copy)[4], lines(db, copy)[2]
    checker.mark(db, copy, [(f'p:{four["id"]}', dict(missing=3)), (f'p:{two["id"]}', dict(missing=1))])
    page = soup(client, db, copy)
    big = page.select_one(f'[data-bc-pl-row="{four["id"]}"]')
    small = page.select_one(f'[data-bc-pl-row="{two["id"]}"]')
    assert 'bc-pl-plain' in big['class'] and 'needs 4 · 3 missing' in big.select_one('.bc-missing-count').get_text(' ', strip=True)
    assert [b.get_text(strip=True) for b in big.select('.bc-found button')] == ['Found 1', 'Found all']
    assert [b.get_text(strip=True) for b in small.select('.bc-found button')] == ['Found 1']      # Found all only above one
    found_all = big.select_one('[data-bc-found-all]')
    assert 'p:' + str(four['id']) in found_all['data-identity']


def test_save_missing_marks_counts_as_checked_caps_and_has_one_undo(coll, copy, client):
    db = coll.db
    four, two = lines(db, copy)[4], lines(db, copy)[2]
    token = csrf(client)
    done = client.post(SAVE + 'mark-missing', json=dict(copy_id=copy, csrf_token=token, rows=[dict(id=four['id'], missing=3), dict(id=two['id'], missing=1)]))
    assert done.status_code == 200 and done.json['message'] == 'Saved · 2 parts marked missing'
    got = lines(db, copy)
    assert (got[4]['missing'], got[4]['checked'], got[2]['missing'], got[2]['checked']) == (3, 1, 1, 1)
    assert not flag_on(db, copy)                                            # Set is checked stays the person's own switch
    assert db.execute("SELECT count(*) FROM event WHERE entity_kind='part_check' AND entity_id=?", (copy,)).fetchone()[0] >= 1
    events = db.execute("SELECT id FROM event WHERE entity_kind='part_check' AND entity_id=? AND field='save'", (copy,)).fetchall()
    assert len(events) == 1 and events[0][0] == done.json['event_id']       # both lines in one receipt
    assert db.execute('SELECT completeness FROM copy WHERE id=?', (copy,)).fetchone()[0] == 'incomplete'
    undone = client.post(SAVE + 'undo', json=dict(event_id=done.json['event_id'], csrf_token=token))
    assert undone.status_code == 200
    got = lines(db, copy)
    assert (got[4]['missing'], got[2]['missing']) == (0, 0) and (got[4]['checked'], got[2]['checked']) == (0, 0)


def test_save_missing_clears_a_row_and_leaves_unsent_rows_alone(coll, copy, client):
    db = coll.db
    four, two = lines(db, copy)[4], lines(db, copy)[2]
    checker.mark(db, copy, [(f'p:{four["id"]}', dict(missing=2, checked=True)), (f'p:{two["id"]}', dict(missing=1, checked=True))])
    token = csrf(client)
    done = client.post(SAVE + 'mark-missing', json=dict(copy_id=copy, csrf_token=token, rows=[dict(id=four['id'], missing=0)]))
    assert done.status_code == 200 and done.json['message'] == 'Saved · 1 marked found'
    got = lines(db, copy)
    assert (got[4]['missing'], got[4]['checked'], got[2]['missing']) == (0, 1, 1)          # cleared stays checked; the other row untouched


@pytest.mark.parametrize('rows', [
    None, [], 'x', [1], [dict(id=1)], [dict(missing=1)], [dict(id='1', missing=1)], [dict(id=True, missing=1)], [dict(id=1, missing=1.5)],
    [dict(id=1, missing=True)], [dict(id=1, missing='2')],
])
def test_save_missing_refuses_a_malformed_request(coll, copy, client, rows):
    token = csrf(client)
    bad = client.post(SAVE + 'mark-missing', json=dict(copy_id=copy, csrf_token=token, rows=rows))
    assert bad.status_code == 400 and bad.json['message']


def test_save_missing_validates_every_row_against_the_copy_and_saves_nothing_on_a_failure(coll, copy, client):
    db = coll.db
    four, two = lines(db, copy)[4], lines(db, copy)[2]
    spare = db.execute('SELECT id FROM copy_part WHERE copy_id=? AND is_spare=1', (copy,)).fetchone()[0]
    figure_part = db.execute('SELECT id FROM copy_part WHERE copy_id=? AND copy_figure_id IS NOT NULL LIMIT 1', (copy,)).fetchone()[0]
    other = coll.add_copy('1000-1')
    foreign = lines(db, other)[4]['id']
    token = csrf(client)
    good = dict(id=two['id'], missing=1)
    for bad_row, text in [(dict(id=four['id'], missing=5), 'from 0 to 4'), (dict(id=four['id'], missing=-1), 'from 0 to 4'),
                          (dict(id=spare, missing=1), 'No such part line'), (dict(id=figure_part, missing=1), 'No such part line'),
                          (dict(id=foreign, missing=1), 'No such part line'), (dict(id=999999, missing=1), 'No such part line'),
                          (dict(id=two['id'], missing=2), 'Name each part line once')]:
        refused = client.post(SAVE + 'mark-missing', json=dict(copy_id=copy, csrf_token=token, rows=[good, bad_row]))
        assert refused.status_code == 400 and text in refused.json['message'], (bad_row, refused.json)
    assert lines(db, copy)[2]['missing'] == 0 and lines(db, copy)[4]['missing'] == 0           # the good row was not saved either
    assert client.post(SAVE + 'mark-missing', json=dict(copy_id='nope', csrf_token=token, rows=[good])).status_code == 400
    assert client.post(SAVE + 'mark-missing', json=dict(copy_id=copy, csrf_token='wrong', rows=[good])).status_code == 400
    assert db.execute("SELECT count(*) FROM event WHERE entity_kind='part_check' AND field='save'").fetchone()[0] == 0


def test_save_missing_is_refused_on_a_read_only_instance(coll, copy, client, app4):
    four = lines(coll.db, copy)[4]
    token = csrf(client)
    app4.config['BW_READ_ONLY'] = True
    try:
        refused = client.post(SAVE + 'mark-missing', json=dict(copy_id=copy, csrf_token=token, rows=[dict(id=four['id'], missing=1)]))
        also = client.post(SAVE + 'set-checked', json=dict(copy_id=copy, csrf_token=token, wanted=True))
        again = client.post(SAVE + 'found-all', json=dict(copy_id=copy, csrf_token=token, token=f'p:{four["id"]}'))
    finally:
        app4.config['BW_READ_ONLY'] = False
    assert refused.status_code == also.status_code == again.status_code == 403
    assert lines(coll.db, copy)[4]['missing'] == 0 and not flag_on(coll.db, copy)


def test_found_all_sets_the_missing_count_to_zero_with_an_undo(coll, copy, client):
    db = coll.db
    four = lines(db, copy)[4]
    checker.mark(db, copy, [(f'p:{four["id"]}', dict(missing=3))])
    token = csrf(client)
    done = client.post(SAVE + 'found-all', json=dict(copy_id=copy, token=f'p:{four["id"]}', csrf_token=token))
    assert done.status_code == 200 and done.json['message'] == 'Found all'
    assert lines(db, copy)[4]['missing'] == 0
    client.post(SAVE + 'undo', json=dict(event_id=done.json['event_id'], csrf_token=token))
    assert lines(db, copy)[4]['missing'] == 3
    checker.mark(db, copy, [(f'p:{four["id"]}', dict(missing=0))])
    refused = client.post(SAVE + 'found-all', json=dict(copy_id=copy, token=f'p:{four["id"]}', csrf_token=token))
    assert refused.status_code == 400 and 'not missing' in refused.json['message']
    assert client.post(SAVE + 'found-all', json=dict(copy_id=copy, token='x:1', csrf_token=token)).status_code == 400
    assert client.post(SAVE + 'found-all', json=dict(copy_id=copy, token='p:999999', csrf_token=token)).status_code == 400


def test_the_switch_saves_at_once_with_a_receipt_and_undo_and_missing_parts_do_not_move_it(coll, copy, client):
    db = coll.db
    four = lines(db, copy)[4]
    token = csrf(client)
    on = client.post(SAVE + 'set-checked', json=dict(copy_id=copy, wanted=True, csrf_token=token))
    assert on.status_code == 200 and on.json['message'] == 'Set is checked · on' and flag_on(db, copy)
    saved = client.post(SAVE + 'mark-missing', json=dict(copy_id=copy, csrf_token=token, rows=[dict(id=four['id'], missing=1)]))
    assert saved.status_code == 200 and flag_on(db, copy)                      # saving missing never switches it, on or off
    assert db.execute('SELECT completeness FROM copy WHERE id=?', (copy,)).fetchone()[0] == 'incomplete'
    page = soup(client, db, copy)
    assert page.select_one('[data-bc-pl-checked]')['aria-checked'] == 'true'
    assert page.select_one('[data-bc-pl-rule]').get_text(strip=True).startswith('Stays Incomplete while 1 part is missing.')
    client.post(SAVE + 'undo', json=dict(event_id=saved.json['event_id'], csrf_token=token))
    off = client.post(SAVE + 'set-checked', json=dict(copy_id=copy, wanted=False, csrf_token=token))
    assert off.status_code == 200 and off.json['message'] == 'Set is checked · off' and not flag_on(db, copy)
    client.post(SAVE + 'undo', json=dict(event_id=off.json['event_id'], csrf_token=token))
    assert flag_on(db, copy)
    for wanted in ('yes', 1, None, 'true'):
        assert client.post(SAVE + 'set-checked', json=dict(copy_id=copy, wanted=wanted, csrf_token=token)).status_code == 400


def test_the_part_edit_script_and_styles_are_wired(coll, copy, client):
    css = (ROOT / 'static/web/toni/bw-collection.css').read_text()
    assert '#bw-collection .bc-pl-box { width:44px;height:44px' in css and '.bc-pl-bar { position:sticky' in css
    assert 'main label' not in css.split('/* #401')[1]                       # none of the new rules reaches for a bare label
