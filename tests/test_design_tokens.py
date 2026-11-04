"""#158: the design builder base, Brick Work's layer and the served stylesheet made from them. The base never shows through:
in every theme and motion context the served file resolves each of the layer's properties exactly as the layer alone does,
so the roll-out changes no page (ADR 0022). The drift check runs without an ai-wiki checkout."""
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
