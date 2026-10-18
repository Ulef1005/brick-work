"""Explicit photo recognition through the budgeted, audited source interface."""
import hashlib
import io
import math
import os
from pathlib import Path
import uuid
import tempfile
from urllib.request import Request

from PIL import Image, UnidentifiedImageError

from .base import Source, SourceError, now
from ..admin import audit


def photo_bytes(raw):
    if not raw or len(raw) > 8 * 1024 * 1024:
        raise ValueError('Choose a photo smaller than 8 MB')
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > 20000000:
                raise ValueError('Choose a smaller photo')
            image.load()
            image = image.convert('RGB')
            image.thumbnail((1600, 1600))
            output = io.BytesIO()
            image.save(output, format='JPEG', quality=90)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError('This photo could not be read') from None


class Brickognize(Source):
    label = 'Brickognize'
    source = 'brickognize'
    freshness = {'predict': 0}

    def __init__(self, db, **kwargs):
        super().__init__(db, **kwargs)
        budget = os.environ.get('BW_BRICKOGNIZE_DAILY_BUDGET', '100')
        if not budget.isdigit() or int(budget) <= 0:
            raise SourceError('Brickognize budget must be positive')
        self.daily_budget = int(budget)

    def predict(self, photo, endpoint=None):
        if endpoint not in (None, "parts", "figs"):
            raise ValueError("Choose parts or figures")
        boundary = 'bw' + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="query_image"; filename="photo.jpg"\r\n'
                'Content-Type: image/jpeg\r\n\r\n').encode() + photo + f'\r\n--{boundary}--\r\n'.encode()
        request = Request('https://api.brickognize.com/predict/' + (endpoint + '/' if endpoint else ''), data=body,
                          headers={'Content-Type': 'multipart/form-data; boundary=' + boundary})
        def consume(reply):
            if not isinstance(reply, dict) or not isinstance(reply.get('items'), list):
                raise SourceError('Brickognize returned an invalid reply')
            types = {'set': 'S', 'minifig': 'M', 'minifigure': 'M', 'part': 'P'}
            candidates = []
            for item in reply['items']:
                if not isinstance(item, dict):
                    raise SourceError('Brickognize returned an invalid candidate')
                kind = types.get(item.get('type'))
                if kind and isinstance(item.get('id'), str):
                    try:
                        score = float(item.get('score', 0))
                    except (TypeError, ValueError):
                        raise SourceError('Brickognize returned an invalid score') from None
                    if not math.isfinite(score) or not 0 <= score <= 1:
                        raise SourceError('Brickognize returned an invalid score')
                    candidates.append(dict(item_type=kind, item_no=item['id'], score=score))
            return sorted(candidates, key=lambda row: row['score'], reverse=True)
        return self.request('predict', {'sha256': hashlib.sha256(photo).hexdigest(), 'endpoint': endpoint}, request, consume)


def keep(db, kind, number, photo, *, copy_id=None, stock_id=None):
    from ..media import media_root
    root = media_root(db)
    relative = 'data/images/own/' + hashlib.sha256(photo).hexdigest() + '.jpg'
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    # Content addressed own photos have no external URL or embedded EXIF.
    if not target.exists():
        descriptor, pending = tempfile.mkstemp(dir=target.parent, prefix='.own-')
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(photo)
            os.replace(pending, target)
        finally:
            if Path(pending).exists():
                Path(pending).unlink()
    if not db.execute("SELECT 1 FROM sources WHERE source='own'").fetchone():
        db.execute("INSERT INTO sources(source,name,kind) VALUES('own','Own photos','manual')")
        audit(db, 'source:own', 'created', None, {'source': 'own', 'name': 'Own photos', 'kind': 'manual'})
    with Image.open(io.BytesIO(photo)) as image:
        cursor = db.execute("INSERT INTO item_images(item_type,item_no,source,kind,local_path,width,height,fetched_at,copy_id,stock_id) VALUES(?,?,'own','own',?,?,?,?,?,?)",
            (kind, number, relative, image.width, image.height, now().isoformat(), copy_id, stock_id))
    audit(db, 'image:' + str(cursor.lastrowid), 'created', None,
          dict(db.execute('SELECT * FROM item_images WHERE id=?', (cursor.lastrowid,)).fetchone()))
