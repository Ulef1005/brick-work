"""The brickwork-design skill (.claude/skills/brickwork-design): it points at the P2 layout in `design/` (the export in `design/sources/`,
the screens, the logo, app icon and icons) in place and keeps no copy of it, so it cannot drift from what the repo holds. Only the kit's
own documents, found nowhere else, sit beside it in `reference/`. The old flat paths are gone (#159)."""
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


def test_the_skill_has_its_frontmatter_and_its_own_base():
    """Brick Work left Toni's World (ADR 0022, #158): its own base and tokens, no sub-brand, no toni-design parent."""
    front = re.match(r'---\nname: brickwork-design\ndescription: (.+)\n---\n', TEXT)
    assert front and 'Brick Work' in front[1]
    assert 'toni-design' not in TEXT and 'sub-brand' not in TEXT
    assert 'design/tokens/tokens.css' in TEXT and 'design/tokens/brickwork-tokens.css' in TEXT


def test_the_skill_keeps_no_copy_of_a_file_the_repo_holds():
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    elsewhere = {digest(p): p for p in _tracked() if p.is_file() and SKILL not in p.parents}
    copies = {p.relative_to(SKILL).as_posix(): elsewhere[d].relative_to(ROOT).as_posix()
              for p in SKILL.rglob('*') if p.is_file() and (d := digest(p)) in elsewhere}
    assert copies == {}


def test_every_path_the_skill_names_exists():
    named = set(re.findall(r'`((?:design|static|docs|tests|scripts)/[^`<>{}*]+|[A-Z][\w-]*\.md)`', TEXT))
    assert {'design/sources/tokens-v2.css', 'design/sources/frames.json', 'design/sources/index.html', 'design/screens/',
            'design/screens/approval/', 'design/sources/test-data/', 'design/sources/assets/data/placeholders/', 'design/logo/',
            'design/app-icon/', 'design/components/icons/', 'static/brickwork/', 'static/fonts/', 'design/DESIGN-CHECK.md'} <= named
    for path in named:
        assert (ROOT / path).exists(), path
    old = ('design/frames', 'design/sections', 'design/approval', 'design/test-data', 'design/assets', 'design/tokens-v2')
    assert not [path for path in re.findall(r'design/[\w./-]+', TEXT) if path.startswith(old)]
    assert '`DESIGN-CHECK.md`' not in TEXT and '`design/frames.json`' not in TEXT
    for page in re.findall(r'`(design/sources/(?:BW [\w ]+|Brick Work [\w ]+)\.dc\.html)`', TEXT):
        assert (ROOT / page).is_file(), page
    for ref in re.findall(r'`(reference/[^`]+)`', TEXT):
        assert (SKILL / ref).exists(), ref


def test_the_catalogue_images_stay_out_of_git():
    for folder in ('parts', 'sets', 'minifigs', 'photos'):
        probe = f'design/sources/assets/data/{folder}/x.jpg'
        assert subprocess.run(['git', 'check-ignore', '-q', probe], cwd=ROOT).returncode == 0, probe
    assert not [p for p in _tracked() if p.suffix == '.jpg' and SKILL in p.parents]
