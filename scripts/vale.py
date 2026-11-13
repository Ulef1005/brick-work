"""Vale, the prose linter of the docs (App Docs Standard: User Docs § Vale): fetch the pinned release, then run it over docs/.

    python3 scripts/vale.py path          print the Vale binary to use, downloading the pinned release into the cache first when it is not there
    python3 scripts/vale.py check [--gate]  lint docs/ with .vale.ini; a report (exit 0) unless --gate, which exits 1 on any finding at warning level or above

The binary is pinned by version and by the SHA-256 of the archive from the release's own checksums file; an archive with another checksum is
refused. The cache is `$BW_VALE_CACHE` (default `~/.cache/brickwork/vale`), one folder per version. `$VALE` names a binary to use instead (the pin is
then not checked). The style packs (Microsoft v0.15.1, Google v0.7.1, MIT) are copied into `.vale/styles/` and committed, so Vale never needs the
network to sync them; `.vale/README.md` says where they come from. Platforms with no pinned checksum (anything but linux x86-64 and macOS on Apple
silicon) set VALE themselves. Standard library only.
"""
import hashlib
import io
import os
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
VERSION = '3.25.1'   # published 2026-10-22; v3.26.0 (2026-10-31) and v3.27.0 (2026-11-12) are younger than the two-week rule of the release watch
# The vendored style packs under .vale/styles/ (errata-ai/Microsoft and errata-ai/Google releases, MIT); one line each so release watch can read the pin.
MICROSOFT_PACK = 'v0.15.1'
GOOGLE_PACK = 'v0.7.1'
URL = 'https://github.com/errata-ai/vale/releases/download/v%s/vale_%s_%s.tar.gz'
# platform -> (asset name, SHA-256 of the archive from vale_3.25.1_checksums.txt). Checked 2026-11-13.
BUILDS = {
    'linux-x86_64': ('Linux_64-bit', '4bf5c5176b682b1da0830f471584d3494f1c2e27ee3029e1ad6f6661d4962182'),
    'darwin-arm64': ('macOS_arm64', 'fbcaa68d9b9e229b9c8dc918f209e93572ce943039700b7e04a423ff12f684cd'),
}


def cache():
    return Path(os.environ.get('BW_VALE_CACHE') or Path.home() / '.cache' / 'brickwork' / 'vale') / VERSION


def build_key():
    return f'{platform.system().lower()}-{platform.machine().lower().replace("amd64", "x86_64").replace("aarch64", "arm64")}'


def binary():
    """The Vale binary: $VALE, else the pinned release from the cache (downloaded and verified when missing)."""
    if os.environ.get('VALE'):
        return os.environ['VALE']
    key = build_key()
    if key not in BUILDS:
        raise SystemExit(f'No pinned Vale for {key}; install Vale and set VALE to its path.')
    target = cache() / 'vale'
    if target.exists():
        return str(target)
    asset, checksum = BUILDS[key]
    with urllib.request.urlopen(URL % (VERSION, VERSION, asset), timeout=120) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != checksum:
        raise SystemExit(f'Vale {VERSION} {asset}: the archive does not match the pinned SHA-256; refused.')
    cache().mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        member = archive.getmember('vale')
        target.write_bytes(archive.extractfile(member).read())
    target.chmod(0o755)
    return str(target)


def check(gate):
    result = subprocess.run([binary(), '--output=line', '--no-exit', 'docs'], cwd=ROOT, capture_output=True, text=True)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    for line in lines:
        print(line)
    if result.returncode:
        print(result.stderr.strip(), file=sys.stderr)
        return result.returncode
    print(f'Vale: {len(lines)} finding(s)' + ('' if gate else ' (report only)'))
    return 1 if gate and lines else 0


def main(argv):
    if argv == ['path']:
        print(binary())
        return 0
    if argv in (['check'], ['check', '--gate']):
        return check(argv == ['check', '--gate'])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
