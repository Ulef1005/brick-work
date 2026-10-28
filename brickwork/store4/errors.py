"""Errors of the 4.0 store."""
import logging
from pathlib import Path
import re
import sqlite3

log = logging.getLogger('brickwork.store4')
_UNDER = re.compile(r"the data folder/(?:[^\s'\"():,;]+/)*([^\s'\"():,;]*)")
GENERIC = 'It stopped before it finished. The details are in the server log.'
_PATH = re.compile(r"(?<![\w:])/(?:[^\s'\"():,;]+/)+([^\s'\"():,;]*)")


class Store4Error(Exception):
    """Base of every store4 refusal."""


class Unsupported(Store4Error):
    """The SQLite build lacks what 4.0 needs."""


class SchemaMismatch(Store4Error):
    """A collection file that is not a 4.0 collection."""


class StaleSchema(SchemaMismatch):
    """A 4.0 collection file made before a fix to the 4.0 DDL (#124): it is rebuilt by migrating again, not opened."""


class CatalogueError(Store4Error):
    """A catalogue file that cannot be attached, or is needed and missing."""


class CatalogueMismatch(CatalogueError):
    """A collection and a catalogue that do not belong together."""


class NotInCatalogue(CatalogueError):
    """The catalogue has no such row."""


class AmbiguousIdentity(Store4Error):
    """A provider key that still names several items; `.items` lists their ids."""

    def __init__(self, message, items):
        super().__init__(message)
        self.items = tuple(items)


class DumpError(Store4Error):
    """A Rebrickable dump directory that is incomplete or not in the expected shape."""


class BuildBusy(Store4Error):
    """Another catalogue build holds the lock on this target."""


class NotActivated(CatalogueError):
    """The attached catalogue has builds this collection has not activated; run activation first."""


class BrickLinkListError(Store4Error):
    """A BrickLink catalogue XML directory that is not a complete, well-formed set of item lists."""


class MergeRefused(Store4Error):
    """A merge, an unmerge or a kind move the rules (design 3.5, 3.6) do not allow, or that would lose data; the message says why."""


def _wraps_sqlite(exc):
    """Does `exc` carry a SQLite error as its cause or context (a refusal that wraps one says the database's own words)?"""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, sqlite3.Error):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def _redact_known(text, known):
    """Replace the paths this install knows (the data folder, the files in it, the home folder) exactly, longest first, before any pattern:
    a folder becomes "the data folder" (or "~" for the home folder), a file its own name."""
    items = []
    for path in [*known, Path.home()]:
        path = Path(path)
        if str(path) in ('', '.', '/'):
            continue
        for form in {str(path), str(path.resolve())}:
            items.append((form, '~' if path == Path.home() else 'the data folder' if path.is_dir() else path.name))
    for form, short in sorted(items, key=lambda i: -len(i[0])):
        text = text.replace(form, short)
    return text


def public_text(exc, *, what='job', known=()):
    """The words a page or a job row may show for `exc`: a store4 refusal written for people keeps its message, with the paths in `known`
    (and the home folder) replaced exactly and any other folder path cut to its last name; a refusal that wraps a SQLite error, and
    anything else (the operating system, a bug), gives a fixed sentence. The full text goes to the server log only."""
    log.warning('%s failed: %s: %s', what, type(exc).__name__, exc, exc_info=exc)
    if isinstance(exc, Store4Error) and not _wraps_sqlite(exc):
        text = _redact_known(str(exc), known)
        text = _UNDER.sub(lambda m: m.group(1) or 'the data folder', text)          # a subfolder of a known folder: its last name only
        return _PATH.sub(lambda m: m.group(1) or 'a folder', text)[:300]
    return GENERIC
