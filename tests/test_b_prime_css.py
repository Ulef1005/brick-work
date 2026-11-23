"""#492 part 2: the B′ component stylesheet is generated from the frames' source and scoped under .b-prime."""
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('b_prime_css', ROOT / 'scripts' / 'b_prime_css.py')
bp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bp)


def test_the_served_stylesheet_is_what_build_makes():
    assert bp.check() == 0


def test_every_rule_is_scoped_under_the_root_class():
    css = re.sub(r'/\*.*?\*/', '', bp.SERVED.read_text(encoding='utf-8'), flags=re.S)
    css = re.sub(r'@media[^{]*\{', '', css)
    selectors = [s for chunk in re.findall(r'([^{}]+)\{[^{}]*\}', css) for s in bp.split_top(chunk.strip())]
    assert len(selectors) > 100
    for selector in selectors:
        assert re.match(r'(:root:not\(\.tw-light\) |\.tw-dark )?\.b-prime(:not\(#_\)){3}( |$)', selector), selector
        assert not re.match(r'(html|body)\b', selector)


def test_the_frames_dark_changes_follow_under_both_dark_selectors():
    css = bp.SERVED.read_text(encoding='utf-8')
    for fragment in ('background:rgba(0,0,0,.55)', '.xchip svg path', 'mix-blend-mode:multiply'):
        assert css.count(fragment) >= 2, fragment
    assert '{color-scheme:' not in css
    assert '@media (prefers-color-scheme: dark)' in css and '.tw-dark .b-prime' in css


def test_the_stylesheet_is_served_and_precached():
    assert 'b-prime.css' in (ROOT / 'static/web/toni/sw.js').read_text().replace('/static/brickwork/', '')
    from scripts import brand_assets  # noqa: F401  (the file is app-owned: a source folder never claims it)


@pytest.mark.parametrize('bad', ['@media (min-width:1px){.a{color:red}}', 'html{color:red}', '.a{.b{color:red}}'])
def test_what_cannot_be_scoped_fails_the_build(bad):
    with pytest.raises(SystemExit):
        bp.generate({'B_COMPONENTS': (bad,), 'SWAPS': [], 'DARK_CSS': ''})


def test_a_swap_is_applied_in_order_and_only_changed_rules_go_dark():
    out = bp.generate({'B_COMPONENTS': ('.a{color:red}.b{box-shadow:0 0 1px rgba(1,1,1,.5)}',), 'SWAPS': [('rgba(1,1,1,.5)', 'blue')], 'DARK_CSS': 'html{color-scheme:dark}.c{x:y}'})
    dark = out.split('\n@media (prefers-color-scheme: dark)', 1)[1]
    assert 'blue' in dark and '.b{' in dark and '.a{' not in dark and '.c{x:y}' in dark and '{color-scheme:' not in dark
