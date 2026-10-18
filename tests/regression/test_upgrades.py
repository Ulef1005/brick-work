"""Upgrade regression: every frozen store from history opens on today's code without losing a row.

Fixtures come from scripts/make_regression_fixtures.py (each built by that commit's own code, with
the same invented rows). On every gate run each is copied, opened by today's connect() (which runs
every pending upgrade), and compared with its own contents before the upgrade. A real store can be
checked the same way: BW_REGRESSION_DB=/path/to/brickwork.db (a copy is used; the file is never opened
for writing).
"""
from contextlib import closing
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3

import pytest

from brickwork.core import upgrade
from brickwork.core.connect import connect

FIXTURES = sorted((Path(__file__).parent / 'fixtures').glob('*.db'))
# Tables whose rows an upgrade may legitimately add to (derived indexes, caches, audit of the upgrade).
GROWS = {'events', 'search_index', 'search_index_data', 'search_index_idx', 'search_index_docsize', 'search_index_config',
         'search_index_content', 'sqlite_stat1', 'sqlite_stat4', 'settings', 'source_freshness', 'sources', 'wishlists',
         'schema_meta', 'exchange_rates'}


def snapshot(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        counts = {t: db.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}
        rows = {}
        for t in ('copies', 'copy_parts', 'copy_minifigs', 'loose_stock', 'lots', 'storages', 'purchase_locations',
                  'wishlist', 'flags', 'item_flags', 'items', 'colors'):
            if t in tables:
                columns = [r[1] for r in db.execute(f'PRAGMA table_info("{t}")')]
                rows[t] = (columns, sorted(tuple(map(str, r)) for r in db.execute(f'SELECT * FROM "{t}"')))
        return counts, rows


def dump(path):
    with closing(sqlite3.connect(path)) as db:
        return hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest()


def check(source, tmp_path):
    work = tmp_path / 'brickwork.db'
    shutil.copy(source, work)
    before_counts, before_rows = snapshot(work)
    with closing(connect(work)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert not upgrade.pending(db)
    after_counts, after_rows = snapshot(work)
    for table, count in before_counts.items():
        assert table in after_counts, f'{table} disappeared'
        if table not in GROWS:
            assert after_counts[table] == count, f'{table}: {count} rows before, {after_counts[table]} after'
    for table, (columns, rows) in before_rows.items():
        new_columns, new_rows = after_rows[table]
        assert set(columns) <= set(new_columns), f'{table} lost columns {set(columns) - set(new_columns)}'
        # Each old row survives with its old values (new columns are additions at the end or by name).
        keep = [new_columns.index(c) for c in columns]
        assert sorted(tuple(r[i] for i in keep) for r in new_rows) == rows, f'{table} rows changed'
    once = dump(work)
    with closing(connect(work)) as db:
        assert not upgrade.pending(db)
    assert dump(work) == once, 'a second open changed the store'
    return work


@pytest.mark.parametrize('fixture', FIXTURES, ids=[f.stem for f in FIXTURES])
def test_history_upgrades_without_loss(fixture, tmp_path):
    work = check(fixture, tmp_path)
    with closing(connect(work)) as db:
        # Today's shape is there: named wishlists, storage fields, filled override, exchange rates.
        assert db.execute("SELECT count(*) FROM wishlist WHERE list_id='default'").fetchone()[0] == 2
        assert {'type', 'parent_id', 'note'} <= {r[1] for r in db.execute('PRAGMA table_info(storages)')}
        assert 'qty_filled_manual' in {r[1] for r in db.execute('PRAGMA table_info(wishlist)')}
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='exchange_rates'").fetchone()
        assert db.execute("SELECT version FROM schema_meta").fetchone()[0] == '3.3'


@pytest.mark.parametrize('fixture', FIXTURES, ids=[f.stem for f in FIXTURES])
def test_read_only_open_leaves_an_old_store_untouched(fixture, tmp_path):
    work = tmp_path / 'brickwork.db'
    shutil.copy(fixture, work)
    before = hashlib.sha256(work.read_bytes()).hexdigest()
    os.chmod(work, 0o444)
    try:
        with closing(connect(work, read_only=True)) as db:
            assert db.execute('SELECT count(*) FROM copies').fetchone()[0] == 2
    except sqlite3.Error:
        pass  # refusing an un-upgraded read-only store is acceptable; changing it is not
    finally:
        os.chmod(work, 0o644)
    assert hashlib.sha256(work.read_bytes()).hexdigest() == before


@pytest.mark.skipif(not os.environ.get('BW_REGRESSION_DB'), reason='set BW_REGRESSION_DB to check a real store copy')
def test_real_store_copy(tmp_path):
    check(Path(os.environ['BW_REGRESSION_DB']), tmp_path)


def test_fixtures_present():
    assert len(FIXTURES) >= 3
