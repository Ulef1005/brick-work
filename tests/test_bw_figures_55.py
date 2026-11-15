"""#55: invented figure places, fresh used quotes, offline readers."""
from decimal import Decimal
from pathlib import Path
import subprocess

from bs4 import BeautifulSoup
import pytest

from brickwork.core import figures, partout
from brickwork.core.sources.base import now
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
    assert all(s not in page.get_text() for s in ('Export selected','Order missing parts','Print'))
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
