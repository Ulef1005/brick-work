"""The two bodies of API v2 item addressing (design 7): `item` and `color`, for one id (`item`, `color`) or for many in a fixed number of
queries (`items`, `colors`; M.11b). Strings pass through the same secret redaction the error text gets; the shapes are `store4.lookup`'s."""
from ..core.sources.base import redact
from ..core.secrets import secret_values
from ..store4 import lookup


def _clean(value, secrets):
    if isinstance(value, str):
        return redact(value, secrets)
    if isinstance(value, dict):
        return {k: _clean(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v, secrets) for v in value]
    return value


def item(db, item_id, secrets=None):
    """`Item` of a live item id, or None."""
    body = lookup.item_body(db, item_id)
    return None if body is None else _clean(body, secret_values() if secrets is None else secrets)


def items(db, item_ids, secrets=None):
    """`{id: Item}` of the live items among `item_ids`, in a fixed number of queries."""
    secrets = secret_values() if secrets is None else secrets
    return {i: _clean(body, secrets) for i, body in lookup.item_bodies(db, item_ids).items()}


def colors(db, color_ids, secrets=None):
    """`{id: Color}` of the known colours among `color_ids`, in a fixed number of queries."""
    secrets = secret_values() if secrets is None else secrets
    return {i: _clean(body, secrets) for i, body in lookup.color_bodies(db, color_ids).items()}


def color(db, color_id, secrets=None):
    """`Color` of a colour id, or None."""
    body = lookup.color_body(db, color_id)
    return None if body is None else _clean(body, secret_values() if secrets is None else secrets)
