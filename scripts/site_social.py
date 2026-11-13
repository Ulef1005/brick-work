"""Render the website's social preview (1200 x 630 PNG) via pinned Chrome for Testing.

    python scripts/site_social.py [--out FILE]
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
    font-family: 'Inter';
    font-style: normal;
    font-weight: 400;
    font-display: block;
    src: url('__INTER_400__') format('woff2');
  }
  @font-face {
    font-family: 'Inter';
    font-style: normal;
    font-weight: 600;
    font-display: block;
    src: url('__INTER_600__') format('woff2');
  }
  @font-face {
    font-family: 'Patrick Hand';
    font-style: normal;
    font-weight: 400;
    font-display: block;
    src: url('__PATRICK_HAND__') format('woff2');
  }
  * {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }
  html, body {
    width: 1200px;
    height: 630px;
    overflow: hidden;
    background: #FAF9F6;
    color: #1C1B19;
    font-family: 'Inter', sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  .canvas {
    position: relative;
    width: 1200px;
    height: 630px;
    overflow: hidden;
    background: #FAF9F6;
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
  .brand-name {
    font-family: 'Patrick Hand', cursive, sans-serif;
    font-size: 48px;
    line-height: 1;
    font-weight: 400;
    color: #1C1B19;
  }
  h1 {
    margin-top: 28px;
    font-family: 'Inter', sans-serif;
    font-weight: 600;
    font-size: 52px;
    line-height: 1.1;
    letter-spacing: -0.02em;
    color: #1C1B19;
  }
  .clay {
    color: #007187;   /* the logo's blue (design/logo, rgb 0 113 135) */
  }
  .subtitle {
    margin-top: 20px;
    max-width: 390px;
    font-family: 'Inter', sans-serif;
    font-weight: 400;
    font-size: 24px;
    line-height: 1.35;
    color: #6F6A62;
  }
  .domain {
    margin-top: auto;
    font-family: 'Inter', sans-serif;
    font-weight: 600;
    font-size: 22px;
    line-height: 1;
    color: #B4410A;
  }
  .shot-desktop {
    position: absolute;
    left: 560px;
    top: 150px;
    width: 640px;
    height: 400px;
    border-radius: 14px;
    overflow: hidden;
    box-shadow: 0 30px 70px rgba(28, 27, 25, .38), 0 6px 18px rgba(28, 27, 25, .25);
    z-index: 1;
  }
  .shot-phone {
    position: absolute;
    left: 470px;
    top: 250px;
    width: 260px;
    border-radius: 24px;
    overflow: hidden;
    box-shadow: 0 30px 70px rgba(28, 27, 25, .38), 0 6px 18px rgba(28, 27, 25, .25);
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
      <h1>Don't just manage your collection. <span class="clay">Work with it.</span></h1>
      <p class="subtitle">A self-hosted workbench for your brick collection.</p>
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


def build_html(folder: Path) -> str:
    """Stage local fonts and images into `folder` and return the self-contained HTML page."""
    icon = first_existing([ROOT / 'design' / 'logo' / 'lockup-horizontal-light.png'])
    icon_tag = f'<img class="brand-icon" src="{stage(icon, folder)}" alt="">' if icon else ''
    tokens = {
        '__INTER_400__': stage(ROOT / 'docs' / 'assets' / 'fonts' / 'inter-latin-400-normal.woff2', folder),
        '__INTER_600__': stage(ROOT / 'docs' / 'assets' / 'fonts' / 'inter-latin-600-normal.woff2', folder),
        '__PATRICK_HAND__': stage(ROOT / 'static' / 'fonts' / 'PatrickHand-Regular.woff2', folder),
        '__ICON_TAG__': icon_tag,
        '__DESKTOP_IMG__': stage(ROOT / 'scripts' / 'site' / 'img' / '1c-sets-desktop-1440-light.png', folder),
        '__PHONE_IMG__': stage(ROOT / 'scripts' / 'site' / 'img' / '3a-matcher-phone-390-light.png', folder),
    }
    page = HTML
    for key, value in tokens.items():
        page = page.replace(key, value)
    return page


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', default=str(DEFAULT_OUT), help='output PNG path')
    options = parser.parse_args(argv)
    chrome = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'chrome.py'), 'pinned'], capture_output=True, text=True)
    if chrome.returncode:
        print(chrome.stderr.strip())
        return 1
    binary = chrome.stdout.strip()
    with tempfile.TemporaryDirectory(prefix='bw-social-') as scratch:
        folder = Path(scratch)
        tmp_html = folder / 'social.html'
        tmp_png = folder / 'social.png'
        tmp_html.write_text(build_html(folder), encoding='utf-8')
        result = subprocess.run([
            binary,
            '--headless=new',
            '--disable-gpu',
            '--hide-scrollbars',
            '--force-device-scale-factor=1',
            '--virtual-time-budget=8000',
            '--window-size=1200,630',
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
