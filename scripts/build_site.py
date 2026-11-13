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
# The top bar: (label, path from the site root).
NAV = (('Install', 'install/'), ('Demo', 'demo/'), ('Use cases', 'use-cases/'), ('Workflows', 'workflows/'), ('Docs', 'docs/'),
       ('Changelog', 'changelog/'), ('About', 'about/'))
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


# Cloudflare Web Analytics (cookieless, public site token): on the pages built here only, never on the docs or the demo (see the privacy page).
ANALYTICS = ('<script defer src="https://static.cloudflareinsights.com/beacon.min.js" '
             'data-cf-beacon=\'{"token": "f09e0d34781b4d658aa5ddd6adce3f44"}\'></script>')   # gitleaks:allow (the site token is public by design: it sits in every page's HTML)
HOME_DESCRIPTION = ('Brick Work is a free, open-source, self-hosted workbench for your brick collection: check a set\'s parts, pull missing ones from loose stock '
                    'and see which unfinished sets your stock can complete.')
MD_DESCRIPTIONS = {'use-cases': 'Eight moments a collector knows, and how Brick Work helps with each: rebuilding used sets, sorted bulk, minifigures, bought collections and orders.',
                   'impressum': 'Impressum of the Brick Work website.', 'privacy': 'What the Brick Work website loads and what it does not: no tracking cookies, no consent banner.'}
DEFAULT_DESCRIPTION = 'Brick Work: the workbench for your brick collection: self-hosted, with a REST API and an MCP server.'


def seo_head(title, description, path):
    """Canonical, Open Graph and Twitter tags for a page at `path` (a folder from the site root, '' for the home page). The apex or the Pages address
    comes from the build's SITE_BASE; a social preview picture is added when scripts/site/social-preview.png exists."""
    url = origin() + site_base() + path
    image = f'{origin()}{site_base()}assets/social-preview.png' if (SITE / 'social-preview.png').exists() else None
    tags = [('og:type', 'website'), ('og:site_name', 'Brick Work'), ('og:title', title), ('og:description', description), ('og:url', url)]
    if image:
        tags.append(('og:image', image))
    tags += [('twitter:card', 'summary_large_image' if image else 'summary'), ('twitter:title', title), ('twitter:description', description)]
    meta = ''.join(f'<meta {"property" if key.startswith("og:") else "name"}="{key}" content="{html.escape(value, quote=True)}">' for key, value in tags)
    return f'<link rel="canonical" href="{url}">' + meta


def page(title, body, depth, *, current, head='', main='doc', absolute=False, path=None, description=None):
    up = site_base() if absolute else '../' * depth
    repo = repository()
    description = description or DEFAULT_DESCRIPTION
    full_title = html.escape(title) + ' · Brick Work' if title != 'Brick Work' else 'Brick Work'
    if path is not None:
        head = seo_head(title + ' · Brick Work' if title != 'Brick Work' else 'Brick Work', description, path) + head
    nav = ''.join(f'<a href="{up}{href}"{" aria-current=\"page\"" if name == current else ""}>{name}</a>' for name, href in NAV)
    menu = nav + f'<a href="https://github.com/{repo}">GitHub</a>'
    col = lambda heading, links: (f'<div><b>{heading}</b><ul>' + ''.join(f'<li><a href="{href}">{label}</a></li>' for label, href in links)
                                  + '</ul></div>')
    footer_cols = ''.join((
        col('Product', (('Install', f'{up}install/'), ('Demo', f'{up}demo/'), ('Use cases', f'{up}use-cases/'), ('Workflows', f'{up}workflows/'))),
        col('Learn', (('Docs', f'{up}docs/'), ('Changelog', f'{up}changelog/'), ('API', f'{up}docs/developer/api-v2-reference/'),
                      ('MCP', f'{up}docs/brickwork/mcp/'))),
        col('Project', (('About', f'{up}about/'), ('GitHub', f'https://github.com/{repo}'), ('Show and tell', f'https://github.com/{repo}/discussions'),
                        ('Roadmap', 'https://github.com/users/Ulef1005/projects/3'))),
        col('Legal', (('Impressum', f'{up}impressum/'), ('Privacy', f'{up}privacy/'), ('MIT licence', blob('LICENSE')))),
    ))
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{full_title}</title>
<meta name="description" content="{html.escape(description, quote=True)}">
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
<p class="small muted fine">Brick Work is an independent project and is not affiliated with the LEGO Group, Rebrickable, Brickset or BrickLink. LEGO® is a trademark of the LEGO Group of companies, which does not sponsor, authorize or endorse this project. Brick Work is MIT-licensed and inspired by BrickTracker. Part and set images: Rebrickable.</p></div></footer></div>
<script src="{up}assets/site.js" defer></script>
{ANALYTICS}
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


def fill(text, up):
    """Fill the tokens of a scripts/site HTML template: {up}, {repository}, {version}, the latest release and the docs counts, and {pic:name|alt}."""
    from brickwork.version import __version__
    version, schema, date, summary = latest_release()
    values = {'repository': repository(), 'up': up, 'version': __version__, 'release_version': version, 'release_date': date,
              'release_summary': html.escape(summary), 'release_schema': schema}
    values['count_adr'] = str(len(list((ROOT / 'docs/adr').glob('[0-9]*.md'))))
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


def home(up):
    """The home page body from scripts/site/landing.html."""
    return fill((SITE / 'landing.html').read_text(), up)


def build_pages(out):
    """Every scripts/site/pages/*.html is one page: a header of `key: value` lines (title, path, current), a line `---`, then the body.
    `path` is the folder from the site root (`install/`, `coming-from/rebrickable/`); `current` names the top-bar item to mark."""
    for source in sorted((SITE / 'pages').glob('*.html')):
        header, _, body = source.read_text().partition('\n---\n')
        meta = dict(line.split(': ', 1) for line in header.strip().splitlines())
        depth = len(Path(meta['path']).parts)
        folder = out / meta['path']
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'index.html').write_text(page(meta['title'], fill(body, '../' * depth), depth, current=meta.get('current') or None, main='home',
                                                path=meta['path'], description=meta.get('description')))


def json_ld():
    """SoftwareApplication structured data for the home page."""
    import json
    from brickwork.version import __version__
    data = {'@context': 'https://schema.org', '@type': 'SoftwareApplication', 'name': 'Brick Work', 'url': origin() + site_base(),
            'applicationCategory': 'UtilitiesApplication', 'operatingSystem': 'Docker on Linux, macOS or Windows', 'softwareVersion': __version__,
            'description': HOME_DESCRIPTION, 'license': 'https://opensource.org/licenses/MIT',
            'downloadUrl': f'https://github.com/{repository()}', 'offers': {'@type': 'Offer', 'price': '0', 'priceCurrency': 'EUR'},
            'author': {'@type': 'Person', 'name': 'Ulf Weihbold'}}
    return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False).replace('</', '<\\/') + '</script>'


def site_urls(out):
    """The marketing pages that go into sitemap-pages.xml: every folder with an index.html outside docs/ and demo/, plus the demo's entry."""
    folders = sorted(p.parent.relative_to(out).as_posix() for p in out.glob('*/index.html')) + sorted(
        p.parent.relative_to(out).as_posix() for p in out.glob('*/*/index.html') if p.parts[-3] in ('coming-from',))
    return [''] + [f + '/' for f in folders if f.split('/')[0] not in ('docs', 'demo', 'api', 'mcp')] + ['demo/']


def build_seo_files(out):
    """robots.txt and the sitemaps: /sitemap.xml is an index of sitemap-pages.xml (the pages of this site) and docs/sitemap.xml (Zensical's)."""
    base = origin() + site_base()
    (out / 'robots.txt').write_text(f'User-agent: *\nAllow: /\n\nSitemap: {base}sitemap.xml\n')
    urls = ''.join(f'<url><loc>{base}{path}</loc></url>' for path in site_urls(out))
    (out / 'sitemap-pages.xml').write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + urls + '</urlset>\n')
    (out / 'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                                     f'<sitemap><loc>{base}sitemap-pages.xml</loc></sitemap><sitemap><loc>{base}docs/sitemap.xml</loc></sitemap></sitemapindex>\n')


def own_address(text):
    """The site's own address instead of the Pages address (an apex build serves from brick-work.app)."""
    owner = repository().split('/')[0].lower()
    return text.replace(f'https://{owner}.github.io/{repository().split("/")[1]}/', origin() + site_base())


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


RELEASE = re.compile(r'^## Brick Work (\S+) \(([^)]*)\) · (\d{4}-\d{2}-\d{2})$', re.M)


def releases():
    """Every release of CHANGELOG.md, newest first: (version, schema note, date, Markdown body). The older task entries and Unreleased are not releases."""
    text = (ROOT / 'CHANGELOG.md').read_text()
    out = []
    for mark in RELEASE.finditer(text):
        end = text.find('\n## ', mark.end())
        out.append((mark[1], mark[2], mark[3], text[mark.end():end if end != -1 else len(text)].strip()))
    return out


def origin():
    owner = repository().split('/')[0].lower()
    return 'https://brick-work.app' if site_base() == '/' else f'https://{owner}.github.io'


def build_changelog(out):
    """/changelog/: every release since the first public one, newest open, an anchor per version, and an Atom feed (feed.xml)."""
    target = site_page('CHANGELOG.md')
    (out / target).mkdir(parents=True, exist_ok=True)
    rows = []
    for index, (version, schema, date, body) in enumerate(releases()):
        markdown_body = own_address(mermaid_to_link(rewrite_links(body, '', 1), 'CHANGELOG.md'))
        pill = '<span class="pill">Latest</span>' if index == 0 else '<span></span>'
        rows.append(f'<details class="rel" id="v{version}"{" open" if index == 0 else ""}><summary><span class="v">{version}</span>'
                    f'<span class="dt">{date} · <span class="sch">{html.escape(schema)}</span></span>{pill}</summary>'
                    f'<div class="body">{render(markdown_body)}<a class="link" href="https://github.com/{repository()}/releases/tag/v{version}">Release {version} on GitHub</a></div></details>')
    oldest = releases()[-1]
    body = (f'<div class="site"><div class="sec"><div class="inner"><div class="pagehead"><span class="label">Home / Changelog</span>'
            f'<h1 class="display page">Changelog</h1><p class="lede">Every release since the first public one on {oldest[2]}, newest first.</p>'
            f'<div class="btns"><a class="link" href="feed.xml">Atom feed</a><a class="link" href="https://github.com/{repository()}/releases">Releases on GitHub</a></div></div>'
            f'<div style="display:flex;flex-direction:column;gap:12px">{"".join(rows)}</div></div></div></div>')
    head = '<link rel="alternate" type="application/atom+xml" title="Brick Work releases" href="feed.xml">'
    (out / target / 'index.html').write_text(page('Changelog', body, 1, current='Changelog', head=head, main='home', path='changelog/',
                                                         description='Every Brick Work release since the first public one, newest first, with an Atom feed.'))
    (out / target / 'feed.xml').write_text(atom_feed())


def atom_feed():
    """The Atom feed of the releases (the newest twenty): one entry each, linking its anchor on the changelog page."""
    base = origin() + site_base()
    entries = []
    for version, schema, date, body in releases()[:20]:
        first = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', body.split('\n\n', 1)[0]).replace('`', '')
        entries.append(f'<entry><title>Brick Work {version}</title><id>tag:{origin().removeprefix("https://")},{date}:{version}</id>'
                       f'<link href="{base}changelog/#v{version}"/><updated>{date}T00:00:00Z</updated><summary>{html.escape(first)}</summary></entry>')
    latest = releases()[0][2]
    return ('<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom"><title>Brick Work releases</title>'
            f'<id>{base}changelog/</id><link rel="self" href="{base}changelog/feed.xml"/><link href="{base}changelog/"/>'
            f'<updated>{latest}T00:00:00Z</updated><author><name>Ulf Weihbold</name></author>{"".join(entries)}</feed>\n')


def llms_txt():
    """/llms.txt (llmstxt.org) from scripts/site/llms.md: the facts an AI assistant is most often asked, with the release's version
    filled in and every repository link turned into the raw Markdown file on GitHub, which an assistant reads best."""
    from brickwork.version import __version__
    text = (SITE / 'llms.md').read_text().replace('{version}', __version__).replace('{repository}', repository()).replace('{site}', origin() + site_base())
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
    for sub in ('api', 'use-cases', 'impressum', 'privacy'):
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
    if (SITE / 'social-preview.png').exists():
        shutil.copy(SITE / 'social-preview.png', out / 'assets/social-preview.png')
    shutil.copy(SITE / 'site.js', out / 'assets/site.js')
    if any((SITE / 'img').glob('*.png')):   # no capture is shown while the demo's pictures are placeholders (the captures return with the Rebrickable pictures, #332)
        shutil.copytree(SITE / 'img', out / 'assets/img')

    build_docs(out / 'docs')

    (out / 'index.html').write_text(page('Brick Work', home(''), 0, current=None, main='home', path='', head=json_ld(), description=HOME_DESCRIPTION))
    for name, title, current in (('use-cases', 'Use cases', 'Use cases'),
                                 ('impressum', 'Impressum', None), ('privacy', 'Privacy', None)):
        text = (SITE / f'{name}.md').read_text().replace('{repository}', repository())
        (out / name / 'index.html').write_text(page(title, render(text), 1, current=current, main='marketing', path=f'{name}/', description=MD_DESCRIPTIONS[name]))

    missing = (SITE / '404.md').read_text().replace('{base}', base)
    (out / '404.html').write_text(page('Page not found', render(missing), 0, current=None, absolute=True))

    build_pages(out)

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
    shim = out / 'demo/demo-shim.js'
    shim.write_text(own_address(shim.read_text()))
    (out / 'llms.txt').write_text(llms_txt())
    build_seo_files(out)
    (out / '.nojekyll').write_text('')
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('out')
    built = build(parser.parse_args(argv).out)
    print(f'Built the documentation site in {built}')


if __name__ == '__main__':
    main()
