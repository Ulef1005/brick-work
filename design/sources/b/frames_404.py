"""Frames of the system pages, approved 2026-11-23 (review artifact https://claude.ai/artifact/H8qLMWcvNiFWPJq7naB4H2, version 4): three
funny 404 pages (A the missing piece, B the drawer, C everywhere), the 500 in B's tone and the Review allocation line on the phone.
The app rotates the three 404 pages. Built on b_frames.py; run it from the repo root:
    BRAND_CHROMIUM=... python design/sources/b/frames_404.py build     (or: check)
"""
import io, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import b_frames as bf


def bricks(n=5, gap=2):
    out = []
    for i in range(n):
        x = 4 + i * 62
        if i == gap:
            out.append(f'<rect x="{x}" y="22" width="56" height="30" rx="3" fill="none" stroke="var(--tw-text-2)" stroke-width="1.5" stroke-dasharray="4 3"/>'
                       f'<rect x="{x+1}" y="23" width="54" height="28" rx="2" fill="url(#h404)" opacity=".55"/>'
                       f'<rect x="{x+20}" y="28" width="16" height="16" rx="3" fill="var(--tw-accent)"/><path d="M{x+25} 33l6 6M{x+31} 33l-6 6" stroke="var(--tw-on-accent)" stroke-width="2" stroke-linecap="round"/>')
        else:
            out.append(f'<rect x="{x}" y="22" width="56" height="30" rx="3" fill="var(--tw-accent)"/><rect x="{x+10}" y="15" width="12" height="8" rx="2" fill="var(--tw-accent)"/><rect x="{x+34}" y="15" width="12" height="8" rx="2" fill="var(--tw-accent)"/>')
    return ('<svg viewBox="0 0 316 60" width="316" height="60" role="img" aria-label="A row of bricks with one missing"><defs><pattern id="h404" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="1.5" height="5" fill="var(--tw-text)"/></pattern></defs>'
            + ''.join(out) + '</svg>')

def drawer(label='404 · EMPTY'):
    return ('<svg viewBox="0 0 260 120" width="260" height="120" role="img" aria-label="An empty drawer labelled 404"><defs><pattern id="h404b" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="1.5" height="5" fill="var(--tw-text)"/></pattern></defs>'
            '<rect x="10" y="8" width="240" height="30" rx="3" fill="var(--tw-surface)" stroke="var(--tw-text)" stroke-width="1.5"/>'
            '<rect x="10" y="38" width="240" height="72" rx="3" fill="var(--tw-surface)" stroke="var(--tw-text)" stroke-width="1.5"/>'
            '<rect x="22" y="48" width="216" height="52" rx="2" fill="url(#h404b)" opacity=".18"/>'
            '<rect x="78" y="52" width="104" height="26" rx="2" fill="var(--tw-accent)"/>'
            f'<text x="130" y="70" text-anchor="middle" font-family="var(--tw-font-label)" font-weight="600" font-size="13" letter-spacing="1.4" fill="var(--tw-on-accent)">{label}</text>'
            '<rect x="108" y="86" width="44" height="6" rx="3" fill="var(--tw-text)"/>'
            '<rect x="108" y="20" width="44" height="6" rx="3" fill="var(--tw-text)"/></svg>')

def everywhere():
    rows = [('Under the sofa', 'checked'), ('Behind the radiator', 'checked'), ('In the vacuum cleaner', 'checked'), ('This page', 'not found')]
    out = []
    for t, s in rows:
        last = s == 'not found'
        out.append(f'<div style="display:flex;align-items:center;gap:10px;padding:9px 0;border-top:1px solid var(--tw-divider)"><span style="width:18px;height:18px;flex:none;display:flex;align-items:center;justify-content:center;border-radius:3px;'
                   f'{"background:var(--tw-accent)" if not last else "box-shadow:inset 0 0 0 1.5px var(--tw-text-2)"}">{bf.CHECK if not last else ""}</span>'
                   f'<span style="font:500 15px var(--tw-font)">{t}</span><span class="tag{"" if not last else " dash"}" style="margin-left:auto">{"0 of 1 found" if last else s}</span></div>')
    return '<div style="width:100%;max-width:380px;margin-top:6px">' + ''.join(out) + '</div>'

LEAD = {'A': 'The link may be old. Go back to your sets and check the count.',
        'B': 'Nothing is filed under this link. Try another drawer, or go back to your sets.',
        'C': 'Under the sofa, behind the radiator, in the vacuum cleaner. This page is not there.'}
HEAD = {'A': 'This page is the missing piece', 'B': 'Drawer 404 is empty', 'C': 'We looked everywhere'}
ART = {'A': bricks, 'B': drawer, 'C': everywhere}

OFFLINE = ('Your drawers are out of reach', 'No connection to your Brick Work server. Your collection is safe where it is. Reconnect and try again.',
           '<span class="btn" style="align-self:flex-start">Try again</span>', 'No connection · offline')


def system(opt, phone, five=False, offline=False):
    h = HEAD[opt] if not five else 'This drawer is stuck'
    lead = LEAD[opt] if not five else 'Your data is safe. Try again.'
    art = ART[opt]() if not five else drawer('500 · JAMMED')
    btns = ('<span class="btn" style="align-self:flex-start">Try again</span><span class="btn sec" style="align-self:flex-start">Back to sets</span>' if five
            else '<span class="btn" style="align-self:flex-start">Back to sets</span>')
    code = 'Something went wrong · 500' if five else 'Page not found · 404'
    if offline:
        h, lead, btns, code = OFFLINE
        art = drawer('OFFLINE')
    size = '34px/40px' if not phone else '26px/32px'
    body = (f'<div style="padding:{"36px 16px" if phone else "64px 32px"};display:flex;flex-direction:{"column" if phone else "row"};gap:{"22px" if phone else "56px"};align-items:{"stretch" if phone else "flex-start"};max-width:1100px">'
            f'<div style="flex:none;{"max-width:100%;overflow:hidden" if phone else ""}">{art}</div>'
            f'<div style="display:flex;flex-direction:column;gap:14px;min-width:0"><h1 style="font:600 {size} var(--tw-font);margin:0">{h}</h1>'
            f'<p style="font:400 {"16px" if not phone else "15px"}/1.5 var(--tw-font);color:var(--tw-text-2);margin:0;max-width:46ch">{lead}</p><div style="display:flex;gap:10px;flex-wrap:wrap">{btns}</div>'
            f'<p class="mono" style="font-size:12.5px;color:var(--tw-danger);margin:0">{code}</p></div></div>')
    return (bf.phone_shell if phone else bf.desk_shell)('Manage', 'Tools & Admin', body)

def line(phone=True):
    """The corrected allocation line at 390: name, colour and number, then "6 available · 0 allocated" on its own line, then the targets."""
    def li(name, col, num, avail, stock):
        return (f'<div style="padding:16px 0;border-top:1px solid var(--tw-divider);display:flex;gap:12px"><div class="ptile" style="flex:none"></div><div style="flex:1;min-width:0">'
                f'<div style="font:600 17px var(--tw-font)">{name}</div><div style="display:flex;align-items:center;gap:8px;margin-top:4px">{bf.colour(col)}<span class="mono" style="font-size:13px;color:var(--tw-text-2)">{num}</span></div>'
                f'<div class="mono" style="font-size:13px;color:var(--tw-text-2);margin-top:6px">{avail} available · 0 allocated</div>'
                f'<div style="display:flex;flex-direction:column;gap:8px;margin-top:10px">'
                f'<div class="row" style="min-height:44px;padding:0 12px;background:var(--tw-surface-2);border-radius:8px;border:0"><div class="t">Loose stock</div><span class="input" style="width:64px;margin-left:auto;justify-content:flex-end;height:36px">{stock}</span></div>'
                f'<div class="row" style="min-height:44px;padding:0 12px;background:var(--tw-surface-2);border-radius:8px;border:0"><div class="t">Location</div><span style="margin-left:auto;font:600 15px var(--tw-font)">Not stored</span></div>'
                f'<div class="row" style="min-height:44px;padding:0 12px;background:var(--tw-surface-2);border-radius:8px;border:0"><div class="t">Lot</div><span style="margin-left:auto;font:600 15px var(--tw-font)">No lot</span></div></div></div></div>')
    body = ('<div style="padding:16px">'
            '<div style="color:var(--tw-accent-text);font:600 14px var(--tw-font);margin-bottom:8px">‹ Orders</div>'
            '<div class="mono" style="font-size:12.5px;color:var(--tw-text-2)">BrickLink 9900102 · 5 Oct 2026 · 5 lines</div>'
            '<h1 style="font:600 24px/30px var(--tw-font);margin:2px 0 8px">Example Parts Depot</h1>'
            '<div style="display:flex;gap:8px"><span class="tag dash">Counting</span><span class="tag">EUR</span></div>'
            '<div style="display:flex;gap:22px;border-bottom:1px solid var(--tw-divider);margin:16px 0 14px;font:500 14.5px var(--tw-font);color:var(--tw-text-2)"><span style="padding-bottom:10px">Order detail</span><span style="padding-bottom:10px">Count what arrived</span><span style="padding-bottom:10px;color:var(--tw-text);font-weight:600;border-bottom:2px solid var(--tw-accent)">Review allocation</span></div>'
            '<h2 style="font:600 20px var(--tw-font);margin:0 0 6px">Review the suggested allocation</h2>'
            '<p style="font-size:14.5px;color:var(--tw-text-2);margin:0 0 12px">Missing parts in your copies come first, the rest goes to loose stock. Change any target before you confirm.</p>'
            '<div style="display:flex;gap:8px"><span class="input" style="flex:1;color:var(--tw-text-muted)">' + bf.ic('search', 16) + '&nbsp; Number or name</span><span class="btn sec sm" style="width:44px;padding:0">' + bf.ic('sliders', 18) + '</span><span class="btn sec sm" style="width:44px;padding:0">' + '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M8 5v14M5 16l3 3 3-3M16 19V5M13 8l3-3 3 3"/></svg>' + '</span></div>'
            '<div class="mono" style="font-size:12.5px;color:var(--tw-text-2);margin:12px 0 4px">5 results</div>'
            + li('Plate 2 x 8', 'White', '3034', 6, 6) + li('Brick Sloped 33 3 x 1', 'Red', '4286', 4, 4) + '</div>')
    return bf.phone_shell('Workbench', 'Orders', body)

WITH_OFFLINE = False   # the offline frame (53) lands with its APPROVALS line once the wiki-agent confirms Ulf's words
NAMES = {'A': '50-404-missing-piece', 'B': '50-404-drawer', 'C': '50-404-everywhere'}
SIZES = ((False, 1440, 1000), (True, 390, 844))


def sources():
    out = {}
    for dark in (False, True):
        theme = 'dark' if dark else 'light'
        saved = bf.LOCKUP
        if dark:
            bf.LOCKUP = bf.LOCKUP_DARK
        try:
            def mk(html, w, h):
                return (bf.darken(html) if dark else html, w, h)
            for opt, folder in NAMES.items():
                for phone, w, h in SIZES:
                    out[f'{folder}/{theme}-{w}.html'] = mk(bf.page6(system(opt, phone), w, h), w, h)
            for phone, w, h in SIZES:
                out[f'51-500-drawer-stuck/{theme}-{w}.html'] = mk(bf.page6(system('B', phone, True), w, h), w, h)
            for phone, w, h in (SIZES if WITH_OFFLINE else ()):
                out[f'53-offline/{theme}-{w}.html'] = mk(bf.page6(system('B', phone, offline=True), w, h), w, h)
            out[f'52-order-allocation-line/{theme}-390.html'] = mk(bf.page6(line(), 390, 1400), 390, 1400)
        finally:
            bf.LOCKUP = saved
    return out


def main(cmd):
    items = sources()
    if cmd == 'build':
        for key, (html, w, h) in items.items():
            (bf.OUT / key).parent.mkdir(parents=True, exist_ok=True)
            (bf.OUT / key).write_text(html)
        for key, png in bf.render(items).items():
            (bf.OUT / key).with_suffix('.png').write_bytes(png)
        print(f'Built {len(items)} system-page frames in design/screens-b/')
        return 0
    bad = [k for k, (html, _, _) in items.items() if not (bf.OUT / k).exists() or (bf.OUT / k).read_text() != html]
    for k in bad:
        print('FRAMES: drift in', k)
    print('System-page frames OK' if not bad else f'{len(bad)} system-page frames drift from frames_404.py')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 'check'))
