"""Brick Owl sync adapter (#522): owned and wanted sets only."""
import re

from .. import errors
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


def _lot_sort_key(lot):
    lot_id = lot['lot_id']
    return (0, int(lot_id)) if _INT_PATTERN.fullmatch(lot_id) else (1, lot_id)


def _collect_sets(reply, ids, unreadable=None):
    counts, lots = {}, {}
    for lot in _require_list(reply):
        if not isinstance(lot, dict) or lot.get('type') != 'Set':
            continue
        qty = _parse_int(lot.get('qty'), minimum=1)
        number = _lot_set_number(lot)
        if qty is None or number is None:
            if unreadable is not None:
                unreadable.append(lot.get('lot_id'))
            continue
        raw_id = lot.get('lot_id')
        if not isinstance(raw_id, (str, int)) or isinstance(raw_id, bool) or not str(raw_id).strip():
            if unreadable is not None:
                unreadable.append(raw_id)
            continue
        counts[number] = counts.get(number, 0) + qty
        lots.setdefault(number, []).append(dict(lot_id=str(raw_id).strip(), qty=qty))
        boid = lot.get('boid')
        if isinstance(boid, (str, int)) and not isinstance(boid, bool) and str(boid).strip():
            ids[number] = str(boid).strip()
    for entries in lots.values():
        entries.sort(key=_lot_sort_key)
    return counts, lots


def lot_changes(lots, target):
    """Plan lot changes to take `lots` to a total of `target`."""
    if isinstance(target, bool) or not isinstance(target, int) or target < 0:
        raise ValueError('invalid target quantity')
    if target == 0:
        return [('delete', lot['lot_id']) for lot in lots]
    if not lots:
        return [('create', None, target)]
    current = sum(lot['qty'] for lot in lots)
    if target == current:
        return []
    if target > current:
        first = lots[0]
        return [('update', first['lot_id'], first['qty'] + (target - current))]
    drop = current - target
    changes = []
    for lot in reversed(lots):
        if drop == 0:
            break
        qty = lot['qty']
        if qty <= drop:
            changes.append(('delete', lot['lot_id']))
            drop -= qty
        else:
            changes.append(('update', lot['lot_id'], qty - drop))
            drop = 0
    return changes


class BrickOwlUser(BrickOwl):
    """Brick Owl sync adapter for collection and wishlist sets."""

    def __init__(self, db, **kwargs):
        super().__init__(db, **kwargs)
        self._fetched = None

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
        ids, unreadable = {}, []
        owned, owned_lots = _collect_sets(self.collection_lots(), ids, unreadable)
        wid = link.get('wishlist_id') if isinstance(link, dict) else None
        if wid is not None and not isinstance(wid, bool) and str(wid).strip():
            wanted, wanted_lots = _collect_sets(self.wishlist_lots(wid), ids, unreadable)
        else:
            wanted, wanted_lots = {}, {}
        return dict(
            owned=owned,
            wanted=wanted,
            ids=ids,
            names={},
            unreadable=len(unreadable),   # set lots with no set number or quantity
            lots=dict(owned=owned_lots, wanted=wanted_lots),
        )

    def set_ids(self, numbers):
        """Look up Brick Owl boids for set numbers."""
        found = {}
        for number in sorted(set(numbers)):
            reply = self.id_lookup(number, 'Set', id_type='set_number')
            boids = reply.get('boids') if isinstance(reply, dict) else None
            if isinstance(boids, list) and len(boids) == 1:           # two catalogue ids for one number: not guessed
                first = boids[0]
                if isinstance(first, (str, int)) and not isinstance(first, bool) and str(first).strip():
                    found[number] = str(first).strip()
        return found

    def _state_lots(self, link, state):
        lots = state.get('lots')
        if lots is not None:
            return lots
        if self._fetched is None:
            self._fetched = self.fetch(link)
        state['lots'] = self._fetched['lots']      # kept with the plan: a job sends one row per client, and one new read serves them all
        return state['lots']

    def _forget_lots(self, state):
        """After a call that did not go through, what is there is not known: a retry reads the lots again, so it never creates a second lot
        for one that arrived (a new lot above quantity 1 is a create, then an update)."""
        state.pop('lots', None)
        self._fetched = None

    def _set_boid(self, number, state):
        boid = (state.get('ids') or {}).get(number)
        if boid is None and self._fetched is not None:
            boid = self._fetched['ids'].get(number)
        if boid is None:
            boid = self.set_ids([number]).get(number)
            if boid is None:
                raise errors.ValidationFailed('Brick Owl does not know this set number')
        if isinstance(state.get('ids'), dict):
            state['ids'][number] = boid
        return boid

    def _apply_changes(self, kind, number, target, link, lots_by_kind, state):
        """Perform the lot calls that take one set to `target`; returns how many calls changed something."""
        if kind == 'wanted':
            wid = link.get('wishlist_id') if isinstance(link, dict) else None
            if wid is None or isinstance(wid, bool) or not str(wid).strip():
                raise errors.ValidationFailed('Link a Brick Owl wishlist to send wishes to')
            wid = str(wid).strip()
            create = lambda boid: self.create_wishlist_lot(wid, boid)
            update = lambda lid, qty: self.update_wishlist_lot(wid, lid, qty)
            delete = lambda lid: self.delete_wishlist_lot(wid, lid)
        elif kind == 'owned':
            create = self.create_collection_lot
            update = lambda lid, qty: self.update_collection_lot(lid, quantity=qty)
            delete = self.delete_collection_lot
        else:
            raise ValueError('invalid row kind')
        steps = lot_changes(lots_by_kind.get(kind, {}).get(number, []), target)
        for step in steps:
            if step[0] == 'delete':
                delete(step[1])
            elif step[0] == 'update':
                update(step[1], step[2])
            else:
                new_id = create(self._set_boid(number, state))
                if step[2] > 1:
                    update(new_id, step[2])
        return len(steps)

    def send_set(self, rows, link, state):
        """Send all owned and wanted plan rows for one set."""
        if not rows:
            return 'unchanged'
        lots_by_kind = self._state_lots(link, state)
        try:
            changed = sum(self._apply_changes(row['kind'], row['remote_no'], row['send'], link, lots_by_kind, state) for row in rows)
        except Exception:
            self._forget_lots(state)
            raise
        return 'sent' if changed else 'unchanged'

    def send(self, row, link, state):
        """Send one plan row for a set."""
        return self.send_set([row], link, state)
