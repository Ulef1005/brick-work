"""The browser for the rendered tests and the screenshot gate (D3, #160): find a Chrome, or fetch the pinned Chrome for Testing.

    python3 scripts/chrome.py path      print the Chrome binary to use; exit 1 and say why when there is none
    python3 scripts/chrome.py ensure    the same, downloading the pinned build into the cache first when nothing else is found
    python3 scripts/chrome.py pinned    print the pinned build's binary, downloading it if it is not cached (the screenshot gate uses this)

Order: the CHROME environment variable (BW_COLLECTION_CHROME is the old name and still read), the pinned Chrome for Testing in the cache
(`$BW_CHROME_CACHE`, default `~/.cache/brickwork/chrome/<version>/`), a system Chrome or Chromium, and, for `ensure` only, a download.
The download is pinned by version and by the SHA-256 of the zip; a zip with another checksum is deleted and refused. Platforms with no
pinned checksum (anything but linux x86-64 and macOS on Apple silicon) set CHROME themselves.
Pixels from a system Chrome differ from the pinned build's, so the screenshot gate asks for `pinned` (or an explicit CHROME). Standard library
only; `unzip` must be installed (it keeps the macOS bundle's symlinks)."""
import fcntl
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request

VERSION = '157.0.8103.38'
# platform -> (zip URL, SHA-256 of the zip, binary inside the extracted folder). Checked 2026-11-04.
BUILDS = {
    'linux64': ('https://storage.googleapis.com/chrome-for-testing-public/%s/linux64/chrome-linux64.zip',
                '8cdeb344e9b2cefe59f4aea8d1d93d5d93054c03cde217665c16fc1f62e72a66', 'chrome-linux64/chrome'),
    'mac-arm64': ('https://storage.googleapis.com/chrome-for-testing-public/%s/mac-arm64/chrome-mac-arm64.zip',
                  '3406b38b52b7d341d74450eb7b369be038c9fec9894c8b8a9e9e9f97333caf2f',
                  'chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'),
}
SYSTEM = ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser',
          '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/Applications/Chromium.app/Contents/MacOS/Chromium')


def cache() -> Path:
    return Path(os.environ.get('BW_CHROME_CACHE') or Path.home() / '.cache' / 'brickwork' / 'chrome')


def platform_key() -> str | None:
    system, machine = platform.system(), platform.machine().lower()
    if system == 'Linux' and machine in ('x86_64', 'amd64'):
        return 'linux64'
    if system == 'Darwin' and machine in ('arm64', 'aarch64'):
        return 'mac-arm64'
    return None


def explicit() -> str | None:
    for name in ('CHROME', 'BW_COLLECTION_CHROME'):
        value = os.environ.get(name)
        if value:
            return value if Path(value).is_file() else None
    return None


def pinned_binary() -> Path | None:
    key = platform_key()
    return cache() / VERSION / BUILDS[key][2] if key else None


def pinned_cached() -> str | None:
    binary = pinned_binary()
    return str(binary) if binary and binary.is_file() else None


def system() -> str | None:
    for name in SYSTEM:
        found = shutil.which(name) or (name if name.startswith('/') and Path(name).is_file() else None)
        if found:
            return found
    return None


def download() -> str:
    """Fetch, verify and unpack the pinned build; returns its binary. Raises RuntimeError with the reason."""
    key = platform_key()
    if key is None:
        raise RuntimeError(f'no pinned Chrome for Testing for {platform.system()} {platform.machine()}: set CHROME to a Chrome binary')
    url, checksum, inner = BUILDS[key]
    url = url % VERSION
    if not shutil.which('unzip'):
        raise RuntimeError('unzip is not installed (needed to unpack Chrome for Testing)')
    target = cache() / VERSION
    target.mkdir(parents=True, exist_ok=True)
    with (target / '.install.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)                                   # one install at a time; a waiter finds it done
        if (target / inner).is_file():
            return str(target / inner)
        return _install(url, checksum, inner, key, target)


def _install(url, checksum, inner, key, target) -> str:
    with tempfile.TemporaryDirectory(dir=target) as scratch:
        archive = Path(scratch) / 'chrome.zip'
        print(f'Downloading Chrome for Testing {VERSION} ({key}) into {target} ...', file=sys.stderr, flush=True)   # stdout is only the path
        try:
            with urllib.request.urlopen(url, timeout=120) as response, archive.open('wb') as out:
                shutil.copyfileobj(response, out)
        except OSError as error:
            raise RuntimeError(f'cannot download {url}: {error} (no network? set CHROME, or BW_SKIP_RENDERED=1 to skip rendered tests)') from None
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != checksum:
            raise RuntimeError(f'{url} has SHA-256 {digest}, expected {checksum}; refusing it')
        unpacked = Path(scratch) / 'unpacked'
        subprocess.run(['unzip', '-q', str(archive), '-d', str(unpacked)], check=True, stdout=sys.stderr)
        binary = unpacked / inner
        if not binary.is_file():
            raise RuntimeError(f'{inner} is not in the downloaded archive')
        top = target / inner.split('/')[0]
        if top.exists():                                                   # a half-installed earlier attempt (the lock is held)
            shutil.rmtree(top)
        shutil.move(str(unpacked / inner.split('/')[0]), str(target / inner.split('/')[0]))
    return str(target / inner)


def find(*, fetch: bool) -> tuple[str, str]:
    """(binary, how) for the browser to use; raises RuntimeError when there is none. `how`: env, pinned, downloaded or system."""
    if explicit():
        return explicit(), 'env'
    if pinned_cached():
        return pinned_cached(), 'pinned'
    if fetch:
        try:
            return download(), 'downloaded'
        except RuntimeError as error:
            found = system()
            if found:
                print(f'NOTE: {error}\nNOTE: using the system browser {found}; it is not the pinned build, so screenshot pixels may differ.',
                      file=sys.stderr)
                return found, 'system'
            raise
    found = system()
    if found:
        return found, 'system'
    raise RuntimeError('no Chrome found: set CHROME, run `python3 scripts/chrome.py ensure`, or set BW_SKIP_RENDERED=1 to skip rendered tests')


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else 'path'
    try:
        if mode == 'pinned':
            if explicit():
                binary = explicit()
            else:
                binary = pinned_cached() or download()
        else:
            binary, how = find(fetch=mode == 'ensure')
    except RuntimeError as error:
        print(f'CHROME: {error}', file=sys.stderr)
        return 1
    print(binary)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
