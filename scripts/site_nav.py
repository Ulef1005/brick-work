"""The site's slim top bar for the pages the site does not build itself: the Zensical docs under /docs/ and the exported demo under /demo/ (#363).

The marketing pages carry their own header (scripts/build_site.py `page`); /docs/ and /demo/ were bare pages with no way back. `bar(base)` is that header
in a smaller, sticky form and `inject(html, base)` puts it into a finished HTML page: the style before `</head>`, the bar right after `<body>`. The links
are absolute from the deployment prefix (`base`, `/` or `/brick-work/`), so one bar fits every depth. The page carries no script, no analytics tag and no
external request; the phone menu is a `<details>`. The bar's height is the CSS variable `--bw-topbar-h`, which the docs and demo layouts offset by."""
import html
import re

MARKER = 'data-bw-topbar'
HEIGHT = 48   # px, the bar's height on every width (the variable `--bw-topbar-h`)
LINKS = (('Home', ''), ('Install', 'install/'), ('Demo', 'demo/'), ('Use cases', 'use-cases/'), ('Workflows', 'workflows/'),
         ('Docs', 'docs/'), ('Changelog', 'changelog/'), ('About', 'about/'))

STYLE = f'''<style data-bw-topbar-style>
:root{{--bw-topbar-h:{HEIGHT}px}}
.bw-topbar{{position:sticky;top:0;z-index:2000;box-sizing:border-box;height:var(--bw-topbar-h);display:flex;align-items:center;gap:8px;padding:0 16px;
background:#fbf8f2;color:#2a2622;border-bottom:1px solid #d9d2c5;font:14px/1.2 system-ui,-apple-system,"Segoe UI",sans-serif}}
.bw-topbar a{{color:inherit;text-decoration:none}}
.bw-topbar .bw-brand{{display:flex;align-items:center;margin-right:8px}}
.bw-topbar .bw-brand img{{height:26px;width:auto;display:block}}
.bw-topbar nav{{display:flex;gap:2px;flex:1;min-width:0}}
.bw-topbar nav a,.bw-topbar .bw-gh{{min-height:36px;display:inline-flex;align-items:center;padding:0 10px;border-radius:6px}}
.bw-topbar nav a:hover,.bw-topbar .bw-gh:hover{{background:rgba(127,127,127,.15)}}
.bw-topbar nav a[aria-current="page"]{{font-weight:600;box-shadow:inset 0 -2px 0 #c8553d}}
.bw-topbar .bw-menu{{display:none;position:relative;margin-left:auto}}
.bw-topbar .bw-menu summary{{list-style:none;min-height:36px;display:inline-flex;align-items:center;padding:0 14px;border:1px solid #d9d2c5;border-radius:6px;cursor:pointer}}
.bw-topbar .bw-menu summary::-webkit-details-marker{{display:none}}
.bw-topbar .bw-menu-list{{position:absolute;right:0;top:44px;min-width:200px;display:flex;flex-direction:column;background:#fbf8f2;border:1px solid #d9d2c5;border-radius:8px;overflow:hidden}}
.bw-topbar .bw-menu-list a{{min-height:44px;display:flex;align-items:center;padding:0 16px;border-bottom:1px solid #d9d2c5}}
.bw-topbar .bw-menu-list a:last-child{{border-bottom:0}}
.bw-topbar .bw-light{{display:block}}.bw-topbar .bw-dark{{display:none}}
@media (prefers-color-scheme:dark){{
.bw-topbar,.bw-topbar .bw-menu-list{{background:#1d1a17;color:#f1ece3;border-color:#3b362f}}
.bw-topbar .bw-menu summary{{border-color:#3b362f}}.bw-topbar .bw-menu-list a{{border-color:#3b362f}}
.bw-topbar .bw-light{{display:none}}.bw-topbar .bw-dark{{display:block}}}}
@media (max-width:760px){{.bw-topbar nav,.bw-topbar .bw-gh{{display:none}}.bw-topbar .bw-brand{{flex:1;margin-right:0}}.bw-topbar .bw-menu{{display:block;margin-left:0}}}}
@media print{{.bw-topbar{{display:none}}}}
</style>'''


def bar(base, repository='Ulef1005/brick-work'):
    """The top bar for a site deployed under `base` (a path with a leading and trailing slash), linking GitHub at `repository`."""
    links = ''.join(f'<a href="{base}{path}">{name}</a>' for name, path in LINKS)
    github = f'https://github.com/{html.escape(repository)}'
    return (f'<header class="bw-topbar" {MARKER}><a class="bw-brand" href="{base}" aria-label="Brick Work home">'
            f'<img class="bw-light" src="{base}assets/lockup-horizontal-light.png" alt="Brick Work" height="26">'
            f'<img class="bw-dark" src="{base}assets/lockup-horizontal-dark.png" alt="" height="26"></a>'
            f'<nav aria-label="Site">{links}</nav><a class="bw-gh" href="{github}">GitHub</a>'
            f'<details class="bw-menu"><summary>Menu</summary><nav class="bw-menu-list" aria-label="Site menu">{links}<a href="{github}">GitHub</a></nav></details></header>')


def inject(page, base, repository='Ulef1005/brick-work'):
    """`page` (an HTML document) with the bar in it. A page that already has the bar comes back unchanged, so a second pass is harmless. A page
    without `<head>` and `<body>` is an error: the bar must never silently go missing."""
    if MARKER in page:
        return page
    head = re.search(r'</head\s*>', page, flags=re.I)
    body = re.search(r'<body\b[^>]*>', page, flags=re.I)
    if not head or not body or head.start() > body.start():
        raise ValueError('cannot add the top bar: the page has no <head> before its <body>')
    return page[:head.start()] + STYLE + page[head.start():body.end()] + bar(base, repository) + page[body.end():]
