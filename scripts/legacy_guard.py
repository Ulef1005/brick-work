"""Keeps the legacy global stylesheets out of B′ subtrees (#492 part 2).

    python3 scripts/legacy_guard.py check    every selector of the three files carries the guard; exit 1 otherwise
    python3 scripts/legacy_guard.py apply    add the guard to every selector that lacks it (run after editing a legacy file)

toni.css, shell.css and remaining.css load on every page. A rebuilt screen and the B′ shell live under `.b-prime`
(scripts/b_prime_css.py), where those rules must not match. The guard `:where(:not(.b-prime,.b-prime *))` is added to the subject of every
selector (before a pseudo-element); `:where` counts zero, so specificity and every unrebuilt page stay as they were. Rules on html, body or
:root alone are left as they are (they sit above every .b-prime). At-rules `@media`, `@supports` and `@container` are entered; `@font-face`,
`@keyframes` and `@page` are copied whole. Comments are kept. Standard library only."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = [ROOT / 'static' / 'web' / 'toni' / name for name in ('toni.css', 'shell.css', 'remaining.css')]
GUARD = ':where(:not(.b-prime,.b-prime *))'
GROUPS = ('@media', '@supports', '@container', '@layer')
WHOLE = ('@font-face', '@keyframes', '@page', '@property', '@-webkit-keyframes')


def split_top(text: str) -> list[str]:
    parts, depth, cur, quote = [], 0, '', ''
    for ch in text:
        if quote:
            quote = '' if ch == quote else quote
        elif ch in '"\'':
            quote = ch
        elif ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        if ch == ',' and depth == 0 and not quote:
            parts.append(cur)
            cur = ''
        else:
            cur += ch
    parts.append(cur)
    return parts


def subject_start(selector: str) -> int:
    """Index where the last compound selector starts (after the last top-level combinator)."""
    depth, quote, cut = 0, '', 0
    for i, ch in enumerate(selector):
        if quote:
            quote = '' if ch == quote else quote
        elif ch in '"\'':
            quote = ch
        elif ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        elif depth == 0 and ch in ' >+~':
            cut = i + 1
    return cut


def guard_one(part: str) -> str:
    lead = part[:len(part) - len(part.lstrip())]
    trail = part[len(part.rstrip()):]
    sel = part.strip()
    if not sel or GUARD in sel:
        return part
    cut = subject_start(sel)
    subject = sel[cut:]
    if cut == 0 and re.fullmatch(r'(html|body|:root)(\[[^\]]*\]|:[\w-]+(\([^)]*\))?|\.[\w-]+)*', subject):
        return part
    pseudo = re.search(r'::', subject)
    at = cut + pseudo.start() if pseudo else len(sel)
    legacy = re.search(r':(before|after|first-line|first-letter)$', sel)
    if not pseudo and legacy:
        at = legacy.start()
    return lead + sel[:at] + GUARD + sel[at:] + trail


def guard_selectors(prelude: str) -> str:
    return ','.join(guard_one(part) for part in split_top(prelude))


def transform(css: str) -> str:
    out, pos, n = [], 0, len(css)

    def block_end(start: int) -> int:           # index after the '}' matching the '{' at start, skipping comments and strings
        depth, i, quote = 0, start, ''
        while i < n:
            if css.startswith('/*', i) and not quote:
                i = css.index('*/', i) + 2
                continue
            ch = css[i]
            if quote:
                quote = '' if ch == quote else quote
            elif ch in '"\'':
                quote = ch
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        raise SystemExit('LEGACY-GUARD: an unclosed block')

    def walk(start: int, stop: int) -> None:
        nonlocal pos
        i, prelude_from = start, start
        while i < stop:
            if css.startswith('/*', i):
                i = css.index('*/', i) + 2
                continue
            if css[i] == '{':
                prelude = css[prelude_from:i]
                head = re.sub(r'/\*.*?\*/', '', prelude, flags=re.S).strip()
                end = block_end(i)
                comments = re.findall(r'/\*.*?\*/\s*', prelude, flags=re.S)
                lead = ''.join(comments)
                tail_ws = prelude[len(prelude.rstrip()):]
                if head.startswith('@'):
                    out.append(css[prelude_from:i + 1])
                    if head.startswith(GROUPS):
                        walk(i + 1, end - 1)
                        out.append(css[end - 1:end])
                    elif head.startswith(WHOLE):
                        out.append(css[i + 1:end])
                    else:
                        raise SystemExit(f'LEGACY-GUARD: an at-rule it does not know: {head[:40]}')
                else:
                    if '{' in css[i + 1:end - 1]:
                        raise SystemExit(f'LEGACY-GUARD: nested rule under {head[:40]}')
                    stripped = re.sub(r'/\*.*?\*/\s*', '', prelude, flags=re.S)
                    lead_ws = stripped[:len(stripped) - len(stripped.lstrip())]
                    out.append(lead + lead_ws + guard_selectors(head) + tail_ws + css[i:end])
                prelude_from = i = end
                continue
            i += 1
        out.append(css[prelude_from:stop])

    walk(0, n)
    return ''.join(out)


def selectors(css: str) -> list[str]:
    """Every style-rule selector part of a stylesheet (at-rules entered, keyframes and font-face skipped)."""
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    found, stack, buf = [], [], ''
    for ch in css:
        if ch == '{':
            head = buf.strip()
            stack.append(head)
            if not head.startswith('@') and not any(s.startswith(WHOLE) for s in stack[:-1]):
                found += [p.strip() for p in split_top(head)]
            buf = ''
        elif ch == '}':
            if stack:
                stack.pop()
            buf = ''
        elif ch == ';' and not stack or ch == ';':
            buf = '' if not buf.strip().startswith('@') or True else buf
        else:
            buf += ch
    return found


def unguarded(css: str) -> list[str]:
    return [s for s in selectors(css) if guard_one(s) != s]


def check() -> int:
    bad = 0
    for path in FILES:
        for sel in unguarded(path.read_text(encoding='utf-8')):
            print(f'LEGACY-GUARD: {path.name}: {sel[:80]} has no guard (run scripts/legacy_guard.py apply)')
            bad += 1
    return 1 if bad else 0


def apply() -> int:
    for path in FILES:
        path.write_text(transform(path.read_text(encoding='utf-8')), encoding='utf-8')
    print('Guarded', ', '.join(p.name for p in FILES))
    return 0


if __name__ == '__main__':
    command = sys.argv[1] if len(sys.argv) > 1 else ''
    if command not in ('check', 'apply'):
        raise SystemExit(__doc__)
    raise SystemExit(check() if command == 'check' else apply())
