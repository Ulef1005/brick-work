"""#158: the design builder base, Brick Work's layer and the served stylesheet made from them. The base never shows through:
in every theme and motion context the served file resolves each of the layer's properties exactly as the layer alone does
(B′ values since #492, pinned to the frames below). The drift check runs without an ai-wiki checkout."""
import importlib.util
import re
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('tokens_base', ROOT / 'scripts' / 'tokens_base.py')
tb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tb)

SPECIFICITY = {':root': (0, 1, 0), ':root:not(.tw-light)': (0, 2, 0), '.tw-dark': (0, 1, 0), '.tw-light': (0, 1, 0), ':focus-visible': (0, 1, 0)}
CONTEXTS = [dict(dark=dark, cls=cls, reduced=reduced) for dark in (False, True) for cls in ('', 'tw-dark', 'tw-light') for reduced in (False, True)]


def rules(css):
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    out, stack, buf, n = [], [], '', 0
    for ch in css:
        if ch == '{':
            stack.append(' '.join(buf.split()))
            buf = ''
        elif ch == '}':
            decls = [d.split(':', 1) for d in buf.split(';') if ':' in d]
            if decls:
                n += 1
                out.append((list(stack), n, {k.strip(): ' '.join(v.split()) for k, v in decls}))
            if stack:
                stack.pop()
            buf = ''
        else:
            buf += ch
    return out


def applies(stack, ctx):
    for media in stack[:-1]:
        if 'prefers-color-scheme: dark' in media and not ctx['dark']:
            return False
        if 'prefers-reduced-motion' in media and not ctx['reduced']:
            return False
    return {':root': True, ':root:not(.tw-light)': ctx['cls'] != 'tw-light', '.tw-dark': ctx['cls'] == 'tw-dark',
            '.tw-light': ctx['cls'] == 'tw-light'}.get(stack[-1], False)


def resolve(css, ctx):
    """What `<html class=ctx.cls>` gets: the winning declaration per property by specificity, then source order."""
    winners = {}
    for stack, order, decls in rules(css):
        assert stack[-1] in SPECIFICITY, f'a selector the test does not know: {stack[-1]}'
        if applies(stack, ctx):
            for name, value in decls.items():
                if name not in winners or (SPECIFICITY[stack[-1]], order) >= winners[name][0]:
                    winners[name] = ((SPECIFICITY[stack[-1]], order), value)
    return {name: value for name, (_, value) in winners.items()}


def test_the_tokens_are_in_order():
    assert tb.problems() == []


@pytest.mark.parametrize('ctx', CONTEXTS, ids=lambda c: f"{'dark' if c['dark'] else 'light'}-{c['cls'] or 'system'}{'-reduced' if c['reduced'] else ''}")
def test_the_base_never_shows_through_the_layer(ctx):
    layer = tb.LAYER.read_text(encoding='utf-8')
    served = resolve(tb.SERVED.read_text(encoding='utf-8'), ctx)
    alone = resolve(layer, ctx)
    assert {k: served.get(k) for k in alone} == alone


def test_an_edited_copy_or_a_hand_edited_served_file_is_drift(tmp_path, monkeypatch):
    for name in ('COPY', 'LAYER', 'JSON_OUT', 'SERVED'):
        target = tmp_path / getattr(tb, name).name
        shutil.copy(getattr(tb, name), target)
        monkeypatch.setattr(tb, name, target)
    assert tb.problems() == []
    tb.COPY.write_text(tb.COPY.read_text(encoding='utf-8').replace('#FFFFFF', '#FFFFFE', 1), encoding='utf-8')
    assert any('was edited' in p for p in tb.problems())
    shutil.copy(ROOT / 'design' / 'tokens' / 'tokens.css', tb.COPY)
    tb.SERVED.write_text(tb.SERVED.read_text(encoding='utf-8') + '\n:root { --tw-accent: red; }\n', encoding='utf-8')
    assert any('is not what' in p for p in tb.problems())


def test_a_layer_that_misses_a_base_property_is_refused(tmp_path, monkeypatch):
    for name in ('COPY', 'LAYER', 'JSON_OUT', 'SERVED'):
        target = tmp_path / getattr(tb, name).name
        shutil.copy(getattr(tb, name), target)
        monkeypatch.setattr(tb, name, target)
    tb.LAYER.write_text(tb.LAYER.read_text(encoding='utf-8').replace('--tw-z-toast: 30;', ''), encoding='utf-8')
    tb.build()
    assert any('--tw-z-toast' in p and 'does not redefine' in p for p in tb.problems())


def test_the_copy_carries_its_provenance():
    head = tb.COPY.read_text(encoding='utf-8').split('*/', 1)[0]
    assert tb.BASE_PATH in head and re.search(r'ai-wiki commit [0-9a-f]{7,40}', head) and re.search(r'source SHA-256: [0-9a-f]{64}', head)


# ---- B′ (#492): the layer takes its values from the frames' source, never a copy that can drift ----

import ast  # noqa: E402

FRAMES = ROOT / 'design' / 'sources' / 'b' / 'b_frames.py'


def frame_values():
    """TOKENS (light: the B′ value is each tuple's second item) and DARK from b_frames.py, read with ast: importing it
    would read the logo and font files and build nothing we need."""
    found = {}
    for node in ast.parse(FRAMES.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and getattr(node.targets[0], 'id', None) in ('TOKENS', 'DARK'):
            found[node.targets[0].id] = ast.literal_eval(node.value)
    light = {k: v[1] for k, v in found['TOKENS'].items() if not v[1].startswith('none')}
    return light, found['DARK']


def family(value):
    return value.split(',')[0].strip()


def block(selector):
    return {k: v for k, v in tb.blocks(tb.LAYER.read_text(encoding='utf-8')).get(selector, {}).items()}


LIGHT_BLOCKS = (':root', '.tw-light')
DARK_BLOCKS = ('@media (prefers-color-scheme: dark) >> :root:not(.tw-light)', '.tw-dark')


@pytest.mark.parametrize('selector', LIGHT_BLOCKS)
def test_the_light_blocks_carry_the_frames_values(selector):
    light, _ = frame_values()
    have = block(selector)
    for name, value in light.items():
        if name.startswith('--tw-font') or name == '--tw-mono':
            if selector == ':root':
                assert family(have[name]) == value, name
            continue
        if name.startswith('--tw-r-'):
            if selector == ':root':
                assert have[name] == value, name
            continue
        assert have[name].upper() == value.upper(), f'{selector} {name}: {have.get(name)} is not the frames\' {value}'
    assert {'--tw-field', '--tw-tile', '--tw-tile-ink'} <= set(light)   # in TOKENS since #537


@pytest.mark.parametrize('selector', DARK_BLOCKS)
def test_the_dark_blocks_carry_the_frames_values(selector):
    _, dark = frame_values()
    have = block(selector)
    for name, value in dark.items():
        assert have[name].upper() == value.upper(), f'{selector} {name}: {have.get(name)} is not the frames\' {value}'


def test_the_forced_blocks_equal_the_system_blocks():
    assert block('.tw-light') == {k: v for k, v in block(':root').items() if k in block('.tw-light')}
    assert block('.tw-dark') == block(DARK_BLOCKS[0])


def test_focus_is_ink_never_violet():
    for selector in LIGHT_BLOCKS + DARK_BLOCKS:
        have = block(selector)
        assert have['--tw-focus-color'] == have['--tw-text'] != have['--tw-accent'], selector


def test_the_retired_faces_are_gone():
    text = tb.LAYER.read_text(encoding='utf-8')
    for face in ('Inter', 'Geist', 'Patrick Hand'):
        assert not re.search(rf"'{face}[ ']", text), face


def test_every_theme_block_sets_the_same_properties():
    names = {selector: set(block(selector)) for selector in DARK_BLOCKS + ('.tw-light',)}
    assert len(set(map(frozenset, names.values()))) == 1, names
    assert names['.tw-light'] <= set(block(':root'))


def test_the_install_colours_are_the_app_bar_surface():
    # W-Q7 (Ulf, 19.11.: "App bar surface"): the manifest, the ?theme=dark manifest and the theme-color metas take --tw-surface.
    import json
    light, dark = block(':root')['--tw-surface'], block('.tw-dark')['--tw-surface']
    manifest = json.loads((ROOT / 'static/brickwork/manifest.webmanifest').read_text(encoding='utf-8'))
    assert manifest['theme_color'] == manifest['background_color'] == light
    assert f"theme_color='{dark}', background_color='{dark}'" in (ROOT / 'brickwork/web/views.py').read_text(encoding='utf-8')
    head = (ROOT / 'templates/web/toni/pwa-head.html').read_text(encoding='utf-8')
    assert f'content="{light}" media="(prefers-color-scheme: light)"' in head and f'content="{dark}" media="(prefers-color-scheme: dark)"' in head
    assert f"'{dark}' : '{light}'" in (ROOT / 'static/web/toni/pwa.js').read_text(encoding='utf-8')


def test_the_docs_and_demo_top_bar_takes_the_layer_values():
    # scripts/site_nav.py's bar sits on the docs and demo pages; its colours are the layer's surface, ink and divider (#492).
    bar = (ROOT / 'scripts/site_nav.py').read_text(encoding='utf-8')
    for selector in ('.tw-light', '.tw-dark'):
        have = block(selector)
        want = f"--bw-bg:{have['--tw-surface']};--bw-fg:{have['--tw-text']};--bw-line:{have['--tw-divider']};"
        assert want in bar, (selector, want)
