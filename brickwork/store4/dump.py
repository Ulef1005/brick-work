"""The 12 Rebrickable dump files (`<dir>/<name>.csv.gz`): fingerprints and checked streaming reads."""
import csv
import gzip
import hashlib
import io
from pathlib import Path

from .errors import DumpError

HEADERS = {
    'colors': 'id,name,rgb,is_trans,num_parts,num_sets,y1,y2',
    'elements': 'element_id,part_num,color_id,design_id',
    'inventories': 'id,version,set_num',
    'inventory_minifigs': 'inventory_id,fig_num,quantity',
    'inventory_parts': 'inventory_id,part_num,color_id,quantity,is_spare,img_url',
    'inventory_sets': 'inventory_id,set_num,quantity',
    'minifigs': 'fig_num,name,num_parts,img_url',
    'part_categories': 'id,name',
    'part_relationships': 'rel_type,child_part_num,parent_part_num',
    'parts': 'part_num,name,part_cat_id,part_material',
    'sets': 'set_num,name,year,theme_id,num_parts,img_url',
    'themes': 'id,name,parent_id',
}


class Dump:
    """Opens a dump directory (every file must exist) and streams its rows; `files()` reports what was read."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.rows_read = {}
        self.fingerprint = {}
        self._data = {}
        for name in HEADERS:
            path = self.path(name)
            if not path.is_file():
                raise DumpError(f'the Rebrickable dump {self.directory} lacks {path.name}')
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise DumpError(f'{path.name} cannot be read: {exc}') from exc
            # The bytes hashed here are the bytes parsed later: a file replaced on disk meanwhile cannot be loaded under another hash.
            self._data[name] = data
            self.fingerprint[name] = (len(data), hashlib.sha256(data).hexdigest())

    def path(self, name):
        return self.directory / f'{name}.csv.gz'

    def rows(self, name):
        """Yield the data rows of one file as lists of strings; the header is checked, rows are counted when read to the end."""
        count = 0
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(self._data[name])) as raw, io.TextIOWrapper(raw, encoding='utf-8', newline='') as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if header is None or ','.join(header) != HEADERS[name]:
                    raise DumpError(f'{self.path(name).name}: header {header} differs from the expected {HEADERS[name].split(",")}')
                width = len(header)
                for row in reader:
                    if len(row) != width:
                        raise DumpError(f'{self.path(name).name}: row {count + 2} has {len(row)} fields, expected {width}')
                    count += 1
                    yield row
        except (OSError, EOFError, UnicodeDecodeError) as exc:
            raise DumpError(f'{self.path(name).name} cannot be read: {exc}') from exc
        self.rows_read[name] = count
        self._data.pop(name, None)                  # the buffer is released once its rows have been consumed

    def files(self):
        """[{name, bytes, sha256, rows}] for every file; rows is known once the file has been read to the end."""
        return [{'name': f'{n}.csv.gz', 'bytes': self.fingerprint[n][0], 'sha256': self.fingerprint[n][1],
                 'rows': self.rows_read.get(n)} for n in HEADERS]
