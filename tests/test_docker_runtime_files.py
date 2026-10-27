"""Guard runtime assets copied by Dockerfile's COPY . . against .dockerignore."""
from pathlib import Path
import posixpath
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def docker_ignored(path, source):
    """Small matcher for the Docker patterns used here (not gitignore).

    Strip whitespace and leading/trailing slashes, clean paths, skip comments
    and the historical '.' no-op. Match from the context root, including each
    parent directory; '*' and '?' cannot cross '/', while a '**' component
    matches zero or more directories. Last matching rule wins, including '!'
    rules below an excluded parent. Character classes and backslash escapes are
    not used in this repository; reject them rather than silently misparse them.
    """
    parents = [path[:i] for i, char in enumerate(path) if char == '/']
    ignored = False
    for line in source.splitlines():
        if line.startswith('#'):
            continue
        pattern = line.strip()
        include = pattern.startswith('!')
        if include:
            pattern = pattern[1:].strip()
        pattern = posixpath.normpath(pattern.strip('/'))
        if pattern == '.':
            continue
        if '[' in pattern or '\\' in pattern:
            raise ValueError('Extend the Docker matcher for character classes or escapes')
        pieces = pattern.split('/')
        expression = ''
        for i, piece in enumerate(pieces):
            if piece == '**':
                expression += '.*' if i == len(pieces) - 1 else '(?:[^/]+/)*'
            else:
                expression += ''.join({'*': '[^/]*', '?': '[^/]'}.get(char, re.escape(char))
                                      for char in piece)
                if i < len(pieces) - 1:
                    expression += '/'
        if any(re.fullmatch(expression, candidate) for candidate in [path, *parents]):
            ignored = not include
    return ignored


@pytest.mark.parametrize('source,path,ignored', [
    ('docs/\n!docs/web-ui/', 'docs/web-ui/coverage-manifest.json', False),
    ('docs/\n!docs/web-ui/\ndocs/web-ui/*.md', 'docs/web-ui/readme.md', True),
    ('docs/\n!docs/brickwork/openapi-v1.yaml', 'docs/brickwork/openapi-v1.yaml', False),
    ('docs/\n!docs/brickwork/openapi-v1.yaml', 'docs/brickwork/api-v1.md', True),
    ('!docs/web-ui/\ndocs/', 'docs/web-ui/coverage-manifest.json', True),
    ('**/*.py', 'brickwork/core/mcp/server.py', True),
    ('**/*.py', 'app.py', True),
    ('brickwork/**/schema.sql', 'brickwork/schema.sql', True),
    ('brickwork/**/schema.sql', 'brickwork/core/schema.sql', True),
    ('**/__pycache__', 'brickwork/core/__pycache__/x.pyc', True),
    ('*.md', 'brickwork/web/README.md', False),
    ('*.md', 'README.md', True),
    (' /docs/ \n! /docs/web-ui/ ', 'docs/web-ui/coverage-manifest.json', False),
    ('# comment\n.\n\n', 'brickwork/core/schema.sql', False),
    ('static/parts', 'static/parts-other/icon.svg', False),
    ('.?*', '.venv/bin/python', True),
    ('a?b', 'a/b', False),
    ('**', 'brickwork/core/schema.sql', True),
    ('docs/../brickwork/**', 'brickwork/core/schema.sql', True),
])
def test_docker_matching_rules(source, path, ignored):
    assert docker_ignored(path, source) is ignored


def test_runtime_files_in_docker_context():
    # Tracked files only: bytecode and downloaded images are local/generated data.
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    required = {
        'docs/brickwork/openapi-v1.yaml',
        'docs/brickwork/openapi-v2.yaml',
        'brickwork/api/write_contract.json',
        'brickwork/store4/brickwork.sql',
        'brickwork/store4/catalogue.sql',
        'app.py',
        'wsgi.py',
        'entrypoint.sh',
        'bin/brickwork',
    }
    required.update(name for name in tracked if name.startswith(('brickwork/', 'templates/', 'static/')))
    source = (ROOT / '.dockerignore').read_text()
    assert all((ROOT / name).is_file() for name in required)
    excluded = sorted(name for name in required if docker_ignored(name, source))
    assert not excluded, 'Runtime files excluded from Docker context: ' + ', '.join(excluded)


def test_docker_base_is_digest_pinned():
    base = (ROOT / 'Dockerfile').read_text().splitlines()[0]
    assert re.fullmatch(r'FROM python:[^@\s]+@sha256:[0-9a-f]{64}', base)


def test_docker_workflow_builds_without_publishing():
    import yaml

    source = (ROOT / '.github/workflows/docker.yml').read_text()
    workflow = yaml.safe_load(source)
    assert workflow['permissions'] == {'contents': 'read'}
    steps = workflow['jobs']['build']['steps']
    actions = [step['uses'] for step in steps if 'uses' in step]
    assert actions
    assert all(re.fullmatch(r'[\w.-]+/[\w.-]+@[0-9a-f]{40}', action) for action in actions)
    assert 'push: false' in source
    assert 'push: true' not in source
    build = next(step for step in steps if step.get('uses', '').startswith('docker/build-push-action@'))
    assert build['with']['push'] is False
    assert build['with']['load'] is True
