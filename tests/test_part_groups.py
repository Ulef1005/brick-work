"""Part grouping is an offline presentation of the existing item categories (#315)."""
import json
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin, collection, errors, part_groups, undo
from brickwork.web import admin_ops
from tests.app4 import app4, client, coll, make_pair, read, world, RICH  # noqa: F401
from tests.api2 import v2, call, write, validate  # noqa: F401


def test_mapping_is_exclusive_and_covers_inventory_categories():
    categories = set()
    for path in Path('design/sources/test-data/inventories').glob('*.json'):
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            categories.update(p['category'] for p in data['parts'])
    assert len(categories) == 54
    mapped = [c for members in part_groups.GROUPS.values() for c in members]
    assert len(mapped) == len(set(mapped))
    assert categories <= set(mapped)
    for category in categories:
        assert sum(category in members for members in part_groups.GROUPS.values()) == 1
        assert part_groups.group_of(category) in part_groups.GROUPS
    for category in ('Made up', '', None):
        assert part_groups.group_of(category) == 'Other'
    assert part_groups.group_of('Made up', 'bricklink') == 'Made up'
    assert part_groups.group_of(None, 'bricklink') == 'Other'
    assert part_groups.group_of('Bricks', 'none') is None


def test_order_and_optional_other():
    assert part_groups.order(['Other', 'Technic', 'Bricks', 'Tiles']) == ['Bricks', 'Tiles', 'Technic', 'Other']
    assert part_groups.order(['Technic', 'Bricks']) == ['Bricks', 'Technic']
    assert part_groups.order(['Other', 'Tiles', 'Bricks'], 'bricklink') == ['Bricks', 'Tiles', 'Other']
    assert part_groups.order(['Bricks'], 'none') == []


@pytest.mark.parametrize('mode', part_groups.MODES)
def test_setting_api_round_trip_and_undo(v2, coll, world, mode):
    assert call(v2, '/settings').json['data']['part_list_grouping'] == 'grouped'
    response = write(v2, '/settings', 'patch', {'part_list_grouping': mode})
    validate(response, 'patch_settings')
    assert response.json['data']['part_list_grouping'] == mode
    assert admin.settings(coll.db)['part_list_grouping'] == mode
    if mode != 'grouped':
        assert write(v2, f"/events/{response.json['event_id']}/undo").status_code == 200
        assert admin.settings(coll.db)['part_list_grouping'] == 'grouped'
        assert coll.db.execute("SELECT value FROM setting WHERE key='part_list_grouping'").fetchone() is None


@pytest.mark.parametrize('bad', ['bogus', '', None, 1, True, []])
def test_setting_rejects_invalid_values(coll, bad):
    with pytest.raises(errors.ValidationFailed):
        admin.patch_settings(coll.db, {'part_list_grouping': bad})
    assert admin.settings(coll.db)['part_list_grouping'] == 'grouped'


def test_cli_uses_shared_writer(coll, monkeypatch, pair):
    monkeypatch.setattr(admin_ops, 'brickwork_path', lambda: pair)
    assert admin_ops.settings_set('part_list_grouping', 'bricklink') == {'part_list_grouping': 'bricklink'}
    assert admin.settings(coll.db)['part_list_grouping'] == 'bricklink'
    event = coll.db.execute("SELECT * FROM event WHERE entity_kind='settings' AND field='save' ORDER BY id DESC").fetchone()
    assert event['via'] == 'cli'
    undo.undo_event(coll.db, event['id'])
    assert admin.settings(coll.db)['part_list_grouping'] == 'grouped'


@pytest.fixture
def grouped_copy(coll):
    cid = coll.add_copy('1000-1')
    # Use the copy's projected item.category_name, the same source as the list.
    parts = coll.db.execute('SELECT id,item_id FROM copy_part WHERE copy_id=? AND copy_figure_id IS NULL AND is_spare=0 ORDER BY id', (cid,)).fetchall()
    assert len(parts) >= 2
    for index, part in enumerate(parts):
        coll.db.execute('UPDATE main.item SET category_name=? WHERE id=?', ('Bricks' if index == 0 else 'Technic Pins', part['item_id']))
        coll.db.execute('UPDATE copy_part SET checked=?,missing=?,damaged=0 WHERE id=?', (1 if index == 0 else 0, 0 if index == 0 else 2, part['id']))
    coll.db.commit()
    return cid


@pytest.mark.parametrize('mode', part_groups.MODES)
def test_set_sections_render_counts_and_no_script_fallback(coll, client, read, grouped_copy, mode):
    admin.patch_settings(coll.db, {'part_list_grouping': mode})
    item = coll.item('sets', '1000-1')
    with read() as db:
        detail = collection.detail(db, item, copy_id=grouped_copy)
    response = client.get(f'/collection/item/{item}?copy={grouped_copy}')
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, 'html.parser')
    module = soup.select_one('[data-module=consists]')
    sections = module.select('[data-bc-part-section]')
    if mode == 'none':
        assert not sections
        assert module['data-bc-page-size'] == '15'
        return
    assert [s['data-bc-part-section'] for s in sections] == ['Bricks', 'Technic' if mode == 'grouped' else 'Technic Pins']
    assert [s['data-bc-default-open'] for s in sections] == ['false', 'true']
    assert all(s.select_one('button')['aria-expanded'] == 'true' for s in sections)
    assert all(not s.select_one('[data-bc-section-body]').has_attr('hidden') for s in sections)
    assert len(module.select('[data-bc-row]')) == len(detail['consists'])
    assert sections[0].select_one('.bc-status.complete').get_text() == 'Complete'
    pending = detail['part_groups'][1]
    assert sections[1].select_one('.bc-status.incomplete').get_text() == f"Missing {pending['missing']} · {pending['todo']} to check"
    assert f"{pending['checked']} of {len(pending['rows'])} checked" in sections[1].get_text()
    assert f"{len(pending['rows'])} rows · {pending['pieces']} pieces" in sections[1].get_text()
    assert module.select_one('[data-bc-sections=expand]') and module.select_one('[data-bc-sections=collapse]')


def test_settings_page_save_and_undo(coll, client):
    current = admin.settings(coll.db)
    form = {'retail_country': current['retail_country'], 'part_list_grouping': 'none'}
    form.update({'priority:' + step + ':' + kind: ','.join(sources) for step, kinds in current['priority'].items() for kind, sources in kinds.items()})
    page = BeautifulSoup(client.get('/manage/settings').data, 'html.parser')
    assert len(page.select('[name=part_list_grouping]')) == 3
    form['csrf_token'] = page.select_one('input[name=csrf_token]')['value']
    response = client.post('/manage/settings', data=form)
    assert response.status_code == 302
    saved = BeautifulSoup(client.get(response.location).data, 'html.parser')
    event = saved.select_one('input[name=event]')['value']
    assert admin.settings(coll.db)['part_list_grouping'] == 'none'
    assert client.post('/manage/settings', data={'action': 'undo', 'event': event, 'csrf_token': form['csrf_token']}).status_code == 302
    assert admin.settings(coll.db)['part_list_grouping'] == 'grouped'


def test_query_count_stays_fixed_with_hundreds_of_parts(coll, read, grouped_copy):
    item = coll.item('sets', '1000-1')
    def measured():
        with read() as db:
            queries = []
            db.set_trace_callback(queries.append)
            result = collection.detail(db, item, copy_id=grouped_copy)
            db.set_trace_callback(None)
            return len(queries), result
    before, _ = measured()
    for n in range(300):
        part = coll.local('part', f'Synthetic grouped part {n}')
        coll.db.execute("UPDATE item SET category_name='Tiles' WHERE id=?", (part,))
        coll.db.execute('INSERT INTO copy_part(copy_id,item_id,color_id,quantity,checked) VALUES(?,?,?,?,0)', (grouped_copy, part, coll.colour('4'), 1))
    coll.db.commit()
    after, result = measured()
    assert len(result['consists']) > 300
    assert after == before
    assert len(next(g for g in result['part_groups'] if g['name'] == 'Tiles')['rows']) == 300


@pytest.mark.parametrize('checked,missing,expected,status', [(1, 2, 'Missing 2', 'incomplete'), (0, 0, '1 to check', 'unknown')])
def test_section_status_variants(coll, client, grouped_copy, checked, missing, expected, status):
    coll.db.execute("UPDATE copy_part SET checked=?,missing=?,damaged=0 WHERE copy_id=? AND item_id IN (SELECT id FROM item WHERE category_name='Bricks')", (checked, missing, grouped_copy))
    coll.db.commit()
    page = BeautifulSoup(client.get(f"/collection/item/{coll.item('sets', '1000-1')}?copy={grouped_copy}").data, 'html.parser')
    section = page.select_one('[data-bc-part-section=Bricks]')
    assert section.select_one('.bc-status.' + status).get_text() == expected
    assert section['data-bc-default-open'] == 'true'


def test_section_runtime():
    import subprocess
    from tests import rendered
    result = subprocess.run([rendered.need_node(), 'tests/toni_bw_part_groups_runtime.cjs'], check=True, capture_output=True, text=True, timeout=30)
    assert 'part groups runtime ok' in result.stdout


@pytest.fixture
def pair(tmp_path, request):
    path = make_pair(tmp_path, rich=True, **getattr(request, 'param', {}))
    if getattr(request, 'param', None):
        import sqlite3
        with sqlite3.connect(path.with_name('catalogue.db')) as db:
            db.execute("UPDATE item SET category_id=NULL WHERE born_key='syn-uncategorised'")
    return path


@pytest.mark.parametrize('pair', [dict(extra_dump={
    'parts': [['syn-uncategorised', 'Synthetic uncategorised part', 11, 'Plastic']],
    'inventory_parts': RICH['inventory_parts'] + [[9001, 'syn-uncategorised', 4, 3, 'False', '']],
})], indirect=True)
def test_catalogue_reference_groups_use_categories_and_other(coll, client, read):
    item = coll.item('sets', '1000-1')
    with read() as db:
        detail = collection.detail(db, item)
    assert not detail['selected']
    groups = {g['name']: g for g in detail['part_groups']}
    assert set(groups) == {'Bricks', 'Plates', 'Other'}
    assert [(p['name'], p['quantity']) for p in groups['Other']['rows'] if p['item_type'] != 'M'] == [('Synthetic uncategorised part', 3)]
    soup = BeautifulSoup(client.get(f'/collection/item/{item}').data, 'html.parser')
    assert [s['data-bc-part-section'] for s in soup.select('[data-bc-part-section]')] == ['Bricks', 'Plates', 'Other']


def test_catalogue_reference_figures_are_separate_from_part_groups(coll, client, read):
    item = coll.item('sets', '1000-1')
    with read() as db:
        detail = collection.detail(db, item)
    assert any(r['item_type'] == 'M' for r in detail['consists'])
    assert all(r['item_type'] != 'M' for g in detail['part_groups'] for r in g['rows'])
    assert sum(len(g['rows']) for g in detail['part_groups']) == 2
    assert sum(g['pieces'] for g in detail['part_groups']) == 6
    soup = BeautifulSoup(client.get(f'/collection/item/{item}').data, 'html.parser')
    rows = soup.select('[data-module=consists] [data-bc-row]')
    figures = [r for r in rows if json.loads(r['data-record'])['type'] == 'M']
    assert len(figures) == 1
    assert not figures[0].find_parent(attrs={'data-bc-part-section': True})
    assert soup.select_one('[data-bc-tab=figures]')


@pytest.mark.parametrize('owned', [False, True])
def test_group_status_only_for_owned_copy(coll, client, owned):
    item = coll.item('sets', '1000-1')
    suffix = f'?copy={coll.add_copy("1000-1")}' if owned else ''
    soup = BeautifulSoup(client.get(f'/collection/item/{item}{suffix}').data, 'html.parser')
    sections = soup.select('[data-bc-part-section]')
    assert sections
    for section in sections:
        header = section.select_one('[data-bc-section-toggle]')
        assert ' rows · ' in header.get_text() and ' pieces' in header.get_text()
        assert bool(header.select_one('.bc-status')) == owned
        assert (' checked' in header.get_text()) == owned
        assert (' to check' in header.get_text()) == owned
