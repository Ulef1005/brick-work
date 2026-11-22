"""The approved dark round (#512): catalogue pictures are blended onto the light grey tile in dark (`mix-blend-mode: multiply`), the user's
own photos never are. Part Spotter draws "Your photo" as a `.tile` inside its `.b-prime` scope, where b-prime.css blends every tile image,
so each own photo carries `inv-own` and bw-inventory-b.css lifts the blend for it. Copy photos are `.bc-thumb` images, which no blend
rule reaches."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / 'static' / 'web' / 'toni'


def test_every_your_photo_tile_is_marked_as_an_own_photo():
    source = (STATIC / 'bw-inventory.js').read_text()
    calls = re.findall(r"tile\(piece\.photo, 'Your photo'(?:, [^)]*)?\)", source)
    assert calls, 'Part Spotter draws the photo with tile()'
    assert all('inv-own' in call for call in calls), calls


def test_own_photos_are_not_blended():
    css = (STATIC / 'bw-inventory-b.css').read_text()
    assert re.search(r'#bw-inventory(?::not\(#_\)){4} \.tile\.inv-own img \{mix-blend-mode:normal\}', css)


def test_no_blend_rule_reaches_a_copy_photo():
    for sheet in list(STATIC.glob('*.css')) + [ROOT / 'static' / 'brickwork' / 'b-prime.css']:
        for rule in re.findall(r'[^{}]*\{[^}]*mix-blend-mode:multiply[^}]*\}', sheet.read_text()):
            assert 'bc-thumb' not in rule and 'bc-photo' not in rule, (sheet.name, rule)
