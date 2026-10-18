"""Design v1.3 detail regressions, using rendered catalogue and copy state."""
from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin, collection
from brickwork.web.formatting import money
from tests.test_bw_collection import bw, add_49a_long_figure
from tests.web_fixtures import app, apps, logged_in
from tests.importer.test_importer import legacy
from tests.test_bw_admin import reset_shell_metadata_after_test


@pytest.mark.parametrize('value,fixed,expected', [
    ('11408.95', True, '€11,408.95'), ('1000', False, '€1,000'),
    ('-11408.95', True, '€11,408.95 below'), ('999.995', True, '€1,000.00'),
])
def test_grouped_money(value, fixed, expected):
    assert money(value, fixed=fixed) == expected


@pytest.mark.parametrize('state', ['present', 'parts-missing', 'missing'])
def test_figure_lines_and_image(app, bw, state):
    missing = state == 'missing'
    with admin.database(bw) as db, db:
        add_49a_long_figure(db)
        db.execute("UPDATE copy_minifigs SET missing=? WHERE minifig_no='long-fig'", (int(missing),))
        if state == 'present':
            db.execute("UPDATE copy_parts SET missing=0 WHERE parent_minifig='long-fig'")
        image = db.execute("SELECT * FROM item_images LIMIT 1").fetchone()
        columns = [k for k in image.keys() if k != 'id']
        values = dict(image, item_type='M', item_no='long-fig', color_id=None)
        image_id = db.execute('INSERT INTO item_images('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')', [values[k] for k in columns]).lastrowid
        d = collection.detail(db, 'S', 'new-set', copy_id='copy')
        assert d['figure_progress']['present'] == sum(max((r['quantity'] or 0)-(r['missing'] or 0),0) for r in d['consists'] if r.get('minifig_no'))
    client = logged_in(app)
    soup = BeautifulSoup(client.get('/collection/item/S/new-set?copy=copy&inventory=figures').data, 'html.parser')
    fig = next(r for r in soup.select('.bc-figure-row') if 'long-fig' == r.select_one('.bc-figure-identity>.mono').get_text())
    assert fig.select_one('.bc-figure-identity>a')['href'] == '/collection/item/M/long-fig'
    assert not fig.select('a.bc-figure-status')
    assert fig.select_one('.bc-figure-status')['data-figure-state'] == state
    assert bool(fig.select_one('button.bc-check-figure[disabled]')) == missing
    if missing:
        assert fig.select_one('.bc-check-figure')['title'] == 'Whole figure missing'
    if not missing:
        assert fig.select_one('.bc-check-figure')['href'] == '/workbench/check-parts/copy/figure/M/long-fig'
        checker = client.get(fig.select_one('.bc-check-figure')['href'])
        assert checker.status_code == 200
        assert 'Check figure parts' in BeautifulSoup(checker.data, 'html.parser').get_text()
        if state == 'parts-missing':
            assert fig.select_one('.bc-figure-parts').get_text() == 'Torso'
        else:
            assert not fig.select_one('.bc-figure-parts')
    assert fig.img['src'] == f'/manage/images/{image_id}?w=320' and fig.img['data-full'] == f'/manage/images/{image_id}'
    assert client.get(fig.img['data-full']).status_code == 200
    assert 'Parts missing from a figure count on the figure, not on the set.' in soup.get_text()
    assert 'Part details' not in soup.get_text()
    assert not soup.select('.bc-inventory-row-details')
    assert soup.select('.bc-inventory-details [data-bc-context]')
    assert soup.select_one('label[for=bc-photo-file]').get_text() == 'Choose photo'
    assert soup.select_one('#bc-photo-file')['type'] == 'file'
    assert soup.select_one('[data-bc-photo-name]').get_text() == 'No file chosen'
    assert 'Grouped by place and condition in lists.' not in soup.get_text()
    minifigure = BeautifulSoup(client.get('/collection/item/M/bl-figure').data, 'html.parser')
    assert 'Part details' not in minifigure.get_text()
    assert minifigure.select('[data-bc-photo-file]')
    assert 'Grouped by place and condition in lists.' not in minifigure.get_text()


def test_canonical_brickset_and_phone_order(app, bw):
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('S','375-2','Castle')")
        links = dict(collection.external_links(db, dict(item_type='S',item_no='375-2')))
        assert links['Brickset'] == 'https://brickset.com/sets/375-2'
    soup = BeautifulSoup(logged_in(app).get('/collection/item/S/375-2').data, 'html.parser')
    assert soup.select_one('.bc-phone-links a[href="https://brickset.com/sets/375-2"]')
    assert soup.select_one('.bc-phone-links').parent.find_next_sibling()['class'] == ['bc-hero-status']
    layout = soup.select_one('.bc-detail-layout')
    assert layout.find(recursive=False)['class'] == ['bc-detail-aside']
    assert [r['data-module'] for r in layout.select('.bc-detail-aside>[data-module]')] == ['info', 'prices']


def test_grouped_price_range_and_wishlist(app, bw):
    with admin.database(bw) as db, db:
        db.execute("DELETE FROM price_current WHERE item_type='S' AND item_no='new-set'")
        db.execute("DELETE FROM price_observations WHERE item_type='S' AND item_no='new-set'")
        db.execute("""INSERT INTO price_observations(item_type,item_no,condition,guide,currency,price,min,max,sold,source,observed_at)
            VALUES('S','new-set','U','sold','EUR','11408.95','1000','15000',7,'bricklink','2026-10-08')""")
        wish_id = db.execute("SELECT id FROM wishlist WHERE item_type='S' AND item_no='new-set'").fetchone()[0]
        db.execute("UPDATE wishlist SET max_price='11408.95',max_price_currency='EUR' WHERE id=?", (wish_id,))
    client = logged_in(app)
    soup = BeautifulSoup(client.get('/collection/item/S/new-set?copy=copy').data, 'html.parser')
    price = soup.select_one('[data-module=prices]').get_text(' ', strip=True)
    assert '€11,408.95' in price and 'min €1,000.00' in price and 'max €15,000.00' in price
    wish = BeautifulSoup(client.get(f'/collection/wishes/{wish_id}').data, 'html.parser')
    assert wish.select_one('.bc-wanted-max strong').get_text() == '€11,408.95'


@pytest.mark.parametrize('missing,damaged', [(1, 0), (0, 1), (1, 1)])
def test_figure_missing_and_damaged_parts_are_separate(app, bw, missing, damaged):
    with admin.database(bw) as db, db:
        add_49a_long_figure(db)
        db.execute("UPDATE copy_parts SET missing=?,damaged=? WHERE parent_minifig='long-fig'", (missing, damaged))
        detail = collection.detail(db, 'S', 'new-set', copy_id='copy')
        figure = next(r for r in detail['consists'] if r['item_no'] == 'long-fig')
        assert figure['parts_missing'] == missing
        assert figure['parts_damaged'] == damaged
        assert figure['missing_part_names'] == (['Torso'] if missing else [])
    soup = BeautifulSoup(logged_in(app).get('/collection/item/S/new-set?copy=copy&inventory=figures').data, 'html.parser')
    figure = next(r for r in soup.select('.bc-figure-row') if r.select_one('.bc-figure-identity>.mono').get_text() == 'long-fig')
    assert figure.select_one('.bc-figure-status').get_text() == ('1 part missing' if missing else 'Present')
    assert ('1 damaged' in figure.get_text()) == bool(damaged)
    assert bool(figure.select_one('.bc-figure-parts')) == bool(missing)
    assert not figure.select_one('button[disabled]')


@pytest.mark.parametrize('status', ['to_check', 'unmatched'])
@pytest.mark.parametrize('kind', ['set_number', 'setID'])
def test_canonical_brickset_does_not_infer_ambiguous_mapping(bw, status, kind):
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('S','375-2','Castle')")
        db.execute("INSERT INTO id_match(source,kind,source_id,item_type,item_no,status,evidence_json) VALUES('brickset',?,'uncertain','S','375-2',?,'{}')", (kind, status))
        links = dict(collection.external_links(db, dict(item_type='S', item_no='375-2')))
        assert 'Brickset' not in links
        assert 'BrickLink' in links
