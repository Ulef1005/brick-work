"""#524 own import plan: zip safety, classification, plan storage and CLI. Invented data."""
from contextlib import closing
import io
import json
import zipfile

import pytest

from brickwork.core import errors, own_export, own_import, sync
from brickwork.core.connect import connect
from brickwork.web.cli import build_parser, main
from tests.app4 import app4, coll, make_pair, pair, read, world  # noqa: F401


def _repack(content, *, mutate=None, extra=None, keep_counts=False):
    """Rewrite a zip archive with optional member edits or extra entries; the manifest counts follow the edited rows unless kept."""
    members = {}
    with zipfile.ZipFile(io.BytesIO(content)) as src:
        for info in src.infolist():
            data = src.read(info.filename)
            members[info.filename] = mutate(info.filename, data) if mutate else data
    members.update(extra or {})
    if not keep_counts and 'manifest.json' in members:
        manifest = json.loads(members['manifest.json'])
        for name, data in members.items():
            if name.startswith('data/') and name.endswith('.jsonl'):
                table = name[len('data/'):-len('.jsonl')]
                if table in (manifest.get('counts') or {}):
                    manifest['counts'][table] = len([line for line in data.splitlines() if line.strip()])
        members['manifest.json'] = json.dumps(manifest).encode('utf-8')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as dst:
        for name, data in members.items():
            dst.writestr(name, data)
    return buf.getvalue()


def test_same_install_all_here_and_plan_round_trip(coll, world):
    content = own_export.build(coll.db)['content']
    planned = own_import.plan(coll.db, content)
    assert planned['direction'] == 'brickwork_file'
    assert planned['source'] == 'file'
    assert list(planned['counts']) == list(own_import.WRITE_ORDER)
    for table, counts in planned['counts'].items():
        assert counts['new'] == 0
        assert counts['difference'] == 0
        assert counts['unresolved'] == 0
        assert counts['here'] == len(planned['tables'][table])
    loaded = sync.load_plan(coll.db, planned['id'], 'brickwork_file')
    assert loaded['id'] == planned['id']
    assert loaded['counts'] == planned['counts']
    assert loaded['tables']['copy'] == planned['tables']['copy']


def test_live_edit_and_archived_copy_report_difference(coll, world):
    content = own_export.build(coll.db)['content']
    coll.sql('UPDATE copy SET note=? WHERE id=?', ('Changed note', world.copy_a))
    edited = own_import.plan(coll.db, content, store=False)
    assert edited['counts']['copy']['difference'] == 1
    diff_row = [r for r in edited['rows']['copy'] if r['id'] == world.copy_a][0]
    assert diff_row['status'] == 'difference'
    assert diff_row['differs'] == ['note']

    # Archived rows are not live, so a matching id reports a difference on archived_at.
    coll.sql("UPDATE copy SET note='Flea market', archived_at='2026-11-01T00:00:00Z' WHERE id=?", (world.copy_a,))
    archived = own_import.plan(coll.db, content, store=False)
    assert archived['counts']['copy']['difference'] == 1
    arch_row = [r for r in archived['rows']['copy'] if r['id'] == world.copy_a][0]
    assert arch_row['status'] == 'difference'
    assert arch_row['differs'] == ['archived_at']


def test_empty_install_new_unresolved_local_and_line_unmatched(coll, world, tmp_path):
    content = own_export.build(coll.db)['content']

    def add_edge_cases(name, data):
        if name == 'data/stock.jsonl':
            rows = [json.loads(line) for line in data.decode('utf-8').splitlines() if line]
            rows.append({
                'id': 'stock-missing-cat', 'kind': 'part',
                'item': {'provider': 'rebrickable', 'namespace': 'parts', 'key': '999999', 'local': False, 'kind': 'part', 'name': 'Missing Part'},
                'color': {'provider': 'rebrickable', 'key': '4', 'name': 'Red'},
                'quantity': 1, 'condition': 'used', 'storage_id': None, 'lot_id': None, 'place_id': None,
                'purchase_date': None, 'purchase_price': None, 'purchase_currency': None, 'note': None,
                'missing': None, 'damaged': None, 'checked': None, 'list_source': None,
                'added_via': None, 'created_at': '2026-10-26T12:00:00Z', 'updated_at': '2026-10-26T12:00:00Z',
                'flags': [], 'lines': [],
            })
            return ('\n'.join(json.dumps(r) for r in rows) + '\n').encode('utf-8')
        if name == 'data/copy.jsonl':
            rows = [json.loads(line) for line in data.decode('utf-8').splitlines() if line]
            for r in rows:
                if r['id'] == world.copy_b:
                    r['lines']['parts'].append({
                        'item': {'provider': 'rebrickable', 'namespace': 'parts', 'key': '888888', 'local': False, 'kind': 'part', 'name': 'Ghost'},
                        'color': {'provider': 'rebrickable', 'key': '4', 'name': 'Red'},
                        'figure': None, 'quantity': 1, 'missing': 0, 'damaged': 0, 'checked': False, 'spare': False,
                    })
            rows.append({
                'id': 'copy-wrong-kind',
                'item': {'provider': 'rebrickable', 'namespace': 'parts', 'key': '3001', 'local': False, 'kind': 'part', 'name': 'Brick 2x4'},
                'list_source': 'rebrickable', 'condition': 'used', 'completeness': None, 'completeness_source': None,
                'storage_id': None, 'place_id': None, 'purchase_date': None, 'purchase_price': None,
                'purchase_currency': None, 'note': None, 'current_value': None, 'current_value_currency': None,
                'pinned': False, 'added_via': None, 'created_at': '2026-10-26T12:00:00Z', 'updated_at': '2026-10-26T12:00:00Z',
                'flags': [], 'lines': {'figures': [], 'parts': []},
            })
            return ('\n'.join(json.dumps(r) for r in rows) + '\n').encode('utf-8')
        return data

    patched = _repack(content, mutate=add_edge_cases)
    empty_dir = tmp_path / 'empty'
    empty_dir.mkdir()
    empty_path = make_pair(empty_dir, rich=True)
    with closing(connect(empty_path, read_only=True)) as db:
        planned = own_import.plan(db, patched, store=False)
    assert planned['counts']['storage']['new'] == 1
    assert planned['counts']['place']['new'] == 1
    assert planned['counts']['lot']['new'] == 1
    assert planned['counts']['wishlist']['here'] == 1
    assert planned['counts']['copy']['new'] == 3
    assert planned['counts']['copy']['unresolved'] == 1
    assert planned['counts']['copy']['lines_unmatched'] == 1
    assert planned['counts']['stock']['new'] == 4
    assert planned['counts']['stock']['unresolved'] == 4
    assert planned['counts']['wish']['new'] == 2
    stock_rows = {r['id']: r for r in planned['rows']['stock']}
    assert stock_rows[world.stock_local]['status'] == 'unresolved'
    assert stock_rows[world.stock_local]['reason'] == 'No number to find it by'
    assert stock_rows[world.stock_mystery]['status'] == 'unresolved'
    assert stock_rows[world.stock_mystery]['reason'] == 'No number to find it by'
    assert stock_rows['stock-missing-cat']['status'] == 'unresolved'
    assert '999999' in stock_rows['stock-missing-cat']['reason']
    copy_rows = {r['id']: r for r in planned['rows']['copy']}
    assert copy_rows['copy-wrong-kind']['status'] == 'unresolved'
    assert world.copy_b not in copy_rows


def test_zip_validation_errors(coll, world):
    valid = own_export.build(coll.db)['content']
    with pytest.raises(errors.ValidationFailed, match='not a Brick Work export file'):
        own_import.read_zip(b'not a zip archive')
    with pytest.raises(errors.ValidationFailed):
        own_import.read_zip(_repack(valid, extra={'extra.txt': b'hello'}))
    with pytest.raises(errors.ValidationFailed):
        own_import.read_zip(_repack(valid, extra={'../escape.jsonl': b'{}\n'}))

    def wrong_format(name, data):
        if name == 'manifest.json':
            m = json.loads(data)
            m['format'] = 'other-format'
            return json.dumps(m).encode('utf-8')
        return data

    with pytest.raises(errors.ValidationFailed, match='not a Brick Work export file'):
        own_import.read_zip(_repack(valid, mutate=wrong_format))

    def newer_version(name, data):
        if name == 'manifest.json':
            m = json.loads(data)
            m['format_version'] = own_export.FORMAT_VERSION + 1
            return json.dumps(m).encode('utf-8')
        return data

    with pytest.raises(errors.ValidationFailed, match='newer Brick Work'):
        own_import.read_zip(_repack(valid, mutate=newer_version))

    def bad_line(name, data):
        if name == 'data/copy.jsonl':
            return data + b'[1, 2, 3]\n'
        return data

    with pytest.raises(errors.ValidationFailed, match=r'data/copy\.jsonl line 4'):
        own_import.read_zip(_repack(valid, mutate=bad_line))

    places_only = own_export.build(coll.db, sections=['places'])['content']
    with pytest.raises(errors.ValidationFailed):
        own_import.plan(coll.db, places_only, sections=['collection'], store=False)


def test_cli_import_file_reads_without_writing(app4, coll, world, pair, tmp_path, capsys):
    target = tmp_path / 'export.zip'
    target.write_bytes(own_export.build(coll.db)['content'])
    before = {t: coll.db.execute(f'SELECT count(*) FROM main.{t}').fetchone()[0] for t in ('copy', 'stock', 'storage')}
    help_text = build_parser().format_help()
    assert 'with --apply it adds the new rows' in ' '.join(help_text.split())

    assert main(['import-file', str(target)]) == 0
    out = capsys.readouterr().out
    assert 'copy: 0 new, 3 here, 0 difference, 0 unresolved' in out
    assert 'storage: 0 new, 1 here, 0 difference, 0 unresolved' in out

    assert main(['import-file', str(target), '--json']) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['counts']['copy']['here'] == 3
    assert 'tables' not in payload

    after = {t: coll.db.execute(f'SELECT count(*) FROM main.{t}').fetchone()[0] for t in ('copy', 'stock', 'storage')}
    assert after == before
    assert not list((pair.parent / 'data' / 'sync').glob('*.json'))

    bad = tmp_path / 'bad.zip'
    bad.write_bytes(b'not a zip')
    assert main(['import-file', str(bad)]) == 1
    assert 'This is not a Brick Work export file' in capsys.readouterr().err


def test_plan_refuses_a_missing_table_a_wrong_count_and_names_a_duplicate_or_impossible_row(coll, world):
    valid = own_export.build(coll.db)['content']
    with zipfile.ZipFile(io.BytesIO(valid)) as zf:
        names = zf.namelist()
    assert 'data/copy.jsonl' in names
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(valid)) as src, zipfile.ZipFile(buf, 'w') as dst:
        for info in src.infolist():
            if info.filename != 'data/copy.jsonl':
                dst.writestr(info.filename, src.read(info.filename))
    with pytest.raises(errors.ValidationFailed, match=r'missing data/copy\.jsonl'):
        own_import.plan(coll.db, buf.getvalue(), store=False)

    def cut(name, data):
        if name == 'data/copy.jsonl':
            return b''
        return data

    with pytest.raises(errors.ValidationFailed, match='the manifest says'):
        own_import.plan(coll.db, _repack(valid, mutate=cut, keep_counts=True), store=False)

    def twice(name, data):
        if name == 'data/stock.jsonl':
            return data + data
        return data

    def counts_follow(name, data):
        if name == 'manifest.json':
            m = json.loads(data)
            m['counts'].pop('stock', None)
            return json.dumps(m).encode('utf-8')
        return twice(name, data)

    planned = own_import.plan(coll.db, _repack(valid, mutate=counts_follow), store=False)
    assert planned['counts']['stock']['unresolved'] >= 1
    assert any(r.get('reason') == 'The same id twice in the file' for r in planned['rows']['stock'])
    assert own_import._value_problem('stock', {'kind': 'part', 'quantity': -1, 'color': {'key': 1}}) == 'Quantity must be a whole number'
    assert own_import._value_problem('stock', {'kind': 'part', 'quantity': 2, 'missing': 3, 'color': {'key': 1}}) == 'Missing is more than the quantity'
    assert own_import._value_problem('wish', {'kind': 'set', 'quantity': 1, 'color': {'key': 1}}) == 'Only a part has a colour'
    assert own_import._value_problem('copy', {'purchase_price': 5, 'purchase_currency': None}) == 'A price needs its currency'
