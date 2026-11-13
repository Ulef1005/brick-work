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
.bw-topbar{{--bw-bg:#fbf8f2;--bw-fg:#2a2622;--bw-line:#d9d2c5;--bw-light:block;--bw-dark:none;
position:sticky;top:0;z-index:2000;box-sizing:border-box;height:var(--bw-topbar-h);display:flex;align-items:center;gap:8px;padding:0 16px;
background:var(--bw-bg);color:var(--bw-fg);border-bottom:1px solid var(--bw-line);font:14px/1.2 system-ui,-apple-system,"Segoe UI",sans-serif}}
/* The pages' own theme switch wins over the system setting: Zensical sets data-md-color-scheme on <body>, the app and the demo set tw-dark / tw-light on <html>. */
@media (prefers-color-scheme:dark){{:root:not(.tw-light) body:not([data-md-color-scheme="default"]) .bw-topbar{{--bw-bg:#1d1a17;--bw-fg:#f1ece3;--bw-line:#3b362f;--bw-light:none;--bw-dark:block}}}}
html.tw-dark .bw-topbar,body[data-md-color-scheme="slate"] .bw-topbar{{--bw-bg:#1d1a17;--bw-fg:#f1ece3;--bw-line:#3b362f;--bw-light:none;--bw-dark:block}}
.bw-topbar a{{color:inherit;text-decoration:none}}
.bw-topbar .bw-brand{{display:flex;align-items:center;margin-right:8px}}
.bw-topbar .bw-brand img{{height:26px;width:auto}}
.bw-topbar .bw-light{{display:var(--bw-light)}}.bw-topbar .bw-dark{{display:var(--bw-dark)}}
.bw-topbar nav{{display:flex;gap:2px;flex:1;min-width:0}}
.bw-topbar nav a,.bw-topbar .bw-gh{{min-height:36px;display:inline-flex;align-items:center;padding:0 10px;border-radius:6px}}
.bw-topbar nav a:hover,.bw-topbar .bw-gh:hover{{background:rgba(127,127,127,.15)}}
.bw-topbar .bw-menu{{display:none;position:relative;margin-left:auto}}
.bw-topbar .bw-menu summary{{list-style:none;min-height:36px;display:inline-flex;align-items:center;padding:0 14px;border:1px solid var(--bw-line);border-radius:6px;cursor:pointer}}
.bw-topbar .bw-menu summary::-webkit-details-marker{{display:none}}
.bw-topbar .bw-menu-list{{position:absolute;right:0;top:44px;min-width:200px;display:flex;flex-direction:column;background:var(--bw-bg);border:1px solid var(--bw-line);border-radius:8px;overflow:hidden}}
.bw-topbar .bw-menu-list a{{min-height:44px;display:flex;align-items:center;padding:0 16px;border-bottom:1px solid var(--bw-line)}}
.bw-topbar .bw-menu-list a:last-child{{border-bottom:0}}
@media (max-width:760px){{.bw-topbar>nav,.bw-topbar .bw-gh{{display:none}}.bw-topbar .bw-brand{{flex:1;margin-right:0}}.bw-topbar .bw-menu{{display:block;margin-left:0}}}}
@media print{{.bw-topbar{{display:none}}}}
</style>'''


# The layouts' own sticky and fixed elements sit at `top: 0` or a few pixels below it; with the bar above them they move down by its height.
DOCS_OFFSETS = (''
                '.md-header{top:var(--bw-topbar-h)}'
                '.md-sidebar{top:calc(var(--bw-topbar-h) + 2.4rem)}')
DEMO_OFFSETS = ('.bs-aside,.bp-aside,.oo-review{top:calc(var(--bw-topbar-h) + 16px)}'
                '.bd-chooser .bd-panel{top:calc(var(--bw-topbar-h) + 72px)}')


def bar(base, repository='Ulef1005/brick-work'):
    """The top bar for a site deployed under `base` (a path with a leading and trailing slash), linking GitHub at `repository`."""
    links = ''.join(f'<a href="{base}{path}">{name}</a>' for name, path in LINKS)
    github = f'https://github.com/{html.escape(repository)}'
    return (f'<header class="bw-topbar" {MARKER}><a class="bw-brand" href="{base}" aria-label="Brick Work home">'
            f'<img class="bw-light" src="{base}assets/lockup-horizontal-light.png" alt="Brick Work" height="26">'
            f'<img class="bw-dark" src="{base}assets/lockup-horizontal-dark.png" alt="" height="26"></a>'
            f'<nav aria-label="Site">{links}</nav><a class="bw-gh" href="{github}">GitHub</a>'
            f'<details class="bw-menu"><summary>Menu</summary><nav class="bw-menu-list" aria-label="Site menu">{links}<a href="{github}">GitHub</a></nav></details></header>')


def inject(page, base, repository='Ulef1005/brick-work', offsets=''):
    """`page` (an HTML document) with the bar in it. A page that already has the bar comes back unchanged, so a second pass is harmless. A page
    without `<head>` and `<body>` is an error: the bar must never silently go missing."""
    if f'<header class="bw-topbar" {MARKER}' in page:
        return page
    head = re.search(r'</head\s*>', page, flags=re.I)
    body = re.search(r'<body\b[^>]*>', page, flags=re.I)
    if not head or not body or head.start() > body.start():
        raise ValueError('cannot add the top bar: the page has no <head> before its <body>')
    style = STYLE.replace('</style>', offsets + '</style>')
    return page[:head.start()] + style + page[head.start():body.end()] + bar(base, repository) + page[body.end():]
