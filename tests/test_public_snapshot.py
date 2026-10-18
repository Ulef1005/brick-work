"""The public snapshot rules: what is left out, what is kept, and what the private scan catches."""
import pytest

from scripts.public_snapshot import PRIVATE, included, rules, tree_modes

RULES = rules("""
# comment
docs/web-ui/**
docs/brickwork/**
!docs/brickwork/api-v1.md
""")


def test_left_out_and_kept():
    assert not included('docs/web-ui/readme.md', RULES)
    assert not included('docs/web-ui/ux-concept/concept.md', RULES)
    assert not included('docs/brickwork/design-diff-49a.md', RULES)
    assert included('docs/brickwork/api-v1.md', RULES)
    assert included('docs/adr/0001-standalone-app.md', RULES)
    assert included('brickwork/core/schema.sql', RULES)


def test_private_patterns(tmp_path):
    for text in ('ssh someone@192.168.1.20', '/Users/someone/x', '/home/user/x', 'op://vault/item/field'):
        assert PRIVATE.search(text), text
    for text in ('version 10.1.2', 'https://example.org', 'Lego test set', 'users/{token}/setlists',
                 'Copyright (c) 2026 A. Maintainer', "REMOTE_ADDR': '10.0.0.9'",
                 'https://github.com/users/someone/projects/1'):
        assert not PRIVATE.search(text), text
    # The maintainer's own patterns come from a private file, never from this repository.
    from brickwork.demo.privacy import pattern
    extra = tmp_path / 'patterns.txt'
    extra.write_text('# private\nexample-home\\.test\n\\bstaging-box\\b\n')
    own = pattern(extra)
    assert own.search('https://lego.example-home.test/x') and own.search('on staging-box now')
    assert own.search('/home/user/x') and not own.search('https://example.org')


def test_rules_file_keeps_the_api_contract():
    from pathlib import Path
    shipped = rules((Path(__file__).resolve().parents[1] / 'scripts' / 'public-snapshot.txt').read_text())
    for path in ('docs/brickwork/api-v1.md', 'docs/brickwork/openapi-v1.yaml', 'docs/brickwork/cutover-4.11j.md'):
        assert included(path, shipped), path
    assert not included('docs/web-ui/readme.md', shipped)


def test_tree_modes_keep_executables_and_refuse_links():
    # The first snapshot lost the exec bit of scripts/check.sh, bin/brickwork and entrypoint.sh.
    listing = b'100644 blob aa\tREADME.md\x00100755 blob bb\tscripts/check.sh\x00'
    assert tree_modes(listing) == {'README.md': '100644', 'scripts/check.sh': '100755'}
    with pytest.raises(SystemExit):
        tree_modes(b'120000 blob cc\tlink\x00')


def test_tracked_tree_holds_no_private_material():
    # The repository is public: every landed commit is published, so the gate scans the whole tracked
    # tree (generic patterns on public CI, plus the maintainer's own through BW_PRIVATE_PATTERNS_FILE).
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    listed = subprocess.run(['git', '-C', str(root), '-c', 'core.fsmonitor=false', 'ls-files', '-z'],
                            check=True, capture_output=True).stdout.decode().split('\0')
    skip = {'scripts/public_snapshot.py', 'tests/test_public_snapshot.py', 'brickwork/demo/privacy.py'}
    hits = []
    for name in listed:
        if not name or name in skip:
            continue
        try:
            text = (root / name).read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        hits += [f'{name}:{n}' for n, line in enumerate(text.splitlines(), 1) if PRIVATE.search(line)]
    assert not hits, hits[:20]
