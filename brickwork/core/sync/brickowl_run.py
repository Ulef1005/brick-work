"""Brick Owl pull-side sync adapter (#522): owned and wanted sets only."""
import re

from ..sources.base import SourceError
from ..sources.brickowl import BrickOwl

_SET_NUMBER_PATTERN = re.compile(r'[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*')
_INT_PATTERN = re.compile(r'[0-9]+')


def _require_list(reply):
    if not isinstance(reply, list):
        raise SourceError('Brick Owl returned an unexpected collection')
    return reply


def _parse_int(value, *, minimum=0):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= minimum else None
    if isinstance(value, str):
        text = value.strip()
        if _INT_PATTERN.fullmatch(text):
            number = int(text)
            return number if number >= minimum else None
    return None


def _normalize_set_number(raw):
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        return None
    text = str(raw).strip()
    if not text or len(text) > 64 or not _SET_NUMBER_PATTERN.fullmatch(text):
        return None
    return f'{text}-1' if '-' not in text else text


def _lot_set_number(lot):
    lot_ids = lot.get('ids')
    if not isinstance(lot_ids, list):
        return None
    for entry in lot_ids:
        if not isinstance(entry, dict) or entry.get('type') != 'set_number':
            continue
        number = _normalize_set_number(entry.get('id'))
        if number is not None:
            return number
    return None


def _collect_sets(reply, ids):
    counts = {}
    for lot in _require_list(reply):
        if not isinstance(lot, dict) or lot.get('type') != 'Set':
            continue
        qty = _parse_int(lot.get('qty'), minimum=1)
        if qty is None:
            continue
        number = _lot_set_number(lot)
        if number is None:
            continue
        counts[number] = counts.get(number, 0) + qty
        boid = lot.get('boid')
        if isinstance(boid, (str, int)) and not isinstance(boid, bool) and str(boid).strip():
            ids[number] = str(boid).strip()
    return counts


class BrickOwlUser(BrickOwl):
    """Brick Owl sync adapter for reading collection and wishlist sets."""

    def check_user(self):
        """Verify the configured Brick Owl API key."""
        self.check_key()
        return True

    def lists(self):
        """Return the account wishlists as id, name, and lot count dicts."""
        out = []
        for row in _require_list(self.wishlist_lists()):
            if not isinstance(row, dict):
                continue
            wid = row.get('wishlist_id')
            if wid is None or isinstance(wid, bool) or not str(wid).strip():
                continue
            lots = _parse_int(row.get('lot_count'), minimum=0)
            out.append(dict(id=str(wid).strip(), name=str(row.get('name') or ''), lots=0 if lots is None else lots))
        return out

    def fetch(self, link):
        """Fetch owned and wanted set counts from Brick Owl."""
        ids = {}
        owned = _collect_sets(self.collection_lots(), ids)
        wid = link.get('wishlist_id') if isinstance(link, dict) else None
        if wid is not None and not isinstance(wid, bool) and str(wid).strip():
            wanted = _collect_sets(self.wishlist_lots(wid), ids)
        else:
            wanted = {}
        return dict(owned=owned, wanted=wanted, ids=ids, names={})
