"""The two bodies of API v2 item addressing (design 7): `item` and `color`. Strings pass through the same secret redaction the error
text gets; the shapes are `store4.lookup`'s."""
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


def color(db, color_id, secrets=None):
    """`Color` of a colour id, or None."""
    body = lookup.color_body(db, color_id)
    return None if body is None else _clean(body, secret_values() if secrets is None else secrets)
