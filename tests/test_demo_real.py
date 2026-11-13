"""The real-sets demo world (brickwork/demo/real.py, #332): seven real sets, their Rebrickable part lists, the pictures of the not-MIT folder."""
import json
import sqlite3

from brickwork.demo import dataset, real

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
    assert sorted(manifest) == ['sets/' + n for n in SETS]
    assert all((real.FOLDER / 'images' / f).is_file() for f in manifest.values())
    _, db, _ = build(tmp_path)
    assert db.execute("SELECT count(*) FROM picture WHERE source='rebrickable_images'").fetchone()[0] == db.execute('SELECT count(*) FROM picture').fetchone()[0] >= 7
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
