"""Run 5 Collection claims, verified against 4.0 data and kit DOM (M.8b, issue #110)."""
import json
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from brickwork.core import collection
from brickwork.core.list_records import payload
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401  (fixtures)
from tests.app4_bulk import bulk_owned

ROOT = Path(__file__).resolve().parents[1]


def unpack(rows):
    data = json.loads(payload(rows))
    return [{data['fields'][int(k)]: v for k, v in r.items()} for r in data['rows']]


def test_missing_records_separate_figures_and_parts(world, coll, read):
    # Beside the world's missing red 3001: a missing figure, a missing spare and a missing retired line, which are not counted as parts.
    coll.mark_figure(world.copy_b, 'fig-000004', missing=1)
    coll.sql('UPDATE copy_part SET missing=1 WHERE is_spare=1')
    coll.sql("UPDATE copy_part SET missing=1 WHERE copy_id=? AND copy_figure_id IS NULL AND is_spare=0 AND item_id=?", (world.copy_b, world.plate))
    coll.retire_line(world.copy_b, '3023', '15')
    with read() as db:
        rows = collection.listing(db, 'S')
        packed = unpack(rows)
        keep = packed[[r['item_id'] for r in rows].index(world.keep)]
        assert (keep['missing_parts'], keep['missing_figures']) == (1, 1)
        assert rows and any(r.get('missing_parts') for r in packed)
        for row, record in zip(rows, packed):
            expected = db.execute('''SELECT sum(p.missing) FROM copy_part p JOIN copy c ON c.id=p.copy_id WHERE c.item_id=? AND c.archived_at IS NULL
                AND p.is_spare=0 AND p.copy_figure_id IS NULL AND p.retired_at IS NULL''', (row['item_id'],)).fetchone()[0] or 0
            figures = db.execute('''SELECT sum(f.missing) FROM copy_figure f JOIN copy c ON c.id=f.copy_id WHERE c.item_id=? AND c.archived_at IS NULL
                AND f.retired_at IS NULL''', (row['item_id'],)).fetchone()[0] or 0
            assert record.get('missing_parts', 0) == expected
            assert record.get('missing_figures', 0) == figures


def test_instruction_pdf_records_share_detail_identity(coll, client):
    # An instructions item is a set's booklet: it shares the files attached to the set of the same number.
    booklet = coll.local('instructions', 'Syn Castle Keep booklet', born_key='1000-1')
    coll.add_stock('instructions', booklet, quantity=1)
    assert not unpack(collection.listing(coll.db, 'I'))[0].get('pdf_available')
    coll.sql("INSERT INTO instruction_file(item_id,path,label,added_at) VALUES(?,'data/instructions/booklet.pdf','Booklet','2026-10-26T12:00:00.000Z')",
             (coll.project(coll.item('sets', '1000-1')),))
    assert unpack(collection.listing(coll.db, 'I'))[0]['pdf_available'] is True
    response = client.get('/collection/I')
    soup = BeautifulSoup(response.data, 'html.parser')
    assert soup.select_one('[data-web-ui=toni]')
    data = json.loads(soup.select_one('[data-bc-records]').string)
    assert any(r.get(str(data['fields'].index('pdf_available'))) for r in data['rows'])


@pytest.mark.parametrize('kind', ['set', 'instructions'])
def test_extended_list_queries_constant_at_300_rows(coll, kind):
    letter = {'set': 'S', 'instructions': 'I'}[kind]
    bulk_owned(coll, kind, 2, prefix='seed')
    db = coll.db

    def cost():
        statements = []
        db.set_trace_callback(statements.append)
        try:
            payload(collection.listing(db, letter))
        finally:
            db.set_trace_callback(None)
        assert not any(s.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for s in statements)
        return len(statements)
    before = cost()
    bulk_owned(coll, kind, 300, prefix='cost-47d', start=10)
    assert len(collection.listing(db, letter)) == 302
    assert cost() == before


def test_set_controls_match_1c_structure(world, client):
    soup = BeautifulSoup(client.get('/collection/sets').data, 'html.parser')
    root = soup.select_one('#bw-collection')
    assert root.select_one('[data-bc-search]')['placeholder'] == 'Number or name'
    assert root.select_one('.bc-search .icon')
    summary = root.select_one('[data-bc-missing-summary]')
    strip = root.select_one('.bc-status-strip')
    assert summary.find_next_sibling() == strip
    panel = root.select_one('[data-bc-panel]')
    assert 'bc-collection-sheet' in panel['class']
    assert panel.select_one('.bc-sheet-handle')
    assert [b.get_text(strip=True) for b in panel.select('.bc-filter-pair [data-bc-pick]')] == ['New', 'Used', 'One', 'Several']
    assert panel.select_one('[data-bc-pick=duplicates][data-value=false]')
    assert len(root.select('[data-bc-filter=duplicates]')) == 1
    assert len(root.select('[data-bc-filter=theme]')) == 1
    theme = panel.select_one('.bc-theme-row')
    assert theme.find_previous_sibling().select_one('[data-bc-pick=has]')
    assert not theme.find_parent('details')
    assert panel.select_one('.bc-storage-row [data-bc-filter=storage]') and not theme.find_parent('details')
    assert panel.find_all(recursive=False)[-1].has_attr('data-bc-apply')
    assert not panel.select_one('[data-bc-filters]')
    assert panel.select_one('[data-bc-reset]').get_text() == 'Reset'
    sort = root.select_one('[data-bc-sort-panel]')
    assert 'bc-collection-sheet' in sort['class']
    assert sort.select_one('[data-bc-sort-pick=used_price]').get_text(strip=True).startswith('Used price')
    assert [o['value'] for o in sort.select('[data-bc-sort] option')] == ['number','name','year','missing','used_price']
    assert root.select_one('[data-bc-sheet-scrim]')


def test_47d_css_dimensions_and_scope():
    css = (ROOT / 'static/web/toni/bw-collection.css').read_text()
    assert '.bc-cards[data-view=list] .bc-card { width:100%;align-self:stretch;' in css
    assert 'grid-template-columns:minmax(0,1fr) 313px' in css
    # 1440 viewport - 232 rail - 64 page inset - 313 dock - 32 gap - 60 grid gaps.
    assert (1440-232-64-313-32-60)/4 == 184.75
    assert '#bw-collection[data-type=M] .bc-cards[data-view=grid] .bc-stock-count { display:none; }' in css
    assert '.bc-filter-apply { height:56px;min-height:56px;' in css
    assert '.bc-sheet-handle { display:block;flex:none;width:36px;height:4px;' in css
    assert 'inset:auto 0 0;width:100%;margin:0;' in css


def test_set_duplicates_count_owned_quantity_not_storage_lines():
    records = unpack([dict(item_type='S', item_no='one', quantity=1, instances=[{}]),
                      dict(item_type='S', item_no='many', quantity=3, instances=[{}])])
    assert not records[0].get('duplicates')
    assert records[1]['duplicates'] is True


def test_wish_quantity_is_not_a_copies_duplicate():
    records = unpack([dict(item_type='S', item_no='wish', entity='wish', id='w', quantity=2, instances=[]),
                      dict(item_type='S', item_no='owned', quantity=2, instances=[{}])])
    assert not records[0].get('duplicates')
    assert records[1]['duplicates'] is True


def test_result_noun_depends_on_list_page_marker(world, read, client):
    page = BeautifulSoup(client.get('/collection/sets').data, 'html.parser')
    assert page.select_one('#bw-collection').has_attr('data-bc-collection-list')
    with read() as db:
        item = collection.listing(db, 'S')[0]['item_id']
    detail = BeautifulSoup(client.get(f'/collection/item/{item}').data, 'html.parser')
    assert not detail.select_one('#bw-collection').has_attr('data-bc-collection-list')
    js = (ROOT / 'static/web/toni/bw-collection.js').read_text()
    assert "root.dataset.bcCollectionList!==undefined?root.dataset.type:''" in js
