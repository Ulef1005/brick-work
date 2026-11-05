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
    from brickwork.demo import showcase
    checks = manifest['counts']['checks']
    first, half, gaps, clean = (showcase.uid('copy', n, 'a') for n in ('99120-1', '99106-1', '99103-1', '99101-1'))
    assert checks[first][0] == 0
    assert 0 < checks[half][0] < checks[half][1]
    assert all(c == n for c, n in (checks[gaps], checks[clean]))
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


def test_the_demo_world_is_the_invented_collection_only(tmp_path):
    """The gate renders `dataset.build(path)`; the public demo (the layer) holds none of the fixture's real-named sets, figures, wishes or licensed parts."""
    from brickwork.demo import showcase
    for folder in ('plain', 'rich', 'again'):
        (tmp_path / folder).mkdir()
    plain = dataset.build(tmp_path / 'plain' / 'x.db')
    rich = dataset.build(tmp_path / 'rich' / 'x.db', layer=showcase.layer())
    assert plain['copy'] == 19 and plain['wish'] == 6                                            # the gate's world is what it was
    assert rich['copy'] >= 25 and rich['wish'] >= 20 and rich['stock'] > plain['stock']
    db = sqlite3.connect(tmp_path / 'rich' / 'x.db')
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok' and not db.execute('PRAGMA foreign_key_check').fetchall()
    kinds = dict(db.execute('SELECT kind, count(*) FROM stock WHERE archived_at IS NULL GROUP BY kind'))
    assert all(kinds.get(k) for k in ('part', 'minifigure', 'gear', 'book', 'catalog'))
    assert db.execute('SELECT count(*) FROM wishlist').fetchone()[0] >= 4 and db.execute('SELECT count(*) FROM purchase_order').fetchone()[0] >= 3
    assert db.execute("SELECT count(*) FROM copy WHERE completeness='incomplete'").fetchone()[0] >= 8
    assert not db.execute("SELECT count(*) FROM item WHERE origin='local'").fetchone()[0]
    # nothing real-named or licensed: no fixture set or figure, and no name the licence rule rejects
    fixture = {r['set'] for r in dataset.load('sets.json')} | {r['set'] for r in dataset.load('wishlist.json')}
    catalogue = sqlite3.connect(tmp_path / 'rich' / 'catalogue.db')
    for name, key, namespace in catalogue.execute('SELECT name, born_key, born_namespace FROM item'):
        assert not showcase.LICENCED.search(name), name
        assert key not in fixture, key
        if namespace == 'minifigs':
            assert key.startswith('fig-99'), key
        if namespace == 'sets':
            assert key.startswith('99'), key
    assert not [n for (n,) in catalogue.execute("SELECT name FROM item WHERE born_namespace='parts'") if showcase.PRINTED.search(n) and 'Minifig' not in n and 'Hips' not in n and 'Torso' not in n]
    again = dataset.build(tmp_path / 'again' / 'x.db', layer=showcase.layer())
    assert {k: v for k, v in again.items() if k != 'ids'} == {k: v for k, v in rich.items() if k != 'ids'}   # deterministic
    ids = "SELECT id FROM stock WHERE storage_id IS NOT 'storage-parts-drawer-unit'"       # loose stock the base fill adds keeps its random ids
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


def test_the_export_carries_one_png_per_picture(site):
    out, _ = site
    files = list((out / 'manage' / 'images').iterdir())
    assert len(files) > 300 and all(f.suffix == '.png' and f.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n' for f in files)
    sets = (out / 'collection/sets/index.html').read_text()
    assert f'data-image-base="{BASE}manage/images/0"' in sets                  # the pages' scripts build <base><id>?w=...
    shim = (out / 'demo-shim.js').read_text()
    assert "'.png'" in shim and 'HTMLImageElement.prototype' in shim and 'manage\\/images' in shim.replace('\\\\', '\\')
    assert not any(re.search(r'manage/images/[1-9][0-9]*(\?|")', p.read_text()) for p in (out / 'workbench').rglob('index.html'))   # src and srcset both name the .png
    detail = (out / 'collection/item').glob('*/index.html')
    assert any(re.search(r'src="' + re.escape(BASE) + r'manage/images/[1-9][0-9]*\.png"', p.read_text()) for p in detail)


def test_every_item_the_world_shows_has_its_picture_row_and_its_exported_file(tmp_path, site):
    """A figure, set, part or other item without its illustration shows the app's error tile: each item the pages can show has a picture row, and every row's file is in the export."""
    from brickwork.demo import showcase
    out, manifest = site
    (tmp_path / 'w').mkdir()
    dataset.build(tmp_path / 'w' / 'x.db', layer=showcase.layer())
    db = sqlite3.connect(tmp_path / 'w' / 'x.db')
    db.execute('ATTACH ? AS catalogue', (str(tmp_path / 'w' / 'catalogue.db'),))
    shown = db.execute("""SELECT DISTINCT i.born_key FROM (SELECT item_id FROM copy UNION SELECT item_id FROM stock UNION SELECT item_id FROM wish
                          UNION SELECT item_id FROM copy_figure) w JOIN main.item i ON i.id = w.item_id
                          WHERE i.kind IN ('set', 'minifigure', 'gear', 'book', 'catalog')""").fetchall()
    pictured = {k for (k,) in db.execute('SELECT i.born_key FROM picture p JOIN main.item i ON i.id = p.item_id')}
    assert shown and {k for (k,) in shown} <= pictured, sorted({k for (k,) in shown} - pictured)
    assert manifest['counts']['pictures'] == db.execute('SELECT count(*) FROM picture').fetchone()[0] == len(list((out / 'manage' / 'images').iterdir()))
    assert all((showcase.ART / f).is_file() for (f,) in db.execute("SELECT replace(local_path, 'data/images/', '') FROM picture"))


def test_no_host_path_reaches_the_export_and_check_covers_every_text_file(tmp_path, site):
    """The Catalogues & keys page prints the store and media paths: the export shows a fixed neutral root, never the build's scratch folder; check() scans every text file."""
    out, manifest = site
    assert '/manage/catalogues' in manifest['pages']
    page = (out / manifest['pages']['/manage/catalogues'] / 'index.html').read_text()
    assert export.NEUTRAL_ROOT + '/brickwork.db' in page and export.NEUTRAL_ROOT + '/data' in page
    for path in out.rglob('*'):
        if path.is_file() and path.suffix in export.TEXT:
            assert not export.HOST_PATH.search(path.read_text(encoding='utf-8', errors='replace')), path.relative_to(out)
    assert export.check(out) == []
    for name in ('manage/tools/index.html', 'data/0001.json', 'static/app.js', 'demo-shim.js'):
        bad = tmp_path / name.replace('/', '_')
        folder = tmp_path / ('site-' + bad.name)
        (folder / 'static').mkdir(parents=True)
        (folder / 'manage' / 'tools').mkdir(parents=True)
        (folder / 'data').mkdir()
        (folder / 'demo-shim.js').write_text('')
        (folder / name).write_text('<p>/private/var/folders/xx/T/tmpabcd1234/brickwork.db</p>' if name.endswith('.html') else '"/var/folders/xx/T/tmpabcd1234"')
        assert any('host path' in f for f in export.check(folder)), name


def test_the_crawl_never_stops_silently_and_the_cache_buster_is_content_derived(site, monkeypatch, tmp_path):
    out, manifest = site
    assert manifest['counts']['crawl_limit'] == export.LIMIT and len(manifest['pages']) < export.LIMIT and manifest['skipped'] == {}
    assert len(manifest['pages']) > 1000                                                        # every item page the lists link to is exported, so no visible link is dead
    versions = set(re.findall(r'\.css\?v=([0-9a-z]+)', (out / 'collection/sets/index.html').read_text()))
    assert len(versions) == 1 and re.fullmatch(r'[0-9a-f]{12}', versions.pop())
    monkeypatch.setattr(export, 'LIMIT', 60)
    with pytest.raises(RuntimeError, match='reached its limit'):
        export.export(tmp_path / 'cut', BASE)
