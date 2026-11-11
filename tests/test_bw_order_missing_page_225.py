"""Order missing parts (#225), the page: the copies with gaps, the choice in the query, the order list with its sources and the file.

The logic is in `test_bw_order_missing_225.py`; these read it through the route. Invented data, no network."""
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

from brickwork.core import order_missing
from tests.app4 import app4, client, coll, csrf, pair  # noqa: F401 (fixtures)
from tests.test_bw_order_missing_225 import SETTINGS, URL, page, scene, ticked


# ---------- the page ----------

def test_the_page_lists_every_copy_with_a_gap_and_ticks_them_by_default(coll, client):
    s = scene(coll)
    soup = page(client)
    assert set(ticked(soup)) == set(s.values())
    assert soup.select_one('h1').text == 'Order missing parts'
    assert soup.select_one('[data-oo-summary]').text == '4 sets have gaps · 4 in the list'
    assert soup.select_one('[data-oo-total]').text == '2 lines · 5 pieces from 4 sets'
    names = [n.text for n in soup.select('.oo-name')]
    assert '1000-1 · Set 1' in names[0] or any('1000-1 · Set 2' in n for n in names)
    r = client.get(URL)
    assert r.headers['Cache-Control'] == 'no-store'
    assert 'href="/planning/complete-sets"' in r.get_data(as_text=True)


def test_the_choice_lives_in_the_query_and_the_totals_follow_it(coll, client):
    s = scene(coll)
    soup = page(client, sel='1', copy=[s['first'], s['gate_new']])
    assert set(ticked(soup)) == {s['first'], s['gate_new']}
    assert soup.select_one('[data-oo-summary]').text == '4 sets have gaps · 2 in the list'
    assert soup.select_one('[data-oo-total]').text == '2 lines · 3 pieces from 2 sets'
    assert 'Export 2 sets · BrickLink XML' in soup.select_one('.oo-export .button').text
    assert not ticked(page(client, sel='none')) and ticked(page(client, sel='1')) == []
    assert 'Tick the sets' in page(client, sel='none').select_one('.oo-review').text
    assert set(ticked(page(client, sel='all'))) == set(s.values())


def test_select_all_and_clear_are_links_that_keep_the_filters(coll, client):
    scene(coll)
    soup = page(client, q='1000-2', sell='0')
    for link, sel in ((soup.find('a', string='Select all'), 'all'), (soup.find('a', string='Clear'), 'none')):
        query = parse_qs(urlsplit(link['href']).query)
        assert query['sel'] == [sel] and query['q'] == ['1000-2'] and query['sell'] == ['0']


def test_search_and_theme_narrow_the_list_and_only_what_is_shown_counts(coll, client):
    s = scene(coll)
    soup = page(client, q='1000-2')
    assert {c['value'] for c in soup.select('[data-oo-copy]')} == {s['gate'], s['gate_new']}
    assert soup.select_one('[data-oo-total]').text == '2 lines · 2 pieces from 2 sets'
    assert page(client, theme='Nowhere').select_one('.oo-none').text.startswith('No set matches')
    assert len(page(client, theme='Castle').select('[data-oo-copy]')) == 4
    assert page(client, sel='1', copy=[s['first'], s['gate']], q='1000-2').select_one('[data-oo-total]').text.endswith('from 1 set')


def test_a_set_to_sell_stays_visible_greyed_and_unticked_with_its_reason(coll, client):
    s = scene(coll)
    coll.tag('copy', s['gate'], coll.flag('To sell', 'status'))
    soup = page(client)
    row = soup.find('input', value=s['gate']).find_parent('label')
    assert 'oo-out' in row['class'] and 'To sell' in row.text and 'left out' in row.text and not row.find('input').has_attr('checked')
    assert s['gate'] not in ticked(soup) and len(ticked(soup)) == 3
    assert soup.select_one('.oo-chip').text.startswith('Leave out: sell or part out · 1 set')
    off = page(client, sell='0')
    assert s['gate'] in ticked(off) and not off.select('.oo-out')
    by_hand = page(client, sel='1', copy=list(s.values()))
    assert s['gate'] in ticked(by_hand) and 'oo-out' in by_hand.find('input', value=s['gate']).find_parent('label')['class']


def test_the_switches_survive_an_unticked_box(client, coll):
    scene(coll)
    soup = page(client)
    for name in ('sell', 'gain'):
        assert [i['value'] for i in soup.select(f'input[name={name}]')][0] == '0'            # the form's 0 comes first, the box's 1 after it
    assert soup.select_one('input[name=sell][type=checkbox]').has_attr('checked')
    assert not soup.select_one('input[name=gain][type=checkbox]').has_attr('checked')
    off = page(client, sell=['0'], gain=['1', '0'])
    assert not off.select_one('input[name=sell][type=checkbox]').has_attr('checked') and not off.select_one('input[name=gain][type=checkbox]').has_attr('checked')


def test_only_gain_leaves_out_the_copies_without_a_price_and_says_so(coll, client):
    scene(coll)
    soup = page(client, gain='1')
    assert not ticked(soup) and 'no value gain' in soup.get_text()
    assert 'count as no gain' in soup.select_one('.oo-note').text


def test_each_line_names_its_sources_and_the_rest_folds(coll, client):
    s = scene(coll)
    soup = page(client)
    first = soup.select('.oo-line')[0]
    assert '×4' in first.select_one('.oo-qty').text
    assert [x.text for x in first.select('.oo-src')] == ['1000-1 · Set 1 ×2', '1000-1 · Set 2 ×1', '1000-2 · Set 1 ×1']
    assert not soup.select('.oo-more')                                                       # 2 lines: nothing to fold
    assert s


def test_more_lines_than_the_first_few_sit_behind_show_all(coll, client):
    """Five lines: used 3001, 3023 and the figure from one copy, new 3001 and 3023 from another."""
    for key, value in SETTINGS.items():
        coll.setting(key, value)
    used, new = coll.add_copy('1000-1', condition='used'), coll.add_copy('1000-1', condition='new')
    for copy in (used, new):
        coll.mark(copy, '3001', '4', missing=1)
        coll.mark(copy, '3023', '15', missing=2)
    coll.mark_figure(used, 'fig-000004', missing=1)
    soup = page(client)
    assert soup.select_one('[data-oo-total]').text == '5 lines · 7 pieces from 2 sets'            # a figure counts as its quantity
    assert len(soup.select('[data-oo-lines] > .oo-line')) == order_missing.FIRST_LINES
    more = soup.select_one('.oo-more')
    assert more.summary.text == '+ 1 more line · Show all' and len(more.select('.oo-line')) == 1
    assert '−1</b> figure' in str(soup.select_one('[data-oo-rows]'))


def test_the_file_is_the_one_complete_sets_exports(coll, client):
    s = scene(coll)
    chosen = [s['first'], s['gate'], s['gate_new']]
    old = client.post('/planning/action/export', json=dict(csrf_token=csrf(client), ids=chosen))
    new = client.get(URL + '/missing-parts.xml', query_string=dict(copy=chosen))
    assert new.status_code == 200 and new.data == old.data and new.mimetype == 'application/xml'
    for header in ('Content-Disposition', 'Cache-Control', 'X-Bw-Skipped'):
        assert new.headers[header] == old.headers[header]
    link = page(client, sel='1', copy=chosen).select_one('.oo-export .button')['href']
    assert client.get(link).data == old.data
    for bad in ('', 'nope'):
        assert client.get(URL + '/missing-parts.xml', query_string=dict(copy=bad) if bad else None).status_code == 400


def test_a_phone_step_shows_the_review_and_the_bar_names_the_choice(coll, client):
    s = scene(coll)
    soup = page(client, sel='1', copy=[s['first']], step='review')
    assert soup.select_one('#bw-planning')['data-step'] == 'review'
    assert 'Export · BrickLink XML' in soup.select_one('.oo-bar').text
    choose = page(client, sel='1', copy=[s['first']])
    assert choose.select_one('#bw-planning')['data-step'] == 'choose'
    button = choose.select_one('[data-oo-review]')
    assert button['form'] == 'oo-form' and button['value'] == 'review' and choose.select_one('form#oo-form')


def test_the_page_is_a_read_it_stays_on_a_read_only_instance_and_needs_login(coll, client, app4):
    s = scene(coll)
    assert app4.test_client().get(URL).status_code == 302
    app4.config['BW_READ_ONLY'] = True
    assert client.get(URL).status_code == 200
    assert client.get(URL + '/missing-parts.xml', query_string=dict(copy=[s['first']])).status_code == 200


def test_the_nav_keeps_complete_sets_current_and_complete_sets_links_here(coll, client):
    scene(coll)
    soup = page(client)
    current = [a for a in soup.select('a[href="/planning/complete-sets"]') if a.get('aria-current')]
    assert current
    assert soup.select_one(f'a[href="{URL}"]') is None                                       # the page does not link to itself
    complete = BeautifulSoup(client.get('/planning/complete-sets').data, 'html.parser')
    assert complete.select_one(f'a[href="{URL}"]').text == 'Order missing parts'


def test_an_empty_collection_says_so(coll, client):
    soup = page(client)
    assert 'No set has a gap' in soup.get_text()
