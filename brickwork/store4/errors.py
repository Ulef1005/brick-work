"""Errors of the 4.0 store."""
import logging
import re

log = logging.getLogger('brickwork.store4')
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


def public_text(exc, *, what='job'):
    """The words a page or a job row may show for `exc`: a store4 refusal keeps its message with every folder path cut to its last name;
    anything else (SQLite, the operating system, a bug) is replaced by a fixed sentence. The full text goes to the server log only."""
    log.warning('%s failed: %s: %s', what, type(exc).__name__, exc, exc_info=exc)
    if isinstance(exc, Store4Error):
        return _PATH.sub(lambda m: m.group(1) or 'a folder', str(exc))[:300]
    return GENERIC
