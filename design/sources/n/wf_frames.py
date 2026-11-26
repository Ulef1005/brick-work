"""Commission N (Sync and files, #517), round 0: black-and-white wireframes of the Sync hub and the Rebrickable flow.

Design builder step 2: neutral base only (tokens.css, copied unchanged from the design-builder skill), system type, no brand,
no colour, no logo. Synthetic content in [brackets]; Brick Work's shipped copy is written as it is.
Usage: python wf_frames.py build   -> design/mockups/<id>-<w>.html and .png (1440 and 390, light)
Approved by Ulf 2026-11-19 ("frames approved"), review artifact https://claude.ai/artifact/1sWRRsfiYxkEgHXxKxrsUn version 2.
"""
import pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE.parents[1] / 'mockups'
BASE = (HERE.parents[1] / 'tokens' / 'tokens.css').read_text()

CSS = r'''
*{box-sizing:border-box;margin:0}
body{font:var(--tw-fs-body)/var(--tw-lh-body) var(--tw-font);color:var(--tw-text);background:var(--tw-bg)}
.top{display:flex;align-items:center;gap:24px;height:56px;padding:0 32px;border-bottom:1px solid var(--tw-divider-strong)}
.logo{width:120px;height:28px;border:1px dashed var(--tw-divider-strong);display:grid;place-items:center;font-size:12px;color:var(--tw-text-muted)}
.tabs{display:flex;gap:4px}.tabs span{padding:6px 14px;font-size:15px}.tabs .on{font-weight:700;border-bottom:3px solid var(--tw-text)}
.search{margin-left:auto;width:360px;height:36px;border:1px solid var(--tw-divider-strong);font-size:14px;color:var(--tw-text-muted);display:flex;align-items:center;padding:0 12px}
.sub{display:flex;gap:22px;padding:0 32px;height:44px;align-items:center;border-bottom:1px solid var(--tw-divider);font-size:14px;white-space:nowrap;overflow:hidden}
.sub .on{font-weight:700;text-decoration:underline;text-underline-offset:6px;text-decoration-thickness:2px}
.main{padding:28px 32px 48px;display:flex;flex-direction:column;gap:20px}
.ptop{display:flex;align-items:center;gap:14px;height:52px;padding:0 16px;border-bottom:1px solid var(--tw-divider-strong)}
.psub{display:flex;gap:18px;padding:0 16px;height:42px;align-items:center;border-bottom:1px solid var(--tw-divider);font-size:14px;white-space:nowrap;overflow:hidden}
.psub .on{font-weight:700;text-decoration:underline;text-underline-offset:6px;text-decoration-thickness:2px}
.pmain{padding:16px 16px 90px;display:flex;flex-direction:column;gap:16px}
.tabbar{position:absolute;left:0;right:0;bottom:0;height:64px;border-top:1px solid var(--tw-divider-strong);display:flex;background:var(--tw-bg)}
.tabbar div{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;font-size:12px;gap:2px}
.tabbar i{width:22px;height:22px;border:1.5px solid var(--tw-text);display:block}
.tabbar .on{font-weight:700}.tabbar .on i{background:var(--tw-text)}
.lbl{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--tw-text-muted)}
h1{font-size:28px;line-height:34px}h2{font-size:18px;line-height:24px}
.head{display:flex;gap:16px;align-items:flex-end;flex-wrap:wrap}.head>div:first-child{flex:1;min-width:0}
.head p{color:var(--tw-text-2);font-size:15px;margin-top:4px}
.back{font-size:14px;text-decoration:underline}
.card{border:1px solid var(--tw-divider-strong);padding:16px;display:flex;flex-direction:column;gap:10px;background:var(--tw-surface)}
.grid{display:grid;gap:16px}.g4{grid-template-columns:repeat(4,1fr)}.g3{grid-template-columns:repeat(3,1fr)}.g2{grid-template-columns:1fr 1fr}
.btn{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:0 18px;border:1.5px solid var(--tw-text);background:var(--tw-text);color:var(--tw-on-accent);font:600 15px var(--tw-font);white-space:nowrap}
.btn.sec{background:var(--tw-bg);color:var(--tw-text)}.btn.q{background:none;border-color:transparent;color:var(--tw-text);text-decoration:underline;padding:0 8px}
.btn.lg{min-height:56px;padding:0 28px}
.acts{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.st{display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:600;border:1px solid var(--tw-text);padding:1px 8px;white-space:nowrap}
.st.dash{border-style:dashed}.st.none{border-color:var(--tw-divider-strong);color:var(--tw-text-2);font-weight:400}
.st.fill{background:var(--tw-text);color:var(--tw-on-accent)}
.n{font-size:14px;color:var(--tw-text-2)}.mono{font-family:var(--tw-mono);font-size:13px}
dl.kv{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;font-size:14px}dl.kv dt{color:var(--tw-text-muted)}
table{border-collapse:collapse;width:100%;font-size:14px}th{text-align:left;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--tw-text-muted);font-weight:400;padding:6px 8px;border-bottom:1px solid var(--tw-divider-strong)}
td{padding:9px 8px;border-bottom:1px solid var(--tw-divider);vertical-align:top}
.steps{display:flex;gap:0;border:1px solid var(--tw-divider-strong)}.steps span{flex:1;padding:10px 12px;font-size:14px;border-right:1px solid var(--tw-divider)}
.steps span:last-child{border-right:0}.steps .on{background:var(--tw-text);color:var(--tw-on-accent);font-weight:700}.steps .done{color:var(--tw-text-2)}.steps .done::before{content:"✓ "}
.pstep{font-size:13px;color:var(--tw-text-2)}.pbar{height:6px;border:1px solid var(--tw-text);margin-top:6px}.pbar b{display:block;height:100%;background:var(--tw-text)}
.field{display:flex;flex-direction:column;gap:4px;font-size:14px;font-weight:600}.field .in{height:44px;border:1px solid var(--tw-divider-strong);font-weight:400;display:flex;align-items:center;padding:0 12px;color:var(--tw-text-muted)}
.sel::after{content:"▾";margin-left:auto;color:var(--tw-text)}
.chk{display:flex;gap:10px;align-items:flex-start;font-size:14px;min-height:32px}.chk i{width:20px;height:20px;border:1.5px solid var(--tw-text);flex:none;margin-top:2px;display:grid;place-items:center;font-style:normal;font-size:14px;font-weight:700}
.chk i.on::after{content:"✓";line-height:1}.chk .r{margin-left:auto;font-family:var(--tw-mono);font-size:13px;color:var(--tw-text-2)}
.rad i{border-radius:50%}.rad i.on::after{content:"";width:10px;height:10px;border-radius:50%;background:var(--tw-text)}
.seg{display:inline-flex;border:1.5px solid var(--tw-text)}.seg span{padding:8px 12px;font-size:13px;border-right:1px solid var(--tw-text);white-space:nowrap}.seg span:last-child{border-right:0}.seg .on{background:var(--tw-text);color:var(--tw-on-accent);font-weight:700}
.block{border:1px solid var(--tw-divider-strong);padding:16px;display:flex;flex-direction:column;gap:12px}
.block h2{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.note{font-size:13px;color:var(--tw-text-2)}.warn{border:2px solid var(--tw-text);padding:12px 14px;font-size:14px}
.row{display:flex;gap:12px;align-items:center;padding:10px 0;border-bottom:1px solid var(--tw-divider);font-size:14px;flex-wrap:wrap}
.row .id{flex:1;min-width:180px}.row .id b{display:block}.foot{display:flex;gap:12px;align-items:center;flex-wrap:wrap;border-top:1.5px solid var(--tw-text);padding-top:16px}
.chips{display:flex;gap:8px;flex-wrap:wrap}.chip{border:1px solid var(--tw-text);padding:4px 10px;font-size:13px}.chip.on{background:var(--tw-text);color:var(--tw-on-accent)}
.tile{width:56px;height:44px;border:1px solid var(--tw-divider-strong);flex:none;font-size:10px;display:grid;place-items:center;color:var(--tw-text-muted)}
'''

GROUPS = {'Collection': [], 'Workbench': ['Part Spotter', 'Set Inspector', 'Lot Sorter', 'Part Runner', 'Matchmaker', 'Build Scout', 'Orders', 'Storage', 'Sync'],
          'Planning': [], 'Manage': []}
STEPS = ['Connect', 'Choose what', 'Pick sets', 'Preview', 'Run', 'Result']


def page(body, w, h):
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="frame-size" content="{w} {h}">'
            f'<style>{BASE}{CSS}html,body{{width:{w}px;min-height:{h}px}}</style></head><body>{body}</body></html>')


def desk(main):
    tabs = ''.join(f'<span class="{"on" if g == "Workbench" else ""}">{g}</span>' for g in GROUPS)
    subs = ''.join(f'<span class="{"on" if s == "Sync" else ""}">{s}</span>' for s in GROUPS['Workbench'])
    return (f'<div class="top"><div class="logo">[logo]</div><div class="tabs">{tabs}</div><div class="search">Jump to a set, copy, figure or part</div>'
            f'<span class="btn sec">Add</span></div><div class="sub">{subs}</div><div class="main">{main}</div>')


def phone(main):
    subs = ''.join(f'<span class="{"on" if s == "Sync" else ""}">{s}</span>' for s in ['Matchmaker', 'Build Scout', 'Orders', 'Storage', 'Sync'])
    tb = ''.join(f'<div class="{"on" if g == "Workbench" else ""}"><i></i><span>{g}</span></div>' for g in GROUPS)
    return (f'<div style="position:relative;min-height:844px"><div class="ptop"><div class="logo" style="width:96px">[logo]</div>'
            f'<span style="margin-left:auto" class="n">Search</span><span class="n">Add</span></div><div class="psub">{subs}</div>'
            f'<div class="pmain">{main}</div><div class="tabbar">{tb}</div></div>')


def steps(cur, ph):
    i = STEPS.index(cur)
    if ph:
        return (f'<div><div class="pstep">Step {i + 1} of 6 · <b>{cur}</b>{" · next: " + STEPS[i + 1] if i < 5 else ""}</div>'
                f'<div class="pbar"><b style="width:{(i + 1) / 6 * 100:.0f}%"></b></div></div>')
    return '<div class="steps">' + ''.join(
        f'<span class="{"on" if s == cur else "done" if STEPS.index(s) < i else ""}">{"" if STEPS.index(s) < i else str(STEPS.index(s) + 1) + " "}{s}</span>' for s in STEPS) + '</div>'


def site_head(title, sub, ph, right=''):
    return (f'<a class="back">‹ Sync</a><div class="head"><div><div class="lbl">Workbench · Sync</div><h1>{title}</h1><p>{sub}</p></div>{right}</div>')


def chk(label, on=False, right='', rad=False):
    return f'<div class="chk{" rad" if rad else ""}"><i class="{"on" if on else ""}"></i><span>{label}</span>{f"<span class=r>{right}</span>" if right else ""}</div>'


# ---------- W0-01 hub ----------
CARDS = [
    ('Rebrickable', '<span class="st fill">Connected</span> <span class="st dash">[3] changes waiting</span>',
     [('Account', '[your username]'), ('Last sync', '[18 Nov, 21:40]')], 'Set lists, wishlist, part lists, Lost Parts; minifigures as a check', 'Open'),
    ('Brickset', '<span class="st fill">Connected</span> <span class="st">In sync</span>',
     [('Account', '[your username]'), ('Last sync', '[12 Nov, 08:15]')], 'Sets with counts, notes, rating and flags; minifigures', 'Open'),
    ('BrickLink', '<span class="st none">Not connected</span>',
     [('Account', 'none'), ('Last sync', 'Never')], 'Store inventory, orders, price guide; wanted lists by file', 'Connect'),
    ('Brick Owl', '<span class="st none">Not connected</span>',
     [('Account', 'none'), ('Last sync', 'Never')], 'Collection lots, wishlists, inventory, orders; a daily budget per kind', 'Connect'),
    ('Import & export', '<span class="st">Files</span>',
     [('Last import', '[3 Nov, BrickLink XML]'), ('Last export', 'Never')], 'Every file format in and out, and your own complete export', 'Open'),
]
LOG = [('[18 Nov, 21:40]', 'Rebrickable', 'Into Brick Work', '[12 sets, 4 Lost Parts]', '<span class="st">Done</span>'),
       ('[18 Nov, 21:40]', 'Rebrickable', 'To Rebrickable', '[3 quantities]', '<span class="st dash">[3] waiting</span>'),
       ('[12 Nov, 08:15]', 'Brickset', 'Into Brick Work', '[2 sets]', '<span class="st">Done</span>'),
       ('[3 Nov, 19:02]', 'File', 'Import', '[BrickLink XML, 140 lots]', '<span class="st">Done</span>')]


def hub(ph):
    cards = ''.join(
        f'<div class="card"><h2>{t}</h2><div class="acts">{s}</div><dl class="kv">{"".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in kv)}</dl>'
        f'<div class="n">{what}</div><div class="acts" style="margin-top:auto"><span class="btn {"sec" if a == "Connect" else ""}">{a}</span></div></div>'
        for t, s, kv, what, a in CARDS[:4])
    t, st, kv, what, a = CARDS[4]
    files = (f'<div class="card" style="flex-direction:{"column" if ph else "row"};align-items:{"stretch" if ph else "center"};gap:{"10px" if ph else "28px"}"><h2>{t}</h2><div class="acts">{st}</div>'
             f'<dl class="kv">{"".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in kv)}</dl><div class="n" style="flex:1">{what}</div><span class="btn" style="align-self:{"flex-start" if ph else "center"}">{a}</span></div>')
    if ph:
        log = ''.join(f'<div class="row"><div class="id"><b>{site} · {d}</b><span class="n">{w}</span></div><span class="mono">{when}</span>{st}</div>' for when, site, d, w, st in LOG)
    else:
        log = ('<table><tr><th>When</th><th>Site</th><th>Direction</th><th>What</th><th></th></tr>'
               + ''.join(f'<tr><td class="mono">{a}</td><td>{b}</td><td>{c}</td><td>{d}</td><td>{e}</td></tr>' for a, b, c, d, e in LOG) + '</table>')
    return (f'<div class="head"><div><div class="lbl">Workbench · Sync</div><h1>Sync</h1>'
            f'<p>Bring a collection in from another site, work on it here, then send the changes back.</p></div></div>'
            f'<div class="grid {"" if ph else "g4"}">{cards}</div>{files}'
            f'<div class="block"><h2>Sync log</h2>{log}</div>'
            '<div class="block"><h2>How sync works</h2><p class="n">A run never deletes anything here unless you choose. Items that are only here are listed for you to decide. '
            'Changes to a site are always shown first, and removals there wait until you tick them.</p></div>')


# ---------- W0-02 Rebrickable at rest ----------
WHAT = [('Owned sets', 'Both ways', '[2] set lists: [Main collection], [Bought 2026]'),
        ('Wishlist', 'Both ways', 'Rebrickable [Wishlist] ↔ wishlist [Wanted]'),
        ('Loose stock', 'Into Brick Work', '[1] part list: [Bulk bin]'),
        ('Lost Parts', 'Both ways', 'Rule: Rebrickable wins per part'),
        ('Minifigures', 'Check only', 'Compared with your copies, never changed')]


def rest(ph):
    right = '' if ph else '<div class="acts"><span class="btn lg">Start a sync</span></div>'
    if ph:
        what = ''.join(f'<div class="row"><div class="id"><b>{a}</b><span class="n">{c}</span></div><span class="st">{b}</span></div>' for a, b, c in WHAT)
    else:
        what = ('<table><tr><th>What</th><th>Direction</th><th>Linked to</th></tr>'
                + ''.join(f'<tr><td><b>{a}</b></td><td><span class="st">{b}</span></td><td>{c}</td></tr>' for a, b, c in WHAT) + '</table>')
    acct = ('<div class="block"><h2>Your Rebrickable account <span class="st fill">Connected</span></h2>'
            '<dl class="kv"><dt>Account</dt><dd>[your username]</dd><dt>API key</dt><dd>Set · [checked 18 Nov]</dd><dt>Speed</dt><dd>About 1 request a second</dd><dt>Budget today</dt><dd class="mono">[140] / [2,000]</dd></dl>'
            '<div class="acts"><span class="btn sec">Test</span><span class="btn q">Change</span><span class="btn q">Remove</span></div></div>')
    sets = f'<div class="block"><h2>What syncs</h2>{what}<div class="acts"><span class="btn sec">Change what syncs</span></div></div>'
    last = ('<div class="block"><h2>Last runs</h2>'
            '<div class="row"><div class="id"><b>Run · [18 Nov, 21:40]</b><span class="n">[12 sets, 4 Lost Parts] added here · [3] rows to Rebrickable still waiting</span></div><span class="st dash">[3] waiting</span><span class="btn q">Retry</span><span class="btn q">Undo this run</span></div>'
            '<div class="row"><div class="id"><b>Run · [15 Nov, 09:12]</b><span class="n">[2 sets] added here · [1] quantity sent</span></div><span class="st">Done</span></div>'
            '<p class="note">Rebrickable keeps its own link to your account. Each run counts against Brick Work\'s daily budget for Rebrickable.</p></div>')
    start = '<span class="btn lg">Start a sync</span>' if ph else ''
    body = site_head('Rebrickable', 'Last run [18 Nov, 21:40]', ph, right) + start
    return body + (acct + sets + last if ph else f'<div class="grid g2">{acct}{last}</div>{sets}')


# ---------- W0-03 connect ----------
def connect(ph):
    key = ('<div class="block"><h2>1 · API key <span class="st fill">Set</span></h2><p class="n">The key reads Rebrickable\'s catalogue. Your account lets Brick Work read and change your lists.</p><div class="field">API key<div class="in">••••••••••••[3f2a]</div></div>'
           '<div class="acts"><span class="btn sec">Test</span><span class="btn q">Remove</span></div></div>')
    acct = ('<div class="block"><h2>2 · Your Rebrickable account <span class="st none">Not connected</span></h2>'
            '<p class="n">Your username and password go straight to Rebrickable once. Brick Work keeps only the token Rebrickable returns, never the password.</p>'
            f'<div class="{"" if ph else "grid g2"}" style="display:grid;gap:12px"><div class="field">Username or email<div class="in">[your username]</div></div>'
            '<div class="field">Password<div class="in">••••••••</div></div></div>'
            '<div class="acts"><span class="btn">Connect</span><span class="btn q">Paste a user token instead</span></div>'
            '<p class="note">A user token is stored encrypted. It is never shown again.</p></div>')
    foot = '<div class="foot"><span class="btn q">Cancel</span><span class="btn" style="margin-left:auto">Next: choose what</span></div>'
    return site_head('Rebrickable', 'Connect your account, choose what to sync, then run the sync.', ph) + steps('Connect', ph) + key + acct + foot


# ---------- W0-04 choose what ----------
DIRS = ['Into Brick Work', 'Both ways', 'To Rebrickable', 'Off']


def seg(on, opts=DIRS):
    return '<div class="seg">' + ''.join(f'<span class="{"on" if o == on else ""}">{o}</span>' for o in opts) + '</div>'


def choose(ph):
    s = lambda on: seg(on, ['In', 'Both', 'Out', 'Off'] if ph else DIRS)
    owned = ('<div class="block"><h2>Owned sets</h2>' + s('Both ways' if not ph else 'Both')
             + '<p class="n">Tick the set lists that hold sets you own. None ticked means every list except the wishlist list.</p>'
             + chk('[Main collection]', True, '[214] sets') + chk('[Bought 2026]', True, '[12] sets') + chk('[Lent to Max]', False, '[3] sets')
             + '<div class="field">Send changes to<div class="in sel">[Main collection]</div></div></div>')
    wish = ('<div class="block"><h2>Wishlist</h2>' + s('Both ways' if not ph else 'Both')
            + f'<div style="display:grid;gap:12px;{"" if ph else "grid-template-columns:1fr 1fr"}"><div class="field">Wanted sets · go to the wishlist<div class="in sel">[Wishlist]</div></div>'
            '<div class="field">Wishlist here<div class="in sel">[Wanted]</div></div></div></div>')
    loose = ('<div class="block"><h2>Loose stock</h2>' + seg('Into Brick Work' if not ph else 'In', ['Into Brick Work', 'Off'] if not ph else ['In', 'Off'])
             + '<p class="n">Tick the part lists that are loose parts. None is ticked until you choose.</p>'
             + chk('[Bulk bin]', True, '[1,830] parts') + chk('[Sorted Technic]', False, '[640] parts')
             + '<div class="field">Put new loose parts in<div class="in sel">One lot per part list</div></div></div>')
    lost = ('<div class="block"><h2>Lost Parts</h2>' + s('Both ways' if not ph else 'Both')
            + '<p class="n">Marks the parts on your Lost Parts list as missing on the matching copy, and sends the parts you find or newly miss here back.</p>'
            + '<div class="lbl">Into Brick Work: which count wins</div>'
            + chk('<b>Add only</b><br><span class="n">The sync only adds missing marks. Where both sides have a count, the larger is kept. Nothing is cleared.</span>', False, rad=True)
            + chk('<b>Rebrickable wins per part</b><br><span class="n">For a part Rebrickable lists as lost, Rebrickable\'s count replaces yours, also when it is smaller. Marks on other parts stay.</span>', True, rad=True)
            + chk('<b>Rebrickable wins per set</b><br><span class="n">A set with at least one Lost Part on Rebrickable becomes exactly Rebrickable\'s list. Other missing marks on that copy are cleared.</span>', False, rad=True)
            + chk('<b>Rebrickable wins everywhere</b><br><span class="n">Every synced set becomes exactly Rebrickable\'s list. A set with no Lost Parts there loses its missing marks.</span>', False, rad=True)
            + '<div class="lbl">To Rebrickable</div><p class="n">Parts newly missing here are added to Lost Parts there; parts found here are removed there. Removals are unticked until you tick them.</p>'
            + '<div class="field">Which count wins<div class="in sel">[Brick Work wins per part]</div></div>'
            + '</div>')
    figs = ('<div class="block"><h2>Minifigures</h2>' + seg('Check only', ['Check only', 'Off'])
            + '<p class="n">Rebrickable derives your minifigures from your sets. Brick Work compares them with your copies and lists the differences; nothing is changed on either side.</p></div>')
    both = '<div class="block"><h2>When both sides differ</h2><p class="n">Ask me each time</p></div>'
    foot = '<div class="foot"><span class="btn q">‹ Back</span><span class="btn" style="margin-left:auto">Next: pick sets</span></div>'
    cols = owned + wish + loose + lost + figs + both if ph else f'<div class="grid g2" style="align-items:start"><div style="display:flex;flex-direction:column;gap:16px">{owned}{wish}{loose}</div><div style="display:flex;flex-direction:column;gap:16px">{lost}{figs}{both}</div></div>'
    return site_head('Rebrickable', 'Choose what to sync, and in which direction. You can change it later.', ph) + steps('Choose what', ph) + cols + foot


# ---------- W0-05 pick sets ----------
PSETS = [('[10294-1]', '[Titanic]', '[Icons]', '[2021]', True), ('[42143-1]', '[Ferrari Daytona SP3]', '[Technic]', '[2022]', True),
         ('[42115-1]', '[Lamborghini Sián FKP 37]', '[Technic]', '[2020]', True), ('[42141-1]', '[McLaren Formula 1 Race Car]', '[Technic]', '[2022]', False),
         ('[42083-1]', '[Bugatti Chiron]', '[Technic]', '[2018]', True), ('[42096-1]', '[Porsche 911 RSR]', '[Technic]', '[2019]', True)]


def pick(ph):
    by = seg('By theme', ['All linked', 'By list', 'By theme', 'By year', 'One by one'] if not ph else ['All', 'List', 'Theme', 'Year', 'One'])
    if ph:
        by = seg('Theme', ['All', 'List', 'Theme', 'Year', 'One'])
    themes = '<div class="chips">' + ''.join(f'<span class="chip {"on" if t in ("[Technic]", "[Icons]") else ""}">{t} [{n}]</span>' for t, n in (('[Technic]', 31), ('[Icons]', 7), ('[City]', 54), ('[Star Wars]', 40), ('[Creator Expert]', 18), ('[Ideas]', 9))) + '</div>'
    rows = ''.join(f'<div class="row">{chk("", on)}<div class="tile">[pic]</div><div class="id"><b>{name}</b><span class="mono">{no}</span> <span class="n">{th} · {yr}</span></div></div>' for no, name, th, yr, on in PSETS)
    count = '<div class="acts"><b>[37] of [229] sets picked</b><span class="n">· loose stock: [Bulk bin] · Lost Parts: on the picked sets</span></div>'
    srch = '<div class="field"><div class="in">Number or name</div></div>'
    foot = '<div class="foot"><span class="btn q">‹ Back</span><span class="btn" style="margin-left:auto">Next: preview</span></div>'
    return (site_head('Rebrickable', 'Pick the sets this run covers. Sets you do not pick stay as they are on both sides.', ph) + steps('Pick sets', ph)
            + f'<div class="block"><h2>Which sets</h2>{by}{themes}{srch}<div>{rows}</div><span class="btn q" style="align-self:flex-start">Show all [38] sets in [Technic], [Icons]</span></div>' + count + foot)


# ---------- W0-06 preview ----------
PREV = [('[42143-1]', '[Ferrari Daytona SP3]', 'Owned', 'New there', 'Add [1] here', True),
        ('[10294-1]', '[Titanic]', 'Owned', 'Different', 'Quantity [1] to [2] there', True),
        ('[42083-1]', '[Bugatti Chiron]', 'Owned', 'Only here', 'Removes there', False),
        ('[21327-1]', '[Typewriter]', 'Wishlist', 'New there', 'Add [1] here', True)]


def preview(ph):
    tabs = '<div class="chips">' + ''.join(f'<span class="chip {"on" if i == 0 else ""}">{t} <span class="mono">[{n}]</span></span>' for i, (t, n) in enumerate(
        (('All', 44), ('Into Brick Work', 31), ('To Rebrickable', 13), ('Changed in both places', 1), ('Lost Parts', 6), ('Loose stock', 9)))) + '</div>'
    rows = ''.join(f'<div class="row">{chk("", on)}<div class="id"><b>{name}</b><span class="mono">{no}</span> <span class="n">· {kind}</span></div>'
                   f'<span class="st {"dash" if st == "Different" else "none" if st == "Only here" else ""}">{st}</span><span style="{"" if ph else "min-width:220px"}">{act}</span></div>' for no, name, kind, st, act, on in PREV)
    conflict = ('<div class="block"><h2>Changed in both places <span class="mono">[1]</span></h2>'
                '<p class="n">[1] item changed here and on Rebrickable since the last run on [18 Nov]. Nothing happens to these unless you choose.</p>'
                '<div class="row"><div class="id"><b>[Lamborghini Sián FKP 37]</b><span class="mono">[42115-1]</span> <span class="n">Here [2] · Rebrickable [1]</span></div>'
                + (('<div style="width:100%">' + chk('Keep here', True, rad=True) + chk('Take Rebrickable: [1] here', rad=True) + chk('Send [2] there', rad=True) + '</div>') if ph else seg("Keep here", ["Keep here", "Take Rebrickable: [1] here", "Send [2] there"])) + '</div>'
                '<p class="note">Checks, storage and notes stay here either way; only quantities are compared.</p></div>')
    lost = ('<div class="block"><h2>Lost Parts <span class="mono">[6]</span></h2><p class="mono">[4] added · [1] replaced · [1] cleared · [0] not matched · [1] set needs a copy</p>'
            '<div class="row"><div class="id"><b>[Porsche 911 RSR]</b><span class="mono">[42096-1]</span> <span class="n">[3] parts · [5] pieces</span></div>'
            '<span class="st dash">Choose a copy</span><div class="field" style="min-width:200px">Mark the parts on<div class="in sel">[Copy 1 · Shelf B]</div></div></div>'
            '<div class="row">' + chk('', True) + '<div class="id"><b>[Titanic]</b><span class="mono">[10294-1]</span></div><span>To Rebrickable: [2] found here, remove from Lost Parts</span></div></div>')
    loose = ('<div class="block"><h2>Loose stock <span class="mono">[9]</span></h2>'
             '<div class="row">' + chk('', True) + '<div class="id"><b>[Brick 2 x 4]</b><span class="mono">[3001] · [Red]</span> <span class="n">from [Bulk bin]</span></div>'
             '<span class="st">New there</span><span>Add [24] here</span><div class="field" style="min-width:200px">Put in<div class="in sel">[Lot · Bulk bin]</div></div></div></div>')
    before = ('<div class="warn"><b>Before you send.</b> Brick Work\'s Undo cannot take a sent change back. Removals are unticked until you tick them.'
              '<dl class="kv" style="margin-top:8px"><dt>Requests</dt><dd class="mono">about [46]</dd><dt>Time</dt><dd class="mono">about [50 s] at 1 request a second</dd><dt>Budget today</dt><dd class="mono">[140] / [2,000]</dd></dl></div>')
    foot = '<div class="foot"><span class="btn q">‹ Back</span><span class="mono">[43] of [44] ticked</span><span class="btn lg" style="margin-left:auto">Run [43] changes</span></div>'
    return (site_head('Rebrickable', '[37] sets compared · checked [19 Nov, 16:52] · last run [18 Nov, 21:40]', ph) + steps('Preview', ph)
            + '<p class="n">Nothing in Brick Work is deleted unless you choose. Choose what happens to each difference, then run.</p>'
            + f'<div class="block">{tabs}<div class="field"><div class="in">Number or name</div></div><div>{rows}</div><span class="btn q" style="align-self:flex-start">Show [40] more</span></div>'
            + conflict + lost + loose + before + foot)


# ---------- W0-07 run ----------
def run(ph):
    bar = '<div style="height:14px;border:1.5px solid var(--tw-text)"><div style="width:59%;height:100%;background:var(--tw-text)"></div></div>'
    blocks = ('<div class="block"><h2>Into Brick Work</h2><p class="mono">[26] of [31] done</p><div class="pbar"><b style="width:84%"></b></div><p class="n">Now: [Porsche 911 RSR], [3] Lost Parts</p></div>'
              '<div class="block"><h2>To Rebrickable</h2><p class="mono">[0] of [12] sent</p><div class="pbar"><b style="width:0%"></b></div><p class="n">Starts when everything here is done.</p></div>')
    return (site_head('Rebrickable', 'Running [43] changes', ph) + steps('Run', ph)
            + f'<div class="block"><h2>[26] of [43] done</h2>{bar}<p class="mono">about [18 s] left · about 1 request a second · budget today [166] / [2,000]</p>'
            '<p class="n">You can leave this page. The run goes on and shows in Jobs.</p><div class="acts"><span class="btn sec">Stop after this one</span></div></div>'
            + (blocks if ph else f'<div class="grid g2">{blocks}</div>'))


# ---------- W0-08 result ----------
def result(ph):
    here = ('<div class="block"><h2>Here in Brick Work <span class="st fill">[31] changed</span></h2>'
            '<p class="n">[12] sets and [1] wish added · [9] loose lots added to [Bulk bin] · [4] parts marked on [3] sets · [1] mark cleared · [4] quantities changed.</p>'
            '<div class="acts"><span class="btn sec">Undo this run</span></div><p class="note">Undo takes back everything this run changed here, in one step. It cannot change what was sent to Rebrickable.</p></div>')
    there = ('<div class="block"><h2>On Rebrickable <span class="st">[11] sent</span> <span class="st dash">[1] failed</span></h2>'
             '<p class="n">[3] quantities changed · [1] set added · [7] Lost Parts removed.</p>'
             '<div class="row"><div class="id"><b>[Titanic]</b><span class="mono">[10294-1]</span> <span class="n">Quantity [1] to [2] · [Rebrickable did not answer]</span></div><span class="btn sec">Retry</span></div>'
             '<div class="warn">A change on Rebrickable cannot be undone here. To reverse it, change it back on Rebrickable or send again.</div></div>')
    figs = ('<div class="block"><h2>Minifigures check</h2><p class="n">[2] minifigures Rebrickable lists are not on your copies: [sw0581] on [75192-1], [hp150] on [76419-1].</p>'
            '<span class="btn q" style="align-self:flex-start">Open the sets</span></div>')
    foot = '<div class="foot"><span class="btn q">Open sync log</span><span class="btn" style="margin-left:auto">Done</span></div>'
    return (site_head('Rebrickable', 'Finished [19 Nov, 16:54] · [42] of [43] done, [1] failed', ph) + steps('Result', ph)
            + (here + there + figs if ph else f'<div class="grid g2" style="align-items:start">{here}{there}</div>{figs}') + foot)


FRAMES = [('W0-01-sync-hub', hub), ('W0-02-rebrickable', rest), ('W0-03-connect', connect), ('W0-04-choose-what', choose),
          ('W0-05-pick-sets', pick), ('W0-06-preview', preview), ('W0-07-run', run), ('W0-08-result', result)]


def build(OUT=OUT):
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        import glob, os; exe = os.environ.get('BRAND_CHROMIUM') or glob.glob(os.path.expanduser('~/Library/Caches/ms-playwright/chromium_headless_shell-1248/*/chrome-headless-shell'))[0]; b = p.chromium.launch(executable_path=exe)
        for name, fn in FRAMES:
            for w, h, ph in ((1440, 900, False), (390, 844, True)):
                html = page(phone(fn(True)) if ph else desk(fn(False)), w, h)
                f = OUT / f'{name}-{w}.html'
                f.write_text(html)
                pg = b.new_page(viewport={'width': w, 'height': h}, device_scale_factor=2, color_scheme='light', reduced_motion='reduce')
                pg.goto(f.as_uri())
                pg.screenshot(path=str(OUT / f'{name}-{w}.png'), full_page=True)
                over = pg.evaluate('document.documentElement.scrollWidth')
                if over > w:
                    print(f'OVERFLOW {name}-{w}: {over}px')
                pg.close()
        b.close()
    print('built', len(FRAMES) * 2, 'frames in', OUT)


def check():
    """Rebuild into a temporary folder; every frame must match the committed one: HTML byte for byte, PNG within 0.1 %."""
    import tempfile
    from PIL import Image, ImageChops
    bad = 0
    with tempfile.TemporaryDirectory() as t:
        tmp = pathlib.Path(t)
        build(tmp)
        for name, _ in FRAMES:
            for w in (1440, 390):
                if (tmp / f'{name}-{w}.html').read_bytes() != (OUT / f'{name}-{w}.html').read_bytes():
                    print('HTML differs', name, w); bad += 1
                a, b = Image.open(tmp / f'{name}-{w}.png').convert('RGB'), Image.open(OUT / f'{name}-{w}.png').convert('RGB')
                if a.size != b.size:
                    print('size differs', name, w); bad += 1; continue
                diff = ImageChops.difference(a, b).convert('L').point(lambda v: 255 if v else 0).histogram()[255] / (a.width * a.height)
                if diff > 0.001:
                    print(f'PNG differs {name} {w}: {diff:.4%}'); bad += 1
    print('check:', 'ok' if not bad else f'{bad} differ')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    {'build': build, 'check': check}[sys.argv[1]]()
