"""Commission N (Sync and files, #517), round 1: the Sync hub and the Rebrickable flow in B′, light and dark, 1440 and 390.

Built on the approved round 0 wireframes (design/mockups, W0-01 to W0-08) and on the B′ frame source (design/sources/b/b_frames.py):
its stylesheet, shells, tokens, dark swaps and components are imported, never copied. New CSS (NCSS) uses tokens only, so dark comes
from b_frames.darken() unchanged. Content is the B′ sample world (b_frames.SETS); committed frames show empty tiles with their alt text.
A frame is as tall as its content (shot whole); the review marks the first-screen fold.

    python n_frames.py build [OUTDIR]   write OUTDIR/<folder>/<theme>-<width>.html and .png; OUTDIR is design/screens-b by default
    python n_frames.py check [OUTDIR]   rebuild and compare with OUTDIR (HTML byte for byte, PNG within 0.1 %, as b_frames' check)
    python n_frames.py narrow OUTDIR    the phone frames at 320 and 375 px into OUTDIR/narrow (outside design/)

Round 1 is approved (Ulf, 2026-11-19, version 4 of the N review artifact): FRAMES build into design/screens-b/17-sync-hub to
24-result. A later round's drafts go in DRAFTS and build only into an OUTDIR outside design/ until Ulf approves them.
An OUTDIR outside design/ needs OUTDIR/../fonts pointing at design/fonts (the frames load ../../fonts).
Renderer: Playwright Chromium at device scale 2 (BRAND_CHROMIUM may name a Chromium binary).
"""
import math, pathlib, shutil, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'b'))
import b_frames as B  # noqa: E402

ic, cb, tag_tint = B.ic, B.cb, 'rgba(26,30,30,.18)'
HATCHED = 'background:' + B.HATCH.replace('var(--tw-text)', tag_tint)   # the hatched status tag as b_frames' components sheet draws it, swapped for dark by darken()

NCSS = '''
.nwrap{display:flex;flex-direction:column;gap:20px}
.nback{display:flex;align-items:center;gap:6px;color:var(--tw-accent-text);font:600 14px var(--tw-font)}
.ncard{background:var(--tw-surface);border:1px solid var(--tw-divider);border-radius:var(--tw-r-2);padding:16px;display:flex;flex-direction:column;gap:12px;min-width:0}
.ncard h2{font:600 18px/24px var(--tw-font);display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.ncard .n{font-size:13.5px;color:var(--tw-text-2)}
.ngrid{display:grid;gap:16px} .g4{grid-template-columns:repeat(4,minmax(0,1fr))} .g2{grid-template-columns:repeat(2,minmax(0,1fr))}
.tags{display:flex;gap:6px;flex-wrap:wrap}
.ntbl{width:100%;border-collapse:collapse;font-size:14px}
.ntbl th{font:600 12px var(--tw-font-label);letter-spacing:.12em;text-transform:uppercase;color:var(--tw-text-muted);text-align:left;padding:0 12px 8px 0;border-bottom:1.5px solid var(--tw-rule)}
.ntbl td{padding:10px 12px 10px 0;border-bottom:1px solid var(--tw-divider);vertical-align:middle}
.nrow{display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--tw-divider);flex-wrap:wrap}
.nrow .id{flex:1;min-width:0} .nrow .id b{font:600 15px var(--tw-font);display:block} .nrow .id span{font-size:13px;color:var(--tw-text-2)}
.nrow .act{font-size:14px;white-space:nowrap}
.nsteps{display:flex;gap:6px}
.nsteps div{flex:1;border-top:3px solid var(--tw-divider);padding-top:7px;font:600 12px var(--tw-font-label);letter-spacing:.1em;text-transform:uppercase;color:var(--tw-text-muted);white-space:nowrap}
.nsteps div.done{border-top-color:var(--tw-text);color:var(--tw-text-2)} .nsteps div.on{border-top-color:var(--tw-accent);color:var(--tw-text)}
.nsteps i{font:500 12px var(--tw-mono);font-style:normal;margin-right:6px}
.pstep{font:600 12px var(--tw-font-label);letter-spacing:.1em;text-transform:uppercase;color:var(--tw-text-2)} .pstep b{color:var(--tw-text)}
.pseg{display:flex;gap:4px;margin-top:8px} .pseg i{flex:1;height:3px;background:var(--tw-divider)} .pseg i.done{background:var(--tw-text)} .pseg i.on{background:var(--tw-accent)}
.rad{display:flex;gap:12px;align-items:flex-start;padding:10px 0;border-bottom:1px solid var(--tw-divider)}
.rad>i{width:22px;height:22px;flex:none;border:1.5px solid var(--tw-text);border-radius:50%;margin-top:1px;position:relative}
.rad>i.on{border-color:var(--tw-accent)} .rad>i.on::after{content:"";position:absolute;inset:4px;border-radius:50%;background:var(--tw-accent)}
.rad b{font:600 14.5px var(--tw-font);display:block} .rad span{font-size:13px;color:var(--tw-text-2)}
.chk{display:flex;gap:12px;align-items:center;padding:9px 0;border-bottom:1px solid var(--tw-divider);font-size:14.5px}
.chk .r{margin-left:auto;font:400 13px var(--tw-mono);color:var(--tw-text-2)}
.select{height:44px;border:1px solid var(--tw-text-muted);border-radius:var(--tw-r-1);background:var(--tw-surface);display:flex;align-items:center;padding:0 12px;font:400 15px var(--tw-font);color:var(--tw-text)}
.select::after{content:"";margin-left:auto;width:8px;height:8px;border-right:1.5px solid var(--tw-text);border-bottom:1.5px solid var(--tw-text);transform:rotate(45deg) translate(-2px,-2px)}
.nfoot{display:flex;flex-wrap:wrap;align-items:center;gap:14px;border-top:1.5px solid var(--tw-rule);padding-top:14px}
.btn.q{background:transparent;color:var(--tw-accent-text);padding:0 4px}
.btn.lg{height:48px;font-size:16px;padding:0 22px}
.ninfo{border-left:3px solid var(--tw-text);background:var(--tw-surface-2);padding:12px 14px;font-size:14px;border-radius:0 var(--tw-r-1) var(--tw-r-1) 0}
.prog{display:flex;height:12px} .prog i{display:block}
.src.col{flex-direction:column}
.fchips{display:flex;gap:8px;flex-wrap:wrap}
.fchip{display:inline-flex;align-items:center;gap:6px;height:34px;padding:0 12px;border:1.5px solid var(--tw-divider);border-radius:3px;font:500 13.5px var(--tw-font);color:var(--tw-text-2)}
.fchip.on{border-color:var(--tw-accent);background:var(--tw-accent-soft);color:var(--tw-accent)}
.fchip .mono{font-size:12px}
'''


def page(body, w, h):
    return B.page6(body, w, h).replace('</style>', NCSS + '</style>', 1)


def tag(text, kind=''):
    if kind == 'hatch':
        return f'<span class="tag" style="{HATCHED}">{text}</span>'
    return f'<span class="tag{" dash" if kind == "dash" else ""}">{text}</span>'


def phone_shell(main):
    subs = ''.join(f'<span class="{"on" if s == "Sync" else ""}">{s}</span>' for s in B.GROUPS['Workbench'])
    tb = ''.join(f'<div class="{"on" if g == "Workbench" else ""}">{ic(i, 22)}<span>{g}</span>{"<b></b>" if g == "Workbench" else ""}</div>'
                 for g, i in (('Collection', 'sets'), ('Workbench', 'sliders'), ('Planning', 'tag'), ('Manage', 'wrench')))
    return (f'<div style="position:relative;height:100%"><div class="ptop">{B.lockup()}<span style="margin-left:auto;color:var(--tw-text-2)">{ic("search", 22)}</span>'
            f'<span style="color:var(--tw-text-2)">{ic("plus", 22)}</span></div><div class="psub">{subs}</div>{main}<div class="tabbar">{tb}</div></div>')


def frame(fn, ph):
    inner = fn(ph)
    if ph:
        return phone_shell(f'<div class="nwrap" style="padding:16px 16px 0">{inner}</div>')
    return B.desk_shell('Workbench', 'Sync', f'<div class="page nwrap">{inner}</div>')


def head(title, sub, ph, right='', back=True):
    h1 = 'font:600 26px/32px var(--tw-font)' if ph else ''
    b = f'<div class="nback">{ic("back", 16)}Sync</div>' if back else ''
    return (f'{b}<div class="head"><div style="flex:1;min-width:0"><div class="lbl">Workbench · Sync</div><h1 style="{h1}">{title}</h1><p>{sub}</p></div>{right}</div>')


def kv(pairs):
    return '<dl class="kv">' + ''.join(f'<dt>{k}</dt><dd>{v}</dd>' for k, v in pairs) + '</dl>'


TICK = ('<svg width="11" height="11" viewBox="0 0 12 12" style="vertical-align:-1px"><path d="M2 6.4l2.6 2.6L10 3.6" stroke="currentColor" '
        'stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>')
STEPS = ['Connect', 'Choose what', 'Pick sets', 'Preview', 'Run', 'Result']


def steps(cur, ph):
    i = STEPS.index(cur)
    if ph:
        nxt = f' · next: {STEPS[i + 1]}' if i < 5 else ''
        segs = ''.join(f'<i class="{"on" if j == i else "done" if j < i else ""}"></i>' for j in range(6))
        return f'<div><div class="pstep">Step {i + 1} of 6 · <b>{cur}</b>{nxt}</div><div class="pseg">{segs}</div></div>'
    return '<div class="nsteps">' + ''.join(
        f'<div class="{"on" if j == i else "done" if j < i else ""}"><i>{TICK if j < i else j + 1}</i>{s}</div>' for j, s in enumerate(STEPS)) + '</div>'


def foot(left, right, mid=''):
    return f'<div class="nfoot">{left}{mid}<span style="margin-left:auto"></span>{right}</div>'


def btn(text, kind=''):
    return f'<span class="btn {kind}">{text}</span>'


def seg(on, opts):
    return '<div class="seg" style="align-self:flex-start">' + ''.join(f'<span class="{"on" if o == on else ""}">{o}</span>' for o in opts) + '</div>'


def chk(label, on, right=''):
    return f'<div class="chk">{cb(on)}<span>{label}</span>{f"<span class=r>{right}</span>" if right else ""}</div>'


def rad(title, note, on=False):
    return f'<div class="rad"><i class="{"on" if on else ""}"></i><div><b>{title}</b><span>{note}</span></div></div>'


def field(label, value, sel=True):
    return f'<div class="field">{label}<div class="{"select" if sel else "input"}">{value}</div></div>'


def ptile(alt):
    return f'<div class="ptile">{alt}</div>'


def prog(done, total):
    p = done / total * 100
    rest = '' if done == total else '<i style="flex:1;border:1.5px dashed var(--tw-text-2);border-left:none"></i>'
    return f'<div class="prog"><i style="width:{p:.2f}%;background:var(--tw-accent)"></i>{rest}</div>'


def drow(lead, name, meta, st, act, ph, minw=0):
    """A difference row: on the phone the status and the action go on a line under the name, so the name keeps its width."""
    if ph:
        return (f'<div class="nrow">{lead}<div class="id"><b>{name}</b><span>{meta}</span>'
                f'<div style="display:flex;flex-wrap:wrap;gap:8px 10px;align-items:center;margin-top:6px">{st}<span class="act" style="white-space:normal">{act}</span></div></div></div>')
    return (f'<div class="nrow">{lead}<div class="id"><b>{name}</b><span>{meta}</span></div>{st}'
            f'<span class="act" style="{f"min-width:{minw}px" if minw else ""}">{act}</span></div>')


def S(n):
    return B.SETS[n]


# ---- N1-01 the Sync hub (#518) ----------------------------------------------------------------------------------------
CARDS = [('Rebrickable', [tag('Connected'), tag('3 changes waiting', 'dash')], [('Account', 'brickfan'), ('Last sync', '18 Nov, 21:40')],
          'Set lists, wishlist, part lists and Lost Parts; minifigures as a check', 'Open'),
         ('Brickset', [tag('Connected'), tag('In sync')], [('Account', 'brickfan'), ('Last sync', '12 Nov, 08:15')],
          'Sets with counts, notes, rating and flags; minifigures', 'Open'),
         ('BrickLink', [tag('Not connected', 'dash')], [('Account', 'none'), ('Last sync', 'Never')],
          'Store inventory, orders, price guide; wanted lists by file', 'Connect'),
         ('Brick Owl', [tag('Not connected', 'dash')], [('Account', 'none'), ('Last sync', 'Never')],
          'Collection lots, wishlists, inventory, orders; a daily budget per kind', 'Connect')]
LOG = [('18 Nov, 21:40', 'Rebrickable', 'Into Brick Work', '2 sets, 4 Lost Parts', tag('Done')),
       ('18 Nov, 21:40', 'Rebrickable', 'To Rebrickable', '3 quantities', tag('3 changes waiting', 'dash')),
       ('15 Nov, 09:12', 'Rebrickable', 'Into Brick Work', '1 set', tag('Done')),
       ('15 Nov, 09:12', 'Rebrickable', 'To Rebrickable', '1 quantity', tag('Done')),
       ('12 Nov, 08:15', 'Brickset', 'Into Brick Work', '1 set', tag('Done')),
       ('3 Nov, 19:02', 'File', 'Import', 'BrickLink XML, 140 lots', tag('Done'))]


def hub(ph):
    cards = ''.join(f'<div class="ncard"><h2>{t}</h2><div class="tags">{"".join(tg)}</div>{kv(k)}<div class="n" style="flex:1">{what}</div>'
                    f'<span class="btn sec sm" style="align-self:flex-start">{a}</span></div>' for t, tg, k, what, a in CARDS)
    files = (f'<div class="ncard" style="{"" if ph else "flex-direction:row;align-items:center;gap:28px"}"><h2 style="min-width:160px">Import &amp; export</h2>'
             f'{kv([("Last import", "3 Nov, BrickLink XML"), ("Last export", "Never")])}'
             '<div class="n" style="flex:1">Every file format in and out, and your own complete export</div>'
             '<span class="btn sec sm" style="align-self:flex-start">Open</span></div>')
    if ph:
        log = ''.join(f'<div class="nrow"><div class="id"><b>{site} · {d}</b><span>{w}</span><br><span class="mono">{when}</span></div>{st}</div>' for when, site, d, w, st in LOG)
    else:
        log = ('<table class="ntbl"><tr><th>When</th><th>Site</th><th>Direction</th><th>What</th><th></th></tr>'
               + ''.join(f'<tr><td class="mono">{a}</td><td>{b}</td><td>{c}</td><td>{d}</td><td style="text-align:right">{e}</td></tr>' for a, b, c, d, e in LOG) + '</table>')
    how = ('<div class="ncard"><h2>How sync works</h2><p class="n">A run never deletes anything here unless you choose. Items that are only here are listed '
           'for you to decide. Changes to a site are always shown first, and removals there wait until you tick them.</p></div>')
    return (head('Sync', 'Bring a collection in from another site, work on it here, then send the changes back.', ph, back=False)
            + f'<div class="ngrid {"" if ph else "g4"}">{cards}</div>{files}'
            + f'<div class="ncard"><h2>Sync log</h2>{log}</div>{how}')


# ---- N1-02 Rebrickable at rest (#519) ----------------------------------------------------------------------------------
WHAT = [('Owned sets', 'Both ways', '2 set lists: Main collection, Bought 2026'),
        ('Wishlist', 'Both ways', 'Rebrickable Wishlist ↔ wishlist Wanted'),
        ('Loose stock', 'Into Brick Work', '1 part list: Bulk bin'),
        ('Lost Parts', 'Both ways', 'Rule: Rebrickable wins per part'),
        ('Minifigures', 'Check only', 'Compared with your copies, never changed')]


def rest(ph):
    start = btn('Start a sync', 'lg')
    if ph:
        what = ''.join(f'<div class="nrow"><div class="id"><b>{a}</b><span>{c}</span></div>{tag(b)}</div>' for a, b, c in WHAT)
    else:
        what = ('<table class="ntbl"><tr><th>What</th><th>Direction</th><th>Linked to</th></tr>'
                + ''.join(f'<tr><td><b>{a}</b></td><td>{tag(b)}</td><td>{c}</td></tr>' for a, b, c in WHAT) + '</table>')
    acct = (f'<div class="ncard"><h2>Your Rebrickable account {tag("Connected")}</h2>'
            + kv([('Account', 'brickfan'), ('API key', 'Set · checked 18 Nov'), ('Speed', 'About 1 request a second'), ('Budget today', '<span class="mono">140 / 1,000</span>')])
            + '<div style="display:flex;gap:10px;flex-wrap:wrap"><span class="btn sec sm">Test</span><span class="btn q sm">Change</span><span class="btn q sm">Remove</span></div></div>')
    sets = f'<div class="ncard"><h2>What syncs</h2>{what}<span class="btn sec sm" style="align-self:flex-start">Change what syncs</span></div>'
    last = ('<div class="ncard"><h2>Last runs</h2>'
            + drow('', 'Run · 18 Nov, 21:40', '2 sets, 4 Lost Parts added here · 3 rows to Rebrickable still waiting', tag('3 changes waiting', 'dash'),
                   '<span class="btn sec sm">Retry</span> <span class="btn q sm">Undo this run</span>', ph) +
            f'<div class="nrow"><div class="id"><b>Run · 15 Nov, 09:12</b><span>1 set added here · 1 quantity sent</span></div>{tag("Done")}</div>'
            '<p class="n">Rebrickable keeps its own link to your account. Each run counts against Brick Work’s daily budget for Rebrickable.</p></div>')
    right = '' if ph else start
    body = head('Rebrickable', 'Last run 18 Nov, 21:40', ph, right)
    return body + (start + acct + sets + last if ph else f'<div class="ngrid g2" style="align-items:start">{acct}{last}</div>{sets}')


# ---- N1-03 connect ----------------------------------------------------------------------------------------------------
def connect(ph):
    key = (f'<div class="ncard"><h2>1 · API key {tag("Set")}</h2><p class="n">The key reads Rebrickable’s catalogue. Your account lets Brick Work read and change your lists.</p>'
           + field('API key', '••••••••••••3f2a', sel=False)
           + '<div style="display:flex;gap:10px"><span class="btn sec sm">Test</span><span class="btn q sm">Remove</span></div></div>')
    acct = (f'<div class="ncard"><h2>2 · Your Rebrickable account {tag("Not connected", "dash")}</h2>'
            '<p class="n">Your username and password go straight to Rebrickable once. Brick Work keeps only the token Rebrickable returns, never the password.</p>'
            f'<div class="ngrid {"" if ph else "g2"}" style="gap:12px">{field("Username or email", "brickfan", sel=False)}{field("Password", "••••••••", sel=False)}</div>'
            '<div style="display:flex;gap:10px;flex-wrap:wrap"><span class="btn">Connect</span><span class="btn q">Paste a user token instead</span></div>'
            '<p class="n">A user token is stored encrypted. It is never shown again.</p></div>')
    cols = key + acct if ph else f'<div class="ngrid g2" style="align-items:start">{key}{acct}</div>'
    return (head('Rebrickable', 'Connect your account, choose what to sync, then run the sync.', ph) + steps('Connect', ph) + cols
            + foot(btn('Cancel', 'q'), btn('Next: choose what', 'sec')))


# ---- N1-04 choose what ------------------------------------------------------------------------------------------------
def choose(ph):
    d = (lambda on: seg({'Both ways': 'Both', 'Into Brick Work': 'In'}.get(on, on), ['In', 'Both', 'Out', 'Off'])) if ph else \
        (lambda on: seg(on, ['Into Brick Work', 'Both ways', 'To Rebrickable', 'Off']))
    owned = ('<div class="ncard"><h2>Owned sets</h2>' + d('Both ways')
             + '<p class="n">Tick the set lists that hold sets you own. None ticked means every list except the wishlist list.</p>'
             + chk('Main collection', True, '5 sets') + chk('Bought 2026', True, '2 sets') + chk('Lent to a friend', False, '1 set')
             + field('Send changes to', 'Main collection') + '</div>')
    wish = ('<div class="ncard"><h2>Wishlist</h2>' + d('Both ways')
            + f'<div class="ngrid {"" if ph else "g2"}" style="gap:12px">{field("Wanted sets · go to the wishlist", "Wishlist")}{field("Wishlist here", "Wanted")}</div></div>')
    loose = ('<div class="ncard"><h2>Loose stock</h2>' + seg('In' if ph else 'Into Brick Work', ['In', 'Off'] if ph else ['Into Brick Work', 'Off'])
             + '<p class="n">Tick the part lists that are loose parts. None is ticked until you choose.</p>'
             + chk('Bulk bin', True, '1,830 parts') + chk('Sorted Technic', False, '640 parts')
             + field('Put new loose parts in', 'One lot per part list') + '</div>')
    lost = ('<div class="ncard"><h2>Lost Parts</h2>' + d('Both ways')
            + '<p class="n">Marks the parts on your Lost Parts list as missing on the matching copy, and sends the parts you find or newly miss here back.</p>'
            + '<div class="lbl" style="margin-top:4px">Into Brick Work: which count wins</div>'
            + rad('Add only', 'The sync only adds missing marks. Where both sides have a count, the larger is kept. Nothing is cleared.')
            + rad('Rebrickable wins per part', 'For a part Rebrickable lists as lost, Rebrickable’s count replaces yours, also when it is smaller. Marks on other parts stay.', True)
            + rad('Rebrickable wins per set', 'A set with at least one Lost Part on Rebrickable becomes exactly Rebrickable’s list. Other missing marks on that copy are cleared.')
            + rad('Rebrickable wins everywhere', 'Every synced set becomes exactly Rebrickable’s list. A set with no Lost Parts there loses its missing marks.')
            + '<div class="lbl" style="margin-top:6px">To Rebrickable</div><p class="n">Parts newly missing here are added to Lost Parts there; parts found here are removed there. Removals are unticked until you tick them.</p>'
            + field('Which count wins', 'Brick Work wins per part') + '</div>')
    figs = ('<div class="ncard"><h2>Minifigures</h2>' + seg('Check only', ['Check only', 'Off'])
            + '<p class="n">Rebrickable derives your minifigures from your sets. Brick Work compares them with your copies and lists the differences; nothing is changed on either side.</p></div>')
    both = f'<div class="ncard"><h2>When both sides differ</h2>{field("", "Ask me each time")}</div>'
    if ph:
        cols = owned + wish + loose + lost + figs + both
    else:
        cols = (f'<div class="ngrid g2" style="align-items:start"><div class="nwrap" style="gap:16px">{owned}{wish}{loose}</div>'
                f'<div class="nwrap" style="gap:16px">{lost}{figs}{both}</div></div>')
    return (head('Rebrickable', 'Choose what to sync, and in which direction. You can change it later.', ph) + steps('Choose what', ph) + cols
            + foot(btn('‹ Back', 'q'), btn('Next: pick sets', 'sec')))


# ---- N1-05 pick sets --------------------------------------------------------------------------------------------------
ORDER = ['7213-1', '7938-1', '10254-1', '10210-1', '31120-1', '8043-1', '21028-1']
PICKED = {'7213-1', '7938-1', '10254-1', '31120-1'}
THEMES = [('Fire', 1, True), ('Trains', 1, True), ('Creator', 1, True), ('Pirates II', 1, False), ('Creator 3-in-1', 1, True), ('Technic', 1, False), ('Skylines', 1, False)]


def pick(ph):
    by = seg('Theme', ['All', 'List', 'Theme', 'Year', 'One']) if ph else seg('By theme', ['All linked', 'By list', 'By theme', 'By year', 'One by one'])
    chips = '<div class="fchips">' + ''.join(f'<span class="fchip{" on" if on else ""}">{t} <span class="mono">{n}</span></span>' for t, n, on in THEMES) + '</div>'
    rows = ''.join(f'<div class="nrow">{cb(n in PICKED)}{ptile(n)}<div class="id"><b>{S(n)["name"]}</b><span><span class="mono">{n}</span> · {S(n)["meta"]}</span></div></div>' for n in ORDER)
    count = (f'<div class="ninfo"><b>{len(PICKED)} of {len(ORDER)} sets picked</b> · loose stock: Bulk bin · Lost Parts: on the picked sets</div>')
    return (head('Rebrickable', 'Pick the sets this run covers. Sets you do not pick stay as they are on both sides.', ph) + steps('Pick sets', ph)
            + f'<div class="ncard"><h2>Which sets</h2>{by}{chips}{field("", "Number or name", sel=False)}<div>{rows}</div></div>' + count
            + foot(btn('‹ Back', 'q'), btn('Next: preview', 'sec')))


# ---- N1-06 preview, with the conflict choice (marketing's screenshot 2) ------------------------------------------------
# 9 differences: 4 set rows, 1 changed in both places, 2 Lost Parts rows, 2 loose lots. Into Brick Work 6, to Rebrickable 2, both 1.
PREV = [('31109-1', 'Pirate Ship', 'Owned', ('New there', ''), 'Add 1 here', True),
        ('21318-1', 'Tree House', 'Wishlist', ('New there', ''), 'Add to Wanted here', True),
        ('10254-1', 'Winter Holiday Train', 'Owned', ('Only here', 'dash'), 'Add 1 there', True),
        ('31120-1', 'Medieval Castle', 'Owned', ('Gone there', 'hatch'), 'Remove here', False)]
TICKED = sum(r[5] for r in PREV) + 1 + 2    # set rows ticked, the 7938-1 Lost Parts row, the two loose lots; 7213-1's marks below too
RUN_INTO, RUN_OUT = 5, 2                    # into: 10220-1, 21313-1, 7213-1's marks, 2 loose lots; out: 10254-1, 7938-1's found parts


def preview(ph):
    tabs = '<div class="fchips">' + ''.join(f'<span class="fchip{" on" if i == 0 else ""}">{t} <span class="mono">{n}</span></span>' for i, (t, n) in enumerate(
        (('All', 9), ('Into Brick Work', 6), ('To Rebrickable', 2), ('Changed in both places', 1), ('Lost Parts', 2), ('Loose stock', 2)))) + '</div>'
    rows = ''.join(drow(cb(on) + ptile(no), name, f'<span class="mono">{no}</span> · {kind}', tag(*st), act, ph, 170) for no, name, kind, st, act, on in PREV)
    choice = '<div class="src{}" style="{}"><span class="on">Keep 2 here<small>Nothing sent</small></span><span>Take 1 from Rebrickable<small>Brick Work becomes 1</small></span><span>Send 2 to Rebrickable<small>Rebrickable becomes 2</small></span></div>'
    conflict = (f'<div class="ncard"><h2>Changed in both places <span class="mono" style="font-weight:500">1</span></h2>'
                '<p class="n">1 item changed here and on Rebrickable since the last run on 18 Nov. Nothing happens to it unless you choose.</p>'
                f'<div class="nrow" style="border-bottom:none">{ptile("7213-1")}<div class="id"><b>{S("7213-1")["name"]}</b><span><span class="mono">7213-1</span> · quantity · here 2 · Rebrickable 1</span></div></div>'
                + choice.format(' col' if ph else '', 'width:100%' if ph else 'width:100%;max-width:720px')
                + '<p class="n">Checks, storage and notes stay here either way; only quantities are compared.</p></div>')
    lost = (f'<div class="ncard"><h2>Lost Parts <span class="mono" style="font-weight:500">2</span></h2><p class="mono" style="font-size:13px;color:var(--tw-text-2)">3 added · 0 replaced · 2 cleared there · 0 not matched · 1 set needs a copy</p>'
            f'<div class="nrow">{cb(True)}<div class="id"><b>{S("7213-1")["name"]}</b><span><span class="mono">7213-1</span> · 3 parts · 5 pieces · 2 copies here</span></div>'
            f'{tag("Choose a copy", "dash")}<div style="min-width:200px;{"width:100%" if ph else ""}">{field("Mark the parts on", "Copy 2")}</div></div>'
            f'<div class="nrow">{cb(True)}<div class="id"><b>{S("7938-1")["name"]}</b><span><span class="mono">7938-1</span> · to Rebrickable: 2 parts found here, remove from Lost Parts</span></div></div></div>')
    loose = (f'<div class="ncard"><h2>Loose stock <span class="mono" style="font-weight:500">2</span></h2>'
             + ''.join(drow(cb(True) + ptile(p), n, f'<span class="mono">{p}</span> · {c} · from Bulk bin', tag('New there'), f'Add {q} here', ph)
                       for n, p, c, q in (('Brick 2 × 4', '3001', 'Red', 24), ('Plate 1 × 2', '3023', 'Light Bluish Gray', 40)))
             + f'<div style="max-width:320px">{field("Put in", "Lot · Bulk bin")}</div></div>')
    before = ('<div class="ninfo"><b>Before you send.</b> Brick Work’s Undo cannot take a sent change back. Removals are unticked until you tick them.'
              f'<div style="margin-top:8px">{kv([("Requests", "about <span class=mono>9</span>"), ("Time", "about <span class=mono>10</span> seconds at 1 request a second"), ("Budget today", "<span class=mono>140 / 1,000</span>")])}</div></div>')
    n = RUN_INTO + RUN_OUT
    ft = foot(btn('‹ Back', 'q'), btn(f'Run {n} changes', 'lg'), f'<span class="mono" style="font-size:13px;color:var(--tw-text-2)">{n} of 9 chosen</span>')
    lead = '<p class="n" style="font-size:14px;color:var(--tw-text-2)">Nothing in Brick Work is deleted unless you choose. Choose what happens to each difference, then run.</p>'
    setsblock = f'<div class="ncard">{tabs}{field("", "Number or name", sel=False)}<div>{rows}</div></div>'
    if ph:
        body = lead + conflict + setsblock + lost + loose + before
    else:   # the conflict choice sits above the fold at 1440 (marketing's screenshot 2)
        body = lead + conflict + setsblock + f'<div class="ngrid g2" style="align-items:start">{lost}{loose}</div>' + before
    return (head('Rebrickable', '4 sets compared · checked 19 Nov, 16:52 · last run 18 Nov, 21:40', ph) + steps('Preview', ph) + body + ft)


# ---- N1-07 run --------------------------------------------------------------------------------------------------------
def run(ph):
    done_in, done = 4, 4
    total = RUN_INTO + RUN_OUT
    blocks = (f'<div class="ncard"><h2>Into Brick Work</h2><p class="mono" style="font-size:13px">{done_in} of {RUN_INTO} done</p>{prog(done_in, RUN_INTO)}'
              '<p class="n">Now: Bulk bin, 2nd loose lot</p></div>'
              f'<div class="ncard"><h2>To Rebrickable</h2><p class="mono" style="font-size:13px">0 of {RUN_OUT} sent</p>{prog(0, RUN_OUT)}'
              '<p class="n">Starts when everything here is done.</p></div>')
    return (head('Rebrickable', f'Running {total} changes', ph) + steps('Run', ph)
            + f'<div class="ncard"><h2>{done} of {total} done</h2>{prog(done, total)}'
            '<p class="mono" style="font-size:13px;color:var(--tw-text-2)">about 3 s left · about 1 request a second · budget today 144 / 1,000</p>'
            '<p class="n">You can leave this page. The run goes on and shows in Jobs.</p><span class="btn sec sm" style="align-self:flex-start">Stop after this one</span></div>'
            + (blocks if ph else f'<div class="ngrid g2">{blocks}</div>'))


# ---- N1-08 result -----------------------------------------------------------------------------------------------------
def result(ph):
    here = (f'<div class="ncard"><h2>Here in Brick Work {tag(f"{RUN_INTO} changed")}</h2>'
            '<p class="n">1 set and 1 wish added · 2 loose lots added to Bulk bin · 3 parts marked missing on Copy 2 of 7213-1.</p>'
            '<span class="btn sec sm" style="align-self:flex-start">Undo this run</span><p class="n">Undo takes back everything this run changed here, in one step. It cannot change what was sent to Rebrickable.</p></div>')
    there = (f'<div class="ncard"><h2>On Rebrickable {tag("1 sent")} {tag("1 failed", "hatch")}</h2>'
             '<p class="n">2 parts removed from Lost Parts for 7938-1.</p>'
             + drow(ptile('10254-1'), S('10254-1')['name'], '<span class="mono">10254-1</span> · add 1 to Main collection · Rebrickable did not answer', '', '<span class="btn sec sm">Retry</span>', ph) +
             '<div class="ninfo">A change on Rebrickable cannot be undone here. To reverse it, change it back on Rebrickable or send again.</div></div>')
    figs = (f'<div class="ncard"><h2>Minifigures check</h2><p class="n">1 minifigure Rebrickable lists is not on your copy of {S("7938-1")["name"]} (<span class="mono">7938-1</span>).</p>'
            '<span class="btn q sm" style="align-self:flex-start">Open the set</span></div>')
    total = RUN_INTO + RUN_OUT
    return (head('Rebrickable', f'Finished 19 Nov, 16:54 · {total - 1} of {total} done, 1 failed', ph) + steps('Result', ph)
            + (here + there + figs if ph else f'<div class="ngrid g2" style="align-items:start">{here}{there}</div>{figs}')
            + foot(btn('Open sync log', 'q'), btn('Done', 'sec')))


# (review id, folder under screens-b, body): round 1, approved
FRAMES = [('N1-01', '17-sync-hub', hub), ('N1-02', '18-rebrickable', rest), ('N1-03', '19-rebrickable-connect', connect),
          ('N1-04', '20-rebrickable-choose-what', choose), ('N1-05', '21-rebrickable-pick-sets', pick),
          ('N1-06', '22-rebrickable-preview', preview), ('N1-07', '23-rebrickable-run', run), ('N1-08', '24-rebrickable-result', result)]
DRAFTS = []   # a later round's frames, same shape, built only outside design/ until approved
SIZES = ((False, 1440, 1000), (True, 390, 844))


def _launch(pw):
    import os
    exe = os.environ.get('BRAND_CHROMIUM')
    return pw.chromium.launch(executable_path=exe) if exe else pw.chromium.launch()


def build_items(out, frames):
    """{key: (html, w, h)}: light and dark per frame and width, each as tall as its content (measured in a first pass)."""
    from playwright.sync_api import sync_playwright
    items = {}
    with sync_playwright() as pw:
        b = _launch(pw)
        for _, fid, fn in frames:
            for ph, w, h0 in SIZES:
                body = frame(fn, ph)
                probe = out / fid / f'probe-{w}.html'
                probe.parent.mkdir(parents=True, exist_ok=True)
                probe.write_text(page(body, w, 6000))
                pg = b.new_page(viewport={'width': w, 'height': 6000})
                pg.goto(probe.as_uri(), wait_until='load')
                pg.evaluate("document.fonts.ready")
                bottom = pg.evaluate("Math.max(...[...document.querySelectorAll('.nwrap *')].map(e => e.getBoundingClientRect().bottom))")
                pg.close()
                probe.unlink()
                h = max(h0, math.ceil(bottom) + (78 + 24 if ph else 48))
                light = page(body, w, h)
                assert '#fff' not in NCSS
                items[f'{fid}/light-{w}.html'] = (light, w, h)
                items[f'{fid}/dark-{w}.html'] = (None, w, h)   # filled below with the on-dark lockup
        b.close()
    lk, B.LOCKUP = B.LOCKUP, B.LOCKUP_DARK
    try:
        for _, fid, fn in frames:
            for ph, w, _ in SIZES:
                _, _, h = items[f'{fid}/dark-{w}.html']
                items[f'{fid}/dark-{w}.html'] = (B.darken(page(frame(fn, ph), w, h)), w, h)
    finally:
        B.LOCKUP = lk
    return items


def render(items, out):
    from playwright.sync_api import sync_playwright
    shots = {}
    with sync_playwright() as pw:
        b = _launch(pw)
        for key, (html, w, h) in items.items():
            path = out / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(html)
            pg = b.new_page(viewport={'width': w, 'height': h}, device_scale_factor=2, color_scheme='dark' if '/dark-' in key else 'light', reduced_motion='reduce')
            pg.goto(path.as_uri(), wait_until='load')
            pg.evaluate("Promise.all(document.fonts ? [...document.fonts].map(f => f.load()) : []).then(() => document.fonts.ready)")
            pg.wait_for_timeout(100)
            if pg.evaluate('document.documentElement.scrollWidth > innerWidth'):
                raise SystemExit(f'FRAMES: {key} runs past the right edge')
            cut = pg.evaluate("[...document.querySelectorAll('.nwrap *')].filter(e => e.getBoundingClientRect().bottom > innerHeight - (innerWidth < 500 ? 78 : 0) + 1).length")
            if cut:
                raise SystemExit(f'FRAMES: {key} cut at the bottom ({cut} elements)')
            shots[key] = pg.screenshot()
            pg.close()
        b.close()
    return shots


def narrow(out):
    """The phone frames at 320 and 375 px: nothing may run past the right edge (design-builder, narrow widths)."""
    from playwright.sync_api import sync_playwright
    bad = []
    with sync_playwright() as pw:
        b = _launch(pw)
        for rid, _, fn in FRAMES + DRAFTS:
            for w in (320, 375):
                path = out / 'narrow' / f'{rid}-{w}.html'
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(page(frame(fn, True), w, 3200))   # OUTDIR/narrow/ is two levels below OUTDIR/.., as the frames
                pg = b.new_page(viewport={'width': w, 'height': 900})
                pg.goto(path.as_uri(), wait_until='load')
                pg.evaluate("document.fonts.ready")
                over = pg.evaluate("[...document.querySelectorAll('body *')].filter(e => e.getBoundingClientRect().right > innerWidth + 0.5).map(e => e.className || e.tagName).slice(0, 5)")
                if over or pg.evaluate('document.documentElement.scrollWidth > innerWidth'):
                    bad.append(f'{rid}@{w}: {over}')
                pg.close()
        b.close()
    print('narrow widths OK' if not bad else 'NARROW: ' + '; '.join(bad))
    return 1 if bad else 0


def main(cmd='check', out=None):
    if cmd not in ('build', 'check', 'narrow'):
        raise SystemExit(f'n_frames: unknown command {cmd!r} (build, check or narrow)')
    out = pathlib.Path(out).resolve() if out else B.OUT.resolve()
    inside = out == B.DESIGN.resolve() or B.DESIGN.resolve() in out.parents
    if cmd == 'narrow':
        if inside:
            raise SystemExit('n_frames: narrow writes OUTDIR/narrow, so OUTDIR must lie outside design/')
        return narrow(out)
    frames = FRAMES + ([] if inside else DRAFTS)
    # Probes and renders go to a scratch folder beside OUTDIR (same depth, so ../../fonts resolves the same); check never writes OUTDIR.
    work = pathlib.Path(tempfile.mkdtemp(prefix='.n_frames-', dir=out.parent))
    try:
        items = build_items(work, frames)
        if cmd == 'build':
            for key, png in render(items, work).items():
                (out / key).parent.mkdir(parents=True, exist_ok=True)
                (out / key).write_text(items[key][0])
                (out / key).with_suffix('.png').write_bytes(png)
            print(f'Built {len(items)} N frames in {out}')
            return 0
        bad = [k for k, (html, _, _) in items.items() if not (out / k).exists() or (out / k).read_text() != html]
        if not bad:
            for key, png in render(items, work).items():
                if not B.same_pixels((out / key).with_suffix('.png').read_bytes(), png):
                    bad.append(key.replace('.html', '.png'))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print('N frames OK' if not bad else f'{len(bad)} N frames drift: {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:3]))
