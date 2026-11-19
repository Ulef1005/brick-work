"""Brick Work, direction B′ Drawer Tag (commission U): the approved frames of screens round 2, generated from one source.

    python3 b_frames.py build     write design/screens-b/<NN-screen>/<theme>-<width>.html and .png
    python3 b_frames.py check     rebuild in memory, compare the HTML byte for byte and the PNGs within 0.1 % (exit 1 on drift)

Approved 2026-11-19 (Ulf: "Approve all as shown (Recommended)"; review artifact https://claude.ai/artifact/FX8PAj3J9cgVkY42oPGc8a,
version 3; design/APPROVALS.md). The frames use one stylesheet (B_CSS) on the app's own token names (--tw-*), so the app's CSS can be
generated from it. Copy comes from the shipped templates, changed only where an approved item says. Fonts are the self-hosted IBM Plex
files in design/fonts. Set pictures are drawn as empty white tiles with their alt text: the review showed catalogue pictures, which
this public repo does not carry (design-builder: committed frames carry synthetic content; the layout is the approved one).
Renderer: Playwright Chromium at device scale 2 (BRAND_CHROMIUM may name a Chromium binary).
"""
import io, os, pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
DESIGN = HERE.parent.parent
OUT = DESIGN / 'screens-b'
FONTDIR = DESIGN / 'fonts'
LOCKUP = (DESIGN / 'logo' / 'lockup-horizontal.svg').read_text()
RATIO = float(re.search(r'viewBox="0 0 ([\d.]+) 100"', LOCKUP).group(1)) / 100

# ---- the B′ token layer: the app's token names, B′ values -------------------------------------------------------------
TOKENS = {
    # role: (shipped value, B′ value, note)
    '--tw-bg': ('#FAFAF8', '#EDEEEB', 'B’s ground, kept (Ulf: "Each keeps its own")'),
    '--tw-surface': ('#F2EFE9', '#F8F8F6', 'cards, bars, the tab bar'),
    '--tw-surface-2': ('#ECE8DF', '#E3E5E1', 'wells, pressed rows'),
    '--tw-divider': ('#E7E2D7', '#C9CDC8', 'hairlines, now 1 px'),
    '--tw-rule': ('none', '#1A1E1E', 'new: the 1.5 px ink rule under headers and tiles'),
    '--tw-text': ('#1A1816', '#1A1E1E', 'ink'),
    '--tw-text-2': ('#45413B', '#434A4A', 'secondary text'),
    '--tw-text-muted': ('#8A847A', '#59615F', 'muted text, now 5.5:1 on the ground (was 3.6:1)'),
    '--tw-accent': ('clay oklch(0.66 0.17 45)', '#7334CF', 'violet: identity and action, clay retired (Ulf: "Retire clay")'),
    '--tw-accent-soft': ('oklch(0.93 0.04 55)', '#F0EAFB', 'selected rows, the X chip'),
    '--tw-accent-text': ('oklch(0.54 0.17 42)', '#7334CF', 'links; 5.7:1 on the soft tint'),
    '--tw-on-accent': ('#FFFFFF', '#FFFFFF', 'text on violet, 6.7:1'),
    '--tw-focus-color': ('teal oklch(0.50 0.10 215)', '#1A1E1E', 'ink: 2 px ring, 2 px offset, so focus never reads as violet selection'),
    '--tw-danger': ('oklch(0.62 0.18 25)', '#8B4F54', 'errors only; with a word, never colour alone'),
    '--tw-r-1': ('6px', '3px', 'controls, tags, tape'),
    '--tw-r-2': ('10px', '4px', 'cards, tiles'),
    '--tw-r-3': ('16px', '8px', 'sheets'),
    '--tw-font': ("'Inter'", "'IBM Plex Sans'", 'text'),
    '--tw-font-label': ('none', "'IBM Plex Sans Condensed'", 'new: tape, tabs, small section labels, in capitals'),
    '--tw-mono': ("'Geist Mono'", "'IBM Plex Mono'", 'numbers, codes, set numbers'),
}
VARS = ';'.join(f'{k}:{v[1]}' for k, v in TOKENS.items())
FACES = [('IBM Plex Sans', w, f'IBMPlexSans-{n}.woff2') for w, n in ((400, 'Regular'), (500, 'Medium'), (600, 'SemiBold'), (700, 'Bold'))] + \
        [('IBM Plex Sans Condensed', w, f'IBMPlexSansCondensed-{n}.woff2') for w, n in ((500, 'Medium'), (600, 'SemiBold'))] + \
        [('IBM Plex Mono', w, f'IBMPlexMono-{n}.woff2') for w, n in ((400, 'Regular'), (500, 'Medium'), (600, 'SemiBold'))]


def font_css(rel):
    return ''.join(f"@font-face{{font-family:'{f}';font-weight:{w};src:url('{rel}/{file}') format('woff2')}}" for f, w, file in FACES)

B_CSS = '''
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:var(--tw-bg);color:var(--tw-text);font:400 15px/1.45 var(--tw-font),system-ui,sans-serif;-webkit-font-smoothing:antialiased;overflow:hidden}
img{display:block}
.mono{font-family:var(--tw-mono),ui-monospace,monospace;font-variant-numeric:tabular-nums}
.ic{flex:none}
/* shell */
.top{height:60px;background:var(--tw-surface);border-bottom:1.5px solid var(--tw-rule);display:flex;align-items:center;gap:34px;padding:0 28px}
.top .tabs{display:flex;gap:30px;align-self:stretch;align-items:flex-end}
.tab{font:600 14px var(--tw-font-label);letter-spacing:.12em;text-transform:uppercase;color:var(--tw-text-muted);padding:0 0 17px;border-bottom:3px solid transparent}
.tab.on{color:var(--tw-text);border-bottom-color:var(--tw-accent)}
.search{margin-left:auto;display:flex;align-items:center;gap:10px;height:38px;width:340px;padding:0 12px;border:1px solid var(--tw-divider);border-radius:var(--tw-r-1);background:var(--tw-bg);color:var(--tw-text-muted);font-size:14px}
.kbd{margin-left:auto;font:500 12px var(--tw-mono);border:1px solid var(--tw-divider);border-radius:3px;padding:1px 6px}
.sub{height:44px;display:flex;align-items:center;gap:26px;padding:0 28px;border-bottom:1px solid var(--tw-divider);background:var(--tw-bg)}
.sub a{font:500 14px var(--tw-font);color:var(--tw-text-2);text-decoration:none;padding:12px 0 10px;border-bottom:2px solid transparent}
.sub a.on{color:var(--tw-text);font-weight:600;border-bottom-color:var(--tw-accent)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;height:44px;padding:0 18px;border-radius:var(--tw-r-1);font:600 15px var(--tw-font);background:var(--tw-accent);color:var(--tw-on-accent);white-space:nowrap}
.btn.sec{background:transparent;color:var(--tw-text);box-shadow:inset 0 0 0 1.5px var(--tw-text)}
.btn.sm{height:38px;font-size:14px;padding:0 14px}
.btn.focus{outline:2px solid var(--tw-focus-color);outline-offset:2px}
/* page */
.page{padding:26px 32px 0;max-width:1180px}
.eyebrow,.lbl{font:600 12px/14px var(--tw-font-label);letter-spacing:.14em;text-transform:uppercase;color:var(--tw-text-muted)}
.head{display:flex;align-items:flex-end;gap:16px;border-bottom:1.5px solid var(--tw-rule);padding-bottom:12px}
.head h1{font:600 30px/36px var(--tw-font);letter-spacing:-.015em;margin-top:4px}
.head p{color:var(--tw-text-2);font-size:14px;margin-top:2px}
.tape{display:flex;align-items:center;gap:10px;background:var(--tw-accent);color:var(--tw-on-accent);border-radius:var(--tw-r-1);padding:6px 10px;font:600 13px var(--tw-font-label);letter-spacing:.1em;text-transform:uppercase}
.tape .mono{font:500 12px var(--tw-mono);letter-spacing:0;text-transform:none;margin-left:auto;opacity:.9}
.card{background:var(--tw-surface);border:1px solid var(--tw-divider);border-radius:var(--tw-r-2)}
.group{display:flex;flex-direction:column}
.group>.lbl{padding:0 0 6px;border-bottom:1px solid var(--tw-divider)}
.hint{font-size:13px;color:var(--tw-text-muted);margin:4px 0 2px}
.row{display:flex;align-items:center;gap:14px;padding:11px 0;border-bottom:1px solid var(--tw-divider);color:inherit;text-decoration:none}
.row .t{font:600 15px var(--tw-font)} .row .n{font-size:13px;color:var(--tw-text-2);margin-top:1px}
.row .sig{margin-left:auto;font:500 12px var(--tw-mono);color:var(--tw-text-2);white-space:nowrap}
.row .chev{color:var(--tw-text-muted)}
.tag{display:inline-flex;align-items:center;height:22px;padding:0 7px;border:1.5px solid var(--tw-text);border-radius:3px;font:600 11px var(--tw-font-label);letter-spacing:.08em;text-transform:uppercase;white-space:nowrap}
.tag.dash{border-style:dashed;color:var(--tw-text-2);border-color:var(--tw-text-2)}
.xchip{display:inline-flex;align-items:center;gap:6px;height:24px;padding:0 8px 0 4px;border-radius:3px;background:var(--tw-accent-soft);color:var(--tw-accent);font:600 12px var(--tw-font)}
.xchip i{width:16px;height:16px;border-radius:3px;background:var(--tw-accent);display:flex;align-items:center;justify-content:center}
.big{font:600 28px/32px var(--tw-mono);letter-spacing:-.02em}
.field{display:flex;flex-direction:column;gap:6px;font:500 13px var(--tw-font);color:var(--tw-text-2)}
.input{height:44px;border:1px solid var(--tw-text-muted);border-radius:var(--tw-r-1);background:#fff;display:flex;align-items:center;padding:0 12px;font:400 15px var(--tw-font);color:var(--tw-text)}
.tile{background:#fff;display:flex;align-items:center;justify-content:center;border-radius:2px;overflow:hidden}
.tile img{max-width:100%;max-height:100%;object-fit:contain}
.ext{display:inline-flex;align-items:center;gap:6px;height:38px;padding:0 12px;border-radius:var(--tw-r-1);box-shadow:inset 0 0 0 1.5px var(--tw-text);font:600 14px var(--tw-font);color:var(--tw-text);white-space:nowrap}
/* phone */
.ptop{height:56px;background:var(--tw-surface);display:flex;align-items:center;gap:16px;padding:0 16px}
.psub{display:flex;gap:22px;padding:0 16px;border-bottom:1.5px solid var(--tw-rule);background:var(--tw-surface);overflow:hidden;white-space:nowrap}
.psub span{font:600 13px var(--tw-font-label);letter-spacing:.1em;text-transform:uppercase;color:var(--tw-text-muted);padding:10px 0 9px;border-bottom:3px solid transparent}
.psub span.on{color:var(--tw-text);border-bottom-color:var(--tw-accent)}
.tabbar{position:absolute;left:0;right:0;bottom:0;height:78px;border-top:1px solid var(--tw-divider);background:var(--tw-surface);display:flex;padding-top:9px}
.tabbar div{flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;font:500 11px var(--tw-font);color:var(--tw-text-muted)}
.tabbar div.on{color:var(--tw-text)} .tabbar div.on b{display:block;width:18px;height:3px;border-radius:2px;background:var(--tw-accent);margin-top:1px}
'''

IC = {
    'search': '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>', 'plus': '<path d="M12 5v14M5 12h14"/>',
    'chev': '<path d="M9 6l6 6-6 6"/>', 'back': '<path d="M15 6l-6 6 6 6"/>',
    'ext': '<path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"/>', 'upload': '<path d="M12 16V4M7 9l5-5 5 5M4 20h16"/>',
    'sets': '<path d="M4 9h16v10H4z"/><path d="M4 9l2-3h12l2 3"/>', 'sliders': '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
    'tag': '<path d="M3 12V4h8l10 10-8 8z"/><circle cx="7.5" cy="8" r="1.2"/>', 'wrench': '<path d="M14 6a4 4 0 105 5l-8 8-3-3 8-8z"/>',
    'doc': '<path d="M6 3h9l3 3v15H6z"/><path d="M9 11h6M9 15h6"/>', 'close': '<path d="M6 6l12 12M18 6L6 18"/>',
}


def ic(n, s=18):
    return (f'<svg class="ic" width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" '
            f'stroke-linecap="round" stroke-linejoin="round">{IC[n]}</svg>')


def lockup(h=32):
    svg = LOCKUP.replace('<svg ', f'<svg role="img" aria-label="Brick Work" style="height:{h}px;width:{round(h * RATIO)}px;flex:none;display:block" ', 1)
    return svg


def picture(img, alt):
    """A set picture's box with its alt text: the committed frames carry no catalogue pictures."""
    return f'<span style="font:400 11px var(--tw-font);color:var(--tw-text-muted);text-align:center;padding:4px">{alt}</span>'


XGLYPH = ('<svg width="10" height="10" viewBox="0 0 10 10"><path d="M2.6 2.6l4.8 4.8M7.4 2.6l-4.8 4.8" stroke="#fff" '
          'stroke-width="1.9" stroke-linecap="round"/></svg>')


def xchip(text='Not checked'):
    return f'<span class="xchip"><i>{XGLYPH}</i>{text}</span>'


def page(body, w, h):
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="frame-size" content="{w} {h}">'
            f'<style>{font_css("../../fonts")}:root{{{VARS}}}{B_CSS}html,body{{width:{w}px;height:{h}px}}</style></head><body>{body}</body></html>')


GROUPS = {'Collection': ['Sets', 'Minifigures', 'Parts', 'Instructions', 'Boxes'],
          'Workbench': ['Part Spotter', 'Set Inspector', 'Lot Sorter', 'Part Runner', 'Matchmaker', 'Build Scout', 'Orders', 'Storage'],
          'Planning': ['Wishlist', 'Prices', 'Complete sets', 'Order missing parts'],
          'Manage': ['Add', 'Tools & Admin', 'Appearance']}


def desk_shell(group, sub, main):
    tabs = ''.join(f'<span class="tab{" on" if g == group else ""}">{g}</span>' for g in GROUPS)
    subs = ''.join(f'<a class="{"on" if s == sub else ""}">{s}</a>' for s in GROUPS[group])
    return (f'<div class="top">{lockup()}<div class="tabs">{tabs}</div><div class="search">{ic("search")}Jump to a set, copy, figure or part<span class="kbd">⌘K</span></div>'
            f'<span class="btn sm">{ic("plus", 16)}Add</span></div><div class="sub">{subs}</div>{main}')


def phone_shell(group, sub, main):
    subs = ''.join(f'<span class="{"on" if s == sub else ""}">{s}</span>' for s in GROUPS[group])
    tb = ''.join(f'<div class="{"on" if g == group else ""}">{ic(i, 22)}<span>{g}</span>{"<b></b>" if g == group else ""}</div>'
                 for g, i in (('Collection', 'sets'), ('Workbench', 'sliders'), ('Planning', 'tag'), ('Manage', 'wrench')))
    return (f'<div style="position:relative;height:100%"><div class="ptop">{lockup()}<span style="margin-left:auto;color:var(--tw-text-2)">{ic("search", 22)}</span>'
            f'<span style="color:var(--tw-text-2)">{ic("plus", 22)}</span></div><div class="psub">{subs}</div>{main}<div class="tabbar">{tb}</div></div>')


def row(title, note, sig='', chev=True):
    s = f'<span class="sig">{sig}</span>' if sig else '<span style="margin-left:auto"></span>'
    return f'<div class="row"><div><div class="t">{title}</div><div class="n">{note}</div></div>{s}{"<span class=chev>" + ic("chev") + "</span>" if chev else ""}</div>'


# ---- Tools & Admin (bw_admin.html page == 'hub', intro on, demo world) ------------------------------------------------
COLLECTION = [('Statistics', 'See your collection counted by theme, storage location and purchase place.', ''),
              ('Collection sync', 'Bring a collection in from Rebrickable or Brickset and send your changes back.', ''),
              ('Unresolved items', 'Decide which catalogue item a local item is, and confirm or reject guesses.', '0 to decide'),
              ('Instruction files', 'Upload or rename the PDF booklets, or open each set’s official or Rebrickable instructions page.', '0'),
              ('Owners, tags and places', 'Edit the owners, statuses, tags, storage locations and purchase places the forms offer.', '')]
SETTINGS = [('Money and prices', 'Display currency and rates, country for retail prices.', ''),
            ('Sets and parts', 'How parts are grouped, which part list a new set starts on, Lost Parts from Rebrickable.', ''),
            ('Labels', 'The address on printed labels.', ''),
            ('Where data comes from', 'Pictures you have, sources, and when data counts as out of date.', 'for experts'),
            ('Keys and sources', 'Add your BrickLink, Rebrickable and Brickset keys and see how the local catalogue stands.', ''),
            ('Appearance', 'Choose light, dark or the device setting for this device.', '')]


def tools_body(phone):
    gs = ('<div class="card" style="overflow:hidden"><div class="tape" style="border-radius:0">Get started<span class="mono">2 of 4 done</span></div>'
          '<div style="padding:12px 14px 14px;display:flex;gap:14px;align-items:center"><div><div class="t" style="font:600 16px var(--tw-font)">Get started</div>'
          '<div class="n" style="font-size:13px;color:var(--tw-text-2);margin-top:2px">Load the catalogue, add your keys and bring your collection in, where you left off.</div></div>'
          f'<span class="chev" style="margin-left:auto;color:var(--tw-text-muted)">{ic("chev")}</span></div></div>')
    cell1 = ('<div class="card" style="padding:14px;display:flex;flex-direction:column;gap:10px;flex:1;min-width:0"><div class="lbl" style="color:var(--tw-text-2)">Prices</div>'
             '<div style="font:500 14px var(--tw-font)">Prices need a BrickLink key</div><span class="btn sec sm" style="align-self:flex-start">Add a key</span></div>')
    cell2 = ('<div class="card" style="padding:14px;display:flex;flex-direction:column;gap:10px;flex:1;min-width:0"><div class="lbl" style="color:var(--tw-text-2)">Pictures</div>'
             '<div><span class="big">1,517</span> <span style="font-size:14px;color:var(--tw-text-2)">pictures missing</span></div><span class="btn sec sm" style="align-self:flex-start">Refresh pictures</span></div>')
    jobs = row('Jobs', 'Follow imports and price refreshes, and retry or resume the ones that stopped.', '0')
    refresh = (f'<div class="group"><div class="lbl">Refresh</div><div style="display:flex;gap:12px;margin-top:12px;{"flex-direction:column" if phone else ""}">{cell1}{cell2}</div>{jobs}</div>')
    coll = '<div class="group"><div class="lbl">Your collection</div><p class="hint">Bring it in, keep it in step, see it counted.</p>' + ''.join(row(*r) for r in COLLECTION) + '</div>'
    sett = '<div class="group"><div class="lbl">Settings</div><p class="hint">What Brick Work shows and how it counts.</p>' + ''.join(row(*r) for r in SETTINGS) + '</div>'
    maint = ('<div class="group"><div class="lbl">Maintenance</div><p class="hint">Catalogue, backup, tokens, reports</p>'
             f'<div class="row"><span class="chev" style="color:var(--tw-text)">{ic("chev")}</span><div class="t">Show 8 tools</div></div></div>')
    about = '<div class="group"><div class="lbl">About</div>' + row('About Brick Work', 'Version, licence, source code and the trademark notices.') + '</div>'
    head = ('<div class="head"><div><div class="lbl">Manage</div><h1>Tools &amp; Admin</h1><p>Things you do. Choices you make once are under Settings.</p></div></div>')
    if phone:
        return (f'<div style="padding:16px 16px 0;display:flex;flex-direction:column;gap:20px">{head.replace("font:600 30px","font:600 26px")}{gs}{refresh}{coll}</div>')
    return (f'<div class="page" style="display:flex;flex-direction:column;gap:22px">{head}<div style="max-width:560px">{gs}</div>{refresh}'
            f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:32px">{coll}{sett}</div>{maint}{about}</div>')


# ---- Settings (page == 'settings'), "Largest instruction download" dropped ------------------------------------------
SET_GROUPS = [('Money and prices', [('Display currency and rates', 'EUR · no rates yet'), ('Country for retail prices', 'DE')]),
              ('Sets and parts', [('Group parts by', 'Grouped categories'), ('Part list for a new set', "Rebrickable's list first"),
                                  ('Lost Parts from Rebrickable', 'Rebrickable wins per part')]),
              ('Labels', [('Address on printed labels', 'Uses the request address')])]


def settings_body(phone):
    groups = ''.join(f'<div class="group"><div class="lbl">{g}</div>' + ''.join(row(t, n) for t, n in rows) + '</div>' for g, rows in SET_GROUPS)
    expert = (f'<div class="group"><div class="lbl" style="display:flex;gap:8px;align-items:center">Where data comes from <span class="tag dash">for experts</span></div>'
              f'<div class="row"><span class="chev" style="color:var(--tw-text)">{ic("chev")}</span><div><div class="t">Show 4 settings</div>'
              '<div class="n">Pictures you have, where pictures and set details come from, when data counts as out of date</div></div></div></div>')
    head = (f'<div style="display:flex;align-items:center;gap:6px;color:var(--tw-accent-text);font:600 14px var(--tw-font);margin-bottom:10px">{ic("back", 16)}Tools &amp; Admin</div>'
            '<div class="head"><div><h1>Settings</h1><p>What Brick Work shows and how it counts.</p></div></div>')
    pad = 'padding:16px 16px 0' if phone else 'padding:26px 32px 0;max-width:820px'
    return f'<div style="{pad};display:flex;flex-direction:column;gap:22px"><div>{head}</div>{groups}{expert}</div>'


# ---- Find instructions (#465, links out; Upload a PDF takes the file) ------------------------------------------------
MISSING = [('7213-1', 'Off-Road Fire Truck & Fireboat', 'Fire · 2010', 'set-7213-1.png'), ('7938-1', 'Passenger Train', 'Trains · 2010', 'set-7938-1.png'),
           ('8043-1', 'Motorized Excavator', 'Technic · 2010', 'set-8043-1.png'), ('10210-1', 'Imperial Flagship', 'Pirates II · 2010', 'set-10210-1.png')]


def finder_body(phone):
    def item(n, name, meta, img):
        links = (f'<span class="ext">{ic("ext", 16)}Official instructions</span><span class="ext">{ic("ext", 16)}Rebrickable</span>'
                 f'<span class="btn sm">{ic("upload", 16)}Upload a PDF</span>')
        if phone:
            return (f'<div style="padding:12px 0;border-bottom:1px solid var(--tw-divider)"><div style="display:flex;gap:12px;align-items:center">'
                    f'<div class="tile" style="width:72px;height:54px;padding:3px">{picture(img, "Set picture")}</div><div style="min-width:0"><div class="mono" style="font:600 16px var(--tw-mono)">{n}</div>'
                    f'<div style="font:500 14px var(--tw-font)">{name}</div></div></div><div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">{links}</div></div>')
        return (f'<div style="display:flex;gap:16px;align-items:center;padding:12px 0;border-bottom:1px solid var(--tw-divider)">'
                f'<div class="tile" style="width:96px;height:72px;padding:4px">{picture(img, "Set picture")}</div>'
                f'<div style="min-width:0;flex:1"><div class="mono" style="font:600 18px var(--tw-mono)">{n}</div><div style="font:500 15px var(--tw-font)">{name}</div>'
                f'<div style="font-size:13px;color:var(--tw-text-2)">{meta}</div></div><div style="display:flex;gap:8px">{links}</div></div>')
    head = ('<div class="head"><div><div class="lbl">Tools &amp; Admin</div><h1>Find instructions</h1>'
            '<p>4 sets have no booklet. Open the set’s official instructions page or its Rebrickable page, download the PDF there, then upload it here.</p></div></div>')
    controls = ('<div style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap">'
                '<label class="field" style="flex:1;min-width:200px">Set number<span class="input" style="color:var(--tw-text-muted)">For example 6081-1</span></label>'
                '<label class="field" style="width:240px">Region for official instructions<span class="input">Germany · German</span></label></div>')
    lst = '<div class="group"><div class="tape">Sets without a booklet<span class="mono">4 sets</span></div>' + ''.join(item(*m) for m in MISSING) + '</div>'
    note = '<p style="font-size:13px;color:var(--tw-text-muted)">Brick Work downloads nothing itself. The links open the set’s instructions page in a new tab.</p>'
    pad = 'padding:16px 16px 0' if phone else 'padding:26px 32px 0;max-width:1100px'
    if phone:
        head = head.replace('<p>4 sets have no booklet. Open the set’s official instructions page or its Rebrickable page, download the PDF there, then upload it here.</p>',
                            '<p>4 sets have no booklet. Open a set’s official instructions or Rebrickable page, get the PDF, then upload it.</p>')
    return f'<div style="{pad};display:flex;flex-direction:column;gap:18px">{head}{controls}{lst}{note if not phone else ""}</div>'


def parts_body(_phone=False):
    """The B′ components on one sheet: what the screens are built from."""
    def cell(title, inner, note=''):
        return (f'<div style="display:flex;flex-direction:column;gap:10px;min-width:0"><div class="lbl">{title}</div>'
                f'<div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;min-height:48px">{inner}</div>'
                f'<div style="font-size:12.5px;color:var(--tw-text-2)">{note}</div></div>')
    bar = ('<div style="width:220px"><div style="display:flex;height:8px"><i style="width:34.7%;background:var(--tw-accent)"></i>'
           '<i style="width:3.2%;background:repeating-linear-gradient(45deg,var(--tw-text) 0 1.5px,transparent 1.5px 4px);box-shadow:inset 0 0 0 1px var(--tw-text)"></i>'
           '<i style="flex:1;border:1.5px dashed var(--tw-text-2);border-left:none"></i></div><div class="mono" style="font-size:12px;color:var(--tw-text-2);margin-top:4px">130/375 · 12 missing</div></div>')
    cells = ''.join(f'<i style="display:block;width:10px;height:10px;border-radius:2px;{st}"></i>' for st in
                    ['background:var(--tw-accent);border:1.5px solid var(--tw-accent)'] * 5 +
                    ['border:1.5px solid var(--tw-text);background:repeating-linear-gradient(45deg,var(--tw-text) 0 1.5px,transparent 1.5px 4px)'] * 2 +
                    ['border:1.5px dashed var(--tw-text-2)'] * 5)
    grid = [
        cell('Buttons', '<span class="btn">Found it</span><span class="btn sec">Missing</span><span class="btn sm">Add set</span>',
             'Primary violet, secondary ink outline. 44 px tall, 3 px radius.'),
        cell('Focus', '<span class="btn sec focus">Refresh pictures</span><span class="btn focus">Add</span>',
             'Ink ring, 2 px wide, 2 px away. Never violet, so focus never looks selected.'),
        cell('Tabs', '<span class="tab on" style="padding-bottom:6px">Manage</span><span class="tab" style="padding-bottom:6px">Planning</span>',
             'Capitals, condensed. The active tab has a violet underline.'),
        cell('Label tape', '<div class="tape" style="width:300px">S-0002 Shelf A2 – Town<span class="mono">3 sets</span></div>',
             'Storage groups, Get started, list headers. White on violet, 6.7:1.'),
        cell('Status', '<span class="tag">Sealed</span><span class="tag dash">For experts</span>' + xchip(),
             'Shape carries status. The logo\u2019s X marks a set not checked yet.'),
        cell('The two Xs', xchip() + f'<span style="display:inline-flex;align-items:center;gap:6px;font:600 14px var(--tw-font);color:var(--tw-text-2)">{ic("close", 18)}Stop</span>',
             'Not checked: the logo\u2019s X, white on a violet square. Close and Stop: a thin line X, no square.'),
        cell('Progress per copy', bar, 'Violet found, hatched missing, dashed still to check. To scale.'),
        cell('Cells in the Set Inspector', f'<div style="display:flex;gap:3px">{cells}</div>', 'One cell per part of the copy.'),
        cell('Field', '<span class="input" style="width:260px;color:var(--tw-text-muted)">For example 6081-1</span>', 'Muted ink border, 44 px.'),
    ]
    return ('<div style="padding:28px 32px;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:28px 36px">' + ''.join(grid) + '</div>')


# ---- screens round 3 (approved 2026-11-19, Ulf: "round 3 approved"): Sets, Sets without storage, Set Inspector,
# Part Runner, empty Sets. Built on the round 2 stylesheet; EXTRA_CSS adds round 3's components.
HATCH = 'repeating-linear-gradient(45deg,var(--tw-text) 0 1.5px,transparent 1.5px 4px)'

EXTRA_CSS = '''
.seg{display:flex;border:1.5px solid var(--tw-text);border-radius:3px;font:600 12px var(--tw-font-label);letter-spacing:.08em;text-transform:uppercase}
.seg span{padding:6px 10px} .seg span.on{background:var(--tw-text);color:var(--tw-bg)}
.stabs{display:flex;gap:24px;font:500 14px var(--tw-font);border-bottom:1px solid var(--tw-divider)}
.stabs span{padding:10px 0 9px;color:var(--tw-text-2);border-bottom:2px solid transparent;white-space:nowrap}
.stabs span.on{color:var(--tw-text);font-weight:600;border-bottom-color:var(--tw-accent)}
.stile{background:var(--tw-surface);border:1px solid var(--tw-divider);border-radius:var(--tw-r-2);padding:9px;display:flex;flex-direction:column;min-width:0}
.stile .num{border-top:1.5px solid var(--tw-rule);margin-top:8px;padding-top:6px;display:flex;align-items:baseline;justify-content:space-between;font:600 18px var(--tw-mono)}
.stile .nm{font:600 14px/18px var(--tw-font);margin:3px 0 2px;min-height:36px}
.stile .meta{font-size:12.5px;color:var(--tw-text-2);margin-bottom:8px}
.bar{display:flex;height:8px} .bar i{display:block}
.bartxt{font:400 12px var(--tw-mono);color:var(--tw-text-2);margin:4px 0 6px;white-space:nowrap;display:flex;align-items:center;gap:6px}
.idx{display:flex;gap:10px;padding:8px 0;border-bottom:1px solid var(--tw-divider);font:500 14px var(--tw-font)}
.idx.on{color:var(--tw-accent);font-weight:600}
.cells{display:flex;flex-wrap:wrap;gap:3px}
.cells i{display:block;width:11px;height:11px;border-radius:2px}
.cells .f{background:var(--tw-accent)} .cells .m{border:1.5px solid var(--tw-text);background:''' + HATCH + '''} .cells .u{border:1.5px dashed var(--tw-text-2)}
.cnt{display:flex;align-items:stretch;border:1.5px solid var(--tw-text);border-radius:3px}
.cnt .k{padding:8px 12px;border-right:1.5px solid var(--tw-text)} .cnt .v{padding:9px 12px;flex:1;min-width:0}
.step{display:flex;align-items:center;border:1.5px solid var(--tw-text);border-radius:3px;height:56px}
.step b{width:56px;height:100%;display:flex;align-items:center;justify-content:center;font:600 24px var(--tw-font)}
.step span{min-width:56px;text-align:center;font:600 22px var(--tw-mono);border-left:1.5px solid var(--tw-text);border-right:1.5px solid var(--tw-text);height:100%;display:flex;align-items:center;justify-content:center}
'''


def colour_fill(hex_):
    """The part's own colour as the ground of its name block, text in white or ink, whichever reads (Ulf, round 3 comment)."""
    r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lum = sum(w * (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4) for w, c in zip((0.2126, 0.7152, 0.0722), (r, g, b)))
    ink = '#FFFFFF' if (1.05 / (lum + 0.05)) >= (lum + 0.05) / 0.0617 else '#1A1E1E'
    return f'background:{hex_};color:{ink}'


def found_row(n, fs):
    """The old stepper (Ulf, round 3 comment): Found ×n is the button in the middle; − and + beside it change n."""
    side = 'width:56px;height:56px;padding:0;font:600 24px var(--tw-font)'
    return (f'<div style="display:flex;gap:8px;align-items:center"><span class="btn sec" style="{side}" aria-label="One fewer">−</span>'
            f'<span class="btn" style="flex:1;height:56px;font-size:{fs}px">Found ×{n}</span><span class="btn sec" style="{side}" aria-label="One more">+</span></div>')



def pic(img, h, pad=6):
    alt = 'Part picture' if img.startswith('part-') else 'Set picture'
    return f'<div class="tile" style="height:{h}px;padding:{pad}px">{picture(img, alt)}</div>'


SETS = {s['n']: s for s in [
    dict(n='7213-1', name='Off-Road Fire Truck & Fireboat', meta='Fire · 2010', img='set-7213-1.png', price='€48.58', copies=[(365, 10, 375), (130, 12, 375)]),
    dict(n='7938-1', name='Passenger Train', meta='Trains · 2010', img='set-7938-1.png', price='€65.73', copies=[(643, 14, 657)]),
    dict(n='10254-1', name='Winter Holiday Train', meta='Creator · 2016', img='set-10254-1.png', price='€99.53', copies=[], sealed=True),
    dict(n='10210-1', name='Imperial Flagship', meta='Pirates II · 2010', img='set-10210-1.png', price='€194.31', copies=[(1590, 33, 1623)]),
    dict(n='31120-1', name='Medieval Castle', meta='Creator 3-in-1 · 2021', img='set-31120-1.png', price='€127.00', copies=[(1426, 0, 1426)]),
    dict(n='8043-1', name='Motorized Excavator', meta='Technic · 2010', img='set-8043-1.png', price='€123.40', copies=[(0, 0, 1123)]),
    dict(n='21028-1', name='New York City', meta='Skylines · 2016', img='set-21028-1.png', price='€53.94', copies=[(0, 0, 598)]),
]}
STORAGE_GROUPS = [('S-0002', 'Shelf A2 – Town', ['7213-1', '7938-1', '10254-1']), ('S-0001', 'Shelf A1 – Castle', ['10210-1', '31120-1']),
          ('S-0005', 'Technic crate', ['8043-1']), ('S-0004', 'Display case', ['21028-1'])]


def bar(found, missing, total, label=''):
    """One copy, to scale: violet found, hatched missing, dashed still to check; a copy never checked carries the X."""
    if found + missing == 0:
        return (f'<div class="bar"><i style="flex:1;border:1.5px dashed var(--tw-text-2)"></i></div>'
                f'<div class="bartxt">{xchip("Not checked")}<span>{label}0/{total:,}</span></div>')
    f, m = found / total * 100, missing / total * 100
    rest = '' if found + missing == total else '<i style="flex:1;border:1.5px dashed var(--tw-text-2);border-left:none"></i>'
    txt = f'{label}{found:,}/{total:,}' + (f' · {missing} missing' if missing else ' · complete')
    return (f'<div class="bar"><i style="width:{f:.2f}%;background:var(--tw-accent)"></i><i style="width:{m:.2f}%;background:{HATCH};'
            f'box-shadow:inset 0 0 0 1px var(--tw-text)"></i>{rest}</div><div class="bartxt">{txt}</div>')


def tile(s, w=None, img_h=112):
    if s.get('sealed'):
        bars = '<span class="tag" style="align-self:flex-start">Sealed</span>'
    else:
        many = len(s['copies']) > 1
        bars = ''.join(bar(*c, label=f'#{i + 1} ' if many else '') for i, c in enumerate(s['copies']))
    width = f'width:{w}px;' if w else ''
    return (f'<div class="stile" style="{width}">{pic(s["img"], img_h)}<div class="num"><span>{s["n"]}</span>'
            f'<span style="font:500 12px var(--tw-mono);color:var(--tw-text-2)">{s["price"]}</span></div><div class="nm">{s["name"]}</div>'
            f'<div class="meta">{s["meta"]}{" · " + str(len(s["copies"])) + " copies" if len(s["copies"]) > 1 else ""}</div>{bars}</div>')


def tape(sid, name, n):
    return f'<div class="tape"><span class="mono" style="margin:0;opacity:1;font-weight:600">{sid}</span>{name}<span class="mono">{n} {"set" if n == 1 else "sets"}</span></div>'


def sets_body(phone):
    stabs = '<div class="stabs">' + ''.join(f'<span class="{"on" if i == 0 else ""}">{t} <span class="mono" style="color:var(--tw-text-muted);padding:0;border:0">{n}</span></span>'
                                            for i, (t, n) in enumerate([('All', 7), ('Incomplete', 3), ('Not checked', 2), ('Complete', 1), ('Sealed', 1)])) + '</div>'
    head = ('<div class="head"><div><div class="lbl">Collection · Sets</div><h1>3 of 7 sets incomplete</h1>'
            '<p>8 copies · 69 parts missing in view · prices are used averages from BrickLink</p></div>'
            + ('' if phone else f'<div style="margin-left:auto;display:flex;gap:10px;align-items:center"><div class="seg"><span class="on">Drawers</span><span>Ledger</span></div>'
                                f'<span class="btn sec sm">{ic("search", 16)}Filter</span><span class="btn sm">{ic("plus", 16)}Add set</span></div>') + '</div>')
    if phone:
        g = STORAGE_GROUPS[0]
        tiles = ''.join(tile(SETS[n], img_h=90) for n in g[2][:2])
        body = (f'<div style="padding:16px 16px 0;display:flex;flex-direction:column;gap:14px">{head.replace("font:600 30px", "font:600 26px")}'
                f'<div style="display:flex;gap:8px;align-items:center"><div class="seg"><span class="on">Drawers</span><span>Ledger</span></div><span class="btn sec sm" style="margin-left:auto">{ic("search", 16)}Filter</span></div>'
                f'<div style="overflow:hidden">{stabs}</div><div style="display:flex;gap:8px;align-items:center;font:500 13px var(--tw-font);color:var(--tw-text-2)">{ic("sliders", 16)}Storage: all <span class="mono" style="margin-left:auto">5 storages</span></div>'
                f'{tape(*g[:2], len(g[2]))}<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">{tiles}</div></div>')
        return body
    idx = ''.join(f'<div class="idx"><span class="mono" style="color:var(--tw-text-muted);font-size:12px;padding-top:2px">{sid}</span><span>{name}</span>'
                  f'<span class="mono" style="margin-left:auto;font-size:12px">{len(nums) + (1 if sid == "S-0002" else 0)}</span></div>' for sid, name, nums in STORAGE_GROUPS)
    idx = ('<div class="idx on"><span class="mono" style="font-size:12px;padding-top:2px">All</span><span>Every storage</span><span class="mono" style="margin-left:auto;font-size:12px">8</span></div>'
           + idx + '<div class="idx" style="color:var(--tw-text-2)"><span class="mono" style="color:var(--tw-text-muted);font-size:12px;padding-top:2px">—</span><span>No storage</span><span class="mono" style="margin-left:auto;font-size:12px">0</span></div>')
    left = (f'<div style="width:230px;flex:none;border-right:1px solid var(--tw-divider);padding:22px 20px;background:var(--tw-surface);min-height:900px">'
            f'<div class="lbl">Storage index</div><div style="margin-top:8px">{idx}</div><div class="lbl" style="margin-top:24px">Copies counted</div>'
            '<div style="font-size:13px;color:var(--tw-text-2);margin-top:6px">Each copy once, in the storage it sits in.</div>'
            '<div class="lbl" style="margin-top:24px">Key</div><div style="font-size:13px;line-height:19px;color:var(--tw-text-2);margin-top:6px">One bar per copy, to scale.<br>'
            'Violet: found. Hatched: missing.<br>Dashed: still to check.</div></div>')
    groups = ''.join(f'<div style="display:flex;flex-direction:column;gap:10px">{tape(sid, name, len(nums))}<div style="display:flex;gap:12px">'
                     + ''.join(tile(SETS[n], w=206) for n in nums) + '</div></div>' for sid, name, nums in STORAGE_GROUPS)
    main = (f'<div style="flex:1;padding:22px 28px 0;min-width:0;display:flex;flex-direction:column;gap:14px">{head}'
            f'<div style="display:flex;align-items:flex-end;gap:16px">{stabs}<span class="input" style="margin-left:auto;width:260px;height:38px;color:var(--tw-text-muted)">Number or name</span>'
            f'<span class="btn sec sm">Sort: number</span></div><div style="display:flex;flex-wrap:wrap;gap:20px 28px">{groups}</div></div>')
    return f'<div style="display:flex">{left}{main}</div>'


# ---- Set Inspector: copy 2 of 7213-1 mid-check; one cell per part line; missing lines as larger cards (O10b) --------
LINES = (54, 4, 73)    # found, missing, still to check: 131 part lines of 7213-1 (sample)


def inspector_body(phone):
    f, m, u = LINES
    cells = '<div class="cells">' + '<i class="f"></i>' * f + '<i class="m"></i>' * m + '<i class="u"></i>' * u + '</div>'
    head = (f'<div class="lbl">Workbench · Set Inspector</div><div style="display:flex;gap:18px;align-items:center;margin-top:6px">'
            f'<div style="width:{96 if phone else 140}px;flex:none">{pic("set-7213-1.png", 72 if phone else 104)}</div><div style="min-width:0">'
            f'<div class="mono" style="font-size:13px;color:var(--tw-text-muted)">7213-1 · Copy 2 of 2{"" if phone else " · bought used, Flohmarkt Mauerpark"}</div>'
            f'<h1 style="font:600 {24 if phone else 32}px/1.2 var(--tw-font);letter-spacing:-.015em;margin:2px 0 6px">Off-Road Fire Truck &amp; Fireboat</h1>'
            f'<span class="tag dash">Check in progress</span></div></div>')
    prog = (f'<div style="border-top:1.5px solid var(--tw-rule);padding-top:12px;display:flex;align-items:flex-end;gap:22px;flex-wrap:wrap">'
            f'<div><div class="lbl">Checked</div><div style="font:600 {36 if phone else 44}px/1 var(--tw-mono);letter-spacing:-.03em">142<span style="color:var(--tw-text-muted);font-size:22px"> of 375 parts</span></div></div>'
            f'<div style="display:flex;gap:16px;font:500 13px var(--tw-font);color:var(--tw-text-2);padding-bottom:4px;flex-wrap:wrap">'
            f'<span>{f} lines found</span><span>{m} missing</span><span>{u} to check</span></div>'
            + ('' if phone else '<div style="margin-left:auto;font-size:13px;color:var(--tw-text-muted);padding-bottom:4px">Saved 14:20 · resume any time</div>') + '</div>')
    current = (f'<div class="card" style="padding:14px;{"" if phone else "width:430px;flex:none"}"><div style="display:flex;justify-content:space-between">'
               f'<span class="lbl">Part line 59 of 131</span><span style="font-size:12px;color:var(--tw-text-muted)">{"" if phone else "keys 1 to 9 count"}</span></div>'
               f'<div style="margin-top:10px">{pic("part-3633-dbg.png", 150 if phone else 180, 14)}</div>'
               f'<div class="cnt" style="margin-top:12px"><div class="k"><div class="lbl" style="font-size:11px">Need</div><div style="font:600 34px/36px var(--tw-mono)">2</div></div>'
               f'<div class="v" style="{colour_fill("#6C6E68")}"><div style="font:600 15px/19px var(--tw-font)">Fence Lattice 1 × 4 × 1</div><div style="display:flex;gap:8px;align-items:center;margin-top:6px">'
               f'<span style="font:600 14px var(--tw-font)">Dark Bluish Gray</span>'
               f'<span class="mono" style="margin-left:auto;font-weight:600">3633</span></div></div></div>'
               f'<div style="margin-top:14px">{found_row(2, 15)}</div>'
               f'<span class="btn sec" style="width:100%;height:56px;margin-top:10px">Missing</span>'
               f'<div style="display:flex;justify-content:space-between;margin-top:12px;font:500 14px var(--tw-font);color:var(--tw-text-2)"><span>Back</span><span>Skip for later</span><span>Undo</span></div></div>')
    if phone:
        return (f'<div style="padding:14px 16px 0;display:flex;flex-direction:column;gap:14px">{head}{prog}{current}</div>')
    missing_card = (f'<div class="card" style="padding:12px;display:flex;gap:14px;align-items:center;margin-top:8px"><div style="width:96px;flex:none">{pic("part-3008-red.png", 96, 6)}</div>'
                    f'<div style="flex:1;min-width:0;align-self:stretch;border-radius:3px;padding:8px 10px;{colour_fill("#C91A09")}"><div style="font:600 15px var(--tw-font)">Brick 1 × 8</div><div style="font-size:13px">Red · <span class="mono">3008</span> · need 2</div>'
                    f'<div style="margin-top:6px;font:600 12px var(--tw-font)">1 missing</div></div><div class="step"><b>−</b><span>1</span><b>+</b></div></div>')
    done = [('part-3005-red.png', 'Brick 1 × 1', 'Red', '3005', 6), ('part-3004-red.png', 'Brick 1 × 2', 'Red', '3004', 8), ('part-3010-dbg.png', 'Brick 1 × 4', 'Dark Bluish Gray', '3010', 4)]
    rows = ''.join(f'<div style="display:flex;align-items:center;gap:12px;padding:8px 0;border-bottom:1px solid var(--tw-divider)"><div style="width:44px;flex:none">{pic(i, 44, 3)}</div>'
                   f'<div style="flex:1"><div style="font:500 14px var(--tw-font)">{n}</div><div style="font-size:12px;color:var(--tw-text-2)">{c} · <span class="mono">{num}</span></div></div>'
                   f'<span class="mono" style="font-size:12px;color:var(--tw-text-2)">{q} of {q}</span></div>' for i, n, c, num, q in done)
    right = (f'<div style="flex:1;min-width:0"><div style="display:flex;justify-content:space-between"><span class="lbl">Checked so far</span><span style="font-size:12px;color:var(--tw-text-muted)">newest first</span></div>'
             f'<div class="lbl" style="margin-top:12px;color:var(--tw-text-2)">Missing · larger, so the count stays editable</div>{missing_card}'
             f'<div class="lbl" style="margin-top:16px;color:var(--tw-text-2)">Found</div>{rows}</div>')
    return (f'<div style="padding:22px 32px 0;display:flex;flex-direction:column;gap:16px;max-width:1240px">{head}{prog}'
            f'<div><div class="lbl" style="margin-bottom:6px">One cell per part line · 131 lines</div>{cells}</div><div style="display:flex;gap:28px">{current}{right}</div></div>')


# ---- Part Runner: run 7 of 52 across 4 sets -----------------------------------------------------------------------
def runner_body(phone):
    strip = ('<div style="display:flex;gap:1.5px">' + '<i style="flex:1;height:10px;background:var(--tw-accent)"></i>' * 6
             + '<i style="flex:1;height:10px;background:var(--tw-text)"></i>' + '<i style="flex:1;height:10px;border:1px dashed var(--tw-text-muted)"></i>' * 45 + '</div>')
    card = (f'<div class="card" style="padding:10px">{pic("part-3633-dbg.png", 250 if phone else 300, 14)}'
            f'<div class="cnt" style="margin-top:10px"><div class="k"><div class="lbl" style="font-size:11px">Pick</div><div style="font:600 40px/40px var(--tw-mono)">3</div></div>'
            f'<div class="v" style="{colour_fill("#6C6E68")}"><div style="font:600 16px/20px var(--tw-font)">Fence Lattice 1 × 4 × 1</div><div style="display:flex;align-items:center;gap:8px;margin-top:6px">'
            f'<span style="font:600 15px var(--tw-font)">Dark Bluish Gray</span>'
            f'<span class="mono" style="margin-left:auto;font:600 16px var(--tw-mono)">3633</span></div></div></div>'
            f'<div class="mono" style="font-size:12px;color:var(--tw-text-2);margin-top:8px">for 10210-1 · copy 1 · 3 missing</div></div>')
    top = (f'<div style="display:flex;align-items:center;gap:10px"><span class="lbl" style="color:var(--tw-text)">Part 7 / 52</span>'
           f'<span style="margin-left:auto;font:600 14px var(--tw-font);display:flex;gap:6px;align-items:center;color:var(--tw-text-2)">Print list</span>'
           f'<span style="font:600 14px var(--tw-font);display:flex;gap:4px;align-items:center;color:var(--tw-text-2);margin-left:12px">{ic("close", 18)}Stop</span></div>')
    found = ('<div style="display:flex;flex-direction:column;gap:10px">' + found_row(3, 17) + '<span class="btn sec" style="width:100%;height:56px">Missing</span></div>')
    if phone:
        return (f'<div style="padding:12px 16px 0;display:flex;flex-direction:column;gap:12px"><div class="lbl">Workbench · Part Runner · 4 sets</div>{top}{strip}{card}{found}</div>')
    nxt = [('part-3010-dbg.png', 'Brick 1 × 4', 'Dark Bluish Gray', '3010', 2, 'S-0002 · drawer 3'), ('part-3009-lbg.png', 'Brick 1 × 6', 'Light Bluish Gray', '3009', 1, 'S-0002 · drawer 3'),
           ('part-87619-white.png', 'Slope 45° 2 × 2', 'White', '87619', 4, 'S-0001 · drawer 1')]
    rows = ''.join(f'<div style="display:flex;align-items:center;gap:12px;padding:9px 0;border-bottom:1px solid var(--tw-divider)"><div style="width:44px;flex:none">{pic(i, 44, 3)}</div>'
                   f'<div style="flex:1"><div style="font:500 14px var(--tw-font)">{n}</div><div style="font-size:12px;color:var(--tw-text-2)">{c} · <span class="mono">{num}</span> · {loc}</div></div>'
                   f'<span class="mono" style="font-weight:600">{q}×</span></div>' for i, n, c, num, q, loc in nxt)
    return (f'<div style="padding:22px 32px 0;display:flex;flex-direction:column;gap:14px;max-width:1240px">'
            f'<div class="head"><div><div class="lbl">Workbench · Part Runner</div><h1>Collecting for 4 sets</h1><p>Storage order: parts come in the order of your drawers.</p></div></div>'
            f'{top}{strip}<div style="display:flex;gap:28px"><div style="width:480px;flex:none;display:flex;flex-direction:column;gap:12px">{card}{found}</div>'
            f'<div style="flex:1;min-width:0">{tape("S-0002", "Shelf A2 – Town", 3).replace(" sets</span>", " parts next</span>")}{rows}</div></div></div>')


# ---- Empty Sets: a new install with the catalogue loaded and no sets ----------------------------------------------
def empty_body(phone):
    gs = ('<div class="card" style="overflow:hidden;max-width:560px"><div class="tape" style="border-radius:0">Get started<span class="mono">1 of 4 done</span></div>'
          '<div style="padding:12px 14px 14px"><div style="font:600 16px var(--tw-font)">Get started</div><div style="font-size:13px;color:var(--tw-text-2);margin-top:2px">'
          'Load the catalogue, add your keys and bring your collection in, where you left off.</div></div></div>')
    box = ('<div style="border:1.5px dashed var(--tw-text-2);border-radius:var(--tw-r-2);padding:22px;display:flex;flex-direction:column;gap:12px;max-width:560px">'
           f'<div style="display:flex;gap:10px;align-items:center"><span class="tag dash">No sets yet</span></div>'
           '<div style="font:600 20px var(--tw-font)">Your shelves are empty</div>'
           '<p style="font-size:14px;color:var(--tw-text-2)">Add a set by its number, or bring your collection in from Rebrickable, Brickset, BrickTracker or a BrickLink file. The catalogue is loaded, so parts and pictures come with each set.</p>'
           f'<div style="display:flex;gap:10px;flex-wrap:wrap"><span class="btn">{ic("plus", 16)}Add a set</span><span class="btn sec">Bring your collection in</span></div></div>')
    head = '<div class="head"><div><div class="lbl">Collection · Sets</div><h1>Sets</h1><p>No sets in your collection yet.</p></div></div>'
    pad = 'padding:16px 16px 0' if phone else 'padding:26px 32px 0;max-width:1180px'
    return f'<div style="{pad};display:flex;flex-direction:column;gap:20px">{head}{box}{gs}</div>'


def nostore_body(phone):
    """Sets when no storage is set at all: no storage index and no label tape, one grid (Ulf, round 3 comment). A set
    without storage, among stored ones, sits in the grid after the groups, also without tape."""
    head = ('<div class="head"><div><div class="lbl">Collection · Sets</div><h1>3 of 7 sets incomplete</h1>'
            '<p>8 copies · 69 parts missing in view · prices are used averages from BrickLink</p></div>'
            + ('' if phone else f'<div style="margin-left:auto;display:flex;gap:10px;align-items:center"><div class="seg"><span class="on">Drawers</span><span>Ledger</span></div>'
                                f'<span class="btn sec sm">{ic("search", 16)}Filter</span><span class="btn sm">{ic("plus", 16)}Add set</span></div>') + '</div>')
    order = ['7213-1', '7938-1', '10254-1', '10210-1', '31120-1', '8043-1', '21028-1']
    if phone:
        tiles = ''.join(tile(SETS[n], img_h=90) for n in order[:2])
        return (f'<div style="padding:16px 16px 0;display:flex;flex-direction:column;gap:14px">{head.replace("font:600 30px", "font:600 26px")}'
                f'<div style="display:flex;gap:8px;align-items:center"><div class="seg"><span class="on">Drawers</span><span>Ledger</span></div><span class="btn sec sm" style="margin-left:auto">{ic("search", 16)}Filter</span></div>'
                f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">{tiles}</div></div>')
    tiles = ''.join(tile(SETS[n]) for n in order)
    return (f'<div style="padding:22px 28px 0;display:flex;flex-direction:column;gap:14px">{head}'
            f'<div style="display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px">{tiles}</div></div>')


# ---- screens round 4 (approved 2026-11-19, Ulf: "round 4 approved"): Matchmaker, Build Scout, Storage.
# Built on round 3's components; the shipped "−245 parts" becomes "245 parts missing" (no minus before a number).
def cover(have, need, total_txt):
    """A coverage bar: violet what loose stock covers, hatched what is still missing."""
    f = have / need * 100
    return (f'<div class="bar" style="height:8px"><i style="width:{f:.1f}%;background:var(--tw-accent)"></i>'
            f'<i style="flex:1;background:{HATCH};box-shadow:inset 0 0 0 1px var(--tw-text)"></i></div><div class="bartxt">{total_txt}</div>')


# ---- Matchmaker ------------------------------------------------------------------------------------------------------
MATCH = [('7213-1', 'Copy 2', 'Off-Road Fire Truck & Fireboat', 'set-7213-1.png', 7, 12, 'covers 7 of 12 missing'),
         ('10210-1', 'Copy 1', 'Imperial Flagship', 'set-10210-1.png', 11, 33, 'covers 11 of 33 missing'),
         ('7938-1', 'Copy 1', 'Passenger Train', 'set-7938-1.png', 2, 14, 'covers 2 of 14 missing')]


def match_body(phone):
    head = ('<div class="head"><div><div class="lbl">Workbench · Matchmaker</div><h1>3 copies can be advanced, 0 can become complete</h1>'
            '<p>Loose stock finds, set detail takes</p></div></div>')
    rows = ''.join(f'<div style="display:flex;gap:14px;align-items:center;padding:12px 0;border-bottom:1px solid var(--tw-divider)">'
                   f'<div style="width:{72 if phone else 96}px;flex:none">{pic(img, 54 if phone else 72, 4)}</div><div style="flex:1;min-width:0">'
                   f'<div class="mono" style="font:600 {16 if phone else 18}px var(--tw-mono)">{n} <span style="font:400 12px var(--tw-mono);color:var(--tw-text-muted)">· {cp}</span></div>'
                   f'<div style="font:500 14px var(--tw-font);margin-bottom:6px">{name}</div>{cover(h, m, txt)}</div>'
                   f'<span class="chev" style="color:var(--tw-text-muted)">{ic("chev")}</span></div>' for n, cp, name, img, h, m, txt in MATCH)
    tools = (f'<div style="display:flex;gap:10px;align-items:center"><span class="input" style="flex:1;height:38px;color:var(--tw-text-muted)">Name, number or colour</span>'
             f'<span class="btn sec sm">Filter</span><span class="btn sec sm">Sort</span></div>')
    lst = (f'<div class="group"><div class="tape">Completable first, then coverage<span class="mono">3 copies</span></div>{rows}</div>'
           f'<div class="row"><span class="chev" style="color:var(--tw-text)">{ic("chev")}</span><div class="t">How matching works</div></div>')
    saves = ('<div class="group"><div class="lbl">Recent saves</div><div style="font-size:13px;color:var(--tw-text-muted);padding:10px 0">'
             'No saves yet. A part you move from loose stock into a copy shows here, with Undo.</div></div>')
    booklets = ('<div class="group"><div class="lbl">Add instruction booklets</div><p class="hint">Physical booklets · one catalogue booklet number per line. '
                'Use the full number when a set has multiple booklets. A comma and quantity can override the count for a line.</p>'
                '<label class="field" style="margin-top:8px">Set numbers<span class="input" style="height:88px;align-items:flex-start;padding-top:10px;color:var(--tw-text-muted)">For example 6081-1</span></label>'
                '<div style="display:flex;gap:10px;align-items:flex-end;margin-top:10px"><label class="field" style="width:160px">Quantity per line<span class="input">1</span></label>'
                '<span class="btn">Add booklets</span></div></div>')
    if phone:
        return f'<div style="padding:14px 16px 0;display:flex;flex-direction:column;gap:14px">{head.replace("font:600 30px", "font:600 24px")}{tools}{lst}</div>'
    return (f'<div style="padding:24px 32px 0;display:flex;flex-direction:column;gap:18px;max-width:980px">{head}{tools}{lst}{booklets}{saves}</div>')


# ---- Build Scout -----------------------------------------------------------------------------------------------------
SCOUT = [('21028-1', 'New York City', 'Skylines · 2016 · 598 parts', 'set-21028-1.png', 412, 598, '186 parts missing · no figures', '€6.10 · 12 lines unpriced'),
         ('31120-1', 'Medieval Castle', 'Creator 3-in-1 · 2021 · 1,426 parts', 'set-31120-1.png', 503, 1426, '923 parts missing · 4 of 4 figures missing', '€41.20 · 31 lines unpriced'),
         ('8043-1', 'Motorized Excavator', 'Technic · 2010 · 1,123 parts', 'set-8043-1.png', 97, 1123, '1,026 parts missing · 1 of 1 figure missing', 'not priced'),
         ('10254-1', 'Winter Holiday Train', 'Creator · 2016 · 714 parts', 'set-10254-1.png', 30, 714, '684 parts missing · 5 of 5 figures missing', 'not priced')]


def scout_body(phone):
    head = ('<div class="head"><div><div class="lbl">Workbench · Build Scout</div><h1>Build Scout</h1>'
            '<p>Which sets can you build, or nearly build, from the parts you hold loose</p></div></div>')
    filt = ('<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end">'
            + ''.join(f'<label class="field" style="width:{w}px">{k}<span class="input" style="height:38px">{v}</span></label>'
                      for k, v, w in [('Parts from', 'All loose stock', 200), ('Min', '0 %', 90), ('Max missing', 'any', 110), ('Theme', 'All', 150), ('Years', 'any – any', 130), ('Sort', '% available', 140)])
            + '<span class="btn sec sm">Apply</span></div>')

    def res(n, name, meta, img, have, need, miss, price, on=False):
        st = 'background:var(--tw-accent-soft);box-shadow:inset 3px 0 0 var(--tw-accent);' if on else ''
        return (f'<div style="display:flex;gap:14px;align-items:center;padding:12px 10px;border-bottom:1px solid var(--tw-divider);{st}">'
                f'<div style="width:{64 if phone else 84}px;flex:none">{pic(img, 50 if phone else 64, 4)}</div><div style="flex:1;min-width:0">'
                f'<div style="display:flex;gap:10px;align-items:baseline"><span class="mono" style="font:600 16px var(--tw-mono)">{n}</span><span style="font:600 14px var(--tw-font)">{name}</span></div>'
                f'<div style="font-size:12.5px;color:var(--tw-text-2);margin:2px 0 6px">{meta}</div>{cover(have, need, f"{have:,} of {need:,} · {have / need * 100:.0f} %")}</div>'
                + ('' if phone else f'<div style="text-align:right;font-size:12.5px;color:var(--tw-text-2);width:230px"><div style="font:600 13px var(--tw-font);color:var(--tw-text)">{miss}</div><div class="mono" style="margin-top:2px">{price}</div></div>')
                + '</div>')
    rows = ''.join(res(*s, on=(i == 0)) for i, s in enumerate(SCOUT))
    summary = '<p style="font-size:13px;color:var(--tw-text-muted)">4 of 7 sets · 1,042 loose pieces counted · figures shown separately · swaps listed in the set, never in the %</p>'
    if phone:
        return f'<div style="padding:14px 16px 0;display:flex;flex-direction:column;gap:12px">{head.replace("font:600 30px", "font:600 26px")}<span class="btn sec sm" style="align-self:flex-start">Filters · 6</span>{rows}</div>'
    lines = [('part-3009-lbg.png', 'Brick 1 × 6', 'Light Bluish Gray', '3009', 14), ('part-3010-dbg.png', 'Brick 1 × 4', 'Dark Bluish Gray', '3010', 9),
             ('part-87619-white.png', 'Slope 45° 2 × 2', 'White', '87619', 6)]
    lr = ''.join(f'<div style="display:flex;gap:12px;align-items:center;padding:8px 0;border-bottom:1px solid var(--tw-divider)"><div style="width:44px;flex:none">{pic(i, 44, 3)}</div>'
                 f'<div style="flex:1;min-width:0"><div style="font:500 14px var(--tw-font)">{n}</div><div style="font-size:12px;color:var(--tw-text-2)">{c} · <span class="mono">{num}</span></div></div>'
                 f'<span class="mono" style="font:600 13px var(--tw-mono)">{q} missing</span></div>' for i, n, c, num, q in lines)
    panel = (f'<div class="card" style="width:400px;flex:none;padding:16px;display:flex;flex-direction:column;gap:12px;align-self:flex-start">'
             f'<div class="lbl">Selected</div><div><span class="mono" style="font:600 18px var(--tw-mono)">21028-1</span> <span style="font:600 16px var(--tw-font)">New York City</span>'
             f'<div style="font-size:13px;color:var(--tw-text-2)">Skylines · 2016 · 598 parts</div></div>'
             f'<div class="lbl" style="color:var(--tw-text-2)">Parts you hold</div>{cover(412, 598, "412 of 598 · 186 missing in 23 lines")}'
             f'<div style="font-size:13px;color:var(--tw-text-2)">No figures in this set</div><div>{lr}<div style="font-size:13px;color:var(--tw-accent-text);padding-top:8px">+ 20 more lines · Show all</div></div>'
             f'<div class="mono" style="font-size:12.5px;color:var(--tw-text-2)">≈ €6.10 · 12 lines unpriced</div>'
             f'<span class="btn" style="height:52px">Build it · make a copy</span><div style="display:flex;gap:10px"><span class="btn sec sm" style="flex:1">Add to wishlist</span>'
             f'<span class="btn sec sm" style="flex:1">Missing parts · XML</span></div>'
             f'<p style="font-size:12.5px;color:var(--tw-text-muted)">Build it moves the 412 matching pieces out of loose stock into a new copy, as one step you can undo.</p></div>')
    return (f'<div style="padding:22px 32px 0;display:flex;flex-direction:column;gap:14px">{head}{filt}{summary}'
            f'<div style="display:flex;gap:24px"><div style="flex:1;min-width:0">{rows}</div>{panel}</div></div>')


# ---- Storage ---------------------------------------------------------------------------------------------------------
STORES = [('S-0001', 'Shelf A1 – Castle', 'Shelf', 2, 0, 0), ('S-0002', 'Shelf A2 – Town', 'Shelf', 3, 0, 0), ('S-0003', 'Parts drawer unit', 'Drawer unit', 0, 0, 6),
          ('S-0004', 'Display case', 'Shelf', 1, 0, 0), ('S-0005', 'Technic crate', 'Box', 1, 0, 0), ('S-0006', 'Bag 07', 'Bag', 0, 0, 0)]


def storage_body(phone):
    head = (f'<div class="head"><div><div class="lbl">Workbench · Storage</div><h1>Storage</h1><p>6 storages · 7 sets · 0 figures · 6 part lots</p></div>'
            + ('' if phone else f'<div style="margin-left:auto;display:flex;gap:10px"><span class="btn sec sm">Purchase locations</span><span class="btn sm">{ic("plus", 16)}Add storage</span></div>') + '</div>')
    th = ('<div style="display:grid;grid-template-columns:70px 1fr 48px 48px 64px;gap:8px;padding:8px 6px;border-bottom:1.5px solid var(--tw-rule)" class="lbl">'
          '<span>Code</span><span>Storage</span><span style="text-align:right">Sets</span><span style="text-align:right">Figs</span><span style="text-align:right">Lots</span></div>')
    rows = ''.join(f'<div style="display:grid;grid-template-columns:70px 1fr 48px 48px 64px;gap:8px;padding:9px 6px;border-bottom:1px solid var(--tw-divider);align-items:center;'
                   f'{"background:var(--tw-accent-soft);box-shadow:inset 3px 0 0 var(--tw-accent);" if sid == "S-0002" else ""}">'
                   f'<span class="mono" style="font-size:12px;color:var(--tw-text-muted)">{sid}</span><span><span style="font:600 14px var(--tw-font)">{n}</span>'
                   f'<span style="display:block;font-size:12px;color:var(--tw-text-2)">{k}</span></span>'
                   + ''.join(f'<span class="mono" style="text-align:right;font-size:13px">{v if v else "—"}</span>' for v in (s, f, l)) + '</div>' for sid, n, k, s, f, l in STORES)
    table = f'<div style="{"" if phone else "width:430px;flex:none"}">{th}{rows}<div class="row"><span class="chev" style="color:var(--tw-text)">{ic("chev")}</span><div class="t">History</div></div></div>'
    if phone:
        return f'<div style="padding:14px 16px 0;display:flex;flex-direction:column;gap:12px">{head.replace("font:600 30px", "font:600 26px")}<span class="btn sm" style="align-self:flex-start">{ic("plus", 16)}Add storage</span>{table}</div>'
    tiles = ''.join(tile(SETS[n], w=196, img_h=96) for n in ('7213-1', '7938-1', '10254-1'))
    detail = (f'<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:12px">{tape("S-0002", "Shelf A2 – Town", 3)}'
              f'<div style="display:flex;gap:10px;align-items:center;font-size:13px;color:var(--tw-text-2)">Shelf · 3 sets · 4 copies · 0 figures · 0 part lots'
              f'<span style="margin-left:auto;display:flex;gap:8px"><span class="btn sec sm">Print label</span><span class="btn sec sm">Edit</span></span></div>'
              f'<div style="display:flex;gap:12px">{tiles}</div>'
              f'<p style="font-size:13px;color:var(--tw-text-muted)">Move sets, figures or part lots here from their detail page, or from another storage in select mode.</p></div>')
    return f'<div style="padding:22px 32px 0;display:flex;flex-direction:column;gap:16px">{head}<div style="display:flex;gap:28px">{table}{detail}</div></div>'


def page3(body, w, h):
    """Round 3 and later frames: round 2's page plus EXTRA_CSS, so the approved round 2 files stay byte-identical."""
    return page(body, w, h).replace('</style>', EXTRA_CSS + '</style>', 1)


FRAMES = [('01-tools-and-admin', 'Manage', 'Tools & Admin', tools_body), ('02-settings', 'Manage', 'Tools & Admin', settings_body),
          ('03-find-instructions', 'Manage', 'Tools & Admin', finder_body),
          ('04-sets', 'Collection', 'Sets', sets_body), ('05-sets-without-storage', 'Collection', 'Sets', nostore_body),
          ('06-set-inspector', 'Workbench', 'Set Inspector', inspector_body), ('07-part-runner', 'Workbench', 'Part Runner', runner_body),
          ('08-sets-empty', 'Collection', 'Sets', empty_body),
          ('09-matchmaker', 'Workbench', 'Matchmaker', match_body), ('10-build-scout', 'Workbench', 'Build Scout', scout_body),
          ('11-storage', 'Workbench', 'Storage', storage_body)]
SIZES = ((False, 1440, 1000), (True, 390, 844))


def sources():
    """{path relative to design/screens-b: (html, w, h)} for every approved frame, plus the components sheet."""
    out = {}
    for folder, g, sub, fn in FRAMES:
        for phone, w, h in SIZES:
            make = page3 if folder >= '04' else page
            out[f'{folder}/light-{w}.html'] = (make((phone_shell if phone else desk_shell)(g, sub, fn(phone)), w, h), w, h)
    out['00-components/light-1440.html'] = (page(parts_body(), 1440, 520), 1440, 520)
    return out


def render(items):
    """{key: (html, w, h)} -> {key: PNG bytes}. Each HTML is written first, so its relative font paths resolve."""
    from playwright.sync_api import sync_playwright
    shots = {}
    with sync_playwright() as pw:
        exe = os.environ.get('BRAND_CHROMIUM')
        b = pw.chromium.launch(executable_path=exe) if exe else pw.chromium.launch()
        for key, (html, w, h) in items.items():
            path = OUT / key
            pg = b.new_page(viewport={'width': w, 'height': h}, device_scale_factor=2, color_scheme='light', reduced_motion='reduce')
            pg.goto(path.as_uri(), wait_until='load')
            pg.evaluate("Promise.all(document.fonts ? [...document.fonts].map(f => f.load()) : []).then(() => document.fonts.ready)")
            pg.wait_for_timeout(100)
            if pg.evaluate('document.documentElement.scrollWidth > innerWidth'):
                raise SystemExit(f'FRAMES: {key} runs past the right edge')
            shots[key] = pg.screenshot()
            pg.close()
        b.close()
    return shots


def same_pixels(a, b, tolerance=0.001):
    from PIL import Image, ImageChops
    ia, ib = (Image.open(io.BytesIO(x)).convert('RGBA') for x in (a, b))
    if ia.size != ib.size:
        return False
    diff = ImageChops.difference(ia, ib).convert('L').point(lambda v: 255 if v > 8 else 0)
    return diff.histogram()[255] / (ia.width * ia.height) <= tolerance


def main(cmd):
    items = sources()
    if cmd == 'build':
        for key, (html, w, h) in items.items():
            (OUT / key).parent.mkdir(parents=True, exist_ok=True)
            (OUT / key).write_text(html)
        for key, png in render(items).items():
            (OUT / key).with_suffix('.png').write_bytes(png)
        print(f'Built {len(items)} B′ frames in design/screens-b/')
        return 0
    bad = [k for k, (html, _, _) in items.items() if not (OUT / k).exists() or (OUT / k).read_text() != html]
    if not bad:
        for key, png in render(items).items():
            if not same_pixels((OUT / key).with_suffix('.png').read_bytes(), png):
                bad.append(key.replace('.html', '.png'))
    for k in bad:
        print('FRAMES: drift in', k)
    print('B′ frames OK' if not bad else f'{len(bad)} B′ frames drift from b_frames.py')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 'check'))
