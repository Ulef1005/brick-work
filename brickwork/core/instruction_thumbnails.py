"""Derived page previews, parsed only by a bounded job child process."""
from contextlib import closing
import json
from pathlib import Path
import subprocess
import sys

from .pipeline import Pipeline
from .transaction import transaction
from ..store4.connect import now

KIND = 'instruction_thumbnail'
MAX_BYTES = 20 * 1024 * 1024
TIMEOUT = 10


def render(source, target):
    """Render page one without document actions or JavaScript; used only in the job child."""
    import pypdfium2 as pdfium
    if Path(source).stat().st_size > MAX_BYTES:
        raise ValueError('PDF exceeds preview limit')
    with pdfium.PdfDocument(str(source)) as document:
        with closing(document[0]) as page:
            width, height = page.get_size()
            if width <= 0 or height <= 0 or height / width > 10:
                raise ValueError('Unsupported page dimensions')
            with closing(page.render(scale=240 / width)) as bitmap:
                bitmap.to_pil().convert('RGB').save(target, format='PNG')


def queue(db, identifier):
    """Queue exactly one active preview job inside the attachment transaction."""
    payload = json.dumps({'file_id': identifier})
    if db.execute("SELECT 1 FROM main.job WHERE kind=? AND payload=? AND state IN ('queued','running')", (KIND, payload)).fetchone():
        return
    stamp = now()
    row = db.execute('SELECT item_id FROM main.instruction_file WHERE id=?', (identifier,)).fetchone()
    job = db.execute("""INSERT INTO main.job(source,kind,item_id,state,payload,via,created_at,updated_at)
        VALUES('import',?,?,'queued',?,'app',?,?)""", (KIND, row[0], payload, stamp, stamp)).lastrowid
    db.execute("INSERT INTO main.job_step(job_id,name,position,sources,updated_at) VALUES(?,'thumbnail',0,'[]',?)", (job, stamp))
    db.execute("UPDATE main.instruction_file SET thumbnail_state='pending',thumbnail_path=NULL WHERE id=?", (identifier,))


def queue_missing(db):
    """Restore derived data on worker startup, without retrying corrupt PDFs forever."""
    from .media import media_root
    root = media_root(db)
    with transaction(db):
        for row in db.execute("SELECT * FROM main.instruction_file WHERE archived_at IS NULL AND (thumbnail_state IS NULL OR thumbnail_state='ready')").fetchall():
            if not row['thumbnail_path'] or not (root / row['thumbnail_path']).is_file():
                queue(db, row['id'])


class Thumbnails(Pipeline):
    kind = KIND

    def queue_retry(self, job, step=None):
        with transaction(self.db):
            super().queue_retry(job, step)
            identifier = json.loads(self.status(job)['payload'])['file_id']
            self.db.execute("UPDATE main.instruction_file SET thumbnail_state='pending' WHERE id=?", (identifier,))

    def _step(self, job, saved):
        from .media import media_root
        identifier = json.loads(job['payload'])['file_id']
        row = self.db.execute('SELECT * FROM main.instruction_file WHERE id=?', (identifier,)).fetchone()
        target = temporary = None
        try:
            if not row:
                self._put(job['id'], saved['name'], 'done', count=0)
                return
            # An archived file is rendered too: Undo or restore brings it back, and a skipped job would leave it 'pending' for good.
            root = media_root(self.db).resolve()
            source = (root / row['path']).resolve()
            if not source.is_relative_to(root / 'data/instructions') or source.stat().st_size > MAX_BYTES:
                raise ValueError('PDF exceeds preview limit or has an invalid path')
            target = source.with_suffix('.thumb.png')
            temporary = target.with_name(target.name + f'.{job["id"]}.tmp')
            subprocess.run([sys.executable, '-m', __name__, str(source), str(temporary)],
                           timeout=TIMEOUT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            temporary.replace(target)
            with transaction(self.db):
                self.db.execute("UPDATE main.instruction_file SET thumbnail_path=?,thumbnail_state='ready' WHERE id=?",
                                (target.relative_to(root).as_posix(), identifier))
                self._put(job['id'], saved['name'], 'done', count=1)
        except Exception:
            with transaction(self.db):
                self.db.execute("UPDATE main.instruction_file SET thumbnail_path=NULL,thumbnail_state='failed' WHERE id=?", (identifier,))
                self._put(job['id'], saved['name'], 'failed', code='invalid_reply', error='Preview unavailable · the PDF still opens')
        finally:
            if temporary:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass  # Cleanup failure must not replace the recorded render result.


def runner_for(db, kind):
    """Select the durable runner for a job, including preview retries."""
    from .instructions import Downloads, DOWNLOAD_KIND
    return Thumbnails(db) if kind == KIND else Downloads(db) if kind == DOWNLOAD_KIND else Pipeline(db)


if __name__ == '__main__':
    try:
        render(sys.argv[1], sys.argv[2])
    except Exception:
        sys.exit(1)
