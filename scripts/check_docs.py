"""The user-docs check: a commit that changes app source changes the user docs too, or says why not.

    python3 scripts/check_docs.py commit-msg MSGFILE   # the .githooks/commit-msg hook; exit 1 blocks the commit
    python3 scripts/check_docs.py range A..B           # check.yml re-checks the pushed commits; reports, never fails
    python3 scripts/check_docs.py post-commit          # the .githooks/post-commit hook: re-checks HEAD as a whole, warns
    python3 scripts/check_docs.py pages [--gate]       # the page checks over docs/ (App Docs Standard: User Docs, Developer Docs); a report unless --gate
    python3 scripts/check_docs.py stale                # the stale-page report: pages not re-verified for 3 minor releases

A commit that touches SOURCE without touching a user doc (any docs/**/*.md outside NOT_USER_DOCS) carries
the trailer `Docs: none`, optionally followed by a reason (`Docs: none, refactor only`). Rule: App Standard, Repo & checks and Maintenance
(ai-wiki wiki/projects/references/app-standard-repo-checks.md). Standard library only, so the hook runs
before any virtualenv exists.

On `git commit --amend` the commit-msg hook sees only what is newly staged, not the changes already in the
amended commit, and git does not tell it reliably that the commit is an amend (`--amend -m` passes no
marker). So the post-commit hook re-checks the finished commit as a whole against its parent and warns at
commit time; it cannot block (the commit exists by then), and it also catches `--no-verify`, which skips
commit-msg but not post-commit. The range report in check.sh lists such a commit again before it lands.
"""
import re
import subprocess
import sys
import tomllib
from pathlib import Path

SOURCE = ('brickwork/', 'templates/', 'static/', 'app.py', 'wsgi.py', 'bin/', 'entrypoint.sh')
# User docs: any Markdown file under docs/ except the decision record and the milestone decks (Ulf, 2026-11-05;
# the Diataxis folders alone missed real user docs such as docs/pipeline.md).
NOT_USER_DOCS = ('docs/adr/', 'docs/milestones/')
TRAILER = re.compile(r'^Docs: none\b', re.MULTILINE)


def git(*args):
    return subprocess.run(('git', *args), check=True, capture_output=True, text=True).stdout


def names(*args):
    """Changed paths, NUL-separated so git does not quote names with spaces or non-ASCII characters."""
    return [name for name in git(*args, '-z').split('\0') if name]


def touches(paths, prefixes):
    return any(path == prefix or path.startswith(prefix) for path in paths for prefix in prefixes)


def is_user_doc(path):
    return path.startswith('docs/') and path.endswith('.md') and not path.startswith(NOT_USER_DOCS)


def needs_docs(paths, message):
    """True when the change touches app source, leaves the user docs alone and carries no trailer."""
    return touches(paths, SOURCE) and not any(map(is_user_doc, paths)) and not TRAILER.search(message)


def strip_comments(message):
    return '\n'.join(line for line in message.splitlines() if not line.startswith('#'))


def commit_msg(path):
    merge_head = git('rev-parse', '--git-path', 'MERGE_HEAD').strip()
    if subprocess.run(('test', '-e', merge_head)).returncode == 0:
        return 0
    # --no-renames: a source file moved out of SOURCE lists both its old and new path, so it still counts
    paths = names('diff', '--cached', '--name-only', '--no-renames')
    with open(path, encoding='utf-8') as fh:
        message = strip_comments(fh.read())
    if not needs_docs(paths, message):
        return 0
    print('Docs check: this commit changes app source but not the user docs (docs/).\n'
          'Add the docs change, or end the message with a trailer line:\n'
          '    Docs: none, <reason>\n'
          'Rule: App Standard, Repo & checks.', file=sys.stderr)
    return 1


def commit_needs_docs(sha):
    """needs_docs for a whole commit against its first parent (--root: a first commit against the empty tree)."""
    paths = names('diff-tree', '--root', '--no-commit-id', '--name-only', '--no-renames', '-r', sha)
    return needs_docs(paths, git('log', '-1', '--format=%B', sha))


def post_commit():
    """Warn when the commit just made, as a whole, changes app source without docs or trailer (amend, --no-verify)."""
    if len(git('rev-list', '--parents', '-n', '1', 'HEAD').split()) > 2:
        return 0  # a merge commit: the commit-msg hook skips merges too
    if commit_needs_docs('HEAD'):
        print('Docs check (post-commit): HEAD changes app source but not the user docs (docs/) and has no\n'
              '`Docs: none` trailer; an amend carries the changes already in the commit. Fix it before landing:\n'
              '    git commit --amend   (add the docs change, or end the message with  Docs: none, <reason>)\n'
              'Rule: App Standard, Repo & checks.', file=sys.stderr)
    return 0


def check_range(rev_range):
    base = rev_range.split('..', 1)[0]
    exists = subprocess.run(('git', 'cat-file', '-e', f'{base}^{{commit}}'), capture_output=True).returncode == 0
    if not base or set(base) == {'0'} or not exists:
        print(f'Docs check: no previous commit to compare with ({base or "none"}); skipped')
        return 0
    missing = []
    for sha in git('rev-list', '--no-merges', rev_range).split():
        if commit_needs_docs(sha):
            missing.append(git('log', '-1', '--format=%h %s', sha).strip())
    for line in missing:
        print(f'::warning title=Docs check::{line} changes app source without docs and without a Docs: none trailer')
    print(f'Docs check: {len(missing)} commit(s) without docs or trailer in {rev_range}')
    return 0


# ---- Page checks (doc-standard-v1 B5; App Docs Standard: User Docs and Developer Docs, Checklist) ----
# Pages with no hand-written text to verify or style: the generated references and the original pitch.
GENERATED = ('docs/developer/api-v2-reference.md', 'docs/developer/mcp-reference.md', 'docs/developer/code-reference.md')
PAGE_EXEMPT = ('docs/pitch/', 'docs/approval/', 'docs/data-model-4.0/', 'docs/img/') + NOT_USER_DOCS
AUDIENCES = ('user', 'developer')
FORBIDDEN = ((re.compile(r'\bplease\b', re.IGNORECASE), 'avoid "please"'),
             (re.compile(r'\be\.g\.|\bi\.e\.', re.IGNORECASE), 'write "for example" or "that is", not "e.g." or "i.e."'))
FENCE = re.compile(r'^(```|~~~)')
IMAGE = re.compile(r'!\[([^\]]*)\]\(([^)\s]+)')
HTML_IMAGE = re.compile(r'<img\b[^>]*>')
BAD_ALT = re.compile(r'(image|picture|screenshot) of\b', re.IGNORECASE)
STALE_AFTER = 3   # minor releases (Ulf, 2026-11-12)


def page_paths(root):
    """Every Markdown page of the docs site that has hand-written text, as paths relative to the repository root."""
    root = Path(root)
    found = []
    for path in sorted((root / 'docs').rglob('*.md')):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(PAGE_EXEMPT) or rel in GENERATED:
            continue
        found.append(rel)
    return found


def front_matter(text):
    """(fields, body) of a page: simple `key: value` lines between the first two `---` lines; no front matter gives ({}, text)."""
    if not text.startswith('---\n'):
        return {}, text
    end = text.find('\n---', 4)
    if end < 0:
        return {}, text
    fields = {}
    for line in text[4:end].splitlines():
        key, sep, value = line.partition(':')
        if sep:
            fields[key.strip()] = value.strip().strip('"\'')
    return fields, text[end + 4:].lstrip('\n')


def minor(value):
    """(major, minor) of '1.0', 'v1.0.1' or '1.2.3'; None when it is not a version."""
    found = re.match(r'v?(\d+)\.(\d+)', value or '')
    return (int(found[1]), int(found[2])) if found else None


def prose_lines(body):
    """(line number, text) of the body without fenced code blocks and inline code, so a command or a sample is never read as prose."""
    inside = False
    for number, line in enumerate(body.splitlines(), 1):
        if FENCE.match(line.strip()):
            inside = not inside
            continue
        if not inside:
            yield number, re.sub(r'`[^`]*`', '', line)


def load_terms(root):
    """Retired names from scripts/docs_terms.toml: {retired: replacement}; a missing file means none."""
    path = Path(root) / 'scripts' / 'docs_terms.toml'
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding='utf-8')).get('retired', {})


def good_alt(alt):
    alt = alt.strip()
    return bool(alt) and not BAD_ALT.match(alt) and alt.endswith(('.', '?', '!', ':'))


def check_page(rel, text, retired):
    """The findings of one page, as (rule, line, message)."""
    fields, body = front_matter(text)
    found = []
    if fields.get('audience') not in AUDIENCES:
        found.append(('front-matter', 1, 'audience must be "user" or "developer"'))
    if minor(fields.get('verified')) is None:
        found.append(('front-matter', 1, 'verified must be the app version (major.minor) the page was last checked against, for example 1.0'))
    headings = [(n, line) for n, line in prose_lines(body) if re.match(r'#{1,6} ', line)]
    h1 = [n for n, line in headings if line.startswith('# ')]
    if len(h1) != 1 or not headings or not headings[0][1].startswith('# '):
        found.append(('h1', h1[0] if h1 else 1, 'a page has exactly one H1, and it comes first'))
    if rel.startswith('docs/tutorials/') and not rel.endswith('/index.md') and not any(line.strip() == '## What next' for _, line in headings):
        found.append(('tutorial-next', 1, 'a tutorial ends with a "What next" section'))
    for n, line in prose_lines(body):
        for image in IMAGE.finditer(line):
            if not good_alt(image[1]):
                found.append(('alt-text', n, f'alt text must be a full description ending with a full stop, not starting with "Image of": "{image[1].strip()}"'))
        for tag in HTML_IMAGE.finditer(line):
            alt = re.search(r'alt="([^"]*)"', tag[0])
            if alt is None or not good_alt(alt[1]):
                found.append(('alt-text', n, 'an <img> needs alt text that is a full description ending with a full stop'))
        for pattern, message in FORBIDDEN:
            if pattern.search(line):
                found.append(('forbidden-term', n, message))
        for old, new in retired.items():
            if old in line.replace(f'(was {old})', ''):
                found.append(('retired-name', n, f'"{old}" is retired; write "{new}"'))
    names = {part for pair in re.findall(r'(?:src|srcset)="([^"]+)"|\]\(([^)\s]+)\)', body) for part in pair if part}
    for name in names:
        if name.endswith('#only-light') and name.replace('-light.', '-dark.').replace('#only-light', '#only-dark') not in names:
            found.append(('light-dark', 1, f'{name} has no dark counterpart'))
        if name.endswith('#only-dark') and name.replace('-dark.', '-light.').replace('#only-dark', '#only-light') not in names:
            found.append(('light-dark', 1, f'{name} has no light counterpart'))
    return found


def check_pages(root):
    """(path, rule, line, message) for every finding in the docs under `root`."""
    retired = load_terms(root)
    out = []
    for rel in page_paths(root):
        text = (Path(root) / rel).read_text(encoding='utf-8')
        out += [(rel, *finding) for finding in check_page(rel, text, retired)]
    return out


def latest_release():
    """(major, minor) of the newest v* tag, or None when the repository has none."""
    tags = [minor(tag) for tag in git('tag', '--list', 'v*').split()]
    tags = [tag for tag in tags if tag]
    return max(tags) if tags else None


def stale_pages(root, release):
    """(path, verified, minors behind) of the pages whose `verified` is STALE_AFTER or more minor releases behind `release`; an older major counts as stale."""
    out = []
    for rel in page_paths(root):
        fields, _ = front_matter((Path(root) / rel).read_text(encoding='utf-8'))
        seen = minor(fields.get('verified'))
        if seen is None:
            continue
        behind = release[1] - seen[1] if release[0] == seen[0] else STALE_AFTER
        if release[0] != seen[0] or behind >= STALE_AFTER:
            out.append((rel, fields['verified'], behind))
    return out


def pages(gate):
    root = Path(git('rev-parse', '--show-toplevel').strip())
    findings = check_pages(root)
    for rel, rule, line, message in findings:
        print(f'{"::error" if gate else "::warning"} file={rel},line={line},title=Docs page ({rule})::{message}')
    print(f'Docs pages: {len(findings)} finding(s) in {len(page_paths(root))} page(s)' + ('' if gate else ' (report only)'))
    return 1 if gate and findings else 0


def stale():
    root = Path(git('rev-parse', '--show-toplevel').strip())
    release = latest_release()
    if release is None:
        print('Stale pages: no release tag; skipped')
        return 0
    old = stale_pages(root, release)
    for rel, verified, behind in old:
        print(f'::warning file={rel},title=Stale page::verified {verified}, {behind} minor release(s) behind v{release[0]}.{release[1]}')
    print(f'Stale pages: {len(old)} not re-verified for {STALE_AFTER} minor releases (latest v{release[0]}.{release[1]})')
    return 0


def main(argv):
    if len(argv) == 2 and argv[0] == 'commit-msg':
        return commit_msg(argv[1])
    if len(argv) == 2 and argv[0] == 'range':
        return check_range(argv[1])
    if argv == ['post-commit']:
        return post_commit()
    if argv in (['pages'], ['pages', '--gate']):
        return pages(argv == ['pages', '--gate'])
    if argv == ['stale']:
        return stale()
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
