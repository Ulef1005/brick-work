"""The Edit set and Edit wish sheets (#667, #670), milestone U follow-up: drafts for Ulf's review (not approved).

Drawn to the built sheets (templates/web/toni/brickwork/collection_modules.html, edit macro), with the decisions of 2026-11-23/24:
- every segmented control has equal segments, dividers the full height of the control and a selected segment that meets the outer
  border (#667); the close button is a plain 44 px target on the title line, not larger than the title block (#667);
- Edit wish shows a currency field only on a wish stored in another currency, so a new wish has no currency fields; Status and
  Owners are not shown on a wish, their stored values are kept; Tags stay as they are (#670, product defaults, Ulf to confirm);
- Rating on Edit set (1 to 5 stars, clearable, per copy) and Priority on Edit wish (a number segment 1 to 5, clearable, no words,
  the range unverified until a live write test) are the "Editable fields" decision of 2026-11-24.

    BRAND_CHROMIUM=... python design/sources/b/edit_frames.py build [OUTDIR] | check
Folders: 63-edit-set, 64-edit-wish (desktop: a drawer on the right over the dimmed page; phone: the sheet fills the screen),
65-build-scout-idle (#668, #669: Build Scout opens without a scan; a Start scan button begins it; the number fields are wide enough
for their value and the spinners).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import b_frames as bf

ic = bf.ic

ECSS = '''
.esheet{position:absolute;top:0;bottom:0;right:0;background:var(--tw-bg);border-left:1.5px solid var(--tw-rule);padding:22px 28px 28px;display:flex;flex-direction:column;gap:18px;overflow:hidden}
.esheet.ph{left:0;border-left:0;padding:16px 16px 24px;gap:16px}
.ehead{display:flex;align-items:flex-start;gap:12px;border-bottom:1.5px solid var(--tw-rule);padding-bottom:12px}
.ehead h2{font:600 26px/32px var(--tw-font);letter-spacing:-.015em;margin:0}
.ehead .sub2{font:400 13px/18px var(--tw-mono);color:var(--tw-text-2);margin-top:2px}
.ehead .x{margin-left:auto;width:44px;height:44px;display:flex;align-items:center;justify-content:center;border-radius:var(--tw-r-1);color:var(--tw-text);flex:none;margin-top:-6px}
.efs{display:flex;flex-direction:column;gap:6px;margin:0}
.eseg{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(0,1fr);border:1.5px solid var(--tw-text);border-radius:3px;overflow:hidden;font:600 12px var(--tw-font-label);letter-spacing:.08em;text-transform:uppercase}
.eseg span{height:44px;display:flex;align-items:center;justify-content:center;text-align:center;padding:0 6px;border-left:1.5px solid var(--tw-text)}
.eseg span:first-child{border-left:0} .eseg span.on{background:var(--tw-text);color:var(--tw-bg)}
.erow{display:flex;align-items:center;justify-content:space-between;gap:14px;min-height:52px;border-bottom:1px solid var(--tw-divider);font:400 16px var(--tw-font)}
.egrp{display:flex;flex-direction:column;border-top:1px solid var(--tw-divider)}
.etwo{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px}
.etwo.ph{grid-template-columns:minmax(0,1fr)}
.money{display:flex;height:44px;border:1px solid var(--tw-text-muted);border-radius:var(--tw-r-1);background:var(--tw-field);overflow:hidden}
.money b{flex:none;width:64px;display:flex;align-items:center;padding:0 12px;border-right:1px solid var(--tw-divider);font:500 15px var(--tw-font);color:var(--tw-text-2)}
.money span{flex:1;display:flex;align-items:center;padding:0 12px;font:400 15px var(--tw-font)}
.input .ph2,.money .ph2{color:var(--tw-text-muted)}
.stars{display:flex;align-items:center;gap:6px}
.stars i{width:44px;height:44px;display:flex;align-items:center;justify-content:center;color:var(--tw-text-muted)}
.stars i.on{color:var(--tw-text)} .stars .clr{margin-left:auto;font:600 13px var(--tw-font);color:var(--tw-accent-text);width:auto;padding:0 6px}
.note{height:96px;align-items:flex-start;padding-top:12px}
.efoot{display:flex;gap:10px;justify-content:flex-end;margin-top:2px}
.edel{font:600 14px var(--tw-font);color:var(--tw-danger)}
.unv{font:400 12px var(--tw-mono);color:var(--tw-text-muted)}
.chips2{display:flex;gap:6px;flex-wrap:wrap}
.chips2 span{display:inline-flex;align-items:center;height:30px;padding:0 10px;border:1.5px solid var(--tw-divider);border-radius:3px;font:500 13px var(--tw-font);color:var(--tw-text-2)}
.chips2 span.on{border-color:var(--tw-accent);background:var(--tw-accent-soft);color:var(--tw-accent-text)}
'''

STAR = ('<svg width="26" height="26" viewBox="0 0 24 24"><path d="M12 3.2l2.6 5.5 6 .8-4.4 4.2 1.1 6-5.3-2.9-5.3 2.9 1.1-6L3.4 9.5l6-.8z" '
        'fill="{f}" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>')


def seg(items, on):
    return '<div class="eseg">' + ''.join(f'<span class="{"on" if i == on else ""}">{t}</span>' for i, t in enumerate(items)) + '</div>'


def fs(label, body, note=''):
    return f'<div class="efs"><span class="lbl">{label}</span>{body}{note}</div>'


def field(label, value, ph=False, mono=False):
    cls = ' ph2' if ph else ''
    return fs(label, f'<div class="input"><span class="{"mono" if mono else ""}{cls}">{value}</span></div>')


def money(label, cur, amount, ph=False):
    return fs(label, f'<div class="money"><b>{cur}</b><span class="{"ph2" if ph else ""}">{amount}</span></div>')


def switch(label, on):
    return f'<div class="erow"><span>{label}</span>{bf.sw(on)}</div>'


def head(title, sub, phone):
    return (f'<div class="ehead"><div><h2>{title}</h2><div class="sub2">{sub}</div></div><span class="x">{ic("close", 22)}</span></div>')


def footer(delete):
    return (f'<div class="efoot"><span class="btn sec">Discard</span><span class="btn">Save</span></div>'
            f'<div class="edel">{delete}</div>')


def edit_set(phone):
    stars = '<div class="stars">' + ''.join(f'<i class="{"on" if n < 4 else ""}">{STAR.format(f="currentColor" if n < 4 else "none")}</i>' for n in range(5)) + '<i class="clr">Clear</i></div>'
    body = (head('Edit set', '6080-1 · King&#8217;s Castle', phone)
            + fs('Condition', seg(['Not recorded', 'New', 'Used'], 2))
            + fs('Completeness', seg(['Unknown', 'Sealed', 'Complete', 'Incomplete'], 2),
                 '<p class="hint">Derived complete requires &#8220;Set is checked&#8221; and nothing missing or damaged, including minifigures. Manual values stay as chosen.</p>')
            + fs('Your rating', stars, '<p class="hint">Per copy. 1 to 5 stars; Clear leaves it unrated.</p>')
            + '<div class="egrp">' + switch('Set is checked', True) + switch('Box present', False) + switch('Instructions present', True) + '</div>'
            + f'<div class="etwo{" ph" if phone else ""}">' + money('Price paid', 'EUR', '34.90') + field('Date', '2026-11-23', mono=True) + '</div>'
            + field('Place', 'Not recorded', ph=True)
            + money('Estimate', 'EUR', 'From prices', ph=True)
            + field('Stored in', 'Shelf A1 &#8211; Castle')
            + fs('Owners', '<div class="chips2"><span class="on">Ulf</span><span>Alex</span></div>')
            + fs('Tags', '<div class="chips2"><span>Gift</span><span>Display</span></div>')
            + fs('Note', '<div class="input note"><span class="ph2">Add a note</span></div>')
            + footer('Delete set'))
    return body


def edit_wish(phone, other_currency=False):
    prio = fs('Priority', seg(['1', '2', '3', '4', '5'], 0),
              '<p class="hint">Clear leaves it unset. The app shows nothing for 1 until a higher value is set.</p><span class="unv">Range 1 to 5 unverified, confirmed after a live write test</span>')
    cur1 = money('Max price currency', 'EUR', '', ph=True) if other_currency else ''
    cur2 = money('Max with box currency', 'EUR', '', ph=True) if other_currency else ''
    body = (head('Edit wish', '383-2 · Knight&#8217;s Tournament', phone)
            + fs('Condition', seg(['Not recorded', 'New', 'Used', 'Any'], 3))
            + field('Quantity', '1')
            + field('Filled so far', 'Counted from your stock', ph=True)
            + prio
            + field('Your max price', '50')
            + (cur1 or '')
            + field('Max price with box', '70')
            + (cur2 or '')
            + fs('Tags', '<div class="chips2"><span>Gift</span><span class="on">Display</span></div>')
            + fs('Note', '<div class="input note"><span class="ph2">Add a note</span></div>')
            + footer('Remove from wishlist'))
    return body


def scout_idle(phone):
    head = ('<div class="head"><div><div class="lbl">Workbench · Build Scout</div><h1>Build Scout</h1>'
            '<p>Which sets can you build, or nearly build, from the parts you hold loose</p></div></div>')
    if phone:
        head = head.replace('font:600 30px', 'font:600 26px')
    flds = [('Parts from', 'All loose stock', 200), ('Min', '60 %', 120), ('Max missing', '20', 120), ('Theme', 'All', 150),
            ('Years', '1998 – 2024', 170), ('Size', '500 – 1500', 170), ('Sort', '% available', 150)]
    filt = ('<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end">'
            + ''.join(f'<label class="field" style="width:{w}px">{k}<span class="input" style="height:38px">{v}</span></label>' for k, v, w in flds)
            + '<span class="btn sm">Start scan</span></div>')
    idle = ('<div class="card" style="padding:28px;display:flex;flex-direction:column;gap:8px;align-items:flex-start">'
            '<div style="font:600 18px var(--tw-font)">No scan yet</div>'
            '<p style="font-size:14px;color:var(--tw-text-2);max-width:60ch">Set your filters, then start a scan. Build Scout counts the parts you hold loose against your sets and your wishes.</p>'
            + ('<span class="btn" style="margin-top:6px">Start scan</span>' if phone else '') + '</div>')
    if phone:
        return (f'<div style="padding:14px 16px 0;display:flex;flex-direction:column;gap:12px">{head}'
                f'<span class="btn sec sm" style="align-self:flex-start">Filters · 7</span>{idle}</div>')
    return f'<div style="padding:22px 32px 0;display:flex;flex-direction:column;gap:14px">{head}{filt}{idle}</div>'


def scout_framed(body, phone):
    return (bf.phone_shell if phone else bf.desk_shell)('Workbench', 'Build Scout', body)


def framed(sheet_body, phone):
    under = (bf.phone_shell if phone else bf.desk_shell)('Collection', 'Sets', bf.setdetail_body(phone))
    cls = 'esheet ph' if phone else 'esheet'
    width = '' if phone else 'width:520px;'
    return f'{under}<div class="scrim"></div><div class="{cls}" style="{width}z-index:5">{sheet_body}</div>'


FRAMES = [('65-build-scout-idle', scout_idle, (700, 700)), ('63-edit-set', edit_set, (1340, 1400)), ('64-edit-wish', edit_wish, (1000, 1060))]


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
                    html = bf.page6((scout_framed if fn is scout_idle else framed)(fn(phone), phone), w, h).replace('</style>', ECSS + '</style>', 1)
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
        print(f'Built {len(items)} edit-sheet frames in {out}')
        return 0
    bad = [k for k, (html, _, _) in items.items() if not (out / k).exists() or (out / k).read_text() != html]
    for k in bad:
        print('FRAMES: drift in', k)
    print('Edit-sheet frames OK' if not bad else f'{len(bad)} edit-sheet frames drift from edit_frames.py')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:3]))
