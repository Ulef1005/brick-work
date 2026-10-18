"""#65: the image runs unprivileged, checks its health and refuses an unwritable data folder."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_drops_root_and_checks_health():
    text = (ROOT / 'Dockerfile').read_text()
    assert 'USER 1000:1000' in text
    assert text.index('USER 1000:1000') < text.index('ENTRYPOINT')
    assert 'HEALTHCHECK' in text and '/api/v1/health' in text
    assert 'chown 1000:1000 /app/data' in text and 'go-w' in text


def test_local_compose_stays_on_this_computer():
    assert '"127.0.0.1:3334:3333"' in (ROOT / 'compose.local.yaml').read_text()


def test_entrypoint_refuses_an_unwritable_data_folder(tmp_path):
    script = (ROOT / 'entrypoint.sh').read_text().replace('/app/data', str(tmp_path / 'data'))
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data').chmod(0o500)
    entry = tmp_path / 'entrypoint.sh'
    entry.write_text(script)
    try:
        result = subprocess.run(['sh', str(entry)], capture_output=True, text=True, env=dict(os.environ, PATH='/usr/bin:/bin'))
    finally:
        (tmp_path / 'data').chmod(0o700)
    if os.geteuid() == 0:
        return  # root can write anywhere; the check is for the unprivileged image
    assert result.returncode == 1
    assert 'chown -R' in result.stderr
