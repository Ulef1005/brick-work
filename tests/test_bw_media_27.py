"""#27 separate media folder: BW_MEDIA_PATH moves pictures, thumbnails and PDFs; the database stays. Invented data.

M.11b ported the reads of this file to API v2 (tests/test_api2_read_catalogue.py: the default folder, the folder of the environment, a link out of
the folder); what is left writes a photo and a PDF through the API and waits for M.11c."""
from contextlib import closing
import io
import os
from pathlib import Path

from PIL import Image

from brickwork.core.connect import connect
from tests.test_bw_api_m1 import app  # noqa: F401
from tests.test_bw_api_m2 import populated  # noqa: F401

H = {'Authorization': 'Bearer synthetic-bootstrap'}


def png(size=(1200, 900)):
    out = io.BytesIO()
    Image.new('RGB', size, (200, 30, 30)).save(out, 'PNG')
    return out.getvalue()


def test_photo_pdf_and_thumbnail_go_to_the_media_folder(populated, monkeypatch, tmp_path):
    target = tmp_path / 'nas'
    monkeypatch.setenv('BW_MEDIA_PATH', str(target))
    store = Path(os.environ['BW_DB_PATH']).resolve()
    c = populated.test_client()
    photo = c.post('/api/v1/copies/c1/photos', headers=dict(H, **{'Idempotency-Key': 'media-1'}), content_type='multipart/form-data',
                   data={'file': (io.BytesIO(png()), 'x.png', 'image/png')})
    assert photo.status_code in (200, 201), photo.json
    with closing(connect(store)) as db:
        local = db.execute("SELECT local_path FROM item_images WHERE local_path LIKE 'data/images/own/%' ORDER BY id DESC").fetchone()[0]
        image_id = db.execute('SELECT id FROM item_images WHERE local_path=?', (local,)).fetchone()[0]
    assert (target / local).is_file() and not (store.parent / local).exists()
    content = c.get(f'/api/v1/images/{image_id}/content', headers=H)
    assert content.status_code == 200 and content.data[:4] == b'\x89PNG' or content.data[:2] == b'\xff\xd8'
    pdf = c.post('/api/v1/instruction-files', headers=dict(H, **{'Idempotency-Key': 'media-2'}),
                 data={'item_type': 'S', 'item_no': '100-1', 'label': 'Synthetic PDF', 'file': (io.BytesIO(b'%PDF-1.4\n%%EOF'), 's.pdf')})
    assert pdf.status_code == 201, pdf.json
    stored = list((target / 'data/instructions').glob('*.pdf'))
    assert len(stored) == 1 and not (store.parent / 'data/instructions' / stored[0].name).exists()
    from brickwork.core import thumbnails
    made = thumbnails.pregenerate(store)
    assert made >= 1 and list((target / 'data/thumbs').glob('*'))
