"""Shared Toni labels and zero-based standalone chart bounds."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from brickwork.web.formatting import (
    money, short_date, source_label, source_line, missing_counts, watch_scale,
    nowrap_tail, ratio,
)


@pytest.mark.parametrize('value,currency,signed,expected', [
    (5.9, 'EUR', False, '€5.90'), (48, 'EUR', False, '€48'),
    (5.9, 'EUR', True, '€5.90 above'), (-5.9, 'EUR', True, '€5.90 below'),
    (0, 'EUR', True, '€0'), (53.9, 'USD', False, '$53.90'),
    (48, 'GBP', False, '£48'), (12.5, 'CHF', False, 'CHF 12.50'),
    (12.5, '€', False, '€12.50'), (None, 'EUR', False, '—'),
])
def test_money(value, currency, signed, expected):
    assert money(value, currency, signed) == expected


@pytest.mark.parametrize('value,expected', [
    ('2026-10-04T21:07:07.613393+00:00', '4 Oct 2026'),
    ('2026-10-04T21:07:07Z', '4 Oct 2026'),
    ('2026/10/04', '4 Oct 2026'), ('2026-10-04', '4 Oct 2026'),
    (None, 'Date not recorded'), ('invalid', 'Date not recorded'),
])
def test_short_date(value, expected):
    assert short_date(value) == expected


@pytest.mark.parametrize('source,label,qualifier', [
    ('bricklink_stock', 'BrickLink', ' · listings, not sales'),
    ('bricklink', 'BrickLink', ' · sold average'),
    ('brickset', 'Brickset', ''), ('manual', 'Manual', ''),
])
def test_source_line(source, label, qualifier):
    assert source_label(source) == label
    assert source_line(dict(source=source, slot='bricklink_used',
                            observed_at='2026-10-04T21:07:07+00:00')) == (
        label + ' used' + qualifier + ' · 4 Oct 2026')


@pytest.mark.parametrize('parts,figures,expected', [
    (0, 0, ''), (1, 0, '1 part missing'), (0, 1, '1 figure missing'),
    (1, 1, '1 part missing / 1 figure missing'),
    (2, 3, '2 parts missing / 3 figures missing'),
])
def test_missing_counts(parts, figures, expected):
    assert missing_counts(parts, figures) == expected


@pytest.mark.parametrize('observed,maximum,expected', [
    (53.9, 48, 70), (48, 53.9, 70), (0, 0, 1), (0, 48, 60),
    (5, 0, 7), (0.5, 0.4, 0.7), (469.1, 48, 600),
])
def test_watch_scale(observed, maximum, expected):
    scale = watch_scale(observed, maximum)
    assert scale == pytest.approx(expected)
    assert scale >= 1.25 * max(observed, maximum)


@pytest.mark.parametrize('value,expected', [
    ('82.39', '€82.39'), (189, '€189.00'), ('12.5144', '€12.51'), (None, '—'),
    ('Unpriced', 'Unpriced'), (-5.9, '€5.90 below'), ('NaN', 'NaN'),
])
def test_collection_shared_money(value, expected):
    assert money(value, 'EUR', fixed=True) == expected



def test_money_unknown_currency_stays_labelled():
    assert money('12.35', 'Currency not recorded', fixed=True) == 'Currency not recorded 12.35'
    assert money('text', 'EUR') == 'text'


@pytest.mark.parametrize('currency,prefix', [
    ('EUR', '€'), ('USD', '$'), ('GBP', '£'),
    ('€', '€'), ('$', '$'), ('£', '£'),
])
@pytest.mark.parametrize('value,signed,expected', [
    (189, False, '{prefix}189.00'),
    (-5.9, False, '{prefix}5.90 below'),
    (5.9, True, '{prefix}5.90 above'),
    (-5.9, True, '{prefix}5.90 below'),
])
def test_fixed_symbol_money(currency, prefix, value, signed, expected):
    assert money(value, currency, signed=signed, fixed=True) == expected.format(prefix=prefix)


@pytest.mark.parametrize('currency,expected', [
    ('chf', 'CHF 12.35'), ('Chf', 'CHF 12.35'), ('CHF', 'CHF 12.35'),
    ('Currency not recorded', 'Currency not recorded 12.35'),
    ('eur', '€12.35'), ('', '12.35'),
])
@pytest.mark.parametrize('fixed', [False, True])
def test_label_money(currency, expected, fixed):
    assert money('12.35', currency, fixed=fixed) == expected


@pytest.mark.parametrize('value,expected', json.loads(
    Path(__file__).with_name('toni_name_tail_cases.json').read_text()))
def test_nowrap_tail(value, expected):
    assert nowrap_tail(value) == expected


@pytest.mark.parametrize('value,expected', [
    ('NaN', 'NaN'), (float('nan'), 'nan'), ('Infinity', 'Infinity'),
    (float('inf'), 'inf'), ('-Infinity', '-Infinity'), ('text', 'text'),
    (None, '—'), ('', '—'), (0, '0.00 gained per 1 spent'),
    (-.15, '0.15 lost per 1 spent'),
])
def test_ratio_invalid_and_unsigned_values(value, expected):
    assert ratio(value) == expected


def test_name_tail_bundles_runtime():
    if not shutil.which('node'):
        pytest.skip('Node is unavailable')
    subprocess.run(['node', str(Path(__file__).with_name('toni_formatting_runtime.cjs'))],
                   check=True)


def test_short_date_saved_time():
    from datetime import datetime
    assert short_date(datetime.now().replace(hour=14, minute=20), with_time=True) == 'today, 14:20'
    assert short_date('2020-10-16T14:20:00', with_time=True) == '16 Oct, 14:20'
    assert short_date(None, with_time=True) == 'Date not recorded'
