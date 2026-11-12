"""The browser for the rendered tests and the screenshot gate (D3, #160): find a Chrome, or fetch the pinned Chrome for Testing.

    python3 scripts/chrome.py path      print the Chrome binary to use; exit 1 and say why when there is none
    python3 scripts/chrome.py ensure    the same, downloading the pinned build into the cache first when nothing else is found
    python3 scripts/chrome.py shell     print the pinned chrome-headless-shell (macOS on Apple silicon only), downloading it if it is not cached
    python3 scripts/chrome.py pinned    print the pinned build's binary, downloading it if it is not cached (the screenshot gate uses this)

Order: the CHROME environment variable (BW_COLLECTION_CHROME is the old name and still read), the pinned chrome-headless-shell when BW_CHROME_HEADLESS_SHELL=1
(macOS on Apple silicon; `path` and `ensure` only, never `pinned`), the pinned Chrome for Testing in the cache (`$BW_CHROME_CACHE`, default `~/.cache/brickwork/chrome/<version>/`), a system Chrome or Chromium, and, for `ensure` only, a download.
The download is pinned by version and by the SHA-256 of the zip; a zip with another checksum is deleted and refused. Platforms with no
pinned checksum (anything but linux x86-64 and macOS on Apple silicon) set CHROME themselves.
`dump_dom()` runs `chrome --headless=new --dump-dom` with a bounded retry, for the rendered tests (#293).
Pixels from a system Chrome differ from the pinned build's, so the screenshot gate asks for `pinned` (or an explicit CHROME). Standard library only; `unzip` must be installed (it keeps the macOS bundle's symlinks)."""
import hashlib
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time
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
# The headless shell (macOS on Apple silicon only; the Linux and CI browser stays the full Chrome above): a separate, smaller browser without the
# window server, so it prints no CVDisplayLink noise. Same version, same pinning. Checked 2026-11-12. `shell` mode and BW_CHROME_HEADLESS_SHELL.
SHELL_BUILDS = {
    'mac-arm64': ('https://storage.googleapis.com/chrome-for-testing-public/%s/mac-arm64/chrome-headless-shell-mac-arm64.zip',
                  'e6a6b13551aa12f951d0891d79282606b13742837c8fa0505e1272bae116ce82', 'chrome-headless-shell-mac-arm64/chrome-headless-shell'),
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


def shell_cached() -> str | None:
    key = platform_key()
    binary = cache() / VERSION / SHELL_BUILDS[key][2] if key in SHELL_BUILDS else None
    return str(binary) if binary and binary.is_file() else None


def download(builds: dict | None = None) -> str:
    """Fetch, verify and unpack the pinned build (`builds`: BUILDS, or SHELL_BUILDS for the headless shell); returns its binary. Raises RuntimeError with the reason."""
    builds = builds or BUILDS
    key = platform_key()
    if key is None or key not in builds:
        raise RuntimeError(f'no pinned Chrome for Testing for {platform.system()} {platform.machine()}: set CHROME to a Chrome binary')
    url, checksum, inner = builds[key]
    url = url % VERSION
    if not shutil.which('unzip'):
        raise RuntimeError('unzip is not installed (needed to unpack Chrome for Testing)')
    target = cache() / VERSION
    target.mkdir(parents=True, exist_ok=True)
    import fcntl                                                           # POSIX only, and only needed to install (Windows sets CHROME)
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


def shell_wanted() -> bool:
    """BW_CHROME_HEADLESS_SHELL=1 on macOS on Apple silicon: the rendered tests use the pinned chrome-headless-shell (an option, off by default)."""
    return os.environ.get('BW_CHROME_HEADLESS_SHELL') == '1' and platform_key() in SHELL_BUILDS


def find(*, fetch: bool) -> tuple[str, str]:
    """(binary, how) for the browser to use; raises RuntimeError when there is none. `how`: env, shell, pinned, downloaded or system."""
    if explicit():
        return explicit(), 'env'
    if shell_wanted():
        if shell_cached():
            return shell_cached(), 'shell'
        if fetch:
            try:
                return download(SHELL_BUILDS), 'shell'
            except RuntimeError as error:
                print(f'NOTE: {error}\nNOTE: BW_CHROME_HEADLESS_SHELL is ignored.', file=sys.stderr)
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


def _stderr_tail(text: str, lines: int = 15) -> str:
    """The last lines of Chrome's stderr; the CVDisplayLinkCreateWithCGDisplay line macOS prints on every start is noise and left out."""
    kept = [line for line in text.splitlines() if line.strip() and 'CVDisplayLinkCreateWithCGDisplay' not in line]
    return '\n'.join(kept[-lines:])


def dump_dom(chrome: str, url: str, *, budget_ms: int | None = 3000, attempts: int | None = None, timeout: float = 60,
             args: tuple[str, ...] = ('--no-sandbox', '--disable-gpu')) -> str:
    """The DOM `chrome --headless=new --dump-dom URL` prints (with `--virtual-time-budget=budget_ms` when given). On macOS under load a start can stall
    or end in "Teardown watchdog expired" (#293), so a launch that exits non-zero or outlives `timeout` is killed (its whole process group) and run
    again with a fresh user-data-dir, up to `attempts` times (BW_CHROME_ATTEMPTS, default 3). The DOM of a successful run is returned unchanged; when
    every attempt failed, RuntimeError names how each ended and the last stderr lines. A run that exits 0 is never retried, so what the page
    contains is asserted on exactly as before."""
    attempts = attempts or int(os.environ.get('BW_CHROME_ATTEMPTS') or 3)
    failures, last_stderr = [], ''
    for number in range(1, attempts + 1):
        with tempfile.TemporaryDirectory(prefix='bw-dump-') as profile:
            headless = [] if Path(chrome).name == 'chrome-headless-shell' else ['--headless=new']      # the shell is headless by itself
            command = [chrome, *headless, *args, f'--user-data-dir={profile}', *([f'--virtual-time-budget={budget_ms}'] if budget_ms else []),
                       '--dump-dom', url]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            try:
                out, err = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_group(process)
                out, err = process.communicate()
                failures.append(f'attempt {number}: no result within {timeout:g} s')
                last_stderr = err
                continue
            finally:
                _kill_group(process)                                       # helpers a finished Chrome left behind
            if process.returncode == 0:
                return out
            failures.append(f'attempt {number}: exit {process.returncode}')
            last_stderr = err
        time.sleep(0.5 * number)
    raise RuntimeError(f'chrome --dump-dom failed after {attempts} attempts ({"; ".join(failures)})\nlast stderr lines:\n{_stderr_tail(last_stderr)}')


def _kill_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else 'path'
    try:
        if mode == 'shell':
            binary = shell_cached() or download(SHELL_BUILDS)
        elif mode == 'pinned':
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
