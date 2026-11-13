"""The top bar that /docs/ and /demo/ carry (#363): where it goes, what it links, and what it must not contain."""
import pytest

from scripts import site_nav

PAGE = '<!doctype html><html><head><title>t</title></head><body class="x"><main>hi</main></body></html>'


@pytest.mark.parametrize('base', ['/', '/brick-work/'])
def test_links_are_absolute_from_the_deployment_base(base):
    bar = site_nav.bar(base)
    for name, path in site_nav.LINKS:
        assert f'<a href="{base}{path}">{name}</a>' in bar
    assert f'src="{base}assets/lockup-horizontal-light.png"' in bar
    assert 'href="https://github.com/Ulef1005/brick-work"' in bar


def test_the_bar_sits_right_after_body_and_the_style_in_the_head():
    out = site_nav.inject(PAGE, '/')
    assert out.index('data-bw-topbar-style') < out.index('</head>') < out.index('<body class="x">')
    assert out.index('<body class="x">') + len('<body class="x">') == out.index('<header class="bw-topbar"')
    assert out.endswith('<main>hi</main></body></html>')


def test_a_second_pass_changes_nothing():
    once = site_nav.inject(PAGE, '/')
    assert site_nav.inject(once, '/') == once
    assert once.count(site_nav.MARKER + '>') == 1


def test_no_analytics_script_or_external_request_comes_with_the_bar():
    out = site_nav.inject(PAGE, '/')
    assert '<script' not in out and 'cloudflareinsights' not in out
    assert 'http://' not in out
    assert out.count('https://') == 2   # only the two GitHub links (desktop bar and phone menu)


def test_a_page_without_head_and_body_is_an_error():
    with pytest.raises(ValueError):
        site_nav.inject('<p>fragment</p>', '/')
    with pytest.raises(ValueError):
        site_nav.inject('<body></body><head></head>', '/')


def test_the_phone_menu_needs_no_script():
    bar = site_nav.bar('/')
    assert '<details class="bw-menu">' in bar and 'onclick' not in bar
    assert '@media (max-width:760px)' in site_nav.STYLE


def test_the_bar_height_is_a_variable_the_layouts_can_offset_by():
    assert f'--bw-topbar-h:{site_nav.HEIGHT}px' in site_nav.STYLE


def test_a_page_marker_in_the_text_does_not_stop_the_bar():
    page = PAGE.replace('<main>', '<main><p>data-bw-topbar</p>')
    assert site_nav.bar('/') in site_nav.inject(page, '/')


def test_the_pages_own_theme_switch_is_honoured():
    style = site_nav.STYLE
    assert 'body[data-md-color-scheme="slate"] .bw-topbar' in style and 'html.tw-dark .bw-topbar' in style
    assert ':root:not(.tw-light) body:not([data-md-color-scheme="default"]) .bw-topbar' in style
