"""The demo's own pictures: original flat illustrations for the invented collection (design/demo-art/).

    python scripts/demo_art.py            # build the world, draw every picture it needs, write design/demo-art/ (PNGs + manifest.json)
    python scripts/demo_art.py --check    # exit 1 when a picture the world needs is missing from the manifest

Every picture is drawn here, from shapes, with Pillow (a runtime dependency already): a brick-built scene for each set, a generic figure for each
minifigure (in the colours of its parts), a flat drawing of the part's shape in its colour for each part. Nothing is taken from, traced from or
derived from BrickLink, Rebrickable, Brickset or LEGO pictures. The style is the app's: flat fills, a hairline in a darker shade of the fill,
no shadows, on a transparent ground. The drawing is deterministic (no randomness). `brickwork/demo/showcase.py` stores the pictures through the
app's own `picture` table (source "Demo illustration"); see design/demo-art/README.md.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ART = ROOT / 'design' / 'demo-art'
SCALE = 4                                           # drawn at 4x and reduced: anti-aliased edges without a drawing library

# The app's warm neutrals (design/tokens) and a few brick colours for the scenes.
INK = (69, 65, 59)
SKY = (236, 232, 223)
BRICKS = {'red': (201, 26, 9), 'blue': (13, 105, 171), 'yellow': (242, 205, 55), 'green': (35, 120, 65), 'orange': (226, 99, 30),
          'tan': (215, 197, 153), 'grey': (160, 165, 169), 'dark': (99, 95, 98), 'white': (244, 244, 240), 'brown': (88, 42, 18), 'teal': (0, 133, 143)}
SCENE_COLOURS = [v for k, v in BRICKS.items() if k != 'white']   # white bodies vanish on the app's light surface


def edge_of(fill):
    """The hairline: a darker shade of the fill, darker still for the palest fills so a white part shows on the white tile."""
    return shade(fill, 0.55 if sum(fill) > 600 else 0.72)


def shade(rgb, factor):
    return tuple(max(0, min(255, round(c * factor))) for c in rgb)


def hexrgb(text):
    text = (text or '').lstrip('#')
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4)) if re.fullmatch('[0-9a-fA-F]{6}', text) else (160, 165, 169)


class Canvas:
    def __init__(self, width, height):
        from PIL import Image, ImageDraw
        self.size = (width, height)
        self.image = Image.new('RGBA', (width * SCALE, height * SCALE), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.image)

    def s(self, *values):
        return [round(v * SCALE) for v in values]

    def rect(self, x, y, w, h, fill, radius=0, line=True):
        box = self.s(x, y, x + w, y + h)
        edge = edge_of(fill) if line else None
        if radius:
            self.draw.rounded_rectangle(box, radius * SCALE, fill=fill, outline=edge, width=SCALE // 2 or 1)
        else:
            self.draw.rectangle(box, fill=fill, outline=edge, width=SCALE // 2 or 1)

    def poly(self, points, fill, line=True):
        pts = [tuple(self.s(*p)) for p in points]
        self.draw.polygon(pts, fill=fill, outline=edge_of(fill) if line else None, width=SCALE // 2 or 1)

    def ellipse(self, cx, cy, rx, ry, fill, line=True):
        self.draw.ellipse(self.s(cx - rx, cy - ry, cx + rx, cy + ry), fill=fill, outline=edge_of(fill) if line else None, width=SCALE // 2 or 1)

    def save(self, path, fit=False, out=None, colours=96):
        from PIL import Image
        image = self.image
        if fit:   # a part is cropped to its drawing and centred, so it fills the frame whatever its shape
            box = image.getbbox()
            margin = 14 * SCALE
            side = max(box[2] - box[0], box[3] - box[1]) + 2 * margin
            framed = Image.new('RGBA', (side, side), (0, 0, 0, 0))
            framed.paste(image.crop(box), ((side - (box[2] - box[0])) // 2, (side - (box[3] - box[1])) // 2))
            image = framed.resize(self.image.size, Image.Resampling.LANCZOS)
        small = image.resize((out, out) if out else self.size, Image.Resampling.LANCZOS)
        small.quantize(colors=colours, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE).save(path, optimize=True)


# ---------- sets: a scene per motif ----------

def ground(c, y=300):
    c.rect(20, y, 440, 14, shade(BRICKS['green'], 1.15), line=False)
    c.rect(20, y + 14, 440, 8, shade(BRICKS['green'], 0.9), line=False)


def windows(c, x, y, cols, rows, w=26, h=30, gap=16, fill=BRICKS['white']):
    for i in range(cols):
        for j in range(rows):
            c.rect(x + i * (w + gap), y + j * (h + gap), w, h, fill, radius=2)
            c.rect(x + i * (w + gap) + w / 2 - 1, y + j * (h + gap), 2, h, shade(fill, 0.8), line=False)


def house(c, body, roof, flat=False, sign=False):
    ground(c)
    c.rect(110, 170, 260, 130, body)
    if flat:
        c.rect(100, 156, 280, 20, roof)
    else:
        c.poly([(96, 172), (240, 78), (384, 172)], roof)
        c.rect(300, 90, 28, 52, shade(body, 0.85))
    windows(c, 134, 196, 2, 1)
    windows(c, 290, 196, 2, 1)
    c.rect(222, 230, 36, 70, BRICKS['brown'], radius=2)
    if sign:
        c.rect(170, 120, 140, 28, BRICKS['red'])
        c.rect(180, 129, 120, 10, BRICKS['white'], line=False)


def tower(c, body, top):
    ground(c)
    c.rect(180, 70, 120, 230, body)
    c.rect(168, 56, 144, 24, top)
    for j in range(4):
        windows(c, 204, 100 + j * 48, 2, 1, w=22, h=26, gap=18)
    c.rect(226, 250, 28, 50, BRICKS['brown'], radius=2)
    c.rect(238, 30, 4, 28, INK, line=False)


def lighthouse(c, body, top):
    ground(c)
    c.poly([(190, 300), (210, 110), (270, 110), (290, 300)], body)
    for k, y in enumerate((150, 210, 260)):
        c.poly([(210 - (y - 110) * 0.1, y), (270 + (y - 110) * 0.1, y), (272 + (y - 110) * 0.1, y + 22), (208 - (y - 110) * 0.1, y + 22)], top if k % 2 == 0 else BRICKS['white'], line=False)
    c.rect(200, 84, 80, 28, BRICKS['dark'])
    c.rect(214, 52, 52, 34, BRICKS['yellow'])
    c.poly([(204, 52), (240, 26), (276, 52)], top)
    c.rect(150, 300, 180, 10, BRICKS['grey'], line=False)


def castle(c, body, flag):
    ground(c)
    c.rect(90, 150, 300, 150, body)
    for x in (70, 340):
        c.rect(x, 90, 70, 210, shade(body, 0.92))
        for k in range(4):
            c.rect(x + k * 20 - 2 + (2 if k == 0 else 0), 74, 16, 18, shade(body, 0.92))
        c.rect(x + 22, 130, 26, 40, shade(body, 0.55), radius=10)
    for k in range(7):
        c.rect(150 + k * 26, 134, 18, 18, body)
    c.rect(200, 200, 80, 100, BRICKS['brown'], radius=40)
    c.rect(238, 40, 3, 36, INK, line=False)
    c.poly([(241, 40), (278, 52), (241, 64)], flag)


def vehicle(c, body, cab, kind='truck'):
    ground(c)
    if kind == 'car':
        c.rect(70, 200, 340, 62, body, radius=14)
        c.poly([(150, 202), (200, 140), (320, 140), (360, 202)], shade(body, 1.08))
        c.poly([(170, 200), (206, 154), (250, 154), (250, 200)], BRICKS['white'], line=False)
        c.poly([(262, 200), (262, 154), (312, 154), (342, 200)], BRICKS['white'], line=False)
        wheels = (130, 350)
    else:
        c.rect(60, 150, 240, 110, body)
        c.rect(300, 180, 110, 80, cab)
        c.poly([(300, 180), (340, 140), (380, 140), (410, 180)], cab)
        c.poly([(330, 176), (352, 150), (376, 150), (396, 176)], BRICKS['white'], line=False)
        wheels = (120, 220, 350)
    for x in wheels:
        c.ellipse(x, 268, 34, 34, INK)
        c.ellipse(x, 268, 14, 14, BRICKS['grey'])


def crane(c, body, arm):
    ground(c)
    c.rect(100, 232, 280, 46, body)
    c.rect(130, 190, 90, 44, arm)
    c.poly([(210, 190), (390, 50), (402, 62), (232, 200)], arm)
    c.rect(392, 60, 3, 90, INK, line=False)
    c.rect(384, 148, 20, 14, BRICKS['red'])
    for x in (140, 240, 340):
        c.ellipse(x, 282, 22, 22, INK)


def ship(c, hull, sail, sails=1):
    c.rect(0, 250, 480, 110, shade(BRICKS['blue'], 1.25), line=False)
    c.poly([(70, 220), (410, 220), (360, 290), (120, 290)], hull)
    for k in range(sails):
        x = 190 + k * 100 - (sails - 1) * 50
        c.rect(x, 70, 5, 152, BRICKS['brown'], line=False)
        c.poly([(x + 8, 80), (x + 78, 190), (x + 8, 190)], sail)
    c.rect(78, 232, 300, 8, shade(hull, 0.8), line=False)


def spaceship(c, body, wing):
    c.poly([(40, 190), (240, 120), (440, 190), (240, 250)], body)
    c.poly([(150, 150), (110, 70), (190, 130)], wing)
    c.poly([(150, 230), (110, 310), (190, 250)], wing)
    c.ellipse(260, 186, 44, 26, BRICKS['white'])
    c.ellipse(262, 186, 22, 14, BRICKS['blue'])
    c.poly([(40, 190), (14, 176), (14, 204)], BRICKS['orange'])


def train(c, body, cab):
    ground(c, 292)
    c.rect(30, 288, 420, 10, INK, line=False)
    c.rect(300, 140, 130, 130, body)
    c.rect(330, 100, 70, 50, cab)
    c.rect(180, 170, 124, 100, shade(body, 1.1))
    c.rect(210, 120, 28, 52, INK)
    c.rect(40, 190, 124, 80, cab)
    for x in (70, 130, 220, 270, 330, 390):
        c.ellipse(x, 276, 16, 16, INK)


def volcano(c, rock, lava):
    ground(c)
    c.poly([(60, 300), (200, 110), (280, 110), (420, 300)], rock)
    c.poly([(200, 110), (240, 150), (280, 110)], lava)
    c.poly([(226, 150), (236, 230), (252, 190), (262, 250), (270, 150)], lava, line=False)
    c.rect(320, 250, 50, 50, BRICKS['white'])
    c.poly([(310, 252), (345, 222), (380, 252)], BRICKS['orange'])


def dome(c, body, cap):
    ground(c)
    c.rect(130, 190, 220, 110, body)
    c.ellipse(240, 190, 110, 100, cap)
    c.rect(130, 190, 220, 110, body)
    c.draw.pieslice(c.s(130, 90, 350, 290), 180, 360, fill=cap, outline=shade(cap, 0.72), width=SCALE // 2)
    c.rect(228, 100, 24, 80, shade(cap, 0.7))
    c.rect(214, 230, 52, 70, BRICKS['brown'], radius=3)


def tree(c, leaf, trunk):
    ground(c)
    c.rect(222, 190, 36, 110, trunk)
    for cx, cy, r in ((240, 130, 80), (180, 170, 54), (300, 170, 54), (240, 80, 50)):
        c.ellipse(cx, cy, r, r, leaf)
    c.rect(380, 230, 60, 70, BRICKS['tan'])
    c.poly([(370, 232), (410, 196), (450, 232)], BRICKS['brown'])


def turbine(c, body, blade):
    ground(c)
    c.poly([(230, 300), (240, 120), (250, 300)], body)
    c.ellipse(240, 116, 12, 12, BRICKS['dark'])
    for dx, dy in ((0, -100), (88, 52), (-88, 52)):
        c.poly([(240, 116), (240 + dx * 0.9 - 8, 116 + dy * 0.9), (240 + dx, 116 + dy), (240 + dx * 0.9 + 8, 116 + dy * 0.9)], blade)


def mill(c, body, blade):
    house(c, body, BRICKS['brown'])
    c.rect(236, 70, 8, 104, blade)
    c.rect(188, 118, 104, 8, blade)


def stalls(c, body, awning):
    ground(c)
    for k, x in enumerate((50, 190, 330)):
        c.rect(x, 190, 100, 110, shade(body, 1 - 0.06 * k))
        for j in range(5):
            c.rect(x + j * 20, 160, 20, 36, awning if (j + k) % 2 == 0 else BRICKS['white'])
        c.rect(x + 14, 232, 72, 20, BRICKS['brown'])


def tray(c, body, accent):
    c.rect(60, 120, 360, 160, body, radius=12)
    for j in range(2):
        for i in range(3):
            c.rect(86 + i * 112, 142 + j * 66, 92, 50, shade(body, 0.86), radius=6)
    c.ellipse(240, 160, 22, 22, accent)


MOTIFS = [
    ('lighthouse', lambda c, p: lighthouse(c, p[0], p[1])),
    ('galleon|ship|cutter|cove|titanic|ocean|explorer boat', lambda c, p: ship(c, p[0], p[1], 1)),
    ('volcano', lambda c, p: volcano(c, p[0], p[1])),
    ('moon base|observatory|dome', lambda c, p: dome(c, p[0], p[1])),
    ('castle|keep|fortress|gatehouse|stable|outpost|colosseum|king|monarch|falcon.s fortress', lambda c, p: castle(c, p[0], p[1])),
    ('cruiser|falcon|galaxy|asteroid|starlight|spaceship|rover', lambda c, p: spaceship(c, p[0], p[1])),
    ('express|train|depot|locomotive', lambda c, p: train(c, p[0], p[1])),
    ('crane', lambda c, p: crane(c, p[0], p[1])),
    ('buggy|batmobile|ferrari|lamborghini|wheel|car\\b|racing|daytona', lambda c, p: vehicle(c, p[0], p[1], 'car')),
    ('transport|truck|caravan|cargo', lambda c, p: vehicle(c, p[0], p[1], 'truck')),
    ('turbine', lambda c, p: turbine(c, p[0], p[1])),
    ('mill', lambda c, p: mill(c, p[0], p[1])),
    ('market|square', lambda c, p: stalls(c, p[0], p[1])),
    ('jungle|tree|bonsai|forest|garden', lambda c, p: tree(c, BRICKS['green'], BRICKS['brown'])),
    ('tray', lambda c, p: tray(c, p[0], p[1])),
    ('tower|fire|skyline|eiffel', lambda c, p: tower(c, p[0], p[1])),
    ('diner', lambda c, p: house(c, p[0], p[1], flat=True, sign=True)),
]


def set_picture(number, name, path):
    text = name.lower()
    seed = sum(map(ord, number))
    body = SCENE_COLOURS[seed % len(SCENE_COLOURS)]
    accent = SCENE_COLOURS[(seed // 3 + 4) % len(SCENE_COLOURS)]
    if body == accent:
        accent = BRICKS['red']
    motif = next((draw for pattern, draw in MOTIFS if re.search(pattern, text)), lambda c, p: house(c, p[0], p[1]))
    canvas = Canvas(480, 360)
    motif(canvas, (body, accent))
    canvas.save(path)


# ---------- gear, books, catalogs ----------

def object_picture(kind, number, name, path):
    seed = sum(map(ord, number))
    colour = SCENE_COLOURS[seed % len(SCENE_COLOURS)]
    c = Canvas(480, 360)
    if kind == 'book':
        c.rect(150, 60, 180, 240, colour, radius=6)
        c.rect(150, 60, 22, 240, shade(colour, 0.8), line=False)
        c.rect(190, 100, 120, 14, BRICKS['white'], line=False)
        c.rect(190, 128, 90, 10, BRICKS['white'], line=False)
        c.rect(200, 220, 70, 50, shade(colour, 1.2))
    elif kind == 'catalog':
        c.rect(120, 80, 150, 210, BRICKS['white'], radius=4)
        c.rect(210, 60, 150, 210, colour, radius=4)
        for k in range(4):
            c.rect(232, 92 + k * 40, 106, 22, BRICKS['white'], line=False)
    else:
        text = name.lower()
        if 'lamp' in text:
            c.rect(190, 270, 100, 20, INK, radius=4)
            c.rect(236, 130, 8, 140, INK, line=False)
            c.poly([(170, 140), (310, 140), (280, 70), (200, 70)], colour)
        elif 'tray' in text:
            tray(c, colour, BRICKS['yellow'])
        elif 'case' in text:
            c.rect(100, 120, 280, 150, colour, radius=14)
            c.rect(210, 96, 60, 28, shade(colour, 0.8), radius=8)
            c.rect(120, 170, 240, 8, shade(colour, 0.8), line=False)
        elif 'stand' in text:
            c.rect(110, 90, 260, 18, colour)
            c.rect(110, 108, 14, 120, shade(colour, 0.8))
            c.rect(356, 108, 14, 120, shade(colour, 0.8))
            c.rect(150, 40, 60, 50, BRICKS['red']); c.rect(260, 40, 60, 50, BRICKS['yellow'])
        else:
            c.rect(180, 160, 120, 40, colour, radius=8)
            c.poly([(300, 168), (380, 140), (380, 220), (300, 192)], shade(colour, 0.8))
            c.rect(140, 170, 40, 20, INK, line=False)
    c.save(path)


# ---------- figures ----------

def figure_picture(colours, path):
    head, torso, legs, hat = colours
    c = Canvas(320, 320)
    c.rect(112, 190, 40, 100, legs, radius=4)
    c.rect(168, 190, 40, 100, legs, radius=4)
    c.rect(108, 116, 104, 84, torso, radius=6)
    c.rect(78, 120, 32, 80, shade(torso, 0.92), radius=10)
    c.rect(210, 120, 32, 80, shade(torso, 0.92), radius=10)
    c.ellipse(94, 206, 15, 15, head); c.ellipse(226, 206, 15, 15, head)
    c.rect(150, 96, 20, 24, head, line=False)
    c.rect(122, 36, 76, 66, head, radius=24)
    c.rect(146, 24, 28, 16, head, radius=3)
    c.rect(144, 62, 6, 8, INK, line=False); c.rect(170, 62, 6, 8, INK, line=False)
    c.rect(148, 80, 24, 4, INK, line=False)
    if hat:
        c.rect(112, 28, 96, 30, hat, radius=14)
        c.rect(104, 52, 112, 10, shade(hat, 0.9), radius=3)
    c.save(path)


# ---------- parts ----------

def studs(c, x, y, w, n, fill, size=14):
    gap = w / n
    for k in range(n):
        c.rect(x + gap * k + (gap - size) / 2, y - 8, size, 9, fill, radius=2)


def dims(name):
    found = re.search(r'(\d+)\s*[x×]\s*(\d+)', name or '')
    return (int(found[1]), int(found[2])) if found else (2, 2)


def part_picture(part_name, category, colour, path):
    text = (part_name or '').lower()
    category = (category or '').lower()
    a, b = dims(part_name)
    n = max(1, min(max(a, b), 8))
    c = Canvas(256, 256)
    w = 40 + 22 * n
    x = (256 - w) / 2
    if 'wheel' in category or 'tyre' in text or 'wheel' in text:
        c.ellipse(128, 128, 78, 78, INK); c.ellipse(128, 128, 44, 44, colour); c.ellipse(128, 128, 14, 14, shade(colour, 0.7))
    elif 'technic' in category and ('beam' in category or 'beam' in text or 'liftarm' in text):
        length = 60 + 26 * n
        x = (256 - length) / 2
        c.rect(x, 108, length, 40, colour, radius=20)
        for k in range(n):
            c.ellipse(x + 20 + k * (length - 40) / max(1, n - 1 if n > 1 else 1), 128, 9, 9, (250, 250, 248))
    elif 'axle' in text or 'pin' in category or 'pin' in text or 'connector' in category:
        c.rect(52, 116, 152, 24, colour, radius=8)
        c.rect(52, 100, 24, 56, shade(colour, 1.0), radius=6)
        c.rect(180, 106, 24, 44, shade(colour, 0.85), radius=6)
    elif 'tile' in category or ' tile' in text and 'round' not in text:
        c.rect(x, 140, w, 34, colour, radius=3)
        c.rect(x + 4, 144, w - 8, 3, shade(colour, 1.18), line=False)
    elif 'plate' in category or text.startswith('plate'):
        c.rect(x, 128, w, 40, colour, radius=3)
        studs(c, x, 128, w, n, colour)
    elif 'slope' in category or 'slope' in text:
        c.poly([(x, 168), (x, 130), (x + w * 0.55, 80), (x + w, 80), (x + w, 168)], colour)
        studs(c, x + w * 0.55, 80, w * 0.45, max(1, n // 2), colour)
    elif 'wedge' in category or 'wedge' in text:
        c.poly([(x, 168), (x + w, 168), (x + w, 112)], colour)
    elif 'round' in category or 'round' in text or 'cone' in text or 'dish' in text:
        c.rect(x + 20, 96, w - 40, 72, colour, radius=36)
        studs(c, x + 20, 96, w - 40, max(1, min(n, 3)), colour)
    elif 'plant' in category or 'tree' in text or 'flower' in text:
        c.rect(120, 150, 16, 70, shade((88, 42, 18), 1.0))
        c.ellipse(128, 100, 58, 58, colour)
        c.ellipse(96, 126, 34, 34, colour); c.ellipse(160, 126, 34, 34, colour)
    elif 'window' in category or 'door' in category or 'window' in text or 'door' in text:
        c.rect(84, 56, 88, 144, colour, radius=3)
        c.rect(98, 72, 60, 112, (250, 250, 248), radius=2)
        c.rect(126, 72, 4, 112, shade(colour, 0.8), line=False)
    elif 'bar' in category or 'fence' in text or 'ladder' in text:
        for k in range(4):
            c.rect(60 + k * 40, 80, 14, 110, colour, radius=5)
        c.rect(52, 74, 152, 14, colour, radius=4)
        c.rect(52, 182, 152, 14, colour, radius=4)
    elif 'panel' in category or 'panel' in text or 'wall' in text:
        c.rect(70, 70, 116, 116, colour)
        c.rect(70, 70, 14, 116, shade(colour, 0.85), line=False)
        c.rect(70, 172, 116, 14, shade(colour, 0.85), line=False)
    elif 'minifig' in category:
        if 'head' in category:
            c.rect(88, 80, 80, 80, colour, radius=26); c.rect(116, 64, 24, 18, colour, radius=3)
            c.rect(108, 108, 6, 8, INK, line=False); c.rect(142, 108, 6, 8, INK, line=False)
        elif 'lower' in category or 'leg' in text:
            c.rect(88, 70, 38, 120, colour, radius=4); c.rect(130, 70, 38, 120, colour, radius=4)
        elif 'upper' in category or 'torso' in text:
            c.rect(78, 70, 100, 90, colour, radius=6); c.rect(52, 74, 28, 76, shade(colour, 0.92), radius=9); c.rect(176, 74, 28, 76, shade(colour, 0.92), radius=9)
        else:
            c.rect(84, 84, 88, 62, colour, radius=22)
            c.rect(70, 138, 116, 12, shade(colour, 0.9), radius=3)
    elif 'hinge' in category or 'arm' in category or 'turntable' in category:
        c.rect(64, 100, 80, 56, colour, radius=4); c.rect(120, 116, 74, 40, shade(colour, 0.9), radius=4); c.ellipse(144, 128, 12, 12, (250, 250, 248))
    elif text.startswith('brick') or 'brick' in category:
        c.rect(x, 100, w, 68, colour, radius=3)
        studs(c, x, 100, w, n, colour)
        c.rect(x + 6, 106, w - 12, 3, shade(colour, 1.15), line=False)
    else:
        c.rect(x, 108, w, 60, colour, radius=4)
        studs(c, x, 108, w, max(1, n), colour)
        c.rect(x + w - 14, 124, 22, 20, shade(colour, 0.9), radius=3)
    c.save(path, fit=True, out=160, colours=40)


# ---------- the world's needs ----------

def targets(db):
    from brickwork.demo.showcase import picture_targets
    return picture_targets(db)


def key_of(row):
    from brickwork.demo.showcase import picture_key
    return picture_key(row)


def figure_colours(layer, number, fixtures):
    """(head, torso, legs, hat) colours of a figure from the part lines of the inventories that hold it, else a fixed pick from its number."""
    rows = layer.figure_rows.get(number) or fixtures.get(number) or []
    found = {}
    for row in rows:
        category = row.get('category', '')
        slot = {'Minifig Heads': 'head', 'Minifig Upper Body': 'torso', 'Minifig Lower Body': 'legs', 'Minifig Headwear': 'hat'}.get(category)
        if slot and slot not in found:
            found[slot] = hexrgb(row['color']['rgb'])
    seed = sum(map(ord, number))
    return (found.get('head', (242, 205, 55)), found.get('torso', SCENE_COLOURS[seed % 9]), found.get('legs', SCENE_COLOURS[(seed + 3) % 9]), found.get('hat'))


def draw_all(out):
    from brickwork.demo import dataset, showcase
    from brickwork.core.connect import connect
    from contextlib import closing
    data = dataset.DATA
    layer = showcase.layer(data, pictures=False)
    fixtures = {}
    for path in sorted((data / 'inventories').glob('*-copy-a.json')):
        for number, rows in json.loads(path.read_text(encoding='utf-8')).get('minifigure_parts', {}).items():
            fixtures.setdefault(number, rows)
    layer.figure_rows = {number: rows for inv in layer.inventories.values() for number, rows in inv['minifigure_parts'].items()}
    out.mkdir(parents=True, exist_ok=True)
    manifest = {}
    with tempfile.TemporaryDirectory() as scratch:
        store = Path(scratch) / 'brickwork.db'
        dataset.build(store, layer=layer)
        with closing(connect(store, read_only=True)) as db:
            needed = targets(db)
    category_of = {}
    for path in sorted((data / 'inventories').glob('*-copy-a.json')):
        for row in json.loads(path.read_text(encoding='utf-8'))['parts']:
            category_of.setdefault(row['part'], row['category'])
    for inv in layer.inventories.values():
        for row in inv['parts']:
            category_of.setdefault(row['part'], row['category'])
        for rows in inv['minifigure_parts'].values():
            for row in rows:
                category_of.setdefault(row['part'], row['category'])
    for row in needed:
        key, ns, number = key_of(row), row['born_namespace'], row['born_key']
        if key in manifest:
            continue
        file = re.sub(r'[^A-Za-z0-9._-]', '_', key.replace('/', '-')) + '.png'
        target = out / file
        if ns == 'parts':
            part_picture(row['name'], category_of.get(number), hexrgb(row['colour_rgb']), target)
        elif ns == 'minifigs':
            figure_picture(figure_colours(layer, number, fixtures), target)
        elif row['kind'] in ('gear', 'book', 'catalog'):
            object_picture(row['kind'], number, row['name'], target)
        else:
            set_picture(number, row['name'], target)
        manifest[key] = file
    (out / 'manifest.json').write_text(json.dumps(dict(sorted(manifest.items())), indent=0) + '\n', encoding='utf-8')
    return manifest


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--check', action='store_true')
    options = parser.parse_args(argv)
    if options.check:
        from brickwork.demo import showcase
        missing = showcase.missing_pictures()
        print('\n'.join(missing) or 'every picture the demo world needs is drawn')
        return 1 if missing else 0
    manifest = draw_all(ART)
    size = sum(p.stat().st_size for p in ART.glob('*.png'))
    print(f'{len(manifest)} pictures, {size / 1024:.0f} KiB in {ART}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
