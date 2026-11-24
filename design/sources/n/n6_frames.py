"""Commission N (Sync and files, #517), round 4 (draft): the rest of the per-site frames, folders 70 to 77.
BrickLink's result (70), Brick Owl's pick, preview and result (71 to 73) and the per-format steps of Import & export (74 to 77, #523).

Drawn from what each site's API really carries (research of 2026-11-24, ~/Workspace/_exports/design-brief-n/syncable-*.md; Ulf: "draw per site -
based on the data syncable via the api from the specific site"). Built on rounds 1 to 3 (imported, never copied). Where a field list is not
confirmed the frame says so with a dashed "Unverified" tag; nothing unverified is drawn as a fact.

    python n6_frames.py build|check|narrow [OUTDIR]
"""
import pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import n2_frames as N2  # noqa: E402
import n_frames as N  # noqa: E402

tag, btn, head, foot, drow, kv, card, two, seg, chk, field = N.tag, N.btn, N.head, N.foot, N.drow, N.kv, N2.card, N2.two, N.seg, N.chk, N.field
steps_n, cb, LOTS, FILE = N2.steps_n, N.cb, N2.LOTS, N2.FILE
small = 'font-size:13px;color:var(--tw-text-2)'
unv = tag('Unverified', 'dash')


def tail(text):
    return f'<span class="mono" style="{small}">{text}</span>'


# ---- 70 BrickLink result (#521): the result of frame 42's run ----------------------------------------------------------
def bl_result(ph):
    here = card(f'Here in Brick Work {tag("3 changed")}',
                '<p class="n">2 orders pulled into Orders (14 and 3 lots) · 1 lot of loose stock updated: Plate 2 × 2 · Black, 300 to 340 pieces · Brick 1 × 4 kept here.</p>'
                '<span class="btn sec sm" style="align-self:flex-start">Undo this run</span>'
                '<p class="n">Undo takes back everything this run changed here, in one step.</p>')
    there = card(f'At BrickLink {tag("0 sent")}',
                 '<p class="n">Nothing was sent. This run only read from BrickLink.</p>'
                 f'<div class="ninfo">{unv}&nbsp; Which fields of a BrickLink store lot can be changed through the API is not confirmed. '
                 'Sending lot changes stays off until the first live write shows it.</div>'
                 + kv([('Calls this run', '<span class=mono>4</span>: 1 orders list, 2 orders, 1 inventory'), ('Budget today', '<span class=mono>4 / 4,400</span>')]))
    left = card('Not changed', '<p class="n">Wanted lists never sync: BrickLink’s API has none. The price guide was off for this run.</p>')
    return (head('BrickLink', 'Finished 24 Nov, 18:20 · 3 of 3 done', ph) + steps_n(LOTS, 'Result', ph)
            + (here + there + left if ph else f'<div class="ngrid g2" style="align-items:start">{here}{there}</div>{left}')
            + foot(btn('Open sync log', 'q'), btn('Done', 'sec')))


# ---- 71 Brick Owl pick (#522) -----------------------------------------------------------------------------------------
def bo_pick(ph):
    lots = [('7213-1 · Off-Road Fire Truck & Fireboat', 'Set · used, complete · 1 at Brick Owl · 2 here', True),
            ('31109-1 · Pirate Ship', 'Set · new, sealed · 1 at Brick Owl · not here yet', True),
            ('8043-1 · Motorized Excavator', 'Set · used · 1 at Brick Owl · same here', False)]
    c = card('Collection lots', '<p class="n">Brick Owl keeps one lot per set and condition. Lots that changed at Brick Owl since the last run are ticked.</p>'
             + ''.join(f'<div class="nrow">{cb(on)}<div class="id"><b>{a}</b><span>{b}</span></div></div>' for a, b, on in lots)
             + f'<div class="ninfo">{unv}&nbsp; Parts, minifigures and minibuilds in the collection: their fields are expected to match the wishlist’s, '
               'but only sets have been read so far. The first run shows them in the preview before anything changes.</div>')
    w = card('Wishlists', '<p class="n">Each list is read with one call.</p>'
             + ''.join(f'<div class="nrow">{cb(on)}<div class="id"><b>{a}</b><span>{b}</span></div></div>' for a, b, on in [
                 ('Wanted', '8 lots · linked to Wanted here', True), ('Christmas', '3 lots · linked to Christmas here', True), ('Old ideas', '5 lots · not linked', False)]))
    o = card(f'Orders {unv}', '<p class="n">New orders are pulled into Orders. Brick Owl’s order fields have not been read yet: the list has been empty on the account tried.</p>')
    budget = ('<div class="ninfo"><b>Reading uses the daily budget.</b>'
              + kv([('Collection reads', 'about <span class=mono>8</span> of 2,000 a day'), ('Wishlist calls', 'about <span class=mono>2</span> of 2,000 a day')]) + '</div>')
    return (head('Brick Owl', 'Pick the lots and wishlists this run covers.', ph) + steps_n(LOTS, 'Pick lots', ph)
            + (c + w + o if ph else f'<div class="ngrid g2" style="align-items:start"><div class="nwrap" style="gap:16px">{c}</div><div class="nwrap" style="gap:16px">{w}{o}</div></div>')
            + budget + foot(btn('‹ Back', 'q'), btn('Next: preview', 'sec'), tail('2 lots and 2 wishlists picked')))


# ---- 72 Brick Owl preview ----------------------------------------------------------------------------------------------
def bo_preview(ph):
    rows = [(True, '31109-1 · Pirate Ship', 'Collection: here none · Brick Owl 1 (new, sealed)', tag('New there'), 'Add here ▾'),
            (True, '7213-1 · Off-Road Fire Truck & Fireboat', 'Collection: here 2 · Brick Owl 1 (used, complete)', tag('Differs', 'dash'), 'Send 2 to Brick Owl ▾'),
            (True, '8043-1 · Motorized Excavator · Wanted', 'Maximum price: here €40 · Brick Owl none', tag('Only here', 'dash'), 'Send to Brick Owl ▾'),
            (False, 'Lot 4417829 · Minibuild', 'Brick Owl has a lot Brick Work cannot place: no matching item', tag('Cannot place', 'hatch'), 'Skip ▾')]
    body = ''.join(drow(cb(on), name, meta, st, act, ph, 150) for on, name, meta, st, act in rows)
    box = card('4 differences', '<p class="n">Brick Owl has no purchase date or price per copy, so those never leave Brick Work. A lot that cannot be placed is skipped unless you choose where it goes.</p>' + body)
    info = ('<div class="ninfo"><b>Before you send.</b> Brick Work’s Undo cannot take a sent change back.'
            + kv([('Calls', 'about <span class=mono>12</span>: 10 to read, 2 to send'), ('Budget today', '<span class=mono>8 / 2,000</span> collection reads')]) + '</div>')
    n = 3
    return (head('Brick Owl', 'Preview of what the run would change.', ph) + steps_n(LOTS, 'Preview', ph) + box + info
            + foot(btn('‹ Back', 'q'), btn(f'Run {n} changes', 'lg'), tail(f'{n} of 4 chosen')))


# ---- 73 Brick Owl result -----------------------------------------------------------------------------------------------
def bo_result(ph):
    here = card(f'Here in Brick Work {tag("1 changed")}', '<p class="n">Pirate Ship (31109-1) added to Sets, new, sealed.</p>'
                '<span class="btn sec sm" style="align-self:flex-start">Undo this run</span>'
                '<p class="n">Undo takes back everything this run changed here, in one step. It cannot change what was sent to Brick Owl.</p>')
    there = card(f'At Brick Owl {tag("2 sent")}', '<p class="n">7213-1 set to quantity 2 · maximum price €40 on 8043-1 in Wanted.</p>'
                 '<div class="ninfo">A change at Brick Owl cannot be undone here. To reverse it, change it back at Brick Owl or send again.</div>'
                 + kv([('Calls this run', '<span class=mono>12</span>: 10 read, 2 sent'), ('Collection reads today', '<span class=mono>8 / 2,000</span>')]))
    left = card('Not changed', '<p class="n">1 lot Brick Work cannot place was skipped: lot 4417829. Purchase date and price are never sent: Brick Owl has no field for them.</p>')
    return (head('Brick Owl', 'Finished 24 Nov, 18:31 · 3 of 3 done', ph) + steps_n(LOTS, 'Result', ph)
            + (here + there + left if ph else f'<div class="ngrid g2" style="align-items:start">{here}{there}</div>{left}')
            + foot(btn('Open sync log', 'q'), btn('Done', 'sec')))


# ---- 74 Import: choose the file, with what the format carries (#523) ---------------------------------------------------
def imp_file(ph):
    f = card('1 · The file', field('Format', 'Brickset My Sets') + '<div class="input" style="min-height:44px;display:flex;align-items:center;justify-content:space-between;gap:10px">'
             '<span class="mono">my-sets-2026-11-19.csv</span><span class="btn q sm">Change</span></div>'
             + kv([('Size', '14 KB'), ('Rows found', '83'), ('Columns read', '9 of 11')]))
    c = card('2 · What the file carries', '<p class="n">Only what the file has can come in. Tick what this import applies.</p>'
             + chk('Sets owned, with quantity', True, '61') + chk('Sets wanted', True, '22') + chk('Notes', True, '9') + chk('Rating', False, '0 rows')
             + f'<div class="ninfo">{unv}&nbsp; The columns of Brickset’s file are checked against a real export before this is built; the list above is the expected one. A file has no purchase date or price from Brickset, so those stay as they are here.</div>')
    return (head('Import', 'Bring a file into Brick Work.', ph) + steps_n(FILE, 'Choose file', ph) + two(f, c, ph)
            + foot(btn('‹ Back', 'q'), btn('Next: choose what', 'sec')))


# ---- 75 Import result (#523): same Result step as a sync, one Undo --------------------------------------------------------
def imp_result(ph):
    done = card(f'Brickset My Sets {tag("Imported")}',
                '<p class="n">83 rows read · 61 owned sets and 22 wanted sets · 9 notes. 78 rows were new, 3 changed and 2 were the same and skipped.</p>'
                '<span class="btn sec sm" style="align-self:flex-start">Undo this import</span>'
                '<p class="n">Undo takes back everything this import changed, in one step.</p>')
    skipped = card('Not imported', '<p class="n">This file had no ratings. It has no purchase date or price either, so none were set.</p>')
    return (head('Import', 'Finished 24 Nov, 18:40', ph) + steps_n(FILE, 'Result', ph) + (done + skipped if ph else two(done, skipped, ph))
            + foot(btn('Import another file', 'q'), btn('Done', 'sec')))


# ---- 76 Export: choose what and the format (#523) ------------------------------------------------------------------------
def exp_choose(ph):
    what = card('1 · What to export', '<p class="n">One wishlist.</p>' + ''.join(N.rad(t, n, on) for t, n, on in [('Wanted', '14 sets · 62 parts', True), ('Christmas', '3 sets', False), ('Train layout', '5 sets', False)]))
    fmt = card('2 · The format', seg('BrickLink XML', ['BrickLink XML', 'CSV']) + '<p class="n">BrickLink XML is the file BrickLink’s wanted-list upload page reads. CSV opens in a spreadsheet.</p>'
               + field('Name', 'wanted-2026-11-24.xml', sel=False) + kv([('Items', '14'), ('Size', 'About 2 KB')]))
    return (head('Export · Wishlist', 'Make a file from one wishlist.', ph) + two(what, fmt, ph)
            + foot(btn('‹ Back', 'q'), btn('Preview what is included', 'sec')))


# ---- 77 Export result: nothing changes here, so no Undo ------------------------------------------------------------------
def exp_result(ph):
    done = card(f'wanted-2026-11-24.xml {tag("Ready")}', '<p class="n">14 items from Wanted, as BrickLink XML. Nothing was changed in Brick Work.</p>'
                '<div style="display:flex;gap:10px;flex-wrap:wrap"><span class="btn">Download</span><span class="btn sec">Copy the XML</span></div>'
                '<p class="n">An export never changes anything here, so it has no Undo.</p>')
    return head('Export · Wishlist', 'Finished 24 Nov, 18:44', ph) + steps_n(['Choose what', 'Choose format', 'Preview', 'Run', 'Result'], 'Result', ph) + done + foot(btn('Export another', 'q'), btn('Done', 'sec'))


N.FRAMES = [('N6-01', '70-bricklink-result', bl_result), ('N6-02', '71-brickowl-pick', bo_pick), ('N6-03', '72-brickowl-preview', bo_preview),
            ('N6-04', '73-brickowl-result', bo_result), ('N6-05', '74-import-choose-file', imp_file), ('N6-06', '75-import-result', imp_result),
            ('N6-07', '76-export-choose', exp_choose), ('N6-08', '77-export-result', exp_result)]
N.DRAFTS = []

if __name__ == '__main__':
    raise SystemExit(N.main(*sys.argv[1:3]))
