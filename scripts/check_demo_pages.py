"""Load every page of the exported demo in the pinned Chrome, light and dark, and fail on a broken picture or a missing stylesheet.

    python scripts/check_demo_pages.py [SITE_DIR]      # a built demo (or whole site) folder; without it the demo is built into a scratch folder

The folder is served over HTTP under the demo's own base path with a threaded server (a one-request-at-a-time server drops the burst of picture
requests a list page makes, and shows error tiles that are not the demo's fault). Needs the pinned Chrome (scripts/chrome.py); exit 1 on a failure.
"""
import functools
import http.server
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = '/brick-work/demo/'


class Server(http.server.ThreadingHTTPServer):
    request_queue_size = 256
    daemon_threads = True


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main(argv):
    chrome = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'chrome.py'), 'pinned'], capture_output=True, text=True)
    if chrome.returncode:
        print(chrome.stderr.strip())
        return 1
    with tempfile.TemporaryDirectory(prefix='bw-demo-check-') as scratch:
        scratch = Path(scratch)
        if argv:
            demo = Path(argv[0])
        else:
            from brickwork.demo.export import export
            demo = scratch / 'demo'
            export(demo, BASE)
        # the server root holds the demo at its base path
        root = scratch / 'root'
        (root / 'brick-work').mkdir(parents=True)
        (root / 'brick-work' / 'demo').symlink_to(demo.resolve())
        manifest = json.loads((demo / 'demo-manifest.json').read_text(encoding='utf-8'))
        pages = [BASE + path for path in sorted(manifest['pages'].values())]
        (scratch / 'pages.json').write_text(json.dumps(pages))
        server = Server(('127.0.0.1', 0), functools.partial(Quiet, directory=str(root)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            result = subprocess.run(['node', str(ROOT / 'scripts' / 'check_demo_pages.cjs'), chrome.stdout.strip(),
                                     f'http://127.0.0.1:{server.server_port}', str(scratch / 'pages.json')], text=True, timeout=3000)
        finally:
            server.shutdown()
        return result.returncode


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
