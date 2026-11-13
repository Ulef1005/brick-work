"""scripts/vale.py: the pinned Vale download is verified, and a seeded bad page fails the gate (App Docs Standard: User Docs, Vale)."""
import importlib.util
import io
import os
import shutil
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("vale_script", ROOT / "scripts/vale.py")
vale = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vale)


class Response:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def archive(content=b'#!/bin/sh\necho vale\n'):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w:gz') as tar:
        info = tarfile.TarInfo('vale')
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    return out.getvalue()


def test_an_archive_with_another_checksum_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv('BW_VALE_CACHE', str(tmp_path))
    monkeypatch.delenv('VALE', raising=False)
    monkeypatch.setattr(vale, 'build_key', lambda: 'linux-x86_64')
    monkeypatch.setattr(vale.urllib.request, 'urlopen', lambda *args, **kwargs: Response(archive()))
    with pytest.raises(SystemExit, match='does not match the pinned SHA-256'):
        vale.binary()
    assert not list(tmp_path.rglob('vale'))


def test_an_archive_with_the_pinned_checksum_is_extracted_and_cached(tmp_path, monkeypatch):
    data = archive()
    monkeypatch.setenv('BW_VALE_CACHE', str(tmp_path))
    monkeypatch.delenv('VALE', raising=False)
    monkeypatch.setattr(vale, 'build_key', lambda: 'linux-x86_64')
    monkeypatch.setitem(vale.BUILDS, 'linux-x86_64', ('Linux_64-bit', vale.hashlib.sha256(data).hexdigest()))
    monkeypatch.setattr(vale.urllib.request, 'urlopen', lambda *args, **kwargs: Response(data))
    path = Path(vale.binary())
    assert path == tmp_path / vale.VERSION / 'vale' and path.stat().st_mode & 0o111
    monkeypatch.setattr(vale.urllib.request, 'urlopen', lambda *args, **kwargs: pytest.fail('cached: no second download'))
    assert vale.binary() == str(path)


def test_an_unpinned_platform_asks_for_VALE(monkeypatch):
    monkeypatch.delenv('VALE', raising=False)
    monkeypatch.setattr(vale, 'build_key', lambda: 'windows-amd64')
    with pytest.raises(SystemExit, match='set VALE'):
        vale.binary()


@pytest.mark.skipif(shutil.which('vale') is None and not os.environ.get('VALE') and not (Path.home() / '.cache/brickwork/vale').exists(), reason='no Vale binary available offline')
def test_a_seeded_bad_page_fails_the_gate(tmp_path, monkeypatch):
    binary = os.environ.get('VALE') or shutil.which('vale') or vale.binary()
    root = tmp_path / 'repo'
    (root / 'docs/how-to').mkdir(parents=True)
    shutil.copytree(ROOT / '.vale', root / '.vale')
    shutil.copy(ROOT / '.vale.ini', root / '.vale.ini')
    (root / 'docs/how-to/x.md').write_text('# Do it\n\nYou cannot do this and I think it is not great and it goes on and on and on and on and on and on and on '
                                           'and on and on and on and on and on and on and on and on and on and on forever.\n')
    monkeypatch.setattr(vale, 'ROOT', root)
    monkeypatch.setenv('VALE', binary)
    assert vale.check(gate=False) == 0
    assert vale.check(gate=True) == 1
