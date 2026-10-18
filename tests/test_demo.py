"""The static demo: synthetic store, exported routes, rewritten links and the write shim."""
import json
import re
import sqlite3

import pytest

from brickwork.demo import dataset, export

BASE = '/brick-work/demo/'


@pytest.fixture(scope='module')
def site(tmp_path_factory):
    import os
    before = dict(os.environ)
    out = tmp_path_factory.mktemp('demo') / 'site'
    manifest = export.export(out, BASE)
    assert dict(os.environ) == before  # export() leaves the environment as it found it
    return out, manifest


def test_dataset_is_invented_and_consistent(tmp_path):
    counts = dataset.build(tmp_path / 'demo.db')
    assert counts['copies'] == 19 and counts['copy_parts'] > 1000 and counts['wishlist'] == 6 and counts['loose_stock'] > 0
    db = sqlite3.connect(tmp_path / 'demo.db')
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    owners = {r[0] for r in db.execute("SELECT name FROM flags WHERE kind='owner'")}
    assert owners == {'Alex', 'Sam', 'Shared'}  # no real names
    assert not db.execute('SELECT count(*) FROM item_images').fetchone()[0]  # no pictures of others
    with pytest.raises(FileExistsError):
        dataset.build(tmp_path / 'demo.db')


def test_agreed_routes_are_exported(site):
    out, manifest = site
    pages = manifest['pages']
    for route in ('/collection/sets', '/collection/M', '/collection/P', '/collection/item/S/1592-1',
                  '/collection/item/P/3001?colour=4', '/workbench/check-parts', '/workbench/part-picker',
                  '/workbench/part-to-inventory', '/planning/wishlist', '/planning/prices',
                  '/planning/complete-sets', '/workbench/storage'):
        assert route in pages, route
        assert (out / pages[route] / 'index.html').is_file()
    assert any(k.startswith('/workbench/check-parts/') and k.endswith('?run=1') for k in pages)  # Start opens a running check
    assert any(k.startswith('/workbench/part-picker?copy=') for k in pages)  # Continue opens the picking view
    assert not any(k.startswith('/manage') for k in pages)
    assert manifest['skipped'] == {} and manifest['gets']['/planning/prices/records']
    # Running checks made with the app's own checker: first part, half done, at the end.
    checks = manifest['counts']['checks']
    assert checks['56325b99-16bc-549b-bb98-f7be2ab38829'][0] == 0
    assert 0 < checks['eaacf51c-1b63-58ff-b1a9-a2ea287565fc'][0] < checks['eaacf51c-1b63-58ff-b1a9-a2ea287565fc'][1]
    assert all(c == n for c, n in (checks['4fcedaaf-0c28-5203-9058-7044daabce23'], checks['ff25ae37-7a6c-5804-92aa-bb3a03e64cac']))
    assert json.loads((out / 'demo-manifest.json').read_text())['base'] == BASE


def test_pages_point_inside_the_demo(site):
    out, _ = site
    for path in out.rglob('index.html'):
        text = path.read_text()
        if path.parent == out:
            assert 'collection/sets/' in text  # the redirect
            continue
        assert f'<script src="{BASE}demo-shim.js"></script>' in text
        assert not re.search(r'(?:href|src|action)="/(?!brick-work/demo/)', text), path
        assert 'rel="manifest"' not in text
    sets = (out / 'collection/sets/index.html').read_text()
    assert f'href="{BASE}workbench/check-parts/"' in sets and 'href="#demo-not-included"' in sets
    assert export.check(out) == []


def test_shim_answers_writes_and_carries_the_manifest(site):
    out, manifest = site
    shim = (out / 'demo-shim.js').read_text()
    assert '/*MANIFEST*/null' not in shim and json.dumps(manifest['base']) in shim
    assert export.NOTE in shim and "method !== 'GET'" in shim and 'serviceWorker' in shim
    # Missing-picture tiles say where the app gets pictures (checked against the pipeline's pictures step).
    assert 'Loads from BrickLink when you add the set' in shim and 'Loads from Rebrickable or BrickLink with Refresh pictures' in shim


def test_keys_and_files():
    assert export.key_of(BASE + 'collection/item/P/3001?colour=4', BASE) == '/collection/item/P/3001?colour=4'
    assert export.key_of(BASE + 'workbench/part-picker?copy=b&amp;copy=a', BASE) == '/workbench/part-picker?copy=a&copy=b'
    assert export.key_of('/collection/sets', BASE) is None and export.key_of('https://example.test' + BASE, BASE) is None
    assert export.file_of('/collection/sets') == 'collection/sets/index.html'
    assert export.file_of('/collection/item/P/3001?colour=4') == 'collection/item/P/3001/_colour-4/index.html'


def test_export_refuses_an_existing_folder_and_a_bad_base(tmp_path):
    with pytest.raises(FileExistsError):
        export.export(tmp_path, BASE)
    with pytest.raises(ValueError):
        export.export(tmp_path / 'new', 'brick-work/demo')
