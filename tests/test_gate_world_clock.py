"""Every timestamp in the screen gate's worlds stands on the demo clock (#207; ADR 0022, ADR 0024).

`checks.stage` once ran before `freeze_clock()` in `scripts/screen_gate.py` `world()`, so the staged checks carried the build time and a baseline
differed every day (#204, fixed in 0c422e4). That showed up as a 0.05 % pixel difference after a long CI run. This test builds the 'demo' and
the 'showcase' world through `screen_gate.world()` itself (no second copy of the setup), opens the stores it built and looks at every column
that holds a timestamp, in every table of the collection and of the catalogue. Each value must be `clock.FIXED_NOW`, a date the dataset sets
on purpose (HISTORY below) or a stamp of a column already known to carry the build time (BUILD_TIME below). Anything else fails at once,
naming the table, the column, a sample value and how many rows.

A timestamp column is found two ways: by name (`*_at`, `*_on`, `*_date`, `date_*`, `created`, `updated`) and by value (any TEXT value that is a
whole ISO 8601 date or date-time, whatever the column is called; `meta.value` is one). A name-matched column whose value is not ISO 8601 fails too.

The world's folder is the gate's shared one, so the module is in the `rendered` group (tests/rendered.py); it does not need Chrome."""
import datetime as dt
import re
import sqlite3
import tempfile
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path

import pytest

from brickwork.demo.clock import FIXED_NOW
from scripts import screen_gate as gate
from tests import rendered

pytestmark = rendered.group

# Without fcntl (Windows) the gate's world lives in a random folder, not under the shared name this test reads; the gate itself is Linux and macOS only.
fcntl = pytest.importorskip('fcntl', reason='the gate world has a fixed folder only where fcntl exists')

NAMED = re.compile(r'(_at|_on|_date|created|updated)$|^(at|date_.+)$')
ISO = re.compile(r'^\d{4}-\d\d-\d\d([T ]\d\d:\d\d(:\d\d(\.\d+)?)?(Z|[+-]\d\d:?\d\d)?)?$')

# Dated history the dataset sets on purpose: the invented collection's purchase dates, the order dates and the price quotes' observation days.
# They lie before the dataset's "now", and the test data's last quotes up to two days after it. The ceiling is a week past FIXED_NOW: a stamp
# of the real clock is always later than that (the clock is frozen at 2026-10-12), so none can hide here.
HISTORY = {
    ('copy', 'purchase_date'): 'the invented purchase dates of the owned sets (design/sources/test-data/sets.json)',
    ('purchase_order', 'date_ordered'): 'the showcase layer\'s three invented orders (showcase.py), 2026-09-28 to 2026-10-10',
    ('price_observation', 'observed_at'): 'the sold-guide quotes and price history of the test data, a day or two either side of the dataset\'s now',
}
CEILING = FIXED_NOW + dt.timedelta(days=7)

# KNOWN LEAK: these columns are written by the app's own add/ensure/project calls while dataset.build() runs, which is before world() freezes the
# clock, so they carry the moment of the build, not FIXED_NOW. No approved screen shows them (the gate's baselines do not move from day to day),
# so nothing breaks yet, but a screen that starts to show one will differ on every run. Each entry may only hold a stamp taken during this test's
# own build window (checked below), so a wrong stamp cannot hide behind it. Remove an entry when its column is fixed (freeze the clock before
# dataset.build()); the test then holds that column to FIXED_NOW.
BUILD_TIME = {
    ('meta', 'value'): 'the catalogue build time the store records when the catalogue is activated',
    ('catalogue_build', 'activated_at'): 'activate() in dataset.build()',
    ('item', 'created_at'): 'items.ensure() projects each used item into the collection',
    ('item', 'updated_at'): 'items.ensure()',
    ('color', 'created_at'): 'identity.project_color()',
    ('color', 'updated_at'): 'identity.project_color()',
    ('item_link', 'decided_at'): 'the identity link written when an item is projected',
    ('color_link', 'decided_at'): 'the identity link written when a colour is projected',
    ('copy', 'materialised_at'): 'add._add_copy() materialises the copy\'s part list',
    ('copy_figure', 'updated_at'): 'the figure lines materialised with the copy (some are re-stamped to FIXED_NOW afterwards)',
    ('stock', 'created_at'): 'stock.add_loose()',
    ('stock', 'updated_at'): 'stock.add_loose()',
    ('wishlist', 'created_at'): 'the default wishlist, created with the store',
    ('event', 'at'): 'the event log entries the add and project calls append',
}


def parse(value) -> dt.datetime | None:
    """A stored ISO 8601 date or date-time as an aware UTC datetime, or None when it is not one."""
    if not isinstance(value, str) or not ISO.match(value):
        return None
    text = value.replace(' ', 'T').replace('Z', '+00:00')
    try:
        stamp = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)


def stores(folder: Path):
    """(label, path) of the world's databases: the collection and its catalogue."""
    for name in ('brickwork.db', 'catalogue.db'):
        if (folder / name).exists():
            yield name.removesuffix('.db'), folder / name


def timestamp_values(path: Path, label: str):
    """(table, column, value) of every value in a timestamp column of every table of one database."""
    with closing(sqlite3.connect(f'file:{path}?mode=ro', uri=True)) as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            for _, column, kind, *_ in db.execute(f'PRAGMA table_info("{table}")').fetchall():
                if kind.upper() == 'BLOB':
                    continue
                named = bool(NAMED.search(column))
                for (value,) in db.execute(f'SELECT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL'):
                    if named or (isinstance(value, str) and ISO.match(value)):
                        yield (table if label == 'brickwork' else f'{label}.{table}'), column, value


def problems(folder: Path, built_from: dt.datetime, built_to: dt.datetime) -> list[str]:
    bad = defaultdict(Counter)
    for label, path in stores(folder):
        for table, column, value in timestamp_values(path, label):
            stamp = parse(value)
            key = (table.split('.')[-1], column)
            if stamp is None:
                reason = 'not an ISO 8601 date or time'
            elif stamp == FIXED_NOW:
                continue
            elif key in HISTORY and stamp <= CEILING:
                continue
            elif key in BUILD_TIME and built_from <= stamp <= built_to:
                continue
            else:
                reason = f'not clock.FIXED_NOW ({FIXED_NOW.isoformat()})'
            bad[(table, column, reason)][value] += 1
    return [f'{table}.{column}: {sum(values.values())} value(s) {reason}, e.g. {values.most_common(1)[0][0]!r}'
            for (table, column, reason), values in sorted(bad.items())]


@pytest.mark.parametrize('name', ['demo', 'showcase', 'extras', 'edge', 'edge-empty'])
def test_every_timestamp_in_the_gate_world_is_the_demo_clock(name):
    built_from = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=2)
    with gate.world(name):
        folder = Path(tempfile.gettempdir()) / 'bw-gate-world'
        assert (folder / 'brickwork.db').exists(), 'the gate world keeps its store at <tmp>/bw-gate-world (screen_gate.world_folder)'
        found = problems(folder, built_from, dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=2))
    assert not found, (f'the {name} world carries a timestamp that is not the demo clock; something wrote a stamp before screen_gate.world() '
                       'froze the clock (or did not use brickwork.demo.clock). A baseline then differs from day to day:\n  ' + '\n  '.join(found))
