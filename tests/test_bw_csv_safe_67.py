"""#67: exported CSV cells never run as spreadsheet formulas."""
import csv
import io

import pytest

from brickwork.core import csv_safe, list_exports, order_exports


@pytest.mark.parametrize('text', ['=HYPERLINK("https://example.org","x")', '+1+1', '-2+3', '@SUM(A1)', '\tx', '\rx', '-A1'])
def test_formula_text_is_prefixed(text):
    assert csv_safe.cell(text) == "'" + text


@pytest.mark.parametrize('value', ['Brick 1 x 2', '12.50', '-2.00', '+3', '-7', 3, None, '', 'a=b'])
def test_other_cells_are_unchanged(value):
    assert csv_safe.cell(value) == value


def test_list_export_escapes_a_formula_note():
    rows = [dict(item_type='P', item_no='3001', name='=cmd|calc', colour='Red', color_id=5, condition='U', quantity=2, unresolved=False)]
    parsed = list(csv.reader(io.StringIO(list_exports.to_csv('missing', rows))))
    assert parsed[1][2] == "'=cmd|calc" and parsed[1][6] == '2'


def test_order_export_escapes_a_formula_name():
    data = [dict(label='O1', date='2026-10-01', store='=x', seller=None, item_type='P', item_no='3001', name='@evil', colour=None,
                 color_id=None, condition='N', qty=1, unit_price='0.10', line_total='0.10', currency='EUR')]
    parsed = list(csv.reader(io.StringIO(order_exports.to_csv('lines', data))))
    assert parsed[1][2] == "'=x" and parsed[1][6] == "'@evil"
