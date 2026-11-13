"""Build the documentation site for GitHub Pages from the repository.

    python scripts/build_site.py OUT_DIR

Pages: `/` the landing page, `/use-cases/`, `/workflows/`, `/impressum/`, `/privacy/` and `404.html` (Markdown in scripts/site), `/docs/` the user and developer docs, `/demo/` the static demo (scripts/build_demo.py), `/api/` and `/mcp/` stub pages that point
at the generated API v2 and MCP reference pages in the docs' Developers tab (scripts/docs_reference.py), `/api/openapi-v2.yaml` the
contract to download, `/changelog/` CHANGELOG.md and `/llms.txt` the facts for AI assistants (scripts/site/llms.md). The ADRs and the 4.0 data-model
design are read on GitHub; the design pages readers need are in the docs' Developers tab (ADR 0030). The user docs are built by
Zensical from docs/ and mkdocs.yml (App Standard, Maintenance § Rules, User docs); the other pages are
Markdown rendered with Python-Markdown, styled with the app's own design tokens and fonts. Links to files
in the repository point at them on GitHub. The output is static and needs no server.
"""
import argparse
import html
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote

import markdown

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SITE = ROOT / 'scripts/site'
# The top bar: (label, path from the site root, key). Install is the home page's install section until /install/ exists (slice S2); About joins in S4.
NAV = (('Install', '#install'), ('Demo', 'demo/'), ('Use cases', 'use-cases/'), ('Workflows', 'workflows/'), ('Docs', 'docs/'),
       ('Changelog', 'changelog/'))
# The pages that moved into the docs (doc-standard-v1 B1b): the old URL keeps a stub page that points at the new one.
MOVED = (('api', 'API reference', 'docs/developer/api-v2-reference/'), ('mcp', 'MCP server', 'docs/brickwork/mcp/'))
USER_DOCS = ('how-to', 'concepts', 'reference', 'tutorials', 'developer')   # the Zensical sections under /docs/


def site_page(resolved):
    """The site path (from the root, with a trailing slash) of a repository file this site renders, or None."""
    if resolved == 'CHANGELOG.md':
        return 'changelog/'
    section, _, name = resolved.removeprefix('docs/').partition('/')
    if resolved.startswith('docs/') and section in USER_DOCS and name.endswith('.md') and '/' not in name:
        return f'docs/{section}/' + ('' if name == 'index.md' else name.removesuffix('.md') + '/')
    return None


def repository():
    """The GitHub repository the links point at: GITHUB_REPOSITORY in Actions, else the project's own."""
    return os.environ.get('GITHUB_REPOSITORY') or 'Ulef1005/brick-work'


def site_base():
    """The deployment prefix, shared by the site, docs and demo."""
    base = os.environ.get('SITE_BASE') or f'/{repository().split("/")[1]}/'
    if not re.fullmatch(r'/(?:(?!\.+/)[A-Za-z0-9_.-]+/)*', base):
        raise ValueError('SITE_BASE must be a path with a leading and trailing slash (for example / or /brick-work/)')
    return base


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
        local = {'docs/brickwork/mcp.md': up + 'docs/brickwork/mcp/', 'docs/brickwork/api-v2.md': up + 'docs/brickwork/api-v2/',
                 'docs/brickwork/openapi-v2.yaml': up + 'docs/developer/api-v2-reference/'}
        if resolved in local:
            url = local[resolved]
        elif site_page(resolved):
            url = up + site_page(resolved)
        else:
            url = blob(resolved)
        return f'[{label}]({url}{"#" + anchor if anchor else ""})'
    return re.sub(r'(?<!!)\[([^\]]+)\]\(([^)\s]+)\)', link, text)


def render(text):
    return markdown.markdown(text, extensions=['fenced_code', 'tables', 'toc', 'sane_lists'],
                             extension_configs={'toc': {'permalink': False}})


def page(title, body, depth, *, current, head='', main='doc', absolute=False):
    up = site_base() if absolute else '../' * depth
    repo = repository()
    nav = ''.join(f'<a href="{up}{href}"{" aria-current=\"page\"" if name == current else ""}>{name}</a>' for name, href in NAV)
    menu = nav + f'<a href="https://github.com/{repo}">GitHub</a>'
    col = lambda heading, links: (f'<div><b>{heading}</b><ul>' + ''.join(f'<li><a href="{href}">{label}</a></li>' for label, href in links)
                                  + '</ul></div>')
    footer_cols = ''.join((
        col('Product', (('Install', f'{up}#install'), ('Demo', f'{up}demo/'), ('Use cases', f'{up}use-cases/'), ('Workflows', f'{up}workflows/'))),
        col('Learn', (('Docs', f'{up}docs/'), ('Changelog', f'{up}changelog/'), ('API', f'{up}docs/developer/api-v2-reference/'),
                      ('MCP', f'{up}docs/brickwork/mcp/'))),
        col('Project', (('GitHub', f'https://github.com/{repo}'), ('Show and tell', f'https://github.com/{repo}/discussions'),
                        ('Roadmap', 'https://github.com/users/Ulef1005/projects/3'))),
        col('Legal', (('Impressum', f'{up}impressum/'), ('Privacy', f'{up}privacy/'), ('MIT licence', blob('LICENSE')))),
    ))
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title) + " · Brick Work" if title != "Brick Work" else "Brick Work"}</title>
<meta name="description" content="Brick Work: the workbench for your brick collection: self-hosted, with a REST API and an MCP server.">
<link rel="icon" href="{up}assets/favicon.svg" type="image/svg+xml">
<link rel="icon" href="{up}assets/favicon-32.png" sizes="32x32" type="image/png">
<link rel="icon" href="{up}assets/favicon-16.png" sizes="16x16" type="image/png">
<link rel="icon" href="{up}assets/favicon.ico" sizes="48x48">
<link rel="apple-touch-icon" href="{up}assets/apple-touch-icon.png">
<link rel="stylesheet" href="{up}assets/tokens-v2.css">
<link rel="stylesheet" href="{up}assets/brick-work.css">
<link rel="stylesheet" href="{up}assets/site.css">
<link rel="stylesheet" href="{up}assets/marketing.css">
{head}
</head>
<body>
<div class="site"><header class="top"><a class="brand" href="{up}" aria-label="Brick Work home">{lockup(up)}</a>
<nav aria-label="Main">{nav}</nav><a class="gh link" href="https://github.com/{repo}">GitHub</a><button class="js-only" type="button" data-theme-toggle aria-label="Switch theme">Theme</button><details class="menu"><summary>Menu</summary><nav class="menu-list" aria-label="Menu">{menu}</nav></details></header></div>
<main class="{main}">{body}</main>
<div class="site"><footer class="sec foot"><div class="inner"><div class="cols">{footer_cols}</div>
<p class="small muted fine">Brick Work is an independent project and is not affiliated with the LEGO Group, Rebrickable, Brickset or BrickLink. LEGO® is a trademark of the LEGO Group of companies, which does not sponsor, authorize or endorse this project. Brick Work is MIT-licensed and inspired by BrickTracker.</p></div></footer></div>
<script src="{up}assets/site.js" defer></script>
</body>
</html>
'''


def lockup(up):
    width, height = struct.unpack(
        '>II', (ROOT / 'static/brickwork/lockup-horizontal-light.png').read_bytes()[16:24])
    return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="{up}assets/lockup-horizontal-dark.png">'
            f'<img src="{up}assets/lockup-horizontal-light.png" alt="Brick Work" width="{width}" height="{height}" '
            'loading="lazy" decoding="async"></picture>')


def picture(name, alt, up, *, phone=None):
    """A light/dark screenshot of scripts/site/img as one <picture>, with its real pixel size (phone captures are drawn at twice the pixels)."""
    light, dark = f'assets/img/{name}-light.png', f'assets/img/{name}-dark.png'
    width, height = struct.unpack('>II', (SITE / 'img' / f'{name}-light.png').read_bytes()[16:24])
    scale = 2 if (phone if phone is not None else 'phone' in name) else 1
    return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="{up}{dark}" width="{width // scale}" height="{height // scale}">'
            f'<img alt="{html.escape(alt)}" src="{up}{light}" width="{width // scale}" height="{height // scale}" loading="lazy" decoding="async"></picture>')


def latest_release():
    """(version, schema, date, summary) of the newest release heading in CHANGELOG.md; the summary is the paragraph under it."""
    text = (ROOT / 'CHANGELOG.md').read_text()
    match = re.search(r'^## Brick Work (\S+) \(schema ([^)]+)\) · (\d{4}-\d{2}-\d{2})\n\n(.+?)\n', text, flags=re.M)
    version, schema, date, summary = match.groups()
    summary = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', summary).replace('`', '')
    first = re.match(r'(.+?\.)\s(?=[A-Z])', summary + ' X')
    return version, schema, date, first.group(1) if first else summary


def docs_count(section):
    return len([p for p in (ROOT / 'docs' / section).glob('*.md') if p.name != 'index.md'])


def home(up):
    """The home page body from scripts/site/landing.html: version, release notes and docs counts from the repository, pictures with their sizes."""
    from brickwork.version import __version__
    version, schema, date, summary = latest_release()
    text = (SITE / 'landing.html').read_text()
    values = {'repository': repository(), 'up': up, 'version': __version__, 'release_version': version, 'release_date': date,
              'release_summary': html.escape(summary), 'release_schema': schema}
    for section in ('tutorials', 'how-to', 'concepts', 'reference'):
        values['count_' + section.replace('-', '_')] = str(docs_count(section))
    # One pass over the template, so a value (a release summary) is never scanned for tokens itself.
    def token(match):
        key = match[1]
        if key.startswith('pic:'):
            name, _, alt = key[4:].partition('|')
            return picture(name, alt, up)
        return values.get(key, match[0])
    return re.sub(r'\{([A-Za-z_]+|pic:[^|}]+\|[^}]+)\}', token, text)


def stub(title, target):
    """The page left at a moved page's old URL: a link to the new one, followed at once by the browser."""
    return page(title, f'<h1>{html.escape(title)}</h1><p>This page has moved to <a href="../{target}">{html.escape(title)} in the docs</a>.</p>',
                1, current=None, head=f'<meta http-equiv="refresh" content="0; url=../{target}">')


def build_docs(out):
    """Zensical takes its output directory only from the config and keeps it inside the project root, and it keeps its cache (`.cache`, cleared
    by `--clean`) beside the config file. So the config goes into a temporary folder of its own in the repo, with a copy of the docs folder, and the site and the cache are built there and the result copied out: builds that run at the same
    time (the tests run in parallel, #254) then never share a cache."""
    import yaml
    zensical = Path(sys.executable).with_name('zensical')
    with tempfile.TemporaryDirectory(prefix='.build-site-', dir=ROOT) as tmp:
        config = yaml.safe_load((ROOT / 'mkdocs.yml').read_text())
        docs = config.get('docs_dir', 'docs')
        shutil.copytree(ROOT / docs, Path(tmp) / docs)   # the docs folder must lie inside the project root (6 MB)
        # The documentation pages make no external requests. In the copy a diagram becomes a link to GitHub, which
        # draws it, as on the other pages (mermaid_to_link); the source file keeps its diagram.
        for page in (Path(tmp) / docs).rglob('*.md'):
            text = page.read_text()
            if '```mermaid' in text:
                resolved = (Path(docs) / page.relative_to(Path(tmp) / docs)).as_posix()
                page.write_text(mermaid_to_link(text, resolved))
        owner = repository().split('/')[0].lower()
        origin = 'https://brick-work.app' if site_base() == '/' else f'https://{owner}.github.io'
        config['site_url'] = origin + site_base() + 'docs/'
        config['site_dir'] = str(Path(tmp) / 'site')
        path = Path(tmp) / 'mkdocs.yml'
        path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
        # The markdown-exec blocks of the reference pages import scripts.docs_reference, so the build runs from the root with it on the path.
        pythonpath = os.pathsep.join(p for p in (str(ROOT), os.environ.get('PYTHONPATH')) if p)
        subprocess.run((str(zensical) if zensical.exists() else 'zensical', 'build', '--strict', '--clean',
                        '--config-file', str(path)), check=True, cwd=ROOT, env={**os.environ, 'PYTHONPATH': pythonpath})
        shutil.copytree(Path(tmp) / 'site', out)


def mermaid_to_link(text, resolved):
    """The documentation pages make no external requests. A diagram links to the file on GitHub,
    which draws it, and keeps its source folded underneath."""
    def figure(match):
        heading = re.findall(r'^#+ (.+)$', text[:match.start()], flags=re.M)
        anchor = '#' + re.sub(r'[^\w\- ]', '', heading[-1].lower()).replace(' ', '-') if heading else ''   # GitHub's heading slug
        return (f'\n<p class="diagram"><a href="{blob(resolved)}{anchor}">This diagram is drawn on GitHub</a>.</p>\n'
                f'<details><summary>Diagram source</summary><pre><code>{html.escape(match.group(1))}</code></pre></details>\n')
    return re.sub(r'^```mermaid\n(.*?)^```$', figure, text, flags=re.M | re.S)


def build_changelog(out):
    """/changelog/: CHANGELOG.md, its links to docs pages kept on the site and every other link pointing at GitHub."""
    target = site_page('CHANGELOG.md')
    (out / target).mkdir(parents=True, exist_ok=True)
    text = mermaid_to_link(rewrite_links((ROOT / 'CHANGELOG.md').read_text(), '', 1), 'CHANGELOG.md')
    (out / target / 'index.html').write_text(page('Changelog', render(text), 1, current='Changelog'))


def llms_txt():
    """/llms.txt (llmstxt.org) from scripts/site/llms.md: the facts an AI assistant is most often asked, with the release's version
    filled in and every repository link turned into the raw Markdown file on GitHub, which an assistant reads best."""
    from brickwork.version import __version__
    text = (SITE / 'llms.md').read_text().replace('{version}', __version__).replace('{repository}', repository())
    raw = f'https://raw.githubusercontent.com/{repository()}/main/'
    return re.sub(r'\]\((?!https?://|#)([^)\s]+)\)', lambda m: f']({raw}{m[1]})', text)


def rewrite_demo_html(text, demo_base):
    """Prefix root paths in copied HTML attributes and CSS URLs with the demo base."""
    paths = {'static': 'static/', 'brand': 'static/brickwork/', 'fonts': 'static/fonts/'}
    text = re.sub(r'''(?<=["'(=])/(static|brand|fonts)/''',
                  lambda m: demo_base + paths[m[1]], text)
    return text.replace('href="/"', f'href="{demo_base}"')


def build(out):
    base = site_base()
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    (out / 'assets' / 'fonts').mkdir(parents=True)
    for sub in ('api', 'use-cases', 'workflows', 'impressum', 'privacy'):
        (out / sub).mkdir()
    (out / 'mcp').mkdir()
    static = ROOT / 'static'
    shutil.copy(static / 'web/toni/tokens-v2.css', out / 'assets/tokens-v2.css')
    for font in (static / 'web/toni/fonts').glob('*'):
        shutil.copy(font, out / 'assets/fonts' / font.name)
    for name in ('app-icon.svg', 'favicon.svg', 'favicon.ico', 'favicon-16.png', 'favicon-32.png',
                 'lockup-horizontal-light.png', 'lockup-horizontal-dark.png'):
        shutil.copy(static / 'brickwork' / name, out / 'assets' / name)
    shutil.copy(static / 'brickwork/icons/icon-180.png', out / 'assets/apple-touch-icon.png')
    brand_css = (static / 'brickwork/brick-work.css').read_text().replace(
        '/static/fonts/PatrickHand-Regular.woff2', 'fonts/PatrickHand-Regular.woff2')
    (out / 'assets/brick-work.css').write_text(brand_css)
    shutil.copy(static / 'fonts/PatrickHand-Regular.woff2', out / 'assets/fonts/PatrickHand-Regular.woff2')
    shutil.copy(ROOT / 'scripts/site/site.css', out / 'assets/site.css')
    shutil.copy(SITE / 'marketing.css', out / 'assets/marketing.css')
    shutil.copy(SITE / 'site.js', out / 'assets/site.js')
    shutil.copytree(SITE / 'img', out / 'assets/img')

    build_docs(out / 'docs')

    (out / 'index.html').write_text(page('Brick Work', home(''), 0, current=None, main='home'))
    for name, title, current in (('use-cases', 'Use cases', 'Use cases'), ('workflows', 'Workflows', 'Workflows'),
                                 ('impressum', 'Impressum', None), ('privacy', 'Privacy', None)):
        text = (SITE / f'{name}.md').read_text().replace('{repository}', repository())
        (out / name / 'index.html').write_text(page(title, render(text), 1, current=current, main='marketing'))

    missing = (SITE / '404.md').read_text().replace('{base}', base)
    (out / '404.html').write_text(page('Page not found', render(missing), 0, current=None, absolute=True))

    for folder, title, target in MOVED:
        (out / folder / 'index.html').write_text(stub(title, target))
    shutil.copy(ROOT / 'docs/brickwork/openapi-v2.yaml', out / 'api/openapi-v2.yaml')
    build_changelog(out)

    from scripts.build_demo import build_demo
    demo_base = base + 'demo/'
    build_demo(out / 'demo', demo_base)
    # The app's absolute font paths need the same deployment prefix as its HTML assets.
    for css in (out / 'demo').rglob('*.css'):
        css.write_text(css.read_text().replace('/static/', demo_base + 'static/'))
    # The copied offline page and brand head snippet are HTML assets too; keep their links local.
    for template in (out / 'demo/static').rglob('*.html'):
        template.write_text(rewrite_demo_html(template.read_text(), demo_base))
    # Static hosts decode URL paths before looking up files (including non-ASCII storage names).
    for directory in sorted((out / 'demo').rglob('*'), key=lambda p: len(p.parts), reverse=True):
        if directory.is_dir() and unquote(directory.name) != directory.name:
            directory.rename(directory.with_name(unquote(directory.name)))
    (out / 'llms.txt').write_text(llms_txt())
    (out / '.nojekyll').write_text('')
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('out')
    built = build(parser.parse_args(argv).out)
    print(f'Built the documentation site in {built}')


if __name__ == '__main__':
    main()
