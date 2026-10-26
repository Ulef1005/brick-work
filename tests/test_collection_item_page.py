"""The item page and its prices, inventory, copy chips, links and panels on the 4.0 store (M.8b, issue #110).

The second half of the old `test_bw_collection.py` (from the Run 2 sets list to the end), rebuilt on `tests.app4` fixtures. Items are ids,
conditions and completeness are words, a part is always in a colour. The Matching module, Take/Give and every write (save, archive, undo,
estimate save, transfers) wait for M.8e / M.8d: the loose stock that could cover a gap is not read yet (`progress.can_take` is None, every
line has `can_take` 0), and the tests of those stay in the old file. Invented data, no network."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
import pytest

from brickwork.core import collection, collection_prices, workbench
from brickwork.store4 import fetched
from tests.app4 import STAMP, app4, client, coll, pair, read  # noqa: F401  (fixtures)

CSS = Path('static/web/toni/bw-collection.css')
FROZEN = lambda: datetime(2026, 10, 14, tzinfo=timezone.utc)      # noqa: E731


# ---------- helpers ----------

def soup_of(client, url, status=200):
    response = client.get(url)
    assert response.status_code == status, response.get_data(as_text=True)[:600]
    return BeautifulSoup(response.data, 'html.parser')


def item_page(client, item, **query):
    """The soup of the item page; query values as the page takes them (`copy`, `stock`, `colour`)."""
    return soup_of(client, f'/collection/item/{item}' + ('?' + '&'.join(f'{k}={v}' for k, v in query.items()) if query else ''))


def detail(read, item, **arguments):
    with read() as db:
        return collection.detail(db, item, **arguments)


def put_observations(coll, item, rows, *, colour=None):
    """Price observations as a refresh leaves them; `rows` are dicts of the columns that differ from a used, sold, EUR BrickLink quote."""
    columns = ('condition', 'guide', 'slot', 'region', 'currency', 'price', 'min', 'max', 'sold', 'source', 'observed_at', 'error')
    base = dict(condition='used', guide='sold', slot=None, region=None, currency='EUR', price='10', min='1', max='50', sold=7, source='bricklink',
                observed_at='2026-10-08', error=None)
    coll.db.executemany(f'INSERT INTO price_observation(item_id,color_id,{",".join(columns)}) VALUES(?,?,{",".join("?" * len(columns))})',
                        [(item, colour, *({**base, **row}[c] for c in columns)) for row in rows])
    coll.db.commit()


def lines_of(coll, copy_id):
    return coll.db.execute('SELECT * FROM copy_part WHERE copy_id=? ORDER BY id', (copy_id,)).fetchall()


def clear_lines(coll, copy_id):
    """A copy with no lines at all (parts first: they point at their figures)."""
    coll.db.execute('DELETE FROM copy_part WHERE copy_id=?', (copy_id,))
    coll.db.execute('DELETE FROM copy_figure WHERE copy_id=?', (copy_id,))
    coll.db.commit()


def add_line(coll, copy_id, item, colour, quantity, *, missing=0, damaged=0, checked=0, spare=0, figure=None):
    """One live part line of a copy; `figure` is the id of its `copy_figure` (a component of that figure)."""
    coll.db.execute('INSERT INTO copy_part(copy_id,copy_figure_id,item_id,color_id,is_spare,quantity,missing,damaged,checked) VALUES(?,?,?,?,?,?,?,?,?)',
                    (copy_id, figure, item, colour, spare, quantity, missing, damaged, checked))
    coll.db.commit()


def add_figure(coll, copy_id, item, *, quantity=1, missing=0):
    coll.db.execute("INSERT INTO copy_figure(copy_id,item_id,inventory_source,inventory_digest,quantity,missing,updated_at) VALUES(?,?,'none','none',?,?,?)",
                    (copy_id, item, quantity, missing, STAMP))
    coll.db.commit()
    return coll.db.execute('SELECT id FROM copy_figure WHERE copy_id=? AND item_id=?', (copy_id, item)).fetchone()[0]


def local_parts(coll, count, prefix='bulk'):
    """`count` BrickLink-born local parts, made with one commit."""
    made = [fetched.create_local_item(coll.db, kind='part', born_provider='bricklink', born_namespace='P', born_key=f'{prefix}-{n}',
                                      name=f'Bulk part {n}', kind_source='bricklink') for n in range(count)]
    coll.db.commit()
    return made


def css():
    return CSS.read_text()


# ---------- the sets list ----------

def test_sets_list_filter_mapping_toolbar_and_subtitle(coll, client):
    keep = coll.item('sets', '1000-1')
    coll.add_copy('1000-1')
    coll.price(keep, '12', condition='used', observed='2026-10-08')
    soup = soup_of(client, '/collection/sets')
    assert soup.select_one('.bc-heading>.button.primary').get_text(strip=True) == 'Add'
    assert 'prices are used averages from BrickLink' in soup.select_one('.bc-heading').get_text()
    toolbar = soup.select_one('.bc-toolbar')
    assert toolbar.select_one('[data-bc-search]') and toolbar.select_one('[data-bc-count]') and toolbar.select_one('.bc-view-switch')
    panel = soup.select_one('[data-bc-panel]')
    assert [h.get_text() for h in panel.select('h4')] == ['Status', 'Condition', 'Copies', 'Tags', 'Has', 'View']
    for key in ['type', 'condition', 'status', 'colour', 'problem', 'flags', 'storage', 'place', 'lot', 'duplicates', 'stock', 'category', 'theme', 'year']:
        assert panel.select_one('[data-bc-filter=' + key + ']'), key
    assert [b['data-value'] for b in panel.select('[data-bc-pick=has]')] == ['Box present', 'Instructions present']
    assert panel.select_one('.bc-other-filters [data-bc-filter=problem]')


# ---------- prices ----------

def test_prices_freshest_priority_records_and_real_history(coll, client, monkeypatch):
    monkeypatch.setattr(collection_prices, 'now', FROZEN)
    keep = coll.item('sets', '1000-1')
    cid = coll.add_copy('1000-1', current_value='19.23', current_value_currency='EUR')
    # Same series twice, an older record, a newer other source, a valuation, and unlike currencies/slots/invalid dates: none become invented points.
    put_observations(coll, keep, [
        dict(price='10', observed_at='2026-05-01'),
        dict(price='12', observed_at='2026-10-08'),
        dict(price='99', observed_at='2025-10-01'),
        dict(price='45', observed_at='2026-10-09', source='rebrickable'),
        dict(condition='new', price='20', observed_at='2026-10-08'),
        dict(condition='new', guide='valuation', price='30', observed_at='2026-10-09', source='brickset'),
        dict(price='13', observed_at='2026-10-10', currency='USD', error='Unavailable'),
        dict(price='14', observed_at='bad date'),
        dict(price='15', observed_at='2026-09-10', slot='boxed'),
        dict(guide='stock', price='18', observed_at='2026-10-11'),
    ])
    soup = item_page(client, keep, copy=cid)
    card = soup.select_one('[data-module=prices]')
    rows = card.select('[data-bc-condition-prices] .bc-price')
    assert [r.strong.get_text() for r in rows] == ['Used', 'New']
    assert '12.00' in rows[0].get_text() and '20.00' in rows[1].get_text()
    records = card.select_one('.bc-price-records')
    assert not records.has_attr('open') and len(records.select('.bc-price')) == 10
    assert '45.00' in records.get_text() and 'Unavailable' in records.get_text()
    assert 'Set estimate' in card.select_one('.bc-price-footer').get_text()
    assert '19.23' in card.select_one('.bc-price-footer').get_text()        # the copy's own estimate wins
    assert '30.00' in records.get_text()                                    # a source valuation stays available
    chart = card.select_one('[data-bc-price-history]')
    assert chart and len(chart.select('circle')) == 2
    assert '2026-05-01' in chart.get_text() and '2026-10-08' in chart.get_text()
    assert '2025-10-01' not in chart.get_text() and '45.00' not in chart.get_text()
    assert 'Axis starts at €10.00.' in chart.get_text()
    assert card.select_one('[data-bc-condition-prices]').find_next_sibling() == chart
    # The source setting controls the condition selection, not an arbitrary source name.
    coll.setting('source_priority', json.dumps({'market_price': {'*': ['rebrickable', 'bricklink']}}))
    soup = item_page(client, keep)
    assert '45.00' in soup.select_one('[data-bc-condition-prices] .bc-price').get_text()
    assert not soup.select_one('[data-bc-price-history]')                   # one point in the selected series


@pytest.mark.parametrize('dates,condition,currency,expected', [
    ([], 'used', 'EUR', False),
    (['2026-10-08'], 'used', 'EUR', False),
    (['2026-10-08', '2026-10-08'], 'used', 'EUR', False),
    (['2026-03-01', '2026-10-08'], 'used', 'EUR', False),
    (['2026-05-01', '2026-10-08'], 'new', 'EUR', False),
    (['2026-05-01', '2026-10-08'], 'used', 'EUR', True),
    (['2026-05-01', '2026-10-08'], 'used', None, True),
])
def test_history_eligibility(coll, client, monkeypatch, dates, condition, currency, expected):
    monkeypatch.setattr(collection_prices, 'now', FROZEN)
    keep = coll.item('sets', '1000-1')
    coll.add_copy('1000-1')
    put_observations(coll, keep, [dict(condition=condition, currency=currency, observed_at=date) for date in dates])
    soup = item_page(client, keep)
    chart = soup.select_one('[data-bc-price-history]')
    assert bool(chart) == expected
    if expected:
        if currency is None:
            assert 'currency not recorded' in chart.get_text().lower()
        assert len({p['cy'] for p in chart.select('circle')}) == 1          # real equal averages form a flat line
    else:
        # #32: one usable date shows the single-point state as text; nothing usable shows nothing.
        single = soup.select_one('[data-bc-price-single]')
        if single:
            assert condition == 'used' and 'Single price point' in single.get_text() and not single.select('svg')
        else:
            assert 'Used average over six months' not in soup.get_text()


@pytest.mark.parametrize('maximum', ['', 'abc'])
def test_superseded_corrupt_price_records_render(coll, client, maximum):
    keep = coll.item('sets', '1000-1')
    coll.add_copy('1000-1')
    put_observations(coll, keep, [dict(price='2', min='1', max=maximum, sold=3, observed_at='2020-01-01T00:00:00+00:00'),
                                  dict(price='2', min='1', max='5', sold=3, observed_at=123)])
    decorated = collection.decorate_prices([
        dict(condition='used', guide='sold', slot='', item_type='S', price='2', min='1', max=maximum, sold=3, observed_at='2020-01-01', max_age_days=1),
        dict(condition='used', guide='sold', slot='', item_type='S', price='2', min='1', max='5', sold=3, observed_at=123, max_age_days=1)])
    assert decorated[0]['stale'] is True and decorated[0]['range'] is None
    assert decorated[1]['stale'] is False and decorated[1]['range'] == 25
    records = item_page(client, keep).select_one('.bc-price-records')
    assert records and len(records.select('.bc-price')) >= 2


@pytest.mark.parametrize('kind', ['set', 'part'])
def test_single_and_multiple_prices(coll, client, kind):
    if kind == 'set':
        item, colour = coll.item('sets', '1000-1'), None
        coll.add_copy('1000-1')
        query = {'copy': coll.db.execute('SELECT id FROM copy').fetchone()[0]}
    else:
        item, colour = coll.item('parts', '3001'), coll.colour('4')
        coll.add_stock('part', item, colour=colour, quantity=2)
        query = {'colour': colour}
    put_observations(coll, item, [dict(condition='used', price='10', min='5', max='15', sold=3), dict(condition='new', price='20', min='20', max='20', sold=1)],
                     colour=colour)
    prices = item_page(client, item, **query).select_one('[data-module=prices]')
    assert 'Window not recorded' not in prices.get_text()
    if kind == 'set':
        assert 'With box: not set' in prices.select_one('.bc-price-footer').get_text()
    used, new = prices.select('[data-bc-condition-prices] .bc-price')
    assert 'avg' in used.get_text() and used.select_one('.bc-range')
    assert 'min €5.00' in used.get_text() and 'max €15.00' in used.get_text()
    assert 'avg' not in new.get_text() and not new.select_one('.bc-range')
    assert 'min ' not in new.get_text() and 'max ' not in new.get_text()
    assert '€20.00' in new.get_text()
    for record in prices.select('.bc-price-records .bc-price'):
        if '1 sold' in record.get_text():
            assert 'avg' not in record.get_text() and not record.select_one('.bc-range')


def test_estimate_footer_and_edit_field(coll, client):
    """The read half of the estimate: the footer shows the copy's own estimate and opens the edit panel on its field. Saving and
    undoing it is M.8d."""
    keep = coll.item('sets', '1000-1')
    cid = coll.add_copy('1000-1')
    put_observations(coll, keep, [dict(guide='valuation', slot='boxed', price='5.00', observed_at='2026-10-08', source='brickset')])
    soup = item_page(client, keep, copy=cid)
    footer = soup.select_one('.bc-price-footer')
    assert 'With box:' in footer.get_text() and '5.00' in footer.get_text()
    assert footer.select_one('[data-bw-open=bc-edit]')['data-bc-focus'] == 'current_value'
    assert soup.select_one('#bc-edit input[name=current_value]')
    assert '€0.00' not in footer.get_text()
    coll.sql("UPDATE copy SET current_value='0',current_value_currency='EUR' WHERE id=?", (cid,))
    footer = item_page(client, keep, copy=cid).select_one('.bc-price-footer')
    assert '€0.00' in footer.get_text() and 'Age not recorded' in footer.get_text()


def test_price_metadata_keeps_provenance_in_title(coll, client):
    keep = coll.item('sets', '1000-1')
    cid = coll.add_copy('1000-1')
    put_observations(coll, keep, [dict(region='eu', sold=7), dict(region='eu', sold=7, min='10', max='14', price='12')])
    soup = item_page(client, keep, copy=cid)
    captions = soup.select('.bc-price>.secondary')
    assert captions
    for caption in captions:
        assert caption['title'] == 'bricklink · eu'
        assert 'bricklink' not in caption.get_text() and 'eu' not in caption.get_text()
    assert soup.select_one('[data-bc-condition-prices] .bc-price>.secondary').get_text().startswith('7 sold · ')


@pytest.mark.parametrize('kind', ['set', 'minifigure', 'part'])
@pytest.mark.parametrize('sold', [None, 0, 1, 8])
def test_price_sale_count_wording(coll, client, kind, sold):
    if kind == 'set':
        item, colour = coll.item('sets', '1000-1'), None
        query = {'copy': coll.add_copy('1000-1')}
    elif kind == 'minifigure':
        item, colour, query = coll.item('minifigs', 'fig-000004'), None, {}
        coll.add_stock('minifigure', item, quantity=1)
    else:
        item, colour = coll.item('parts', '3001'), coll.colour('4')
        coll.add_stock('part', item, colour=colour, quantity=1)
        query = {'colour': colour}
    put_observations(coll, item, [dict(price='10', min='5', max='15', sold=sold)], colour=colour)
    captions = item_page(client, item, **query).select('[data-module=prices] .bc-price>.secondary')
    assert captions
    for caption in captions:
        assert caption.get_text().startswith('Sold count not recorded · ' if sold is None else f'{sold} sold · ')
        assert 'Count not recorded sold' not in caption.get_text()


# ---------- the info panel, the edit panel and the archive form ----------

def test_info_edit_panel_instructions_tab_and_archive_form(coll, client):
    """The read half of the old info/edit/archive test: the panels and the archive form. The archive and its undo are M.8d."""
    keep = coll.item('sets', '1000-1')
    cid = coll.add_copy('1000-1')
    soup = item_page(client, keep, copy=cid)
    info = soup.select_one('[data-module=info]')
    assert info.h2.get_text() == 'Info'
    assert info.select_one('.bc-info-edit .icon')
    assert not info.select('.bc-source-details, a')
    assert len(soup.select('.bc-info-edit[data-bw-open=bc-edit]')) == 1
    assert soup.select_one('#bc-edit .bc-source-details')
    assert soup.select_one('#bc-edit [data-bw-open=bc-delete]').get_text() == 'Delete set'
    assert not soup.select_one('.bc-detail-hero [data-bw-open=bc-delete]')
    extras = soup.select_one('[data-bc-tab-extras]')
    assert extras.has_attr('hidden')
    assert extras.select_one('a[href="/manage/instructions"]')
    archive = soup.select_one('#bc-delete form')
    assert archive['data-bc-action'] == 'archive'
    assert json.loads(archive['data-identity']) == {'entity': 'copy', 'ids': [cid]}
    assert soup.select_one('#bc-delete [data-bw-close]').get_text() == 'Keep it'


def test_edit_panel_omits_source_and_offers_completeness(coll, client):
    """The read half of the old manual-override test; saving the override and its undo are M.8d."""
    keep = coll.item('sets', '1000-1')
    soup = item_page(client, keep, copy=coll.add_copy('1000-1'))
    assert not soup.select_one('#bc-edit [name=completeness_source]')
    assert soup.select_one('#bc-edit [name=completeness]')


def test_instruction_files_are_in_extras(coll, client):
    keep = coll.item('sets', '1000-1')
    cid = coll.add_copy('1000-1')
    identifier = coll.sql("INSERT INTO instruction_file(item_id,path,label,added_at) VALUES(?,'data/instructions/guide.pdf','Recorded guide',?)",
                          (keep, STAMP)).lastrowid
    soup = item_page(client, keep, copy=cid)
    extras = soup.select_one('[data-bc-tab-extras]')
    assert 'Open PDF · Recorded guide' in extras.get_text()
    assert str(identifier) in extras.select_one('a.button')['href']
    assert extras.select_one('a[href="/manage/instructions"]')
    assert not soup.select_one('[data-module=info]').select('a')


# ---------- navigation, identity and recorded links ----------

@pytest.mark.parametrize('kind', ['set', 'part'])
def test_detail_navigation_and_identity(coll, client, kind):
    if kind == 'set':
        item, query, parent, letter = coll.item('sets', '1000-1'), {'copy': coll.add_copy('1000-1')}, 'Sets', 'S'
    else:
        item, parent, letter = coll.item('parts', '3001'), 'Parts', 'P'
        coll.add_stock('part', item, colour=coll.colour('4'), quantity=1)
        query = {'colour': coll.colour('4')}
    soup = item_page(client, item, **query)
    back = soup.select_one('.bc-detail-back')
    assert back.span.get_text() == parent
    assert back.select_one('svg path')['d'] == 'M15 6l-6 6 6 6'
    assert back['href'] == '/collection/' + letter
    assert soup.select_one('.header .shell-add .icon')
    hero = soup.select_one('.bc-detail-hero')
    assert not hero.select('[data-bw-open=bc-edit], [data-bw-open=bc-delete]')
    if kind == 'set':
        assert [x.get_text() for x in hero.select('.bc-identity>span')] == ['1000-1', '1990', 'Castle']
        assert hero.select_one('.bc-phone-links').parent.find_next_sibling()['class'] == ['bc-hero-status']
        assert hero.select_one('.bc-hero-status .bc-desktop-links')
        assert 'Source not recorded' not in hero.get_text()


def test_recorded_external_links_and_missing_ambiguous_ids(coll, client, read):
    # A BrickLink-born local set: BrickLink by its own number, Brickset only from a confirmed Brickset link.
    local = coll.local('set', 'Only on BrickLink', born_key='new-set')

    def links():
        soup = item_page(client, local)
        return {a.get_text(strip=True): a['href'] for a in soup.select('.bc-external-links a')}
    assert links() == {'BrickLink': 'https://www.bricklink.com/v2/catalog/catalogitem.page?S=new-set'}
    coll.link(local, '7286-2', kind='S', provider='brickset', status='manual')
    assert links()['Brickset'] == 'https://brickset.com/sets/7286-2'
    coll.link(local, '7286-3', kind='S', provider='brickset', status='matched')
    assert 'Brickset' not in links()                                        # two confirmed numbers: ambiguous
    # A catalogue set with no Brickset link carries its own set number there.
    keep = coll.item('sets', '1000-1')
    assert item_page(client, keep).select_one('.bc-external-links a[href="https://brickset.com/sets/1000-1"]')
    # An unidentified item has no links, and a number is encoded: it cannot inject query parameters.
    unidentified = coll.local('set', 'Mystery set')
    encoded = coll.local('set', 'Odd number', born_key='a&b=1')
    with read() as db:
        assert collection.external_links(db, dict(item_type='S', item_id=unidentified, unidentified=True)) == []
        assert collection.external_links(db, dict(item_type='P', item_id=encoded, unidentified=False)) == []
        assert collection.external_links(db, dict(item_type='S', item_id=encoded, unidentified=False, number='a&b=1')) == [
            ('BrickLink', 'https://www.bricklink.com/v2/catalog/catalogitem.page?S=a%26b%3D1')]


def test_set_identity_keeps_to_check(coll, client):
    keep = coll.item('sets', '1000-1')
    cid = coll.add_copy('1000-1')
    coll.link(keep, 'uncertain', kind='S', provider='brickset', status='to_check')
    hero = item_page(client, keep, copy=cid).select_one('.bc-detail-hero')
    assert 'To check' in hero.get_text()
    assert not hero.select_one('.bc-external-links a[href*="brickset"]')


# ---------- "Consists of": progress, rows and their metadata ----------

@pytest.mark.parametrize('state', ['missing', 'present', 'unchecked', 'empty'])
def test_missing_inventory_projection_and_no_invented_progress(coll, client, read, state):
    keep = coll.item('sets', '1000-1')
    cid = coll.add_copy('1000-1')
    coll.sql('UPDATE copy_figure SET missing=0 WHERE copy_id=?', (cid,))
    coll.sql('UPDATE copy_part SET missing=0,damaged=0,checked=1 WHERE copy_id=?', (cid,))
    if state == 'missing':
        coll.sql('UPDATE copy_part SET missing=1,damaged=1 WHERE id=(SELECT id FROM copy_part WHERE copy_id=? AND copy_figure_id IS NULL AND is_spare=0 ORDER BY id LIMIT 1)', (cid,))
    elif state == 'unchecked':
        coll.sql('UPDATE copy_part SET checked=0 WHERE copy_id=?', (cid,))
    elif state == 'empty':
        clear_lines(coll, cid)
    d = detail(read, keep, copy_id=cid)
    assert d['progress']['known'] == (state not in ('unchecked', 'empty'))
    assert d['progress']['can_take'] is None                                # the loose stock that covers a gap is the Matcher's (M.8e)
    if state == 'missing':
        assert any(r['deficit'] == 2 for r in d['consists'])
    else:
        assert not any(r['deficit'] for r in d['consists'])
    soup = item_page(client, keep, copy=cid)
    progress = soup.select_one('[aria-label="Copy progress"]')
    assert 'primary' in progress.select_one('a.button')['class']
    assert not soup.select_one('[data-module=consists]>.actions a')
    if state in ('unchecked', 'empty'):
        assert progress.h3.get_text() == 'Parts not checked'
        assert not progress.select_one('.bc-progress-subline')
        assert 'parts present' not in progress.get_text() and 'all 0' not in progress.get_text()
    else:
        assert progress.select_one('.bc-progress-subline').get_text() == f"{d['progress']['different']} different parts · all checked"
    if state == 'missing':
        assert progress.h3.get_text() == f"{d['progress']['missing']} parts missing" and 'to order' not in progress.get_text()
        assert soup.select_one('.bc-missing-card') and soup.select_one('[data-bc-present]')
    else:
        assert not soup.select_one('.bc-missing-card')


def test_detail_query_count_is_bounded_with_hundreds_of_lines(coll, read):
    keep = coll.item('sets', '1000-1')
    cid = coll.add_copy('1000-1')
    with read() as db:
        def measured():
            queries = []
            db.set_trace_callback(queries.append)
            try:
                collection.detail(db, keep, copy_id=cid)
            finally:
                db.set_trace_callback(None)
            return len(queries)
        before = measured()
        red = coll.colour('4')
        for part in local_parts(coll, 300):
            coll.db.execute('INSERT INTO copy_part(copy_id,item_id,color_id,quantity) VALUES(?,?,?,1)', (cid, part, red))
        coll.db.commit()
        assert len(collection.detail(db, keep, copy_id=cid)['consists']) > 300
        assert measured() == before


@pytest.mark.parametrize('checked', [0, 1])
def test_consists_text_and_reading_order(coll, client, read, checked):
    keep = coll.item('sets', '1000-1')
    cid = coll.add_copy('1000-1')
    coll.sql('UPDATE copy_part SET missing=1,damaged=1,checked=? WHERE copy_id=? AND copy_figure_id IS NULL AND is_spare=0', (checked, cid))
    d = detail(read, keep, copy_id=cid)
    soup = item_page(client, keep, copy=cid)
    module = soup.select_one('[data-module=consists]')
    progress = module.select_one('[aria-label="Copy progress"]')
    p = d['progress']
    assert p['can_take'] is None
    assert progress.h3.get_text() == f"{p['missing']} parts missing"
    assert progress.select_one('.bc-progress-present').get_text() == f"{p['total'] - p['missing']} of {p['total']} parts present"
    assert progress.select_one('.bc-progress-subline').get_text() == f"{p['different']} different parts · " + ('all checked' if checked else '0 checked')
    assert [n.get_text() for n in progress.select('.bc-progress-stats span')] == [f"{p['missing']} missing"]
    stats = ' '.join(n.get_text() for n in progress.select('.bc-progress-stats span'))
    assert not any(dash in stats for dash in ['-', '−', '–', '—'])
    assert 'checked' not in stats and 'or damaged' not in stats
    assert f"{p['checked']} checked" in module.select_one('.bc-inventory-details').get_text()
    assert not module.select_one('[data-bc-missing] h3')
    assert module.select_one('[data-bc-missing]')['aria-label'] == 'Missing parts'
    cards = module.select('.bc-missing-card')
    gaps = [r for r in d['consists'] if r['deficit'] and not r.get('minifig_no')]
    assert len(cards) == len(gaps) == 2
    for card, part in zip(cards, gaps):
        identity = card.select_one('.bc-missing-identity')
        children = identity.find_all(recursive=False)
        if identity.strong:
            assert [n.name for n in children][:2] == ['strong', 'span']
        else:
            assert children[0]['class'] == ['bc-missing-meta']
        meta = identity.select_one('.bc-missing-meta')
        if meta.select_one('.bc-colour'):
            assert meta.find_all(recursive=False)[0]['class'] == ['bc-colour']
            if part.get('rgb'):
                assert meta.select_one('.bc-colour')['style'] == f"background:#{part['rgb']};color:{part['ink']}"
        assert meta.find_all(recursive=False)[-1]['class'] == ['mono']
        count = card.select_one('.bc-missing-count')
        assert count.get_text().startswith('needs ')
        assert ' missing' in count.get_text() and '−' not in count.get_text()
        assert 'checked' not in count.get_text()
        assert not card.select_one('.bc-loose-stock')                       # no loose stock is read until M.8e
    for part in gaps:
        state = 'checked' if part['checked'] else 'not checked'
        assert state in soup.select_one('.bc-inventory-details').get_text()


@pytest.mark.parametrize('selection', ['wish', 'copyless', 'copy', 'unchecked-copy'])
def test_inventory_summary_requires_recorded_copy_checks(coll, client, read, selection):
    keep = coll.item('sets', '1000-1')
    cid = coll.add_copy('1000-1')
    wish = None
    path = f'/collection/item/{keep}'
    if selection == 'wish':
        wish = coll.add_wish(keep, quantity=1, condition='any')
        coll.sql('UPDATE copy SET archived_at=? WHERE id=?', (STAMP, cid))
        path = f'/collection/wishes/{wish}'
    elif selection == 'copyless':
        coll.sql('UPDATE copy SET archived_at=? WHERE id=?', (STAMP, cid))
    elif selection == 'copy':
        coll.sql('UPDATE copy_part SET missing=0,damaged=0,checked=1 WHERE copy_id=?', (cid,))
    else:
        coll.sql('UPDATE copy_part SET missing=0,damaged=0,checked=0 WHERE copy_id=?', (cid,))
        coll.sql('UPDATE copy_figure SET missing=0 WHERE copy_id=?', (cid,))
    d = detail(read, keep, wish_id=wish)
    module = soup_of(client, path).select_one('[data-module=consists]')
    summary = module.select_one('.bc-inventory-details')
    if selection == 'copy':
        assert summary.summary.get_text() == f"Details · {detail(read, keep, copy_id=cid)['progress']['checked']} checked"
    else:
        assert d['progress']['check_recorded'] is False
        assert summary.summary.get_text() == 'Details · Check state not recorded'
        assert '0 checked' not in summary.get_text()
    assert not summary.select('li, [data-bc-row]')


def test_inventory_lists_every_line_once_keeps_spares_out_and_retains_metadata(coll, client, read):
    """300 lines on one copy, one of them a spare. (Equal lines can no longer be merged: a copy has one line per part, colour and
    figure, so every line is its own and has one context.)"""
    keep = coll.item('sets', '1000-1')
    cid = coll.add_copy('1000-1')
    clear_lines(coll, cid)
    red = coll.colour('4')
    for n, part in enumerate(local_parts(coll, 300)):
        add_line(coll, cid, part, red, 1, missing=1 if n == 0 else 0, damaged=1 if n == 0 else 0, checked=1, spare=1 if n == 0 else 0)
    d = detail(read, keep, copy_id=cid)
    soup = item_page(client, keep, copy=cid)
    module = soup.select_one('[data-module=consists]')
    # 4.8a: the spare line (index 0) is not part of the set list; 299 lines remain, each with its one context.
    assert len(d['consists']) == 299
    assert {len(p['contexts']) for p in d['consists']} == {1}
    assert len(module.select('[data-bc-row]')) == 299
    assert len(module.select('[data-bc-context]')) == 299
    summary = module.select_one('.bc-inventory-details')
    assert '1 spare line · not listed or counted' in summary.get_text()
    assert not summary.select('ul, li')
    assert not module.select_one('.bc-missing-card')
    metadata = module.select_one('.bc-inventory-context').get_text()
    assert 'checked' in metadata and 'spare' not in metadata
    part = d['consists'][0]
    assert not part['spare'] and part['deficit'] == 0
    assert d['progress']['missing'] == 0 and d['progress']['spare_lines'] == 1 and d['progress']['total'] == 299
    assert part['item_no'] in metadata


@pytest.mark.parametrize('checked', [False, True])
def test_shared_figure_parts(coll, client, read, checked):
    keep = coll.item('sets', '1000-1')
    cid = coll.add_copy('1000-1')
    clear_lines(coll, cid)
    brick, red, white = coll.item('parts', '3001'), coll.colour('4'), coll.colour('15')
    figures = [coll.local('minifigure', f'Figure {n}', born_key=f'figure-{n}') for n in range(4)]
    for figure in figures:
        add_line(coll, cid, brick, red, 1, missing=1 if checked else 0, checked=int(checked), figure=add_figure(coll, cid, figure))
    direct = coll.local('part', 'Direct part', born_key='direct-part')
    add_line(coll, cid, direct, red, 3, missing=2 if checked else 0, checked=int(checked))
    add_line(coll, cid, brick, white, 1, missing=1 if checked else 0, checked=int(checked))       # the same part in another colour stays separate
    d = detail(read, keep, copy_id=cid)
    # 4.8a (supersedes the 4.6s counting rule): figure component rows are not set parts. Only the two direct lines remain, and each
    # figure line carries its own parts count.
    parts = [p for p in d['consists'] if p['item_type'] == 'P']
    assert len(parts) == 2
    assert not any(p.get('minifig_no') for p in parts)
    assert d['progress']['total'] == 4
    assert d['progress']['missing'] == (3 if checked else 0)
    assert d['progress']['different'] == 2 and d['progress']['lines'] == 2
    shown = [p for p in d['consists'] if p['item_type'] == 'M']
    assert len(shown) == 4
    assert all(f['parts_lines'] == 1 and f['parts_missing'] == (1 if checked else 0) for f in shown)
    assert coll.db.execute('SELECT count(*) FROM copy_part WHERE copy_figure_id IS NOT NULL').fetchone()[0] == 4
    soup = item_page(client, keep, copy=cid)
    assert len(soup.select('[data-bc-context]')) == 2 + 4
    pills = [a.get_text() for a in soup.select('.bc-figure-status')]
    assert len(pills) == 4
    if checked:
        assert all(t.startswith('1 part missing') for t in pills)
        assert not soup.select('a.bc-figure-status')
        assert {a['href'] for a in soup.select('a.bc-check-figure')} == {f'/workbench/check-parts/{cid}/figure/M/{f}' for f in figures}
    else:
        assert all(t.startswith('Present') for t in pills)
        assert soup.select_one('[aria-label="Copy progress"] h3').get_text() == 'Parts not checked'
        assert not soup.select_one('.bc-progress-present')
        assert not soup.select_one('.bc-missing-card')


@pytest.mark.parametrize('context', ['direct', 'figure', 'whole-figure', 'spare'])
def test_required_card_counts_agree(coll, client, read, context):
    keep = coll.item('sets', '1000-1')
    cid = coll.add_copy('1000-1')
    clear_lines(coll, cid)
    brick, red = coll.item('parts', '3001'), coll.colour('4')
    if context in ('figure', 'whole-figure'):
        figure = add_figure(coll, cid, coll.local('minifigure', 'Bl figure', born_key='bl-figure'), missing=int(context == 'whole-figure'))
        add_line(coll, cid, brick, red, 2, missing=1, checked=1, figure=figure)
    else:
        add_line(coll, cid, brick, red, 2, missing=1, checked=1)
    if context == 'spare':
        add_line(coll, cid, brick, red, 2, missing=1, checked=1, spare=1)
    d = detail(read, keep, copy_id=cid)
    p = d['progress']
    # 4.8a: figure component rows and spares are not set parts.
    expected = int(context in ('direct', 'spare'))
    counted = (2, expected, expected, 1, 1) if expected else (0, 0, 0, 0, 0)
    assert (p['total'], p['missing'], p['different'], p['lines'], p['checked_lines']) == counted
    assert p['can_take'] is None
    required = [r for r in d['consists'] if r['item_type'] == 'P' and not r['spare']]
    assert sum(r['deficit'] for r in required) == p['missing']
    parts = [r for r in d['consists'] if r['item_type'] == 'P']
    assert len(parts) == expected and not any(r['spare'] for r in parts)
    assert p['spare_lines'] == int(context == 'spare')
    soup = item_page(client, keep, copy=cid)
    progress = soup.select_one('[aria-label="Copy progress"]')
    if not expected:
        assert progress.h3.get_text() == 'Parts not checked'
        assert soup.select_one('.bc-tab-count, [data-bc-tab=parts] .bc-tab-count').get_text() == '0'
        return
    assert progress.h3.get_text() == f'{expected} parts missing'
    assert progress.select_one('.bc-progress-subline').get_text() == '1 different parts · all checked'
    assert [s.get_text() for s in progress.select('.bc-progress-stats span')] == [f'{expected} missing']
    part_cards = [c for c in soup.select('[data-bc-inventory-rows] > article') if c.select_one('.bc-missing-count') and 'needs 2' in c.get_text()]
    assert sum('bc-missing-card' in c.get('class', []) for c in part_cards) == expected == len(part_cards)


@pytest.mark.parametrize('missing,stock', [(0, 0), (2, 0), (2, 1), (2, 20)])
def test_inventory_counts_without_coverage(coll, client, read, missing, stock):
    """The progress counts of a copy. What loose stock could cover of the gap (`.bc-coverage`, 'can be taken', 'to order') is M.8e:
    until then the page shows none of it, whatever stock there is."""
    keep = coll.item('sets', '1000-1')
    cid = coll.add_copy('1000-1')
    coll.sql('UPDATE copy_part SET missing=?,damaged=0,checked=1 WHERE copy_id=? AND copy_figure_id IS NULL AND is_spare=0', (missing, cid))
    if stock:
        coll.add_stock('part', coll.item('parts', '3001'), colour=coll.colour('4'), quantity=stock)
    p = detail(read, keep, copy_id=cid)['progress']
    soup = item_page(client, keep, copy=cid)
    assert soup.select_one('[data-bc-tab=parts] .bc-tab-count').get_text() == str(p['total']) == '6'
    assert not soup.select_one('[data-bc-tab=figures] .bc-tab-count')
    assert p['missing'] == missing * 2 and p['can_take'] is None
    assert not soup.select_one('.bc-coverage') and 'can be taken' not in soup.get_text() and 'to order' not in soup.get_text()
    if p['missing']:
        assert soup.select_one('.bc-progress:not(.bc-coverage) .bc-progress-outline')


# ---------- copy chips ----------

@pytest.mark.parametrize('count', [1, 2, 30])
def test_copy_chips(coll, client, count):
    keep = coll.item('sets', '1000-1')
    ids = [coll.add_copy('1000-1') for _ in range(count)]
    soup = item_page(client, keep, copy=ids[0])
    chips = soup.select('.bc-copy-chip')
    assert len(chips) == (count if count > 1 else 0)
    assert 'Choose copy' not in soup.get_text()
    if chips:
        assert [c.get_text() for c in chips] == [f'Set {n}' for n in range(1, count + 1)]
        assert len(soup.select('.bc-copy-chip[aria-current=page]')) == 1
        other = next(c for c in chips if not c.has_attr('aria-current'))
        switched = soup_of(client, other['href'])
        assert switched.select_one('.bc-copy-chip[aria-current=page]')['href'] == other['href']
        assert soup.select_one('[data-bw-open=bc-copies]').get_text() == 'Copy details'


# ---------- the phone layout of the inventory ----------

def add_47f_inventory_parts(coll, copy_id):
    """Reported identities added to a copy's inventory for the layout checks: a long name with a colour label, and a second one."""
    for key, name, colour, quantity in [('7b', 'Tire Smooth Small Dually', coll.colour('0'), 8),
                                        ('3001old', 'Brick 2 x 4 without Cross Support', coll.colour('1051'), 1)]:
        add_line(coll, copy_id, coll.local('part', name, born_key=key), colour, quantity)


def test_inventory_phone_layout_contract(coll, client):
    """The shared row keeps its identity line and unbroken colour labels."""
    fix = css().split('/* 4.7f')[1]
    assert '@media(max-width:1023px)' in fix
    assert '>a:first-of-type { flex:1 0 calc(100% - 68px)' in fix
    assert '.bc-colour { white-space:nowrap;flex-shrink:0' in fix
    assert '.bc-inventory-row-details[open] { flex-basis:100%;min-width:0' in fix
    assert '.bc-missing-card>.bc-inventory-row-details[open] { grid-column:1 / -1' in fix
    keep = coll.item('sets', '1000-1')
    cid = coll.add_copy('1000-1')
    add_47f_inventory_parts(coll, cid)
    soup = item_page(client, keep, copy=cid)
    rows = soup.select('[data-bc-inventory-rows] article.bc-inventory-row[data-bc-row]')
    assert rows
    for row in rows:
        assert 'bc-inventory-row' in row['class']
        assert row.select_one(':scope > a .bc-identity, :scope > a .bc-missing-identity')
        assert not row.select_one(':scope > .bc-inventory-row-details')
        assert soup.select_one('.bc-inventory-context')


def test_phone_identity_width_from_css_and_real_dom(coll, client):
    """CSS/DOM proof: a nonshrinking basis reserves a complete phone identity line. Chromium additionally measures actual rectangles in
    the opt-in geometry test. Use the narrower 310 px content width (20 px page and module insets each)."""
    keep = coll.item('sets', '1000-1')
    cid = coll.add_copy('1000-1')
    add_47f_inventory_parts(coll, cid)
    soup = item_page(client, keep, copy=cid)
    phone = css().split('/* 4.7f')[1].split('@media(max-width:1023px) {')[1]
    basis = re.search(r'>a:first-of-type \{ flex:1 0 calc\(100% - (\d+)px\)', phone)
    assert basis, 'identity must have a nonshrinking basis within the phone media rule'
    reserved_width = 390 - 2 * 20 - 2 * 20 - int(basis[1])
    for name in ['Tire Smooth Small Dually', 'Brick 2 x 4 without Cross Support']:
        identity = next(n for n in soup.select('.bc-inventory-row > a:first-of-type .bc-identity') if name in n.get_text().replace('\xa0', ' '))
        assert reserved_width >= 150, (name, reserved_width)
        chip = identity.select_one('.bc-colour')
        assert chip and chip.get_text(strip=True) in ['Black', 'Pastel Blue']
        assert '.bc-colour { white-space:nowrap;flex-shrink:0;' in phone


# ---------- part facts, names and chips ----------

def test_part_facts_and_quantity(coll, client, read):
    brick, red = coll.item('parts', '3001'), coll.colour('4')
    coll.add_stock('part', brick, colour=red, quantity=3, condition='used', note='Parts inventory scanner event e5f5a61a-bdc7-41eb-a325-18af6d86de13')
    coll.add_stock('part', brick, colour=red, quantity=2, condition='new')
    cid = coll.add_copy('1000-1')
    coll.mark(cid, '3001', '4', missing=1)
    d = detail(read, brick, colour=red)
    soup = item_page(client, brick, colour=red)
    assert [n.get_text() for n in soup.select('[data-module=info] dt')][:4] == ['Condition', 'Damaged', 'Quantity', 'Storage']
    assert soup.select_one('.bc-quantity-pill:not(.bc-condition-pill)').get_text() == '×' + str(sum(r['quantity'] for r in d['instances'])) == '×5'
    assert not soup.select_one('[data-module=matching]')                    # the Matching module is M.8e


def test_matching_note_strips_the_scanner_event_prefix():
    scanner = 'Parts inventory scanner event e5f5a61a-bdc7-41eb-a325-18af6d86de13'
    assert collection.matching_note(scanner + ' · Keep in drawer') == 'Keep in drawer'
    assert collection.matching_note(scanner) == ''
    assert collection.matching_note('Parts inventory scanner event e5f5a61abdc741eba32518af6d86de13a1b2 · Note') == 'Note'
    assert collection.matching_note('Parts inventory scanner event e5f5a61abdc741eba32518af6d86de13a1b2.') == ''
    assert collection.matching_note('Keep in drawer') == 'Keep in drawer'


@pytest.mark.parametrize('rows,expected', [
    ([], 'Nothing to complete'),
    ([(1, False), (1, False)], 'Fits 1 set, completes none'),
    ([(1, True), (1, True)], 'Completes 1 set'),
    ([(1, True), (2, False)], 'Completes 1 set, fits 1 more'),
    ([(1, True), (2, True), (3, False)], 'Completes 2 sets, fits 1 more'),
    ([(1, False), (2, False)], 'Fits 2 sets, completes none'),
])
def test_matching_headline_counts_copies_once(rows, expected):
    matches = [dict(copy_id=copy, completes=complete, target='part') for copy, complete in rows]
    matches.append(dict(copy_id='loose-figure', completes=False, target='stock-part'))
    assert collection.matching_headline(matches) == expected


def test_part_names_display_only_on_detail_and_cards(coll, client, read):
    from brickwork.web.formatting import nowrap_tail, part_name
    name = 'Bracket 1 x 2 - 1 x 2 Inverted'
    expected = 'Bracket 1 x 2 · 1 x 2 Inverted'
    assert nowrap_tail(part_name(name)) == expected
    assert part_name('600-2') == '600-2'
    assert part_name('Plate - Modified') == 'Plate - Modified'
    bracket, red = coll.local('part', name, born_key='bracket'), coll.colour('4')
    coll.add_stock('part', bracket, colour=red, quantity=1)
    keep = coll.item('sets', '1000-1')
    cid = coll.add_copy('1000-1')
    add_line(coll, cid, bracket, red, 2, missing=1, checked=1)
    part = item_page(client, bracket, colour=red)
    assert part.h1.get_text() == expected
    sets = item_page(client, keep, copy=cid)
    assert expected in [n.get_text() for n in sets.select('.bc-missing-identity strong')]
    # Lists keep the original raw record for search and editing; JS formats its label.
    assert name in client.get('/collection/P').get_data(as_text=True)
    with read() as db:
        assert db.execute('SELECT name FROM item WHERE id=?', (bracket,)).fetchone()[0] == name


def test_colour_chooser_uses_readable_shared_chip(coll, client):
    brick = coll.item('parts', '3001')
    coll.add_stock('part', brick, colour=coll.colour('0'), quantity=1)
    coll.add_wish(brick, colour=coll.colour('15'), quantity=1)
    soup = item_page(client, brick)
    chips = {n.text: n['style'] for n in soup.select('.bc-colour-chooser .bc-colour')}
    assert chips['Black'] == 'background:#05131D;color:#FAFAF8'
    assert chips['White'] == 'background:#FFFFFF;color:#1A1816'


def test_component_identity_and_unidentified_tile(coll, client):
    figure = coll.local('minifigure', 'Figure', born_key='r2-figure')
    coll.add_stock('minifigure', figure, source='none')
    stock = coll.db.execute('SELECT id FROM stock WHERE item_id=?', (figure,)).fetchone()[0]
    vest, nameless = coll.local('part', 'Minifigure Vest', born_key='r2-vest'), coll.local('part', 'Mystery bit')
    for part in (vest, nameless):
        coll.sql('INSERT INTO stock_part(stock_id,item_id,color_id,quantity) VALUES(?,?,?,1)', (stock, part, coll.colour('0')))
    soup = item_page(client, figure)
    rows = soup.select('.bc-figure-components .bc-row')
    assert len(rows) == 2
    for row in rows:
        identity = row.select_one('.bc-component-name .bc-missing-identity')
        assert identity.strong
        # an identified part shows its number; an unidentified one has none and says so instead
        assert bool(identity.select_one('.bc-missing-meta .mono')) != ('Unidentified' in identity.get_text())
    placeholder = next(row for row in rows if 'Unidentified' in row.get_text())
    assert placeholder.select_one('.bc-picture').get_text(strip=True) == 'No image'
    assert 'Unidentified' in placeholder.select_one('.bc-component-name').get_text()


def test_picture_caption_and_alt_use_display_part_name(app4):
    template = "{% from 'web/toni/brickwork/collection_modules.html' import picture %}{{ picture(row) }}"
    with app4.test_request_context('/'):
        part = BeautifulSoup(app4.jinja_env.from_string(template).render(row={'item_type': 'P', 'item_no': 'p', 'name': 'Brick 1 x 2 - 1 x 2', 'image': 1, 'color_name': 'Red'}), 'html.parser')
        button = part.select_one('button')
        assert button['data-caption'] == 'Brick 1 x 2 · 1 x 2 · Red' and button.img['alt'] == button['data-caption']
        moc = BeautifulSoup(app4.jinja_env.from_string(template).render(row={'item_type': 'S', 'item_no': 's', 'name': 'Set - 1 x 2', 'image': 1}), 'html.parser')
        assert moc.select_one('button')['data-caption'] == 'Set - 1 x 2'


def test_partially_checked_merge_retains_recorded_defects():
    rows = [dict(item_type='P', item_no='part', color_id=11, id=n, quantity=1,
                 missing=1 if n == 0 else None, damaged=1 if n == 0 else None,
                 checked=1 if n == 0 else 0, deficit=2 if n == 0 else 0, can_take=0)
            for n in range(4)]
    group, = workbench.merged_inventory(rows)
    assert group['quantity'] == 4
    assert group['missing'] == group['damaged'] == 1
    assert group['deficit'] == 2
    assert group['missing_recorded'] is False
    assert group['checked'] == 0
    assert len(group['contexts']) == 4


def test_matching_leaves_set_detail_and_edit_panel_holds_instances_and_photos(coll, client):
    keep, brick, red = coll.item('sets', '1000-1'), coll.item('parts', '3001'), coll.colour('4')
    cid = coll.add_copy('1000-1')
    coll.add_stock('part', brick, colour=red, quantity=2)
    coll.add_stock('minifigure', coll.item('minifigs', 'fig-000004'), quantity=1)
    assert not item_page(client, keep, copy=cid).select('[data-module=matching]')
    for path in (f'/collection/item/{keep}?copy={cid}', f'/collection/item/{brick}?colour={red}', f"/collection/item/{coll.item('minifigs', 'fig-000004')}"):
        soup = soup_of(client, path)
        layout = soup.select_one('.bc-detail-layout')
        assert not layout.select('.bc-own-photos') and not [h for h in layout.select('h2') if h.get_text().startswith('Instances')]
        panel = soup.select_one('dialog#bc-edit')
        headings = [h.get_text() for h in panel.select('.bc-edit-section > h3')]
        assert any(h.startswith('Instances') for h in headings) and 'Own photos' in headings
        assert panel.select_one('form[data-bc-action=save]') and panel.select_one('.bc-own-photos form[data-bc-action=photo]')
        assert panel.select_one('.bc-edit-section[data-bc-list] [data-bc-rows]')


# ---------- style and formatter contracts (no database) ----------

def test_collection_style_contract():
    """Confirmed visual rules; geometry is re-measured by the UI reviewer."""
    text = css()

    def rule(selector):
        return re.search(re.escape(selector) + r'\s*\{([^}]+)', text).group(1)
    assert 'display:none' in rule('body:has(#bw-collection[data-bc-collection-list]) .shell-add')
    assert '.bc-heading>.button { display:none' not in text
    assert 'width:89px' in rule('#bw-collection .bc-heading>.button')
    assert 'var(--tw-accent-soft)' in rule('#bw-collection .bc-view-switch button[aria-pressed=true]')
    assert 'border:0' in rule('#bw-collection[data-type=S] .bc-card>.bc-picture')
    assert 'text-decoration:none' in rule('#bw-collection .bc-row a,#bw-collection .bc-card a')
    assert 'outline:2px solid var(--tw-accent)' in rule('#bw-collection .bc-row a:focus-visible,#bw-collection .bc-card a:focus-visible')
    assert 'border-left:.5px solid var(--tw-divider)' in text
    assert not re.search(r'(?:^|[;{])\s*order\s*:', text)
    assert 'display:contents' not in text


def test_info_css_contract():
    text = css()
    assert '.bc-fact dt { color:var(--tw-text-muted)' in text
    assert '.bc-fact dd { font-size:15px;line-height:20px;font-weight:500' in text
    assert '[data-module=info]>p.secondary { font-size:13px;line-height:18px' in text
    assert 'min-width:81px;min-height:44px' in text
    assert '.bc-source-details summary::before' not in text
    assert '.bc-source-details[open]>summary::before' not in text


def test_price_css_contract():
    text = css()
    assert '.bc-price { border-bottom:.5px solid var(--tw-divider)' in text
    assert '.bc-price>.actions>strong { font-size:15px;font-weight:600' in text
    assert '.bc-price-footer { display:flex;justify-content:space-between;align-items:center' in text


def test_navigation_css_contract():
    text = css()
    shell = Path('static/web/toni/shell.css').read_text()
    assert '.header .shell-add { width:44px;min-height:44px;background:transparent;border-color:transparent;color:var(--tw-accent-text)' in shell
    assert '.bc-detail-back { display:flex;align-items:center;gap:2px;min-height:44px;text-decoration:none' in text
    assert 'body:has(.bc-detail-hero) .layout>main { padding-top:0' in text
    # Beat the earlier body:has(#bw-collection) selector (one ID), not just source order.
    assert 'body:has(#bw-collection .bc-detail-hero) .layout>main,' in text
    assert '#bw-collection[data-type=M] .bc-detail-hero { margin-top:0' in text
    assert '.bc-hero-picture { width:100%;aspect-ratio:4/3' in text
    assert '.bc-picture img { display:block;width:100%;height:100%;object-fit:contain' in text
    assert '.bc-external-links a { display:inline-flex;align-items:center;gap:4px;min-height:44px' in text
    assert '.bc-identity>span+span::before { content:" · ";white-space:pre;margin:0' in text


def test_consists_css_contract():
    text = css()
    contracts = {
        '.bc-progress-heading h3': 'font:600 22px/28px var(--tw-font)',
        '.bc-progress-subline': 'font:400 14px/20px var(--tw-font)',
        '.bc-progress-present': 'font:400 12px/16px var(--tw-mono)',
        '.bc-loose-stock': 'font:400 13px var(--tw-mono)',
        '.bc-progress-stats': 'font:400 12px/16px var(--tw-mono)',
        '[data-module=consists] [data-bc-count]': 'font:400 13px/18px var(--tw-font)',
        '.bc-missing-identity strong': 'font:600 15px/20px var(--tw-font)',
        '.bc-missing-meta .bc-colour': 'height:22px',
        '.bc-missing-meta .mono': 'font:400 12px var(--tw-mono)',
        '.bc-missing-count': 'font:500 13px var(--tw-mono)',
        '.bc-missing-card>.bc-picture': 'width:96px;height:96px',
        '[data-bc-present]>summary': 'min-height:56px',
    }
    for selector, declaration in contracts.items():
        rule = text.split('#bw-collection ' + selector + ' {')[-1].split('}')[0]
        assert declaration in rule, selector
    assert not re.search(r'(?:[;{]\s*)order\s*:', text.split('/* 4.6o')[1])
    assert 'display:contents' not in text.split('/* 4.6o')[1]


def test_disclosure_marker_has_standalone_shape_and_open_rotation():
    remaining = Path('static/web/toni/remaining.css').read_text()
    selector = 'html[data-web-ui="toni"] details.kit-disclosure'
    closed = re.search(re.escape(selector + '>summary::before') + r'\{([^}]+)\}', remaining)[1]
    opened = re.search(re.escape(selector + '[open]>summary::before') + r'\{([^}]+)\}', remaining)[1]
    assert 'width:16px;height:16px' in closed
    assert 'background:currentColor' in closed
    assert "mask:url('icons/chevron-right.svg') center/contain no-repeat" in closed
    assert 'transform:rotate(0deg)' in closed and 'transform:rotate(90deg)' in opened
    assert 'gap:var(--tw-s-2)' in remaining                                # 8 px between icon and label
    # An inline SVG fragment without xmlns is not an SVG image when used as a mask.
    root = ET.parse('static/web/toni/icons/chevron-right.svg').getroot()
    assert root.tag == '{http://www.w3.org/2000/svg}svg'
    assert root.attrib['viewBox'] == '0 0 24 24'
    assert root.attrib['stroke-width'] == '1.6'
    assert root.attrib['stroke-linecap'] == root.attrib['stroke-linejoin'] == 'round'
    assert root.find('{http://www.w3.org/2000/svg}path').attrib['d'] == 'M9.5 6l6 6-6 6'
    assert 'summary::before' not in css()


def test_copy_chip_and_identity_css_values():
    text = css()
    assert '.bc-copy-chip { height:36px;min-height:0;padding:0 14px;border-radius:10px;background:var(--tw-surface);color:var(--tw-text-2)' in text
    assert '.bc-copy-chip[aria-current=page] { background:var(--tw-accent-soft);color:var(--tw-accent-text)' in text
    assert '.bc-hero-status { align-items:center;flex-wrap:wrap;gap:8px' in text
    assert '.bc-hero-picture { width:100%;aspect-ratio:4/3' in text
    assert '.bc-detail-hero h1 { font:600 28px/34px var(--tw-font);letter-spacing:-.3px' in text
    assert '.bc-detail-hero { gap:16px;margin:0 0 24px' in text
    assert 'body:has(#bw-collection[data-type=S] .bc-detail-hero) .layout>main { padding-top:16px' in text


def test_copy_chip_resets_toni_link_min_height():
    rule = re.search(r'#bw-collection \.bc-copy-chip \{([^}]*)\}', css()).group(1)
    assert 'height:36px' in rule and 'min-height:0' in rule                # beats toni.css main a min-height
    assert re.search(r'@media\(max-width:767px\) \{ #bw-collection \.bc-copy-chip \{ min-height:44px; \} \}', css())


def test_part_name_digits_are_ascii_in_python_and_js():
    from brickwork.web import formatting
    arabic = '١'                                                        # ARABIC-INDIC DIGIT ONE
    name = f'Brick - {arabic} x 2'
    assert formatting.part_name(name) == name
    assert formatting.part_name('Brick - 1 x 2') == 'Brick · 1 x 2'
    js = Path('static/web/toni/formatting.js').read_text()
    assert '\\d' not in js.split('const nowrapTail')[0] and '(?=[0-9])' in js
