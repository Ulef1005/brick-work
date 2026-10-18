"""Run 5 Collection claims, verified against migrated data and kit DOM."""
import json
from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin, collection
from brickwork.core.list_records import payload
from tests.test_bw_collection import bw, legacy, reset_shell_metadata_after_test
from tests.web_fixtures import app, logged_in
from tests.web_fixtures import apps


def unpack(rows):
    data = json.loads(payload(rows))
    return [{data['fields'][int(k)]: v for k, v in r.items()} for r in data['rows']]


def test_missing_records_separate_figures_and_parts(bw):
    with admin.database(bw) as db:
        rows = collection.listing(db, 'S')
        packed = unpack(rows)
        for row, record in zip(rows, packed):
            expected = db.execute('''SELECT sum(coalesce(p.missing,0)) FROM copy_parts p
                JOIN copies c ON c.id=p.copy_id WHERE c.set_no=? AND c.archived_at IS NULL
                AND coalesce(p.spare,0)=0 AND p.parent_minifig IS NULL''', (row['item_no'],)).fetchone()[0] or 0
            figures = db.execute('''SELECT sum(coalesce(m.missing,0)) FROM copy_minifigs m
                JOIN copies c ON c.id=m.copy_id WHERE c.set_no=? AND c.archived_at IS NULL''', (row['item_no'],)).fetchone()[0] or 0
            assert record.get('missing_parts', 0) == expected
            assert record.get('missing_figures', 0) == figures


def test_instruction_pdf_records_share_detail_identity(app, bw):
    with admin.database(bw) as db, db:
        # Existing migrated set identity; an instruction and its set share a number.
        assert not unpack(collection.listing(db, 'I'))[0].get('pdf_available')
        db.execute("INSERT INTO instruction_files(item_type,set_no,path,label) VALUES('S','new-set','data/instructions/booklet.pdf','Booklet')")
        assert unpack(collection.listing(db, 'I'))[0]['pdf_available'] is True
    response = logged_in(app).get('/collection/I')
    soup = BeautifulSoup(response.data, 'html.parser')
    assert soup.select_one('[data-web-ui=toni]')
    data = json.loads(soup.select_one('[data-bc-records]').string)
    assert any(r.get(str(data['fields'].index('pdf_available'))) for r in data['rows'])


@pytest.mark.parametrize('kind', ['S', 'I'])
def test_extended_list_queries_constant_at_300_rows(bw, kind):
    with admin.database(bw) as db, db:
        def cost():
            statements = []
            db.set_trace_callback(statements.append)
            try:
                payload(collection.listing(db, kind))
            finally:
                db.set_trace_callback(None)
            assert not any(s.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for s in statements)
            return len(statements)
        before = cost()
        for i in range(300):
            number = f'cost-47d-{i}'
            db.execute('INSERT INTO items(item_type,item_no,name) VALUES(?,?,?)', (kind, number, number))
            if kind == 'S':
                db.execute("INSERT INTO copies(id,item_type,set_no) VALUES(?,'S',?)", (number, number))
            else:
                db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity) VALUES(?,'I',?,1)", (number, number))
        assert cost() == before


def test_set_controls_match_1c_structure(app, bw):
    soup = BeautifulSoup(logged_in(app).get('/collection/sets').data, 'html.parser')
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
    from pathlib import Path
    css = Path('static/web/toni/bw-collection.css').read_text()
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


def test_result_noun_depends_on_list_page_marker(app, bw):
    client = logged_in(app)
    page = BeautifulSoup(client.get('/collection/sets').data, 'html.parser')
    assert page.select_one('#bw-collection').has_attr('data-bc-collection-list')
    with admin.database(bw) as db:
        number = collection.listing(db, 'S')[0]['item_no']
    detail = BeautifulSoup(client.get('/collection/item/S/' + number).data, 'html.parser')
    assert not detail.select_one('#bw-collection').has_attr('data-bc-collection-list')
    js = open('static/web/toni/bw-collection.js').read()
    assert "root.dataset.bcCollectionList!==undefined?root.dataset.type:''" in js
