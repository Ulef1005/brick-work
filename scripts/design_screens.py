"""Brick Work's screens folder: design/screens/ and its manifest, made from the design export's frames.json (#159, D2).

    python3 scripts/design_screens.py manifest   write design/screens/manifest.json from design/sources/frames.json
    python3 scripts/design_screens.py check      the drift check (scripts/check.sh); exit 1 on drift

Layout (App Design Standard, P2): design/screens/NN-<Screen>/NN-<Screen>[-<state>]-<width>-<light|dark>.png, plus the section's static
HTML as NN-<Screen>.html, one folder per frames.json section. NN is the section's position in frames.json (two digits), <Screen> the
section's short title in kebab-case. frames.json is the design project's export and stays byte-identical: it still names the old flat
paths (`frames/<name>.png`, `sections/<Group>/<id>.html`); this script resolves them to the folders. A frame the export never listed
(the 10a iPad frames) was retired by the maintainer (2026-11-05): it sits in design/screens/_retired/ under its old name, and the manifest lists it.
The build captures of the app are design/screens/approval/ and are not part of this manifest. design/screens/states.json (hand-kept, D3) says how
each screen is reached in the built app and whether it is built and approved; `check` also keeps it and approval/baselines/ consistent:
an approved state has all six baselines (1440 / 1024 / 390, light and dark), a built state that is not approved needs none (baselines are committed at approval only).
`check`: the manifest is what `manifest` writes, every PNG and HTML it lists exists, no PNG or HTML in the folders is unlisted.
Standard library only. Modelled on engram's design/screens/manifest.json."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCREENS = ROOT / 'design' / 'screens'
FRAMES = ROOT / 'design' / 'sources' / 'frames.json'
MANIFEST = SCREENS / 'manifest.json'
STATES = SCREENS / 'states.json'
BASELINES = SCREENS / 'approval' / 'baselines'
RETIRED = '_retired'
THEMES = ('light', 'dark')
PHONE = 390


def kebab(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', text.lower().replace('&', ' and ')).strip('-')


def screen_name(title: str, section_id: str) -> str:
    """The short, kebab-case name of a section: its title up to the first ' · ', ',' or ' (', without the 'G1' of the guide pages."""
    head = re.split(r' · |,| \(', title)[0]
    if re.match(r'^G\d', head):
        head = head[2:]
    slug = kebab(head) or kebab(section_id)
    return slug[:1].upper() + slug[1:]


def png_name(number: int, screen: str, old: str, section_id: str) -> tuple[str, int, str]:
    """The new name, width and theme of a frame PNG given by its old flat name."""
    match = re.fullmatch(r'(?:.*/)?(.+)-(\d+)-(light|dark)\.png', old)
    if match:
        stem, width, theme = match[1], int(match[2]), match[3]
    elif match := re.fullmatch(r'(?:.*/)?(.+-phone)-(light|dark)\.png', old):   # 3f's three phone frames carry no width: the kit's 390
        stem, width, theme = match[1], PHONE, match[2]
    else:
        raise ValueError(f'unexpected frame name {old}')
    state = re.sub(rf'^{re.escape(section_id)}(-|$)', '', stem, flags=re.I)
    if kebab(state) in ('', screen.lower()):
        state = ''
    middle = f'-{state}' if state else ''
    return f'{number:02d}-{screen}{middle}-{width}-{theme}.png', width, theme


def sections() -> list[dict]:
    """Every frames.json section with its folder, files and old-to-new mapping (old paths relative to design/)."""
    out = []
    for number, section in enumerate(json.loads(FRAMES.read_text(encoding='utf-8'))['sections'], 1):
        screen = screen_name(section['title'], section['id'])
        folder = f'{number:02d}-{screen}'
        old = list(section.get('pngs', []))
        for frame in section['frames']:
            old += list(frame.get('png', {}).values())
        files = {}
        for path in old:
            name, width, theme = png_name(number, screen, path, section['id'])
            if name in files.values():
                raise ValueError(f'two frames of {folder} get the name {name}')
            files[path] = name
        html = section.get('static_html')
        out.append({'number': number, 'id': section['id'], 'folder': folder, 'screen': screen, 'section': section,
                    'png': files, 'html': {html: f'{number:02d}-{screen}.html'} if html else {}})
    return out


def listed_files(item: dict) -> list[str]:
    return sorted(item['png'].values())


def retired_files() -> list[str]:
    folder = SCREENS / RETIRED
    return sorted(p.name for p in folder.iterdir() if p.is_file()) if folder.is_dir() else []


def manifest_text() -> str:
    screens = []
    for item in sections():
        section = item['section']
        sizes = sorted({frame['width'] for frame in section['frames']})
        screens.append({
            'id': section['id'], 'folder': item['folder'], 'screen': item['screen'], 'group': section['group'], 'sub': section['sub'],
            'title': section['title'], 'source': section['source'], 'view': section['view'],
            'html': next(iter(item['html'].values()), None),
            'states': [{'label': f['label'], 'width': f['width'], 'state': f['state']} for f in section['frames']],
            'sizes': sizes, 'themes': list(THEMES), 'pngs': listed_files(item)})
    return json.dumps({'app': 'brick-work', 'generated_by': 'scripts/design_screens.py manifest',
                       'source': 'design/sources/frames.json', 'screens': screens, 'retired': retired_files()},
                      indent=2, ensure_ascii=False) + '\n'


def manifest() -> int:
    MANIFEST.write_text(manifest_text(), encoding='utf-8')
    print(f'Wrote {MANIFEST.relative_to(ROOT)}')
    return 0


def problems() -> list[str]:
    found = []
    folders = set()
    for item in sections():
        folders.add(item['folder'])
        folder = SCREENS / item['folder']
        want = set(listed_files(item)) | set(item['html'].values())
        have = {p.name for p in folder.iterdir() if p.is_file()} if folder.is_dir() else set()
        found += [f'{item["folder"]}/{name} is listed but missing' for name in sorted(want - have)]
        found += [f'{item["folder"]}/{name} is not listed by design/sources/frames.json' for name in sorted(have - want)]
    for path in sorted(SCREENS.iterdir()):
        if path.is_dir() and path.name not in folders | {RETIRED, 'approval'}:
            found.append(f'design/screens/{path.name}/ is not a section folder of design/sources/frames.json')
    if not MANIFEST.is_file() or MANIFEST.read_text(encoding='utf-8') != manifest_text():
        found.append('design/screens/manifest.json is not what `scripts/design_screens.py manifest` makes (it is generated)')
    return found + state_problems(folders)


def state_problems(folders: set) -> list[str]:
    """design/screens/states.json (the screenshot gate's list, hand-kept) against the manifest and the baseline files."""
    if not STATES.is_file():
        return ['design/screens/states.json is missing']
    found, listed, expected = [], set(), set()
    states = json.loads(STATES.read_text(encoding='utf-8'))
    for entry in states['states']:
        name = f'{entry["screen"]}{" [" + entry["state"] + "]" if entry["state"] else ""}'
        listed.add(entry['screen'])
        if entry['screen'] not in folders:
            found.append(f'states.json: {name} is not a screen folder of the manifest')
        if entry['approved'] and not entry['built']:
            found.append(f'states.json: {name} is approved but not built')
        if entry['built'] and not (entry.get('world') and entry.get('path', '').startswith('/')):
            found.append(f'states.json: {name} is built but names no world and path')
        if not entry['built'] and not entry.get('reason'):
            found.append(f'states.json: {name} is not built and gives no reason')
        if entry['built']:
            stem = entry['screen'] + (f'-{entry["state"]}' if entry['state'] else '')
            for width in states['sizes']:
                for theme in states['themes']:
                    file = f'{stem}-{width}-{theme}.png'
                    expected.add((entry['screen'], file))
                    if entry['approved'] and not (BASELINES / entry['screen'] / file).is_file():
                        found.append(f'states.json: {name} is approved but has no baseline approval/baselines/{entry["screen"]}/{file}')
    found += [f'states.json lists no state of {folder}' for folder in sorted(folders - listed)]
    if BASELINES.is_dir():
        for folder in sorted(p for p in BASELINES.iterdir() if p.is_dir()):
            for file in sorted(p.name for p in folder.iterdir() if p.is_file()):
                if (folder.name, file) not in expected:
                    found.append(f'approval/baselines/{folder.name}/{file} belongs to no built state of states.json')
    return found


def check() -> int:
    found = problems()
    for line in found:
        print('SCREENS: ' + line)
    if found:
        return 1
    count = sum(len(listed_files(item)) for item in sections())
    print(f'Design screens OK: {len(sections())} screens, {count} PNGs listed and present, manifest generated, '
          f'{len(retired_files())} retired file(s) in {RETIRED}/; states.json consistent with the baselines.')
    return 0


if __name__ == '__main__':
    sys.exit({'check': check, 'manifest': manifest}[sys.argv[1]]())
