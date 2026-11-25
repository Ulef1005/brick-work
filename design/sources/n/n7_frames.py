"""Commission N (Sync and files, #517), rounds 5 to 7 (approved 2026-11-24 and 2026-11-25): every frame still missing for milestone N (Ulf, 24.11., via brick-work-product:
"ask design to write all missing frames"; gap list ~/Workspace/_exports/design-brief-n/frame-gaps-n.md). Folders 78 to 96.

G2/G3 (#551): the added-via chip and filter on loose-stock lots (78) and on wishes (79). G4 (#521): BrickLink's price guide, preview and result
(80, 81). G5 (#523): one choose-file frame for each import format still undrawn (82 to 86). G6 (#523, #470): one choose frame for each export
format still undrawn (87 to 92). G7 (#524): the result of re-importing a complete export (93). G1, the Workbench rail with Sync first, is in the shell
(b_frames.GROUPS) and needs no frame of its own.

File layouts that were not read from a real file are drawn with a dashed "Unverified" tag, never as facts: the columns are checked against a real
file before the build. Built on rounds 1 to 4 (imported, never copied).

    python n7_frames.py build|check|narrow [OUTDIR]
"""
import pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import n2_frames as N2  # noqa: E402
import n_frames as N  # noqa: E402
import n6_frames as N6  # noqa: E402,F401
import n4_frames as N4  # noqa: E402
B = N.B

tag, btn, head, foot, kv, card, two, seg, chk, field, rad = N.tag, N.btn, N.head, N.foot, N.kv, N2.card, N2.two, N.seg, N.chk, N.field, N.rad
steps_n, cb, LOTS, FILE, drow = N2.steps_n, N.cb, N2.LOTS, N2.FILE, N.drow
small = 'font-size:13px;color:var(--tw-text-2)'
unv = tag('Unverified', 'dash')
EXPORT = ['Choose what', 'Choose format', 'Preview', 'Run', 'Result']


def tail(text):
    return f'<span class="mono" style="{small}">{text}</span>'


def ph_head(lbl, title, sub, ph):
    h1 = 'font:600 26px var(--tw-font)' if ph else ''
    return f'<div class="head"><div style="flex:1;min-width:0"><div class="lbl">{lbl}</div><h1 style="{h1}">{title}</h1><p>{sub}</p></div></div>'


def fchips(label, items, on=None):
    return ('<div class="fchips" style="align-items:center"><span class="lbl" style="margin-right:4px">' + label + '</span>'
            + ''.join(f'<span class="fchip{" on" if t == on else ""}">{t} <span class="mono">{n}</span></span>' for t, n in items) + '</div>')


def lot_row(name, meta, chip, ph):
    return (f'<div class="nrow"><div class="id"><b>{name}</b><span>{meta}</span></div>{"" if ph else chip}</div>' if not ph else
            f'<div class="nrow"><div class="id"><b>{name}</b><span>{meta}</span><div style="margin-top:6px">{chip}</div></div></div>')


def padded(body, ph):
    return f'<div class="nwrap" style="padding:16px 16px 0">{body}</div>' if ph else f'<div class="page nwrap">{body}</div>'


# ---- 78 Loose stock with the added-via chip and filter (#551) ---------------------------------------------------------
def stock_source(ph):
    items = [('By hand', 1), ('Rebrickable sync', 1), ('BrickLink file', 1), ('Before this release', 1)]
    rows = [('Plate 2 × 2 · Black', '3022 · new · 340 pieces · Bulk bin', 'Added via BrickLink file'),
            ('Brick 1 × 4 · Dark Bluish Gray', '3010 · used · 120 pieces · Bulk bin', 'Added via Rebrickable sync'),
            ('Tile 1 × 2 · White', '3069b · new · 60 pieces · Sorted Technic', 'Added via By hand'),
            ('Technic Pin 3L · Black', '6558 · new · 200 pieces · Sorted Technic', 'Before this release')]
    body = (ph_head('Collection · Parts', 'Loose stock', '4 lots · 720 parts in 2 storages', ph) + fchips('Added via', items)
            + card('Lots', ''.join(lot_row(a, b, tag(c), ph) for a, b, c in rows)
                   + '<p class="n">Each lot says how it arrived. A lot a sync created is marked with that run, so the run’s Undo takes back only its own lots. '
                     'Lots from before this release read “Before this release”.</p>'))
    return padded(body, ph)


# ---- 79 Wishes with the added-via chip and filter (#551) -------------------------------------------------------------
def wish_source(ph):
    items = [('By hand', 1), ('Rebrickable sync', 1), ('Brick Owl sync', 1), ('Before this release', 1)]
    rows = [('21318-1 · Tree House', 'Wanted · up to €180', 'Added via Rebrickable sync'),
            ('31109-1 · Pirate Ship', 'Christmas · up to €25', 'Added via Brick Owl sync'),
            ('8043-1 · Motorized Excavator', 'Wanted · up to €40', 'Added via By hand'),
            ('10210-1 · Imperial Flagship', 'Old ideas · no maximum', 'Before this release')]
    return padded(ph_head('Planning · Wishlist', 'Wishlist', '4 wishes in 3 lists', ph) + fchips('Added via', items)
                  + card('Wishes', ''.join(lot_row(a, b, tag(c), ph) for a, b, c in rows)
                         + '<p class="n">Where a wish came from cannot be edited; the chip and the filter match those on Sets.</p>'), ph)


# ---- 80 / 81 BrickLink price guide (#521) ----------------------------------------------------------------------------
def pg_preview(ph):
    rows = [(True, 'Plate 2 × 2 · Black', 'New · here €0.030 · BrickLink average €0.035 (Europe)', tag('Newer there'), 'Take €0.035 ▾'),
            (True, 'Brick 1 × 4 · Dark Bluish Gray', 'Used · here none · BrickLink average €0.070', tag('New there'), 'Add price ▾'),
            (True, 'Tile 1 × 2 · White', 'New · nothing sold at BrickLink; the stock guide says €0.050', tag('Stock guide', 'dash'), 'Take €0.050 ▾'),
            (False, 'Technic Pin 3L · Black', 'New · here €0.020 (typed in) · BrickLink average €0.018', tag('Typed here', 'dash'), 'Keep €0.020 ▾')]
    body = ''.join(drow(cb(on), a, b, c, d, ph, 150) for on, a, b, c, d in rows)
    box = card('4 prices', '<p class="n">Only prices you did not type yourself are replaced unless you tick them. Region Europe, new and used, as chosen in step 2.</p>' + body)
    info = ('<div class="ninfo"><b>Reading uses the daily budget.</b>'
            + kv([('Calls', 'about <span class=mono>4</span>: one per item'), ('Budget today', '<span class=mono>4 / 4,400</span>')]) + '</div>')
    return (head('BrickLink', 'Preview of the price guide.', ph) + steps_n(LOTS, 'Preview', ph) + box + info
            + foot(btn('‹ Back', 'q'), btn('Run 3 changes', 'lg'), tail('3 of 4 chosen')))


def pg_result(ph):
    here = card(f'Here in Brick Work {tag("3 changed")}', '<p class="n">3 prices set from the BrickLink price guide: 1 newer, 1 new, 1 from the stock guide · 1 typed price kept.</p>'
                '<span class="btn sec sm" style="align-self:flex-start">Undo this run</span>'
                '<p class="n">Undo puts the earlier prices back, in one step.</p>')
    there = card(f'At BrickLink {tag("0 sent")}', '<p class="n">Nothing was sent. The price guide is read only.</p>'
                 + kv([('Calls this run', '<span class=mono>4</span>'), ('Budget today', '<span class=mono>8 / 4,400</span>')]))
    return (head('BrickLink', 'Finished 24 Nov, 18:52 · 3 of 3 done', ph) + steps_n(LOTS, 'Result', ph) + two(here, there, ph)
            + foot(btn('Open sync log', 'q'), btn('Done', 'sec')))


# ---- 82 to 86 import: the formats still undrawn (#523) ------------------------------------------------------------------
UNCHECKED = (f'<div class="ninfo">{unv}&nbsp; The columns are checked against a real file of this format before it is built. '
             'Every row an import creates says <b>Added via File import</b>.</div>')


def imp(fmt, fname, found, carries, ticks, note='', ph=False, title='Import'):
    f = card('1 · The file', field('Format', fmt) + '<div class="input" style="min-height:44px;display:flex;align-items:center;justify-content:space-between;gap:10px">'
             f'<span class="mono">{fname}</span><span class="btn q sm">Change</span></div>' + kv(found))
    c = card('2 · What the file carries', f'<p class="n">{carries}</p>' + ''.join(chk(a, on, r) for a, on, r in ticks) + note + UNCHECKED)
    return (head(title, 'Bring a file into Brick Work.', ph) + steps_n(FILE, 'Choose file', ph) + two(f, c, ph)
            + foot(btn('‹ Back', 'q'), btn('Next: choose what', 'sec')))


def imp_bl_xml(ph):
    return imp('BrickLink XML · wanted list or inventory', 'wanted-list.xml', [('Items found', '14'), ('Kind', 'Wanted list')],
               'A wanted list becomes wishes; an inventory becomes loose stock. The file says which.',
               [('Items and wanted quantity', True, '14'), ('Condition', True, 'New'), ('Maximum price', False, 'none in file'), ('Remarks', False, 'none in file')], ph=ph)


def imp_bl_orders(ph):
    return imp('BrickLink order XML', 'order-6403217.xml', [('Orders found', '1'), ('Lots', '14')],
               'Each order becomes one order in Orders, with its lots. An order email can be pasted instead of a file.',
               [('Seller, date and status', True, ''), ('Lots, quantity and price', True, '14'), ('Currency', True, 'EUR'), ('Shipping and fees', False, '')], ph=ph)


def imp_rb_csv(ph):
    return imp('Rebrickable CSV', 'my-parts-lists.csv', [('Rows found', '412'), ('Columns read', '3 of 4')],
               'A sets file becomes sets, a parts file becomes loose stock: one lot per file, or one lot per part list when the file names the lists.',
               [('Parts and colours', True, '412'), ('Quantity', True, '412'), ('Spare parts', False, '0 rows')],
               note='<div class="field">Put the loose parts in<div class="select">Bulk bin</div></div>', ph=ph)


def imp_bricktracker(ph):
    return imp('BrickTracker', 'bricktracker-export.zip', [('Sets found', '31'), ('Missing-part rows', '118')],
               'The sets and their missing parts come in; BrickTracker’s own catalogue ids are matched to Brick Work’s.',
               [('Sets and quantity', True, '31'), ('Missing parts per set', True, '118'), ('Storage places', False, '4')],
               note='<p class="n">Rows from BrickTracker read <b>Added via BrickTracker</b>, as those migrated before.</p>', ph=ph)


def imp_bw_csv(ph):
    return imp('Brick Work CSV', 'loose-stock.csv', [('Rows found', '1,830'), ('Table', 'Loose stock')],
               'A file in Brick Work’s own columns. Each column must match by name; the preview lists any that do not.',
               [('Part, colour and quantity', True, '1,830'), ('Storage place', True, '2'), ('Notes', False, '0 rows')], ph=ph)


# ---- 87 to 92 export: the formats still undrawn (#523, #470) ---------------------------------------------------------
def exp(title, sub, what, fmt, ph, facts='', preview='Preview what is included'):
    return (head(f'Export · {title}', sub, ph) + steps_n(EXPORT, 'Choose what', ph) + two(what, fmt, ph) + facts
            + foot(btn('‹ Back', 'q'), btn(preview, 'sec')))


def exp_db(ph):
    what = card('1 · What to export', '<p class="n">The whole database, as it is on disk.</p>' + kv([('Sets and copies', '8'), ('Loose stock', '1,830 parts'), ('Everything else', 'included')]))
    fmt = card('2 · The file', seg('SQLite', ['SQLite']) + field('Name', 'brick-work-2026-11-24.sqlite', sel=False) + kv([('Size', 'About 38 MB'), ('Made from', 'a copy taken now')])
               + '<div class="ninfo"><b>Keys are not included.</b> The file keeps your sync settings (directions, what syncs, remembered choices, account names), never a key, a token or a password. You re-enter your keys on each site page after a restore.</div>')
    return exp('Database file', 'A copy of the whole database for a backup.', what, fmt, ph)


def exp_insurance(ph):
    what = card('1 · What to include', chk('Sets and copies', True, '8') + chk('Loose stock', True, '1,830 parts') + chk('Minifigures', False, '12')
                + chk('Purchase price where known', True) + '<p class="n">Values are used averages from BrickLink, not what you paid.</p>')
    fmt = card('2 · The report', seg('PDF', ['PDF']) + field('Currency', 'EUR') + field('Name', 'insurance-2026-11-24.pdf', sel=False) + kv([('Pages', 'About 6'), ('Total value', '€1,420')]))
    return exp('Insurance report', 'A list of what you own and what it is worth.', what, fmt, ph)


def exp_missing(ph):
    what = card('1 · Which missing parts', ''.join(rad(t, n, on) for t, n, on in [('Every set', '4 sets · 69 parts', True), ('One set', '7213-1 · 10 parts', False), ('One storage', 'Shelf A2 – Town · 37 parts', False)])
                + chk('Take the parts in loose stock off first', True, '−14'))
    fmt = card('2 · The format', seg('CSV', ['CSV', 'BrickLink XML']) + '<p class="n">BrickLink XML is a wanted list you upload on BrickLink. CSV opens in a spreadsheet.</p>'
               + field('Name', 'missing-2026-11-24.csv', sel=False) + kv([('Lines', '41'), ('Pieces', '55')]))
    return exp('Missing parts', 'Make a file of what is still missing.', what, fmt, ph)


def exp_orderfiles(ph):
    what = card('1 · Which one', ''.join(rad(t, n, on) for t, n, on in [('Order 9900102', 'Example Parts Depot · 5 lines', True), ('Order 9900101', 'Sample Bricks Store · 7 lines', False), ('Part Runner run', '12 Nov · 38 parts', False)]))
    fmt = card('2 · The file', seg('PDF', ['PDF', 'CSV']) + '<p class="n">PDF is a printable list to pick from. CSV opens in a spreadsheet.</p>'
               + field('Name', 'order-9900102.pdf', sel=False) + kv([('Lines', '5'), ('Pages', '1')]))
    return exp('Part Runner and order files', 'A printable list for one order or one run.', what, fmt, ph)


def exp_bw_csv(ph):
    what = card('1 · Which table', ''.join(rad(t, n, on) for t, n, on in [('Loose stock', '1,830 parts', True), ('Sets and copies', '8 copies', False), ('Wishes', '2 lists', False)]))
    fmt = card('2 · The file', seg('CSV', ['CSV']) + '<p class="n">Brick Work’s own columns. The same file comes back in through Import.</p>'
               + field('Name', 'loose-stock-2026-11-24.csv', sel=False) + kv([('Rows', '1,830'), ('Size', 'About 120 KB')]))
    return exp('Brick Work CSV', 'One table in Brick Work’s own columns.', what, fmt, ph)


def exp_other(ph):
    what = card('1 · What to export', chk('Sets owned', True, '61') + chk('Sets wanted', True, '22') + chk('Loose stock', False, '1,830 parts'))
    fmt = card('2 · Another tool’s format', seg('Rebrickable CSV', ['Rebrickable CSV', 'BrickLink XML', 'Brickset CSV'])
               + '<p class="n">Rebrickable CSV and BrickLink XML are the files those sites read when you import. Only what the format carries is written.</p>'
               + field('Name', 'sets-rebrickable-2026-11-24.csv', sel=False) + kv([('Rows', '83'), ('Left out', 'notes, storage, checks')])
               + f'<div class="ninfo">{unv}&nbsp; Brickset’s import columns are checked against a real file before this is built.</div>')
    return exp('Collection in another format', 'Take your collection to another tool.', what, fmt, ph)


# ---- 93 re-import result (#524) ----------------------------------------------------------------------------------------
def reimport_result(ph):
    done = card(f'brick-work-2026-11-19.zip {tag("Imported")}', '<p class="n">3 rows applied: 1 added (31109-1 · Pirate Ship), 2 replaced by the file’s values (7213-1 copy 1, Bulk bin). 1 row was the same and skipped.</p>'
                '<span class="btn sec sm" style="align-self:flex-start">Undo this import</span>'
                '<p class="n">Undo takes back everything this import changed, in one step.</p>')
    skipped = card('Not changed', '<p class="n">Keys are not included: re-enter your keys on each site page. Sync settings came back with the file. Catalogue data was fetched again for the added set.</p>')
    return (head('Re-import', 'Finished 24 Nov, 19:03', ph) + steps_n(['Choose file', 'Choose what', 'Preview', 'Run', 'Result'], 'Result', ph)
            + (done + skipped if ph else two(done, skipped, ph)) + foot(btn('Open sync log', 'q'), btn('Done', 'sec')))


# ---- 94 and 95: frames 23 and 57 redrawn (#685; brick-work-product, 24.11.) ------------------------------------------------
# The pull and the part lists apply in one transaction and cannot report "N of M": they read "Applying the pull" with a spinner, no count and no
# ETA. Sends and Lost Parts out keep "N of M" per call. 23 and 57 stay approved until Ulf approves these.
def _spin(text):
    return f'<p class="n" style="display:flex;gap:10px;align-items:center">{N4.SPIN}{text}</p>'


def run_applying(ph):
    into = card('Into Brick Work', _spin('Applying the pull') + '<p class="n">Sets, wishes, loose stock and part lists are applied together, so there is no count for this part. If it fails, nothing here changed.</p>')
    out = card('To Rebrickable', f'<p class="mono" style="{small}">0 of 2 sent</p>{N.prog(0, 2)}<p class="n">Sends and Lost Parts start when the pull is applied, one request each.</p>')
    top = card('Running 6 changes', f'<p class="mono" style="{small}">about 1 request a second for the sends · budget today 144 / 1,000</p>'
               '<p class="n">You can leave this page. The run goes on and shows in Jobs. The pull is applied in one step, so it cannot be stopped halfway; Stop after this one works on the sends.</p>'
               '<span class="btn sec sm" style="align-self:flex-start;opacity:.55">Stop after this one</span>')
    return head('Rebrickable', 'Running 6 changes', ph) + N.steps('Run', ph) + top + (into + out if ph else f'<div class="ngrid g2">{into}{out}</div>')


def long_applying(ph):
    top = card('Sending 640 of 800', f'{N.prog(640, 800)}<p class="mono" style="{small}">about 3 min left · 1 request a second · budget today 810 / 1,000</p>'
               '<div class="ninfo">You can close this page, the browser or the tablet. The run keeps going on the server and shows in Jobs. If the server restarts, the run stops safely and shows what went out. Finished steps stay done.</div>'
               f'<div style="display:flex;gap:10px;flex-wrap:wrap">{btn("Stop after this one", "sec sm")}{btn("Open Jobs", "q sm")}</div>')
    done = card(f'Pull applied {tag("Done")}', '<p class="n">3,200 changes applied here, in one step. Undo for the run stays on the result page.</p>')
    return head('Rebrickable', 'Running 4,000 changes, started 19 Nov, 15:02', ph) + N.steps('Run', ph) + done + top


# ---- 96 an interrupted run (#685, redrawn to the build in #718; Ulf, 25.11.: "Redraw to the app") -------------------------------
# After a restart, finished stages stay done and a send in flight is never repeated (a send is not safe to repeat). The run lists only the rows that
# did not go out, the Not known row first with a "Send it too" checkbox (off); rows that went out are counted. The app lists the first 20 rows and then
# "and N more not sent"; the frame draws the first three and counts the rest.
def interrupted(ph):
    done = card(f'Pull applied {tag("Done")}', '<p class="n">3,200 changes applied here, in one step. They stay done. Undo for this pull is in Last runs, where this run is listed as Interrupted.</p>')
    also = ('<label style="display:flex;align-items:center;gap:8px;min-height:44px;font:500 15px var(--tw-font)">'
            '<span aria-hidden="true" style="width:20px;height:20px;border:2px solid var(--tw-text);border-radius:3px;background:var(--tw-surface);flex:none"></span>Send it too</label>')
    rows = ''
    for name, sub, state, kind, extra in (('Winter Holiday Train', '10254-1 · add 1 to main collection', 'Not known', 'hatch', also),
                                          ('Fire Station', '60320-1 · add 1 to main collection', 'Not sent', 'dash', ''),
                                          ('Lighthouse Point', '31051-1 · add 1 to main collection', 'Not sent', 'dash', '')):
        who = f'<div class="id"><b>{name}</b><span>{sub}</span>' + (f'<div style="margin-top:6px">{tag(state, kind)}</div>' if ph else '') + extra + '</div>'
        rows += f'<div class="nrow">{who}{"" if ph else tag(state, kind)}</div>'
    link = 'font:600 15px var(--tw-font);color:var(--tw-accent-text);display:inline-flex;align-items:center;min-height:44px'
    out = card(f'Sending {tag("Interrupted", "hatch")}', f'<p class="mono" style="{small}">640 of 800 sent · 1 not known · 159 not sent</p>' + rows
               + f'<p class="mono" style="{small}">and 157 more not sent</p>'
               + '<div class="ninfo">A send is never repeated by itself, because sending twice can change a list twice. Check the row marked Not known on Rebrickable. Tick Send it too only if it is not there, then send the rest again.</div>'
               f'<div style="display:flex;gap:16px;flex-wrap:wrap;align-items:center">{btn("Send again", "sec sm")}<span style="{link}">Open Jobs</span><span style="{link}">Open the result</span></div>')
    return head('Rebrickable', 'Interrupted 19 Nov, 15:31 · the server restarted', ph) + N.steps('Run', ph) + done + out


N.FRAMES = [('N7-01', '78-stock-added-via', N2._shell('Collection', 'Parts', stock_source)), ('N7-02', '79-wishes-added-via', N2._shell('Planning', 'Wishlist', wish_source)),
            ('N7-03', '80-bricklink-prices-preview', pg_preview), ('N7-04', '81-bricklink-prices-result', pg_result),
            ('N7-05', '82-import-bricklink-xml', imp_bl_xml), ('N7-06', '83-import-bricklink-orders', imp_bl_orders), ('N7-07', '84-import-rebrickable-csv', imp_rb_csv),
            ('N7-08', '85-import-bricktracker', imp_bricktracker), ('N7-09', '86-import-brickwork-csv', imp_bw_csv),
            ('N7-10', '87-export-database', exp_db), ('N7-11', '88-export-insurance', exp_insurance), ('N7-12', '89-export-missing-parts', exp_missing),
            ('N7-13', '90-export-order-files', exp_orderfiles), ('N7-14', '91-export-brickwork-csv', exp_bw_csv), ('N7-15', '92-export-other-formats', exp_other),
            ('N7-16', '93-re-import-result', reimport_result),
            ('N7-17', '94-rebrickable-run-applying', run_applying), ('N7-18', '95-sync-long-run-applying', long_applying),
            ('N7-19', '96-sync-run-interrupted', interrupted)]
N.DRAFTS = []

if __name__ == '__main__':
    raise SystemExit(N.main(*sys.argv[1:3]))
