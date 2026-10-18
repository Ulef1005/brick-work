"""Build the documentation site for GitHub Pages from the repository.

    python scripts/build_site.py OUT_DIR

Pages: `/` the landing page, `/use-cases/` and `/workflows/` (Markdown in scripts/site), `/docs/` the README, `/demo/` the static demo (scripts/build_demo.py), `/api/` the OpenAPI contract as one local reference page, `/mcp/` the MCP
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
from urllib.parse import unquote

import markdown

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SITE = ROOT / 'scripts/site'
PAGES = (('Home', ''), ('Use cases', 'use-cases/'), ('Workflows', 'workflows/'), ('Demo', 'demo/'), ('Docs', 'docs/'),
         ('API reference', 'api/'), ('MCP', 'mcp/'))


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
        local = {'README.md': up + 'docs/', 'docs/brickwork/mcp.md': up + 'mcp/', 'docs/brickwork/openapi-v1.yaml': up + 'api/'}
        if resolved in local:
            url = local[resolved]
        else:
            url = blob(resolved)
        return f'[{label}]({url}{"#" + anchor if anchor else ""})'
    return re.sub(r'(?<!!)\[([^\]]+)\]\(([^)\s]+)\)', link, text)


def render(text):
    return markdown.markdown(text, extensions=['fenced_code', 'tables', 'toc', 'sane_lists'],
                             extension_configs={'toc': {'permalink': False}})


def page(title, body, depth, *, current, head='', main='doc'):
    up = '../' * depth
    nav = ''.join(f'<a href="{up}{href}"{" aria-current=\"page\"" if name == current else ""}>{name}</a>'
                  for name, href in PAGES)
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title) + " · Brick Work" if title != "Brick Work" else "Brick Work"}</title>
<meta name="description" content="Brick Work: the workbench for your brick collection: self-hosted, with a REST API and an MCP server.">
<link rel="icon" href="{up}assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{up}assets/tokens-v2.css">
<link rel="stylesheet" href="{up}assets/brick-work.css">
<link rel="stylesheet" href="{up}assets/site.css">
{head}
</head>
<body>
<header class="site-head"><a class="brand" href="{up}" aria-label="Brick Work home">{lockup(up)}</a>
<nav aria-label="Documentation">{nav}<a href="https://github.com/{repository()}">GitHub</a></nav><button class="js-only" type="button" data-theme-toggle aria-label="Switch theme">Theme</button></header>
<main class="{main}">{body}</main>
<footer class="site-foot"><div class="footer-inner"><div><a class="footer-brand" href="{up}">{lockup(up)}</a><p>Brick Work is MIT-licensed and inspired by BrickTracker. LEGO® is a trademark of the LEGO Group of companies, which does not sponsor, authorize or endorse this project.</p></div><nav aria-label="Footer"><a href="{up}demo/">Demo</a><a href="{up}docs/">Docs</a><a href="https://github.com/users/Ulef1005/projects/3">Roadmap</a><a href="https://github.com/{repository()}">GitHub</a></nav></div></footer>
<script src="{up}assets/site.js" defer></script>
</body>
</html>
'''


def lockup(up):
    return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="{up}assets/lockup-horizontal-dark.svg">'
            f'<img src="{up}assets/lockup-horizontal.svg" alt="Brick Work" width="450" height="104" '
            'loading="lazy" decoding="async"></picture>')


def api_reference():
    """Render the complete contract locally, without a remote renderer or runtime requests."""
    import yaml
    contract = yaml.safe_load((ROOT / 'docs/brickwork/openapi-v1.yaml').read_text())
    chunks = ['<h1>API reference</h1><p>The REST API at <code>/api/v1</code>. '
              '<a href="openapi-v1.yaml">Download the OpenAPI contract</a>. '
              f'<a href="{blob("docs/brickwork/api-v1.md")}">Authentication and examples</a>.</p>']
    for path, operations in contract['paths'].items():
        for method, operation in operations.items():
            if method not in ('get', 'post', 'put', 'patch', 'delete', 'head', 'options'):
                continue
            chunks.append('<section class="api-operation"><h2>' + html.escape(method.upper() + ' ' + path) + '</h2>')
            chunks.append('<p>' + html.escape(operation.get('summary', '')) + '</p>')
            chunks.append('<details><summary>Request and responses</summary><pre><code>' +
                          html.escape(yaml.safe_dump(operation, sort_keys=False)) + '</code></pre></details></section>')
    chunks.append('<h2>Shared schemas and authentication</h2><pre><code>' +
                  html.escape(yaml.safe_dump(contract.get('components', {}), sort_keys=False)) + '</code></pre>')
    return ''.join(chunks)


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
    for sub in ('api', 'docs', 'use-cases', 'workflows'):
        (out / sub).mkdir()
    (out / 'mcp').mkdir()
    static = ROOT / 'static'
    shutil.copy(static / 'web/toni/tokens-v2.css', out / 'assets/tokens-v2.css')
    for font in (static / 'web/toni/fonts').glob('*'):
        shutil.copy(font, out / 'assets/fonts' / font.name)
    for name in ('app-icon.svg', 'favicon.svg', 'lockup-horizontal.svg', 'lockup-horizontal-dark.svg'):
        shutil.copy(static / 'brickwork' / name, out / 'assets' / name)
    brand_css = (static / 'brickwork/brick-work.css').read_text().replace(
        '/static/fonts/PatrickHand-Regular.woff2', 'fonts/PatrickHand-Regular.woff2')
    (out / 'assets/brick-work.css').write_text(brand_css)
    shutil.copy(static / 'fonts/PatrickHand-Regular.woff2', out / 'assets/fonts/PatrickHand-Regular.woff2')
    shutil.copy(ROOT / 'scripts/site/site.css', out / 'assets/site.css')
    shutil.copy(SITE / 'site.js', out / 'assets/site.js')
    shutil.copytree(SITE / 'img', out / 'assets/img')

    readme = re.sub(r'<!-- site:skip -->.*?<!-- /site:skip -->\n*', '', (ROOT / 'README.md').read_text(), flags=re.S)
    readme = rewrite_links(readme, '.', 1)
    (out / 'docs/index.html').write_text(page('Documentation', render(readme), 1, current='Docs'))

    landing = (SITE / 'landing.html').read_text().replace('{repository}', repository())
    (out / 'index.html').write_text(page('Brick Work', landing, 0, current='Home', main='marketing landing'))
    for name, title, current in (('use-cases', 'Use cases', 'Use cases'), ('workflows', 'Workflows', 'Workflows')):
        text = (SITE / f'{name}.md').read_text()
        (out / name / 'index.html').write_text(page(title, render(text), 1, current=current, main='marketing'))

    guide = rewrite_links((ROOT / 'docs/brickwork/mcp.md').read_text(), 'docs/brickwork', 1) + mcp_tables()
    (out / 'mcp/index.html').write_text(page('MCP server', render(guide), 1, current='MCP'))

    shutil.copy(ROOT / 'docs/brickwork/openapi-v1.yaml', out / 'api/openapi-v1.yaml')
    body = api_reference()
    (out / 'api/index.html').write_text(page('API reference', body, 1, current='API reference').replace(
        '<main class="doc">', '<main class="doc api">'))
    from scripts.build_demo import build_demo
    demo_base = f'/{repository().split("/")[1]}/demo/'
    build_demo(out / 'demo', demo_base)
    # The app's absolute font paths need the same Pages prefix as its HTML assets.
    for css in (out / 'demo').rglob('*.css'):
        css.write_text(css.read_text().replace('/static/', demo_base + 'static/'))
    # Static hosts decode URL paths before looking up files (including non-ASCII storage names).
    for directory in sorted((out / 'demo').rglob('*'), key=lambda p: len(p.parts), reverse=True):
        if directory.is_dir() and unquote(directory.name) != directory.name:
            directory.rename(directory.with_name(unquote(directory.name)))
    (out / '.nojekyll').write_text('')
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('out')
    built = build(parser.parse_args(argv).out)
    print(f'Built the documentation site in {built}')


if __name__ == '__main__':
    main()
