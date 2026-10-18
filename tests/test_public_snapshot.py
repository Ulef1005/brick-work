"""The public snapshot rules: what is left out, what is kept, and what the private scan catches."""
from scripts.public_snapshot import PRIVATE, included, rules

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


def test_private_patterns():
    for text in ('https://lego.example-home.test/x', 'ssh someone@192.168.1.20', '/Users/someone/x', '/home/user/x',
                 'op://vault/item/field', 'on test instance now'):
        assert PRIVATE.search(text), text
    for text in ('version 10.1.2', 'https://example.org', 'Lego test set', 'users/{token}/setlists',
                 'Copyright (c) 2026 Ulf Weihbold', "REMOTE_ADDR': '10.0.0.9'"):
        assert not PRIVATE.search(text), text


def test_rules_file_keeps_the_api_contract():
    from pathlib import Path
    shipped = rules((Path(__file__).resolve().parents[1] / 'scripts' / 'public-snapshot.txt').read_text())
    for path in ('docs/brickwork/api-v1.md', 'docs/brickwork/openapi-v1.yaml', 'docs/brickwork/cutover-4.11j.md'):
        assert included(path, shipped), path
    assert not included('docs/web-ui/readme.md', shipped)
