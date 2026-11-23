"""The approved dark round (#512): catalogue pictures are blended onto the light grey tile in dark (`mix-blend-mode: multiply`), the user's
own photos never are. Part Spotter draws "Your photo" as a `.tile` inside its `.b-prime` scope, where b-prime.css blends every tile image,
so each own photo carries `inv-own` and bw-inventory-b.css lifts the blend for it. Copy photos are `.bc-thumb` images; every blend rule
targets a catalogue picture's container only, so none reaches them."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / 'static' / 'web' / 'toni'
SHEETS = sorted(STATIC.glob('*.css')) + [ROOT / 'static' / 'brickwork' / 'b-prime.css']
# The containers of a catalogue picture; a blend rule's image must sit directly in one of them.
CATALOGUE = re.compile(r'\.(tile|bc-picture|check-picture|jump-image) img(:where\(.*\))?$')   # the legacy guard may follow


def split(selectors):
    """A selector list split at its top-level commas (not the ones inside :is() or :not())."""
    parts, depth, start = [], 0, 0
    for i, char in enumerate(selectors):
        depth += char == '('
        depth -= char == ')'
        if char == ',' and depth == 0:
            parts.append(selectors[start:i].strip())
            start = i + 1
    return parts + [selectors[start:].strip()]


def blend_rules():
    for sheet in SHEETS:
        text = re.sub(r'/\*.*?\*/', '', sheet.read_text(), flags=re.S)
        for selectors, body in re.findall(r'([^{}]+)\{([^{}]*)\}', text):
            mode = re.search(r'mix-blend-mode\s*:\s*([a-z-]+)', body)
            if mode:
                yield sheet.name, split(selectors), mode.group(1)


def test_every_your_photo_is_marked_as_an_own_photo():
    source = (STATIC / 'bw-inventory.js').read_text()
    lines = [line for line in source.splitlines() if re.search(r'''['"]Your photo['"]''', line) and 'tile(' in line]
    assert lines, 'Part Spotter draws "Your photo" with tile()'
    for line in lines:
        assert line.count('tile(') == line.count('inv-own'), line.strip()[:160]


def test_own_photos_are_not_blended():
    lifted = [s for name, selectors, mode in blend_rules() if mode == 'normal' and name == 'bw-inventory-b.css' for s in selectors]
    assert any(re.fullmatch(r'#bw-inventory(?::not\(#_\)){4} \.tile\.inv-own img', s) for s in lifted), lifted


def test_every_blend_targets_a_catalogue_picture_only():
    """A broad rule (`#bw-collection img`, `.bc-photos img`) would reach copy photos: every multiply rule must end in a catalogue picture's
    container, never a copy photo's (`.bc-thumb`, `.bc-photo-row`) or a bare `img`."""
    found = 0
    for name, selectors, mode in blend_rules():
        if mode != 'multiply':
            continue
        for selector in selectors:
            found += 1
            assert CATALOGUE.search(selector), (name, selector)
            assert not re.search(r'bc-thumb|bc-photo', selector), (name, selector)
    assert found
