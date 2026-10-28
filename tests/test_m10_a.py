"""M.10 batch A (issue #112): the part list on the copy page (control, Switch sheet, pending, changed, retired lines, figure sources) and
in the Add review (picker, picture warning, unknown numbers). One test per screen state the approval frames show. Invented data."""
import pytest

from tests.app4 import app4, client, coll, csrf, pair, post, read  # noqa: F401 (fixtures)
from tests.m10a_data import build_world, make_a_pair
from tests.sources4 import keyed, unkeyed


@pytest.fixture
def pair(tmp_path):                                                    # noqa: F811  (the fixture pair with three versions of 1000-1)
    return make_a_pair(tmp_path)


@pytest.fixture
def w(coll, monkeypatch):
    keyed(monkeypatch, 'bricklink', 'rebrickable')
    return build_world(coll)


def page(client, w, copy):
    response = client.get(f'/collection/item/{w.keep}?copy={copy}')
    assert response.status_code == 200
    return response.get_data(as_text=True)


def test_a1_the_copy_page_names_its_list_and_offers_the_switch(client, w):
    html = page(client, w, w.copy_a)
    assert 'Rebrickable · version 2 of 3' in html and '3 lines' in html and '1 minifigure' in html
    assert 'data-bc-part-list="/collection/copy/' in html and '>Switch</button>' in html
    assert 'latest</span>' not in html.split('data-module="part-list"')[1].split('</section>')[0]            # version 2 of 3 is not the latest
    latest = page(client, w, w.copy_e)
    assert 'Rebrickable · version 3 of 3' in latest and 'latest</span>' in latest
    assert "BrickLink&#39;s list" in page(client, w, w.copy_b) or "BrickLink's list" in page(client, w, w.copy_b)


def test_a1_nothing_is_offered_without_a_choice(coll, client, monkeypatch):
    unkeyed(monkeypatch)
    copy = coll.add_copy('1000-2')
    html = client.get(f'/collection/item/{coll.item("sets", "1000-2")}?copy={copy}').get_data(as_text=True)
    assert 'Rebrickable · version 1 of 1' in html and 'data-bc-part-list' not in html


def sheet(client, w, copy, **query):
    response = client.get(f'/collection/copy/{copy}/part-list', query_string=query)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def test_a2_the_switch_sheet_says_what_changes_and_which_marks_do_not_carry_over(client, w):
    html = sheet(client, w, w.copy_a)
    for text in ('Switch part list', 'Rebrickable · version 1 of 3', 'in use', 'BrickLink', 'Lines added', 'Lines retired', 'Quantities capped',
                 'Marks that will not carry over', 'retires', '1 missing', 'checked', 'quantity 4 to 3', 'Use this for new copies of this set'):
        assert text in html, text
    assert 'value="rebrickable:3" checked' in html                                   # the latest list is the default
    assert 'value="rebrickable:2" disabled' in html                                  # the copy's own list cannot be chosen again
    assert 'value="rebrickable:1"' in sheet(client, w, w.copy_a, choose='rebrickable:1')


def test_a2_a_switch_keeps_one_receipt_with_undo_and_can_set_the_preference(client, w, coll):
    from brickwork.store4 import copies
    token = csrf(client)
    answer = post(client, token, 'part-list', copy_id=w.copy_c, choice='rebrickable:3', preference=True)
    body = answer.get_json()
    assert answer.status_code == 200 and body['event_id'] and body['message'].startswith('Part list switched · 1 added, 2 retired')
    assert copies.part_list_preference(coll.db, w.keep) == {'source': 'rebrickable', 'version': None}      # the latest: no pinned version
    html = page(client, w, w.copy_c)
    assert 'Rebrickable · version 3 of 3' in html and '<span class="mono">2</span> retired lines kept' in html and '<span class="mono">1</span> with marks' in html
    assert post(client, token, 'undo', event_id=body['event_id']).status_code == 200
    assert 'Rebrickable · version 2 of 3' in page(client, w, w.copy_c)
    refused = post(client, token, 'part-list', copy_id=w.copy_c, choice='rebrickable:2')
    assert refused.status_code == 400 and refused.get_json()['message']                                    # nothing to switch to the same list


def test_a3_a_pending_bricklink_list_waits_on_rebrickables_and_can_be_cancelled(client, w, coll):
    html = client.get(f'/collection/item/{w.gate}?copy={w.copy_d}').get_data(as_text=True)
    assert 'BrickLink list pending' in html and "Waiting for today&#39;s BrickLink budget" in html and 'tries again 2026-10-28 00:00 UTC' in html
    assert 'Rebrickable · version 1 of 1' in html and 'data-bc-part-act="part-list-cancel"' in html
    coll.sql("UPDATE job SET state='failed', error_code='source_error', retry_at='2026-10-27T13:00:00.000Z' WHERE state='waiting_for_budget'")
    assert 'Waiting for the network' in client.get(f'/collection/item/{w.gate}?copy={w.copy_d}').get_data(as_text=True)
    answer = post(client, csrf(client), 'part-list-cancel', copy_id=w.copy_d)
    assert answer.status_code == 200 and answer.get_json()['event_id'] is None
    assert 'BrickLink list pending' not in client.get(f'/collection/item/{w.gate}?copy={w.copy_d}').get_data(as_text=True)


def test_a4_a_changed_list_is_offered_per_copy_and_per_figure_line(client, w):
    html = page(client, w, w.copy_e).replace('&#39;', "'")
    assert 'Rebrickable changed version 3 of 3 since this copy was built · 1 line differs' in html                    # the copy
    assert "Rebrickable changed this figure's list, version 1 of 1 since this copy was built · 1 line differs" in html    # its figure line
    assert html.count('Switch to the current list') == 2 and 'Nothing switches until you do' in html
    assert 'changed' not in page(client, w, w.copy_f).split('data-module="part-list"')[1].split('</section>')[0]
    assert 'value="rebrickable:3"' in sheet(client, w, w.copy_e, choose='rebrickable:3')


def test_a5_retired_lines_are_a_collapsed_note_kept_out_of_the_counts(client, w):
    html = page(client, w, w.copy_f)
    assert '<span class="mono">2</span> retired lines kept' in html and '<span class="mono">1</span> with marks' in html
    note = html.split('data-module="retired"')[1]
    assert 'Plate 1' in note and 'checked' in note and '1 missing' in note and 'Left out of every count and check' in note
    assert 'retired line' not in page(client, w, w.copy_b)
    assert '3 parts missing' in html and '4 parts missing' not in html                                    # the retired 3023 white is no gap


def test_a6_a_figure_line_says_where_its_parts_came_from(client, w):
    html = page(client, w, w.copy_b)
    assert 'Parts from Rebrickable · version 1 of 1' in html
    assert 'Parts unknown for this figure: no Rebrickable list' in html


def review(client, token, rows, where='owned', kind='set'):
    answer = client.post('/manage/add/review', json=dict(csrf_token=token, type=kind, where=where, mode='search', items=rows))
    assert answer.status_code == 200, answer.get_data(as_text=True)
    return answer.get_json()


def test_a7_the_review_offers_a_part_list_picker_only_when_there_is_a_choice(client, w, coll):
    token = csrf(client)
    keep = review(client, token, [dict(item_id=w.keep, quantity=1)])['items'][0]['part_list']
    assert [o['label'] for o in keep['options']] == ['Version 1 of 3', 'Version 2 of 3', 'Version 3 of 3, latest', "BrickLink's list"]
    assert keep['preselected'] == 'rebrickable:3' and keep['why'] == 'the latest Rebrickable list'
    assert keep['options'][-1]['note'] is None                                                          # a BrickLink list is already fetched for 1000-1
    gate = review(client, token, [dict(item_id=w.gate, quantity=1)])['items'][0]['part_list']
    assert gate['options'][-1]['note'].startswith('Fetched after you add')                              # nothing fetched for 1000-2
    duplo = review(client, token, [dict(item_id=coll.item('sets', '2070-1'), quantity=1)])['items'][0]
    assert duplo['part_list']['options'][0]['label'] == 'Version 1 of 2' and duplo['part_list']['preselected'] == 'rebrickable:2'


def test_a7_the_preselection_follows_the_sets_own_choice_first(client, w, coll):
    from brickwork.store4 import copies
    copies.set_part_list_preference(coll.db, w.keep, {'source': 'rebrickable', 'version': 1}, via='cli')
    picker = review(client, csrf(client), [dict(item_id=w.keep, quantity=1)])['items'][0]['part_list']
    assert picker['preselected'] == 'rebrickable:1' and picker['why'] == 'your saved choice for this set'


def test_a7_the_chosen_list_makes_the_copy_and_may_become_the_sets_choice(client, w, coll):
    from brickwork.store4 import copies
    token = csrf(client)
    proposal = review(client, token, [dict(item_id=w.keep, quantity=1)])
    row = dict(proposal['items'][0], decision='another', part_list_choice='rebrickable:1', use_for_new=True)
    done = client.post('/manage/add/confirm', json=dict(csrf_token=token, token=proposal['token'], items=[row]))
    assert done.status_code == 200, done.get_data(as_text=True)
    version = coll.db.execute('SELECT inventory_version FROM copy ORDER BY created_at DESC LIMIT 1').fetchone()[0]
    assert version == 1 and copies.part_list_preference(coll.db, w.keep) == {'source': 'rebrickable', 'version': 1}
    again = review(client, token, [dict(item_id=w.keep, quantity=1)])
    bad = client.post('/manage/add/confirm', json=dict(csrf_token=token, token=again['token'], items=[dict(again['items'][0], decision='another', part_list_choice='rebrickable:9')]))
    assert bad.status_code == 400


def test_a7_a_part_with_no_known_picture_is_warned_about_before_confirming(client, w, coll, monkeypatch):
    monkeypatch.delenv('BW_REBRICKABLE_API_KEY')
    token = csrf(client)
    telephone, brick = coll.item('parts', 'dupupn0123a'), coll.item('parts', '3001')
    rows = review(client, token, [dict(item_id=telephone, color_id=coll.colour('4'), quantity=1), dict(item_id=brick, color_id=coll.colour('4'), quantity=1)],
                  kind='part')['items']
    assert [r['no_picture'] for r in rows] == [True, False]
    asked = client.get('/manage/add/picture-known', query_string=dict(item_id=telephone, color_id=coll.colour('4')))
    assert asked.get_json() == {'no_picture': True}
    assert client.get('/manage/add/picture-known').status_code == 400
    assert 'No picture known for this colour' in open('static/web/toni/bw-add.js').read()


def test_a8_an_unknown_number_offers_fetch_and_unidentified(client, w, monkeypatch):
    token = csrf(client)
    row = review(client, token, [dict(kind='set', number='9999-1', quantity=1)], kind='set')['items'][0]
    assert row['unknown'] and row['offers']['unidentified'] and row['offers']['fetch'] == {'available': True, 'why': None}
    monkeypatch.delenv('BW_REBRICKABLE_API_KEY')
    row = review(client, token, [dict(kind='set', number='9999-1', quantity=1)], kind='set')['items'][0]
    assert row['offers']['fetch']['available'] is False and 'add a Rebrickable key' in row['offers']['help']
    html = open('static/web/toni/bw-add.js').read()
    assert 'Add as unidentified' in html and "'Fetch from Rebrickable'" in html


def test_an_existing_copy_can_ask_for_a_list_that_is_not_fetched_yet(client, w, coll):
    from brickwork.store4 import pending
    copy = coll.add_copy('1000-2')
    html = sheet(client, w, copy).replace('&#39;', "'")
    assert "Fetches BrickLink's list; the copy switches when it arrives" in html and 'value="bricklink"' in html
    answer = post(client, csrf(client), 'part-list', copy_id=copy, choice='bricklink')
    assert answer.status_code == 200 and answer.get_json()['event_id'] is None
    assert answer.get_json()['message'] == "Fetching BrickLink's list · the copy switches when it arrives"
    assert pending.pending_offer(coll.db, copy)['state'] == 'waiting'
    page_html = client.get(f'/collection/item/{w.gate}?copy={copy}').get_data(as_text=True)
    assert 'BrickLink list pending' in page_html
    assert 'Not available while the copy waits' in sheet(client, w, copy)                  # it cannot ask twice


def test_with_a_fetched_list_the_sheet_switch_to_bricklink_is_at_once(client, w, coll):
    answer = post(client, csrf(client), 'part-list', copy_id=w.copy_c, choice='bricklink')
    assert answer.status_code == 200 and answer.get_json()['event_id']
    assert "BrickLink's list" in page(client, w, w.copy_c).replace('&#39;', "'")


def test_bricklink_is_disabled_in_the_sheet_without_a_key(client, w, monkeypatch):
    for name in ('CONSUMER_KEY', 'CONSUMER_SECRET', 'TOKEN_VALUE', 'TOKEN_SECRET'):
        monkeypatch.delenv('BW_BRICKLINK_' + name)
    html = sheet(client, w, w.copy_a)
    assert 'needs a BrickLink key' in html
    refused = post(client, csrf(client), 'part-list', copy_id=w.copy_a, choice='bricklink')
    assert refused.status_code == 400 and 'BrickLink key' in refused.get_json()['message']


def confirm_row(client, w, **edits):
    token = csrf(client)
    proposal = review(client, token, [dict(item_id=w.keep, quantity=1)])
    row = dict(proposal['items'][0], decision='another', **edits)
    return client.post('/manage/add/confirm', json=dict(csrf_token=token, token=proposal['token'], items=[row]))


def newest_copy_version(coll):
    return coll.db.execute('SELECT inventory_source, inventory_version FROM copy ORDER BY created_at DESC LIMIT 1').fetchone()[:]


def test_add_confirm_a_choice_equal_to_the_preselection_writes_no_preference(client, w, coll):
    from brickwork.store4 import copies
    done = confirm_row(client, w, part_list_choice='rebrickable:3', use_for_new=True)
    assert done.status_code == 200 and tuple(newest_copy_version(coll)) == ('rebrickable', 3)
    assert copies.part_list_preference(coll.db, w.keep) is None                         # nothing to remember: it is what the set gets anyway


def test_add_confirm_a_different_choice_makes_that_copy_and_may_be_remembered(client, w, coll):
    from brickwork.store4 import copies
    assert confirm_row(client, w, part_list_choice='rebrickable:1', use_for_new=False).status_code == 200
    assert tuple(newest_copy_version(coll)) == ('rebrickable', 1) and copies.part_list_preference(coll.db, w.keep) is None
    assert confirm_row(client, w, part_list_choice='rebrickable:2', use_for_new=True).status_code == 200
    assert copies.part_list_preference(coll.db, w.keep) == {'source': 'rebrickable', 'version': 2}
    assert confirm_row(client, w, part_list_choice='bricklink', use_for_new=True).status_code == 200
    assert tuple(newest_copy_version(coll)) == ('bricklink', None) and copies.part_list_preference(coll.db, w.keep) == {'source': 'bricklink', 'version': None}


def test_add_confirm_bricklink_without_a_key_is_refused(client, w, coll, monkeypatch):
    token = csrf(client)
    proposal = review(client, token, [dict(item_id=w.keep, quantity=1)])
    for name in ('CONSUMER_KEY', 'CONSUMER_SECRET', 'TOKEN_VALUE', 'TOKEN_SECRET'):
        monkeypatch.delenv('BW_BRICKLINK_' + name)
    before = coll.db.execute('SELECT count(*) FROM copy').fetchone()[0]
    row = dict(proposal['items'][0], decision='another', part_list_choice='bricklink')
    refused = client.post('/manage/add/confirm', json=dict(csrf_token=token, token=proposal['token'], items=[row]))
    assert refused.status_code == 400 and coll.db.execute('SELECT count(*) FROM copy').fetchone()[0] == before


def test_add_confirm_a_missing_choice_falls_back_to_the_preselection(client, w, coll):
    assert confirm_row(client, w).status_code == 200
    assert tuple(newest_copy_version(coll)) == ('rebrickable', 3)
    assert confirm_row(client, w, part_list_choice='').status_code == 200 and tuple(newest_copy_version(coll)) == ('rebrickable', 3)


# ---------- Codex review: reading a copy needs no credentials, a BrickLink copy can take a newer list, a preference rides the switch ----------

def drop_bricklink_key(monkeypatch):
    for name in ('CONSUMER_KEY', 'CONSUMER_SECRET', 'TOKEN_VALUE', 'TOKEN_SECRET'):
        monkeypatch.delenv('BW_BRICKLINK_' + name)


def test_review1_a_copy_page_never_needs_a_key_to_say_a_list_changed(client, w, coll, monkeypatch):
    coll.sql("UPDATE copy_figure SET inventory_digest='figure-digest-before' WHERE copy_id=?", (w.copy_b,))       # a BrickLink copy whose figure list changed
    with_key = page(client, w, w.copy_b)
    assert 'Rebrickable changed' in with_key and 'Switch to the current list' in with_key
    drop_bricklink_key(monkeypatch)
    response = client.get(f'/collection/item/{w.keep}?copy={w.copy_b}')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'changed' in html and 'needs a BrickLink key' in html and 'Switch to the current list' not in html


def test_review2_a_copy_on_bricklink_can_take_a_newer_fetched_list(client, w, coll):
    from tests.m10a_data import fetch_bricklink
    old = coll.db.execute('SELECT fetched_inventory_id FROM copy WHERE id=?', (w.copy_b,)).fetchone()[0]
    newer = fetch_bricklink(coll, w.keep, [(w.brick, w.red, 0, 9)], [(w.figure, 1)])
    html = page(client, w, w.copy_b)
    assert 'A newer BrickLink list was fetched' in html and 'Switch to the current list' in html
    answer = post(client, csrf(client), 'part-list', copy_id=w.copy_b, choice='bricklink')
    assert answer.status_code == 200 and answer.get_json()['event_id'], answer.get_json()
    assert coll.db.execute('SELECT fetched_inventory_id FROM copy WHERE id=?', (w.copy_b,)).fetchone()[0] == newer != old
    again = post(client, csrf(client), 'part-list', copy_id=w.copy_b, choice='bricklink')
    assert again.status_code == 400                                                                   # nothing newer now


def api_list_copy(coll, w):
    from tests.m10a_data import fetch_bricklink
    from brickwork.store4 import fetched, identity
    with coll.db:
        identity.project(coll.db, w.gate)
        identity.project(coll.db, w.brick)
        identity.project_color(coll.db, w.red)
        fetched.write_fetched(coll.db, w.gate, 'rebrickable_api', [(w.brick, w.red, 0, 3)], [])
    return coll.add_copy('1000-2')


def test_review3_a_list_that_cannot_be_remembered_is_refused_before_anything_changes(client, w, coll):
    from brickwork.store4 import copies
    copy = api_list_copy(coll, w)
    before = coll.db.execute('SELECT inventory_source, inventory_digest FROM copy WHERE id=?', (copy,)).fetchone()[:]
    html = sheet(client, w, copy)
    assert 'value="rebrickable_api"' in html and 'data-remember="0"' in html and 'data-remember="1"' in html     # the box is not offered for it
    refused = post(client, csrf(client), 'part-list', copy_id=copy, choice='rebrickable_api', preference=True)
    assert refused.status_code == 400 and 'cannot be remembered' in refused.get_json()['message']
    assert coll.db.execute('SELECT inventory_source, inventory_digest FROM copy WHERE id=?', (copy,)).fetchone()[:] == before
    assert copies.part_list_preference(coll.db, w.gate) is None


def test_review3_the_preference_is_part_of_the_switch_and_its_undo(client, w, coll):
    from brickwork.store4 import copies
    token = csrf(client)
    done = post(client, token, 'part-list', copy_id=w.copy_c, choice='rebrickable:1', preference=True).get_json()
    assert copies.part_list_preference(coll.db, w.keep) == {'source': 'rebrickable', 'version': 1}
    undone = post(client, token, 'undo', event_id=done['event_id'])
    assert undone.status_code == 200 and copies.part_list_preference(coll.db, w.keep) is None            # one receipt takes both back


def test_review4_the_sheet_reaffirming_the_sets_choice_is_recorded(client, w, coll):
    from brickwork.store4 import copies
    token = csrf(client)
    count = lambda: coll.db.execute("SELECT count(*) FROM event WHERE entity_kind='set_preference'").fetchone()[0]   # noqa: E731
    assert post(client, token, 'part-list', copy_id=w.copy_c, choice='rebrickable:1', preference=True).status_code == 200
    before = count()
    assert post(client, token, 'part-list', copy_id=w.copy_a, choice='rebrickable:1', preference=True).status_code == 200      # the same choice, said again
    assert count() == before + 1 and copies.part_list_preference(coll.db, w.keep) == {'source': 'rebrickable', 'version': 1}
