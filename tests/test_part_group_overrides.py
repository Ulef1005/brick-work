"""Your own moves of categories between part groups (#315, part 3): the setting `part_group_overrides`, the Settings editor and every grouped surface."""
import uuid

from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin, collection, errors, part_groups, undo
from brickwork.core.checker import sorter
from brickwork.core.workbench import order_picker
from brickwork.web import admin_ops
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401 (fixtures)
from tests.api2 import v2, call, write, validate  # noqa: F401
from tests.test_part_groups_surfaces import PRINT, URL, categorise, names, order_scene, print_scene, sections_of, soup_of


def stored(coll):
    row = coll.db.execute("SELECT value FROM setting WHERE key='part_group_overrides'").fetchone()
    return row[0] if row else None


# ---------- the rule ----------

def test_group_of_applies_moves_in_grouped_only():
    moved = {'Plates Special': 'Tiles', 'Made up': 'Technic'}
    assert part_groups.group_of('Plates Special', 'grouped', moved) == 'Tiles'
    assert part_groups.group_of('Made up', 'grouped', moved) == 'Technic'
    assert part_groups.group_of('Plates', 'grouped', moved) == 'Plates'
    assert part_groups.group_of('Plates Special', 'bricklink', moved) == 'Plates Special'
    assert part_groups.group_of('Plates Special', 'none', moved) is None
    assert part_groups.group_of('Plates Special') == 'Plates'                       # no moves given: the table as before
    assert part_groups.group_of('Plates Special', overrides={}) == 'Plates'


def test_valid_overrides_drops_the_default_and_sorts():
    assert part_groups.valid_overrides(None) == {} and part_groups.valid_overrides({}) == {}
    assert part_groups.valid_overrides({'Tiles': 'Tiles', 'Made up': 'Other', 'Plates': 'Bricks', ' Bars ': 'Bricks'}) == {'Bars': 'Bricks', 'Plates': 'Bricks'}
    assert part_groups.encode_overrides({'Plates': 'Plates'}) is None
    assert part_groups.encode_overrides({'Plates': 'Bricks'}) == '{"Plates": "Bricks"}'


@pytest.mark.parametrize('bad', [{'Plates': 'Nowhere'}, {'Plates': 'plates'}, {'Plates': None}, {'Plates': 1}, {'': 'Bricks'}, {'  ': 'Bricks'},
                                 {'x' * 101: 'Bricks'}, {str(i): 'Bricks' for i in range(201)}, [], 'Bricks', 3, True])
def test_valid_overrides_refuses_what_does_not_fit(bad):
    with pytest.raises(ValueError):
        part_groups.valid_overrides(bad)


def test_the_longest_name_and_the_most_entries_are_accepted():
    assert len(part_groups.valid_overrides({str(i): 'Bricks' for i in range(200)})) == 200
    assert part_groups.valid_overrides({'x' * 100: 'Bricks'})


def test_reading_leaves_out_what_does_not_read(coll):
    assert part_groups.overrides(coll.db) == {}
    for text in ('not json', '[1]', '"x"'):
        coll.setting('part_group_overrides', text)
        assert part_groups.overrides(coll.db) == {}
    coll.setting('part_group_overrides', '{"Plates": "Bricks", "Tiles": "Nowhere", "Tools": 4}')
    assert part_groups.overrides(coll.db) == {'Plates': 'Bricks'}


# ---------- the setting: API, CLI, errors, Undo ----------

def test_api_round_trip_and_undo(v2, coll, world):
    assert call(v2, '/settings').json['data']['part_group_overrides'] == {}
    response = write(v2, '/settings', 'patch', {'part_group_overrides': {'Plates Special': 'Tiles', 'Tiles': 'Tiles'}})
    validate(response, 'patch_settings')
    assert response.json['data']['part_group_overrides'] == {'Plates Special': 'Tiles'}
    assert call(v2, '/settings').json['data']['part_group_overrides'] == {'Plates Special': 'Tiles'}
    assert stored(coll) == '{"Plates Special": "Tiles"}'
    assert write(v2, f"/events/{response.json['event_id']}/undo").status_code == 200
    assert stored(coll) is None and admin.settings(coll.db)['part_group_overrides'] == {}


def test_api_sends_a_clear_message_and_nothing_is_saved(v2, coll, world):
    response = write(v2, '/settings', 'patch', {'part_group_overrides': {'Plates': 'Nowhere'}})
    assert response.status_code == 422
    assert 'expected one of Bricks' in response.get_data(as_text=True)
    assert stored(coll) is None


def test_patch_refuses_bad_input_whole(coll):
    for bad in ({'Plates': 'Nowhere'}, {'': 'Bricks'}, {str(i): 'Bricks' for i in range(201)}, 'x'):
        with pytest.raises(errors.ValidationFailed):
            admin.patch_settings(coll.db, {'part_group_overrides': bad, 'part_list_grouping': 'none'})
    assert stored(coll) is None and admin.settings(coll.db)['part_list_grouping'] == 'grouped'


def test_an_empty_patch_clears_and_an_unchanged_one_writes_no_event(coll):
    admin.patch_settings(coll.db, {'part_group_overrides': {'Plates': 'Bricks'}})
    events = coll.db.execute("SELECT count(*) FROM event WHERE entity_kind='settings'").fetchone()[0]
    admin.patch_settings(coll.db, {'part_group_overrides': {'Plates': 'Bricks'}})
    assert coll.db.execute("SELECT count(*) FROM event WHERE entity_kind='settings'").fetchone()[0] == events
    admin.patch_settings(coll.db, {'part_group_overrides': {}})
    assert stored(coll) is None and admin.settings(coll.db)['part_group_overrides'] == {}


def test_cli_uses_the_shared_writer(coll, monkeypatch, pair):
    monkeypatch.setattr(admin_ops, 'brickwork_path', lambda: pair)
    assert admin_ops.settings_set('part_group_overrides', '{"Plates": "Bricks"}') == {'part_group_overrides': {'Plates': 'Bricks'}}
    event = coll.db.execute("SELECT * FROM event WHERE entity_kind='settings' AND field='save' ORDER BY id DESC").fetchone()
    assert event['via'] == 'cli'
    assert admin_ops.settings_show()['part_group_overrides'] == {'Plates': 'Bricks'}
    undo.undo_event(coll.db, event['id'])
    assert stored(coll) is None
    with pytest.raises(errors.ValidationFailed):
        admin_ops.settings_set('part_group_overrides', '{"Plates": "Nowhere"}')


# ---------- the Settings page ----------

def settings_form(client, **extra):
    page = BeautifulSoup(client.get('/manage/settings').data, 'html.parser')
    form = {}
    for field in page.select('form.stack input, form.stack select, input[form=bw-settings-form], select[form=bw-settings-form]'):
        name = field.get('name')
        if not name or field.get('type') in ('submit', 'button'):
            continue
        if field.name == 'select':
            chosen = field.select_one('option[selected]') or field.select_one('option')
            form[name] = chosen['value']
        elif field.get('type') in ('radio', 'checkbox'):
            if field.has_attr('checked'):
                form[name] = field['value']
        else:
            form[name] = field.get('value', '')
    form.update(extra)
    return page, form


def test_the_editor_lists_every_category_under_its_group(coll, client):
    coll.add_copy('1000-1')
    categorise(coll, **{'3001': 'Made up'})
    page, form = settings_form(client)
    editor = page.select_one('[data-grouping-editor]')
    assert editor.select_one('summary').text == 'Edit grouping' and not editor.has_attr('open')
    assert 'Changed: 0 categories.' in editor.select_one('[data-grouping-status]').text
    selects = {s['name'].removeprefix('group_of:'): s for s in editor.select('select')}
    assert set(selects) >= {c for cs in part_groups.GROUPS.values() for c in cs} | {'Made up'}
    assert selects['Plates Special'].select_one('[selected]')['value'] == 'Plates'
    assert [o['value'] for o in selects['Plates'].select('option')] == list(part_groups.GROUPS)
    assert selects['Made up'].select_one('[selected]')['value'] == 'Other' and selects['Made up']['data-default'] == 'Other'
    assert [g.select_one('summary').text.split(' · ')[0] for g in editor.select('details')] == ['Group: ' + n for n in part_groups.GROUPS]
    assert form['edit_grouping'] == '1' and form['part_list_grouping'] == 'grouped'


def test_the_counts_are_the_different_parts_held_per_category(coll):
    assert 'Made up' not in part_groups.held_counts(coll.db)
    coll.add_copy('1000-1')
    categorise(coll, **{'3001': 'Made up', '3023': 'Bricks'})
    counts = part_groups.held_counts(coll.db)
    assert counts['Made up'] == 1 and counts['Bricks'] == 1 and counts['Technic Pins'] == 0
    assert set(counts) >= {c for cs in part_groups.GROUPS.values() for c in cs}


def test_save_moves_with_a_receipt_and_undo_then_reset(coll, client):
    page, form = settings_form(client, **{'group_of:Plates Special': 'Tiles'})
    form['csrf_token'] = page.select_one('input[name=csrf_token]')['value']
    response = client.post('/manage/settings', data=form)
    assert response.status_code == 302
    assert stored(coll) == '{"Plates Special": "Tiles"}'
    saved = BeautifulSoup(client.get(response.location).data, 'html.parser')
    event = saved.select_one('input[name=event]')['value']
    editor = saved.select_one('[data-grouping-editor]')
    assert editor.has_attr('open') and 'Changed: 1 category.' in editor.select_one('[data-grouping-status]').text
    assert editor.select_one('select[name="group_of:Plates Special"] [selected]')['value'] == 'Tiles'
    assert client.post('/manage/settings', data={'action': 'undo', 'event': event, 'csrf_token': form['csrf_token']}).status_code == 302
    assert stored(coll) is None
    client.post('/manage/settings', data=form)
    assert stored(coll) == '{"Plates Special": "Tiles"}'
    reset = dict(form, reset_grouping='1')
    response = client.post('/manage/settings', data=reset)
    assert response.status_code == 302 and stored(coll) is None
    receipt = BeautifulSoup(client.get(response.location).data, 'html.parser').select_one('input[name=event]')
    assert receipt and client.post('/manage/settings', data={'action': 'undo', 'event': receipt['value'], 'csrf_token': form['csrf_token']}).status_code == 302
    assert stored(coll) == '{"Plates Special": "Tiles"}'


def test_a_save_without_the_editor_keeps_the_moves(coll, client):
    admin.patch_settings(coll.db, {'part_group_overrides': {'Plates': 'Bricks'}})
    page, form = settings_form(client)
    for key in [k for k in form if k.startswith('group_of:') or k == 'edit_grouping']:
        del form[key]
    form.update(csrf_token=page.select_one('input[name=csrf_token]')['value'], part_list_grouping='none')
    assert client.post('/manage/settings', data=form).status_code == 302
    assert stored(coll) == '{"Plates": "Bricks"}' and admin.settings(coll.db)['part_list_grouping'] == 'none'


def test_a_category_outside_the_table_can_be_moved_and_stays_listed(coll, client):
    admin.patch_settings(coll.db, {'part_group_overrides': {'Brand new category': 'Tiles'}})
    page, _ = settings_form(client)
    other = [g for g in page.select('[data-grouping-editor] details') if g.select_one('summary').text.startswith('Group: Other')][0]
    assert other.select_one('select[name="group_of:Brand new category"] [selected]')['value'] == 'Tiles'


# ---------- every grouped surface uses the move ----------

def test_set_page_uses_the_move(coll, read):
    copy = coll.add_copy('1000-1')
    parts = coll.db.execute('SELECT id,item_id FROM copy_part WHERE copy_id=? AND copy_figure_id IS NULL AND is_spare=0 ORDER BY id', (copy,)).fetchall()
    for part in parts:
        coll.db.execute('UPDATE main.item SET category_name=? WHERE id=?', ('Plates Special', part['item_id']))
    coll.db.commit()
    item = coll.item('sets', '1000-1')
    with read() as db:
        assert [g['name'] for g in collection.detail(db, item, copy_id=copy)['part_groups']] == ['Plates']
    admin.patch_settings(coll.db, {'part_group_overrides': {'Plates Special': 'Tiles'}})
    with read() as db:
        assert [g['name'] for g in collection.detail(db, item, copy_id=copy)['part_groups']] == ['Tiles']
    admin.patch_settings(coll.db, {'part_list_grouping': 'bricklink'})
    with read() as db:
        assert [g['name'] for g in collection.detail(db, item, copy_id=copy)['part_groups']] == ['Plates Special']


def test_checker_order_and_picker_use_the_move(coll):
    rows = [dict(token=str(i), category=c, name='x', quantity=1, color_name='Red', item_no=str(i)) for i, c in enumerate(['Plates Special', 'Tiles'])]
    position = {r['token']: i for i, r in enumerate(rows)}
    assert [r['token'] for r in sorted(rows, key=sorter('group', position))] == ['0', '1']
    admin.patch_settings(coll.db, {'part_group_overrides': {'Plates Special': 'Tiles', 'Tiles': 'Bricks'}})
    moved = part_groups.overrides(coll.db)
    assert [r['token'] for r in sorted(rows, key=sorter('group', position, moved))] == ['1', '0']
    picker = [dict(item_id=str(i), item_no=str(i), color_id=1, category=c, color_name='Red', rank_set='1000-1', rank_storage='', completes=0)
              for i, c in enumerate(['Plates Special', 'Tiles'])]
    assert [r['item_id'] for r in order_picker(picker, ['group'])] == ['0', '1']
    assert [r['item_id'] for r in order_picker(picker, ['group'], moved)] == ['1', '0']


def test_checker_session_in_group_order_uses_the_move(coll):
    from brickwork.core import checker

    def started(copy):
        checker.write(coll.db, copy, dict(action='start', operation=uuid.uuid4().hex, session=None, order='group'), None)
        state = checker.view(coll.db, copy)
        by_token = {r['token']: r for r in state['rows']}
        return [by_token[t]['category'] for t in state['session']['order'] if by_token[t]['kind'] == 'part']
    first = coll.add_copy('1000-1', condition='used', completeness='incomplete', completeness_source='derived')
    second = coll.add_copy('1000-1', condition='used', completeness='incomplete', completeness_source='derived')
    for copy in (first, second):
        coll.sql("UPDATE item SET category_name='Tiles' WHERE id IN (SELECT item_id FROM copy_part WHERE copy_id=? AND quantity=4)", (copy,))
        coll.sql("UPDATE item SET category_name='Bricks' WHERE id IN (SELECT item_id FROM copy_part WHERE copy_id=? AND quantity=2)", (copy,))
    assert started(first) == ['Bricks', 'Tiles']
    admin.patch_settings(coll.db, {'part_group_overrides': {'Bricks': 'Technic'}})
    assert started(second) == ['Tiles', 'Bricks']


def test_order_list_print_list_use_the_move(world, coll, client):
    order_scene(coll)
    categorise(coll, **{'3001': 'Bricks', '3023': 'Plates'})
    assert names(soup_of(client)) == ['Bricks', 'Plates']
    admin.patch_settings(coll.db, {'part_group_overrides': {'Plates': 'Technic'}})
    assert names(soup_of(client)) == ['Bricks', 'Technic']
    admin.patch_settings(coll.db, {'part_list_grouping': 'bricklink'})
    assert names(soup_of(client)) == ['Bricks', 'Plates']                                  # the moves apply to Grouped categories only


def test_print_list_uses_the_move(world, coll, client):
    copy = print_scene(coll, world)
    assert [s[0] for s in sections_of(soup_of(client, PRINT.format('missing'), copy=copy))] == ['Bricks', 'Plates']
    admin.patch_settings(coll.db, {'part_group_overrides': {'Bricks': 'Tiles'}})
    assert [s[0] for s in sections_of(soup_of(client, PRINT.format('missing'), copy=copy))] == ['Plates', 'Tiles']


# ---------- review fixes ----------

def test_null_clears_the_moves_like_an_empty_object(coll):
    admin.patch_settings(coll.db, {'part_group_overrides': {'Plates': 'Bricks'}})
    assert stored(coll) is not None
    admin.patch_settings(coll.db, {'part_group_overrides': None})
    assert stored(coll) is None


def test_a_stored_value_too_big_never_blocks_another_settings_save(coll):
    import json
    coll.setting('part_group_overrides', json.dumps({f'Category {i:03d}': 'Bricks' for i in range(250)} | {'x' * 120: 'Tiles'}))
    assert len(part_groups.overrides(coll.db)) == part_groups.MAX_OVERRIDES
    admin.patch_settings(coll.db, {'retail_country': 'US'})                              # no error: the stored moves are cut to what a save accepts
    assert admin.settings(coll.db)['retail_country'] == 'US'


def test_the_counts_leave_out_an_archived_copy_and_stock_taken_to_zero(coll):
    coll.add_copy('1000-1')
    categorise(coll, **{'3001': 'Made up'})
    assert part_groups.held_counts(coll.db)['Made up'] == 1
    coll.db.execute("UPDATE main.copy SET archived_at='2026-01-01T00:00:00Z'")
    assert part_groups.held_counts(coll.db).get('Made up', 0) == 0


def test_the_cli_parser_accepts_the_two_part_list_settings():
    from brickwork.web import cli
    for key in ('part_list_grouping', 'part_group_overrides'):
        assert cli.build_parser().parse_args(['settings', 'set', key, '{}']).key == key
