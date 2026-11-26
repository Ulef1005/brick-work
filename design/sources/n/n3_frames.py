"""Commission N (Sync and files, #517), round 3 (draft): the states of a run that the first two rounds do not draw. Folders 54 to 58.

R3-01 a rate limit (the site asks us to wait), R3-02 the day's budget used up, R3-03 rows that wait for your choice, R3-04 a long run,
R3-05 nothing to sync. Built on round 1 and 2's components (imported, never copied).

    python n3_frames.py build|check|narrow [OUTDIR]
"""
import pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import n2_frames as N2  # noqa: E402  (its import also installs round 2's shell for frames with a `shell` attribute)
import n_frames as N  # noqa: E402

tag, btn, head, steps, foot, drow, kv, prog, card, two, ic = N.tag, N.btn, N.head, N.steps, N.foot, N.drow, N.kv, N.prog, N2.card, N2.two, N.ic
mono = 'font-size:13px;color:var(--tw-text-2)'


def hatched(done, total):
    return prog(done, total)


def rate_limit(ph):
    """Rebrickable: halfway through a run the site asks us to wait; the run waits as long as asked and goes on by itself."""
    main = (card('62 of 140 done', f'{prog(62, 140)}<p class="mono" style="{mono}">paused by Rebrickable · goes on in 38 s · budget today 262 / 1,000</p>'
                 '<div class="ninfo">Rebrickable asked for a short break. Brick Work waits as long as it asks and goes on by itself. Nothing is lost and nothing is repeated.</div>'
                 f'<div style="display:flex;gap:10px;flex-wrap:wrap">{btn("Stop after this one", "sec sm")}</div>'))
    return (head('Rebrickable', 'Running 140 changes', ph) + steps('Run', ph) + main
            + card('Why it waits', '<p class="n">Each site allows only so many requests a minute. When it says “slow down”, the run takes a break instead of failing. A run that has to wait more than 10 minutes stops with “Run again later” and keeps its place.</p>'))


def budget_used(ph):
    """Brickset: the day's 100 calls are gone; the rest of the run waits for tomorrow."""
    main = (card('Today’s budget is used up', f'{prog(100, 100)}<p class="mono" style="{mono}">100 of 100 calls · comes back in 6 h 12 min</p>'
                 '<p class="n">The run stopped after 61 of 83 sets. Those 61 are done. The other 22 wait, and nothing is lost. Run Brickset again when the budget is back, in 6 h 12 min, and it carries on with them.</p>'
                 f'<div style="display:flex;gap:10px;flex-wrap:wrap">{btn("Open the sync log", "q sm")}</div>'))
    left = card('Still to do', ''.join(drow(N.ptile(s), n, f'<span class="mono">{s}</span>', '', '<span class="n">waits</span>', ph)
                                     for s, n in (('21319-1', 'Central Perk'), ('10270-1', 'Bookshop'), ('21330-1', 'Home Alone'))) + '<p class="n">and 19 more</p>')
    return (head('Brickset', 'Stopped: today’s budget is used up', ph, right='') + main + left
            + '<div class="ninfo">Brickset allows 100 calls a day. Brick Work never goes past the number, so your account is not locked out.</div>')


def conflicts(ph):
    """The result of a run with rows that differ on both sides: they were not changed and wait for a choice."""
    rows = (('7938-1', 'Set 7938-1, Copy 1', 'Brick Work: 2 missing · Rebrickable: 0 missing'),
            ('10254-1', 'Set 10254-1', 'Brick Work: in Main collection · Rebrickable: not in any list'),
            ('8043-1', 'Set 8043-1, Copy 2', 'Brick Work: checked 12 Nov · Rebrickable: edited 18 Nov'))
    lst = ''.join(drow(N.ptile(s), t, f'<span class="mono">{s}</span> · {d}', tag('Waiting', 'dash'), '<span class="btn sec sm">Choose</span>', ph) for s, t, d in rows)
    return (head('Rebrickable', 'Finished 19 Nov, 16:54 · 137 of 140 done, 3 wait for you', ph) + steps('Result', ph)
            + card('3 rows differ on both sides ' + tag('3 waiting', 'hatch'), lst
                   + '<p class="n">Nothing was changed on these rows, here or on Rebrickable. Choose per row, or one choice for all.</p>'
                   f'<div style="display:flex;gap:10px;flex-wrap:wrap">{btn("Keep Brick Work for all", "sec sm")}{btn("Take Rebrickable for all", "sec sm")}</div>')
            + foot(btn('Open sync log', 'q'), btn('Done', 'sec')))


def long_run(ph):
    """A run of 4,000 changes: hours, not seconds. It goes on if the page closes; if the server restarts it stops safely and shows what went out."""
    main = card('3,840 of 4,000 done', f'{prog(3840, 4000)}<p class="mono" style="{mono}">about 3 min left · 1 request a second · budget today 810 / 1,000</p>'
                '<div class="ninfo">You can close this page, the browser or the tablet. The run keeps going on the server and shows in Jobs. If the server restarts, the run stops safely and shows what went out. Finished steps stay done.</div>'
                f'<div style="display:flex;gap:10px;flex-wrap:wrap">{btn("Stop after this one", "sec sm")}{btn("Open Jobs", "q sm")}</div>')
    return head('Rebrickable', 'Running 4,000 changes, started 19 Nov, 15:02', ph) + steps('Run', ph) + main


def nothing(ph):
    """The preview of a run when both sides already match."""
    main = card('Everything already matches', '<p class="n">Compared 1,284 sets, 312 part lines and 48 wishes with Rebrickable. There is nothing to change here or there.</p>'
                + kv([('Compared', '19 Nov, 16:51'), ('Last change', '12 Nov, run of 41 changes'), ('Next check', 'when you run again')])
                + f'<div style="display:flex;gap:10px;flex-wrap:wrap">{btn("Compare again", "sec sm")}</div>')
    return head('Rebrickable', 'Preview', ph) + steps('Preview', ph) + main + foot(btn('Back', 'q'), btn('Done', 'sec'))


FRAMES3 = [('R3-01', '54-sync-rate-limit', rate_limit), ('R3-02', '55-sync-budget-used', budget_used), ('R3-03', '56-sync-conflicts-waiting', conflicts),
           ('R3-04', '57-sync-long-run', long_run), ('R3-05', '58-sync-nothing-to-sync', nothing)]
N.FRAMES = FRAMES3
N.DRAFTS = []

if __name__ == '__main__':
    raise SystemExit(N.main(*sys.argv[1:3]))
