"""The docs site's theme is generated from the served tokens and is current (doc-standard-v1 B2, scripts/docs_theme.py)."""
import re

from scripts import docs_theme


def test_the_docs_css_and_fonts_match_the_tokens():
    assert docs_theme.check() == []


def test_the_docs_css_writes_no_colour_of_its_own():
    """Every colour comes from a token: the mapping and the rules after the tokens use var(--tw-*) only."""
    own = docs_theme.MAPPING + docs_theme.admonitions()
    assert not re.search(r'#[0-9a-fA-F]{3,8}\b|\b(?:oklch|oklab|rgba?|hsla?|hwb|lab|lch|color-mix|color)\(', own)
    named = re.findall(r':\s*(white|black|red|blue|green|gray|grey|orange|yellow|purple|teal|navy|silver)\b', own)
    assert not named, named


def test_the_docs_css_loads_nothing_from_outside():
    css = docs_theme.css()
    assert 'http' not in css and '@import' not in css
    for url in re.findall(r"url\('([^']+)'\)", css):
        assert (docs_theme.OUT.parent / url).is_file(), url
