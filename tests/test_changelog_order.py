"""The task entries belong under the changelog and unreleased title."""
from pathlib import Path


def test_task_entries_follow_unreleased_title_newest_first():
    lines = (Path(__file__).parents[1] / 'CHANGELOG.md').read_text().splitlines()
    headings = [line for line in lines if line.startswith('#')]
    assert headings[:10] == [
        '# Changelog',
        '## Unreleased',
        '## Brick Work 0.8.1 (schema 4.1) · 2026-11-04',
        '## Brick Work 0.8.0 (schema 4.1) · 2026-11-03',
        '## Brick Work 0.7.0 (schema 4.1) · 2026-11-03',
        '## Brick Work 0.6.0 (schema 4.0, API v2) · 2026-10-28',
        '## Brick Work 0.5.0 (first public release) · 2026-10-18',
        '### All changes in this release',
        '## 4.6d-1 · Collection design comparison (partial)',
        '## 4.5v · list cost and quiet name refresh',
    ]
    assert lines[0] == '# Changelog'
    assert headings.count('# Changelog') == 1
