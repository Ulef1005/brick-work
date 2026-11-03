"""4.8a on the 4.0 store (M.8d, issue #110): a set's part list leaves out spares and figure parts, the spare question, the figure check.

The checker's own behaviour is in test_bw_checker.py; this file keeps the 4.8a contracts across screens: the item page, the list, the chooser
and the check agree on which lines are the set's; the finished check opens on its start card. The Matching-uses-set-gaps test moved to the
workbench (M.8e); the 3.3 recompute command is gone (derived completeness is `store4.copies.derived_completeness`, shared with the checker)."""
import json

from bs4 import BeautifulSoup
import pytest

from brickwork.core import checker, collection
from brickwork.core.completeness import derived_state
from brickwork.store4 import copies
from tests.app4 import app4, client, coll, csrf, pair, read  # noqa: F401 (fixtures)
from tests.test_bw_checker import answer_all, mutate, page, start


@pytest.fixture
def scene(coll):
    """A derived copy of 1000-1 with one required part missing, one spare line and one figure line with four own parts."""
    copy = coll.add_copy('1000-1', condition='used', completeness='incomplete', completeness_source='derived')
    coll.mark(copy, '3001', '4', missing=1)
    return copy


def test_a_set_list_counts_exclude_spares_and_figure_parts(coll, scene, client):
    db = coll.db
    item = coll.item('sets', '1000-1')
    detail = collection.detail(db, item, copy_id=scene)
    lines = {(r['item_id'], r.get('color_id')) for r in detail['consists'] if not r.get('minifig_no')}
    assert len(lines) == 2 and len([r for r in detail['consists'] if r.get('minifig_no')]) == 1
    assert (detail['progress']['total'], detail['progress']['missing'], detail['progress']['lines'], detail['progress']['spare_lines']) == (6, 1, 2, 1)
    # checker, chooser and the list count the same lines
    assert [r['kind'] for r in checker.rows(db, scene, decorate=False)].count('part') == 2
    choice = next(c for c in checker.choices(db) if c['copy']['id'] == scene)
    assert (choice['parts'], choice['total'] if choice['session'] else None) == (2, None)
    listing = {r['item_id']: r for r in collection.listing(db, 'S')}
    assert listing[item]['missing_parts'] == 1
    assert db.execute('SELECT count(*) FROM copy_part WHERE copy_id=?', (scene,)).fetchone()[0] == 3 + 4      # nothing deleted: spare and figure parts stay rows
    assert derived_state(db, scene) == 'incomplete'
    text = BeautifulSoup(client.get(f'/collection/item/{item}?copy={scene}').text, 'html.parser').select_one('[data-module=consists]').get_text()
    assert '1 spare line · not listed or counted' in text


def test_a_figure_parts_gap_is_not_a_set_gap(coll, scene):
    db = coll.db
    figure = db.execute('SELECT id FROM copy_figure WHERE copy_id=?', (scene,)).fetchone()[0]
    coll.sql('UPDATE copy_part SET missing=1 WHERE copy_figure_id=?', (figure,))
    assert derived_state(db, scene) == 'incomplete'                                  # still the one missing set line
    coll.sql('UPDATE copy_part SET missing=0 WHERE copy_id=? AND copy_figure_id IS NULL', (scene,))
    coll.tag('copy', scene, coll.flag('Set is checked', 'status'))
    assert derived_state(db, scene) == 'complete'                                    # figure parts never count on the set
    coll.mark_figure(scene, 'fig-000004', missing=1)
    assert derived_state(db, scene) == 'incomplete'                                  # a missing whole figure does
    coll.sql('UPDATE copy SET completeness_source=? WHERE id=?', ('manual', scene))
    assert derived_state(db, scene) is None                                          # and a manual completeness is nobody's to derive


def test_the_spare_question_comes_last_and_the_default_skips_the_spares(coll, scene):
    db = coll.db
    state = start(db, scene)
    answer_all(db, scene, state)
    assert checker.session(db, scene)['spares'] is None and state['session']['cursor'] == 0
    saved = mutate(db, scene, 'spares', include=False)
    assert saved['session']['spares'] == 'no' and len(saved['session']['order']) == 3
    done = mutate(db, scene, 'finish', checked=True)
    assert done['session']['finished'] and all(r['kind'] != 'spare' for r in done['rows'])


def test_the_switch_of_a_part_list_does_not_lose_the_spare_lines(coll):
    db = coll.db
    copy = coll.add_copy('2070-1', version=1)
    before = db.execute('SELECT count(*) FROM copy_part WHERE copy_id=?', (copy,)).fetchone()[0]
    copies.switch_part_list(db, copy, {'source': 'rebrickable', 'version': 2}, via='cli')
    db.commit()
    assert db.execute('SELECT count(*) FROM copy_part WHERE copy_id=?', (copy,)).fetchone()[0] >= before        # retired lines stay rows


@pytest.mark.parametrize('figure_mode', [False, True])
def test_finished_reload_shows_only_start_card(coll, scene, client, figure_mode):
    token = csrf(client)
    figure = coll.db.execute('SELECT id FROM copy_figure WHERE copy_id=?', (scene,)).fetchone()[0]
    url = f'/workbench/check-parts/{scene}' + (f'/figure/{figure}' if figure_mode else '')
    state = client.post(url, json=dict(csrf_token=token, action='start', operation='reload-start')).json['state']
    # Finishing without the checked flag is allowed with unanswered entries.
    response = client.post(url, json=dict(csrf_token=token, action='finish', operation='reload-finish', session=state['session']['id'], checked=False))
    assert response.status_code == 200
    soup = page(client, url + '?run=1')
    assert soup.select_one('#bw-checker')['data-check-stage'] == 'start'
    assert soup.select_one('[data-start] h2').text == 'Check again'
    assert soup.select_one('[data-check-body]').has_attr('hidden')
    assert json.loads(soup.select_one('script[data-check-state]').text)['session']['finished'] is True


def test_the_figure_link_on_the_set_page_names_the_line(coll, scene, client):
    figure = coll.db.execute('SELECT id FROM copy_figure WHERE copy_id=?', (scene,)).fetchone()[0]
    html = client.get(f'/collection/item/{coll.item("sets", "1000-1")}?copy={scene}&inventory=figures').text
    assert f'/workbench/check-parts/{scene}/figure/{figure}' in html
    figure_item = coll.item('minifigs', 'fig-000004')
    assert f'/workbench/check-parts/{scene}/figure/{figure}' in client.get(f'/collection/item/{figure_item}').text
