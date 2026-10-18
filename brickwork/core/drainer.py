"""The embedded job drainer loop, shared by the web app and the API."""
from contextlib import closing
import os
import threading
import time

from .connect import connect
from .pipeline import poll_delay, worker
from .sources.base import audit_origin


def loop(path, sleep, *, stop=None):
    """Drain due jobs, then sleep until the next deadline; return when nothing is pending."""
    with audit_origin('app'):
        while stop is None or not stop.is_set():
            worker(path=path)
            with closing(connect(path)) as db:
                delay = poll_delay(db)
            if delay is None:
                return
            sleep(delay)


def spawn(target):
    """Seam for the embedded drainer's thread; tests replace it."""
    threading.Thread(target=target, name='brickwork-drainer', daemon=True).start()


def sleep(seconds):
    """Looked up at call time, so gevent's patching applies and tests can replace it."""
    time.sleep(seconds)


def enabled():
    """BW_EMBEDDED_WORKER=0 leaves draining to `brickwork worker` on headless installs."""
    return os.environ.get('BW_EMBEDDED_WORKER', '1').lower() not in ('0', 'false', 'no', 'off')


LOCK = threading.Lock()


def start(app, path, fallback=None):
    """One drainer per app; a daemon thread is the standalone default.

    The active flag is set and cleared under a lock (#68), and the drainer checks for due work once more
    before it clears the flag, so a job queued while it was stopping is not left waiting.
    """
    if not enabled():
        return False
    with LOCK:
        if app.extensions.get('bw_import_worker_active'):
            return True
        app.extensions['bw_import_worker_active'] = True
    launch = fallback or spawn

    def pending():
        with closing(connect(path)) as db:
            return poll_delay(db) is not None

    def run():
        try:
            with app.app_context():
                while True:
                    loop(path, sleep)
                    with LOCK:
                        if not pending():
                            app.extensions['bw_import_worker_active'] = False
                            return
        except BaseException:
            with LOCK:
                app.extensions['bw_import_worker_active'] = False
            raise
    try:
        launch(run)
    except Exception:
        with LOCK:
            app.extensions['bw_import_worker_active'] = False
        raise
    return True
