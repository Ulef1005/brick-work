"""Commission N (Sync and files, #517), round 4 (draft): Brickset's pick, preview and result, drawn from what the Brickset API really carries
(research of 2026-11-24, ~/Workspace/_exports/design-brief-n/syncable-brickset.md; Ulf: "draw per site - based on the data syncable via the api
from the specific site"). Folders 67 to 69. Built on rounds 1 and 2 (imported, never copied); frames 25 and 26 stand.

Facts the frames rest on: Brickset keeps quantities per set, never copies; one call per set; every call counts against 100 a day; a rating is
1 to 5 and 0 means none; a priority of 1 is Brickset's default; there is no purchase date or price and no wanted quantity for minifigures.

    python n5_frames.py build|check|narrow [OUTDIR]
"""
import pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import n2_frames as N2  # noqa: E402
import n_frames as N  # noqa: E402

tag, btn, head, foot, drow, kv, card, two, ptile, seg = N.tag, N.btn, N.head, N.foot, N.drow, N.kv, N2.card, N2.two, N.ptile, N.seg
steps_n, S, cb = N2.steps_n, N.S, N.cb
BS = ['Connect', 'Choose what', 'Pick sets', 'Preview', 'Run', 'Result']
mono = 'font-size:13px;color:var(--tw-text-2)'


# ---- 67 Pick sets -----------------------------------------------------------------------------------------------------
def pick(ph):
    scopes = seg('Changed since 12 Nov', ['All linked', 'Owned', 'Wanted', 'Changed since 12 Nov', 'One by one'])
    rows = [('7213-1', 'Owned · 2 here · Brickset 1', True), ('7938-1', 'Wanted · 1 here · Brickset 1', True),
            ('10254-1', 'Owned · 1 here · Brickset 1 · rating 4', True), ('31120-1', 'Owned · 1 here · gone at Brickset', True),
            ('8043-1', 'Wanted · 1 here · Brickset 1 · unchanged', False)]
    lst = ''.join(f'<div class="nrow">{cb(on)}{ptile(no)}<div class="id"><b>{S(no)["name"]}</b><span><span class="mono">{no}</span> · {m}</span></div></div>' for no, m, on in rows)
    sets = card('Sets this run covers', '<p class="n">Brickset keeps a quantity per set, so a set is the unit here. Sets that changed on either side since the last run are ticked.</p>'
                + f'<div style="overflow-x:auto">{scopes}</div>' + lst
                + '<p class="mono" style="font-size:13px;color:var(--tw-text-2)">5 of 83 shown · 61 owned · 22 wanted</p>')
    figs = card('Loose minifigures', '<p class="n">Own, want, quantity and notes. Brickset has no wanted quantity for a minifigure.</p>'
                + ''.join(f'<div class="nrow">{cb(on)}<div class="id"><b>{n}</b><span><span class="mono">{no}</span> · {m}</span></div></div>'
                          for n, no, m, on in (('Knight with banner', 'cas123', 'own 1 here · Brickset 0', True), ('Space explorer', 'sp045', 'wanted here · own 2 at Brickset', True))))
    budget = ('<div class="ninfo"><b>One call per set.</b> Every call counts against Brickset’s 100 a day.'
              + kv([('Calls this run', 'about <span class=mono>6</span>'), ('Budget today', '<span class=mono>14 / 100</span>')]) + '</div>')
    return (head('Brickset', 'Pick the sets and minifigures this run covers.', ph) + steps_n(BS, 'Pick sets', ph) + two(sets, figs, ph)
            + budget + foot(btn('‹ Back', 'q'), btn('Next: preview', 'sec'), '<span class="mono" style="font-size:13px;color:var(--tw-text-2)">4 sets and 2 minifigures picked</span>'))


# ---- 68 Preview: one row per set and field, as the choose-what step ticked them ---------------------------------------
def preview(ph):
    rows = [  # lead tick, name, meta, status tag, action
        (True, '7213-1 · Off-Road Fire Truck & Fireboat', 'Quantity owned: here 2 · Brickset 1 (new 1, used 0)', tag('Changed in both places', 'dash'), 'Keep 2 here ▾'),
        (True, '7213-1 · Off-Road Fire Truck & Fireboat', 'Notes: here “Box dented” · Brickset empty', tag('Only here', 'dash'), 'Send to Brickset ▾'),
        (True, '10254-1 · Winter Holiday Train', 'Rating: here none · Brickset 4', tag('New there'), 'Take 4 here ▾'),
        (True, '10254-1 · Winter Holiday Train', 'Flags: here Gift · Brickset Gift, Display', tag('Differs', 'dash'), 'Take Display here ▾'),
        (False, '31120-1 · Medieval Castle', 'Owned: here 1 · not on Brickset any more', tag('Gone there', 'hatch'), 'Remove here ▾'),
    ]
    body = ''.join(drow(cb(on), name, meta, st, act, ph, 150) for on, name, meta, st, act in rows)
    sets = card('Sets · 5 differences', '<p class="n">Only the fields you ticked are compared; wanted priority is off. A set gone at Brickset is never removed here unless you tick it.</p>' + body)
    figs = card('Loose minifigures · 2', ''.join(drow(cb(True), n, m, st, a, ph, 150) for n, m, st, a in (
        ('Knight with banner <span class="mono">cas123</span>', 'Own: here 1 · Brickset 0', tag('Only here', 'dash'), 'Send to Brickset ▾'),
        ('Space explorer <span class="mono">sp045</span>', 'Own: here 0 · Brickset 2', tag('New there'), 'Take 2 here ▾'))))
    info = ('<div class="ninfo"><b>Before you send.</b> Brick Work’s Undo cannot take a sent change back.'
            + kv([('Calls', 'about <span class=mono>6</span>: 4 to read, 2 to send'), ('Budget today', '<span class=mono>14 / 100</span>')]) + '</div>')
    n = 6   # six of the seven rows are ticked; the removal of Medieval Castle stays unticked
    return (head('Brickset', 'Preview of what the run would change.', ph) + steps_n(BS, 'Preview', ph) + sets + figs + info
            + foot(btn('‹ Back', 'q'), btn(f'Run {n} changes', 'lg'), f'<span class="mono" style="font-size:13px;color:var(--tw-text-2)">{n} of 7 chosen</span>'))


# ---- 69 Result ---------------------------------------------------------------------------------------------------------
def result(ph):
    here = (f'<div class="ncard"><h2>Here in Brick Work {tag("3 changed")}</h2>'
            '<p class="n">Rating 4 and the Display flag added to 10254-1 · 1 minifigure counted · Medieval Castle kept.</p>'
            '<span class="btn sec sm" style="align-self:flex-start">Undo this run</span>'
            '<p class="n">Undo takes back everything this run changed here, in one step. It cannot change what was sent to Brickset.</p></div>')
    there = (f'<div class="ncard"><h2>On Brickset {tag("2 sent")}</h2><p class="n">A note on 7213-1 · 1 minifigure owned.</p>'
             '<div class="ninfo">A change on Brickset cannot be undone here. To reverse it, change it back on Brickset or send again.</div>'
             '<p class="mono" style="font-size:13px;color:var(--tw-text-2)">Budget today 20 / 100</p></div>')
    skipped = card('Not changed', '<p class="n">Wanted priority was off for this run. Purchase date and price are never sent: Brickset has no field for them.</p>')
    return (head('Brickset', 'Finished 24 Nov, 18:02 · 6 of 6 done', ph) + steps_n(BS, 'Result', ph)
            + (here + there + skipped if ph else f'<div class="ngrid g2" style="align-items:start">{here}{there}</div>{skipped}')
            + foot(btn('Open sync log', 'q'), btn('Done', 'sec')))


N.FRAMES = [('N5-01', '67-brickset-pick', pick), ('N5-02', '68-brickset-preview', preview), ('N5-03', '69-brickset-result', result)]
N.DRAFTS = []

if __name__ == '__main__':
    raise SystemExit(N.main(*sys.argv[1:3]))
