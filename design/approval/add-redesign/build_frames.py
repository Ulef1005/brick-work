"""Approval frames of the Add page redesign (Ulf, 2026-10-28: "Add to list" read as adding to the collection). Re-runnable.

    <the canonical venv's python> design/approval/add-redesign/build_frames.py [frame id ...]   (from the repo root)

It reuses the invented 4.0 pair and the app set-up of design/approval/112-m10-a/build_frames.py (no Rebrickable key) and captures the
Add page at the three kit sizes, light and dark. Nothing under data/ is read."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

OUT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('m10a_frames', OUT.parent / '112-m10-a' / 'build_frames.py')
m10a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m10a)

SELECT = m10a.REVIEW + """
const find=async(text,expect)=>{const i=R.querySelector('[data-search]');i.value=text;i.dispatchEvent(new Event('input',{bubbles:true}));
 await until(()=>{const f=R.querySelector('[data-results] .bw-add-item');return f&&f.textContent.includes(expect);});};
await find('Syn','Syn');R.querySelector('[data-results] .bw-add-select').click();await pause(150);
"""
REVIEW = SELECT + "R.querySelector('[data-review]').click();await until(shown);await pause(200);"
CHOSEN = REVIEW + "const c=R.querySelector('select[aria-label^=\"Choice for\"]');c.value='another';c.dispatchEvent(new Event('change'));await pause(150);"
WISHLIST = "document.querySelector('#bw-add input[name=where][value=wishlist]').click();"


def frames():
    return [
        ('add1', 'find', '/manage/add', ''),
        ('add2', 'selected', '/manage/add', SELECT),
        ('add3', 'review', '/manage/add', REVIEW),
        ('add3b', 'review-another-copy', '/manage/add', CHOSEN),
        ('add4', 'wishlist-options', '/manage/add', WISHLIST),
    ]


def run(selected):
    folder = Path(tempfile.mkdtemp(prefix='add-redesign-'))
    try:
        _, app = m10a.build_app(folder, False)
        server, base = m10a.serve(app)
        cookie = m10a.session_cookie(app)
        jobs = [dict(url=base + url, out=str(OUT / f'{frame}-{view}-{device}-{width}-{theme}.png'), width=width, theme=theme, script=script)
                for frame, view, url, script in frames() if not selected or frame in selected
                for device, width in m10a.SIZES for theme in ('light', 'dark')]
        spec_file = folder / 'jobs.json'
        spec_file.write_text(json.dumps(dict(headers={'Cookie': cookie}, jobs=jobs)))
        subprocess.run(['node', str(m10a.ROOT / 'scripts' / 'capture_screens.cjs'), m10a.CHROME, str(spec_file)], cwd=m10a.ROOT, check=True)
        server.shutdown()
    finally:
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == '__main__':
    run(set(sys.argv[1:]))
