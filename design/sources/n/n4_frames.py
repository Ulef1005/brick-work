"""Commission N (Sync and files, #517), round 4 (draft): the busy state of the one-request run (#519). Folder 66.

v1.2.1 applies a Rebrickable run in one request (product, 2026-11-24): frame 23, the progress view, waits for a job runner (#685).
Until then the Preview step's button is busy while the request runs. Built on round 1's Preview (frame 22, imported, never copied).

    python n4_frames.py build|check|narrow [OUTDIR]
"""
import pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import n2_frames as N2  # noqa: E402,F401  (its import also installs round 2's shell for frames with a `shell` attribute)
import n_frames as N  # noqa: E402

SPIN = ('<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><circle cx="9" cy="9" r="7" fill="none" stroke="currentColor" stroke-opacity=".35" stroke-width="2.5"/>'
        '<path d="M9 2a7 7 0 0 1 7 7" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/></svg>')


def busy(ph):
    n = N.RUN_INTO + N.RUN_OUT
    html = N.preview(ph)
    old_run = N.btn(f'Run {n} changes', 'lg')
    old_back = N.btn('‹ Back', 'q')
    assert html.count(old_run) == 1 and html.count(old_back) == 1
    run = f'<span class="btn lg" style="gap:10px;opacity:.78">{SPIN}Running {n} changes</span>'
    back = '<span class="btn q" style="opacity:.45">‹ Back</span>'
    note = ('<p class="n" style="font-size:13.5px;color:var(--tw-text-2);flex-basis:100%;order:3">'
            'Keep this page open until the run is done. Everything above is locked while it runs.</p>')
    html = html.replace(old_run, run).replace(old_back, back)
    return _with_note(html, note)


def _with_note(html, note):
    """The note goes inside the footer row, after the button, so it wraps under it on the phone."""
    marker = '<div class="nfoot">'
    i = html.rindex(marker)
    j = html.index('</div>', i)
    return html[:j] + note + html[j:]


N.FRAMES = [('N4-01', '66-sync-run-busy', busy)]
N.DRAFTS = []

if __name__ == '__main__':
    raise SystemExit(N.main(*sys.argv[1:3]))
