"""Shipped mapping files, their reader, the leg rule and the build script (design 3.2, 3.3, 3.4, 3.7)."""
import csv
import gzip
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from brickwork.store4.mappings import MAPPINGS_DIR, leg_rule, read_mapping

ROOT = Path(__file__).resolve().parent.parent
SHIPPED = ('colors.csv', 'parts.csv', 'set_exceptions.csv', 'theme_kinds.csv')


def load_build():
    spec = importlib.util.spec_from_file_location('build_mappings', ROOT / 'scripts' / 'build_mappings.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_no_minifig_mapping_ships():
    # Until the public-flip decision changes this test (design 3.4): the BrickStore-derived figure mapping stays out of the repo.
    assert not (MAPPINGS_DIR / 'minifigs.csv').exists()
    tracked = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    assert [t for t in tracked if Path(t).name == 'minifigs.csv'] == []


def test_shipped_files_read_with_one_version():
    metas = {name: read_mapping(MAPPINGS_DIR / name)[0] for name in SHIPPED}
    assert len({(m['mapping_version'], m['dump_date']) for m in metas.values()}) == 1
    assert 'Rebrickable' in metas['colors.csv']['source']
    for name in ('colors.csv', 'parts.csv'):
        assert metas[name]['external_ids_fetched']
    assert 'external_ids_fetched' not in metas['set_exceptions.csv']


def test_static_files():
    assert read_mapping(MAPPINGS_DIR / 'set_exceptions.csv')[1] == []
    assert read_mapping(MAPPINGS_DIR / 'theme_kinds.csv')[1] == [
        {'rb_theme_id': '501', 'theme_name': 'Gear', 'kind': 'gear'}, {'rb_theme_id': '497', 'theme_name': 'Books', 'kind': 'book'}]


@pytest.fixture(scope='module')
def colors():
    return read_mapping(MAPPINGS_DIR / 'colors.csv')[1]


def bricklink(colors, rb_id):
    return [r for r in colors if r['rb_color_id'] == str(rb_id) and r['provider'] == 'bricklink']


def test_journey_colours(colors):
    # user-journey.md line 17 and 19 (Rebrickable id -> BrickLink id and name): White 15->1, Black 0->11, Red 4->5, Yellow 14->3,
    # Dark Gray 8->10, Light Gray 7->9, Dark Brown 308->120, Warm Pink 1146 present; design 3.7 / journey line 73: BrickLink 72, 77.
    for rb, bl, name in ((15, '1', 'White'), (0, '11', 'Black'), (4, '5', 'Red'), (14, '3', 'Yellow'), (8, '10', 'Dark Gray'),
                         (7, '9', 'Light Gray'), (308, '120', 'Dark Brown')):
        (row,) = bricklink(colors, rb)
        assert (row['provider_key'], row['provider_name'], row['inverse_preferred']) == (bl, name, '0')
    assert len(bricklink(colors, 1146)) == 1


def test_inverse_preferred(colors):
    shared = {}
    for r in colors:
        shared.setdefault((r['provider'], r['provider_key']), []).append(r)
    for rows in shared.values():
        assert sum(r['inverse_preferred'] == '1' for r in rows) == (1 if len(rows) > 1 else 0)
    pick = {k: next(r for r in v if r['inverse_preferred'] == '1')['rb_name'] for k, v in shared.items() if len(v) > 1}
    assert pick[('bricklink', '72')] == 'Pastel Blue'
    assert pick[('bricklink', '77')] == 'Pearl Titanium'
    assert {r['rb_color_id'] for r in shared[('bricklink', '72')]} == {'313', '1051'}


def test_leg_rule_example():
    colors = [dict(rb_color_id='0', rb_name='Black', provider='bricklink', provider_key='11', inverse_preferred='0'),
              dict(rb_color_id='0', rb_name='Black', provider='lego', provider_key='26', inverse_preferred='0'),
              dict(rb_color_id='4', rb_name='Red', provider='bricklink', provider_key='5', inverse_preferred='0')]
    parts = [('970c03', 'Hips and Black Legs'), ('970c22', 'Hips and Red Legs [Plain]'), ('970c03pat01', 'Hips and Black Legs'),
             ('970c99', 'Hips and Mauve Legs'), ('3023', 'Plate 1 x 2'), ('970c98', 'Torso')]
    rows = [(r['rb_part_num'], r['rb_color_id'], r['provider_key']) for r in leg_rule(parts, colors)]
    assert rows == [('970c03', '0', '970c00'), ('970c03', '', '970c11'), ('970c22', '4', '970c00'), ('970c22', '', '970c05')]
    first = next(leg_rule(parts, colors))
    assert (first['provider'], first['provider_kind'], first['status'], first['method']) == ('bricklink', 'P', 'matched', 'leg_rule')


def test_leg_rule_on_shipped_colours(colors):
    parts = [('970c03', 'Hips and Black Legs'), ('970c12', 'Hips and Dark Bluish Gray Legs'), ('970c75', 'Hips and Pearl Titanium Legs [Plain]'),
             ('970c88', 'Hips and Invented Legs')]
    got = {(r['rb_part_num'], r['rb_color_id']): r['provider_key'] for r in leg_rule(parts, colors)}
    assert got == {('970c03', '0'): '970c00', ('970c03', ''): '970c11', ('970c12', '72'): '970c00', ('970c12', ''): '970c85',
                   ('970c75', '1103'): '970c00', ('970c75', ''): '970c77'}


def test_read_mapping_refusals(tmp_path):
    ok = '# mapping_version: 1\n# dump_date: 2026-10-23\nrb_theme_id,theme_name,kind\n501,Gear,gear\n'
    cases = {'theme_kinds.csv': ok.replace('# mapping_version: 1\n', ''), 'colors.csv': ok, 'other.csv': ok}
    for name, text in cases.items():
        (tmp_path / name).write_text(text)
        with pytest.raises(ValueError, match=name):
            read_mapping(tmp_path / name)
    (tmp_path / 'theme_kinds.csv').write_text(ok.replace('# dump_date: 2026-10-23\n', ''))
    with pytest.raises(ValueError, match='dump_date'):
        read_mapping(tmp_path / 'theme_kinds.csv')
    (tmp_path / 'theme_kinds.csv').write_text(ok)
    assert read_mapping(tmp_path / 'theme_kinds.csv')[1] == [{'rb_theme_id': '501', 'theme_name': 'Gear', 'kind': 'gear'}]


def gz(path, header, rows):
    with gzip.open(path, 'wt', newline='') as f:
        csv.writer(f, lineterminator='\n').writerows([header] + rows)


def make_inputs(root):
    (root / 'dump').mkdir(parents=True)
    gz(root / 'dump' / 'colors.csv.gz', ['id', 'name', 'rgb', 'is_trans', 'num_parts', 'num_sets', 'y1', 'y2'],
       [['0', 'Black', '000000', 'f', '100', '1', '1990', '2026'], ['5', 'Dark Pink', 'FF0000', 'f', '10', '1', '1990', '2026'],
        ['6', 'Twin A', '111111', 'f', '50', '1', '1990', '2026'], ['7', 'Twin B', '222222', 'f', '50', '1', '1990', '2026']])
    gz(root / 'dump' / 'elements.csv.gz', ['element_id', 'part_num', 'color_id', 'design_id'],
       [['1', '2339', '0', ''], ['2', '9001', '0', '777'], ['3', '9001', '5', '777'], ['4', '9001', '5', '778']])
    ext = [{'kind': 'color', 'id': '0', 'name': 'Black', 'external_ids': {'BrickLink': {'ext_ids': [11], 'ext_descrs': [['Black']]},
                                                                   'LEGO': {'ext_ids': [26, 342], 'ext_descrs': [['Black', 'BLACK'], ['Cond']]}}},
           {'kind': 'color', 'id': '5', 'name': 'Dark Pink', 'external_ids': {}},
           {'kind': 'color', 'id': '6', 'name': 'Twin A', 'external_ids': {'BrickLink': {'ext_ids': [90], 'ext_descrs': [['Twin']]}}},
           {'kind': 'color', 'id': '7', 'name': 'Twin B', 'external_ids': {'BrickLink': {'ext_ids': [90], 'ext_descrs': [['Twin']]}}},
           {'kind': 'part', 'id': '3023', 'name': 'Plate', 'external_ids': {'BrickLink': ['3023'], 'LDraw': ['3023']}},
           {'kind': 'part', 'id': '003402', 'name': 'Stickers', 'external_ids': {'BrickLink': ['311.1stk01', '310.3stk01']}},
           {'kind': 'part', 'id': '970c03', 'name': 'Hips and Black Legs', 'external_ids': {'BrickLink': ['970c11', '970c03']}},
           {'kind': 'part', 'id': '2339', 'name': 'Brick', 'external_ids': {}},
           {'kind': 'part', 'id': '9001', 'name': 'Odd', 'external_ids': {}}]
    (root / 'external_ids.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in ext))
    (root / 'fetched.json').write_text(json.dumps({'fetched_at': '2026-10-23T17:52:26Z', 'api_calls': 2}))


def test_build_is_deterministic(tmp_path):
    build = load_build()
    make_inputs(tmp_path / 'in')
    args = [str(tmp_path / 'in'), None, '--version', '2026.10.23.1', '--dump-date', '2026-10-23']
    for run in ('a', 'b'):
        args[1] = str(tmp_path / run)
        build.main(list(args))
    for name in ('colors.csv', 'parts.csv'):
        assert (tmp_path / 'a' / name).read_bytes() == (tmp_path / 'b' / name).read_bytes()
    meta, colors = read_mapping(tmp_path / 'a' / 'colors.csv')
    assert meta == {'mapping_version': '2026.10.23.1', 'dump_date': '2026-10-23', 'external_ids_fetched': '2026-10-23T17:52:26Z',
                    'source': 'Rebrickable (https://rebrickable.com), data free to use with acknowledgement'}
    assert [(r['rb_color_id'], r['provider'], r['provider_key'], r['provider_name'], r['inverse_preferred']) for r in colors] == [
        ('0', 'bricklink', '11', 'Black', '0'), ('0', 'lego', '26', 'Black', '0'), ('0', 'lego', '342', 'Cond', '0'),
        ('6', 'bricklink', '90', 'Twin', '1'), ('7', 'bricklink', '90', 'Twin', '0')]
    parts = [(r['rb_part_num'], r['provider_key'], r['status'], r['method'], r['preferred'])
             for r in read_mapping(tmp_path / 'a' / 'parts.csv')[1]]
    assert parts == [('003402', '310.3stk01', 'matched', 'external_ids', '0'), ('003402', '311.1stk01', 'matched', 'external_ids', '0'),
                     ('3023', '3023', 'matched', 'external_ids', '0'),
                     ('9001', '777', 'inferred', 'element', '0'), ('9001', '778', 'inferred', 'element', '0'),
                     ('970c03', '970c03', 'matched', 'external_ids', '1'), ('970c03', '970c11', 'matched', 'external_ids', '0')]
