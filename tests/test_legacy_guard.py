"""#492 part 2: the legacy global stylesheets never match inside a .b-prime subtree, and nothing else about them changes."""
import importlib.util
import re
from pathlib import Path

from tests import rendered

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('legacy_guard', ROOT / 'scripts' / 'legacy_guard.py')
lg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lg)

SAMPLE = '''/* a comment with { braces } and , commas */
.a,.b .c{color:red}
@media(min-width:1px){.d>.e::before{x:y}input::placeholder{x:y}}
@keyframes k{from{opacity:0}to{opacity:1}}
@font-face{font-family:F;src:url(f.woff2)}
:root{--x:1}
body{margin:0}
.f::-webkit-scrollbar-thumb:hover{x:y}
a:hover,*::after{x:y}
'''


def test_every_selector_of_the_three_files_carries_the_guard():
    assert lg.check() == 0


def test_the_transform_keeps_comments_pseudo_elements_and_at_rules_and_is_idempotent():
    once = lg.transform(SAMPLE)
    g = lg.GUARD
    assert once.startswith('/* a comment with { braces } and , commas */')
    assert f'.a{g},.b .c{g}{{color:red}}' in once
    assert f'.d>.e{g}::before' in once and f'input{g}::placeholder' in once
    assert f'.f{g}::-webkit-scrollbar-thumb:hover' in once
    assert f'a:hover{g},*{g}::after' in once
    assert '@keyframes k{from{opacity:0}to{opacity:1}}' in once and '@font-face{font-family:F;src:url(f.woff2)}' in once
    assert ':root{--x:1}' in once and 'body{margin:0}' in once
    assert lg.transform(once) == once
    assert lg.transform(once).replace(g, '') == SAMPLE


@rendered.group
def test_the_guard_drops_no_rule_and_stops_matching_inside_b_prime(tmp_path):
    """Chrome parses every guarded file to as many rules as the unguarded text, and a guarded rule skips a .b-prime subtree."""
    chrome = rendered.chrome()
    count = ('<script>const c=r=>[...r].reduce((n,x)=>n+1+(x.cssRules?c(x.cssRules):0),0);'
             'document.body.append(document.createTextNode("COUNT="+c(document.styleSheets[0].cssRules)))</script>')
    for path in lg.FILES:
        text = path.read_text(encoding='utf-8')
        counts = []
        for css in (text, text.replace(lg.GUARD, '')):
            page = tmp_path / 'count.html'
            page.write_text(f'<style>{css}</style><body>{count}')
            counts.append(re.search(r'COUNT=(\d+)', rendered.dump_dom(chrome, f'file://{page}')).group(1))
        assert counts[0] == counts[1], (path.name, counts)
    page = tmp_path / 'inside.html'
    page.write_text('<style>.x' + lg.GUARD + '{color:rgb(255,0,0)}</style><div class=x id=out>o</div><div class=b-prime><div class=x id=in>i</div></div>'
                    '<script>document.body.append(document.createTextNode("R="+getComputedStyle(out).color+";"+getComputedStyle(document.getElementById("in")).color))</script>')
    assert 'R=rgb(255, 0, 0);rgb(0, 0, 0)' in rendered.dump_dom(chrome, f'file://{page}')
