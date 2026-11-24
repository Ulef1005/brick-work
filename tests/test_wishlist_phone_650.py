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
    """#653, #654: "No max set" under the tile's max row is body text, not the mono of an amount."""
    template = (ROOT / 'templates' / 'web' / 'toni' / 'web' / 'bw_planning.html').read_text()
    assert '<span class="bp-max-none">No max set</span>' in template and '<strong class="mono">No max set</strong>' not in template
    css = (ROOT / 'static' / 'web' / 'toni' / 'bw-planning-b.css').read_text()
    assert '#bw-planning:not(#_):not(#_):not(#_) .bp-max-none {font:400 14px/20px var(--tw-font);color:var(--tw-text-2)}' in css


def test_the_wish_detail_cards_keep_their_gap_and_the_single_price_point_reads_plainly():
    """#655: the aside is a column at every width, so its 10px gap separates Wish details from Prices on a phone; a closed disclosure card
    has no hairline strip; the status row keeps 8px from the links; a single price point is said once, in plain words."""
    css = (ROOT / 'static' / 'web' / 'toni' / 'bw-detail-b.css').read_text()
    scope = '#bw-collection[data-b-detail]:not(#_):not(#_)'
    assert f'{scope} .bc-detail-aside {{display:flex;flex-direction:column}}' in css
    assert f'{scope} .bc-detail-aside>details.bc-module:not([open]) {{gap:0}}' in css
    assert f'{scope} .bc-detail-aside>.bc-module {{margin-bottom:0}}' in css                      # the aside's gap is the only space between cards
    assert f'{scope}:not([data-type=S]) .bc-hero-heading+.bc-hero-status {{margin-top:8px}}' in css
    assert f'{scope}[data-type=S] .bc-hero-heading+.bc-hero-status {{margin-top:8px}}' in css.split('@media(max-width:767.98px) {', 1)[1]   # on a phone only: desktop has its own gap
    modules = (ROOT / 'templates' / 'web' / 'toni' / 'brickwork' / 'collection_modules.html').read_text()
    assert 'a line needs two dates' not in modules and 'The trend starts with the second date.' not in modules and 'One price so far' in modules


def test_a_wrapped_state_tag_stays_inside_its_border_and_no_max_is_plain_text_on_every_wish_list():
    """Review of #657: the tile's tag may wrap (height:auto above its 22px), and "No max set" on /collection/wishes is body text like the tile's."""
    css = (ROOT / 'static' / 'web' / 'toni' / 'bw-planning-b.css').read_text()
    scope = '#bw-planning:not(#_):not(#_):not(#_)'
    assert f'{scope} .bp-wish-number .bc-status {{height:auto;min-height:22px;padding-block:2px;line-height:14px}}' in css
    script = (ROOT / 'static' / 'web' / 'toni' / 'bw-collection.js').read_text()
    assert "el('span','bc-wish-max-none','No max set')" in script and "r.max_price||'Not recorded'" not in script
    assert '.bc-wish-max-none { font:400 14px/20px var(--tw-font);color:var(--tw-text-2); }' in (ROOT / 'static' / 'web' / 'toni' / 'bw-collection.css').read_text()


def test_a_wish_page_on_a_phone_has_its_picture_beside_the_title():
    """Product, 23.11. (#654): on a phone a wish's picture is 110px beside the title, as on Set detail, so the answer is on the first screen."""
    template = (ROOT / 'templates' / 'web' / 'toni' / 'web' / 'bw_collection_detail.html').read_text()
    assert '{% if detail.wish %} data-b-wish{% endif %}' in template
    css = (ROOT / 'static' / 'web' / 'toni' / 'bw-detail-b.css').read_text()
    phone = css.split('#bw-collection[data-b-detail][data-b-wish]', 1)[0].rsplit('@media(max-width:1023.98px) {', 1)[1] + css.split('@media(max-width:1023.98px) {')[-1]
    assert '.bc-detail-hero {grid-template-columns:110px minmax(0,1fr)' in phone and '.bc-hero-picture {width:110px;height:84px' in phone
