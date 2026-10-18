"""v1.3 figure detail states and shared item-detail regressions."""
from urllib.parse import urlsplit, parse_qs, quote
from pathlib import Path
import os
import sqlite3

from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin, collection
from tests.test_bw_collection import bw, token
from tests.web_fixtures import app, apps, logged_in
from tests.importer.test_importer import legacy
from tests.test_bw_admin import reset_shell_metadata_after_test


def page(client, route='/collection/item/M/bl-figure'):
    response = client.get(route)
    assert response.status_code == 200
    return BeautifulSoup(response.data, 'html.parser')


@pytest.mark.parametrize('state', ['loose-and-sets', 'parts-missing', 'only-loose', 'only-sets', 'unresolved', 'no-picture'])
def test_six_figure_states(app, bw, state):
    kind, number = 'M', 'bl-figure'
    with admin.database(bw) as db, db:
        db.execute("UPDATE copy_minifigs SET missing=0 WHERE minifig_no='bl-figure'")
        db.execute("UPDATE items SET year=2011 WHERE item_type='M' AND item_no='bl-figure'")
        db.execute("INSERT OR REPLACE INTO item_properties VALUES('M','bl-figure','theme','rebrickable','City · Police',NULL,'2026-10-08')")
        image = dict(db.execute('SELECT * FROM item_images LIMIT 1').fetchone())
        image.update(id=None,item_type='M',item_no='bl-figure',color_id=None)
        db.execute('INSERT INTO item_images('+','.join(image)+') VALUES('+','.join('?' for _ in image)+')',tuple(image.values()))
        if state == 'parts-missing':
            db.execute("INSERT INTO copy_parts(copy_id,parent_minifig_type,parent_minifig,item_type,item_no,color_id,quantity,missing,damaged,checked) VALUES('copy','M','bl-figure','P','bl-part',11,1,1,0,1)")
        elif state == 'only-loose':
            db.execute("DELETE FROM copy_minifigs WHERE minifig_no='bl-figure'")
        elif state == 'only-sets':
            db.execute("UPDATE loose_stock SET archived_at='2026-10-01' WHERE id='loose-figure'")
        elif state == 'unresolved':
            kind, number = '?', 'rebrickable:rb-review'
            db.execute("UPDATE items SET name=NULL WHERE item_type='?' AND item_no='rebrickable:rb-review'")
        elif state == 'no-picture':
            db.execute("DELETE FROM item_images WHERE item_type='M' AND item_no='bl-figure'")
    client = logged_in(app)
    soup = page(client, f'/collection/item/{quote(kind,safe="")}/{number}')
    assert [m['data-module'] for m in soup.select('[data-module]')] == ['status','consists','used-in','prices','matching','wanted','info']
    assert not soup.select('.bc-hero-status .bc-quantity-pill')
    assert 'Grouped by place' not in soup.get_text()
    assert 'rebrickable-translated' not in soup.select_one('[data-module=consists]').get_text()
    assert not soup.select('[data-module=consists] .bc-toolbar, [data-module=used-in] .bc-toolbar')
    used = soup.select_one('[data-module=used-in]')
    if state == 'only-loose':
        assert 'Not in any set copy.' in used.get_text()
    elif state != 'unresolved':
        assert used.select_one('.bc-used-identity>.mono').get_text() == 'new-set · Set 1'
        check = used.select_one('a.bc-check-figure')
        assert check['href'] == '/workbench/check-parts/copy/figure/M/bl-figure'
        assert 'Check figure parts' in page(client, check['href']).get_text()
    if state == 'parts-missing':
        assert used.select_one('[data-figure-state=parts-missing]').get_text() == '1 part missing'
        assert 'Set 1 · new-set · missing' in soup.select_one('.bc-component-state').get_text()
    if state == 'unresolved':
        assert soup.h1.get_text().replace('\xa0',' ') == 'Unresolved figure (placeholder)'
        assert 'Parts unknown until the figure is resolved.' in soup.get_text()
        assert used.select_one('.bc-used-identity>.mono').get_text() == 'new-set · Set 1'
        check = used.select_one('a.bc-check-figure')
        assert check['href'] == '/workbench/check-parts/copy/figure/%3F/rebrickable:rb-review'
        assert 'Check figure parts' in page(client, check['href']).get_text()
        assert soup.select_one('[data-module=info] a')['href'] == '/manage/unresolved'
    else:
        assert 'Resolved' in soup.select_one('[data-module=info]').get_text()
        assert soup.select_one('.bc-figure-context').get_text() == 'City · Police · 2011'
        if state != 'no-picture':
            assert soup.select_one('.bc-hero-picture img')
            assert client.get(soup.select_one('.bc-hero-picture img')['src']).status_code == 200
    if state == 'no-picture':
        assert 'No image' in soup.select_one('.bc-hero-picture').get_text()
        assert not soup.select_one('.bc-hero-picture img')
    if os.environ.get('BW_UI12F_CAPTURE'):
        for link in soup.select('link[rel=stylesheet]'):
            css_path = Path(urlsplit(link['href']).path.lstrip('/'))
            style = soup.new_tag('style')
            style.string = css_path.read_text()
            link.replace_with(style)
        for script in soup.select('script'):
            if script.get('src') and ('formatting.js' in script['src'] or 'bw-collection.js' in script['src']):
                src = Path(urlsplit(script['src']).path.lstrip('/'))
                script.attrs.clear()
                script.string = src.read_text()
                soup.body.append(script.extract())
            else:
                script.decompose()
        Path('.snap/12f/fixture-' + state + '.html').write_text(str(soup))
    if state != 'only-sets' and state != 'unresolved':
        assert soup.select_one('[data-bc-photo-file]')


def test_missing_figure_disables_checker(app, bw):
    soup = page(logged_in(app))
    used = soup.select_one('[data-module=used-in]')
    assert used.select_one('[data-figure-state=missing]').get_text() == 'Missing'
    assert used.select_one('button.bc-check-figure[disabled]')
    assert not used.select_one('a.bc-check-figure')


def test_wanted_add_uses_existing_review_confirm_and_undo(app, bw, monkeypatch):
    monkeypatch.setattr('brickwork.web.views.bw_start_worker', lambda: None)
    with sqlite3.connect(bw.with_name('bricklink-catalog.db')) as cat:
        cat.execute('CREATE TABLE items(item_type TEXT,item_no TEXT,name TEXT)')
        cat.execute("INSERT INTO items VALUES('M','bl-figure','Synthetic figure')")
    client = logged_in(app)
    csrf = token(client)
    soup = page(client)
    link = soup.select_one('[data-module=wanted] a')
    target = page(client, link['href'])
    assert target.select_one('input[name=type][checked]')['value'] == 'M'
    assert target.select_one('input[name=where][checked]')['value'] == 'wishlist'
    assert target.select_one('input[name=mode][checked]')['value'] == 'paste'
    assert target.select_one('[data-paste]').get_text() == 'bl-figure'
    review = client.post('/manage/add/review', json=dict(csrf_token=csrf,type='M',where='wishlist',mode='paste',text='bl-figure'))
    assert review.status_code == 200, review.json
    proposal = review.get_json()
    assert len(proposal['items']) == 1
    proposal['items'][0]['decision'] = 'another'
    confirmed = client.post('/manage/add/confirm', json=dict(csrf_token=csrf,token=proposal['token'],items=proposal['items']))
    assert confirmed.status_code == 200, confirmed.json
    soup = page(client)
    wish_link = soup.select_one('[data-module=wanted] a')
    assert 'On the wishlist' in wish_link.get_text()
    with admin.database(bw) as db, db:
        db.execute("UPDATE wishlist SET max_price='11408.95',max_price_currency='EUR' WHERE item_type='M' AND item_no='bl-figure'")
    assert '€11,408.95' in page(client).select_one('[data-module=wanted]').get_text()
    # A later edit of the wish blocks the Undo of the add; it never restores over the edit.
    blocked = client.post('/manage/add/undo', json=dict(csrf_token=csrf,batch=confirmed.json['batch']))
    assert blocked.status_code == 400 and 'undo the later save first' in blocked.get_json()['error']
    assert '€11,408.95' in page(client).select_one('[data-module=wanted]').get_text()
    with admin.database(bw) as db, db:
        db.execute("UPDATE wishlist SET max_price=NULL,max_price_currency=NULL WHERE item_type='M' AND item_no='bl-figure'")
    assert client.post('/manage/add/undo', json=dict(csrf_token=csrf,batch=confirmed.json['batch'])).status_code == 200
    assert 'Not on the wishlist' in page(client).select_one('[data-module=wanted]').get_text()


def test_part_colour_redirect_chooser_and_jump(app, bw):
    client = logged_in(app)
    response = client.get('/collection/item/P/bl-part?stock=loose-part')
    assert response.status_code == 302
    assert parse_qs(urlsplit(response.location).query) == {'stock':['loose-part'],'colour':['11']}
    assert 'Unknown colour' not in page(client, response.location).select_one('.bc-detail-hero').get_text()
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO colors(color_id,name,rgb) VALUES(999,'Another colour','FFFFFF')")
        db.execute("INSERT INTO wishlist(item_type,item_no,color_id,quantity) VALUES('P','bl-part',999,1)")
    soup = page(client, '/collection/item/P/bl-part')
    assert len(soup.select('.bc-colour-chooser a')) == 2
    assert 'Unknown colour' not in soup.select_one('.bc-detail-hero').get_text()
    assert not soup.select('[data-module=prices]')
    result = client.get('/collection/jump?q=bl-part')
    assert result.status_code == 200
    assert all('colour=' in r['url'] for r in result.json['results'] if r['kind']=='part')


def test_shared_rows_and_short_toolbar_threshold(app, bw):
    client = logged_in(app)
    soup = page(client, '/collection/item/P/bl-part?colour=11')
    used = soup.select_one('.bc-used-sets')
    assert used.select_one('.bc-used-identity>.mono').get_text() == 'new-set · Set 1'
    assert 'needs ' in used.get_text() and ' · have ' in used.get_text()
    assert not used.select('sup, .bc-toolbar')
    assert soup.select_one('[data-bc-photo-file]')
    with admin.database(bw) as db, db:
        original = dict(db.execute("SELECT * FROM copies WHERE id='copy'").fetchone())
        for n in range(15):
            copy = dict(original, id=f'copy-{n}')
            db.execute('INSERT INTO copies('+','.join(copy)+') VALUES('+','.join('?' for _ in copy)+')', tuple(copy.values()))
            db.execute("INSERT INTO copy_minifigs(copy_id,item_type,minifig_no,quantity,missing) VALUES(?,'M','bl-figure',1,0)", (copy['id'],))
    used = page(client).select_one('[data-module=used-in]')
    assert used.select_one('.bc-toolbar') and used['data-bc-page-size']=='15'
    assert len(used.select('[data-bc-row]'))==16


def test_figure_detail_queries_do_not_grow_per_component_or_copy(bw):
    with admin.database(bw) as db:
        def measured():
            queries = []
            db.set_trace_callback(queries.append)
            try:
                collection.detail(db, 'M', 'bl-figure')
            finally:
                db.set_trace_callback(None)
            return len(queries)
        before = measured()
        original = dict(db.execute("SELECT * FROM copies WHERE id='copy'").fetchone())
        with db:
            for n in range(20):
                copy = dict(original,id=f'query-copy-{n}')
                db.execute('INSERT INTO copies('+','.join(copy)+') VALUES('+','.join('?' for _ in copy)+')', tuple(copy.values()))
                db.execute("INSERT INTO copy_minifigs(copy_id,item_type,minifig_no,quantity,missing) VALUES(?,'M','bl-figure',1,0)", (copy['id'],))
            for n in range(100):
                db.execute("INSERT INTO items(item_type,item_no,name) VALUES('P',?,?)", (f'component-{n}',f'Component {n}'))
                db.execute("INSERT INTO copy_parts(copy_id,parent_minifig_type,parent_minifig,item_type,item_no,color_id,quantity,missing) VALUES('copy','M','bl-figure','P',?,11,1,1)", (f'component-{n}',))
        assert measured() == before


def test_unresolved_wanted_receipt_undo_and_rollback(app, bw):
    client = logged_in(app)
    csrf = token(client)
    route = '/collection/item/%3F/rebrickable:rb-review'
    soup = page(client, route)
    assert soup.select_one('[data-module=wanted] form[data-bc-action=wish] button').get_text() == 'Add to wishlist'
    saved = client.post('/collection/save/wish', json=dict(csrf_token=csrf,item_no='rebrickable:rb-review'))
    assert saved.status_code == 200, saved.json
    assert 'On the wishlist' in page(client, route).select_one('[data-module=wanted]').get_text()
    duplicate = client.post('/collection/save/wish', json=dict(csrf_token=csrf,item_no='rebrickable:rb-review'))
    assert duplicate.status_code == 400
    event = saved.json['event_id']
    with admin.database(bw) as db:
        assert db.execute('SELECT entity FROM events WHERE id=?',(event,)).fetchone()[0] == 'bw_collection'
    undone = client.post('/collection/save/undo', json=dict(csrf_token=csrf,event_id=event))
    assert undone.status_code == 200
    assert 'Not on the wishlist' in page(client, route).select_one('[data-module=wanted]').get_text()
    with admin.database(bw) as db:
        db.execute("CREATE TRIGGER reject_wish BEFORE INSERT ON events WHEN new.entity='bw_collection' BEGIN SELECT RAISE(ABORT,'receipt failed'); END")
        with pytest.raises(sqlite3.IntegrityError):
            collection.want_placeholder(db, 'rebrickable:rb-review')
        assert db.execute("SELECT count(*) FROM wishlist WHERE item_type='?' AND archived_at IS NULL").fetchone()[0] == 0


@pytest.mark.parametrize('query', ['number=x', 'kind=S', 'number=x&kind=S'])
def test_colour_redirect_drops_path_arguments(app, bw, query):
    client = logged_in(app)
    response = client.get('/collection/item/P/bl-part?stock=loose-part&' + query)
    assert response.status_code == 302
    assert urlsplit(response.location).path == '/collection/item/P/bl-part'
    assert parse_qs(urlsplit(response.location).query) == {'stock':['loose-part'], 'colour':['11']}
    page(client, response.location)


def test_null_colour_chooser_opens_instance(app, bw):
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity) VALUES('unknown-part','P','bl-part',NULL,2)")
    client = logged_in(app)
    soup = page(client, '/collection/item/P/bl-part')
    link = next(a for a in soup.select('.bc-colour-chooser a') if 'Unknown colour' in a.get_text())
    assert parse_qs(urlsplit(link['href']).query) == {'colour':['none']}
    selected = page(client, link['href'])
    assert not selected.select('.bc-colour-chooser')
    assert 'unknown-part' in selected.get_text()
    assert 'loose-part ·' not in selected.get_text()
    for link in selected.select('[data-bc-rows] a[href*="stock=unknown-part"]'):
        assert parse_qs(urlsplit(link['href']).query)['colour'] == ['none']
        assert not page(client, link['href']).select('.bc-colour-chooser')


@pytest.mark.parametrize('source', ['stock', 'copy'])
def test_zero_quantity_colour_is_not_a_choice(app, bw, source):
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO colors(color_id,name) VALUES(999,'Empty colour')")
        if source == 'stock':
            db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity) VALUES('empty','P','bl-part',999,0)")
        elif source == 'copy':
            db.execute("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity) VALUES('copy','P','bl-part',999,0)")
    response = logged_in(app).get('/collection/item/P/bl-part')
    assert response.status_code == 302
    assert parse_qs(urlsplit(response.location).query) == {'colour':['11']}


@pytest.mark.parametrize('query', ['type=X', 'type=X&where=X', 'type=&where='])
def test_add_invalid_initial_radios_fall_back(app, bw, query):
    soup = page(logged_in(app), '/manage/add?' + query)
    assert [r['value'] for r in soup.select('input[name=type][checked]')] == ['S']
    assert [r['value'] for r in soup.select('input[name=where][checked]')] == ['owned']


def test_manual_figure_line_does_not_duplicate_used_copy(app, bw):
    with admin.database(bw) as db, db:
        # Shape retained by the importer for a manual part-to-figure decision.
        db.execute("INSERT INTO copy_parts(copy_id,parent_minifig_type,parent_minifig,item_type,item_no,color_id,quantity,missing,damaged,checked) VALUES('copy',NULL,NULL,'M','bl-figure',NULL,1,0,0,1)")
        detail = collection.detail(db, 'M', 'bl-figure')
        assert len(detail['used_in']) == 1
        assert detail['set_count'] == 1
        assert detail['used_in'][0]['missing'] == 1  # canonical figure state wins
    soup = page(logged_in(app))
    assert len(soup.select('[data-module=used-in] [data-bc-row]')) == 1


@pytest.mark.parametrize('partial', [False, True])
def test_headline_counts_each_loose_figure(app, bw, partial):
    with admin.database(bw) as db, db:
        db.execute("UPDATE loose_minifig_parts SET missing=1,damaged=0,spare=0 WHERE stock_id='loose-figure'")
        stock = dict(db.execute("SELECT * FROM loose_stock WHERE id='loose-figure'").fetchone())
        stock['id'] = 'loose-figure-2'
        db.execute('INSERT INTO loose_stock('+','.join(stock)+') VALUES('+','.join('?' for _ in stock)+')', tuple(stock.values()))
        part = dict(db.execute("SELECT * FROM loose_minifig_parts WHERE stock_id='loose-figure'").fetchone())
        part['stock_id'] = stock['id']
        db.execute('INSERT INTO loose_minifig_parts('+','.join(part)+') VALUES('+','.join('?' for _ in part)+')', tuple(part.values()))
        if partial:
            db.execute("INSERT INTO items(item_type,item_no) VALUES('P','unavailable-part')")
            db.execute("INSERT INTO loose_minifig_parts(stock_id,item_type,item_no,color_id,quantity,missing,spare) VALUES('loose-figure-2','P','unavailable-part',11,1,1,0)")
        for selected in ['loose-figure', 'loose-figure-2']:
            detail = collection.detail(db, 'M', 'bl-figure', stock_id=selected)
            assert detail['figure_matching_headline'].endswith('completes 1 figure' if partial else 'completes 2 figures')
    assert ('completes 1 figure' if partial else 'completes 2 figures') in page(logged_in(app)).get_text()


@pytest.mark.parametrize('kind', ['S', 'P', 'M', '?'])
def test_unresolved_price_message_matches_item_type(app, bw, kind):
    with admin.database(bw) as db, db:
        db.execute('INSERT INTO items(item_type,item_no) VALUES(?,?)', (kind, 'unresolved-price'))
        db.execute("INSERT INTO id_match(source,kind,source_id,item_type,item_no,status,evidence_json) VALUES('rebrickable',?, ?,?,?,'to_check','{}')", ('part' if kind=='P' else 'set', 'unresolved-price-'+kind, kind, 'unresolved-price'))
    prices = page(logged_in(app), f'/collection/item/{quote(kind,safe="")}/unresolved-price?colour=none').select_one('[data-module=prices]').get_text()
    assert ('No price until the figure is resolved.' in prices) == (kind in ('M', '?'))
    if kind not in ('M', '?'):
        assert 'No sales and no listings recorded.' in prices


def test_only_zero_quantity_colour_does_not_redirect(app, bw):
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO items(item_type,item_no) VALUES('P','empty-part')")
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity) VALUES('empty','P','empty-part',11,0)")
    response = logged_in(app).get('/collection/item/P/empty-part')
    assert response.status_code == 200


def test_single_null_colour_redirect_uses_sentinel(app, bw):
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO items(item_type,item_no) VALUES('P','unknown-part')")
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity) VALUES('unknown','P','unknown-part',1)")
    client = logged_in(app)
    response = client.get('/collection/item/P/unknown-part')
    assert response.status_code == 302
    assert parse_qs(urlsplit(response.location).query) == {'colour':['none']}
    assert not page(client, response.location).select('.bc-colour-chooser')
