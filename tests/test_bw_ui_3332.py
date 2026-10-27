"""Design v1.3 detail regressions, using rendered catalogue and copy state on a 4.0 collection (M.8b, issue #110)."""
from bs4 import BeautifulSoup
import pytest

from brickwork.core import collection
from brickwork.web.formatting import money
from brickwork.web.ui import part_name
from tests.app4 import STAMP, app4, client, coll, pair, read, world  # noqa: F401  (fixtures)

FIGURE = 'fig-000004'
SET = '1000-1'


@pytest.mark.parametrize('value,fixed,expected', [
    ('11408.95', True, '€11,408.95'), ('1000', False, '€1,000'),
    ('-11408.95', True, '€11,408.95 below'), ('999.995', True, '€1,000.00'),
])
def test_grouped_money(value, fixed, expected):
    assert money(value, fixed=fixed) == expected


def figure_part(coll, copy, part_key='970c03', **changes):
    """The set-side line of one component of the figure in a copy (the figure's parts, design 4.4)."""
    sets = ','.join(f'{k}=?' for k in changes)
    done = coll.sql(f'''UPDATE copy_part SET {sets} WHERE copy_id=? AND item_id=? AND retired_at IS NULL AND copy_figure_id IS NOT NULL''',
                    (*changes.values(), copy, coll.item('parts', part_key))).rowcount
    assert done == 1
    return part_name(coll.db.execute('SELECT name FROM catalogue.item WHERE id=?', (coll.item('parts', part_key),)).fetchone()[0])


def figure_row(soup, number=FIGURE):
    return next(r for r in soup.select('.bc-figure-row') if r.select_one('.bc-figure-identity>.mono').get_text().startswith(number))


@pytest.mark.parametrize('state', ['present', 'parts-missing', 'missing'])
def test_figure_lines_and_image(coll, client, state):
    missing = state == 'missing'
    copy = coll.add_copy(SET)
    set_id, figure = coll.item('sets', SET), coll.item('minifigs', FIGURE)
    torso = None
    if missing:
        coll.mark_figure(copy, FIGURE, missing=1)
    elif state == 'parts-missing':
        torso = figure_part(coll, copy, missing=1)
    detail = collection.detail(coll.db, set_id, copy_id=copy)
    assert detail['figure_progress']['present'] == sum(max((r['quantity'] or 0) - (r['missing'] or 0), 0) for r in detail['consists'] if r['kind'] == 'minifigure')
    soup = BeautifulSoup(client.get(f'/collection/item/{set_id}?copy={copy}&inventory=figures').data, 'html.parser')
    fig = figure_row(soup)
    assert fig.select_one('.bc-figure-identity>a')['href'] == f'/collection/item/{figure}'
    assert not fig.select('a.bc-figure-status')
    assert fig.select_one('.bc-figure-status')['data-figure-state'] == state
    assert bool(fig.select_one('button.bc-check-figure[disabled]')) == missing
    if missing:
        assert fig.select_one('.bc-check-figure')['title'] == 'Whole figure missing'
    else:
        # The link names the figure line (`copy_figure.id`); the screen itself is tested in test_bw_checker.py.
        line = coll.db.execute('SELECT id FROM copy_figure WHERE copy_id=? AND item_id=?', (copy, figure)).fetchone()[0]
        assert fig.select_one('.bc-check-figure')['href'] == f'/workbench/check-parts/{copy}/figure/{line}'
        if state == 'parts-missing':
            assert fig.select_one('.bc-figure-parts').get_text() == torso
        else:
            assert not fig.select_one('.bc-figure-parts')
    # The figure's picture and its /manage/images file are M.8f; the row itself keeps its picture frame.
    assert fig.select_one('.bc-picture')
    assert 'Parts missing from a figure count on the figure, not on the set.' in soup.get_text()
    assert 'Part details' not in soup.get_text()
    assert not soup.select('.bc-inventory-row-details')
    assert soup.select('.bc-inventory-details [data-bc-context]')
    assert 'Grouped by place and condition in lists.' not in soup.get_text()
    coll.add_stock('minifigure', figure, quantity=1)
    minifigure = BeautifulSoup(client.get(f'/collection/item/{figure}').data, 'html.parser')
    assert 'Part details' not in minifigure.get_text()
    assert 'Grouped by place and condition in lists.' not in minifigure.get_text()


def test_canonical_brickset_and_phone_order(coll, client):
    item = coll.local('set', 'Castle', born_key='375-2')
    links = dict(collection.external_links(coll.db, dict(item_type='S', item_id=item, number='375-2')))
    assert links['Brickset'] == 'https://brickset.com/sets/375-2'
    soup = BeautifulSoup(client.get(f'/collection/item/{item}').data, 'html.parser')
    assert soup.select_one('.bc-phone-links a[href="https://brickset.com/sets/375-2"]')
    assert soup.select_one('.bc-phone-links').parent.find_next_sibling()['class'] == ['bc-hero-status']
    layout = soup.select_one('.bc-detail-layout')
    assert layout.find(recursive=False)['class'] == ['bc-detail-aside']
    assert [r['data-module'] for r in layout.select('.bc-detail-aside>[data-module]')] == ['info', 'prices']


def test_grouped_price_range_and_wishlist(coll, client):
    copy = coll.add_copy(SET)
    keep = coll.item('sets', SET)
    coll.price(keep, '11408.95', condition='used', guide='sold', minimum='1000', maximum='15000', sold=7)
    wish = coll.add_wish(keep, max_price='11408.95', currency='EUR')
    soup = BeautifulSoup(client.get(f'/collection/item/{keep}?copy={copy}').data, 'html.parser')
    price = soup.select_one('[data-module=prices]').get_text(' ', strip=True)
    assert '€11,408.95' in price and 'min €1,000.00' in price and 'max €15,000.00' in price
    page = BeautifulSoup(client.get(f'/collection/wishes/{wish}').data, 'html.parser')
    assert page.select_one('.bc-wanted-max strong').get_text() == '€11,408.95'


@pytest.mark.parametrize('missing,damaged', [(1, 0), (0, 1), (1, 1)])
def test_figure_missing_and_damaged_parts_are_separate(coll, client, missing, damaged):
    copy = coll.add_copy(SET)
    set_id = coll.item('sets', SET)
    torso = figure_part(coll, copy, missing=missing, damaged=damaged)
    detail = collection.detail(coll.db, set_id, copy_id=copy)
    figure = next(r for r in detail['consists'] if r['number'] == FIGURE)
    assert figure['parts_missing'] == missing
    assert figure['parts_damaged'] == damaged
    assert figure['missing_part_names'] == ([torso] if missing else [])
    soup = BeautifulSoup(client.get(f'/collection/item/{set_id}?copy={copy}&inventory=figures').data, 'html.parser')
    row = figure_row(soup)
    assert row.select_one('.bc-figure-status').get_text() == ('1 part missing' if missing else 'Present')
    assert ('1 damaged' in row.get_text()) == bool(damaged)
    assert bool(row.select_one('.bc-figure-parts')) == bool(missing)
    assert not row.select_one('button[disabled]')


@pytest.mark.parametrize('status', ['to_check', 'unmatched'])
@pytest.mark.parametrize('kind', ['set_number', 'setID'])
def test_canonical_brickset_does_not_infer_ambiguous_mapping(coll, status, kind):
    item = coll.local('set', 'Castle', born_key='375-2')
    if status == 'to_check':
        coll.link(item, 'uncertain', kind=kind, provider='brickset', status='to_check')
    else:
        coll.sql("INSERT INTO item_provider_status(item_id,provider,status,reason,checked_at) VALUES(?,'brickset','unmatched','no_match',?)", (item, STAMP))
    links = dict(collection.external_links(coll.db, dict(item_type='S', item_id=item, number='375-2')))
    assert 'Brickset' not in links
    assert 'BrickLink' in links
