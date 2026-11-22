"""Render the social preview (1200 x 630 PNG for the website, 1280 x 640 for GitHub) via pinned Chrome for Testing.

    python scripts/site_social.py [--out FILE] [--size WIDTHxHEIGHT]
    python scripts/site_social.py --size 1280x640 --out docs/assets/social-preview-github-1280x640.png   # Ulf uploads it by hand

B′ (#492, #502): IBM Plex Sans, the B′ light roles of static/web/toni/tokens-v2.css, the category line as the subtitle.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / 'scripts' / 'site' / 'social-preview.png'

HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
  @font-face {
    font-family: 'IBM Plex Sans';
    font-style: normal;
    font-weight: 400;
    font-display: block;
    src: url('__PLEX_400__') format('woff2');
  }
  @font-face {
    font-family: 'IBM Plex Sans';
    font-style: normal;
    font-weight: 600;
    font-display: block;
    src: url('__PLEX_600__') format('woff2');
  }
  * {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }
  html, body {
    width: __WIDTH__px;
    height: __HEIGHT__px;
    overflow: hidden;
    background: #F8F8F6;   /* --tw-surface, B′ light */
    color: #1A1E1E;        /* --tw-text */
    font-family: 'IBM Plex Sans', sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  .canvas {
    position: relative;
    width: __WIDTH__px;
    height: __HEIGHT__px;
    overflow: hidden;
    background: #F8F8F6;
  }
  .left {
    position: absolute;
    left: 64px;
    top: 52px;
    bottom: 48px;
    width: 456px;
    display: flex;
    flex-direction: column;
    z-index: 3;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 14px;
  }
  .brand-icon {
    height: 64px;
    width: auto;
    display: block;
  }
  h1 {
    margin-top: 28px;
    font-family: 'IBM Plex Sans', sans-serif;
    font-weight: 600;
    font-size: 52px;
    line-height: 1.1;
    letter-spacing: -0.02em;
    color: #1A1E1E;   /* ink: in B′ violet means action, found or chosen */
  }
  .subtitle {
    margin-top: 20px;
    max-width: 430px;
    font-family: 'IBM Plex Sans', sans-serif;
    font-weight: 400;
    font-size: 24px;
    line-height: 1.35;
    color: #434A4A;   /* --tw-text-2 */
  }
  .domain {
    margin-top: auto;
    font-family: 'IBM Plex Sans', sans-serif;
    font-weight: 600;
    font-size: 22px;
    line-height: 1;
    color: #7334CF;   /* --tw-accent-text: the address is the one link */
  }
  .shot-desktop {
    position: absolute;
    left: calc(540px + __SHIFT__px);   /* the screenshots stay flush right on a wider canvas */
    top: 150px;
    width: 640px;
    height: 400px;
    border-radius: 14px;
    overflow: hidden;
    box-shadow: 0 30px 70px rgba(26, 30, 30, .38), 0 6px 18px rgba(26, 30, 30, .25);
    z-index: 1;
  }
  .shot-phone {
    position: absolute;
    left: calc(930px + __SHIFT__px);   /* the phone on the right, over the desktop's right edge */
    top: 250px;
    width: 260px;
    border-radius: 24px;
    overflow: hidden;
    box-shadow: 0 30px 70px rgba(26, 30, 30, .38), 0 6px 18px rgba(26, 30, 30, .25);
    z-index: 2;
  }
  .shot-desktop img,
  .shot-phone img {
    display: block;
    width: 100%;
    height: auto;
  }
</style>
</head>
<body>
  <div class="canvas">
    <div class="left">
      <div class="brand">__ICON_TAG__</div>
      <h1>Don't just manage your collection. Work with it.</h1>
      <p class="subtitle">Free, self-hosted app for your brick collection and its missing parts.</p>
      <div class="domain">brick-work.app</div>
    </div>
    <div class="shot-desktop"><img src="__DESKTOP_IMG__" alt=""></div>
    <div class="shot-phone"><img src="__PHONE_IMG__" alt=""></div>
  </div>
</body>
</html>
"""


def first_existing(paths: list[Path]) -> Path | None:
    """Return the first existing file from `paths`, ignoring missing ones."""
    for path in paths:
        if path.is_file():
            return path
    return None


def stage(src: Path, folder: Path) -> str:
    """Copy `src` into `folder` and return its file:// URL."""
    dst = folder / src.name
    shutil.copy2(src, dst)
    return dst.as_uri()


def optimise(path: Path) -> None:
    """Palette PNG: the app's flat colours quantise without visible loss and weigh a fraction."""
    from PIL import Image
    with Image.open(path) as image:
        image = image.convert('RGB')
        image.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(path, optimize=True)


def build_html(folder: Path, width: int = 1200, height: int = 630) -> str:
    """Stage local fonts and images into `folder` and return the self-contained HTML page."""
    icon = first_existing([ROOT / 'design' / 'logo' / 'lockup-horizontal-light.png'])
    icon_tag = f'<img class="brand-icon" src="{stage(icon, folder)}" alt="">' if icon else ''
    tokens = {
        '__PLEX_400__': stage(ROOT / 'docs' / 'assets' / 'fonts' / 'IBMPlexSans-Regular.woff2', folder),
        '__PLEX_600__': stage(ROOT / 'docs' / 'assets' / 'fonts' / 'IBMPlexSans-SemiBold.woff2', folder),
        '__ICON_TAG__': icon_tag,
        '__WIDTH__': str(width),
        '__HEIGHT__': str(height),
        '__SHIFT__': str(width - 1200),
        '__DESKTOP_IMG__': stage(ROOT / 'scripts' / 'site' / 'img' / '1c-sets-desktop-1440-light.png', folder),
        '__PHONE_IMG__': stage(ROOT / 'scripts' / 'site' / 'img' / '3a-matcher-phone-390-light.png', folder),
    }
    page = HTML
    for key, value in tokens.items():
        page = page.replace(key, value)
    return page


def canvas(text: str) -> tuple[int, int]:
    """`WIDTHxHEIGHT`, at least 1200x630: the layout is drawn for that canvas and only grows to the right."""
    parts = text.lower().split('x')
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise argparse.ArgumentTypeError(f'{text!r} is not WIDTHxHEIGHT')
    width, height = int(parts[0]), int(parts[1])
    if width < 1200 or height < 630:
        raise argparse.ArgumentTypeError(f'{text!r} is smaller than 1200x630, the layout\'s canvas')
    return width, height


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', default=str(DEFAULT_OUT), help='output PNG path')
    parser.add_argument('--size', default='1200x630', type=canvas, help='WIDTHxHEIGHT, at least 1200x630; 1280x640 is GitHub\'s social preview')
    options = parser.parse_args(argv)
    width, height = options.size
    chrome = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'chrome.py'), 'pinned'], capture_output=True, text=True)
    if chrome.returncode:
        print(chrome.stderr.strip())
        return 1
    binary = chrome.stdout.strip()
    with tempfile.TemporaryDirectory(prefix='bw-social-') as scratch:
        folder = Path(scratch)
        tmp_html = folder / 'social.html'
        tmp_png = folder / 'social.png'
        tmp_html.write_text(build_html(folder, width, height), encoding='utf-8')
        result = subprocess.run([
            binary,
            '--headless=new',
            '--disable-gpu',
            '--hide-scrollbars',
            '--force-device-scale-factor=1',
            '--virtual-time-budget=8000',
            f'--window-size={width},{height}',
            f'--screenshot={tmp_png}',
            tmp_html.as_uri(),
        ], capture_output=True, text=True, timeout=120)
        if result.returncode or not tmp_png.is_file():
            print(result.stdout[-2000:] + result.stderr[-2000:])
            return 1
        optimise(tmp_png)
        out_path = Path(options.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(tmp_png.read_bytes())
        print(out_path, out_path.stat().st_size)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
