"""#55: invented figure places, fresh used quotes, offline readers."""
from decimal import Decimal
from pathlib import Path
import subprocess

from bs4 import BeautifulSoup
import pytest

from brickwork.core import figures, partout
from brickwork.core.sources.base import now
from tests.api2 import v2, call, validate  # noqa: F401
from tests.app4 import STAMP, app4, client, coll, pair, read, world  # noqa: F401


@pytest.fixture
def figure(coll):
    item = coll.local('minifigure', 'Alex the Knight', born_key='syn-55-knight')
    parts = [coll.local('part', 'Sam component '+str(n), born_key='syn-55-part-'+str(n)) for n in range(4)]
    red = coll.colour('4')
    stock = coll.add_stock('minifigure', item, source='none')
    for n, part in enumerate(parts):
        coll.sql('INSERT INTO stock_part(stock_id,item_id,color_id,quantity,missing,checked) VALUES(?,?,?,1,?,1)', (stock, part, red, int(n==3)))
        coll.price(part, '2.00' if n<3 else '3.50', colour=red, region='eu', currency='EUR', observed=now().isoformat())
    coll.price(item, '18.00', region='eu', currency='EUR', observed=now().isoformat())
    for key, value in [('bricklink_currency','EUR'),('bricklink_region','eu'),('repair_shipping','0.30'),('repair_fees','0.20'),('repair_min_order','0')]:
        coll.setting(key,value)
    return item, parts, red, stock


def result(read, figure):
    with read() as db:
        return figures.compare(db, figure[0])[0]


def test_complete_it_and_cost_breakdown(figure, read):
    r=result(read,figure)
    assert (r['complete'],r['parts_value'],r['to_complete'],r['gain'],r['shipping_fees'])==('18.00','6.00','4.00','8.00','0.50')
    assert r['recommendation']=='Complete it' and r['priced']==4 and not r['needs_evidence']


@pytest.mark.parametrize('complete,cost,expected,gain', [('6.50','3.00','Keep as is','-3.00'),('12.00','11.00','Part out','-5.50')])
def test_other_recommendations(figure,coll,read,complete,cost,expected,gain):
    coll.price(figure[0],complete,region='eu',observed=now().isoformat())
    coll.price(figure[1][-1],cost,colour=figure[2],region='eu',observed=now().isoformat())
    r=result(read,figure)
    assert r['recommendation']==expected and r['gain']==gain


def test_coverage_four_parts_and_missing_quote(figure,coll,read):
    coll.sql('DELETE FROM price_current WHERE item_id=?',(figure[1][0],))
    coll.sql('DELETE FROM price_observation WHERE item_id=?',(figure[1][0],))
    r=result(read,figure)
    assert (r['priced'],r['lines'],r['parts_value'],r['recommendation'])==(3,4,None,None)
    assert r['needs_evidence'] and r['to_complete']=='4.00'
    coll.sql('DELETE FROM price_current WHERE item_id=?',(figure[1][-1],))
    coll.sql('DELETE FROM price_observation WHERE item_id=?',(figure[1][-1],))
    assert result(read,figure)['to_complete'] is None


@pytest.mark.parametrize('change', ['currency','stale','complete'])
def test_bad_quote_is_evidence(figure,coll,read,change):
    target=figure[0] if change=='complete' else figure[1][0]
    coll.sql('UPDATE price_observation SET '+("currency='USD'" if change=='currency' else "observed_at='2020-01-01T00:00:00Z'")+ ' WHERE item_id=?',(target,))
    if change=='currency':
        coll.sql("UPDATE price_current SET currency='USD' WHERE item_id=?",(target,))
    r=result(read,figure)
    assert r['needs_evidence'] and r['recommendation'] is None


def test_whole_figure(figure,coll,read,client):
    coll.sql('UPDATE stock_part SET missing=0 WHERE stock_id=?',(figure[3],))
    r=result(read,figure)
    assert r['to_complete']=='0.00' and r['shipping_fees']=='0.00' and r['recommendation'] is None
    page=BeautifulSoup(client.get(f'/collection/item/{figure[0]}').data,'html.parser')
    card=page.select_one('[data-module=figure-comparison]')
    assert card and 'To complete' not in card.get_text() and 'Complete it' not in card.get_text()
    assert 'Every figure is complete.' in client.get('/planning/complete-sets?tab=figures').text


def add_place(coll,figure,n):
    copy=f'syn55-copy-{n}'
    set_id=coll.project(coll.item('sets','1000-1'))
    coll.sql("INSERT INTO copy(id,item_id,inventory_source,inventory_digest,created_at,updated_at) VALUES(?,?,'migrated','d',?,?)",(copy,set_id,STAMP,STAMP))
    coll.sql("INSERT INTO copy_figure(copy_id,item_id,inventory_source,quantity,updated_at) VALUES(?,?,'none',1,?)",(copy,figure[0],STAMP))
    fid=coll.db.execute('SELECT id FROM copy_figure WHERE copy_id=?',(copy,)).fetchone()[0]
    for n,part in enumerate(figure[1]):
        coll.sql('INSERT INTO copy_part(copy_id,copy_figure_id,item_id,color_id,quantity,missing) VALUES(?,?,?,?,1,?)',(copy,fid,part,figure[2],int(n==3)))
    return copy,fid


def test_several_places_card_switcher_and_set_link(figure,coll,read,client):
    copy,fid=add_place(coll,figure,1)
    with read() as db: rows=figures.compare(db,figure[0])
    assert len(rows)==2 and rows[0]['stock_id']==figure[3] and rows[1]['copy_id']==copy
    page=BeautifulSoup(client.get(f'/collection/item/{figure[0]}?figure={fid}').data,'html.parser')
    card=page.select_one('[data-module=figure-comparison]')
    assert 'In 1000-1 Set 1' in card.get_text() and card.select_one('.bf-copy-picker a[aria-current]')['href'].endswith(f'place=figure:{fid}')
    page=BeautifulSoup(client.get(f'/collection/item/{coll.item("sets","1000-1")}?copy={copy}').data,'html.parser')
    assert page.select_one(f'a[href$="figure={fid}"]')


def test_list_controls_paging_empty_and_placeholder(figure,coll,client):
    base='/planning/complete-sets?tab=figures'
    page=BeautifulSoup(client.get(base).data,'html.parser')
    assert page.select_one('#bw-figures') and 'Complete it' in page.get_text()
    main=page.select_one('#bw-figures').get_text()      # the shell's navigation names Order missing parts since #412; the figures list itself must not
    assert all(s not in main for s in ('Export selected','Order missing parts','Print'))
    for query in ('q=zzz','where=sets','recommendation=Part+out','theme=zzz','storage=zzz'):
        assert 'No figures match these filters.' in client.get(base+'&'+query).text
    for n in range(16):
        sid=coll.add_stock('minifigure',figure[0],source='none')
        coll.sql('INSERT INTO stock_part(stock_id,item_id,color_id,quantity,missing) VALUES(?,?,?,1,1)',(sid,figure[1][0],figure[2]))
    page=BeautifulSoup(client.get(base+'&sort=cost').data,'html.parser')
    assert len(page.select('.bf-row'))==15 and page.select_one('.bc-pager')
    assert len(BeautifulSoup(client.get(base+'&page=2').data,'html.parser').select('.bf-row'))==2
    unknown=coll.local('minifigure','Sam unresolved')
    coll.add_stock('minifigure',unknown,source='none')
    assert 'data-module="figure-comparison"' not in client.get(f'/collection/item/{unknown}').text


def test_empty(client):
    page=client.get('/planning/complete-sets?tab=figures')
    assert page.status_code==200 and 'No figures with part data' in page.text


def test_batch_query_count(figure,coll,read):
    with read() as db:
        statements=[]; db.set_trace_callback(statements.append)
        figures.compare(db); small=len(statements)
    for n in range(210):
        sid=coll.add_stock('minifigure',figure[0],source='none')
        coll.sql('INSERT INTO stock_part(stock_id,item_id,color_id,quantity,missing) VALUES(?,?,?,1,1)',(sid,figure[1][0],figure[2]))
    with read() as db:
        statements=[]; db.set_trace_callback(statements.append)
        rows=figures.compare(db)
    assert len(rows)==211 and len(statements)==small


def test_margin_shared_with_sets():
    assert partout.advantage(Decimal('110'),Decimal('100'))
    assert not partout.advantage(Decimal('104.99'),Decimal('100'))
    assert not partout.advantage(Decimal('8'),Decimal('4'))


def test_runtime():
    from tests import rendered
    node=rendered.need_node()
    run=subprocess.run([node,str(Path(__file__).with_name('toni_bw_figures_runtime.cjs'))],capture_output=True,text=True)
    assert run.returncode==0,run.stdout+run.stderr


def test_api_and_mcp_share_comparison(figure, v2, app4, read):
    import json
    from brickwork.core.mcp import Adapter
    from brickwork.core.mcp.client import InProcessClient
    from tests.api2 import BOOTSTRAP
    response=call(v2,f'/minifigures/{figure[0]}')
    validate(response,'get_minifigures_by_id')
    expected=response.json['data']['figure_comparisons']
    assert expected[0]['gain']=='8.00' and expected[0]['parts'][-1]['quote']['price']=='3.50'
    other=call(v2,f'/items/{figure[0]}/detail')
    validate(other,'get_items_by_id_detail')
    assert other.json['data']['figure_comparisons']==expected
    adapter=Adapter(InProcessClient(app4,BOOTSTRAP))
    result=adapter.call_tool('get_minifigure_detail',dict(kind='minifigure',no='syn-55-knight'))
    assert json.loads(result.content[0].text)['figure_comparisons']==expected


def test_loose_stock_minimum_order_damage_and_scope(figure,coll,read):
    coll.add_stock('part',figure[1][-1],colour=figure[2],quantity=1)
    coll.setting('repair_use_loose_stock','1')
    coll.setting('repair_min_order','2.00')
    r=result(read,figure)
    assert r['to_complete']=='2.50' and r['minimum_order_extra']=='2.00' and r['parts'][-1]['stock_used']==1
    coll.sql('UPDATE stock_part SET damaged=1 WHERE stock_id=? AND missing=1',(figure[3],))
    r=result(read,figure)
    assert r['missing_count']==1
    with read() as db:
        assert figures.compare(db,figure[0])==[r for r in figures.compare(db) if r['item_id']==figure[0]]


def test_evidence_card_budget_and_error(figure,coll,client,app4,monkeypatch):
    coll.sql('DELETE FROM price_current WHERE item_id=?',(figure[1][0],))
    app4.jinja_env.globals['bw_key_missing']=lambda source:False
    monkeypatch.setenv('BW_BRICKLINK_DAILY_BUDGET','1')
    page=BeautifulSoup(client.get('/planning/complete-sets?tab=figures&recommendation=Needs+evidence').data,'html.parser')
    assert '3 of 4 parts priced' in page.get_text() and 'prices not fetched' in page.get_text()
    assert page.select_one('[data-bf-fetch]').has_attr('disabled')
    card=BeautifulSoup(client.get(f'/collection/item/{figure[0]}').data,'html.parser').select_one('[data-module=figure-comparison]')
    assert card.select_one('.bf-no-sales') and 'Needs evidence' in card.get_text() and not card.select_one('.bf-pill')
    monkeypatch.setattr(figures,'compare',lambda *a,**k: (_ for _ in ()).throw(ValueError('synthetic database failure')))
    page=BeautifulSoup(client.get('/planning/complete-sets?tab=figures').data,'html.parser')
    assert page.select_one('[role=alert]') and 'Retry' in page.get_text()


def test_edge_candidates_reach_their_states(tmp_path,app4,client,monkeypatch):
    from contextlib import closing
    from brickwork.demo import dataset, gate_edge, clock
    from brickwork.core.connect import connect
    folder=tmp_path/'edge';folder.mkdir();path=folder/'brickwork.db'
    dataset.build(path,layer=gate_edge.layer(pictures=False))
    monkeypatch.setenv('BW_DB_PATH',str(path))
    patched=clock.freeze_clock()
    try:
        with closing(connect(path)) as db:
            rows=figures.compare(db)
            knight=next(r for r in rows if r['name'].startswith('Knight,') and r['number_text']=='syn55-knight')
            assert (knight['complete'],knight['parts_value'],knight['to_complete'],knight['gain'])==('18.00','6.00','4.00','8.00')
        for key,text in [('knight','Complete it'),('whole','Complete or part out'),('forestman','3 of 4 parts priced')]:
            response=client.get('/collection/item/minifigure/syn55-'+key,follow_redirects=True)
            assert response.status_code==200 and text in response.text
        response=client.get('/planning/complete-sets?tab=figures&theme=Complete+figures')
        assert response.status_code==200 and 'Every figure is complete.' in response.text
        assert 'Needs evidence' in client.get('/planning/complete-sets?tab=figures&recommendation=Needs+evidence').text
    finally:
        clock.thaw_clock(patched)


def test_query_choices_sort_chips_and_group_order(figure,coll,read,app4):
    from brickwork.web.figure_views import listing
    from werkzeug.datastructures import MultiDict
    second=coll.local('minifigure','Sam the Chef',born_key='aaa55-chef-test')
    sid=coll.add_stock('minifigure',second,source='none')
    for n,part in enumerate(figure[1]):
        coll.sql('INSERT INTO stock_part(stock_id,item_id,color_id,quantity,missing) VALUES(?,?,?,1,?)',(sid,part,figure[2],int(n==3)))
    coll.price(second,'2.00',region='eu',observed=now().isoformat())
    add_place(coll,figure,1)
    with read() as db: rows=figures.compare(db)
    with app4.test_request_context():
        gain=listing(rows,MultiDict())
        assert gain['rows'][0]['name']=='Alex the Knight'
        assert gain['rows'][-1]['where']=='sets'
        assert listing(rows,MultiDict({'sort':'name'}))['rows'][0]['name']=='Alex the Knight'
        assert listing(rows,MultiDict({'sort':'number'}))['rows'][0]['name']=='Sam the Chef'
        assert listing(rows,MultiDict({'sort':'parts'}))['rows'][0]['where']=='loose'
        page=listing(rows,MultiDict({'q':'Knight','where':'loose','sort':'cost'}))
        assert len(page['rows'])==1 and 'q=Knight' in page['link'](page=2)
        assert 'q=' not in page['link'](q='') and 'where=loose' in page['link'](q='')


def test_shipping_per_figure(figure,coll,read):
    coll.sql('UPDATE stock SET quantity=2 WHERE id=?',(figure[3],))
    coll.sql('UPDATE stock_part SET quantity=2,missing=missing*2 WHERE stock_id=?',(figure[3],))
    r=result(read,figure)
    assert (r['complete'],r['parts_value'],r['shipping_fees'],r['to_complete'])==('36.00','12.00','1.00','8.00')


def test_visible_money_uses_words_and_one_currency(figure,coll,client):
    import re
    coll.price(figure[0],'2.00',region='eu',observed=now().isoformat())
    text=BeautifulSoup(client.get('/planning/complete-sets?tab=figures').data,'html.parser').select_one('#bw-figures').get_text(' ',strip=True)
    assert 'part out gains €8.00' in text and 'Part out' in text
    assert not re.search(r'[−–-]\s*€|€\s+\d',text)
    assert 'USD' not in text and '$' not in text
    assert figures.RULE.format(minimum_gain='€5.00')=='Complete it when complete value less the cost to complete beats the part-out value by 10% and at least €5.00. Part out when the reverse holds. Otherwise no recommendation.'


def test_present_set_figures_only(figure, coll, read):
    copy, fid = add_place(coll, figure, 1)
    coll.sql('UPDATE copy_figure SET quantity=2,missing=1 WHERE id=?', (fid,))
    # The absent whole figure accounts for one missing piece on every component line.
    coll.sql('UPDATE copy_part SET quantity=2,missing=missing+1 WHERE copy_figure_id=?', (fid,))
    with read() as db:
        row = next(r for r in figures.compare(db) if r['copy_figure_id'] == fid)
    assert row['quantity'] == 1
    assert (row['complete'], row['parts_value'], row['shipping_fees'], row['to_complete'], row['missing_count']) == ('18.00', '6.00', '0.50', '4.00', 1)
    assert [(p['quantity'], p['missing']) for p in row['parts']] == [(1, 0)] * 3 + [(1, 1)]
    # Match collection's combined missing/damaged gap subtraction for an absent whole figure.
    coll.sql('UPDATE copy_part SET missing=0,damaged=1 WHERE copy_figure_id=? AND item_id=?', (fid, figure[1][0]))
    with read() as db:
        row = next(r for r in figures.compare(db) if r['copy_figure_id'] == fid)
    assert row['missing_count'] == 1 and row['parts'][0]['damaged'] == 0
    coll.sql('UPDATE copy_figure SET missing=2 WHERE id=?', (fid,))
    with read() as db:
        assert all(r['copy_figure_id'] != fid for r in figures.compare(db))


def test_default_loose_card_directly_follows_prices(figure, coll, client):
    add_place(coll, figure, 1)
    page = BeautifulSoup(client.get(f'/collection/item/{figure[0]}').data, 'html.parser')
    card = page.select_one('[data-module=figure-comparison]')
    assert card.select_one('summary').get_text() == 'Copy: Loose'
    assert card.parent.name == 'aside'
    assert card.find_previous_sibling()['data-module'] == 'prices'


def test_unknown_cost_hides_minimum_order(figure, coll, read, client):
    coll.setting('repair_min_order', '10')
    coll.sql('DELETE FROM price_current WHERE item_id=?', (figure[1][-1],))
    row = result(read, figure)
    assert row['to_complete'] is None and row['minimum_order_extra'] is None
    card = BeautifulSoup(client.get(f'/collection/item/{figure[0]}').data, 'html.parser').select_one('[data-module=figure-comparison]')
    assert 'no sales' in card.get_text() and 'Minimum order extra' not in card.get_text()


@pytest.mark.parametrize('currency,amount', [('EUR', '€5.00'), ('USD', '$5.00')])
def test_rule_uses_configured_currency(figure, coll, client, currency, amount):
    coll.setting('bricklink_currency', currency)
    page = BeautifulSoup(client.get('/planning/complete-sets?tab=figures').data, 'html.parser')
    assert 'at least ' + amount in page.select_one('[data-bf-rule]').get_text()
    if currency == 'USD':
        assert '€' not in page.select_one('#bw-figures').get_text()


def test_filtered_refresh_only_visible_incomplete_figure(figure, coll, client, app4, monkeypatch):
    import json
    coll.sql('DELETE FROM price_current WHERE item_id=?', (figure[1][-1],))
    other = coll.local('minifigure', 'Sam unseen figure', born_key='syn55-unseen')
    sid = coll.add_stock('minifigure', other, source='none')
    component = coll.local('part', 'Sam unseen part', born_key='syn55-unseen-part')
    coll.sql('INSERT INTO stock_part(stock_id,item_id,color_id,quantity,missing) VALUES(?,?,?,1,1)', (sid, component, figure[2]))
    # A complete figure matching the query must also stay outside the refresh scope.
    whole = coll.local('minifigure', 'Alex complete figure', born_key='syn55-complete-test')
    sid = coll.add_stock('minifigure', whole, source='none')
    coll.sql('INSERT INTO stock_part(stock_id,item_id,color_id,quantity) VALUES(?,?,?,1)', (sid, component, figure[2]))
    app4.jinja_env.globals['bw_key_missing'] = lambda source: False
    monkeypatch.setenv('BW_BRICKLINK_DAILY_BUDGET', '2')
    page = BeautifulSoup(client.get('/planning/complete-sets?tab=figures&q=Alex').data, 'html.parser')
    button = page.select_one('[data-bf-fetch]')
    assert button and not button.has_attr('disabled')
    assert json.loads(button['data-bf-fetch']) == [figure[1][-1]]
    assert '0 of 2 calls used today' in page.get_text()
