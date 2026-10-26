"""The app's one way to open the collection: the 4.0 store (M.8a, issue #110).

`connect(path)` keeps its name and signature so the ~40 call sites stay; it opens the 4.0 collection at `path` through
`store4.connect` with `catalogue.db` beside it attached read-only. A 3.2/3.3 file is refused with the fix named, never opened."""
from pathlib import Path

from ..store4 import connect as store4_connect
from ..store4.errors import CatalogueError, SchemaMismatch
from . import errors

CATALOGUE_NAME = 'catalogue.db'
MIGRATE = ('run `python -m brickwork.store4 migrate --in <3.3 file> --catalogue <catalogue.db> --mappings <dir> --out <4.0 file> '
           '--report <dir>`; the 3.3 file is only read (a `brickwork migrate4` alias comes with M.8i)')
GET_CATALOGUE = '`python -m brickwork.store4 --data <the folder of brickwork.db> catalogue download` (or `catalogue import`)'


class OldStore(errors.NotSetUp):
    """The file at BW_DB_PATH is a 3.2/3.3 collection (or not a Brick Work file at all)."""


class NoCatalogue(errors.CatalogueNotLoaded):
    """There is no catalogue.db beside the collection."""


def catalogue_path(path='brickwork.db'):
    """The catalogue that belongs to the collection at `path`: `catalogue.db` in the same folder."""
    return Path(path).with_name(CATALOGUE_NAME)


def connect(path='brickwork.db', *, read_only=False, require_catalogue=True):
    """Open the 4.0 collection at `path` with its catalogue attached read-only.

    Without the catalogue file `require_catalogue` decides: True (the default) refuses with the way to get one; False opens the
    collection alone (setup, and the first-run page that tells the user to get a catalogue)."""
    path = Path(path)
    catalogue = catalogue_path(path)
    if require_catalogue and not catalogue.is_file():
        raise NoCatalogue(f'No catalogue at {catalogue}. First run: get one with {GET_CATALOGUE}, then restart.')
    try:
        return store4_connect.connect(path, catalogue, read_only=read_only)
    except SchemaMismatch as exc:
        raise OldStore(f'{path} is not a Brick Work 4.0 collection. A 3.2/3.3 file must be migrated, never opened: {MIGRATE}. '
                       f'({exc})') from None
    except CatalogueError as exc:
        raise NoCatalogue(str(exc)) from None
