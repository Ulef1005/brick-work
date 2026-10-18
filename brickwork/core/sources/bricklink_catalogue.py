"""Eight-type streaming catalogue; replacement protocol reused from web.bl_catalog."""
from contextlib import closing
import fcntl
import html
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import uuid
from xml.etree import ElementTree as ET

from .base import Source, now, write

TYPES = set('SPMGBCIO')


def normalize(value):
    return ' '.join(value.split())


class BrickLinkCatalogue(Source):
    label = 'BrickLink catalogue'
    source = 'bricklink_catalogue'
    source_kind = 'file'
    daily_budget = 0
    freshness = {'xml': 90}


def load(directory, target, db):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        metadata = _load(Path(directory), target)
        with db:
            BrickLinkCatalogue(db).register()
            from ..names import refresh
            metadata['names_updated'] = refresh(db, target)
            import_id = uuid.uuid4().hex
            write(db, '''INSERT INTO jobs(source,kind,state,payload,created_at,updated_at)
                VALUES('bricklink_catalogue','xml','done',?,?,?)''',
                  (json.dumps(metadata), metadata['loaded_at'], metadata['loaded_at']))
            for source in metadata['sources']:
                write(db, 'INSERT OR REPLACE INTO source_records VALUES(?,?,?,?,?,?)',
                      ('bricklink_catalogue', 'xml', import_id + ':' + source['name'],
                       (Path(directory) / source['name']).read_text(), metadata['loaded_at'], 'success'))
        return metadata


def source_directory(database):
    """The one place catalogue XML files are read from: beside the resolved database file."""
    return Path(database).resolve().parent / 'bricklink-catalog-src'


def info(target):
    target = Path(target)
    if not target.is_file():
        return {'available': False, 'path': str(target)}
    with closing(sqlite3.connect(target.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        return {'available': True, 'path': str(target),
                **json.loads(db.execute('SELECT info FROM metadata').fetchone()[0])}


def _load(directory, target):
    fd, temp = tempfile.mkstemp(prefix='.bricklink-catalog-', suffix='.db', dir=target.parent)
    os.close(fd)
    previous_temp = None
    backup_temp = None
    previous = target.with_name('bricklink-catalog.prev.db')
    previous_installed = False
    try:
        metadata = {'loaded_at': now().isoformat(), 'sources': [], 'counts': {}}
        with closing(sqlite3.connect(temp)) as db, db:
            db.execute('''CREATE TABLE items(item_type TEXT NOT NULL,item_no TEXT NOT NULL,
                name TEXT NOT NULL,normalized_name TEXT NOT NULL,category TEXT,year INTEGER,
                PRIMARY KEY(item_type,item_no))''')
            db.execute('CREATE INDEX items_name ON items(normalized_name)')
            db.execute('CREATE TABLE metadata(info TEXT NOT NULL)')
            for source in sorted(directory.glob('*.xml')):
                if source.name.startswith('.'):
                    continue
                filename = source.name
                stat = source.stat()
                count = 0
                kinds = set()
                # Clear the root too: clearing ITEM alone retains 96k children.
                context = ET.iterparse(source, events=('start', 'end'))
                _, root = next(context)
                if root.tag != 'CATALOG':
                    raise ValueError('expected CATALOG root')
                for event, element in context:
                    if event != 'end' or element.tag != 'ITEM':
                        continue
                    item_type = element.findtext('ITEMTYPE')
                    number = element.findtext('ITEMID')
                    name = normalize(html.unescape(html.unescape(element.findtext('ITEMNAME') or '')))
                    if item_type not in TYPES or not number or not name:
                        raise ValueError(f'invalid catalogue item in {filename}')
                    year = element.findtext('YEARRELEASED') or element.findtext('YEAR')
                    if year is not None and (not year.isdigit() or len(year) != 4):
                        raise ValueError('invalid catalogue year')
                    db.execute('INSERT INTO items VALUES (?,?,?,?,?,?)',
                               (item_type, number, name, name.lower(), element.findtext('CATEGORY'), int(year) if year else None))
                    count += 1
                    kinds.add(item_type)
                    metadata['counts'][item_type] = metadata['counts'].get(item_type, 0) + 1
                    root.clear()
                metadata['sources'].append(dict(name=filename, size=stat.st_size,
                    mtime=stat.st_mtime, item_types=sorted(kinds), count=count))
            if set(metadata['counts']) != TYPES:
                raise ValueError('catalogue must contain all eight item types')
            db.execute('INSERT INTO metadata VALUES (?)', (json.dumps(metadata),))
        with open(temp, 'rb') as stream:
            os.fsync(stream.fileno())
        if target.exists():
            fd, previous_temp = tempfile.mkstemp(prefix='.bricklink-catalog-prev-', dir=target.parent)
            os.close(fd)
            shutil.copyfile(target, previous_temp)
            with open(previous_temp, 'rb') as stream:
                os.fsync(stream.fileno())
            if previous.exists():
                fd, backup_temp = tempfile.mkstemp(prefix='.bricklink-catalog-backup-', dir=target.parent)
                os.close(fd)
                shutil.copyfile(previous, backup_temp)
            os.replace(previous_temp, previous)
            previous_installed = True
        try:
            os.replace(temp, target)
        except OSError:
            # A failed install must preserve the previous version as well.
            if previous_installed:
                if backup_temp:
                    os.replace(backup_temp, previous)
                else:
                    previous.unlink()
            raise
        return metadata
    finally:
        for filename in (temp, previous_temp, backup_temp):
            if filename and Path(filename).exists():
                Path(filename).unlink()
