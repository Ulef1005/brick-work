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
PROSE = ('README.md', 'CONTRIBUTING.md', 'SECURITY.md', 'docs/brickwork/mcp.md', 'docs/brickwork/api-v2.md')
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
    assert sorted(named - settings_in_code() - tooling_variables()) == []


def tooling_variables():
    """The BW_ variables of the test and check tooling (BW_SKIP_RENDERED, BW_CHROME_CACHE, ...): not app settings, but CONTRIBUTING names them."""
    names = set()
    for path in [*(ROOT / 'scripts').iterdir(), ROOT / 'tests' / 'rendered.py']:
        if path.suffix in ('.py', '.sh', '.cjs'):
            names |= set(CODE.findall(path.read_text(errors='replace')))
    return names


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
        for name in re.findall(r'`brickwork ([a-z][a-z0-9-]*)', (ROOT / doc).read_text()):
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
    for page in ('index.html', 'docs/index.html', 'use-cases/index.html', 'workflows/index.html', 'api/index.html', 'api/openapi-v2.yaml', 'mcp/index.html', 'assets/site.css', '.nojekyll'):
        assert (site / page).is_file(), page
    # The API v2 and MCP references are generated in the Developers tab (#319); the old URLs keep a stub that points there.
    api = (site / 'docs/developer/api-v2-reference/index.html').read_text()   # the retired v1 contract is not what the site documents (#125)
    assert '<code>/api/v2</code>' in api and 'GET <code>/items/{id}</code>' in api and 'openapi-v1' not in api
    assert 'id="get-itemsid"' in api and 'exec-1' not in api and 'docs_reference' not in api
    assert 'flag imported from &lt;site&gt;' in api   # a summary's placeholder is text, not a raw HTML tag
    assert 'href="../docs/developer/api-v2-reference/"' in (site / 'changelog/index.html').read_text()
    mcp = (site / 'docs/developer/mcp-reference/index.html').read_text()
    for name in Adapter(client=None).tools:
        assert f'<code>{name}</code>' in mcp, name
    code = (site / 'docs/developer/code-reference/index.html').read_text()   # rendered by mkdocstrings from the docstrings (ADR 0030)
    from brickwork.core import valuation
    assert 'id="brickwork.core.valuation"' in code and 'id="brickwork.core.valuation.valuation"' in code and 'the insurance report' in code
    assert '_migrations' not in code   # the importer's migrations are upstream code copied unchanged, not Brick Work's reference
    assert 'Brick Work&#39;s services on the 4.0 store' in code or "Brick Work's services on the 4.0 store" in code
    assert 'url=../docs/developer/api-v2-reference/' in (site / 'api/index.html').read_text()
    assert 'url=../docs/brickwork/mcp/' in (site / 'mcp/index.html').read_text()
    assert (site / 'docs/brickwork/mcp/index.html').is_file() and (site / 'docs/brickwork/openapi-v2.yaml').is_file()
    assert 'BW_AUTHENTICATION_PASSWORD' in (site / 'docs/reference/settings/index.html').read_text()
    # The changelog keeps its links to docs pages on the site; the ADRs and the 4.0 design are on GitHub, not on the site (ADR 0030).
    changelog = (site / 'changelog/index.html').read_text()
    assert 'id="v0.6.0"' in changelog and 'href="../docs/how-to/receive-an-order/"' in changelog
    from scripts.build_site import blob
    assert 'href="docs/adr' not in changelog and 'href="../docs/adr' not in changelog    # a repository link never stays relative (ADR 0030)
    assert not (site / 'design').exists()
    docs_design = (site / 'docs/data-model-4.0/data-model-design/index.html').read_text()   # the same page in the Developers tab (#319)
    assert docs_design.count('This diagram is drawn on GitHub') == 2 and 'language-mermaid' not in docs_design
    assert (site / 'docs/pitch/brick-work-pitch.pdf').is_file() and not (site / 'docs/brickwork/api-v1/index.html').exists()
