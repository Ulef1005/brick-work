"""The docs site's theme, generated from Brick Work's design tokens (App Docs Standard, B2 of doc-standard-v1).

    python scripts/docs_theme.py build    # write docs/assets/brickwork-docs.css and copy the fonts into docs/assets/fonts/
    python scripts/docs_theme.py check    # exit 1 when the committed files differ from what build would write

The docs CSS is the served tokens (static/web/toni/tokens-v2.css, itself built from design/tokens/ by scripts/tokens_base.py)
with their light and dark classes moved onto Zensical's colour schemes (`default` and `slate`), then the mapping of those
tokens onto Zensical's own variables and a few rules of the brickwork-design skill (paper header with an ink hairline, clay
for links and the active tab, no shadows, Inter and Geist Mono, status colours on the admonitions). No colour is written
here by hand: every value is a var(--tw-*). The fonts are the app's own files, so the documentation pages make no external requests.

Zensical puts the scheme on <body>, so the tokens' OS-preference block still sets <html> from the system setting; the body's
scheme block then redefines every colour token for the page. A token that is only defined on :root in terms of another
(--tw-sheet-edge) resolves at <html> and follows the system setting: use the colour tokens themselves in the docs CSS.
"""
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKENS = ROOT / 'static/web/toni/tokens-v2.css'
FONTS = ROOT / 'static/web/toni/fonts'
OUT = ROOT / 'docs/assets/brickwork-docs.css'
OUT_FONTS = ROOT / 'docs/assets/fonts'
FONT_FILES = ('inter-latin-400-normal.woff2', 'inter-latin-500-normal.woff2', 'inter-latin-600-normal.woff2',
              'geist-mono-latin-400-normal.woff2', 'geist-mono-latin-500-normal.woff2', 'LICENSE-Inter.txt', 'LICENSE-GeistMono.txt')
LIGHT, DARK = '[data-md-color-scheme="default"]', '[data-md-color-scheme="slate"]'

FACES = ''.join(
    f"@font-face{{font-family:'{family}';font-style:normal;font-weight:{weight};font-display:swap;"
    f"src:url('fonts/{name}') format('woff2')}}\n"
    for family, weight, name in (('Inter', 400, 'inter-latin-400-normal.woff2'), ('Inter', 500, 'inter-latin-500-normal.woff2'),
                                 ('Inter', 600, 'inter-latin-600-normal.woff2'), ('Geist Mono', 400, 'geist-mono-latin-400-normal.woff2'),
                                 ('Geist Mono', 500, 'geist-mono-latin-500-normal.woff2')))

MAPPING = f'''
/* Zensical's variables, from the tokens above (both schemes: the tokens differ, the mapping does not). Zensical's own
   palette rules name the scheme and the primary colour, so these name both to come after them at the same weight. */
{LIGHT}, {DARK}, {LIGHT}[data-md-color-primary], {DARK}[data-md-color-primary] {{
  --md-text-font: "Inter";
  --md-code-font: "Geist Mono";
  --md-default-bg-color: var(--tw-bg);
  --md-default-fg-color: var(--tw-text);
  --md-default-fg-color--light: var(--tw-text-2);
  --md-default-fg-color--lighter: var(--tw-text-muted);
  --md-default-fg-color--lightest: var(--tw-divider);
  --md-primary-fg-color: var(--tw-bg);
  --md-primary-fg-color--light: var(--tw-surface);
  --md-primary-fg-color--dark: var(--tw-surface-2);
  --md-primary-bg-color: var(--tw-text);
  --md-primary-bg-color--light: var(--tw-text-muted);
  --md-accent-fg-color: var(--tw-accent);
  --md-accent-fg-color--transparent: var(--tw-accent-soft);
  --md-accent-bg-color: var(--tw-on-accent);
  --md-typeset-color: var(--tw-text);
  --md-typeset-a-color: var(--tw-accent-text);
  --md-code-bg-color: var(--tw-surface);
  --md-code-fg-color: var(--tw-text);
  --md-code-hl-color: var(--tw-accent-soft);
  --md-typeset-table-color: var(--tw-divider);
  --md-footer-bg-color: var(--tw-surface);
  --md-footer-bg-color--dark: var(--tw-surface-2);
  --md-footer-fg-color: var(--tw-text);
  --md-footer-fg-color--light: var(--tw-text-2);
  --md-footer-fg-color--lighter: var(--tw-text-muted);
}}

/* Paper and ink, with 0.5 px hairlines and no shadows (brickwork-design: no gradients, no shadows). */
.md-header, .md-tabs {{ background-color: var(--tw-bg); color: var(--tw-text); box-shadow: none; }}
.md-header {{ border-bottom: 0.5px solid var(--tw-divider); }}
.md-header--shadow {{ box-shadow: none; }}
.md-tabs {{ border-bottom: 0.5px solid var(--tw-divider); }}
.md-tabs__link {{ opacity: 1; color: var(--tw-text-2); font-weight: 500; }}
.md-tabs__item--active {{ border-bottom: 2px solid var(--tw-accent); }}
.md-tabs__item--active .md-tabs__link {{ color: var(--tw-text); }}
.md-tabs__link:hover, .md-nav__link:hover {{ color: var(--tw-accent-text); }}
.md-nav .md-nav__item .md-nav__link--active, .md-nav--primary .md-nav__item .md-nav__link--active {{ color: var(--tw-text); background-color: var(--tw-accent-soft); font-weight: 600; }}
.md-search__form {{ background-color: var(--tw-surface); box-shadow: none; }}
.md-typeset h1, .md-typeset h2, .md-typeset h3 {{ color: var(--tw-text); font-weight: 600; letter-spacing: 0; }}
.md-typeset code {{ border-radius: var(--tw-r-1); }}
.md-typeset pre > code {{ border: 0.5px solid var(--tw-divider); border-radius: var(--tw-r-2); }}
.md-typeset table:not([class]) {{ box-shadow: none; border: 0.5px solid var(--tw-divider); border-radius: var(--tw-r-2); }}
.md-typeset table:not([class]) th {{ background-color: var(--tw-surface); color: var(--tw-text-2); font-weight: 600; }}
.md-typeset table:not([class]) td {{ border-top: 0.5px solid var(--tw-divider); }}
.md-typeset .tabular, .md-typeset td code {{ font-variant-numeric: tabular-nums; }}
:focus-visible {{ outline: var(--tw-focus-width) solid var(--tw-focus-color); outline-offset: var(--tw-focus-offset); }}

/* Admonitions take the status colours as the status pills do: a soft ground, ink text, the icon in the status colour.
   One ground per box: the title has none of its own. */
.md-typeset .admonition, .md-typeset details {{ box-shadow: none; border: 0; border-radius: var(--tw-r-2); font-size: inherit; }}
.md-typeset .admonition-title, .md-typeset summary {{ background-color: transparent; color: var(--tw-text); }}
.md-typeset summary::after {{ background-color: var(--tw-text-muted); }}
/* A folded reference block (the API reference's request and responses): a plain surface, no status, no icon. */
.md-typeset details.reference {{ background-color: var(--tw-surface); border: 0.5px solid var(--tw-divider); }}
.md-typeset details.reference > summary {{ padding-left: 0; font-weight: 500; }}
.md-typeset details.reference > summary::before {{ display: none; }}
'''
SCREENS = f'''
/* The screens switch (docs/assets/screens.js) and the screenshots: the picture never outgrows the column; a phone shot shown on a wide screen stays phone-sized. */
.md-typeset picture {{ display: inline-block; max-width: 100%; }}
.md-typeset picture[data-forced="phone"] img {{ width: 300px; }}
.bw-screens {{ display: flex; flex-wrap: wrap; align-items: center; gap: var(--tw-s-2); margin: var(--tw-s-3) 0; font-size: var(--tw-fs-small); color: var(--tw-text-2); }}
.bw-screens button {{ font: inherit; color: var(--tw-text); background: transparent; border: 0.5px solid var(--tw-divider-strong); border-radius: var(--tw-r-2); padding: var(--tw-s-1) var(--tw-s-3); cursor: pointer; }}
.bw-screens button[aria-pressed="true"] {{ background: var(--tw-accent-soft); border-color: var(--tw-accent); color: var(--tw-accent-text); font-weight: 600; }}
.bw-screens button:hover {{ border-color: var(--tw-accent); }}
'''
STATUS = (('note', 'info'), ('info', 'info'), ('abstract', 'info'), ('tip', 'success'), ('success', 'success'),
          ('question', 'info'), ('warning', 'warning'), ('failure', 'danger'), ('danger', 'danger'), ('bug', 'danger'),
          ('example', 'info'), ('quote', 'info'))


def admonitions():
    rules = []
    for kind, status in STATUS:
        box = f'.md-typeset .admonition.{kind}, .md-typeset details.{kind}'
        title = f'.md-typeset .{kind} > .admonition-title, .md-typeset .{kind} > summary'
        icon = f'.md-typeset .{kind} > .admonition-title::before, .md-typeset .{kind} > summary::before'
        rules.append(f'{box} {{ background-color: var(--tw-{status}-soft); }}\n'
                     f'{title} {{ background-color: transparent; color: var(--tw-text); }}\n'
                     f'{icon} {{ background-color: var(--tw-{status}); }}\n')
    return ''.join(rules)


def css():
    # The tokens' comments go (they describe the app, where the classes sit on <html>); then the app's .tw-light / .tw-dark,
    # and only those exact classes, become Zensical's schemes.
    tokens = re.sub(r'/\*.*?\*/\n?', '', TOKENS.read_text(), flags=re.S)
    tokens = re.sub(r'\.tw-(light|dark)(?![-\w])', lambda m: LIGHT if m[1] == 'light' else DARK, tokens)
    head = ('/* Generated by scripts/docs_theme.py from static/web/toni/tokens-v2.css: do not edit, run '
            '`python scripts/docs_theme.py build`. */\n')
    return head + FACES + tokens + MAPPING + admonitions() + SCREENS


def build():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(css())
    OUT_FONTS.mkdir(exist_ok=True)
    for name in FONT_FILES:
        shutil.copy(FONTS / name, OUT_FONTS / name)


def check():
    problems = []
    if not OUT.is_file() or OUT.read_text() != css():
        problems.append(f'{OUT.relative_to(ROOT)} is out of date: run python scripts/docs_theme.py build')
    for name in FONT_FILES:
        if not (FONTS / name).is_file():
            problems.append(f'static/web/toni/fonts/{name} is missing: FONT_FILES names a font the app no longer has')
        elif not (OUT_FONTS / name).is_file() or (OUT_FONTS / name).read_bytes() != (FONTS / name).read_bytes():
            problems.append(f'docs/assets/fonts/{name} differs from static/web/toni/fonts/{name}')
    extra = sorted(p.name for p in OUT_FONTS.glob('*') if p.name not in FONT_FILES) if OUT_FONTS.is_dir() else []
    problems += [f'docs/assets/fonts/{name} is not in FONT_FILES: remove it' for name in extra]
    return problems


if __name__ == '__main__':
    if sys.argv[1:] == ['build']:
        build()
    elif sys.argv[1:] == ['check']:
        found = check()
        print('\n'.join(found) or 'docs theme is up to date')
        sys.exit(1 if found else 0)
    else:
        sys.exit(__doc__)
