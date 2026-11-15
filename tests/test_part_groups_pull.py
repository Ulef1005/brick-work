"""Part groups on the pull list (#315, part 3): the page on the sticker world (`tests/stickers_world.py`) and the data on the synthetic one with figures."""
from bs4 import BeautifulSoup
from contextlib import closing

import pytest

from brickwork.core.connect import connect
from brickwork.web import pull_page
from tests.app4 import app4, client, csrf, make_pair, Coll  # noqa: F401 (fixtures)
from tests.stickers_world import World, coll, db, pair, world  # noqa: F401 (fixtures)
from tests.store4_mint_fixtures import item_id
from tests.test_pull_list import W
from tests.test_set_scoring import SYN


def base(world, number='9401-1'):
    return f"/collection/lots/{world.lot}/pull/{world.set(number)}"


def soup_of(client, world, query='', number='9401-1'):
    response = client.get(base(world, number) + query)
    assert response.status_code == 200
    return BeautifulSoup(response.text, 'html.parser')


def sections(soup):
    return [(s['data-bw-section'], s.has_attr('open'), s.select_one('.bw-sec-count').text, [l.select_one('.bp-nm').text for l in s.select('.bp-line')])
            for s in soup.select('[data-bw-section]')]


def tick(client, world, name, found, query='?show=all'):
    line = next(l for l in soup_of(client, world, query).select('.bp-line') if l.select_one('.bp-nm').text == name)
    data = {i['name']: i['value'] for i in line.select('.bp-cbform input')}
    posted = client.post(base(world) + '/found', data=dict(data, found=str(found), csrf_token=csrf(client)))
    assert posted.status_code == 302
    return posted.headers['Location']


def test_lines_sit_under_part_groups_and_a_group_with_work_left_is_open(client, world):
    soup = soup_of(client, world, '?show=all')
    assert sections(soup) == [('Plates', True, '2 lines · 4 pieces to find', ['Stk bar', 'Stk tile']),
                              ('Decoration and extras', True, '1 line · 1 piece to find', ['Stk sheet-a'])]
    assert not soup.select('.bp-grp') and soup.select_one('[data-bw-sections-actions]').has_attr('hidden')
    assert soup.select_one('input[name=q]') and soup.select_one('select[name=show]') and soup.select_one('select[name=sort]')      # the controls stay
    assert soup.select_one('.bp-prog').get_text(' ', strip=True) == '2 of 7 pieces found 5 to find'


def test_a_finished_group_starts_collapsed_and_its_counters_still_work(client, world):
    where = tick(client, world, 'Stk sheet-a', 1)
    assert where.endswith('?show=all#l-' + where.rsplit('#l-', 1)[1]) and '#l-' in where
    soup = soup_of(client, world, '?show=all')
    found = {name: (opened, meta) for name, opened, meta, _ in sections(soup)}
    assert found['Decoration and extras'] == (False, '1 line · all found') and found['Plates'][0] is True
    closed = soup.select_one('[data-bw-section="Decoration and extras"]')
    assert closed.select_one('.bp-cnt .v').text == '1 of 1' and closed.select('.bp-step form, form.bp-step')               # the counters are in the page, closed or not
    minus = closed.select('form.bp-step')[0]
    data = {i['name']: i['value'] for i in minus.select('input')}
    assert client.post(base(world) + '/found', data=dict(data, csrf_token=csrf(client))).status_code == 302
    reopened = {name: opened for name, opened, _, _ in sections(soup_of(client, world, '?show=all'))}
    assert reopened['Decoration and extras'] is True                          # one less found: work is left again, so the group starts open
    assert soup.select_one('.bp-bar-count').get_text(' ', strip=True) == '3 found 4 to find'


def test_search_show_and_sort_keep_working_with_sections(client, world):
    soup = soup_of(client, world, '?show=all&q=bar')
    assert [(n, lines) for n, _, _, lines in sections(soup)] == [('Plates', ['Stk bar'])]
    assert sections(soup_of(client, world, '?show=found')) == []
    flat = soup_of(client, world, '?show=all&sort=number')
    assert not flat.select('[data-bw-section]') and [g.text.split(' · ')[0] for g in flat.select('.bp-grp')] == ['All parts']


def test_the_setting_changes_the_names_and_none_is_the_old_page(client, world, coll):
    coll.setting('part_list_grouping', 'bricklink')
    assert [s[0] for s in sections(soup_of(client, world, '?show=all'))] == ['Plates', 'Stickers']
    coll.setting('part_list_grouping', 'none')
    soup = soup_of(client, world, '?show=all')
    assert not soup.select('[data-bw-section], [data-bw-sections]') and [g.text.split(' · ')[0] for g in soup.select('.bp-grp')] == ['Plates', 'Stickers']
    assert len(soup.select('.bp-line')) == 3


@pytest.fixture
def syn(tmp_path):
    path = make_pair(tmp_path, extra_dump=SYN)
    with closing(connect(path)) as db:
        yield W(db, Coll(db), path)


def test_whole_figures_stay_outside_the_groups_first_and_a_header_counts_its_whole_group(syn):
    syn.coll.add_stock('minifigure', item_id(syn.db, 'minifigs', 'fig-000004'), quantity=1, lot=syn.lot)
    data = pull_page.page(syn.db, syn.lot, item_id(syn.db, 'sets', '9103-1'), {'show': 'all'})
    assert [ln['kind'] for ln in data['figures']] == ['figure'] and data['groups'] == []
    assert all(ln['kind'] == 'part' for g in data['sections'] for ln in g['lines'])
    assert [g['name'] for g in data['sections']] == sorted((g['name'] for g in data['sections']), key=lambda n: (n == 'Other', ['Bricks', 'Slopes and curves', 'Plates', 'Tiles', 'Technic', 'Hinges, bars and connectors', 'Windows, doors and panels', 'Wheels and vehicles', 'Minifigure parts', 'Nature and creatures', 'Decoration and extras', 'Other'].index(n)))
    assert data['shown'] == len(data['figures']) + sum(len(g['lines']) for g in data['sections'])


def test_the_budget_counts_figures_first_but_a_header_keeps_its_whole_group(syn, monkeypatch):
    syn.coll.add_stock('minifigure', item_id(syn.db, 'minifigs', 'fig-000004'), quantity=1, lot=syn.lot)
    for number in ('3001', 'syn-r2'):
        syn.db.execute('UPDATE main.item SET category_name=? WHERE id=?', ('Bricks', syn.coll.project(item_id(syn.db, 'parts', number))))
    syn.db.commit()
    monkeypatch.setattr(pull_page, 'FIRST', 2)
    data = pull_page.page(syn.db, syn.lot, item_id(syn.db, 'sets', '9103-1'), {})
    assert len(data['figures']) == 1 and data['shown'] == 2 and data['hidden'] == 1
    [bricks] = data['sections']
    assert bricks['name'] == 'Bricks' and len(bricks['lines']) == 1 and bricks['total'] == 2 and bricks['to_find'] == 3 and bricks['open']          # the header counts the whole group
    flat = pull_page.page(syn.db, syn.lot, item_id(syn.db, 'sets', '9103-1'), {'sort': 'number'})
    assert flat['sections'] is None and flat['figures'] is None
