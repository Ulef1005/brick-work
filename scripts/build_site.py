"""Build the documentation site for GitHub Pages from the repository.

    python scripts/build_site.py OUT_DIR

Pages: `/` the README, `/api/` the OpenAPI contract as one reference page (Redoc), `/mcp/` the MCP
guide with the tool and resource tables generated from the server itself. No site generator: Markdown
is rendered with Python-Markdown, styled with the app's own design tokens and fonts. Links to files in
the repository point at them on GitHub. The output is static and needs no server.
"""
import argparse
import html
import os
import re
import shutil
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REDOC = 'https://cdn.jsdelivr.net/npm/redoc@2.5.0/bundles/redoc.standalone.js'
PAGES = (('Home', ''), ('API reference', 'api/'), ('MCP', 'mcp/'))


def repository():
    """The GitHub repository the links point at: GITHUB_REPOSITORY in Actions, else the project's own."""
    return os.environ.get('GITHUB_REPOSITORY') or 'Ulef1005/brick-work'


def blob(path):
    return f'https://github.com/{repository()}/blob/main/{path}'


def rewrite_links(text, base, depth=0):
    """Relative links in a Markdown file: to another page of this site, or to the file on GitHub."""
    def link(match):
        label, target = match.group(1), match.group(2)
        if re.match(r'^[a-z][a-z0-9+.-]*:|^#|^/', target):
            return match.group(0)
        path, _, anchor = target.partition('#')
        resolved = os.path.normpath(os.path.join(base, path)).replace(os.sep, '/')
        up = '../' * depth
        local = {'README.md': up or './', 'docs/brickwork/mcp.md': up + 'mcp/', 'docs/brickwork/openapi-v1.yaml': up + 'api/'}
        if resolved in local:
            url = local[resolved]
        else:
            url = blob(resolved)
        return f'[{label}]({url}{"#" + anchor if anchor else ""})'
    return re.sub(r'(?<!!)\[([^\]]+)\]\(([^)\s]+)\)', link, text)


def render(text):
    return markdown.markdown(text, extensions=['fenced_code', 'tables', 'toc', 'sane_lists'],
                             extension_configs={'toc': {'permalink': False}})


def page(title, body, depth, *, current, head=''):
    up = '../' * depth
    nav = ''.join(f'<a href="{up}{href}"{" aria-current=\"page\"" if name == current else ""}>{name}</a>'
                  for name, href in PAGES)
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} · Brick Work</title>
<meta name="description" content="Brick Work: a self-hosted workbench for your LEGO® collection, with a REST API and an MCP server.">
<link rel="icon" href="{up}assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{up}assets/tokens-v2.css">
<link rel="stylesheet" href="{up}assets/site.css">
{head}
</head>
<body>
<header class="site-head"><a class="brand" href="{up}"><img src="{up}assets/app-icon.svg" alt="" width="28" height="28"><span>Brick Work</span></a>
<nav aria-label="Documentation">{nav}<a href="https://github.com/{repository()}">GitHub</a></nav></header>
<main class="doc">{body}</main>
<footer class="site-foot"><p>Brick Work is MIT-licensed and inspired by BrickTracker. LEGO® is a trademark of the LEGO Group of companies, which does not sponsor, authorize or endorse this project.</p></footer>
</body>
</html>
'''


def mcp_tables():
    """Read tools, write tools and resources, from the adapter the server itself uses."""
    from brickwork.core.mcp import Adapter, contract
    adapter = Adapter(client=None)
    rows = {'GET': [], 'write': []}
    for name, (method, path, op) in sorted(adapter.tools.items()):
        arguments = ', '.join(f'`{a}`' for a in adapter.schema(op)['properties']) or 'none'
        line = f'| `{name}` | {html.escape(op.get("summary", "")).capitalize()} | {arguments} | `{method} /api/v1{path}` |'
        rows['GET' if method == 'GET' else 'write'].append(line)
    head = '| Tool | What it does | Arguments | API call |\n|---|---|---|---|'
    resources = contract().get('x-mcp', {}).get('resources', [])
    resource_rows = '\n'.join(f'| `{r.get("uri")}` | {html.escape(str(r.get("description") or r.get("reads") or ""))} |'
                              for r in resources if isinstance(r, dict))
    text = (f'\n### Read tools ({len(rows["GET"])})\n\n{head}\n' + '\n'.join(rows['GET']) +
            f'\n\n### Write tools ({len(rows["write"])}, only with a write token and `--allow-write`)\n\n{head}\n' + '\n'.join(rows['write']))
    if resource_rows:
        text += f'\n\n### Resources ({len(resources)})\n\n| URI | Reads |\n|---|---|\n{resource_rows}'
    return text + '\n'


def build(out):
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    (out / 'assets' / 'fonts').mkdir(parents=True)
    (out / 'api').mkdir()
    (out / 'mcp').mkdir()
    static = ROOT / 'static'
    shutil.copy(static / 'web/toni/tokens-v2.css', out / 'assets/tokens-v2.css')
    for font in (static / 'web/toni/fonts').glob('*'):
        shutil.copy(font, out / 'assets/fonts' / font.name)
    for name in ('app-icon.svg', 'favicon.svg'):
        shutil.copy(static / 'brickwork' / name, out / 'assets' / name)
    shutil.copy(ROOT / 'scripts/site/site.css', out / 'assets/site.css')

    readme = rewrite_links((ROOT / 'README.md').read_text(), '.', 0)
    (out / 'index.html').write_text(page('Documentation', render(readme), 0, current='Home'))

    guide = rewrite_links((ROOT / 'docs/brickwork/mcp.md').read_text(), 'docs/brickwork', 1) + mcp_tables()
    (out / 'mcp/index.html').write_text(page('MCP server', render(guide), 1, current='MCP'))

    shutil.copy(ROOT / 'docs/brickwork/openapi-v1.yaml', out / 'api/openapi-v1.yaml')
    body = ('<p class="api-note">The REST API at <code>/api/v1</code>. Download the contract as '
            '<a href="openapi-v1.yaml">openapi-v1.yaml</a>; the guide, with authentication and examples, is '
            f'<a href="{blob("docs/brickwork/api-v1.md")}">api-v1.md</a>.</p>'
            '<div id="redoc"></div>'
            f'<script src="{REDOC}" crossorigin="anonymous"></script>'
            '<script>Redoc.init("openapi-v1.yaml", {hideDownloadButton: false, expandResponses: "200,201"}, '
            'document.getElementById("redoc"))</script>')
    (out / 'api/index.html').write_text(page('API reference', body, 1, current='API reference').replace(
        '<main class="doc">', '<main class="doc api">'))
    (out / '.nojekyll').write_text('')
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('out')
    built = build(parser.parse_args(argv).out)
    print(f'Built the documentation site in {built}')


if __name__ == '__main__':
    main()
