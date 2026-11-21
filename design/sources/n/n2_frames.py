"""Commission N (Sync and files, #517), round 2 (approved 2026-11-20): Brickset, BrickLink, Brick Owl, Import & export, the complete export (#520 to #524) and #531 (list tags on the copy). Folders 25 to 36 and 41 to 48 (37 to 40 were replaced by 44 to 47 on 2026-11-20: the list names are the detail of the source, #551).

Built on round 1's model (n_frames.py: its components, steps and tokens are imported, never copied). A step that differs from the Rebrickable
frame only by the site's name is not drawn: the review lists it as "as N1-0x".

    python n2_frames.py build|check|narrow [OUTDIR]      (default design/screens-b; OUTDIR/fonts must sit beside it, as for n_frames.py)
"""
import pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import n_frames as N  # noqa: E402

tag, btn, seg, chk, rad, field, kv, head, steps, foot, drow, ic = N.tag, N.btn, N.seg, N.chk, N.rad, N.field, N.kv, N.head, N.steps, N.foot, N.drow, N.ic


LOTS = ['Connect', 'Choose what', 'Pick lots', 'Preview', 'Run', 'Result']
FILE = ['Choose file', 'Choose what', 'Preview', 'Run', 'Result']


def steps_n(names, cur, ph):
    """N.steps for any number of steps (its progress strip is fixed at six); the step names belong to the flow."""
    i, n = names.index(cur), len(names)
    if ph:
        nxt = f' · next: {names[i + 1]}' if i < n - 1 else ''
        segs = ''.join(f'<i class="{"on" if j == i else "done" if j < i else ""}"></i>' for j in range(n))
        return f'<div><div class="pstep">Step {i + 1} of {n} · <b>{cur}</b>{nxt}</div><div class="pseg">{segs}</div></div>'
    return '<div class="nsteps">' + ''.join(
        f'<div class="{"on" if j == i else "done" if j < i else ""}"><i>{N.TICK if j < i else j + 1}</i>{s}</div>' for j, s in enumerate(names)) + '</div>'


def card(title, body, extra=''):
    return f'<div class="ncard"{extra}><h2>{title}</h2>{body}</div>'


def two(a, b, ph, col2=None):
    return a + b if ph else f'<div class="ngrid g2" style="align-items:start">{a}{b}</div>'


def account(site, rows, ph, tags=None):
    return card(f'Your {site} account {tags or tag("Connected")}', kv(rows)
                + '<div style="display:flex;gap:10px;flex-wrap:wrap"><span class="btn sec sm">Test</span><span class="btn q sm">Change</span><span class="btn q sm">Remove</span></div>')


def what_table(rows, ph, third='Linked to'):
    if ph:
        return ''.join(f'<div class="nrow"><div class="id"><b>{a}</b><span>{c}</span></div>{tag(b)}</div>' for a, b, c in rows)
    return (f'<table class="ntbl"><tr><th>What</th><th>Direction</th><th>{third}</th></tr>'
            + ''.join(f'<tr><td><b>{a}</b></td><td>{tag(b)}</td><td>{c}</td></tr>' for a, b, c in rows) + '</table>')


def runs(rows, ph):
    out = ''
    for title, meta, st, act in rows:
        out += drow('', title, meta, st, act, ph)
    return out


# ---- N2-01 Brickset at rest (#520) -------------------------------------------------------------------------------------
BS_WHAT = [('Owned sets', 'Both ways', 'Quantities, notes, rating and flags'),
           ('Wanted sets', 'Both ways', 'The Wanted wishlist, with priority'),
           ('Minifigures', 'Both ways', 'Loose minifigures: own, want, quantity, notes')]


def bs_rest(ph):
    acct = account('Brickset', [('Account', 'brickfan'), ('API key', 'Set · checked 12 Nov'), ('Today’s budget', '0 of 100 calls')], ph)
    what = card('What syncs', what_table(BS_WHAT, ph) + '<span class="btn sec sm" style="align-self:flex-start">Change what syncs</span>')
    last = card('Last runs', runs([('Run · 12 Nov, 08:15', '1 set added here', tag('Done'), '<span class="btn q sm">Undo this run</span>')], ph)
                + '<p class="n">Purchase date and price never leave Brick Work: Brickset has no field for them.</p>')
    start = btn('Start a sync', 'lg')
    return head('Brickset', 'Last run 12 Nov, 08:15', ph, '' if ph else start) + (start + acct + what + last if ph else two(acct, last, ph) + what)


# ---- N2-02 Brickset choose what (#520) ---------------------------------------------------------------------------------
def bs_choose(ph):
    fields = ''.join(chk(f, on, r) for f, on, r in [
        ('Owned', True, 'both'), ('Wanted', True, 'both'), ('Quantity owned', True, 'both'), ('Quantity wanted', True, 'both'),
        ('Notes', True, '1,000 characters'), ('Rating', True, '1 to 5'), ('Wanted priority', False, 'both'),
        ('New and used counts', True, '')])
    flags = ''.join(chk(f, on) for f, on in [('Flag 1 · Duplicate', True), ('Flag 2 · Gift', True), ('Flag 3 · Display', False), ('Flag 4 · Built', True),
                                           ('Flag 5 · Sealed', True), ('Flag 6 · Sold', False), ('Flag 7 · Parts', False), ('Flag 8 · Trade', False)])
    sets = card('Sets: which fields go each way', seg('Both' if ph else 'Both ways', ['In', 'Both', 'Out', 'Off'] if ph else ['Into Brick Work', 'Both ways', 'To Brickset', 'Off'])
                + '<p class="n">Tick the fields Brick Work and Brickset share. An unticked field is never read or written.</p>' + fields)
    fl = card('Flags', '<p class="n">Brickset has eight flags with names you give them there. Brick Work shows them as tags on the copy.</p>' + flags)
    figs = card('Minifigures', seg('Both' if ph else 'Both ways', ['In', 'Both', 'Out', 'Off'] if ph else ['Into Brick Work', 'Both ways', 'To Brickset', 'Off'])
                + '<p class="n">Loose minifigures: own, want, quantity and notes. A minifigure that comes with a set stays with that set.</p>')
    both = card('When both sides differ', field('', 'Ask me each time'))
    never = '<div class="ninfo">Purchase date and price are never sent: Brickset has no field for them.</div>'
    cols = sets + fl + figs + both if ph else (f'<div class="ngrid g2" style="align-items:start"><div class="nwrap" style="gap:16px">{sets}</div>'
                                              f'<div class="nwrap" style="gap:16px">{fl}{figs}{both}</div></div>')
    return head('Brickset', 'Choose what to sync, and in which direction. You can change it later.', ph) + steps('Choose what', ph) + cols + never + foot(btn('‹ Back', 'q'), btn('Next: pick sets', 'sec'))


# ---- N2-03 BrickLink at rest (#521) ------------------------------------------------------------------------------------
BL_WHAT = [('Orders', 'Into Brick Work', 'Pulled into Orders'),
           ('Loose stock on BrickLink', 'Both ways', 'Loose stock, one lot per store lot'),
           ('Price guide', 'Into Brick Work', 'Used for prices and Complete sets'),
           ('Wanted lists', 'By file', 'The page builds the XML; BrickLink has no wanted-list API')]


def bl_rest(ph):
    acct = account('BrickLink', [('Account', 'brickfan-bricks'), ('Token', 'Set · bound to 203.0.113.7'), ('Today’s budget', '0 of 4,400 calls')], ph)
    what = card('What syncs', what_table(BL_WHAT, ph) + '<span class="btn sec sm" style="align-self:flex-start">Change what syncs</span>')
    file = card('Wanted lists by file', '<p class="n">BrickLink offers no wanted lists through its API. Brick Work builds the wanted-list XML for a list you pick; you upload it on BrickLink.</p>'
                '<span class="btn sec sm" style="align-self:flex-start">Build a wanted-list file</span>')
    last = card('Last runs', '<p class="n">No sync yet. Last file import: 3 Nov, 19:02, BrickLink XML, 140 lots.</p>')
    start = btn('Start a sync', 'lg')
    return head('BrickLink', 'Connected 19 Nov · not synced yet', ph, '' if ph else start) + (start + acct + what + file + last if ph else two(acct, last, ph) + what + file)


# ---- N2-04 BrickLink connect: the token is bound to one IP (#521) ------------------------------------------------------
def bl_connect(ph):
    note = ('<div class="ninfo"><b>BrickLink ties the token to one IP address.</b> Register this install’s address on BrickLink, then create the token for that '
            'address. If the address changes, the token stops working until you register the new one.</div>')
    ip = card('1 · This install’s address', '<p class="n">Register this address in BrickLink’s API settings.</p>'
              + field('Address seen by BrickLink', '203.0.113.7', sel=False) + '<div style="display:flex;gap:10px;flex-wrap:wrap"><span class="btn sec sm">Check the address</span><span class="btn q sm">Copy</span></div>')
    keys = card('2 · Your four BrickLink values', f'<p class="n">BrickLink’s API settings show a consumer key and secret, and a token and its secret. They are stored encrypted and never shown again.</p>'
                f'<div class="ngrid {"" if ph else "g2"}" style="gap:12px">{field("Consumer key", "••••••••••••", sel=False)}{field("Consumer secret", "••••••••••••", sel=False)}'
                f'{field("Token value", "••••••••••••", sel=False)}{field("Token secret", "••••••••••••", sel=False)}</div>'
                '<div style="display:flex;gap:10px;flex-wrap:wrap"><span class="btn">Connect</span><span class="btn q">Remove</span></div>')
    return head('BrickLink', 'Connect your BrickLink account, choose what to sync, then run the sync.', ph) + steps_n(LOTS, 'Connect', ph) + note + two(ip, keys, ph) + foot(btn('Cancel', 'q'), btn('Next: choose what', 'sec'))


# ---- N2-05 BrickLink choose what (#521) --------------------------------------------------------------------------------
def bl_choose(ph):
    d4 = (lambda on: seg(on, ['In', 'Both', 'Out', 'Off'])) if ph else (lambda on: seg(on, ['Into Brick Work', 'Both ways', 'To BrickLink', 'Off']))
    on_in = 'In' if ph else 'Into Brick Work'
    orders = card('Orders', seg(on_in, ['In', 'Off'] if ph else ['Into Brick Work', 'Off'])
                  + '<p class="n">New orders are pulled into Orders.</p>'
                  + chk('Orders since', True, '1 Oct') + field('Orders to pull', 'Received and paid'))
    inv = card('Loose stock on BrickLink', d4('Both' if ph else 'Both ways')
               + '<p class="n">Each BrickLink lot becomes one lot of loose stock. Changes are shown first; removals wait until you tick them.</p>'
               + chk('Create, update lots', True) + chk('Remove lots at BrickLink', False) + field('BrickLink lots come in as', 'One lot per BrickLink lot'))
    price = card('Price guide', seg(on_in, ['In', 'Off'] if ph else ['Into Brick Work', 'Off'])
                 + field('Region', 'Europe') + field('Condition', 'New and used') + field('When nothing sold', 'Use the stock guide'))
    nothing = '<div class="ninfo">BrickLink’s API offers no wanted lists and no personal collection, so neither is synced. Wanted lists go by file instead.</div>'
    cols = orders + inv + price if ph else (f'<div class="ngrid g2" style="align-items:start"><div class="nwrap" style="gap:16px">{orders}{price}</div><div class="nwrap" style="gap:16px">{inv}</div></div>')
    return head('BrickLink', 'Choose what to sync, and in which direction. You can change it later.', ph) + steps_n(LOTS, 'Choose what', ph) + cols + nothing + foot(btn('‹ Back', 'q'), btn('Next: pick lots', 'sec'))


# ---- N2-06 BrickLink wanted lists by file (#143, #521) -----------------------------------------------------------------
def bl_file(ph):
    pick = card('1 · Pick a wishlist', ''.join(rad(t, n, on) for t, n, on in [('Wanted', '14 sets · 62 parts', True), ('Christmas', '3 sets', False), ('Train layout', '5 sets', False)])
                + field('Include', 'Sets and their parts') + field('Condition', 'New'))
    xml = ('<pre class="mono" style="margin:0;font-size:12.5px;line-height:1.5;background:var(--tw-surface-2);border:1px solid var(--tw-divider);border-radius:var(--tw-r-1);padding:12px;overflow:auto">'
           '&lt;INVENTORY&gt;\n  &lt;ITEM&gt;\n    &lt;ITEMTYPE&gt;S&lt;/ITEMTYPE&gt;\n    &lt;ITEMID&gt;31109-1&lt;/ITEMID&gt;\n    &lt;MINQTY&gt;1&lt;/MINQTY&gt;\n  &lt;/ITEM&gt;\n  …\n&lt;/INVENTORY&gt;</pre>')
    out = card('2 · The file', f'<p class="n">14 items. BrickLink reads this as a wanted list.</p>{xml}<div style="display:flex;gap:10px;flex-wrap:wrap"><span class="btn">Download wanted-list.xml</span><span class="btn sec">Copy the XML</span></div>')
    up = card('3 · Upload it on BrickLink', '<p class="n">BrickLink only takes a wanted list through its website. Open the upload page, choose this file and finish there. Brick Work does not see what happens there.</p>'
              '<span class="btn sec" style="align-self:flex-start">Open BrickLink’s upload page ↗</span>')
    return head('BrickLink · Wanted lists by file', 'Build the wanted-list file for one of your wishlists.', ph) + two(pick, out, ph) + up + foot(btn('‹ Back to BrickLink', 'q'), '')


# ---- N2-07 Brick Owl at rest (#522) ------------------------------------------------------------------------------------
BO_WHAT = [('Collection', 'Both ways', 'Lots as sets and loose stock'),
           ('Wishlists', 'Both ways', 'Each linked to a Brick Work wishlist'),
           ('Orders', 'Into Brick Work', 'Pulled into Orders')]
BUDGET = [('Collection reads', 0, 2000), ('Collection writes', 0, None), ('Wishlist calls', 0, None), ('Orders', 0, None)]


def budget_rows(ph, lim=True):
    out = ''
    for name, used, tot in BUDGET:
        s = f'<span class="mono">{used:,} of {tot:,}</span>' if tot else '<span class="mono">per-endpoint quota</span>'
        out += f'<div class="nrow"><div class="id"><b>{name}</b></div>{s}</div>'
    return out


def bo_rest(ph):
    acct = account('Brick Owl', [('Account', 'brickfan'), ('API key', 'Set · checked 19 Nov'), ('Speed', 'Up to 600 requests a minute')], ph)
    bud = card('Today’s budget', '<p class="n">Brick Owl limits some kinds of calls per day. Brick Work stops a run before it passes one and tells you how many items waited.</p>' + budget_rows(ph))
    what = card('What syncs', what_table(BO_WHAT, ph) + '<span class="btn sec sm" style="align-self:flex-start">Change what syncs</span>')
    start = btn('Start a sync', 'lg')
    return head('Brick Owl', 'Not synced yet', ph, '' if ph else start) + (start + acct + bud + what if ph else two(acct, bud, ph) + what)


# ---- N2-08 Brick Owl choose what (#522) --------------------------------------------------------------------------------
def bo_choose(ph):
    d = (lambda on: seg(on, ['In', 'Both', 'Out', 'Off'])) if ph else (lambda on: seg(on, ['Into Brick Work', 'Both ways', 'To Brick Owl', 'Off']))
    coll = card('Collection', d('Both' if ph else 'Both ways') + '<p class="n">Brick Owl lots come in as sets or loose stock. Reading all lots uses collection reads, against the daily budget of 2,000.</p>'
                + chk('Complete sets come in as sets', True) + chk('Everything else comes in as loose stock', True) + field('A lot Brick Work cannot place', 'Ask me in the preview'))
    wish = card('Wishlists', d('Both' if ph else 'Both ways') + ''.join(chk(a, on, b) for a, on, b in [('Wanted', True, '→ Wanted'), ('Christmas', True, '→ Christmas'), ('Old ideas', False, '→ none')]))
    orders = card('Orders', seg('In' if ph else 'Into Brick Work', ['In', 'Off'] if ph else ['Into Brick Work', 'Off']) + '<p class="n">New orders are pulled into Orders.</p>')
    cols = coll + wish + orders if ph else (f'<div class="ngrid g2" style="align-items:start"><div class="nwrap" style="gap:16px">{coll}{orders}</div><div class="nwrap" style="gap:16px">{wish}</div></div>')
    return head('Brick Owl', 'Choose what to sync, and in which direction. You can change it later.', ph) + steps_n(LOTS, 'Choose what', ph) + cols + foot(btn('‹ Back', 'q'), btn('Next: pick lots', 'sec'))


# ---- N2-09 Brick Owl run with a daily budget per kind (#522) -----------------------------------------------------------
def bo_run(ph):
    rows = ''.join(f'<div class="nrow"><div class="id"><b>{a}</b><span>{b}</span></div><span class="mono">{c}</span></div>' for a, b, c in [
        ('Collection reads', 'Page 6 of 8 · 6 of 2,000 today', '6'), ('Collection writes', 'Waiting', '0'), ('Wishlist calls', 'Done', '2')])
    bar = N.prog(6, 8)
    box = card('Running · pulling the collection', f'{bar}<p class="n">6 of 8 pages read. The run stops by itself at the daily budget; the rest waits for tomorrow.</p>{rows}')
    warn = '<div class="ninfo">1,994 collection reads are left today. This run needs 2 more. Nothing is lost if it stops early.</div>'
    return head('Brick Owl', 'Started 19 Nov, 16:41', ph) + steps_n(LOTS, 'Run', ph) + box + warn + foot(btn('Stop after this page', 'sec'), '')


# ---- N2-10 Import & export (#523) --------------------------------------------------------------------------------------
IN = [('BrickLink wanted list or inventory', 'XML', 'Wishes or loose stock'), ('BrickLink order', 'XML', 'Orders'), ('Rebrickable', 'CSV', 'Sets and loose stock'),
      ('Brickset My Sets', 'CSV', 'Sets'), ('BrickTracker', 'Its import file', 'Sets and missing parts'), ('Brick Work CSV', 'CSV', 'In Brick Work’s columns'),
      ('Complete export', 'Zip', 'Everything you tick')]
OUT = [('Complete export', 'Zip of JSON and CSV', 'Everything you tick'), ('Database file', 'SQLite', 'The whole database'), ('Insurance report', 'PDF', 'Sets and values'),
       ('Wishlist', 'BrickLink XML, CSV', 'One wishlist'), ('Missing parts', 'CSV, BrickLink XML', 'Missing parts'), ('Part Runner and order files', 'PDF, CSV', 'One order or run'),
       ('Brick Work CSV', 'CSV', 'In Brick Work’s columns')]


def ie_table(rows, ph):
    if ph:
        return ''.join(f'<div class="nrow"><div class="id"><b>{a}</b><span>{b} · {c}</span></div><span class="btn sec sm">Choose</span></div>' for a, b, c in rows)
    return ('<table class="ntbl"><tr><th>Format</th><th>File</th><th>What</th><th></th></tr>'
            + ''.join(f'<tr><td><b>{a}</b></td><td>{b}</td><td>{c}</td><td style="text-align:right"><span class="btn sec sm">Choose</span></td></tr>' for a, b, c in rows) + '</table>')


def ie_page(ph):
    steps_note = ('<div class="ncard"><h2>Every file goes through the same steps</h2><p class="n">Choose what, choose the format, preview, run, result. An import has Undo; an export '
                  'never changes anything here.</p></div>')
    return (head('Import & export', 'All imports and exports in one place.', ph)
            + two(card('Import', ie_table(IN, ph)), card('Export', ie_table(OUT, ph)), ph) + steps_note)


# ---- N2-11 Brick Work's own complete export (#524) ---------------------------------------------------------------------
INC = [('Sets and copies', '', True, '8 copies'), ('Loose stock', '', True, '1,830 parts'), ('Minifigures', '', True, '12'),
       ('Storage', 'places', True, '6'), ('Wishes', '', True, '2 lists'), ('Orders', '', True, '12'),
       ('Prices and history', '', False, '3,200 rows'), ('Settings', 'never includes keys', False, '')]


def own_export(ph):
    inc = card('1 · What to include', ''.join(chk(f'{a}{" · " + b if b else ""}', on, c) for a, b, on, c in INC)
               + '<p class="n">Copies come with their part checks. Catalogue data is fetched again on import. Keys and passwords never leave Brick Work.</p>')
    fmt = card('2 · The file', '<p class="n">One zip: a manifest, one JSON file for the data and one CSV per table you can open in a spreadsheet.</p>' + field('Name', 'brick-work-2026-11-19.zip', sel=False)
               + kv([('Size', 'About 4 MB'), ('Format version', 'Set in the manifest')]))
    btns = '<div style="display:flex;gap:10px;flex-wrap:wrap"><span class="btn lg">Export</span><span class="btn q">Preview what is included</span></div>'
    return head('Complete export', 'A complete, readable copy of your Brick Work data that you can bring back in.', ph) + two(inc, fmt, ph) + btns


# ---- N2-12 re-import preview with conflicts and Undo (#524) -----------------------------------------------------------
def re_import(ph):
    sm = ('<div class="ninfo"><b>brick-work-2026-11-19.zip</b> · made 19 Nov, 15:02 · format version in the manifest · from another install. '
          'Nothing has been changed yet.</div>')
    rows = [('7213-1 Off-Road Fire Truck & Fireboat', 'Copy 1 here has 10 missing parts; the file says 8', tag('Differs', 'dash'), 'Keep here ▾'),
            ('31109-1 Pirate Ship', 'Not here yet', tag('Only in the file'), 'Add here ▾'),
            ('Bulk bin', 'Same lot, 1,830 and 1,842 parts', tag('Differs', 'dash'), 'Take the file’s ▾'),
            ('Shelf A1 – Castle', 'Same in both', tag('Same'), 'Skip')]
    body = ''.join(drow(N.cb(i != 3), a, b, c, d, ph, 150) for i, (a, b, c, d) in enumerate(rows))
    sumry = card('3 changes', f'<p class="n">1 is new and 2 differ. A fourth row is the same in both and is skipped. You choose a result for each row or for all at once.</p>'
                 + field('For every difference', 'Ask me each time') + body)
    return head('Re-import', 'Preview of what the file would change.', ph) + steps_n(FILE, 'Preview', ph) + sm + sumry + '<p class="n">One Undo for the whole import.</p>' + foot(btn('‹ Back', 'q'), btn('Import 3', ''))


# ---- N2-17 BrickLink pick lots and orders (#521): the pick step of the lots flow, which N1-05 (sets) does not show ----------
def bl_pick(ph):
    orders = [('Order 6403217', 'Received 17 Nov · 14 lots · €38.20', True), ('Order 6403198', 'Received 15 Nov · 3 lots · €9.40', True), ('Order 6402955', 'Received 9 Nov · 22 lots · €71.10', False)]
    lots = [('Brick 1 × 4 · Dark Bluish Gray', '3010 · used · 120 pieces · €0.07', True), ('Plate 2 × 2 · Black', '3022 · new · 340 pieces · €0.03', True),
            ('Tile 1 × 2 · White', '3069b · new · 60 pieces · €0.05', False)]
    o = card('Orders to pull', '<p class="n">Orders since 1 Oct with status Received or Paid. Tick the orders this run pulls into Orders.</p>'
             + ''.join(f'<div class="nrow">{N.cb(on)}<div class="id"><b>{a}</b><span>{b}</span></div></div>' for a, b, on in orders))
    l = card('BrickLink lots', '<p class="n">Lots that changed at BrickLink since 3 Nov. Unticked lots are left as they are on both sides.</p>'
             + ''.join(f'<div class="nrow">{N.cb(on)}<div class="id"><b>{a}</b><span>{b}</span></div></div>' for a, b, on in lots))
    count = '<div class="ninfo"><b>2 of 3 orders and 2 of 3 lots picked</b></div>'
    return head('BrickLink', 'Pick the orders and lots this run covers.', ph) + steps_n(LOTS, 'Pick lots', ph) + two(o, l, ph) + count + foot(btn('‹ Back', 'q'), btn('Next: preview', 'sec'))


# ---- N2-18 BrickLink preview of lots and orders (#521) ----------------------------------------------------------------
def bl_preview(ph):
    rows = [('Order 6403217', '14 lots become an order; 2 lots match loose stock', tag('New at BrickLink'), 'Pull in ▾'),
            ('Order 6403198', '3 lots become an order', tag('New at BrickLink'), 'Pull in ▾'),
            ('Plate 2 × 2 · Black', 'Here 300 pieces, at BrickLink 340', tag('Differs', 'dash'), 'Take BrickLink’s ▾'),
            ('Brick 1 × 4 · Dark Bluish Gray', 'No longer at BrickLink', tag('Gone at BrickLink', 'hatch'), 'Keep here ▾')]
    body = ''.join(drow(N.cb(i < 3), a, b, c, d, ph, 150) for i, (a, b, c, d) in enumerate(rows))
    box = card('4 differences', '<p class="n">2 come in, 1 differs and 1 is gone at BrickLink. A lot gone there is never removed here unless you tick it.</p>' + body)
    return head('BrickLink', 'Preview of what the run would change.', ph) + steps_n(LOTS, 'Preview', ph) + box + '<p class="n">One Undo for the whole run.</p>' + foot(btn('‹ Back', 'q'), btn('Next: run', 'sec'))


# ---- N2-19 how a run stops before it changes anything: bad token, budget, site down (marketing's tone rule: each ends "Nothing was changed.") ----
def sync_errors(ph):
    cases = [('A bad key or token', 'BrickLink did not accept your token. Check the four values and that this install’s address is registered there. Nothing was changed.',
              '<span class="btn sec sm">Open the connection</span>'),
             ('The day’s budget is too small', 'This run needs 12 calls and 3 are left today. It did not start. Nothing was changed.',
              '<span class="btn sec sm">Run tomorrow</span>'),
             ('The site is down', 'BrickLink did not answer. Try again in a few minutes. Nothing was changed.',
              '<span class="btn sec sm">Try again</span>')]
    body = ''.join(card(t, f'<p class="n">{m}</p><div style="display:flex;gap:10px;flex-wrap:wrap">{a}</div>') for t, m, a in cases)
    return head('BrickLink · When a run stops', 'The three ways a run stops before it changes anything. Brickset and Brick Owl say the same with their own names.', ph) + body


# ---- #531 Rebrickable list names kept on synced sets: tags on the copy, the existing tag filter (drafts of changed frames) ---
B = N.B
LISTS = [('Main collection', 5, True), ('Bought 2026', 2, True), ('Lent to a friend', 1, False)]
# one world for the #531 frames: 7 sets, 8 set-list pairs (7938-1 is in two lists), the counts of round 1's chips
LISTOF = {'7213-1': ['Main collection'], '7938-1': ['Main collection', 'Bought 2026'], '10254-1': ['Main collection'], '10210-1': ['Bought 2026'],
          '31120-1': ['Main collection'], '8043-1': ['Main collection'], '21028-1': ['Lent to a friend']}


# the chips Main collection and Bought 2026 are on: every set of an on chip is ticked, as in N1-05 (6 of 7)
LPICKED = {n for n, ls in LISTOF.items() if 'Main collection' in ls or 'Bought 2026' in ls}


def _once(html, old, new):
    assert old in html, old
    return html.replace(old, new, 1)


def _shell(g, sub, fn):
    fn.shell = (g, sub)
    return fn


_orig_frame = N.frame


def _frame(fn, ph):
    sh = getattr(fn, 'shell', None)
    if not sh:
        return _orig_frame(fn, ph)
    return (B.phone_shell if ph else B.desk_shell)(sh[0], sh[1], f'<div class="nwrap" style="display:block">{fn(ph)}</div>')


N.frame = _frame


# the sample world: added via. 7213-1, 7938-1, 10210-1 and 8043-1 came from a Rebrickable sync; 10254-1 and 31120-1 were added by hand;
# 21028-1 is from before this release. A set added by hand can still be matched by a later sync, which is the "last synced from" line.
SOURCES = [('By hand', 2), ('Rebrickable sync', 4), ('Before this release', 1)]


def detail_source(ph):
    """N2-15's Set detail with the source in place of the list tag: 'Added via' as a chip, 'last synced from' as its detail."""
    body = B.setdetail_body(ph)
    body = _once(body, '<span class="tag">Checked</span>', '<span class="tag">Checked on Rebrickable</span>')   # #489: a pulled copy names the source of its check
    if not ph:   # the Info card is on the desktop frame only
        body = _once(body, '<dd>Checked</dd>', '<dd>Checked on Rebrickable</dd>')
    row = ('<span style="display:flex;flex-basis:100%;gap:8px 10px;align-items:center;flex-wrap:wrap"><span class="lbl">Source</span>'
           f'{tag("Added via Rebrickable sync")}<span class="mono" style="font-size:12.5px;color:var(--tw-text-2)">Last synced from Rebrickable: Main collection · 18 Nov, 21:40</span></span>')
    return _once(body, '<span class="tag">Checked on Rebrickable</span>', '<span class="tag">Checked on Rebrickable</span>' + row)


def sets_source(ph):
    """The approved Sets frame with the Source filter: how a row arrived, and which Rebrickable lists it was last synced from (the list names are the detail
    of the source, not tags). No source chosen (all 7 sets)."""
    body = B.sets_body(ph)
    chip = lambda t, n: f'<span class="fchip">{t} <span class="mono">{n}</span></span>'
    rows = ('<div class="fchips" style="align-items:center"><span class="lbl" style="margin-right:4px">Added via</span>' + ''.join(chip(t, n) for t, n in SOURCES) + '</div>'
            '<div class="fchips" style="align-items:center"><span class="lbl" style="margin-right:4px">Last synced from</span>'
            + ''.join(chip('Rebrickable · ' + t, n) for t, n in [('Main collection', 5), ('Bought 2026', 2), ('Lent to a friend', 1)]) + '</div>')
    if ph:
        return _once(body, '<div style="display:flex;gap:8px;align-items:center;font:500 13px', rows + '<div style="display:flex;gap:8px;align-items:center;font:500 13px')
    return _once(body, '<div style="display:flex;flex-wrap:wrap;gap:20px 28px">', rows + '<div style="display:flex;flex-wrap:wrap;gap:20px 28px">')


def _srcline(n):
    return ', '.join(LISTOF[n])


def pick_source(ph):
    """N2-13 in the source form: each set row names the Rebrickable lists it is in as a plain line (not tags); the checkbox keeps them as the source detail."""
    by = N.seg('List', ['All', 'List', 'Theme', 'Year', 'One']) if ph else N.seg('By list', ['All linked', 'By list', 'By theme', 'By year', 'One by one'])
    chips = '<div class="fchips">' + ''.join(f'<span class="fchip{" on" if on else ""}">{t} <span class="mono">{n}</span></span>' for t, n, on in LISTS) + '</div>'
    rows = ''.join(f'<div class="nrow">{N.cb(n in LPICKED)}{N.ptile(n)}<div class="id"><b>{N.S(n)["name"]}</b><span><span class="mono">{n}</span> · {N.S(n)["meta"]}</span>'
                   f'<div class="mono" style="font-size:12px;color:var(--tw-text-2);margin-top:4px">Rebrickable: {_srcline(n)}</div></div></div>' for n in N.ORDER)
    keep = card('Keep the list names', N.chk('Keep each set’s Rebrickable list names as its source detail', True)
                   + '<p class="n">A set in two lists keeps both names. A list renamed or removed at Rebrickable updates or drops its name on the next run; the preview shows it first.</p>')
    count = '<div class="ninfo"><b>6 of 7 sets picked</b> · list names kept: Main collection, Bought 2026</div>'
    return (N.head('Rebrickable', 'Pick the sets this run covers. A set you do not pick keeps its copies, counts and fields; only its list names follow their lists.', ph) + N.steps('Pick sets', ph)
            + f'<div class="ncard"><h2>Which sets</h2>{by}{chips}<div>{rows}</div></div>' + keep + count + N.foot(N.btn('‹ Back', 'q'), N.btn('Next: preview', 'sec')))


def preview_source(ph):
    """N2-16 in the source form: the line per list says whose source detail changes."""
    rows = [('Main collection', 'Renamed at Rebrickable to "Home collection"; the source detail of 5 sets changes', tag('Renamed', 'dash'), 'Rename it ▾'),
            ('Bought 2026', 'Removed at Rebrickable; the source detail of 2 sets changes', tag('Removed', 'dash'), 'Drop the name ▾'),
            ('Lent to a friend', 'Unchanged; the source detail of 1 set', tag('Same'), 'Skip')]
    body = ''.join(N.drow(N.cb(i < 2), a, b, c, d, ph, 150) for i, (a, b, c, d) in enumerate(rows))
    return (N.head('Rebrickable', 'Preview of what the run would change, list names first.', ph) + N.steps('Preview', ph)
            + card('Rebrickable lists', '<p class="n">A list name follows its list on every set whose source detail carries it, picked or not. Nothing else on a copy changes.</p>' + body)
            + N.foot(N.btn('‹ Back', 'q'), N.btn('Next: run', 'sec')))


def sets_pulled(ph):
    """#489: the bar of a pulled copy. A pulled copy shows as checked by Rebrickable (its Lost Parts are the missing parts, none means complete) and says so
    under its bar; a copy Brick Work checked itself carries no label. 8043-1 is pulled without Lost Parts, 21028-1 with 9."""
    keep = {n: B.SETS[n]['copies'] for n in ('8043-1', '21028-1')}
    B.SETS['8043-1']['copies'] = [(1123, 0, 1123)]
    B.SETS['21028-1']['copies'] = [(589, 9, 598)]
    try:
        body = B.sets_body(ph)
    finally:
        for n, c in keep.items():
            B.SETS[n]['copies'] = c
    lab = '<div class="mono" style="font-size:11.5px;color:var(--tw-text-2);margin-top:2px">Checked on Rebrickable</div>'
    for old, new in [('3 of 7 sets incomplete', '4 of 7 sets incomplete'), ('8 copies · 69 parts missing', '8 copies · 78 parts missing'),
                     ('Incomplete <span', 'Incomplete <span'), ('1,123/1,123 · complete</div>', '1,123/1,123 · complete</div>' + lab), ('589/598 · 9 missing</div>', '589/598 · 9 missing</div>' + lab)]:
        if old in body:
            body = body.replace(old, new)
    for a, b in [('>Incomplete <span class="mono" style="color:var(--tw-text-muted);padding:0;border:0">3<', '>Incomplete <span class="mono" style="color:var(--tw-text-muted);padding:0;border:0">4<'),
                 ('>Not checked <span class="mono" style="color:var(--tw-text-muted);padding:0;border:0">2<', '>Not checked <span class="mono" style="color:var(--tw-text-muted);padding:0;border:0">0<'),
                 ('>Complete <span class="mono" style="color:var(--tw-text-muted);padding:0;border:0">1<', '>Complete <span class="mono" style="color:var(--tw-text-muted);padding:0;border:0">2<')]:
        body = body.replace(a, b)
    return body


def sel_tile(s, picks, w=None, img_h=112, limit=21):
    """A Sets tile in select mode (#500): a checkbox beside each copy's bar is the select target; a sealed set carries it beside its tag.
    The copy text wraps at `limit` characters, the room that is left beside the checkbox."""
    many = len(s['copies']) > 1
    if s.get('sealed'):
        bars = f'<div style="display:flex;gap:8px;align-items:center">{B.cb((s["n"], 0) in picks)}<span class="tag">Sealed</span></div>'
    else:
        bars = ''.join(f'<div style="display:flex;gap:8px;align-items:flex-start;margin-top:{6 if i else 0}px">{B.cb((s["n"], i) in picks)}'
                       f'<div style="flex:1;min-width:0">{B.bar(*c, label=f"#{i + 1} " if many else "", wrap=limit)}</div></div>' for i, c in enumerate(s['copies']))
    width = f'width:{w}px;' if w else ''
    return (f'<div class="stile" style="{width}">{B.pic(s["img"], img_h)}<div class="num"><span>{s["n"]}</span>'
            f'<span style="font:500 12px var(--tw-mono);color:var(--tw-text-2)">{s["price"]}</span></div><div class="nm">{s["name"]}</div>'
            f'<div class="meta">{s["meta"]}{" · " + str(len(s["copies"])) + " copies" if many else ""}</div>{bars}</div>')


def storage_select(ph):
    """#500, asked by brick-work-product: Select mode on a Storage tile with several copies. A checkbox beside each copy's bar is the select
    target (copy 2 of 7213-1 and the one copy of 7938-1 are picked); a bar above the tiles says what is picked and offers Move to another storage."""
    picks = {('7213-1', 1), ('7938-1', 0)}
    names = ('7213-1', '7938-1', '10254-1')
    bar_sel = (f'<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;border:1.5px solid var(--tw-text);border-radius:var(--tw-r-2);padding:10px 12px;background:var(--tw-accent-soft)">'
               f'<b style="font:600 14px var(--tw-font)">2 copies picked</b><span style="font-size:13px;color:var(--tw-text-2)">from 2 sets in S-0002</span>'
               f'<span style="margin-left:auto;display:flex;gap:8px"><span class="btn sm">Move to another storage</span><span class="btn sec sm">Cancel</span></span></div>')
    note = '<p style="font-size:13px;color:var(--tw-text-muted)">Pick copies, figures or part lots, then choose where they go. A set with two copies can be split between storages.</p>'
    if ph:
        tiles = ''.join(sel_tile(B.SETS[n], picks, img_h=90, limit=14) for n in names[:2])
        return (f'<div style="padding:14px 16px 0;display:flex;flex-direction:column;gap:12px"><div class="head"><div><div class="lbl">Workbench · Storage</div>'
                f'<h1 style="font:600 26px/1.15 var(--tw-font)">Shelf A2 – Town</h1><p>Shelf · 3 sets · 4 copies</p></div></div>'
                f'{B.tape("S-0002", "Shelf A2 – Town", 3)}<div style="display:flex;gap:8px;align-items:center"><span class="btn sec sm on">Select</span>'
                f'<span style="font-size:13px;color:var(--tw-text-2)">2 of 4 copies</span></div>{bar_sel}'
                f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">{tiles}</div>{note}</div>')
    tiles = ''.join(sel_tile(B.SETS[n], picks, w=232, img_h=96, limit=40) for n in names)
    return (f'<div style="padding:22px 32px 0;display:flex;flex-direction:column;gap:16px"><div class="head"><div><div class="lbl">Workbench · Storage</div><h1>Storage</h1>'
            f'<p>6 storages · 7 sets · 0 figures · 6 part lots</p></div></div><div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:12px">'
            f'{B.tape("S-0002", "Shelf A2 – Town", 3)}<div style="display:flex;gap:10px;align-items:center;font-size:13px;color:var(--tw-text-2)">Shelf · 3 sets · 4 copies · 0 figures · 0 part lots'
            f'<span style="margin-left:auto;display:flex;gap:8px"><span class="btn sec sm">Print label</span><span class="btn sec sm">Edit</span><span class="btn sm">Select</span></span></div>'
            f'{bar_sel}<div style="display:flex;gap:12px">{tiles}</div>{note}</div></div>')


FRAMES2 = [('N2-01', '25-brickset', bs_rest), ('N2-02', '26-brickset-choose-what', bs_choose),
           ('N2-03', '27-bricklink', bl_rest), ('N2-04', '28-bricklink-connect', bl_connect), ('N2-05', '29-bricklink-choose-what', bl_choose),
           ('N2-06', '30-bricklink-wanted-file', bl_file),
           ('N2-07', '31-brickowl', bo_rest), ('N2-08', '32-brickowl-choose-what', bo_choose), ('N2-09', '33-brickowl-run', bo_run),
           ('N2-10', '34-import-export', ie_page), ('N2-11', '35-own-export', own_export), ('N2-12', '36-re-import-preview', re_import),
           ('N2-17', '41-bricklink-pick-lots', bl_pick), ('N2-18', '42-bricklink-preview', bl_preview), ('N2-19', '43-sync-errors', sync_errors),
           ('N2-20', '44-source-chip', _shell('Collection', 'Sets', detail_source)), ('N2-21', '45-sets-source-filter', _shell('Collection', 'Sets', sets_source)),
           ('N2-22', '46-rebrickable-pick-sources', pick_source), ('N2-23', '47-rebrickable-preview-sources', preview_source),
           ('N2-24', '48-sets-pulled-copy', _shell('Collection', 'Sets', sets_pulled)),
           ('N2-25', '49-storage-select-mode', _shell('Workbench', 'Storage', storage_select))]
N.FRAMES = FRAMES2   # round 2's frames replace round 1's list here, so build and check cover folders 25 to 43 (n_frames.py itself covers 17 to 24)
N.DRAFTS = []

if __name__ == '__main__':
    raise SystemExit(N.main(*sys.argv[1:3]))
