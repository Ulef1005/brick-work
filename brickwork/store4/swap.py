"""What every catalogue file rebuild shares (design 6.2, 6.6): the build lock, the checks of the new file, and the swap that
publishes it. The Rebrickable build and the BrickLink list import both write `<target>.new` under the lock and publish it here."""
from contextlib import closing, contextmanager
import fcntl
import os
from pathlib import Path
import sqlite3
import uuid

from .connect import _uri
from .errors import BuildBusy, CatalogueMismatch


@contextmanager
def build_lock(target):
    """Hold `<target>.lock` for the whole build; a second builder is refused without touching anything."""
    target = Path(target)
    lock = open(target.with_name(target.name + '.lock'), 'a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise BuildBusy(f'another catalogue build is running on {target}; nothing was touched') from None
    try:
        yield
    finally:
        lock.close()                                          # closing releases the flock


def new_path(target):
    target = Path(target)
    return target.with_name(target.name + '.new')


def remove_new(new):
    for p in (new, new.with_name(new.name + '-journal')):
        p.unlink(missing_ok=True)


def fsync(path, directory=False):
    fd = os.open(path, os.O_RDONLY | (os.O_DIRECTORY if directory else 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def publish(new, target, *, keep_previous):
    """fsync the finished `new`, keep the replaced target as `<target>.prev` (a hard link, so the target stays in place until
    the one rename that publishes the new file) and rename `new` over it. Returns the .prev path or None."""
    new, target = Path(new), Path(target)
    prev = target.with_name(target.name + '.prev')
    fsync(new)
    if keep_previous:
        link = target.with_name(f'{target.name}.prev.{uuid.uuid4().hex}')
        os.link(target, link)
        os.replace(link, prev)
    os.replace(new, target)
    fsync(target.parent, directory=True)
    return prev if keep_previous else None


def check_new(db):
    """Foreign keys, integrity and journal mode of the finished new file (an open connection with no transaction)."""
    db.execute('PRAGMA foreign_keys=ON')
    found = db.execute('PRAGMA foreign_key_check').fetchall()
    if found:
        raise CatalogueMismatch(f'the new catalogue breaks foreign keys: {[tuple(r) for r in found[:5]]} ({len(found)} in all)')
    verdict = db.execute('PRAGMA integrity_check').fetchall()
    if [tuple(r) for r in verdict] != [('ok',)]:
        raise CatalogueMismatch(f'the new catalogue fails its integrity check: {[tuple(r) for r in verdict[:5]]}')
    if db.execute('PRAGMA journal_mode=DELETE').fetchone()[0] != 'delete':
        raise CatalogueMismatch('the new catalogue could not be set to journal_mode=DELETE')


def recheck_merged(new, collection):
    """Refuse to publish when the collection merged away an id that the new file has live: a merge committed while the build
    ran (the build lock keeps out other builders only). Invariant 4: no catalogue row ever names a merged id."""
    with closing(sqlite3.connect(_uri(collection, 'ro'), uri=True)) as db:
        merged = [r[0] for r in db.execute('SELECT id FROM item WHERE merged_into IS NOT NULL')]
    if not merged:
        return
    with closing(sqlite3.connect(_uri(new, 'ro'), uri=True)) as db:
        db.execute('CREATE TEMP TABLE merged(id INTEGER PRIMARY KEY)')
        db.executemany('INSERT INTO temp.merged VALUES(?)', [(i,) for i in merged])
        live = [r[0] for r in db.execute('SELECT id FROM main.item WHERE retired_at IS NULL AND id IN (SELECT id FROM temp.merged) ORDER BY id')]
    if live:
        raise CatalogueMismatch(f'items {live[:5]} were merged in the collection while the catalogue was being built; run the build again')
