"""Errors of the 4.0 store."""
import logging
from pathlib import Path
import re
import sqlite3

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


def _wraps_sqlite(exc):
    """Does `exc` carry a SQLite error anywhere in its chain, on the cause branch or the context branch (a refusal that wraps one says the
    database's own words)?"""
    seen, stack = set(), [exc]
    while stack:
        item = stack.pop()
        if item is None or id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, sqlite3.Error):
            return True
        stack += [item.__cause__, item.__context__]
    return False


_STOP = r"[^\s'\"():,;]"


def _redact_known(text, known):
    """Replace the paths this install knows in ONE pass over the original text (a replacement is never searched again): the data folder and
    the home folder become "the data folder" and "~", a file its own name, and what lies below a known folder its last name. A relative path
    ("data") is normalised to its absolute form and also matched as written, but only as the start of a longer path, so the word "data" in
    prose is left alone. An absolute path matches only at a path boundary."""
    home = Path.home()
    forms = {}
    for path in [*known, home]:
        path = Path(path)
        if str(path) in ('', '.', '/'):
            continue
        short = '~' if path == home else 'the data folder' if path.is_dir() or not path.suffix else path.name
        absolute = {str(path.absolute()), str(path.resolve())}
        for form in absolute:
            forms[form] = (short, False)
        if not path.is_absolute():
            forms.setdefault(str(path), (short, True))                  # as written: only as the start of a longer path
    if not forms:
        return text
    ordered = sorted(forms, key=len, reverse=True)
    pattern = re.compile('(?<![\\w/.~-])(?:' + '|'.join(re.escape(f) for f in ordered) + ')(?P<rest>(?:/' + _STOP + '+)*)(?![\\w-])')

    def short(match):
        form = match.group(0)[:len(match.group(0)) - len(match.group('rest'))]
        name, needs_rest = forms[form]
        rest = match.group('rest')
        if needs_rest and not rest:
            return match.group(0)
        return rest.rsplit('/', 1)[-1] or name if rest else name
    return pattern.sub(short, text)


def public_text(exc, *, what='job', known=()):
    """The words a page or a job row may show for `exc`: a store4 refusal written for people keeps its message, with the paths in `known`
    (and the home folder) replaced exactly and any other folder path cut to its last name; a refusal that wraps a SQLite error, and
    anything else (the operating system, a bug), gives a fixed sentence. The full text goes to the server log only."""
    log.warning('%s failed: %s: %s', what, type(exc).__name__, exc, exc_info=exc)
    if isinstance(exc, Store4Error) and not _wraps_sqlite(exc):
        text = _redact_known(str(exc), known)
        return _PATH.sub(lambda m: m.group(1) or 'a folder', text)[:300]
    return GENERIC
