"""The screen gate's `edge` worlds (#268, decision 595): synthetic data for the approved states that were untested for want of data or a seam.

The approved baselines are Linux renders that cannot be re-made here, so the three older worlds must not change by a single row: the first test
fingerprints their built databases (every table's rows, ids and build-time stamps masked, rows sorted) and compares them with the fingerprints taken
on origin/main before the edge worlds existed. The module is in the `rendered` group: the gate's world folder is shared."""
import datetime as dt
import hashlib
import re
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

from brickwork.demo.clock import FIXED_NOW
from scripts import screen_gate as gate
from tests import rendered

pytestmark = rendered.group

HEX = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{32}|[0-9a-f]{64}')
STAMP = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z')
CEILING = FIXED_NOW + dt.timedelta(days=7)
SKIPPED = {('catalogue.db', 'build')}     # the build row holds the byte sizes of the dump files, which depend on the zlib in use


def mask(value):
    if isinstance(value, bytes):
        return value.hex()
    if not isinstance(value, str):
        return repr(value)
    def late(m):
        return '#T' if dt.datetime.fromisoformat(m.group(0).replace('Z', '+00:00')) > CEILING else m.group(0)   # the build moment: a stamp the demo clock never gives
    return STAMP.sub(late, HEX.sub('#', value))


def fingerprint(name):
    """{database file: {table: sha256 of its sorted, masked rows}} of the world `name` built by the gate's own build_store."""
    result = {}
    with tempfile.TemporaryDirectory() as scratch:
        store = Path(scratch) / 'brickwork.db'
        gate.build_store(name, store)
        for file in ('brickwork.db', 'catalogue.db'):
            with closing(sqlite3.connect(Path(scratch) / file)) as db:
                tables = sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
                result[file] = {}
                for table in tables:
                    if (file, table) in SKIPPED:
                        continue
                    rows = sorted('|'.join(mask(v) for v in row) for row in db.execute(f'SELECT * FROM "{table}"'))
                    result[file][table] = hashlib.sha256('\n'.join(rows).encode()).hexdigest()
    return result


def digest(name):
    prints = fingerprint(name)
    return hashlib.sha256(repr(sorted((f, sorted(t.items())) for f, t in prints.items())).encode()).hexdigest()


# Taken on origin/main (21ac7ce), before the edge worlds were added.
BEFORE = {
    'demo': '7df99615330895f2cb8ef3ac0ab561e214c8c98ad3abbd74634e05e1c6321093',
    'showcase': '92a4f3f53da923af093e09624257e80cf810d610fee70bda7f84d26cd7e833ad',
    'extras': '56b8fc87611dc171e5b55bc9b1ef74ac52c2d44f0e036cb07ea67ad72b211b94',
}


@pytest.mark.parametrize('name', ['demo', 'showcase', 'extras'])
def test_the_older_worlds_are_unchanged(name):
    assert digest(name) == BEFORE[name]


if __name__ == '__main__':
    for world_name in ('demo', 'showcase', 'extras'):
        print(world_name, digest(world_name))
