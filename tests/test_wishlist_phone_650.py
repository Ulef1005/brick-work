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


def test_the_wish_detail_cards_keep_their_gap_and_the_single_price_point_reads_plainly():
    """#655: the aside is a column at every width, so its 10px gap separates Wish details from Prices on a phone; a closed disclosure card
    has no hairline strip; the status row keeps 8px from the links; a single price point is said once, in plain words."""
    css = (ROOT / 'static' / 'web' / 'toni' / 'bw-detail-b.css').read_text()
    scope = '#bw-collection[data-b-detail]:not(#_):not(#_)'
    assert f'{scope} .bc-detail-aside {{display:flex;flex-direction:column}}' in css
    assert f'{scope} .bc-detail-aside>details.bc-module:not([open])>summary {{border-bottom:0}}' in css
    assert f'{scope} .bc-hero-heading+.bc-hero-status {{margin-top:8px}}' in css
    modules = (ROOT / 'templates' / 'web' / 'toni' / 'brickwork' / 'collection_modules.html').read_text()
    assert 'a line needs two dates' not in modules and 'The trend starts with the second date.' in modules
