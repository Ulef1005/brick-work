"""On-demand picture thumbnails (320 and 640 px wide), cached under data/thumbs.

A thumbnail is generated on first request from the stored original and kept
beside it; the file name carries the image id, width and the original's mtime
and size, so a refreshed picture never serves a stale thumbnail. Originals that
cannot or need not be shrunk (animated, unreadable, too many pixels, already
small) are served as they are.
"""
from io import BytesIO
import logging
import os
import sys
import threading
import uuid
from pathlib import Path

from PIL import Image, ImageOps, features

WIDTHS = (320, 640)
MAX_PIXELS = 48_000_000   # checked from the header, before any pixel is decoded
QUALITY = 80
MAX_PENDING = 64          # bounded queue: further misses are served the original and retried later
log = logging.getLogger(__name__)
_lock = threading.Lock()
_pending = set()          # keys queued or running: one generation per key at a time
_skipped = set()          # keys that fall back to the original (logged once, never rescheduled)
_cpu = threading.Semaphore(1)   # one render at a time keeps a small host responsive


def format_for_thumbs():
    return ('WEBP', 'webp', 'image/webp') if features.check('webp') else ('JPEG', 'jpg', 'image/jpeg')


def thumbnail_path(root, image_id, width, original):
    """Cache path for this original at this width."""
    if width not in WIDTHS:
        raise ValueError('unsupported thumbnail width')
    stat = original.stat()
    _, extension, _ = format_for_thumbs()
    folder = Path(root) / 'data/thumbs'
    return folder / f'{int(image_id)}-{width}-{stat.st_mtime_ns}-{stat.st_size}.{extension}'


def _render(original, width):
    """Return encoded thumbnail bytes, or None to fall back to the original."""
    try:
        with Image.open(original) as image:
            w, h = image.size
            if w <= 0 or h <= 0 or w * h > MAX_PIXELS:
                return None
            if getattr(image, 'is_animated', False) or getattr(image, 'n_frames', 1) > 1:
                return None
            if w <= width:
                return None
            if image.format == 'JPEG':
                image.draft('RGB', (width, max(1, round(h * width / w))))
            image.load()
            image = ImageOps.exif_transpose(image)
            image = image.resize((width, max(1, round(image.height * width / image.width))),
                                 Image.Resampling.LANCZOS, reducing_gap=2.0)
            name, _, _ = format_for_thumbs()
            if name == 'JPEG':
                if image.mode in ('RGBA', 'LA', 'P', 'PA'):
                    image = image.convert('RGBA')
                    flat = Image.new('RGB', image.size, 'white')
                    flat.paste(image, mask=image.getchannel('A'))
                    image = flat
                elif image.mode != 'RGB':
                    image = image.convert('RGB')
            elif image.mode not in ('RGB', 'RGBA'):
                image = image.convert('RGBA' if 'transparency' in image.info or image.mode in ('LA', 'PA') else 'RGB')
            out = BytesIO()
            image.save(out, name, quality=QUALITY, **({'method': 4} if name == 'WEBP' else {'optimize': True}))
            return out.getvalue()
    except Exception:
        return None


def get(root, image_id, width, original):
    """Return (path, mimetype) of the file to serve; mimetype None means the original."""
    original = Path(original)
    target = thumbnail_path(root, image_id, width, original)
    if target.is_file():
        return target, format_for_thumbs()[2]
    data = _render(original, width)
    if data is None:
        return original, None
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name('.' + target.name + '-' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_bytes(data)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    for stale in target.parent.glob(f'{int(image_id)}-{width}-*'):
        if stale != target and not stale.name.startswith('.'):
            stale.unlink(missing_ok=True)
    return target, format_for_thumbs()[2]


def _spawn(job):
    """Run job off the request path: gevent's real-thread pool when gevent is active, else a thread."""
    try:
        from gevent import monkey
        if monkey.is_module_patched('threading') or monkey.is_module_patched('socket'):
            import gevent
            gevent.get_hub().threadpool.spawn(job)
            return
    except ImportError:
        pass
    threading.Thread(target=job, daemon=True).start()


def lookup(root, image_id, width, original):
    """Request path: the cached thumbnail path (and mimetype), else (original, None) and a background job.

    Never decodes or resizes an image itself.
    """
    original = Path(original)
    target = thumbnail_path(root, image_id, width, original)
    if target.is_file():
        return target, format_for_thumbs()[2]
    key = target.name
    with _lock:
        if key in _pending or key in _skipped or len(_pending) >= MAX_PENDING:
            return original, None
        _pending.add(key)

    def job():
        try:
            with _cpu:
                path, mimetype = get(root, image_id, width, original)
            if mimetype is None:
                with _lock:
                    _skipped.add(key)
        except Exception:
            with _lock:
                _skipped.add(key)
            log.warning('thumbnail %s could not be generated; serving the original', key, exc_info=True)
        finally:
            with _lock:
                _pending.discard(key)
    try:
        _spawn(job)
    except Exception:
        with _lock:
            _pending.discard(key)
            _skipped.add(key)
        log.warning('thumbnail %s could not be scheduled', key, exc_info=True)
    return original, None


def pregenerate(database):
    """Maintenance: build both thumbnails for every stored picture; returns the count made."""
    from .admin import database as open_database
    database = Path(database)
    from .media import root_for
    root = root_for(database)
    made = 0
    with open_database(database, read_only=True) as db:
        rows = db.execute('SELECT id, local_path FROM picture').fetchall()
    for image_id, local_path in rows:
        original = (root / local_path).resolve()
        if not original.is_relative_to(root / 'data/images') or not original.is_file():
            continue
        for width in WIDTHS:
            path, mimetype = get(root, image_id, width, original)
            made += mimetype is not None
    return made


if __name__ == '__main__':
    print(pregenerate(sys.argv[1]), 'thumbnails ready')
