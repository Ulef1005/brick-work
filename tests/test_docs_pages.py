"""The page checks of scripts/check_docs.py (App Docs Standard: User Docs and Developer Docs, Checklist): each rule fails a seeded bad page."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_docs", ROOT / "scripts/check_docs.py")
check_docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_docs)

GOOD = """---
audience: user
verified: 1.0
---

# Check a set's parts

Select **Start**.

![The Add screen with two call-outs.](../img/tutorials/x-light.png#only-light)
![The Add screen with two call-outs.](../img/tutorials/x-dark.png#only-dark)

## What next

- [Next](next.md)
"""


def rules(rel, text, retired=None):
    return {rule for rule, _, _ in check_docs.check_page(rel, text, retired or {})}


def test_a_good_page_has_no_findings():
    assert check_docs.check_page('docs/tutorials/x.md', GOOD, {}) == []


@pytest.mark.parametrize(('text', 'rule'), [
    (GOOD.replace('audience: user\n', ''), 'front-matter'),
    (GOOD.replace('audience: user', 'audience: everyone'), 'front-matter'),
    (GOOD.replace('verified: 1.0\n', ''), 'front-matter'),
    (GOOD.replace('verified: 1.0', 'verified: soon'), 'front-matter'),
    (GOOD.replace('# Check a set\'s parts', '## Check a set\'s parts'), 'h1'),
    (GOOD + '\n# A second H1\n', 'h1'),
    (GOOD.replace('![The Add screen with two call-outs.](../img/tutorials/x-light.png#only-light)', '![](../img/tutorials/x-light.png#only-light)'), 'alt-text'),
    (GOOD.replace('The Add screen with two call-outs.', 'Image of the Add screen.', 1), 'alt-text'),
    (GOOD.replace('The Add screen with two call-outs.', 'The Add screen', 1), 'alt-text'),
    (GOOD + '\n<img src="a.png" alt="Image of a set">\n', 'alt-text'),
    (GOOD + '\n<img src="a.png">\n', 'alt-text'),
    (GOOD.replace('Select **Start**.', 'Please select **Start**.'), 'forbidden-term'),
    (GOOD.replace('Select **Start**.', 'Select a set, e.g. a small one.'), 'forbidden-term'),
    (GOOD.replace('Select **Start**.', 'Select **Start** in Check Set Parts.'), 'retired-name'),
    (GOOD.replace('![The Add screen with two call-outs.](../img/tutorials/x-dark.png#only-dark)\n', ''), 'light-dark'),
    (GOOD.replace('![The Add screen with two call-outs.](../img/tutorials/x-light.png#only-light)\n', ''), 'light-dark'),
    (GOOD.replace('## What next', '## Afterwards'), 'tutorial-next'),
])
def test_each_rule_fails_its_seeded_page(text, rule):
    assert rule in rules('docs/tutorials/x.md', text, {'Check Set Parts': 'Set Inspector'})


def test_a_how_to_needs_no_what_next_section():
    assert 'tutorial-next' not in rules('docs/how-to/x.md', GOOD.replace('## What next', '## Afterwards'))


def test_code_blocks_and_inline_code_are_not_prose():
    text = GOOD.replace('Select **Start**.', 'Run `curl -s e.g.` then:\n\n```sh\necho "please" e.g.\n# Not a heading\n```')
    assert check_docs.check_page('docs/how-to/x.md', text, {}) == []


def test_a_retired_name_may_appear_in_its_was_note():
    assert 'retired-name' not in rules('docs/how-to/x.md', GOOD.replace('Select **Start**.', 'Set Inspector (was Check Set Parts).'),
                                       {'Check Set Parts': 'Set Inspector'})


def test_generated_pages_the_pitch_and_the_records_are_not_checked(tmp_path):
    for rel in ('docs/developer/api-v2-reference.md', 'docs/pitch/README.md', 'docs/adr/0001.md', 'docs/milestones/m.md'):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text('no front matter, no heading')
    assert check_docs.page_paths(tmp_path) == []
    assert check_docs.check_pages(tmp_path) == []


def test_check_pages_reads_the_retired_names_file(tmp_path):
    (tmp_path / 'docs/how-to').mkdir(parents=True)
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'scripts/docs_terms.toml').write_text('[retired]\n"Check Set Parts" = "Set Inspector"\n')
    (tmp_path / 'docs/how-to/x.md').write_text(GOOD.replace('Select **Start**.', 'Open Check Set Parts.'))
    found = check_docs.check_pages(tmp_path)
    assert [(rel, rule) for rel, rule, _, _ in found] == [('docs/how-to/x.md', 'retired-name')]


@pytest.mark.parametrize(('verified', 'stale'), [('1.4', False), ('1.3', False), ('1.2', True), ('1.0', True), ('0.9', True)])
def test_a_page_not_reverified_for_three_minor_releases_is_stale(tmp_path, verified, stale):
    (tmp_path / 'docs/how-to').mkdir(parents=True)
    (tmp_path / 'docs/how-to/x.md').write_text(GOOD.replace('verified: 1.0', f'verified: {verified}'))
    assert bool(check_docs.stale_pages(tmp_path, (1, 5))) is stale
    # 1.5 is "three behind" 1.2: the third minor release after it
    assert check_docs.stale_pages(tmp_path, (1, 5)) == ([('docs/how-to/x.md', verified, 5 - int(verified.split('.')[1]) if verified.startswith('1.') else 3)] if stale else [])


def test_the_pages_command_fails_only_with_gate_and_findings(tmp_path, monkeypatch, capsys):
    (tmp_path / 'docs/how-to').mkdir(parents=True)
    (tmp_path / 'docs/how-to/x.md').write_text('no front matter')
    monkeypatch.setattr(check_docs, 'git', lambda *args: str(tmp_path) + '\n')
    assert check_docs.pages(gate=False) == 0
    assert check_docs.pages(gate=True) == 1
    assert 'front-matter' in capsys.readouterr().out


def test_the_repository_pages_run_without_crashing():
    check_docs.check_pages(ROOT)
