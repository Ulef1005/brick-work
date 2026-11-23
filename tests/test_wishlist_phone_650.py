"""#650: the Wishlist on a phone stays inside the screen."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_wishlist_head_and_tiles_stay_inside_a_phone():
    """#650: many lists scroll in their own row instead of widening the page, the actions start at the left edge, and a wish tile's tags wrap
    under its number instead of squeezing it to one digit per line."""
    css = (ROOT / 'static' / 'web' / 'toni' / 'bw-planning-b.css').read_text()
    scope = '#bw-planning:not(#_):not(#_):not(#_)'
    assert f'{scope} {{min-width:0}}' in css                                    # a grid item of #content
    phone = css.split('@media(max-width:767.98px) {', 1)[1].split('\n}', 1)[0]
    assert f'{scope} .wl-head {{flex-direction:column;align-items:stretch;min-width:0;max-width:100%}}' in phone
    assert f'{scope} .wl-head .wl-toolbar {{justify-content:flex-start;flex-wrap:wrap;max-width:100%}}' in phone
    assert f'{scope} .bp-wish-number {{flex-wrap:wrap;row-gap:4px;min-width:0}}' in css
    assert f'{scope} .bp-wish-number>.mono {{white-space:nowrap;max-width:100%;overflow:hidden;text-overflow:ellipsis}}' in css


def test_a_wish_without_a_max_says_so_in_body_text():
    """#653: "Not recorded" under Your max price is body text, not the 20px mono of an amount."""
    template = (ROOT / 'templates' / 'web' / 'toni' / 'web' / 'bw_planning.html').read_text()
    assert '<span class="bp-max-none">Not recorded</span>' in template and '<strong class="mono">Not recorded</strong>' not in template
    css = (ROOT / 'static' / 'web' / 'toni' / 'bw-planning-b.css').read_text()
    assert '#bw-planning:not(#_):not(#_):not(#_) .bp-max-none {font:400 14px/20px var(--tw-font);color:var(--tw-text-2)}' in css
