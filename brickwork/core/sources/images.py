"""Local picture cache on the 4.0 store (M.8f, issue #110; design 6.8). No credentials, redirects or remote image hot-links.

A picture is a file under `data/images/<source>/<kind>/<sha256>.<ext>` and a row of `picture` (item, colour or none, source, kind). Only
the three picture sources of design 6.8 write here: `rebrickable_dump`, `bricklink`, `rebrickable_api`. The download is a plain GET of a
public image URL on a host that belongs to the source; it is not an API call and counts against no budget."""
from hashlib import sha256
from io import BytesIO
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from PIL import Image

from ...store4.connect import now as store_now
from .base import NoRedirect, SourceError, redact, USER_AGENT

HOSTS = {'bricklink': {'img.bricklink.com', 'www.bricklink.com'},
         'rebrickable_dump': {'cdn.rebrickable.com', 'rebrickable.com', 'images.rebrickable.com'},
         'rebrickable_api': {'cdn.rebrickable.com', 'rebrickable.com', 'images.rebrickable.com'}}
SOURCES = tuple(HOSTS)
NAMES = {'bricklink': 'BrickLink', 'rebrickable_dump': 'Rebrickable dump', 'rebrickable_api': 'Rebrickable API'}      # for a file written before the seeds had them
MAX_BYTES = 20 * 1024 * 1024


def picture_kind(source, kind):
    """Only Rebrickable's API part pictures are renders; every other picture is a photo (design 6.8, `picture.kind`)."""
    return 'render' if source == 'rebrickable_api' and kind == 'part' else 'photo'


def transport(request):
    with build_opener(NoRedirect()).open(request, timeout=20) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise SourceError('image is too large')
    return data


def download(db, root, source, item_id, kind, url, *, color_id=None, image_kind=None, http=None):
    """Fetch one picture from a public image URL and store it for the item (and colour). Returns the stored `local_path`.

    The URL must be https on a host of the source; a redirect, a login in the URL or another port is refused."""
    if url.startswith('//'):
        url = 'https:' + url
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in HOSTS.get(source, set())
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise SourceError('unsupported image URL')
    try:
        data = (http or transport)(Request(url, headers={'User-Agent': USER_AGENT}))
    except Exception:
        raise SourceError(source + ' image could not be downloaded') from None
    return store(db, root, source, item_id, kind, data, color_id=color_id, image_kind=image_kind or picture_kind(source, kind), url=redact(url))


def store(db, root, source, item_id, kind, data, *, color_id=None, image_kind='photo', url=None, fetched_at=None):
    """Verify the bytes, copy them atomically into the cache, then replace the `picture` row of (item, colour, source, kind).

    The row is written in the caller's transaction (a savepoint when one is open) with one `picture:stored` event; the file is written
    first, so a failed write never leaves a row without its file."""
    from ..admin import audit
    from ..transaction import transaction
    if source not in HOSTS:
        raise SourceError(f'{source} is not a picture source')
    try:
        if len(data) > MAX_BYTES:
            raise ValueError('oversized')
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            extension = {'PNG': '.png', 'JPEG': '.jpg', 'GIF': '.gif', 'WEBP': '.webp'}.get(image.format)
            if extension is None:
                raise ValueError('unsupported image format')
            image.verify()
    except Exception:
        raise SourceError(source + ' image could not be verified') from None
    digest = sha256(data).hexdigest()
    relative = Path('data/images') / source / kind / (digest + extension)
    target = Path(root) / relative
    if not target.resolve().is_relative_to(Path(root).resolve() / 'data/images'):
        raise SourceError('Image storage is outside the managed cache')
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name('.' + digest + '-' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_bytes(data)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    with transaction(db):
        db.execute("INSERT OR IGNORE INTO source(id, name, kind) VALUES(?, ?, ?)", (source, NAMES[source], 'file' if source == 'rebrickable_dump' else 'api'))
        old = [dict(r) for r in db.execute('''SELECT id, local_path, url, fetched_at FROM picture WHERE item_id=? AND color_key=coalesce(?, 0)
                                              AND source=? AND kind=?''', (item_id, color_id, source, image_kind))]
        db.execute('DELETE FROM picture WHERE item_id=? AND color_key=coalesce(?, 0) AND source=? AND kind=?', (item_id, color_id, source, image_kind))
        db.execute('''INSERT INTO picture(item_id, color_id, source, kind, local_path, url, width, height, fetched_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                   (item_id, color_id, source, image_kind, relative.as_posix(), url, width, height, fetched_at or store_now()))
        audit(db, f'picture:{item_id}', 'stored', old or None, dict(source=source, kind=image_kind, local_path=relative.as_posix(), color_id=color_id))
    return relative.as_posix()
