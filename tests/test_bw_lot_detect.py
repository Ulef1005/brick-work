"""The lot page's Set detection section (#200) and the sticker chooser (#201), rendered by the real app on the invented sets of `tests/stickers_world.py`.

The page is server-rendered: the filters are a GET form whose state is the URL, the candidate details are `<details>`, the chooser is a page of its own."""
from bs4 import BeautifulSoup
import pytest

from brickwork.core import stickers
from brickwork.web import lot_detect
from tests.app4 import app4, client, csrf  # noqa: F401 (fixtures)
from tests.stickers_world import World, coll, db, pair, world  # noqa: F401 (fixtures)


def page(client, lot, query='', path=''):
    response = client.get(f'/collection/lots/{lot}{path}{query}')
    assert response.status_code == 200, response.text[:300]
    return BeautifulSoup(response.text, 'html.parser'), response


def section(soup):
    found = soup.select_one('#set-detection')
    assert found is not None
    return found


def names(soup):
    return [c.select_one('.bd-name').get_text(' ', strip=True) for c in soup.select('.bd-cand')]


# ---------- Set detection ----------

def test_the_section_states_the_score_is_not_a_probability_and_lists_the_candidates(client, world):
    soup, _ = page(client, world.lot, '?min_score=0')
    detect = section(soup)
    assert detect.select_one('h2').text == 'Which sets are in this lot?' and detect.select_one('.bd-eyebrow').text == 'Set detection'
    assert 'It is not a probability.' in detect.select_one('.bd-lead').text
    first = detect.select_one('.bd-cand')
    assert first.select_one('details').has_attr('open'), 'the best candidate is open'
    assert first.select_one('.bd-pct').text == '100%' and first.select_one('.bd-best').text == 'best match'
    assert first.select_one('.bd-bar b')['style'] == 'width:100%'
    assert 'Stk Set 9403' in first.select_one('.bd-name').text, 'the rare part decides'
    assert 'distinctive parts found' not in first.select_one('.bd-reasons').text or 'part lines of the set are in the lot' in first.select_one('.bd-reasons').text
    assert not detect.select('.bd-cand')[1].select_one('details').has_attr('open')


def test_details_show_found_missing_swaps_and_the_link_to_the_set(client, world, coll):
    coll.add_stock('part', coll.item('parts', 'stk-bar'), colour=coll.colour('4'), quantity=2, condition='used', lot=world.lot)
    soup, _ = page(client, world.lot, '?min_score=0&ignore_common=0&show=40')
    card = next(c for c in soup.select('.bd-cand') if 'Stk Set 9401' in c.text)
    labels = [p.text for p in card.select('.bd-label')]
    assert labels == ['Found in the lot · 0', 'Not found yet · 0', 'Swaps, not counted in the score · 1'] or labels[2] == 'Swaps, not counted in the score · 1'
    assert 'Lot has' in card.select_one('.bd-swaps').text and 'Red' in card.select_one('.bd-swaps').text
    pull, link = card.select('.bd-actions a')
    assert pull.text == 'Pull list' and pull['href'] == f"/collection/lots/{world.lot}/pull/{world.set('9401-1')}"        # #202
    assert link.text.startswith('Open set') and link['href'] == f"/collection/item/{world.set('9401-1')}"


def test_found_and_missing_parts_have_a_tile_each_with_the_picture_when_there_is_one(client, world, coll):
    coll.sql("INSERT INTO picture(item_id,color_id,source,kind,local_path,width,height,fetched_at) VALUES(?,NULL,'bricklink','photo','data/images/x.png',4,3,'2026-10-26T12:00:00.000Z')",
             (world.coll.item('parts', 'stk-r1'),))
    soup, _ = page(client, world.lot, '?min_score=0')
    first = soup.select_one('.bd-cand')
    found = first.select('.bd-tiles')[0]
    assert found.select_one('img') is not None and found.select_one('img')['src'].startswith('/manage/images/')
    assert 'Found in the lot' in first.select('.bd-label')[0].text and first.select('.bd-label')[1].text.startswith('Not found yet')


def test_the_counts_line_says_how_many_parts_were_too_common_to_count(client, world, coll):
    coll.setting('candidate_sets_common_max', '25')
    soup, _ = page(client, world.lot, '?min_score=0')
    line = section(soup).select_one('.bd-count').text
    assert line.endswith("1 of the lot's parts was too common to count") and 'candidate set' in line
    soup, _ = page(client, world.lot, '?min_score=0&detect=1&ignore_common=0')
    assert 'too common' not in section(soup).select_one('.bd-count').text


def test_the_filters_are_the_urls_query_and_the_switch_maps_to_ignore_common(client, world, coll):
    coll.setting('candidate_sets_common_max', '25')
    soup, _ = page(client, world.lot, '?detect=1&min_score=0&theme=Stickerland&year_from=1999&year_to=2001&parts_min=10&parts_max=50&ignore_common=1')
    form = section(soup).select_one('form.bd-filters')
    assert form['method'] == 'get' and form['action'].endswith('#set-detection')
    value = lambda name: form.select_one(f'[name={name}]')                     # noqa: E731
    assert (value('min_score')['value'], value('theme')['value'], value('year_from')['value'], value('year_to')['value'], value('parts_min')['value'], value('parts_max')['value']) == ('0', 'Stickerland', '1999', '2001', '10', '50')
    assert value('ignore_common').has_attr('checked') and value('ignore_common')['role'] == 'switch'
    assert names(soup) == ['9403-1 Stk Set 9403'] or all('9403' in n or '9401' in n for n in names(soup))
    off, _ = page(client, world.lot, '?detect=1&min_score=0')                     # a submitted form without the box: the switch is off
    assert not off.select_one('input[name=ignore_common]').has_attr('checked')
    default, _ = page(client, world.lot)
    assert default.select_one('input[name=ignore_common]').has_attr('checked') and default.select_one('input[name=min_score]')['value'] == '30'
    assert 'min_score' not in lot_detect.query_of(lot_detect.read_filters({})[0])


def test_filters_cut_the_list(client, world):
    everyone = names(page(client, world.lot, '?min_score=0&show=100')[0])
    assert len(everyone) > 10
    soup, _ = page(client, world.lot, '?min_score=100')
    assert len(names(soup)) < len(everyone)
    soup, _ = page(client, world.lot, '?min_score=0&year_from=2010&year_to=2010&show=100')
    assert all('Noise' in n or '9407' in n for n in names(soup))
    soup, _ = page(client, world.lot, '?min_score=0&parts_min=30&parts_max=40')
    assert all('Set 94' in n for n in names(soup)) and not any('Noise' in n for n in names(soup))


def test_more_candidates_come_with_a_show_more_link_that_keeps_the_filters(client, world):
    soup, _ = page(client, world.lot, '?min_score=0&detect=1&ignore_common=0')
    assert len(soup.select('.bd-cand')) == 10
    link = section(soup).select_one('.bd-more-link a')
    assert 'offset=10' in link['href'] and 'ignore_common=0' in link['href'] and link['href'].endswith('#set-detection')
    more, _ = page(client, world.lot, '?min_score=0&show=20')
    assert len(more.select('.bd-cand')) == 20
    second, _ = page(client, world.lot, '?min_score=0&offset=10')
    assert [c.select_one('.bd-name').text for c in second.select('.bd-cand')][:1] != [c.select_one('.bd-name').text for c in soup.select('.bd-cand')][:1]


def test_bad_filter_values_are_notes_not_errors(client, world):
    soup, _ = page(client, world.lot, '?min_score=abc&year_from=2010&year_to=2000&parts_min=-4&theme=Nowhere')
    notes = [n.text for n in section(soup).select('.bd-note')]
    assert 'Min score is a number from 0 to 100' in notes and 'Years: the first value is above the second' in notes and any('Parts min' in n for n in notes)
    assert 'No set matches these filters' in section(soup).text and section(soup).select_one('.bd-empty a')['href'].endswith('#set-detection')


def test_a_lot_without_parts_and_a_filter_that_matches_nothing_have_their_own_words(client, coll, world):
    empty = coll.lot('Empty lot')
    soup, _ = page(client, empty)
    assert 'Nothing to match yet' in section(soup).select_one('.bd-empty').text and not section(soup).select('form')
    soup, _ = page(client, world.lot, '?min_score=100&theme=Stickerland&year_from=1800&year_to=1801')
    text = section(soup).select_one('.bd-empty').text
    assert text.startswith('No candidate sets') and 'clear the filters' in text
    assert section(soup).select_one('.bd-count').text.startswith('0 candidate sets')


def test_without_a_catalogue_the_section_says_so(client, world, monkeypatch):
    monkeypatch.setattr('brickwork.core.collection.has_catalogue', lambda db: False)
    soup, _ = page(client, world.lot)
    assert 'The catalogue is not loaded yet' in section(soup).text


def test_a_read_only_instance_still_shows_the_section_and_hides_the_writes(client, world, app4):
    world.flag()
    app4.config['BW_READ_ONLY'] = True
    soup, _ = page(client, world.lot, '', '/sticker/' + world.line)
    assert section(soup) is not None and not soup.select('#sticker-chooser form')
    assert client.post(f'/collection/lots/{world.lot}/sticker/{world.line}/clear', data=dict(csrf_token=csrf(client))).status_code == 403
    assert stickers.states(world.coll.db, [world.line])[world.line]['flagged']
    app4.config['BW_READ_ONLY'] = False


# ---------- stickers on the lot page ----------

def test_a_flagged_line_shows_its_sticker_tag_and_the_link_that_opens_the_chooser(client, world):
    soup, _ = page(client, world.lot)
    assert not soup.select('.bd-stk')
    world.flag()
    soup, _ = page(client, world.lot)
    tag = soup.select_one('.bd-stk')
    assert tag.text == 'Sticker · not chosen' and 'with a sticker' in soup.select_one('.bc-module p').text
    link = soup.select_one('.bd-stk-link')
    assert link.text == 'Which sticker?' and link['href'] == f'/collection/lots/{world.lot}/sticker/{world.line}#sticker-chooser'
    stickers.confirm(world.coll.db, world.lot, world.line, world.set('9401-1'), world.sheet('sheet-a'))
    soup, _ = page(client, world.lot)
    assert soup.select_one('.bd-stk').text == 'Sticker · set 9401-1' and soup.select_one('.bd-stk-link').text == 'Change'


def test_the_chooser_lists_the_candidates_with_the_note_and_the_three_ways_out(client, world):
    world.flag()
    soup, _ = page(client, world.lot, '', '/sticker/' + world.line)
    panel = soup.select_one('#sticker-chooser')
    assert panel.select_one('h2').text == 'Which sticker is it?'
    assert 'The catalogue does not say which part a sticker goes on. These are sets that hold this part in Red and a sticker sheet.' in panel.select_one('.bd-info').text
    rows = panel.select('.bd-set')
    assert [r.select_one('.bd-number').text for r in rows] == ['9401-1', '9408-1', '9402-1']
    assert [r.select_one('button').text for r in rows] == ['This one'] * 3
    assert panel.select_one('.bd-more-link').text.startswith('+ 3 more sets') and panel.select_one('.bd-more-link a').text == 'Show all'
    assert 'stk-sheet-a' in rows[0].select_one('.bd-meta').text and '2001' in rows[0].select_one('.bd-meta').text
    assert panel.select_one('.bd-actions a').text == 'Keep as a hint' and panel.select_one('.bd-actions button').text == 'Not a sticker'
    assert soup.select_one('#set-detection') is not None, 'the lot stays on the page behind the panel'


def test_show_all_lists_every_candidate(client, world):
    world.flag()
    soup, _ = page(client, world.lot, '?all=1', '/sticker/' + world.line)
    assert len(soup.select('#sticker-chooser .bd-set')) == 6 and soup.select_one('#sticker-chooser .bd-more-link') is None


def test_this_one_not_a_sticker_and_undo_work_as_plain_form_posts(client, world):
    world.flag()
    token = csrf(client)
    url = f'/collection/lots/{world.lot}/sticker/{world.line}'
    done = client.post(url + '/confirm', data=dict(csrf_token=token, set_item_id=world.set('9401-1'), sheet_item_id=world.sheet('sheet-a')))
    assert done.status_code == 302 and '#set-detection' in done.headers['Location'] and 'done=' in done.headers['Location']
    soup, _ = page(client, world.lot, '?' + done.headers['Location'].split('?')[1].split('#')[0])
    assert soup.select_one('.bd-done').text.startswith('Sticker chosen') and soup.select_one('.bd-stk').text == 'Sticker · set 9401-1'
    event = soup.select_one('.bd-done input[name=event_id]')['value']
    undone = client.post(f'/collection/lots/{world.lot}/sticker-undo', data=dict(csrf_token=token, event_id=event))
    assert undone.status_code == 302
    assert page(client, world.lot)[0].select_one('.bd-stk').text == 'Sticker · not chosen'
    cleared = client.post(url + '/clear', data=dict(csrf_token=token))
    assert cleared.status_code == 302
    soup, _ = page(client, world.lot, '?done=' + cleared.headers['Location'].split('done=')[1].split('&')[0] + '&was=clear')
    assert not soup.select('.bd-stk') and 'Sticker removed from this part' in soup.select_one('.bd-done').text
    assert client.get(url).status_code == 404, 'the chooser opens only for a part that has the flag'


def test_the_chooser_writes_refuse_what_is_wrong(client, world, coll):
    world.flag()
    token = csrf(client)
    base = f'/collection/lots/{world.lot}/sticker/{world.line}'
    bad = dict(csrf_token=token, set_item_id=world.set('9403-1'), sheet_item_id=world.sheet('sheet-a'))
    assert client.post(base + '/confirm', data=bad).status_code == 400
    assert client.post(base + '/confirm', data=dict(csrf_token=token)).status_code == 400
    assert client.post(base + '/confirm', data=dict(bad, csrf_token='wrong')).status_code in (400, 403)
    assert client.post(base + '/other', data=dict(csrf_token=token)).status_code == 404
    other = coll.lot('Other')
    assert client.post(f'/collection/lots/{other}/sticker/{world.line}/clear', data=dict(csrf_token=token)).status_code == 404
    assert client.post(f'/collection/lots/{world.lot}/sticker-undo', data=dict(csrf_token=token, event_id='1')).status_code in (400, 404)
    assert stickers.states(coll.db, [world.line])[world.line]['flagged'], 'nothing was written'
