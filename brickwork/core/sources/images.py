"""Local image cache. No credentials, redirects or remote image hot-links."""
from hashlib import sha256
from io import BytesIO
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from PIL import Image

from .base import NoRedirect, SourceError, now, write, redact, USER_AGENT

HOSTS = {'bricklink': {'img.bricklink.com', 'www.bricklink.com'},
         'rebrickable': {'cdn.rebrickable.com', 'rebrickable.com', 'images.rebrickable.com'}}
MAX_BYTES = 20 * 1024 * 1024


def picture_kind(source, item_type):
    """Only Rebrickable part pictures are renders; all others are photos."""
    return 'render' if source == 'rebrickable' and item_type == 'P' else 'photo'


def transport(request):
    with build_opener(NoRedirect()).open(request, timeout=20) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise SourceError('image is too large')
    return data


def download(db, root, source, kind, number, url, *, color=None, image_kind='photo', http=None):
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
    return store(db, root, source, kind, number, data, color=color,
                 image_kind=image_kind, url=redact(url))


def store(db, root, source, kind, number, data, *, color=None, image_kind='photo', url=None, fetched_at=None):
    """Verify before atomically copying bytes; replace rows after storage succeeds."""
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
    with db:
        write(db, 'INSERT OR IGNORE INTO sources(source,name,kind) VALUES(?,?,?)', (source, source, 'api'))
        if color is not None:
            write(db, 'INSERT OR IGNORE INTO colors(color_id) VALUES(?)', (color,))
        old = [dict(r) for r in db.execute('SELECT * FROM item_images WHERE item_type=? AND item_no=? AND color_id IS ? AND source=? AND kind=? AND copy_id IS NULL AND stock_id IS NULL', (kind, number, color, source, image_kind))]
        write(db, '''DELETE FROM item_images WHERE item_type=? AND item_no=? AND color_id IS ?
            AND source=? AND kind=? AND copy_id IS NULL AND stock_id IS NULL''',
              (kind, number, color, source, image_kind))
        write(db, '''INSERT INTO item_images(item_type,item_no,color_id,source,kind,local_path,url,
            width,height,fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?)''',
              (kind, number, color, source, image_kind, relative.as_posix(), url, width, height, fetched_at or now().isoformat()))
        from .base import AUDIT_ORIGIN, AUDIT_ACTOR
        import json
        db.execute('INSERT INTO events(entity,field,old_value,new_value,at,via,actor) VALUES(?,?,?,?,?,?,?)',
                   ('picture:' + kind + ':' + number, 'stored', json.dumps(old),
                    json.dumps(dict(source=source, local_path=relative.as_posix(), color_id=color)),
                    now().isoformat(), AUDIT_ORIGIN.get(), AUDIT_ACTOR.get()))
    return relative.as_posix()
