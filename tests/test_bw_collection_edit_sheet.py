"""The set edit sheet built to frame 1e with photos (#397): order and groups, the three switches, flag fields, money prefixes, photo rows,
caption edits and removals saved by the one Save, and one Undo for all of it. The sheets of stock, a lot and a wish keep every field."""
from io import BytesIO
import json

from bs4 import BeautifulSoup
from PIL import Image

from brickwork.core import collection
from tests.app4 import app4, client, coll, csrf, pair, post, read, world  # noqa: F401 (fixtures)

SYSTEM = ('Set is checked', 'Box present', 'Instructions present')


def png():
    out = BytesIO()
    Image.new('RGB', (4, 3), 'white').save(out, 'PNG')
    return out.getvalue()


def sheet(client, url):
    return BeautifulSoup(client.get(url).text, 'html.parser').select_one('dialog#bc-edit')


def copy_url(w, copy):
    return f'/collection/item/{w.keep}?copy={copy}'


def add_photo(client, token, entity, identifier, caption=''):
    r = client.post('/collection/save/photo', data={'csrf_token': token, 'entity': entity, 'identifier': identifier, 'caption': caption, 'photo': (BytesIO(png()), 'p.png')})
    assert r.status_code == 200, r.json
    return r.json['event_id']


def photos(coll, **where):
    return [dict(r) for r in coll.db.execute('SELECT * FROM photo ORDER BY created_at,id')]


def flag_ids(coll, copy):
    return {r[0] for r in coll.db.execute('SELECT flag_id FROM copy_flag WHERE copy_id=?', (copy,))}


# ---------- order and groups ----------

def test_the_set_sheet_has_the_approved_order_and_two_groups(world, client):
    form = sheet(client, copy_url(world, world.copy_a)).select_one('form#bc-edit-form')
    names = []
    for field in form.select('[name]'):
        if field['name'] not in names or field['name'] == 'flags':
            names.append(field['name'])
    top = [n for n in names if n != 'flags']
    assert top == ['condition', 'completeness', 'purchase_currency', 'purchase_price', 'purchase_date', 'place_id', 'current_value_currency', 'current_value', 'storage_id', 'note']
    switches = form.select_one('.bc-switches')
    assert [s.get_text() for s in switches.select('.bc-sw > span')] == list(SYSTEM)
    groups = form.select('.bc-group')
    assert len(groups) == 2 and not switches.find_parent(class_='bc-group')
    first, second = groups
    assert [f['name'] for f in first.select('input[name],select[name]')] == ['purchase_currency', 'purchase_price', 'purchase_date', 'place_id', 'current_value_currency', 'current_value']
    assert [label.get_text() for label in second.select('.bc-field > label, .bc-field > .bc-label')] == ['Stored in', 'Owners', 'Tags', 'Note']
    order = list(form.descendants)
    assert order.index(form.select_one('fieldset.bc-segments')) < order.index(form.select('fieldset.bc-segments')[1]) < order.index(switches) < order.index(first) < order.index(second)
    panel = form.find_parent('dialog')
    assert order.index(second) < list(panel.descendants).index(panel.select_one('.bc-own-photos')) < list(panel.descendants).index(panel.select_one('.bc-sheet-footer'))
    assert len(form.select('.bc-two')) == 1 and form.select_one('.bc-two [name=purchase_price]') and form.select_one('.bc-two [name=purchase_date]')
    assert 'Your own value for this set. Empty uses the price Brick Work works out.' in first.get_text()
    assert not form.select('fieldset[data-bc-flags]') and 'Flags' not in [l.get_text() for l in form.select('legend')]


def test_the_sheet_head_has_the_mono_subtitle_and_an_icon_close(world, client):
    head = sheet(client, copy_url(world, world.copy_a)).select_one('.bc-sheet-head')
    assert head.select_one('h2').get_text() == 'Edit set' and head.select_one('.bc-sheet-sub.mono').get_text().startswith('1000-1')
    close = head.select_one('button[data-bw-close]')
    assert close['aria-label'] == 'Close' and close.select_one('svg') and not close.get_text(strip=True)


def test_the_three_system_flags_are_switches_and_not_in_the_flag_fields(world, coll, client):
    w = world
    form = sheet(client, copy_url(w, w.copy_a)).select_one('form#bc-edit-form')
    switches = {s.select_one('span').get_text(): s.select_one('input') for s in form.select('.bc-sw')}
    assert all(i['type'] == 'checkbox' and i['role'] == 'switch' and i['name'] == 'flags' for i in switches.values())
    assert [i['value'] for i in switches.values()] == [w.checked, w.box, w.booklet_flag]
    assert switches['Set is checked'].has_attr('checked') and not switches['Box present'].has_attr('checked')
    inside_fields = {i['value'] for i in form.select('.bc-multi input[name=flags]')}
    assert w.tag in inside_fields and not inside_fields & {w.checked, w.box, w.booklet_flag}


def test_a_switch_turns_a_flag_on_and_off_through_the_save(world, coll, client):
    token = csrf(client)
    w = world
    r = post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'flags': [w.tag, w.box]})
    assert r.status_code == 200 and flag_ids(coll, w.copy_a) == {w.tag, w.box}
    form = sheet(client, copy_url(w, w.copy_a))
    on = {s.select_one('span').get_text() for s in form.select('.bc-sw') if s.select_one('input').has_attr('checked')}
    assert on == {'Box present'}
    assert post(client, token, 'undo', event_id=r.json['event_id']).status_code == 200 and flag_ids(coll, w.copy_a) == {w.tag, w.checked}


def test_a_missing_system_flag_still_has_its_switch_and_is_made_by_the_save(world, coll, client):
    token = csrf(client)
    w = world
    coll.db.execute('DELETE FROM copy_flag WHERE flag_id=?', (w.box,))
    coll.db.execute('DELETE FROM flag WHERE id=?', (w.box,))
    coll.db.commit()
    before = coll.db.execute('SELECT COUNT(*) FROM flag').fetchone()[0]
    box = next(s.select_one('input') for s in sheet(client, copy_url(w, w.copy_a)).select('.bc-sw') if 'Box present' in s.get_text())
    assert box['value'] == 'system:Box present' and not box.has_attr('checked')
    assert coll.db.execute('SELECT COUNT(*) FROM flag').fetchone()[0] == before, 'rendering writes nothing'
    r = post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'flags': [w.checked, 'system:Box present']})
    assert r.status_code == 200, r.json
    made = dict(coll.db.execute("SELECT * FROM flag WHERE name='Box present'").fetchone())
    assert (made['kind'], made['system'], made['archived_at']) == ('status', 1, None)
    assert flag_ids(coll, w.copy_a) == {w.checked, made['id']}
    again = post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'flags': [w.checked, 'system:Box present']})
    assert again.status_code == 200 and coll.db.execute("SELECT COUNT(*) FROM flag WHERE name='Box present'").fetchone()[0] == 1, 'the flag made once is found again'
    assert post(client, token, 'undo', event_id=again.json['event_id']).status_code == 200
    assert post(client, token, 'undo', event_id=r.json['event_id']).status_code == 200
    assert flag_ids(coll, w.copy_a) == {w.tag, w.checked}
    assert post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'flags': ['system:Nothing']}).status_code == 400


def test_the_system_flag_entry_belongs_to_the_web_save_only(world, coll):
    import pytest
    with pytest.raises(ValueError, match='Unknown flag'):
        collection.save(coll.db, 'copy', [world.copy_a], {'flags': ['system:Box present']})


def test_owners_and_tags_are_multi_select_fields_of_flag_ids(world, coll, client):
    token = csrf(client)
    w = world
    alex, sam = coll.flag('Alex', 'owner'), coll.flag('Sam', 'owner')
    coll.tag('copy', w.copy_a, sam)
    form = sheet(client, copy_url(w, w.copy_a)).select_one('form#bc-edit-form')
    fields = {f.select_one('.bc-label').get_text(): f for f in form.select('.bc-field') if f.select_one('details.bc-multi')}
    assert list(fields) == ['Owners', 'Tags']
    owners = fields['Owners'].select_one('details.bc-multi')
    assert owners.has_attr('data-bc-multi') and owners.select_one('summary [data-bc-multi-value]').get_text() == 'Sam'
    assert [(i['value'], i.has_attr('checked'), i['data-name']) for i in owners.select('input[type=checkbox][name=flags]')] == [(alex, False, 'Alex'), (sam, True, 'Sam')]
    assert fields['Tags'].select_one('[data-bc-multi-value]').get_text() == 'collection'
    assert owners.select_one('summary')['aria-labelledby'] == fields['Owners'].select_one('.bc-label')['id']
    r = post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'flags': [w.checked, alex, sam, w.tag]})
    assert r.status_code == 200 and flag_ids(coll, w.copy_a) == {w.checked, alex, sam, w.tag}
    empty = sheet(client, copy_url(w, w.copy_b)).select_one('details.bc-multi [data-bc-multi-value]')
    assert empty.get_text() == 'None' and empty.has_attr('data-empty')


def test_a_status_field_appears_only_for_status_flags_that_are_not_switches(world, coll, client):
    w = world
    labels = lambda: [l.get_text() for l in sheet(client, copy_url(w, w.copy_a)).select('form#bc-edit-form .bc-field > .bc-label')]  # noqa: E731
    assert 'Status' not in labels()
    other = coll.flag('Needs photos', 'status')
    assert labels() == ['Status', 'Owners', 'Tags']
    assert [i['value'] for i in sheet(client, copy_url(w, w.copy_a)).select('#bc-status-flags-label ~ details input')] == [other]


# ---------- money ----------

def test_price_and_estimate_have_a_currency_prefix_with_the_server_currency_as_placeholder(world, coll, client):
    w = world
    coll.setting('display_currency', 'CHF')
    coll.setting('bricklink_currency', 'GBP')
    form = sheet(client, copy_url(w, w.copy_b)).select_one('form#bc-edit-form')
    price, estimate = (form.select_one(f'input[name={n}]') for n in ('purchase_price', 'current_value'))
    for amount, code, placeholder in ((price, 'purchase_currency', 'CHF'), (estimate, 'current_value_currency', 'GBP')):
        box = amount.find_parent(class_='bc-money')
        field = box.select_one(f'input[name={code}]')
        assert field['placeholder'] == placeholder and field['maxlength'] == '8' and list(box.find_all('input'))[0] is field
    assert form.select_one('label[for=bc-price]').get_text() == 'Price paid' and form.select_one('label[for=bc-estimate]').get_text() == 'Estimate'
    kept = sheet(client, copy_url(w, w.copy_a)).select_one('input[name=purchase_currency]')
    assert kept['value'] == 'EUR'
    assert sheet(client, copy_url(w, w.copy_a)).select_one('input[name=purchase_date]')['type'] == 'date'


# ---------- photos ----------

def test_photo_rows_show_caption_in_place_a_remove_mark_and_the_pending_row(world, coll, client):
    token = csrf(client)
    w = world
    empty = sheet(client, copy_url(w, w.copy_a)).select_one('.bc-own-photos')
    assert empty.select_one('[data-bc-photo-empty]').get_text() == 'No photos yet.' and empty.select_one('[data-bc-photo-count]').get_text() == 'none yet'
    add_photo(client, token, 'copy', w.copy_a, 'Front of the box')
    add_photo(client, token, 'copy', w.copy_a, '')
    section = sheet(client, copy_url(w, w.copy_a)).select_one('.bc-own-photos')
    assert section.select_one('h3').get_text() == 'Photos' and section.select_one('[data-bc-photo-count]').get_text() == '2 saved'
    rows = section.select('[data-bc-photo-row]')
    assert len(rows) == 2 and not section.select('[data-bc-photo-empty]')
    saved = photos(coll)
    first = rows[0]
    assert first['data-photo-id'] == saved[0]['id'] and first['data-bc-form'] == 'bc-edit-form'
    assert first.select_one('button.bc-thumb[data-bw-lightbox]') and first.select_one('img')['src'].startswith('/manage/images/')
    caption = first.select_one('input[data-bc-photo-caption]')
    assert (caption['value'], caption['data-initial'], caption['form'], caption['maxlength']) == ('Front of the box', 'Front of the box', 'bc-edit-form', '200') and not caption.has_attr('name')
    assert first.select_one('[data-bc-photo-meta]').get_text().startswith('Added ') and first.select_one('button[data-bc-photo-remove][aria-pressed=false]')
    assert rows[1].select_one('input[data-bc-photo-caption]')['placeholder'] == 'Add a caption'
    pending = section.select_one('[data-bc-photo-pending]')
    assert pending.has_attr('hidden') and pending.select_one('[name=new_photo_caption][form=bc-edit-form]') and pending.select_one('button[data-bc-photo-cancel]')
    assert 'New · added on Save' in pending.get_text()
    assert section.select_one('label[for=bc-photo-file]').get_text().strip() == 'Add photo' and section.select_one('[data-bc-photo-warning]').has_attr('hidden')
    assert 'Photos are added when you press Save.' in section.get_text()
    assert not section.select('form') and not section.select('button.primary')
    assert not sheet(client, copy_url(w, w.copy_b)).select('.bc-own-photos [data-bc-photo-row]')


def test_the_save_applies_caption_edits_and_removals_and_one_undo_takes_them_back(world, coll, client):
    token = csrf(client)
    w = world
    add_photo(client, token, 'copy', w.copy_a, 'Front')
    add_photo(client, token, 'copy', w.copy_a, 'Back')
    one, two = [p['id'] for p in photos(coll)]
    r = post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'note': 'edited'}, photo_captions={one: ' Front of the box '}, remove_photos=[two])
    assert r.status_code == 200 and len(r.json['also']) == 2, r.json
    assert coll.db.execute('SELECT caption FROM photo WHERE id=?', (one,)).fetchone()[0] == 'Front of the box'
    assert coll.db.execute('SELECT archived_at FROM photo WHERE id=?', (two,)).fetchone()[0] is not None
    assert (coll.db.execute('SELECT note FROM copy WHERE id=?', (w.copy_a,)).fetchone()[0]) == 'edited'
    fields = [coll.db.execute('SELECT field FROM event WHERE id=?', (i,)).fetchone()[0] for i in r.json['also']]
    assert fields == ['caption', 'remove_photo']
    html = client.get(copy_url(w, w.copy_a)).text
    assert BeautifulSoup(html, 'html.parser').select_one('.bc-own-photos [data-bc-photo-count]').get_text() == '1 saved'
    for event in [*reversed(r.json['also']), r.json['event_id']]:
        assert post(client, token, 'undo', event_id=event).status_code == 200, event
    assert coll.db.execute('SELECT caption, archived_at FROM photo WHERE id=?', (one,)).fetchone()[:] == ('Front', None)
    assert coll.db.execute('SELECT archived_at FROM photo WHERE id=?', (two,)).fetchone()[0] is None
    assert (coll.db.execute('SELECT note FROM copy WHERE id=?', (w.copy_a,)).fetchone()[0]) == 'Flea market'


def test_an_unchanged_caption_makes_no_event_and_the_file_stays_after_a_removal(world, coll, client, pair):
    token = csrf(client)
    w = world
    add_photo(client, token, 'copy', w.copy_a, 'Front')
    (only,) = photos(coll)
    r = post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'note': 'x'}, photo_captions={only['id']: 'Front'})
    assert r.status_code == 200 and 'also' not in r.json
    r = post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'note': 'y'}, remove_photos=[only['id']], photo_captions={only['id']: 'ignored'})
    assert r.status_code == 200 and len(r.json['also']) == 1
    assert (pair.parent / only['local_path']).is_file(), 'removing is not a file delete'
    assert coll.db.execute('SELECT caption FROM photo WHERE id=?', (only['id'],)).fetchone()[0] == 'Front'


def test_bad_photo_ids_and_captions_are_refused_before_anything_is_saved(world, coll, client):
    token = csrf(client)
    w = world
    add_photo(client, token, 'copy', w.copy_a, 'Mine')
    add_photo(client, token, 'copy', w.copy_b, 'Other copy')
    mine, other = [p['id'] for p in photos(coll)]
    note = lambda: coll.db.execute('SELECT note FROM copy WHERE id=?', (w.copy_a,)).fetchone()[0]  # noqa: E731
    cases = [dict(photo_captions={other: 'x'}), dict(remove_photos=[other]), dict(photo_captions={'nope': 'x'}), dict(remove_photos=['nope']),
             dict(photo_captions={mine: 'x' * 201}), dict(photo_captions=['x']), dict(remove_photos='x'), dict(photo_captions={mine: 5}), dict(remove_photos=[5])]
    for extra in cases:
        r = post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'note': 'must not save'}, **extra)
        assert r.status_code == 400, extra
        assert note() == 'Flea market', extra
    assert post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'note': 'ok'}, photo_captions={mine: 'x' * 200}).status_code == 200
    again = post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'note': 'ok2'}, remove_photos=[mine])
    assert again.status_code == 200
    assert post(client, token, 'save', entity='wish', ids=[w.wish_part], values={'note': 'w'}, remove_photos=[mine]).status_code == 400


def test_stock_photos_follow_the_same_save(world, coll, client):
    token = csrf(client)
    w = world
    add_photo(client, token, 'stock', w.stock_brick, 'Bin')
    (p,) = photos(coll)
    r = post(client, token, 'save', entity='stock', ids=[w.stock_brick], values={'note': 'n'}, photo_captions={p['id']: 'Bin 2'})
    assert r.status_code == 200 and len(r.json['also']) == 1
    assert coll.db.execute('SELECT caption FROM photo WHERE id=?', (p['id'],)).fetchone()[0] == 'Bin 2'
    assert post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'note': 'n'}, remove_photos=[p['id']]).status_code == 400


# ---------- the other sheets keep every field ----------

def names(panel):
    return {e['name'] for e in panel.select('form#bc-edit-form [name]')}


def test_the_stock_sheet_keeps_every_field_and_gets_the_same_structure(world, coll, client):
    w = world
    panel = sheet(client, f'/collection/item/{w.brick}?stock={w.stock_brick}&colour=4')
    assert {'condition', 'purchase_price', 'purchase_currency', 'purchase_date', 'place_id', 'lot_id', 'storage_id', 'flags', 'note'} <= names(panel)
    assert 'current_value' not in names(panel) and not panel.select('.bc-switches')
    form = panel.select_one('form#bc-edit-form')
    assert [l.get_text() for l in form.select('.bc-group')[1].select('.bc-field > label, .bc-field > .bc-label')] == ['Lot', 'Stored in', 'Status', 'Owners', 'Tags', 'Note']
    status = [i['value'] for i in form.select('#bc-status-flags-label ~ details input')]
    assert set(status) == {w.checked, w.box, w.booklet_flag}, 'stock has no switches: the status flags are a field'
    assert panel.select_one('input[name=condition][value=damaged]') and panel.select_one('.bc-own-photos [name=new_photo]')


def test_the_lot_sheet_keeps_every_field(world, client):
    w = world
    panel = sheet(client, f'/collection/lots/{w.bag}')
    assert panel and {'name', 'storage_id', 'place_id', 'purchase_date', 'purchase_price', 'purchase_currency', 'note'} <= names(panel)
    assert 'flags' not in names(panel) and 'condition' not in names(panel)
    assert json.loads(panel.select_one('form#bc-edit-form')['data-identity'])['entity'] == 'lot'


def test_the_wish_sheet_keeps_every_field(world, client):
    w = world
    panel = sheet(client, f'/collection/wishes/{w.wish_part}')
    assert {'quantity', 'qty_filled_manual', 'color_id', 'max_price', 'condition', 'flags', 'note'} <= names(panel) and 'max_price_currency' not in names(panel)   # #670: the currency shows only when it differs
    assert 'storage_id' not in names(panel) and not panel.select('.bc-switches')
    assert [l.get_text() for l in panel.select('form#bc-edit-form .bc-group .bc-field > label, form#bc-edit-form .bc-group .bc-field > .bc-label')] == ['Tags', 'Note']        # #670: Status and Owners are not on Edit wish


# ---------- one Save is all or nothing, and a Save sent again still saves ----------

def test_a_failed_photo_edit_rolls_back_the_details_and_every_event(world, coll, client, monkeypatch):
    token = csrf(client)
    w = world
    add_photo(client, token, 'copy', w.copy_a, 'Front')
    add_photo(client, token, 'copy', w.copy_a, 'Back')
    one, two = [p['id'] for p in photos(coll)]
    events_before = coll.db.execute('SELECT COUNT(*) FROM event').fetchone()[0]

    def broken(db, identifier):
        raise ValueError('Own photo is unavailable')
    monkeypatch.setattr(collection, 'remove_photo', broken)
    r = post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'note': 'must not stay'}, photo_captions={one: 'New caption'}, remove_photos=[two])
    assert r.status_code == 400
    assert coll.db.execute('SELECT note FROM copy WHERE id=?', (w.copy_a,)).fetchone()[0] == 'Flea market'
    assert coll.db.execute('SELECT caption FROM photo WHERE id=?', (one,)).fetchone()[0] == 'Front', 'the caption written before the failure is rolled back'
    assert coll.db.execute('SELECT COUNT(*) FROM event').fetchone()[0] == events_before


def test_a_save_sent_again_skips_photos_that_are_already_removed(world, coll, client):
    token = csrf(client)
    w = world
    add_photo(client, token, 'copy', w.copy_a, 'Front')
    add_photo(client, token, 'copy', w.copy_a, 'Back')
    one, two = [p['id'] for p in photos(coll)]
    first = post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'note': 'first'}, photo_captions={one: 'Front, new'}, remove_photos=[two])
    assert first.status_code == 200 and len(first.json['also']) == 2
    again = post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'note': 'second'}, photo_captions={one: 'Front, new', two: 'x' * 500}, remove_photos=[two])
    assert again.status_code == 200, again.json
    assert 'also' not in again.json, 'nothing is written twice: the caption is the same and the photo is already gone'
    assert coll.db.execute('SELECT note FROM copy WHERE id=?', (w.copy_a,)).fetchone()[0] == 'second'
    assert post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'note': 'third'}, photo_captions={two: 'y' * 300}).status_code == 200      # a caption for a removed photo is skipped
    add_photo(client, token, 'copy', w.copy_b, 'Other')
    other = photos(coll)[-1]['id']
    assert post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'note': 'no'}, remove_photos=[other]).status_code == 400      # not this copy's photo: still an error


def test_the_caption_length_is_checked_only_for_captions_that_are_written(world, coll, client):
    token = csrf(client)
    w = world
    add_photo(client, token, 'copy', w.copy_a, 'Front')
    (p,) = photos(coll)
    long = 'z' * 201
    assert post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'note': 'a'}, photo_captions={p['id']: long}, remove_photos=[p['id']]).status_code == 200
    add_photo(client, token, 'copy', w.copy_a, 'Next')
    nxt = photos(coll)[-1]['id']
    assert post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'note': 'b'}, photo_captions={nxt: long}).status_code == 400


# ---------- the system flags are found the way the workbench finds them ----------

def test_a_system_flag_in_another_case_is_the_switch_and_no_duplicate_is_made(world, coll, client):
    token = csrf(client)
    w = world
    coll.db.execute("UPDATE flag SET name='box present' WHERE id=?", (w.box,))
    coll.db.commit()
    page = sheet(client, copy_url(w, w.copy_a))
    box = next(s.select_one('input') for s in page.select('.bc-sw') if 'Box present' in s.get_text())
    assert box['value'] == w.box, 'the switch is the flag the workbench reads'
    assert w.box not in [i['value'] for i in page.select('.bc-multi input')]
    r = post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'flags': [w.checked, 'system:Box present']})
    assert r.status_code == 200 and flag_ids(coll, w.copy_a) == {w.checked, w.box}
    assert coll.db.execute("SELECT COUNT(*) FROM flag WHERE lower(name)='box present'").fetchone()[0] == 1


def test_two_live_flags_of_one_system_name_are_refused_not_added_to(world, coll, client):
    token = csrf(client)
    w = world
    coll.flag('BOX PRESENT', 'status')
    box = next(s.select_one('input') for s in sheet(client, copy_url(w, w.copy_a)).select('.bc-sw') if 'Box present' in s.get_text())
    assert box['value'] == 'system:Box present'
    r = post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'flags': ['system:Box present']})
    assert r.status_code == 400 and 'Two status flags' in r.json['message']
    assert coll.db.execute("SELECT COUNT(*) FROM flag WHERE lower(name)='box present'").fetchone()[0] == 2


def test_set_is_checked_is_matched_by_its_exact_name_like_the_checker(world, coll, client):
    token = csrf(client)
    w = world
    coll.db.execute("UPDATE flag SET name='set is checked' WHERE id=?", (w.checked,))
    coll.db.commit()
    page = sheet(client, copy_url(w, w.copy_a))
    switch = next(s.select_one('input') for s in page.select('.bc-sw') if 'Set is checked' in s.get_text())
    assert switch['value'] == 'system:Set is checked', 'a flag in another case is not the one the checker and the set page read'
    r = post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'flags': ['system:Set is checked']})
    assert r.status_code == 200
    assert coll.db.execute("SELECT COUNT(*) FROM flag WHERE name='Set is checked'").fetchone()[0] == 1
