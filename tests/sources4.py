"""Test helpers for the source layer on the 4.0 store (M.8f, issue #110): fake transports and keys. Nothing here touches the network.

    net = Net({'meta': {'code': 200}, 'data': {...}})        # JSON replies, the last one repeats
    BrickLink(db, http=net)
    net.requests                                             # the urllib requests that were "sent"
"""
from io import BytesIO
import json

from PIL import Image

from brickwork.core.sources.base import Reply

BRICKLINK_KEYS = ('BW_BRICKLINK_CONSUMER_KEY', 'BW_BRICKLINK_CONSUMER_SECRET', 'BW_BRICKLINK_TOKEN_VALUE', 'BW_BRICKLINK_TOKEN_SECRET')
REBRICKABLE_KEY = 'BW_REBRICKABLE_API_KEY'
BRICKSET_KEY = 'BW_BRICKSET_API_KEY'


def keyed(monkeypatch, *sources):
    """Put invented keys of the named sources (`bricklink`, `rebrickable`, `brickset`) in the environment."""
    names = {'bricklink': BRICKLINK_KEYS, 'rebrickable': (REBRICKABLE_KEY,), 'brickset': (BRICKSET_KEY,)}
    for source in sources:
        for name in names[source]:
            monkeypatch.setenv(name, 'synthetic-' + name.lower())


def unkeyed(monkeypatch):
    for name in (*BRICKLINK_KEYS, REBRICKABLE_KEY, BRICKSET_KEY, 'BW_SECRET_KEY'):
        monkeypatch.delenv(name, raising=False)


class Net:
    """A fake `http(request)`: answers the replies in order (the last repeats). A reply is JSON-able, a `(status, body)` pair for an
    HTTP error answer, or an Exception to raise."""

    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []

    def __call__(self, request):
        self.requests.append(request)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, tuple):
            status, body = reply
            text = Reply(body if isinstance(body, str) else json.dumps(body))
            text.status = status
            return text
        return json.dumps(reply)

    @property
    def urls(self):
        return [r.full_url for r in self.requests]


def png(colour='red', size=(8, 6)):
    out = BytesIO()
    Image.new('RGB', size, colour).save(out, 'PNG')
    return out.getvalue()


class Pictures:
    """A fake image download: bytes by URL (the PNG for any URL not listed), every URL asked for recorded."""

    def __init__(self, by_url=None, default=None):
        self.by_url, self.default, self.asked = by_url or {}, default if default is not None else png(), []

    def __call__(self, request):
        self.asked.append(request.full_url)
        answer = self.by_url.get(request.full_url, self.default)
        if isinstance(answer, Exception):
            raise answer
        return answer


def price_reply(quantity=3, average='12.5', low='10', high='15'):
    """A BrickLink price guide answer."""
    return {'meta': {'code': 200}, 'data': {'total_quantity': quantity, 'qty_avg_price': average, 'min_price': low, 'max_price': high}}


class Router(Net):
    """A fake `http(request)` that answers by URL: `{substring: reply}`, the first key found in the URL wins; an unlisted URL fails the test."""

    def __init__(self, routes):
        super().__init__({})
        self.routes = routes

    def __call__(self, request):
        self.requests.append(request)
        for part, reply in self.routes.items():
            if part in request.full_url:
                if isinstance(reply, Exception):
                    raise reply
                if isinstance(reply, tuple):
                    status, body = reply
                    text = Reply(json.dumps(body))
                    text.status = status
                    return text
                return json.dumps(reply)
        raise AssertionError('unexpected request ' + request.full_url)


def step_handlers(*, http=None, image_http=None, root=None):
    """The pipeline's source handlers with fake transports: `Pipeline(db, handlers=step_handlers(http=net, image_http=pictures))`."""
    from brickwork.core import pictures
    from brickwork.core.sources import bricklink, brickset
    out = pictures.handlers(http=http, image_http=image_http, root=root)
    out.update(bricklink.handlers(http=http))
    out.update(brickset.handlers(http=http))
    return out


def add_picture_url(pair, item_id, colour_id, url):
    """A row of the catalogue's `picture_url` (the dump's image of a part in a colour), written to the catalogue file beside the pair."""
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect(pair.with_name('catalogue.db'))) as db, db:
        db.execute('INSERT OR REPLACE INTO picture_url(item_id, color_id, url) VALUES(?, ?, ?)', (item_id, colour_id, url))
