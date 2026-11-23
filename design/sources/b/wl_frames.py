"""Wishlist (#654) and the Wishlist set detail (#655), milestone U: drafts for Ulf's review (not approved).

A wanted set answers one question: can I buy it now at a price I accept? Per set: the picture, number, name, theme and year, what I want
(condition, count), my max, the price now for that condition with the gap to the max, and one state word. The min/avg/max strip and the
second price source live on the detail. Built on b_frames.py (shells, tokens, tag, tile, seg); every colour is a token, so dark comes
from b_frames.darken(). Pictures are empty tiles with their alt text (the catalogue is not in the repo).

    BRAND_CHROMIUM=... python design/sources/b/wl_frames.py build [OUTDIR] | check
Folders: 59-wishlist (tile view, all lists, the five states), 60-wishlist-list (list view, one list), 61-wishlist-empty, 62-wishlist-detail.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import b_frames as bf

ic, pic, card, money_row = bf.ic, bf.pic, bf.card, bf.money_row

WCSS = '''
.wl{display:flex;flex-direction:column;gap:5px;font-size:12.5px;color:var(--tw-text-2)}
.wl .r{display:flex;align-items:baseline;gap:6px;justify-content:space-between}
.wl .v{font:600 13px var(--tw-mono);color:var(--tw-text)}
.wl .gap{font:600 13px var(--tw-font);color:var(--tw-text);border-top:1px solid var(--tw-divider);padding-top:6px;margin-top:2px}
.wl .quiet{color:var(--tw-text-muted)}
.wl a{color:var(--tw-accent-text);font-weight:600}
.tag.fill{background:var(--tw-text);color:var(--tw-bg)}
.fchips{display:flex;gap:8px;flex-wrap:wrap}
.fchip{display:inline-flex;align-items:center;gap:6px;height:34px;padding:0 12px;border:1.5px solid var(--tw-divider);border-radius:3px;font:500 13.5px var(--tw-font);color:var(--tw-text-2);white-space:nowrap}
.fchip.on{border-color:var(--tw-accent);background:var(--tw-accent-soft);color:var(--tw-accent-text)}
.fchip .mono{font-size:12px}
.lrow{display:grid;grid-template-columns:56px minmax(0,1.5fr) 130px 96px minmax(0,1fr) minmax(0,1.1fr) 120px;gap:14px;align-items:center;padding:10px 0;border-bottom:1px solid var(--tw-divider);font-size:13.5px}
.lrow.h{font:600 12px var(--tw-font-label);letter-spacing:.12em;text-transform:uppercase;color:var(--tw-text-muted);border-bottom:1.5px solid var(--tw-rule);padding:0 0 8px}
.lrow .nm{font:600 14.5px/18px var(--tw-font)} .lrow .wsub{font-size:12.5px;color:var(--tw-text-2)}
.prow{display:flex;gap:12px;align-items:flex-start;padding:12px 0;border-bottom:1px solid var(--tw-divider)}
.strip{position:relative;height:6px;background:var(--tw-surface-2);border:1px solid var(--tw-divider);border-radius:3px;margin:8px 0 6px}
.strip i{position:absolute;top:-5px;width:2px;height:14px;background:var(--tw-text)}
.strip b{position:absolute;left:0;right:0;top:1px;height:2px;background:var(--tw-text-muted)}
'''

WISHES = [
    dict(n='10210-1', name='Imperial Flagship', meta='Pirates II · 2010', img='set-10210-1.png', want='Used', have='0 of 1', mx='€90.00', price='€79.14', guide='Used avg',
         src='BrickLink', state='buy', gap='€10.86 under your max', lst='Wanted sets'),
    dict(n='7938-1', name='Passenger Train', meta='Trains · 2010', img='set-7938-1.png', want='New', have='0 of 1', mx='€150.00', price='€182.00', guide='New avg',
         src='BrickLink', state='wait', gap='€32.00 over your max', lst='Wanted sets'),
    dict(n='10254-1', name='Winter Holiday Train', meta='Creator · 2016', img='set-10254-1.png', want='Used', have='0 of 1', mx=None, price='€59.91', guide='Used listings',
         src='BrickLink', state='nomax', gap='No max to compare with', lst='Gifts'),
    dict(n='31120-1', name='Medieval Castle', meta='Creator 3-in-1 · 2021', img='set-31120-1.png', want='Any', have='0 of 1', mx='$120.00', price='€127.00', guide='Used avg',
         src='BrickLink', state='differs', gap='Max in USD, price in EUR', lst='Gifts'),
    dict(n='8043-1', name='Motorized Excavator', meta='Technic · 2010', img='set-8043-1.png', want='Used', have='0 of 1', mx='€100.00', price=None, guide='Used',
         src='BrickLink', state='noprice', gap='No sales recorded yet', lst='Wanted sets'),
]
STATE = {'buy': ('Buy now', 'tag fill'), 'wait': ('Wait', 'tag'), 'nomax': ('No max', 'tag dash'), 'differs': ('Not comparable', 'tag dash'), 'noprice': ('No price', 'tag dash')}


def stag(s):
    t, c = STATE[s]
    return f'<span class="{c}">{t}</span>'


def wl_block(w):
    price = (f'<div class="r"><span>{w["guide"]}</span><span class="v">{w["price"]}</span></div>' if w['price']
             else '<div class="r"><span>No sales yet</span><span class="v quiet">-</span></div>')
    mx = (f'<div class="r"><span>Your max</span><span class="v">{w["mx"]}</span></div>' if w['mx']
          else '<div class="r"><span class="quiet">No max set</span><a>Set max</a></div>')
    return (f'<div class="wl"><div class="r"><span>Wants {w["want"].lower()}</span><span class="mono">{w["have"]}</span></div>{mx}{price}'
            f'<div class="gap">{w["gap"]}</div></div>')


def wtile(w, width=None, img_h=112, lists=False, stack=False):
    wd = f'width:{width}px;' if width else ''
    meta = w['meta'] + (f' · {w["lst"]}' if lists else '')
    return (f'<div class="stile" style="{wd}gap:0">{pic(w["img"], img_h)}<div class="num" style="{"flex-direction:column;align-items:flex-start;gap:5px" if stack else ""}"><span style="font-size:16px">{w["n"]}</span>{stag(w["state"])}</div>'
            f'<div class="nm">{w["name"]}</div><div class="meta">{meta}</div>{wl_block(w)}</div>')


def chips(items):
    return '<div class="fchips">' + ''.join(f'<span class="fchip{" on" if i == 0 else ""}">{t}<span class="mono">{n}</span></span>' for i, (t, n) in enumerate(items)) + '</div>'


GRID = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><rect x="4" y="4" width="6.5" height="6.5"/><rect x="13.5" y="4" width="6.5" height="6.5"/><rect x="4" y="13.5" width="6.5" height="6.5"/><rect x="13.5" y="13.5" width="6.5" height="6.5"/></svg>'
LIST = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg>'


def viewseg(tiles):
    return f'<div class="seg" aria-label="View"><span class="{"on" if tiles else ""}">{GRID}</span><span class="{"" if tiles else "on"}">{LIST}</span></div>'


def head(phone, h1, sub, extra=''):
    btns = ('' if phone else '<div style="margin-left:auto;display:flex;gap:10px;align-items:center"><span class="btn sec sm">Select</span><span class="btn sec sm">Upload CSV</span>'
            f'<span class="btn sm">{ic("plus", 16)}Add to wishlist</span></div>')
    return (f'<div class="head"><div><div class="lbl">Planning · Wishlist</div><h1>{h1}</h1><p>{sub}</p></div>{btns}</div>')


def controls(phone, scope=0, tiles=True, lists=True):
    seg = ('<div class="seg"><span class="on">All lists</span><span>Wanted sets</span><span>Gifts</span></div>' if scope == 0
           else '<div class="seg"><span>All lists</span><span class="on">Wanted sets</span><span>Gifts</span></div>')
    if scope == 0:
        cond = chips([('All', 5), ('Used', 3), ('New', 1), ('Not yet filled', 5)])
        price = chips([('All', 5), ('Buy now', 1), ('Wait', 1), ('No max', 1), ('Not comparable', 1), ('No price', 1)])
    else:
        cond = chips([('All', 3), ('Used', 2), ('New', 1), ('Not yet filled', 3)])
        price = chips([('All', 3), ('Buy now', 1), ('Wait', 1), ('No max', 0), ('Not comparable', 0), ('No price', 1)])
    sort = '<span class="btn sec sm">Sort: buy now first</span>'
    row3 = (f'<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">{sort}<span style="margin-left:auto">{viewseg(tiles)}</span></div>')
    return (f'<div style="display:flex;flex-direction:column;gap:12px"><div style="overflow:hidden">{seg}</div>'
            f'<div><div class="lbl" style="margin-bottom:6px">Condition</div>{cond}</div>'
            f'<div><div class="lbl" style="margin-bottom:6px">State</div>{price}</div>{row3}</div>')


def wishlist(phone):
    h1 = '1 of 5 wanted sets is under your max'
    sub = '5 sets wanted · prices are used or new averages from BrickLink for the condition you want'
    if phone:
        tiles = ''.join(wtile(w, img_h=92, lists=True, stack=True) for w in WISHES)
        body = (f'<div style="padding:16px 16px 0;display:flex;flex-direction:column;gap:14px">{head(True, h1, sub).replace("font:600 30px", "font:600 24px")}'
                f'{controls(True)}<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">{tiles}</div></div>')
    else:
        tiles = ''.join(wtile(w, width=250, lists=True) for w in WISHES)
        body = (f'<div style="padding:22px 32px 0;display:flex;flex-direction:column;gap:14px;max-width:1400px">{head(False, h1, sub)}{controls(False)}'
                f'<div style="display:flex;flex-wrap:wrap;gap:16px">{tiles}</div></div>')
    return (bf.phone_shell if phone else bf.desk_shell)('Planning', 'Wishlist', body)


def wlist(phone):
    ws = [w for w in WISHES if w['lst'] == 'Wanted sets']
    h1 = '1 of 3 sets on Wanted sets is under your max'
    sub = '3 sets wanted · prices are used or new averages from BrickLink for the condition you want'
    if phone:
        rows = ''.join(f'<div class="prow"><div style="width:56px;flex:none">{pic(w["img"], 56, 3)}</div><div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:3px">'
                       f'<div style="display:flex;justify-content:space-between;align-items:center;gap:8px"><span class="mono" style="font-weight:600">{w["n"]}</span>{stag(w["state"])}</div>'
                       f'<div class="nm" style="font:600 14px/18px var(--tw-font)">{w["name"]}</div><div class="mono" style="font-size:12px;color:var(--tw-text-2)">'
                       f'Wants {w["want"].lower()} · {w["have"]}</div><div class="mono" style="font-size:12.5px">{(w["guide"] + " " + w["price"]) if w["price"] else "No sales yet"} · max {w["mx"] or "not set"}</div>'
                       f'<div style="font:600 12.5px var(--tw-font)">{w["gap"]}</div></div></div>' for w in ws)
        body = (f'<div style="padding:16px 16px 0;display:flex;flex-direction:column;gap:14px">{head(True, h1, sub).replace("font:600 30px", "font:600 24px")}'
                f'{controls(True, 1, False)}<div style="border-top:1.5px solid var(--tw-rule)">{rows}</div></div>')
    else:
        rows = ''.join(f'<div class="lrow"><div>{pic(w["img"], 48, 3)}</div><div><div class="nm">{w["name"]}</div><div class="wsub"><span class="mono">{w["n"]}</span> · {w["meta"]}</div></div>'
                       f'<div class="mono" style="font-size:13px">{w["want"]} · {w["have"]}</div><div class="mono" style="font-weight:600">{w["mx"] or "Not set"}</div>'
                       f'<div><span class="mono" style="font-weight:600">{w["price"] or "No sales yet"}</span><div class="wsub">{w["guide"] if w["price"] else ""}</div></div>'
                       f'<div style="font-weight:600">{w["gap"]}</div><div>{stag(w["state"])}</div></div>' for w in ws)
        hdr = ('<div class="lrow h"><span></span><span>Set</span><span>Wants</span><span>Your max</span><span>Price now</span><span>Gap to max</span><span>State</span></div>')
        body = (f'<div style="padding:22px 32px 0;display:flex;flex-direction:column;gap:14px;max-width:1400px">{head(False, h1, sub)}{controls(False, 1, False)}'
                f'<div>{hdr}{rows}</div></div>')
    return (bf.phone_shell if phone else bf.desk_shell)('Planning', 'Wishlist', body)


def empty(phone):
    body = (f'<div style="padding:{"28px 16px" if phone else "40px 32px"};display:flex;flex-direction:column;gap:{"18px" if phone else "22px"};max-width:760px">'
            f'<div class="lbl">Planning · Wishlist</div><h1 style="font:600 {"26px/32px" if phone else "34px/40px"} var(--tw-font);margin:0">Nothing is on your wishlist yet</h1>'
            '<p style="font:400 15px/1.5 var(--tw-font);color:var(--tw-text-2);margin:0;max-width:52ch">Add a set you want and a price you would pay. Brick Work then tells you when it is under your max. '
            'Your collection, your parts and the other Planning pages work as before.</p>'
            '<div style="display:flex;gap:10px;flex-wrap:wrap"><span class="btn">Add to wishlist</span><span class="btn sec">Upload CSV</span></div>'
            '<p style="font-size:13px;color:var(--tw-text-muted);margin:0">A CSV is a BrickLink or Rebrickable wanted list.</p></div>')
    return (bf.phone_shell if phone else bf.desk_shell)('Planning', 'Wishlist', body)


def strip(pos):
    return f'<div class="strip"><b></b><i style="left:{pos}%"></i></div>'


def detail_cards():
    w = WISHES[0]
    wish = card('Your wish', '<dl class="kv"><dt>Wants</dt><dd>Used</dd><dt>Filled</dt><dd>0 of 1</dd><dt>List</dt><dd>Wanted sets</dd>'
                '<dt>Your max</dt><dd class="mono" style="font-weight:600">€90.00</dd><dt>Max with box</dt><dd>Not set</dd></dl>'
                '<div style="font-size:13px;color:var(--tw-accent-text);font-weight:600">Move or copy to another list</div>'
                f'<div style="display:flex;gap:6px;align-items:center;font-size:13px;color:var(--tw-text-2)">{ic("chev", 14)}Wish details</div>', 'Edit')
    prices = card('Prices',
                  '<div style="display:flex;align-items:baseline;gap:8px"><span style="font:600 15px var(--tw-font);flex:1">Used</span><span class="big" style="font-size:24px;line-height:28px">€79.14</span><span class="mono" style="font-size:12px;color:var(--tw-text-muted)">avg</span></div>'
                  + strip(46) + '<div class="mono" style="display:flex;justify-content:space-between;font-size:12px;color:var(--tw-text-2)"><span>min €5.44</span><span>max €280.00</span></div>'
                  '<div class="mono" style="font-size:11.5px;color:var(--tw-text-muted)">2 sold · 6 months · 4 Nov · fresh</div>'
                  + money_row('New', 'No sales', '') .replace('font-weight:600', 'font-weight:400;color:var(--tw-text-muted)')
                  + '<div style="font-size:13px;color:var(--tw-text-2)">One price so far, from 4 Nov. Update price adds another, and a trend line follows.</div>'
                  '<div style="font-size:13px;color:var(--tw-text-2);display:flex;gap:6px;align-items:center">' + ic('chev', 14) + 'Price records · 1</div>', 'Update price')
    return wish, prices


def detail(phone):
    w = WISHES[0]
    hero = (f'<div style="font:600 13px var(--tw-font);color:var(--tw-accent-text);display:flex;align-items:center;gap:4px">{ic("back", 16)}Wishlist</div>'
            f'<div style="display:flex;gap:20px;align-items:{"flex-start" if phone else "center"}"><div style="width:{110 if phone else 200}px;flex:none">{pic(w["img"], 84 if phone else 150, 8)}</div>'
            f'<div style="flex:1;min-width:0"><div class="mono" style="font-size:13px;color:var(--tw-text-muted)">{w["n"]} · 2010 · Pirates II</div>'
            f'<h1 style="font:600 {22 if phone else 34}px/1.15 var(--tw-font);letter-spacing:-.015em;margin:3px 0 10px">{w["name"]}</h1>'
            f'<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><span class="tag">Wants used</span>{stag("buy")}</div></div></div>')
    answer = ('<div style="border-top:1.5px solid var(--tw-rule);padding-top:12px"><div style="font:600 18px var(--tw-font)">€10.86 under your max</div>'
              '<div class="mono" style="font-size:12.5px;color:var(--tw-text-2);margin-top:3px">Used avg €79.14 · BrickLink · your max €90.00</div></div>')
    wish, prices = detail_cards()
    cards = (f'<div style="display:flex;flex-direction:column;gap:14px">{wish}{prices}</div>' if phone
             else f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;align-items:start">{wish}{prices}</div>')
    body = f'<div style="padding:{"16px 16px" if phone else "22px 32px"} 0;display:flex;flex-direction:column;gap:14px;max-width:1240px">{hero}{answer}{cards}</div>'
    return (bf.phone_shell if phone else bf.desk_shell)('Planning', 'Wishlist', body)


FRAMES = [('59-wishlist', wishlist, (860, 1720)), ('60-wishlist-list', wlist, (760, 1250)), ('61-wishlist-empty', empty, (700, 844)), ('62-wishlist-detail', detail, (900, 1000))]


def sources():
    out = {}
    for dark in (False, True):
        theme = 'dark' if dark else 'light'
        saved = bf.LOCKUP
        if dark:
            bf.LOCKUP = bf.LOCKUP_DARK
        try:
            for folder, fn, (dh, ph) in FRAMES:
                for phone, w, h in ((False, 1440, dh), (True, 390, ph)):
                    html = bf.page6(fn(phone), w, h).replace('</style>', WCSS + '</style>', 1)
                    out[f'{folder}/{theme}-{w}.html'] = (bf.darken(html) if dark else html, w, h)
        finally:
            bf.LOCKUP = saved
    return out


def main(cmd='check', outdir=None):
    out = Path(outdir) if outdir else bf.OUT
    bf.OUT = out
    items = sources()
    if cmd == 'build':
        for key, (html, w, h) in items.items():
            (out / key).parent.mkdir(parents=True, exist_ok=True)
            (out / key).write_text(html)
        for key, png in bf.render(items).items():
            (out / key).with_suffix('.png').write_bytes(png)
        print(f'Built {len(items)} wishlist frames in {out}')
        return 0
    bad = [k for k, (html, _, _) in items.items() if not (out / k).exists() or (out / k).read_text() != html]
    for k in bad:
        print('FRAMES: drift in', k)
    print('Wishlist frames OK' if not bad else f'{len(bad)} wishlist frames drift from wl_frames.py')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:3]))
