"""Guard runtime assets copied by Dockerfile's COPY . . against .dockerignore."""
from pathlib import Path
import posixpath
import re
import subprocess

import pytest
import yaml

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
        'docs/brickwork/openapi-v2.yaml',
        'brickwork/api2/write_contract.json',
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


def test_release_workflow_publishes_only_on_the_maintainers_switch():
    """#78: the release workflow builds and smoke-tests every v* tag on both architectures; every step that writes to GHCR (log in,
    push, manifest, attestations) runs only when the repository variable GHCR_PUBLISH is true, which is set on the maintainer's go."""
    source = (ROOT / '.github/workflows/release.yml').read_text()
    workflow = yaml.safe_load(source)
    triggers = workflow[True]                                          # PyYAML reads the key `on` as True
    assert triggers['push'] == {'tags': ['v*']} and 'workflow_dispatch' in triggers
    assert workflow['permissions'] == {'contents': 'read'}
    jobs = workflow['jobs']
    assert "vars.GHCR_PUBLISH" in source and source.count('${{ vars.') == 1   # the one switch, read once, into `publish`
    for name, job in jobs.items():
        for step in job.get('steps', []):
            uses = step.get('uses', '')
            if uses:
                assert re.fullmatch(r'[\w.-]+/[\w.-]+@[0-9a-f]{40}', uses), (name, uses)
            writes = (uses.startswith(('docker/login-action@', 'actions/attest', 'anchore/sbom-action@', 'actions/upload-artifact@',
                                       'actions/download-artifact@'))
                      or 'push=true' in str(step.get('with', {}).get('outputs', '')) or 'imagetools create' in step.get('run', ''))
            if writes:
                assert step.get('if') == "needs.version.outputs.publish == 'true'", (name, step.get('name') or uses)
    smoke = [s for s in jobs['build']['steps'] if s.get('name') == 'Smoke test fresh installation']
    push = [i for i, s in enumerate(jobs['build']['steps']) if s.get('name') == 'Push by digest']
    assert smoke and push and jobs['build']['steps'].index(smoke[0]) < push[0]        # tested before anything is pushed
    assert {m['platform'] for m in jobs['build']['strategy']['matrix']['include']} == {'linux/amd64', 'linux/arm64'}
    assert jobs['publish']['permissions'] == {'contents': 'read', 'packages': 'write', 'id-token': 'write', 'attestations': 'write'}


RELEASE_TAGS = ['v0.8.1', 'v0.9.0', 'v0.9.1', 'v1.0.0-rc.1']


@pytest.mark.parametrize('tag,tags', [
    ('v0.9.1', '0.9.1 0.9 0 latest'),          # the highest stable release moves every alias
    ('v0.9.0', '0.9.0'),                        # a rebuild of an older one moves none (Codex review)
    ('v0.8.1', '0.8.1 0.8'),                    # the highest of its X.Y line, not of 0 or overall
    ('v1.0.0-rc.1', '1.0.0-rc.1'),              # a pre-release gets only its own tag
])
def test_release_workflow_tags(tag, tags, tmp_path):
    """The tag step's own bash, in a repository holding RELEASE_TAGS: aliases only to the highest stable release they cover, the
    tagged commit as the revision, and anything that is not a release tag refused."""
    script = next(s for s in yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text())['jobs']['version']['steps'] if s.get('id') == 'read')['run']
    repo = tmp_path / 'repo'
    vcs = lambda *a: subprocess.run(['git', '-C', str(repo), *a], check=True, capture_output=True, text=True).stdout.strip()
    repo.mkdir()
    vcs('init', '-q')
    revisions = {}
    for t in RELEASE_TAGS:
        vcs('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', t)
        vcs('tag', t)
        revisions[t] = vcs('rev-parse', 'HEAD')
    out = tmp_path / 'out'
    run = lambda t, p='': subprocess.run(['bash', '-c', script], cwd=repo, capture_output=True, text=True,
                                         env={'TAG': t, 'PUBLISH': p, 'GITHUB_OUTPUT': str(out), 'PATH': '/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin'})
    result = run(tag)
    assert result.returncode == 0, result.stderr
    lines = dict(line.split('=', 1) for line in out.read_text().splitlines())
    assert lines['tags'] == tags and lines['publish'] == 'false' and lines['version'] == tag[1:]
    assert lines['revision'] == revisions[tag]
    out.unlink()
    assert run(tag, 'true').returncode == 0 and 'publish=true' in out.read_text()
    for bad in ('main', 'v0.9', 'v0.9.0; rm -rf /', '0.9.0'):
        assert run(bad).returncode != 0, bad
