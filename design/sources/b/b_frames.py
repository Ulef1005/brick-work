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


FRAMES = [('01-tools-and-admin', 'Manage', 'Tools & Admin', tools_body), ('02-settings', 'Manage', 'Tools & Admin', settings_body),
          ('03-find-instructions', 'Manage', 'Tools & Admin', finder_body)]
SIZES = ((False, 1440, 1000), (True, 390, 844))


def sources():
    """{path relative to design/screens-b: (html, w, h)} for every approved frame, plus the components sheet."""
    out = {}
    for folder, g, sub, fn in FRAMES:
        for phone, w, h in SIZES:
            out[f'{folder}/light-{w}.html'] = (page((phone_shell if phone else desk_shell)(g, sub, fn(phone)), w, h), w, h)
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
