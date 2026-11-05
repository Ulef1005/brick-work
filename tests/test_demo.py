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
    """The demo is a 4.0 collection on a catalogue built from the design test data (M.8j)."""
    counts = dataset.build(tmp_path / 'demo.db')
    assert counts['copy'] == 19 and counts['copy_part'] > 1000 and counts['wish'] == 6 and counts['stock'] > 0
    assert (tmp_path / 'catalogue.db').is_file() and len(counts['ids']) == 18                 # the catalogue is beside the collection; 7286-1 is held twice
    db = sqlite3.connect(tmp_path / 'demo.db')
    db.execute('PRAGMA foreign_keys=ON')
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    owners = {r[0] for r in db.execute("SELECT name FROM flag WHERE kind='owner'")}
    assert owners == {'Alex', 'Sam', 'Shared'}  # no real names
    assert not db.execute('SELECT count(*) FROM picture').fetchone()[0]  # no pictures of others
    assert not db.execute("SELECT count(*) FROM item WHERE origin='local'").fetchone()[0]    # every item is a catalogue item: nothing is unidentified
    assert db.execute("SELECT count(*) FROM item i WHERE i.kind='set' AND NOT EXISTS(SELECT 1 FROM copy c WHERE c.item_id=i.id) AND NOT EXISTS(SELECT 1 FROM wish w WHERE w.item_id=i.id)").fetchone()[0] == 0
    with pytest.raises(FileExistsError):
        dataset.build(tmp_path / 'demo.db')
    with pytest.raises(FileExistsError):
        dataset.build(tmp_path / 'demo-2.db')                                                   # the catalogue.db beside the first one is not overwritten


def test_agreed_routes_are_exported(site):
    out, manifest = site
    pages = manifest['pages']
    for route in ('/collection/sets', '/collection/M', '/collection/P', '/workbench/check-parts', '/workbench/part-picker',
                  '/workbench/part-to-inventory', '/planning/wishlist', '/planning/prices', '/planning/complete-sets', '/workbench/storage'):
        assert route in pages, route
        assert (out / pages[route] / 'index.html').is_file()
    items = [k for k in pages if re.fullmatch(r'/collection/item/[0-9]+', k)]
    assert len(items) >= 18                                                                    # every owned set has its page, by item id
    assert any(re.fullmatch(r'/collection/item/[0-9]+\?colour=[0-9]+', k) for k in pages)     # and one part in one colour
    assert any(k.startswith('/workbench/check-parts/') and k.endswith('?run=1') for k in pages)  # Start opens a running check
    assert any(k.startswith('/workbench/part-picker?copy=') for k in pages)  # Continue opens the picking view
    for route in ('/collection/G', '/collection/B', '/collection/C', '/workbench/match', '/workbench/orders', '/workbench/orders/1', '/planning/wishlist',
                  '/manage/add', '/manage/tools', '/manage/statistics', '/manage/sync', '/manage/jobs'):
        assert route in pages, route                                                          # every kind and every area of 0.9.0 has its pages
    assert not any(k.startswith('/manage/get-started') for k in pages)
    assert manifest['skipped'] == {} and manifest['gets']['/planning/prices/records']
    assert any(k.startswith('/planning/prices/details?item_id=') for k in manifest['gets'])
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
    banner = shim.split('// The banner:', 1)[1].split('const realFetch', 1)[0]
    assert "website.href = 'https://ulef1005.github.io/brick-work/'; website.textContent = 'Website'; website.style.color = 'inherit';" in banner
    assert banner.index('bar.append(link);') < banner.index("bar.append(' · ', website);")
    assert 'target' not in banner
    # Missing-picture tiles say where the app gets pictures (checked against the pipeline's pictures step).
    assert 'Loads from BrickLink when you add the set' in shim and 'Loads from Rebrickable or BrickLink with Refresh pictures' in shim


def test_keys_and_files():
    assert export.key_of(BASE + 'collection/item/P/3001?colour=4', BASE) == '/collection/item/P/3001?colour=4'
    assert export.key_of(BASE + 'workbench/part-picker?copy=b&amp;copy=a', BASE) == '/workbench/part-picker?copy=a&copy=b'
    assert export.key_of('/collection/sets', BASE) is None and export.key_of('https://example.test' + BASE, BASE) is None
    assert export.file_of('/collection/sets') == 'collection/sets/index.html'
    assert export.file_of('/collection/item/P/3001?colour=4') == 'collection/item/P/3001/_colour-4/index.html'


@pytest.mark.parametrize('suffix', ['', 'other/', '?query=1', '#fragment', '\n'])
def test_export_allows_only_the_exact_website_url(tmp_path, suffix):
    url = 'https://ulef1005.github.io/brick-work/' + suffix
    (tmp_path / 'index.html').write_text(f'<a href="{url}">Website</a>')
    (tmp_path / 'demo-shim.js').write_text('')
    findings = export.check(tmp_path)
    assert findings == ([] if not suffix else [f'index.html: outside link {url}'])


def test_export_refuses_an_existing_folder_and_a_bad_base(tmp_path):
    with pytest.raises(FileExistsError):
        export.export(tmp_path, BASE)
    with pytest.raises(ValueError):
        export.export(tmp_path / 'new', 'brick-work/demo')


def test_the_richer_world_is_an_additive_layer_over_the_gates_world(tmp_path):
    """The screen gate renders `dataset.build(path)`: the demo's extra collection must not touch it (approved baselines)."""
    from brickwork.demo import showcase
    for folder in ('plain', 'rich', 'again'):
        (tmp_path / folder).mkdir()
    plain = dataset.build(tmp_path / 'plain' / 'x.db')
    rich = dataset.build(tmp_path / 'rich' / 'x.db', layer=showcase.layer())
    assert plain['copy'] == 19 and plain['wish'] == 6                                            # the gate's world is what it was
    assert rich['copy'] >= 40 and rich['wish'] >= 25 and rich['stock'] > 3 * plain['stock']
    db = sqlite3.connect(tmp_path / 'rich' / 'x.db')
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok' and not db.execute('PRAGMA foreign_key_check').fetchall()
    kinds = dict(db.execute('SELECT kind, count(*) FROM stock WHERE archived_at IS NULL GROUP BY kind'))
    assert all(kinds.get(k) for k in ('part', 'minifigure', 'gear', 'book', 'catalog'))
    assert db.execute('SELECT count(*) FROM wishlist').fetchone()[0] >= 4 and db.execute('SELECT count(*) FROM purchase_order').fetchone()[0] >= 3
    assert db.execute("SELECT count(*) FROM copy WHERE completeness='incomplete'").fetchone()[0] >= 8
    assert not db.execute("SELECT count(*) FROM item WHERE origin='local'").fetchone()[0]
    again = dataset.build(tmp_path / 'again' / 'x.db', layer=showcase.layer())
    assert {k: v for k, v in again.items() if k != 'ids'} == {k: v for k, v in rich.items() if k != 'ids'}   # deterministic
    ids = "SELECT id FROM stock WHERE storage_id IS NOT 'storage-parts-drawer-unit'"       # the base world's own loose stock keeps its random ids
    assert {r[0] for r in db.execute(ids)} == {r[0] for r in sqlite3.connect(tmp_path / 'again' / 'x.db').execute(ids)}


def test_export_without_the_layer_is_the_base_world(tmp_path):
    manifest = export.export(tmp_path / 'plain', BASE, rich=False)
    assert manifest['counts']['copy'] == 19 and '/collection/sets' in manifest['pages']


def test_every_picture_the_world_needs_is_drawn_and_stored_as_a_picture(tmp_path):
    """The demo's pictures are original illustrations (design/demo-art/, scripts/demo_art.py) stored through the app's `picture` table; the gate's world has none."""
    from brickwork.demo import showcase
    assert showcase.missing_pictures() == []
    for folder in ('plain', 'rich'):
        (tmp_path / folder).mkdir()
    dataset.build(tmp_path / 'plain' / 'x.db')
    dataset.build(tmp_path / 'rich' / 'x.db', layer=showcase.layer())
    plain, rich = sqlite3.connect(tmp_path / 'plain' / 'x.db'), sqlite3.connect(tmp_path / 'rich' / 'x.db')
    assert plain.execute('SELECT count(*) FROM picture').fetchone()[0] == 0
    assert rich.execute("SELECT count(*) FROM picture WHERE source='demo_illustration'").fetchone()[0] == rich.execute('SELECT count(*) FROM picture').fetchone()[0] > 300
    assert rich.execute("SELECT name FROM source WHERE id='demo_illustration'").fetchone()[0] == 'Demo illustration'
    for (path,) in rich.execute('SELECT local_path FROM picture'):
        assert (tmp_path / 'rich' / path).is_file()
    total = sum(p.stat().st_size for p in showcase.ART.glob('*.png'))
    assert total < 1_500_000 and (showcase.ART / 'README.md').is_file()


def test_the_export_carries_one_file_per_picture(site):
    out, _ = site
    files = list((out / 'manage' / 'images').iterdir())
    assert len(files) > 300 and all(f.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n' for f in files)
    sets = (out / 'collection/sets/index.html').read_text()
    assert f'data-image-base="{BASE}manage/images/0"' in sets
