"""The documentation cannot drift from the code: settings, commands, links and the published site.

The API reference is the OpenAPI contract, which scripts/check_api_contract.py and the route parity
test already hold to the real routes; the MCP tool tables are generated from the server's own tool
table. These tests cover the hand-written prose.
"""
from pathlib import Path
import re
import shlex
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROSE = ('README.md', 'CONTRIBUTING.md', 'SECURITY.md', 'docs/brickwork/mcp.md', 'docs/brickwork/api-v1.md')
# The user docs: their links are checked by Zensical's strict build, their settings and commands here.
USER_DOCS = tuple(str(p.relative_to(ROOT)) for p in sorted((ROOT / 'docs').glob('*/*.md'))
                  if p.parts[-2] in ('tutorials', 'how-to', 'concepts', 'reference'))
CODE = re.compile(r'\bBW_[A-Z0-9_]*[A-Z0-9]\b')


def tracked(*paths):
    out = subprocess.run(['git', '-C', str(ROOT), '-c', 'core.fsmonitor=false', 'ls-files', '--cached', '--others',
                          '--exclude-standard', *paths], capture_output=True, text=True, check=True).stdout
    return [ROOT / p for p in out.split()]


def settings_in_code():
    names = set()
    for path in tracked('brickwork', 'app.py', 'wsgi.py', 'entrypoint.sh', 'bin'):
        if path.suffix in ('.py', '.sh', '') and path.is_file():
            names |= set(CODE.findall(path.read_text(errors='replace')))
    from brickwork.settings import SETTINGS
    names |= {'BW_' + key for key in SETTINGS}
    names |= {'BW_BRICKLINK_' + n for n in ('CONSUMER_KEY', 'CONSUMER_SECRET', 'TOKEN_VALUE', 'TOKEN_SECRET')}
    return names


def settings_table():
    reference = (ROOT / 'docs/reference/settings.md').read_text()
    return {name for line in reference.splitlines() if line.startswith('| `') for name in CODE.findall(line.split('|')[1])}


def test_every_setting_the_code_reads_is_in_the_reference():
    assert sorted(settings_in_code() - settings_table()) == []


def test_every_setting_in_the_reference_is_read_by_the_code():
    assert sorted(settings_table() - settings_in_code()) == []


@pytest.mark.parametrize('doc', PROSE + USER_DOCS + ('.env.sample',))
def test_settings_named_anywhere_exist(doc):
    named = set(CODE.findall((ROOT / doc).read_text()))
    assert sorted(named - settings_in_code()) == []


def command_lines(doc):
    """Shell lines in fenced code blocks, continuation lines joined, comments dropped."""
    text, lines, block = (ROOT / doc).read_text(), [], None
    for line in text.splitlines():
        if line.startswith('```'):
            block = None if block is not None else line[3:].strip()
            continue
        if block in ('sh', 'bash', 'shell', ''):
            lines.append(line)
    joined = re.sub(r'\\\n\s*', ' ', '\n'.join(lines))
    return [re.sub(r'\s+#.*$', '', l).strip() for l in joined.splitlines() if 'brickwork' in l]


def documented_commands():
    for doc in PROSE + USER_DOCS:
        for line in command_lines(doc):
            words = shlex.split(line)
            positions = [i for i, w in enumerate(words) if w == 'brickwork' and i + 1 < len(words)
                         and not words[i + 1].startswith('-') and words[i + 1] != 'brickwork']
            if positions:
                yield doc, line, words[positions[-1] + 1:]


@pytest.mark.parametrize('doc,line,argv', list(documented_commands()), ids=lambda v: v if isinstance(v, str) and len(v) < 60 else None)
def test_documented_commands_parse(doc, line, argv):
    from brickwork.web.cli import build_parser
    try:
        build_parser().parse_args(argv)
    except SystemExit:
        pytest.fail(f'{doc}: `{line}` is not a valid brickwork command')


def test_inline_commands_name_real_subcommands():
    from brickwork.web.cli import build_parser
    commands = set(build_parser()._subparsers._group_actions[0].choices)
    for doc in PROSE + USER_DOCS:
        for name in re.findall(r'`brickwork ([a-z][a-z-]*)', (ROOT / doc).read_text()):
            assert name in commands, f'{doc}: brickwork {name}'


@pytest.mark.parametrize('doc', PROSE)
def test_relative_links_point_at_files(doc):
    base = (ROOT / doc).parent
    for target in re.findall(r'(?<!!)\[[^\]]+\]\(([^)\s]+)\)', (ROOT / doc).read_text()):
        if re.match(r'^[a-z][a-z0-9+.-]*:|^#', target):
            continue
        path = (base / target.split('#', 1)[0]).resolve()
        assert path.exists(), f'{doc}: link to {target}'


def test_the_site_builds_with_every_tool(tmp_path):
    from scripts.build_site import build
    from brickwork.core.mcp import Adapter
    site = build(tmp_path / 'site')
    for page in ('index.html', 'docs/index.html', 'use-cases/index.html', 'workflows/index.html', 'api/index.html', 'api/openapi-v1.yaml', 'mcp/index.html', 'assets/site.css', '.nojekyll'):
        assert (site / page).is_file(), page
    mcp = (site / 'mcp/index.html').read_text()
    for name in Adapter(client=None).tools:
        assert f'<code>{name}</code>' in mcp, name
    assert 'BW_AUTHENTICATION_PASSWORD' in (site / 'docs/reference/settings/index.html').read_text()
