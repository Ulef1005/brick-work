"""Collection file exports (#470): own CSV, BrickLink XML and Rebrickable CSV. Invented data."""
import csv
import io
import json

import pytest

from brickwork.core import add, collection_export, items, tokens
from tests.app4 import STAMP, app4, client, coll, csrf, pair, read, world  # noqa: F401


def table(text):
    return list(csv.reader(io.StringIO(text)))


def _read_headers(coll):
    """Authorization header for a fresh read-scope token."""
    secret = tokens.create(coll.db, 'export-reader', ['read'])[0]['secret']
    coll.db.commit()
    return {'Authorization': f'Bearer {secret}'}


@pytest.fixture
def read_headers(coll):
    return _read_headers(coll)


def test_own_csv_sets_and_parts(app4, coll, world, read_headers):
    coll.sql("UPDATE copy SET note='=SUM(A1:A2)' WHERE id=?", (world.copy_b,))
    extra = coll.add_stock('part', world.brick, colour=world.red, quantity=4, condition='used', note='=1+1')
    api = app4.test_client()

    got = api.get('/api/v2/export/collection.csv?kind=set', headers=read_headers)
    assert got.status_code == 200
    assert got.mimetype == 'text/csv'
    assert got.headers['X-Brickwork-Exported'] == '3'
    assert got.headers['X-Brickwork-Skipped'] == '0'
    rows = table(got.get_data(as_text=True))
    assert rows[0] == list(collection_export.OWN_COLUMNS)
    assert len(rows) == 4
    by_key = {(r[1], r[6]): dict(zip(rows[0], r)) for r in rows[1:]}
    used_keep = by_key[('1000-1', 'Used')]
    assert used_keep['Kind'] == 'set' and used_keep['Quantity'] == '1'
    assert used_keep['Completeness'] == 'Incomplete' and used_keep['Storage'] == 'Shelf A'
    assert used_keep['Place'] == 'Shop' and used_keep['Price paid'] == '12.50'
    assert used_keep['Price paid currency'] == 'EUR' and used_keep['Purchase date'] == '2024-05-01'
    assert 'collection' in used_keep['Tags/flags'] and used_keep['Note'] == 'Flea market'
    assert by_key[('1000-1', 'New')]['Note'] == "'=SUM(A1:A2)"

    got_parts = api.get('/api/v2/export/collection.csv?kind=part', headers=read_headers)
    assert got_parts.status_code == 200
    assert got_parts.headers['X-Brickwork-Exported'] == '5'
    assert got_parts.headers['X-Brickwork-Skipped'] == '0'
    part_rows = table(got_parts.get_data(as_text=True))
    assert part_rows[0] == list(collection_export.OWN_COLUMNS)
    assert len(part_rows) == 6
    part_dicts = [dict(zip(part_rows[0], r)) for r in part_rows[1:]]
    assert all(d['Kind'] == 'part' and d['Completeness'] == '' for d in part_dicts)
    used_3001 = [d for d in part_dicts if d['Item number'] == '3001' and d['Condition'] == 'Used']
    assert sorted(d['Quantity'] for d in used_3001) == ['3', '4']
    assert any(d['Note'] == "'=1+1" for d in used_3001)
    assert extra


def test_bricklink_xml_merges_and_counts_skipped(app4, coll, world, read_headers):
    coll.add_stock('part', world.brick, colour=world.red, quantity=4, condition='used')
    unmatched = coll.local('part', 'Unmatched widget')
    coll.add_stock('part', unmatched, colour=world.red, quantity=2, condition='used')
    api = app4.test_client()

    got = api.get('/api/v2/export/collection.xml?kind=part', headers=read_headers)
    assert got.status_code == 200
    assert got.mimetype == 'application/xml'
    assert got.headers['X-Brickwork-Exported'] == '4'
    assert got.headers['X-Brickwork-Skipped'] == '1'
    core_res = collection_export.to_xml(coll.db, 'part')
    assert core_res['skipped'] == [{'name': 'Unmatched widget', 'why': 'no BrickLink number'}]

    parsed = add.file_rows(got.data, 'x.xml', 'part')
    plate_bl = items.bricklink_key(coll.db, world.plate, world.white)
    by_line = {(r['kind'], r['number'], r['bl_color'], r['condition']): r['quantity'] for r in parsed}
    assert by_line == {
        ('part', '3001', '5', 'used'): 7,
        ('part', '3001', '5', 'new'): 2,
        ('part', plate_bl[1], plate_bl[2], 'new'): 2,
        ('part', 'x999', '5', 'used'): 5,
    }

    got_fig = api.get('/api/v2/export/collection.xml?kind=minifigure', headers=read_headers)
    assert got_fig.status_code == 200
    fig_rows = add.file_rows(got_fig.data, 'x.xml', 'minifigure')
    fig_bl = items.bricklink_key(coll.db, world.figure)
    assert [(r['kind'], r['number'], r['bl_color'], r['quantity']) for r in fig_rows] == [
        ('minifigure', fig_bl[1], None, 1),
    ]


def test_rebrickable_csv_and_round_trip(app4, coll, world, read_headers):
    api = app4.test_client()

    got_parts = api.get('/api/v2/export/collection.rebrickable.csv?kind=part', headers=read_headers)
    assert got_parts.status_code == 200
    assert got_parts.mimetype == 'text/csv'
    assert got_parts.headers['X-Brickwork-Exported'] == '2'
    assert got_parts.headers['X-Brickwork-Skipped'] == '1'
    assert table(got_parts.get_data(as_text=True))[0] == ['part_num', 'color_id', 'quantity']
    parsed_parts = add.file_rows(got_parts.data, 'x.csv', 'part')
    assert {(r['kind'], r['number'], r['rb_color']): r['quantity'] for r in parsed_parts} == {
        ('part', '3001', '4'): 5,
        ('part', '3023', '15'): 2,
    }

    got_sets = api.get('/api/v2/export/collection.rebrickable.csv?kind=set', headers=read_headers)
    assert got_sets.status_code == 200
    assert got_sets.headers['X-Brickwork-Exported'] == '2'
    assert got_sets.headers['X-Brickwork-Skipped'] == '0'
    assert table(got_sets.get_data(as_text=True))[0] == ['set_num', 'quantity']
    parsed_sets = add.file_rows(got_sets.data, 'x.csv', 'set')
    assert {(r['kind'], r['number'], r['rb_color']): r['quantity'] for r in parsed_sets} == {
        ('set', '1000-1', None): 2,
        ('set', '2070-1', None): 1,
    }

    got_figs = api.get('/api/v2/export/collection.rebrickable.csv?kind=minifigure', headers=read_headers)
    assert got_figs.status_code == 200
    assert got_figs.headers['X-Brickwork-Exported'] == '1'
    assert got_figs.headers['X-Brickwork-Skipped'] == '0'
    assert table(got_figs.get_data(as_text=True))[0] == ['minifig_num', 'quantity']
    parsed_figs = add.file_rows(got_figs.data, 'x.csv', 'minifigure')
    assert {(r['kind'], r['number'], r['rb_color']): r['quantity'] for r in parsed_figs} == {
        ('minifigure', 'fig-000004', None): 1,
    }


def test_id_filter_and_validation(app4, coll, world, read_headers):
    api = app4.test_client()
    got = api.get(f'/api/v2/export/collection.csv?kind=set&id={world.copy_a}', headers=read_headers)
    assert got.status_code == 200
    assert got.headers['X-Brickwork-Exported'] == '1'
    rows = table(got.get_data(as_text=True))
    assert len(rows) == 2 and rows[1][1] == '1000-1'

    got_parts = api.get(f'/api/v2/export/collection.rebrickable.csv?kind=part&id={world.stock_brick}&id={world.stock_plate}', headers=read_headers)
    assert got_parts.status_code == 200
    assert got_parts.headers['X-Brickwork-Exported'] == '2'
    assert {(r['number'], r['quantity']) for r in add.file_rows(got_parts.data, 'x.csv', 'part')} == {('3001', 3), ('3023', 2)}

    coll.sql('UPDATE copy SET archived_at=? WHERE id=?', (STAMP, world.copy_c))
    assert api.get(f'/api/v2/export/collection.csv?kind=set&id={world.copy_c}', headers=read_headers).status_code == 422
    assert api.get('/api/v2/export/collection.csv?kind=set', headers=read_headers).headers['X-Brickwork-Exported'] == '2'

    assert api.get('/api/v2/export/collection.csv?kind=set&id=no-such-id', headers=read_headers).status_code == 422
    assert api.get(f'/api/v2/export/collection.xml?kind=set&id={world.copy_a}&id={world.copy_a}', headers=read_headers).status_code == 422
    for path in ('/api/v2/export/collection.csv', '/api/v2/export/collection.xml', '/api/v2/export/collection.rebrickable.csv'):
        assert api.get(f'{path}?kind=gear', headers=read_headers).status_code == 422
        assert api.get(path, headers=read_headers).status_code == 422


def test_read_scope_token_calls_all_three_routes(app4, world, read_headers):
    api = app4.test_client()
    for path in ('/api/v2/export/collection.csv', '/api/v2/export/collection.xml', '/api/v2/export/collection.rebrickable.csv'):
        got = api.get(f'{path}?kind=set', headers=read_headers)
        assert got.status_code == 200


def test_the_export_command_prints_the_file_and_the_counts(app4, world, capsys):
    from brickwork.web.cli import main
    assert main(['export', 'set']) == 0
    out = capsys.readouterr()
    assert table(out.out)[0] == list(collection_export.OWN_COLUMNS)
    assert json.loads(out.err)['exported'] == len(table(out.out)) - 1
    assert main(['export', 'set', '--format', 'bricklink']) == 0
    assert capsys.readouterr().out.lstrip().startswith('<?xml')
    assert main(['export', 'part', '--format', 'rebrickable', '--id', 'nope']) == 1
    assert 'Export error' in capsys.readouterr().err


def test_owners_have_their_own_column_and_the_item_number_is_the_number(app4, coll, world, read_headers):
    coll.tag('copy', world.copy_a, coll.flag('Alex', 'owner'))
    coll.tag('copy', world.copy_a, coll.flag('Gift', 'tag'))
    got = app4.test_client().get('/api/v2/export/collection.csv?kind=set', headers=read_headers)
    rows = [dict(zip(table(got.get_data(as_text=True))[0], r)) for r in table(got.get_data(as_text=True))[1:]]
    mine = [r for r in rows if r['Owners'] == 'Alex']
    assert mine and 'Alex' not in mine[0]['Tags/flags'] and 'Gift' in mine[0]['Tags/flags']
    assert all(' · ' not in r['Item number'] and r['Item number'] for r in rows)
