"""Brick Work's brand assets: the design sources and the files the app serves from them (#159, D2).

    python3 scripts/brand_assets.py check    the drift check (scripts/check.sh); exit 1 on drift
    python3 scripts/brand_assets.py build    write every served file from its design/ source

The design files live in design/ (logo, app icon, UI icons). The app serves them at the paths it always has, /static/brickwork/...,
so no page, manifest or service worker changes. Those served files are GENERATED copies: build writes each byte for byte from its
source; never edit one. Three source folders, each mapped to a served folder with the same relative paths:

    design/logo/              -> static/brickwork/               marks and lockups (svg, png)
    design/app-icon/          -> static/brickwork/               app icon, favicons, icons/, splash/, head-block.html
    design/components/icons/  -> static/brickwork/icons-ui/      the UI icon set, its sprite and README

Two files in static/brickwork/ are the app's own, not design assets, and have no source: brick-work.css (the accent stylesheet every
page links) and manifest.webmanifest (served through the app's manifest view). A folder named `retired` in a source folder keeps old
marks and is never served.
`check` fails on a served file that differs from its source, a served file with no source, and a source with no served file (a missing
file is only a drift until `build` runs). Standard library only. Modelled on scripts/tokens_base.py."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVED = ROOT / 'static' / 'brickwork'
SOURCES = (('design/logo', ''), ('design/app-icon', ''), ('design/components/icons', 'icons-ui'))   # source folder -> served subfolder
APP_OWNED = {'brick-work.css', 'manifest.webmanifest'}
RETIRED = 'retired'


def mapping() -> dict[str, Path]:
    """`{served path relative to static/brickwork: source file}` for every source file; a path two sources claim is an error."""
    found: dict[str, Path] = {}
    for folder, subfolder in SOURCES:
        base = ROOT / folder
        for path in sorted(p for p in base.rglob('*') if p.is_file() and RETIRED not in p.relative_to(base).parts):
            served = (Path(subfolder) / path.relative_to(base)).as_posix()
            if served in found:
                raise SystemExit(f'BRAND: {served} is claimed by {found[served].relative_to(ROOT)} and {path.relative_to(ROOT)}')
            if served in APP_OWNED:
                raise SystemExit(f'BRAND: {path.relative_to(ROOT)} would overwrite the app-owned {served}')
            found[served] = path
    return found


def served_files() -> set[str]:
    return {p.relative_to(SERVED).as_posix() for p in SERVED.rglob('*') if p.is_file()} - APP_OWNED


def build() -> int:
    files = mapping()
    for served, source in files.items():
        target = SERVED / served
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    print(f'Built {len(files)} files in static/brickwork/ from design/')
    return 0


def problems() -> list[str]:
    files = mapping()
    found = []
    for served, source in files.items():
        target = SERVED / served
        if not target.is_file():
            found.append(f'static/brickwork/{served} is missing: run `python3 scripts/brand_assets.py build` ({source.relative_to(ROOT)})')
        elif target.read_bytes() != source.read_bytes():
            found.append(f'static/brickwork/{served} differs from {source.relative_to(ROOT)} (it is generated; edit the source, then build)')
    for served in sorted(served_files() - set(files)):
        found.append(f'static/brickwork/{served} has no source in design/ (add the source, or it is not a served brand file)')
    return found


def check() -> int:
    found = problems()
    for line in found:
        print('BRAND: ' + line)
    if found:
        return 1
    print(f'Brand assets OK: {len(mapping())} served files in static/brickwork/ equal their sources in design/.')
    return 0


if __name__ == '__main__':
    sys.exit({'check': check, 'build': build}[sys.argv[1]]())
