"""The brickwork-design skill (.claude/skills/brickwork-design): it points at the design export in `design/` and the brand assets in
`static/brickwork/` in place and keeps no copy of them, so it cannot drift from what the repo holds. Only the kit's own documents, found
nowhere else, sit beside it in `reference/`."""
import hashlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / '.claude' / 'skills' / 'brickwork-design'
TEXT = (SKILL / 'SKILL.md').read_text(encoding='utf-8')


def _tracked():
    out = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, capture_output=True, check=True).stdout.decode().split('\0')
    return [ROOT / f for f in out if f]


def test_the_skill_has_its_frontmatter_and_builds_on_toni():
    front = re.match(r'---\nname: brickwork-design\ndescription: (.+)\n---\n', TEXT)
    assert front and 'Brick Work' in front[1]
    assert 'toni-design' in TEXT                      # builds on the Toni skill instead of repeating its rules


def test_the_skill_keeps_no_copy_of_a_file_the_repo_holds():
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    elsewhere = {digest(p): p for p in _tracked() if p.is_file() and SKILL not in p.parents}
    copies = {p.relative_to(SKILL).as_posix(): elsewhere[d].relative_to(ROOT).as_posix()
              for p in SKILL.rglob('*') if p.is_file() and (d := digest(p)) in elsewhere}
    assert copies == {}


def test_every_path_the_skill_names_exists():
    named = set(re.findall(r'`((?:design|static|docs|tests|scripts)/[^`<>{}*]+|[A-Z][\w-]*\.md)`', TEXT))
    assert {'design/tokens-v2.css', 'design/frames.json', 'design/frames/', 'design/sections/', 'design/test-data/',
            'static/brickwork/', 'static/brickwork/icons-ui/', 'static/fonts/', 'DESIGN-CHECK.md'} <= named
    for path in named:
        assert (ROOT / path).exists(), path
    for page in re.findall(r'`(design/(?:BW [\w ]+|Brick Work [\w ]+)\.dc\.html)`', TEXT):
        assert (ROOT / page).is_file(), page
    for ref in re.findall(r'`(reference/[^`]+)`', TEXT):
        assert (SKILL / ref).exists(), ref


def test_the_catalogue_images_stay_out_of_git():
    for folder in ('parts', 'sets', 'minifigs', 'photos'):
        probe = f'design/assets/data/{folder}/x.jpg'
        assert subprocess.run(['git', 'check-ignore', '-q', probe], cwd=ROOT).returncode == 0, probe
    assert not [p for p in _tracked() if p.suffix == '.jpg' and SKILL in p.parents]
