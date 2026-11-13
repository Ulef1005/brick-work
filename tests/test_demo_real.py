"""The real-sets demo world (brickwork/demo/real.py, #332): seven real sets, their Rebrickable part lists, the pictures of the not-MIT folder."""
import json
import sqlite3

import pytest

from brickwork.demo import dataset, real
from tests import rendered

SETS = ['10210-1', '10254-1', '21028-1', '31120-1', '7213-1', '7938-1', '8043-1']


def build(tmp_path, name='w', **options):
    (tmp_path / name).mkdir()
    counts = dataset.build(tmp_path / name / 'x.db', layer=real.layer(**options))
    return counts, sqlite3.connect(tmp_path / name / 'x.db'), sqlite3.connect(tmp_path / name / 'catalogue.db')


def test_the_world_holds_the_seven_real_sets_and_five_wished_ones(tmp_path):
    counts, db, catalogue = build(tmp_path)
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok' and not db.execute('PRAGMA foreign_key_check').fetchall()
    keys = {k for (k,) in catalogue.execute("SELECT born_key FROM item WHERE born_namespace='sets'")}
    assert keys == set(SETS) | {'6382-1', '6985-1', '6085-1', '6270-1', '6542-1'}                 # no invented 99xxx set
    owned = {k for (k,) in db.execute("SELECT i.born_key FROM copy c JOIN item i ON i.id = c.item_id WHERE c.archived_at IS NULL")}
    assert owned == set(SETS) and counts['copy'] == 8 and counts['wish'] >= 14
    assert db.execute("SELECT count(*) FROM copy WHERE completeness='incomplete'").fetchone()[0] >= 3
    assert db.execute('SELECT count(*) FROM wishlist').fetchone()[0] >= 3 and db.execute('SELECT count(*) FROM purchase_order').fetchone()[0] >= 3
    assert db.execute('SELECT count(*) FROM lot').fetchone()[0] == 1
    figures = [k for (k,) in catalogue.execute("SELECT born_key FROM item WHERE born_namespace='minifigs'")]
    assert figures and not [k for k in figures if k.startswith('fig-99')]                           # the sets' own figures


def test_the_part_lists_are_rebrickables_and_deterministic(tmp_path):
    data = {e['set']: e for e in real.snapshot()['sets']}
    assert sorted(data) == SETS
    first, db, _ = build(tmp_path, 'a')
    second, other, _ = build(tmp_path, 'b')
    assert {k: v for k, v in first.items() if k != 'ids'} == {k: v for k, v in second.items() if k != 'ids'}
    assert first['ids'] == second['ids']
    lines = db.execute("SELECT count(*) FROM copy_part cp JOIN copy c ON c.id = cp.copy_id WHERE cp.copy_figure_id IS NULL AND cp.retired_at IS NULL").fetchone()[0]
    assert lines >= sum(len([r for r in e['parts_list']]) for n, e in data.items() if n != '10254-1') * 0.9   # one line per catalogue line (the sealed copy keeps its list too)
    ids = "SELECT id FROM stock WHERE storage_id IS NOT 'storage-parts-drawer-unit'"
    assert {r[0] for r in db.execute(ids)} == {r[0] for r in other.execute(ids)}


def test_each_set_has_its_picture_and_every_picture_has_a_file(tmp_path):
    manifest = real.pictures_manifest()
    assert {k for k in manifest if k.startswith('sets/')} == {'sets/' + n for n in SETS}
    assert {k for k in manifest if not k.startswith('sets/')} == {'parts/33299a/71', 'parts/62462/25', 'parts/87619/15', 'parts/91968c01/0', 'parts/2527/4', 'parts/3665/71', 'parts/4865b/19', 'parts/48336/14', 'parts/6091/14', 'parts/3633/72', 'minifigs/fig-004770'}
    assert all((real.FOLDER / 'images' / f).is_file() for f in manifest.values())
    _, db, _ = build(tmp_path)
    assert db.execute("SELECT count(*) FROM picture WHERE source='rebrickable_images'").fetchone()[0] == db.execute('SELECT count(*) FROM picture').fetchone()[0] == len(manifest)   # every manifest entry matched an item
    assert db.execute("SELECT name FROM source WHERE id='rebrickable_images'").fetchone()[0] == 'Rebrickable'
    for (path,) in db.execute('SELECT local_path FROM picture'):
        assert (tmp_path / 'w' / path).is_file()
    for (width, height) in db.execute('SELECT width, height FROM picture'):
        assert width and height


def test_without_pictures_the_world_is_the_same(tmp_path):
    with_pictures, _, _ = build(tmp_path, 'a')
    without, db, _ = build(tmp_path, 'b', pictures=False)
    assert db.execute('SELECT count(*) FROM picture').fetchone()[0] == 0
    assert {k: v for k, v in with_pictures.items() if k != 'ids'} == {k: v for k, v in without.items() if k != 'ids'}


def test_the_not_mit_folder_carries_its_notice_and_stays_out_of_the_image():
    root = real.FOLDER.parents[1]
    notice = (root / 'not-mit' / 'NOTICE.md').read_text()
    assert 'not' in notice.splitlines()[0].lower() and 'Rebrickable' in notice and 'LEGO' in notice
    assert 'not-mit/' in (root / '.dockerignore').read_text().splitlines()
    assert 'not-mit/NOTICE.md' in (root / 'THIRD_PARTY_NOTICES.md').read_text() and 'not-mit/NOTICE.md' in (root / 'README.md').read_text()
    assert 'sets' in json.loads((real.FOLDER / 'sets.json').read_text())


def test_the_real_world_exports_with_jpeg_pictures(tmp_path):
    """The export keeps each picture's own extension: the real sets' JPEGs are `<id>.jpg`, listed in the manifest for the shim; the showcase's PNGs stay `.png`."""
    import re
    from brickwork.demo import export
    base = '/brick-work/demo/'
    manifest = export.export(tmp_path / 'site', base, world='real')
    out = tmp_path / 'site'
    pictures = real.pictures_manifest()
    assert manifest['counts']['pictures'] == len(pictures) == 18 and manifest['counts']['copy'] == 8      # 7 sets, 1 figure, 10 parts
    files = {f.stem: f for f in (out / 'manage' / 'images').iterdir()}
    assert len(files) == 18
    jpegs = {i for i, f in files.items() if f.suffix == '.jpg'}
    assert len(jpegs) == 8 and all(files[i].read_bytes()[:2] == b'\xff\xd8' for i in jpegs)             # the sets and the figure
    assert all(f.suffix == '.png' and f.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n' for i, f in files.items() if i not in jpegs)   # the part renders
    assert manifest['pictures'] == {i: 'jpg' for i in jpegs}                                            # only the non-PNG ones are listed for the shim
    assert 'kindOf' in (out / 'demo-shim.js').read_text() and '"pictures"' in (out / 'demo-shim.js').read_text()
    pages = list((out / 'collection').rglob('index.html'))
    assert any(re.search(r'src="' + re.escape(base) + r'manage/images/[1-9][0-9]*\.jpg"', p.read_text()) for p in pages)
    named = set()
    for page in pages:   # every picture a page names has the extension of its file
        for number, extension in re.findall(r'manage/images/([1-9][0-9]*)\.(png|jpg)', page.read_text()):
            assert files[number].suffix == '.' + extension, (page, number)
            named.add(extension)
    assert named == {'png', 'jpg'}   # a part render and a set picture are both shown


@rendered.group
def test_a_capture_fails_on_a_missing_picture_tile(tmp_path):
    """#332: no capture shows a placeholder. `no_tiles` passes a page whose pictures are all there (the sets) and fails one that shows the app's tile (the
    loose parts have no picture yet)."""
    import subprocess
    from scripts import screen_gate
    chrome = rendered.chrome()
    with screen_gate.world('real') as base:
        def capture(path):
            jobs = {'jobs': [{'url': base + path, 'out': str(tmp_path / 'x.png'), 'width': 1440, 'height': 900, 'theme': 'light', 'no_tiles': True}]}
            (tmp_path / 'jobs.json').write_text(json.dumps(jobs))
            return subprocess.run(['node', str(real.FOLDER.parents[1] / 'scripts' / 'capture_screens.cjs'), chrome, str(tmp_path / 'jobs.json')], capture_output=True, text=True)
        assert capture('/collection/sets').returncode == 0
        failed = capture('/collection/P')
        assert failed.returncode != 0 and 'no_tiles' in (failed.stderr + failed.stdout)


def test_size_of_reads_png_and_jpeg_headers_and_refuses_the_rest(tmp_path):
    import struct
    png = tmp_path / 'a.png'
    png.write_bytes(b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR' + struct.pack('>II', 30, 20))
    assert real.size_of(png) == (30, 20)
    frame = b'\xff\xc2' + struct.pack('>HBHHB', 11, 8, 40, 60, 1) + b'\0\0\0'                   # a progressive frame header: 60 wide, 40 high
    jpeg = tmp_path / 'a.jpg'
    jpeg.write_bytes(b'\xff\xd8\xff\xff\xe0' + struct.pack('>H', 4) + b'\0\0' + b'\xff\xd0' + frame)   # a fill byte, an APP0 segment, a standalone marker
    assert real.size_of(jpeg) == (60, 40)
    for name, body in (('empty.jpg', b''), ('cut.jpg', b'\xff\xd8\xff\xe0\x00'), ('text.png', b'not a picture at all, long enough to pass any length check')):
        (tmp_path / name).write_bytes(body)
        with pytest.raises(ValueError):
            real.size_of(tmp_path / name)
    assert real.size_of(real.FOLDER / 'images' / 'sets' / '31120-1.jpg') == (900, 668)
