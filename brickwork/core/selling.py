"""Sell this copy (#53): a fair asking price and the listing text for one copy, on the set detail.

The asking price is the copy's used sold average (new for a new or sealed copy; the quote the Prices card and Worth now use, `valuation._quotes`)
less what its missing parts and figures are worth, priced line by line (`deductions`: the used quote Complete sets prices a repair with). A line with
no usable quote is a "needs evidence" line, listed and left out of the sum. A damaged line is not deducted. The part-out value of what is present
(`partout`, shown only when 90 % of the lines have a price) is the floor: when the deductions would take the price under it, the floor is the price.
Nothing is stored and the copy's own estimate is ignored (it is the owner's worth, not the market's). Both cards use the same per-line
deductions, but Worth now honours the owner's own estimate and applies no part-out floor, so its worth can differ from the Sell card's asking price.

One function, `card`, works out the numbers, the words and the listing text, so the card and the text cannot disagree. A copy with no part check yet
(`deductions.checked`) shows the average, not adjusted, and the card says so. Money is the display currency, whole cents, from the same rates the
Value card uses: a missing rate is a state of its own, never a guess.
"""
from decimal import Decimal, ROUND_HALF_UP
import re
import sqlite3

from . import collection, deductions, items, partout, valuation
from . import currency as fx
from .retail import display_currency
from .sources.base import now
from ..web.formatting import money, part_name, short_age

CENT = Decimal('0.01')
TRADEMARK = re.compile(r'\bLEGO(?:[®™]|(?![A-Za-z]))\s*', re.IGNORECASE)             # the brand is not written in a listing (the kit's voice)
DASH_BEFORE_NUMBER = re.compile(r'(?<![\w])[-−–—]+\s*(?=\d)')           # `1592-1` and `fig-008732` have a word before the dash and stay
SHOWN_NAMES = 3                                                        # names in the coverage line before "and n more"


def _cents(amount):
    return amount.quantize(CENT, ROUND_HALF_UP)


def plain(text):
    """Listing words: no trademark word, no dash or minus in front of a number."""
    return DASH_BEFORE_NUMBER.sub('', TRADEMARK.sub('', str(text or ''))).strip()


def _count(db, copy_id):
    """`(pieces, missing pieces, figures, missing figures)` of the copy's live lines (spares and a figure's own parts are none)."""
    parts = db.execute("""SELECT coalesce(sum(quantity),0), coalesce(sum(missing),0) FROM copy_part
        WHERE copy_id=? AND is_spare=0 AND copy_figure_id IS NULL AND retired_at IS NULL""", (copy_id,)).fetchone()
    figures = db.execute('SELECT coalesce(sum(quantity),0), coalesce(sum(missing),0) FROM copy_figure WHERE copy_id=? AND retired_at IS NULL', (copy_id,)).fetchone()
    return parts[0], parts[1], figures[0], figures[1]


def _named(db, lines):
    """The lines with their name, number, colour (name, rgb, ink) and catalogue category."""
    names = collection._names(db, [l['item_id'] for l in lines])
    rows = collection.decorate(db, [dict(l, name=(names.get(l['item_id']) or {}).get('name')) for l in lines])
    for r in rows:
        r['category'] = ((names.get(r['item_id']) or {}).get('category_name') or '').strip() or 'Other parts'
        r['title'] = plain(part_name(r['name'] or r['number_text'] or 'Part'))
    return rows


def _name(line):
    """A line's name, colour first (a figure has none): `Black Brick 1 × 4`."""
    return ' '.join(([line['color_name']] if line['group'] == 'part' and line['color_name'] else []) + [line['title']])


def _label(line):
    """A line as the coverage line names it: its name, then the part number."""
    return _name(line) + (f" {line['item_no']}" if line['group'] == 'part' and line['item_no'] else '')


def _coverage(sums, lines):
    """The coverage line as `dict(priced, total, needs, names)`, or None when no line is missing."""
    if not sums['lines']:
        return None
    left = [l for l in lines if l['shown'] is None]
    shown = [_label(l) for l in left[:SHOWN_NAMES]]
    if len(left) > SHOWN_NAMES:
        shown.append(f'{len(left) - SHOWN_NAMES} more')
    return dict(priced=sums['priced'], total=sums['lines'], needs=len(left), names=', '.join(shown))


def _line_view(line, display):
    """A line of a deduction row: colour chip, name, number, its quote (None: needs evidence) and, for more than one piece, the count."""
    return dict(colour=line['color_name'], rgb=line['rgb'], ink=line['ink'], name=line['title'], number=line['item_no'] if line['group'] == 'part' else '',
                amount=None if line['shown'] is None else money(line['shown'], display, fixed=True), count=line['missing'] if line['missing'] > 1 else None)


def _pills(c, state, incomplete, checked, damaged):
    pills = []
    if c['condition'] in ('new', 'used'):
        pills.append(dict(text=c['condition'].capitalize(), tone=''))
    if c['completeness'] == 'sealed':
        pills.append(dict(text='Sealed', tone=''))
    elif not checked:
        pills.append(dict(text='Not checked', tone='unknown'))
    elif incomplete:
        pills.append(dict(text='Incomplete', tone='warning'))
    elif damaged:
        pills.append(dict(text=f'Complete, {damaged} damaged', tone='warning'))
    elif state == 'filled':
        pills.append(dict(text='Complete', tone='success'))
    return pills


def card(db, copy_id, stamp=None):
    """The Sell card of one live copy, as a dict for `sell_module.html`:

    `copy_id`, `label` (Set N), `state` (`filled`, `unchecked`, `no_quote` or `no_rate`), `pills`, `ask` (`title`, `text` None without a price, `age`, `stale`,
    `none` the words for no price), `basis` and `basis_note`, `note` (why the floor is the price), `rows` (the arithmetic: `kind` plain, deduction or sum,
    `label`, `count`, `noun`, `amount`, and for a deduction its `lines`), `floor` (`label`, `amount`, `known`; None when nothing is missing or the floor
    is the price), `coverage` (`priced`, `total`, `needs`, `names`), `copy_enabled` and `text` (the listing text). Raises ValueError for a copy that
    does not exist."""
    stamp = stamp or now()
    c = db.execute('SELECT c.*, i.year FROM copy c JOIN item i ON i.id=c.item_id WHERE c.id=? AND c.archived_at IS NULL', (copy_id,)).fetchone()
    if c is None:
        raise ValueError('Copy is unavailable')
    c = dict(c)
    c['condition_wanted'] = 'new' if c['condition'] == 'new' or c['completeness'] == 'sealed' else 'used'
    label = items.labels(db, {(c['item_id'], None)}).get((c['item_id'], None))
    number, name = (label.number if label else None) or str(c['item_id']), plain(part_name(label.name if label else ''))
    copy_label = collection.copy_labels(db, [copy_id]).get(copy_id) or 'Set'
    flags = {r[0] for r in db.execute("""SELECT f.name FROM copy_flag x JOIN flag f ON f.id=x.flag_id AND f.archived_at IS NULL AND f.kind='status'
        WHERE x.copy_id=?""", (copy_id,))}
    display, table = display_currency(db), collection.exchange_rates(db)
    wanted = c['condition_wanted']
    out = dict(copy_id=copy_id, label=copy_label, state='filled', pills=[], ask=dict(title='Asking price', text=None, age='', stale=False, none='no sales'), basis='', basis_note=None,
               note=None, rows=[], floor=None, coverage=None, copy_enabled=True, text='')
    quote = valuation._quotes(db, [c]).get((c['item_id'], wanted))
    average = None
    if quote is None:
        out['state'] = 'no_quote'
        out['basis'] = f"{valuation.SOURCE_WORDS[wanted]} · no sales in 6 months"
    else:
        average, reason = valuation._money(quote['amount'], quote['currency'], display, table)
        sold = quote.get('sold')
        out['basis'] = ' · '.join([valuation.SOURCE_WORDS[wanted], f'{sold} sold' if sold is not None else 'Sold count not recorded']
                                  + (['single price point'] if sold == 1 else ['6 months'] if quote['source'] == 'bricklink' else []))
        if reason:
            out['state'], average = 'no_rate', None
            out['ask']['none'] = 'needs a rate'
            out['basis_note'] = f"The price is in {quote['currency']} with no rate for {display} · add one in Settings"
        elif average['converted']:
            was = money(average['original']['amount'], average['original']['currency'], fixed=True)
            out['basis_note'] = f"{was} converted at the rate of {short_age(average['rate_as_of'])}"
        out['ask'].update(age=short_age((quote['observed_at'] or '')[:10]), stale=bool(quote['stale']))
    checked = c['id'] in deductions.checked(db, [c])
    total, short, figures, figures_short = _count(db, copy_id)
    raw = deductions.lines(db, [copy_id], stamp)[copy_id] if checked else dict(parts=[], figures=[])
    lines = _named(db, raw['parts'] + raw['figures'])
    damaged_lines = []
    if checked:
        damaged_lines.extend(dict(r, group='part') for r in db.execute('''SELECT item_id, color_id, sum(damaged) damaged FROM copy_part
            WHERE copy_id=? AND retired_at IS NULL AND is_spare=0 AND copy_figure_id IS NULL
            GROUP BY item_id, color_id HAVING sum(damaged)>0''', (copy_id,)))
        damaged_lines.extend(dict(r, group='figure') for r in db.execute('''SELECT f.item_id, NULL AS color_id, sum(min(f.quantity-f.missing, (SELECT max(p.damaged) FROM copy_part p
                WHERE p.copy_figure_id=f.id AND p.retired_at IS NULL AND p.is_spare=0))) damaged
            FROM copy_figure f
            WHERE f.copy_id=? AND f.retired_at IS NULL AND f.quantity>f.missing
            AND EXISTS (SELECT 1 FROM copy_part p WHERE p.copy_figure_id=f.id
                AND p.retired_at IS NULL AND p.is_spare=0 AND p.damaged>0)
            GROUP BY f.item_id''', (copy_id,)))
    damaged_lines = _named(db, damaged_lines)
    damaged = sum(l['damaged'] for l in damaged_lines)
    sums, asking, after = None, None, None
    if average is not None:
        average = average['amount']
        if not checked:
            out['state'] = 'unchecked'
            asking = average
            out['ask']['title'] = f'{valuation.SOURCE_WORDS[wanted].split()[0]} average · not adjusted'
        else:
            found = deductions.shown(raw, display, table)
            if found is None:
                out['state'], out['ask']['none'] = 'no_rate', 'needs a rate'
                out['basis_note'] = 'A missing part is priced in a currency with no rate · add one in Settings'
            else:
                sums = deductions.totals(found)
                lines = _named(db, found['parts'] + found['figures'])
                after = deductions.net(average, sums)
                asking = after
    if asking is not None:
        floor = None
        if sums and sums['lines']:
            made = partout.values(db, [copy_id]).get(copy_id)
            if made and made['value'] is not None:                  # a value only with enough priced lines
                converted = fx.convert(made['value'], made['currency'], display, table)
                floor = _cents(converted['amount']) if converted else None
                if converted is None:
                    out['state'], out['ask']['none'] = 'no_rate', 'needs a rate'
                    out['basis_note'] = f"The part-out value is in {made['currency']} with no rate for {display} · add one in Settings"
                    asking = None
            out['floor'] = dict(label='Part-out value of what is present', amount=None if floor is None else money(floor, display, fixed=True), known=floor is not None)
        if out['state'] == 'no_rate':
            out['floor'] = None
        if floor is not None and after < floor:
            out['floor'] = None
            if floor <= average:
                asking = floor
                out['note'] = f"Set to the part-out value: the deductions would take it to {money(after, display, fixed=True)}."
            else:                                                       # a gap never asks more than the complete copy
                asking = average
                out['note'] = (f"Held at the average: the deductions would take it to {money(after, display, fixed=True)}, "
                               f"below the part-out value of {money(floor, display, fixed=True)}, which is above the average.")
        out['ask']['text'] = money(asking, display, fixed=True) if asking is not None else None
    if average is not None:
        out['rows'].append(dict(kind='plain', label=f'{valuation.SOURCE_WORDS[wanted].split()[0]} average for this condition', amount=money(average, display, fixed=True)))
    if sums is not None:
        if not sums['lines']:
            out['rows'].append(dict(kind='plain', label='Nothing missing', amount=''))
        for kind, label_text, count, amount, group in (('parts', 'Missing parts', sums['pieces'], sums['parts'], [l for l in lines if l['group'] == 'part']),
                                                 ('figures', 'Missing figures', sums['figure_count'], sums['figures'], [l for l in lines if l['group'] == 'figure'])):
            if group:
                out['rows'].append(dict(kind='deduction', label=label_text, count=count, noun=('piece' if count == 1 else 'pieces') if kind == 'parts' else '',
                                        amount=f"less {money(amount, display, fixed=True)}" if any(l['shown'] is not None for l in group) else 'not priced',
                                        lines=[_line_view(l, display) for l in group]))
        if note := out['note']:
            out['rows'].append(dict(kind='plain', label='After deductions', amount=money(after, display, fixed=True)))
        if asking is not None:
            out['rows'].append(dict(kind='sum', label=('Asking price · part-out value' if asking == floor else 'Asking price · held at the average') if note else 'Asking price', amount=out['ask']['text']))
        out['coverage'] = _coverage(sums, lines)
    out['pills'] = _pills(c, out['state'], bool(checked and (short or figures_short)), checked, damaged)
    out['copy_enabled'] = out['state'] in ('filled', 'unchecked')
    out['text'] = listing(dict(number=number, name=name, year=c['year'], condition=c['condition'], completeness=c['completeness'], checked=checked,
                               total=total, short=short, figures=figures, figures_short=figures_short, lines=lines, damaged_lines=damaged_lines, damaged=damaged, flags=flags,
                               price=out['ask']['text'] if checked and out['state'] == 'filled' else None))
    return out


def listing(facts):
    """The listing text: plain text, one fact a line, the asking price last so the owner can delete it. Words only from the copy's own records;
    a fact the copy does not record is said as such, never guessed."""
    head = f"{facts['number']} {facts['name']}".strip() + (f" · {facts['year']}" if facts['year'] else '')
    sealed = facts['completeness'] == 'sealed'
    rows = [head, 'Condition: ' + {'new': 'new', 'used': 'used'}.get(facts['condition'], 'not stated') + (', sealed' if sealed else '')]
    pieces = facts['total']
    if not sealed:
        if not facts['checked']:
            rows.append('Completeness: not checked')
        elif not facts['short'] and not facts['figures_short']:
            rows.append((f'Completeness: complete, {pieces} pieces' if pieces else 'Completeness: complete') + (f", {facts['damaged']} damaged" if facts.get('damaged') else ''))
        elif not facts['short']:
            rows.append(f'Parts: complete, {pieces} of {pieces} pieces' if pieces else 'Parts: none recorded')
        else:
            percent = min(99, int((Decimal(pieces - facts['short']) * 100 / Decimal(pieces)).quantize(Decimal(1), ROUND_HALF_UP))) if pieces else None
            rows.append(f"Completeness: {f'{percent}% complete, ' if percent is not None else ''}{pieces - facts['short']} of {pieces} pieces")
    parts = [l for l in facts['lines'] if l['group'] == 'part']
    if parts:
        rows.append('Missing parts')
        grouped = {}
        for line in sorted(parts, key=lambda l: (l['category'], l['item_no'], l['color_name'] or '')):
            entry = (f"{line['missing']} " if line['missing'] > 1 else '') + _name(line) + (f" ({line['item_no']})" if line['item_no'] else '')
            grouped.setdefault(line['category'], []).append(entry)
        rows.extend(f"  {category}: {', '.join(entries)}" for category, entries in grouped.items())
    if facts['figures']:
        rows.append(f"Figures: {facts['figures'] - facts['figures_short']} of {facts['figures']} present")
        gone = [(f"{l['missing']} " if l['missing'] > 1 else '') + l['title'] for l in facts['lines'] if l['group'] == 'figure']
        if gone:
            rows.append('  Missing: ' + ', '.join(gone))
    if facts.get('damaged_lines'):
        rows.append('Damaged: ' + ', '.join(f"{l['damaged']} {_name(l)}" for l in facts['damaged_lines']))
    rows.append('Box: ' + ('yes' if any(collection._same_system_name('Box present', flag) for flag in facts['flags']) else 'no'))
    rows.append('Instructions: ' + ('yes' if any(collection._same_system_name('Instructions present', flag) for flag in facts['flags']) else 'no'))
    if facts['price']:
        rows.append('Asking price: ' + facts['price'])
    return '\n'.join(plain_line(r) for r in rows)


def plain_line(row):
    """One line of listing text with the dash-before-number rule applied, leaving the line's indent."""
    indent = row[:len(row) - len(row.lstrip())]
    return indent + DASH_BEFORE_NUMBER.sub('', row.strip())


def module(db, selected):
    """The card for a set detail's selected copy, or None for a loose item, a wish or a copy the card does not know. A failed read is an error state."""
    if not selected or selected.get('entity') != 'copy':
        return None
    try:
        return card(db, selected['id'])
    except ValueError:
        return None
    except sqlite3.Error:
        return dict(state='error', label=selected.get('label') or 'Set')
