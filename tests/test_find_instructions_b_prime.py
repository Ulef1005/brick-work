"""Find instructions of the B′ frames (frame 03, #484): the sets without a booklet, the link-out pair, the number lookup and the Add switch."""
import contextlib

from bs4 import BeautifulSoup

from brickwork.core import instructions
from scripts import screen_gate
from tests.app4 import app4, client, coll, pair, world  # noqa: F401


def page(client, path='/manage/instructions/find'):
    return BeautifulSoup(client.get(path).data, 'html.parser')


def test_the_frames_world_lists_the_four_sets_the_frame_draws(tmp_path):
    store = tmp_path / 'brickwork.db'
    screen_gate.build_store('frames-instructions', store)
    from brickwork.core.admin import database
    with database(store, read_only=True) as db:
        rows = instructions.sets_without_booklet(db, 'DE')
    assert [r['number'] for r in rows] == ['7213-1', '7938-1', '8043-1', '10210-1']
    first = rows[0]
    assert [l['source'] for l in first['links']] == ['lego', 'rebrickable']
    assert first['links'][0]['url'].startswith('https://www.lego.com/de-de/service/building-instructions/7213')
    assert first['links'][1]['url'] == 'https://rebrickable.com/sets/7213-1/'


def test_the_page_names_its_place_and_links_out(client, world):
    soup = page(client)
    assert soup.select_one('.bw-find-kicker').text == 'Tools & Admin'
    assert soup.select_one('.bw-find h1').text == 'Find instructions'
    assert soup.select_one('form.bw-find-form input[name=set]') is not None and soup.select_one('select[name=region]') is not None
    for link in soup.select('.bw-find-ext'):
        assert link['target'] == '_blank' and 'noopener' in link['rel']
    assert 'downloads nothing itself' in soup.select_one('.bw-find-note').text


def test_a_set_number_shows_its_links_without_scripts(client, world):
    soup = page(client, '/manage/instructions/find?set=6081-1&region=US')
    row = soup.select_one('.bw-find-lookup')
    assert row.select_one('.bw-find-no').text == '6081-1'
    assert [a.text.strip() for a in row.select('.bw-find-ext')] == ['Official instructions', 'Rebrickable']
    assert 'en-us' in row.select('.bw-find-ext')[0]['href']
    assert soup.select_one('select[name=region] option[selected]')['value'] == 'US'


def test_a_bad_set_number_is_said_not_raised(client, world):
    soup = page(client, '/manage/instructions/find?set=not%20a%20number')
    assert soup.select_one('[role=alert]').text.startswith('Choose a set number')
    assert not soup.select('.bw-find-lookup')


def test_a_promotional_number_gets_the_rebrickable_link_only(client, world):
    soup = page(client, '/manage/instructions/find?set=COMCON034-1')
    assert [a.text.strip() for a in soup.select('.bw-find-lookup .bw-find-ext')] == ['Rebrickable']


def test_upload_link_prefills_the_instruction_files_form(client, world):
    soup = page(client, '/manage/instructions/find?set=6081-1')
    href = soup.select_one('.bw-find-lookup .bw-find-upload')['href']
    assert href.endswith('#upload') and 'item_no=6081-1' in href
    form = page(client, href.split('#')[0])
    assert form.select_one('#upload').has_attr('open') and form.select_one('input[name=item_no]')['value'] == '6081-1'


def test_add_hides_the_fetch_switch_and_settings_drops_the_download_limit(client, world):
    switch = page(client, '/manage/add').select_one('.bw-add-instruction-switch')
    assert switch.has_attr('hidden')
    settings = page(client, '/manage/settings')
    assert 'Largest instruction download' not in settings.get_text() and 'official_download_limit_mb' not in str(settings)
    assert [h.text for h in settings.select('h2.bw-label')].count('Labels') == 1


def test_a_set_page_links_here_with_its_item_and_the_page_looks_that_set_up(client, world):   # review round 1: ?item=<id> of the Instructions & Box tab
    soup = page(client, f'/manage/instructions/find?item={world.keep}')
    row = soup.select_one('.bw-find-lookup')
    assert row is not None and [a.text.strip() for a in row.select('.bw-find-ext')][-1] == 'Rebrickable'
    assert page(client, '/manage/instructions/find?item=999999999').select_one('[role=alert]') is not None


def test_a_number_without_a_suffix_is_filled_into_the_upload_form_with_its_suffix(client, world):   # review round 1
    soup = page(client, '/manage/instructions/find?set=6081')
    assert soup.select_one('.bw-find-lookup .bw-find-no').text == '6081-1'
    assert 'item_no=6081-1' in soup.select_one('.bw-find-lookup .bw-find-upload')['href']
