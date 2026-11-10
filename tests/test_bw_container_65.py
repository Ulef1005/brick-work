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


def entrypoint_with_stubs(tmp_path, setup_exit):
    entry = tmp_path / 'entrypoint.sh'
    entry.write_text((ROOT / 'entrypoint.sh').read_text().replace('/app/data', str(tmp_path / 'data')))
    for name, body in {
        'brickwork': f'printf "brickwork\\n" >> "$CALLS"\nprintf "%s\\n" "$@" >> "$CALLS"\nexit {setup_exit}\n',
        'gunicorn': 'printf "gunicorn\\n" >> "$CALLS"\nprintf "%s\\n" "$@" >> "$CALLS"\n',
    }.items():
        stub = tmp_path / name
        stub.write_text('#!/bin/sh\n' + body)
        stub.chmod(0o700)
    calls = tmp_path / 'calls'
    env = dict(os.environ, PATH=str(tmp_path) + os.pathsep + '/usr/bin:/bin',
               CALLS=str(calls), BW_HOST='127.0.0.1', BW_PORT='4321')
    result = subprocess.run(['sh', str(entry), '--log-level', 'debug', '--access-logformat', 'user argument'],
                            capture_output=True, text=True, env=env)
    return result, calls.read_text().splitlines()


def test_entrypoint_sets_up_before_gunicorn_without_control_socket(tmp_path):
    result, calls = entrypoint_with_stubs(tmp_path, 0)
    assert result.returncode == 0, result.stderr
    assert calls == [
        'brickwork', 'setup', '--if-missing',
        'gunicorn', '--bind', '127.0.0.1:4321', 'wsgi:application',
        '--worker-class', 'gevent', '--workers', '1', '--timeout', '120',
        '--no-control-socket', '--log-level', 'debug', '--access-logformat', 'user argument',
    ]


def test_entrypoint_stops_when_setup_fails(tmp_path):
    result, calls = entrypoint_with_stubs(tmp_path, 1)
    assert result.returncode == 1
    assert result.stderr == 'Brick Work setup failed; the server will not start.\n'
    assert calls == ['brickwork', 'setup', '--if-missing']
