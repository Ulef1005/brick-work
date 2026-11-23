"""#524 own export: zip builder, API v2 route and CLI command. Invented data."""
import io
import json
import zipfile

import pytest

from brickwork.core import errors, own_export, tokens
from brickwork.web.cli import main
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401

FORBIDDEN_COPY_KEYS = {
    'inventory_source', 'inventory_version', 'fetched_inventory_id', 'inventory_digest',
    'inventory_pending', 'pending_job_id', 'materialised_at', 'checked_by', 'item_id',
}
ITEM_REF_KEYS = {'provider', 'namespace', 'key', 'local', 'kind', 'name'}
COLOR_REF_KEYS = {'provider', 'key', 'name'}


def _open(content):
    return zipfile.ZipFile(io.BytesIO(content))


def _jsonl(archive, name):
    text = archive.read(name).decode('utf-8')
    return [json.loads(line) for line in text.splitlines() if line]


def test_build_manifest_tables_lines_and_refs(coll, world, read):
    child = coll.storage('Bin A', id='0000-child', type='Bin', parent_id=world.shelf)
    archived_copy = coll.add_copy('1000-2')
    coll.sql("UPDATE copy SET archived_at='2026-10-27T00:00:00.000Z' WHERE id=?", (archived_copy,))
    coll.retire_line(world.copy_b, '3023', '15')
    with read() as db:
        built = own_export.build(db)
        schema = db.execute("SELECT value FROM main.meta WHERE key='schema_version'").fetchone()[0]
    expected_members = {
        'manifest.json', 'data/storage.jsonl', 'data/place.jsonl', 'data/flag.jsonl',
        'data/lot.jsonl', 'data/copy.jsonl', 'data/stock.jsonl', 'data/wishlist.jsonl', 'data/wish.jsonl',
    }
    with _open(built['content']) as zf:
        assert set(zf.namelist()) == expected_members
        manifest = json.loads(zf.read('manifest.json'))
        assert manifest['format'] == 'brickwork-export' and manifest['format_version'] == 1
        assert manifest['schema'] == schema and manifest['created_at'].endswith('Z')
        assert manifest['sections'] == ['places', 'flags', 'collection', 'wishes']
        assert manifest['counts'] == built['counts']
        storages = _jsonl(zf, 'data/storage.jsonl')
        ids = [r['id'] for r in storages]
        assert ids.index(world.shelf) < ids.index(child)
        assert all('short_id' not in r for r in storages)
        flags = _jsonl(zf, 'data/flag.jsonl')
        assert {r['name'] for r in flags} == {'collection', 'Set is checked'}
        copies = {r['id']: r for r in _jsonl(zf, 'data/copy.jsonl')}
        assert archived_copy not in copies
        copy_a = copies[world.copy_a]
        assert FORBIDDEN_COPY_KEYS.isdisjoint(copy_a)
        assert copy_a['list_source'] == 'rebrickable'
        assert set(copy_a['item']) == ITEM_REF_KEYS and copy_a['item']['key'] == '1000-1'
        assert copy_a['flags'] == ['Set is checked', 'collection']
        figs, parts = copy_a['lines']['figures'], copy_a['lines']['parts']
        assert len(figs) == 1 and set(figs[0]['item']) == ITEM_REF_KEYS and figs[0]['item']['key'] == 'fig-000004'
        assert all('id' not in line and 'item_id' not in line for line in figs)
        assert all(set(line['item']) == ITEM_REF_KEYS and set(line['color']) == COLOR_REF_KEYS for line in parts)
        assert all('id' not in line and 'item_id' not in line and 'color_id' not in line for line in parts)
        assert any(line['item']['key'] == '3001' and line['missing'] == 1 and not line['spare'] for line in parts)
        assert any(line['item']['key'] == '3023' and line['spare'] for line in parts)
        assert not any(line['item']['key'] == '3023' and line['color']['key'] == '15' for line in copies[world.copy_b]['lines']['parts'])
        stocks = {r['id']: r for r in _jsonl(zf, 'data/stock.jsonl')}
        assert stocks[world.stock_local]['item']['key'] and stocks[world.stock_local]['item']['local'] is True
        assert stocks[world.stock_local]['item']['name'] == 'Only on BrickLink'
        assert stocks[world.stock_mystery]['item']['key'] is None
        assert stocks[world.stock_mystery]['item']['kind'] == 'gear'
        assert all('inventory_source' not in s and 'item_id' not in s for s in stocks.values())
        assert all('id' not in line and 'item_id' not in line for line in stocks[world.stock_figure]['lines'])


def test_sections_filter_and_unknown_section(coll, world, read):
    with read() as db:
        built = own_export.build(db, sections=['places'])
        with pytest.raises(errors.ValidationFailed):
            own_export.build(db, sections=['nope'])
    assert built['sections'] == ['places']
    with _open(built['content']) as zf:
        assert set(zf.namelist()) == {'manifest.json', 'data/storage.jsonl', 'data/place.jsonl'}
        assert 'data/copy.jsonl' not in zf.namelist()


def test_note_redacts_stored_credential(coll, world, read, monkeypatch):
    secret = 'synthetic-env-credential-value'
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', secret)
    coll.sql('UPDATE copy SET note=? WHERE id=?', (f'api {secret} note', world.copy_a))
    with read() as db:
        built = own_export.build(db, sections=['collection'])
    with _open(built['content']) as zf:
        raw = zf.read('data/copy.jsonl').decode('utf-8')
        assert secret not in raw
        copies = {r['id']: r for r in _jsonl(zf, 'data/copy.jsonl')}
        assert copies[world.copy_a]['note'] == 'api [set] note'


def test_api_route_and_cli(app4, coll, world, tmp_path, capsys):
    secret = tokens.create(coll.db, 'x', ['read'])[0]['secret']
    api = app4.test_client()
    headers = {'Authorization': f'Bearer {secret}'}
    ok = api.get('/api/v2/export/brickwork.zip', headers=headers)
    assert ok.status_code == 200 and ok.mimetype == 'application/zip'
    assert ok.headers['Content-Disposition'].startswith('attachment; filename=brickwork-export-')
    with _open(ok.data) as zf:
        manifest = json.loads(zf.read('manifest.json'))
        assert int(ok.headers['X-Brickwork-Exported']) == sum(manifest['counts'].values())
    assert api.get('/api/v2/export/brickwork.zip?sections=nope', headers=headers).status_code == 422
    assert main(['export-all']) == 1
    assert 'Give --output FILE' in capsys.readouterr().err
    target = tmp_path / 'export.zip'
    assert main(['export-all', '--output', str(target)]) == 0
    summary = json.loads(capsys.readouterr().err)
    assert target.is_file() and summary['counts'] == manifest['counts']
    with _open(target.read_bytes()) as zf:
        assert 'data/copy.jsonl' in zf.namelist()


def test_a_reference_to_an_archived_parent_is_written_as_null_and_the_wishlist_has_no_bricklink_id(app4, coll, world):
    lot = coll.db.execute('SELECT lot_id FROM stock WHERE lot_id IS NOT NULL LIMIT 1').fetchone()
    assert lot is not None
    coll.sql('UPDATE lot SET archived_at=? WHERE id=?', ('2026-11-01T00:00:00Z', lot[0]))
    data = own_export.build(coll.db, 'collection')
    with zipfile.ZipFile(io.BytesIO(data['content'])) as zf:
        assert all(r['lot_id'] != lot[0] for r in _jsonl(zf, 'data/stock.jsonl'))
    wishes = own_export.build(coll.db, 'wishes')
    with zipfile.ZipFile(io.BytesIO(wishes['content'])) as zf:
        assert all('bricklink_id' not in r for r in _jsonl(zf, 'data/wishlist.jsonl'))
