"""#57 Value and gain on the pages: the Value module on a set's detail, the Paid vs value section on Statistics and the insurance report.

The figures are `core.valuation`'s (read its docstrings); this module turns them into the words, money and bar widths the templates print, so a
template never does arithmetic. Everything is rendered on the server: there is no separate fetch, so the frames' loading state cannot occur; the
error state is the page's own answer when the read fails, with Retry as a link that reloads the page."""
from decimal import Decimal
import sqlite3

from flask import Response, current_app, render_template, request, url_for
from flask_login import login_required

from ..core import valuation
from .formatting import money, plural, short_age, short_date
from .safe_errors import public
from .views import web_page

PAGE_SIZE = 15                                                         # the shared pager's page (12h)
SHOWN_PHOTOS = 4                                                       # photos in a row's strip; the rest read "n more"
BAR_SCALE = 72                                                         # the longest bar of a list, in percent of its track: the figure sits after the bar
CSV_NAME = 'brickwork-insurance-report.csv'


def amount(m):
    """A money body (`valuation`) as shown: currency first, unspaced, two places."""
    return money(m['amount'], m['currency'], fixed=True)


def text(value, currency):
    """A money string of `paid_vs_value` / `report` as shown."""
    return money(value, currency, fixed=True)


def gain_line(amount_value, percent, currency):
    """`("Gain" | "Loss", "€37.00 · 154%")` for a signed amount (negative = loss): words, no sign, no percent when the price paid rounds to 0.00."""
    value = Decimal(str(amount_value))
    figure = money(abs(value), currency, fixed=True)
    if percent is not None:
        figure += f' · {abs(int(percent))}%'
    return ('Loss' if value < 0 else 'Gain'), figure


# ---- A. the Value module on a set's detail --------------------------------------------------------------------------------------------------------------

def module(r, label):
    """The Value module's view of one `valuation.copies` row: `paid` and `worth` (each `state` value / none / no_rate / no_quote, its `text` and its `mark`),
    `gain` (`word`, `figure`) or None, `source` (the line under the rows, `stale` when the quote is old) and `notes` (a converted figure's rate)."""
    out = dict(label=label)
    if r['paid']:
        out['paid'] = dict(state='value', text=amount(r['paid']), mark=short_date(r['purchase_date']) if r['purchase_date'] else '')
    else:
        out['paid'] = dict(state='no_rate' if r['paid_reason'] == 'no_rate' else 'none', text='', mark='')
    wanted = 'New' if r['condition'] == 'new' or r['completeness'] == 'sealed' else 'Used'
    if r['worth']:
        out['worth'] = dict(state='value', text=amount(r['worth']), mark='your value' if r['worth_source'] == 'override' else short_age(r['worth_date']))
    else:
        out['worth'] = dict(state='no_rate' if r['worth_reason'] == 'no_rate' else 'no_quote', text='', mark='')
    out['gain'] = None
    if r['gain']:
        word, figure = gain_line(r['gain']['amount'], r['gain']['percent'], r['gain']['currency'])
        out['gain'] = dict(word=word, figure=figure)
    parts, stale = [], False
    if r['worth_source'] == 'override':
        parts = ['Your value']
    elif r['worth_source'] and r['worth_reason'] != 'no_quote':
        parts = [valuation.SOURCE_WORDS[r['worth_source']]]
        if r['worth_sales'] is not None:
            parts.append(plural(r['worth_sales'], 'sale'))
        if r['worth_date']:
            parts.append(short_age(r['worth_date']))
        if r['worth_discount_pct']:
            parts.append(f"incomplete, {r['worth_discount_pct']}% off")
        stale = bool(r['worth_stale'])
    elif r['worth_reason'] == 'no_quote':
        parts = [wanted, 'no sales']
    out['source'] = dict(text=' · '.join(parts), stale=stale)
    notes = []
    for word, key in (('Paid', 'paid'), ('Worth', 'worth')):
        m = r[key]
        if m and m['converted']:
            was = money(m['original']['amount'], m['original']['currency'], fixed=True)
            notes.append(f"{word} {was}, shown as {amount(m)} at the rate of {short_age(m['rate_as_of'])}")
    if r['paid_reason'] == 'no_rate' and r['paid_original']:
        notes.append(f"Paid {money(r['paid_original']['amount'], r['paid_original']['currency'], fixed=True)} · no rate for {r['paid_original']['currency']}, add one in Settings")
    if r['worth_reason'] == 'no_rate':
        notes.append('The value is in a currency with no rate · add one in Settings')
    out['notes'] = notes
    return out


def detail_module(db, selected):
    """The module for a set detail's selected copy, or None for a loose item, a wish or a copy the valuation does not know. A failed read is an error state."""
    if not selected or selected.get('entity') != 'copy':
        return None
    try:
        rows = valuation.copies(db, [selected['id']])
    except (sqlite3.Error, ValueError):
        return dict(error=True, label=selected.get('label') or 'Set')
    row = next((r for r in rows if str(r['id']) == str(selected['id'])), None)
    return module(row, selected.get('label') or 'Set') if row else None


# ---- B. Paid vs value on Statistics --------------------------------------------------------------------------------------------------------------------

def _bars(groups, currency, key='worth'):
    """The rows of a bar list: paid (outline) and worth (solid) on one scale per list, both from zero, the gain written at the end of the row."""
    top = max([Decimal(g['paid']) for g in groups if 'paid' in g] + [Decimal(g['worth']) for g in groups], default=Decimal(0))
    rows = []
    for g in groups:
        worth = Decimal(g['worth'])
        row = dict(label=g['label'], worth=text(g['worth'], currency), worth_width=float(worth / top * BAR_SCALE) if top else 0, paid=None, gain=None)
        if 'paid' in g:
            row['paid'] = text(g['paid'], currency)
            row['paid_width'] = float(Decimal(g['paid']) / top * BAR_SCALE) if top else 0
            word, figure = gain_line(g['gain'], g['percent'], currency)
            row['gain'] = f'{word} {figure}'
        rows.append(row)
    return rows


def paid_vs_value(db):
    """The Statistics section as a dict for `_bw_paid_vs_value.html`, or None when there is nothing to show (no copy) or the read failed (`error`).

    `state`: `filled`, `few` (under three comparable copies), `no_price` (no copy has a price paid, worth only) or `no_quotes` (no copy has a quote)."""
    try:
        rows = valuation.copies(db)
        stats = valuation.paid_vs_value(db, rows)
    except (sqlite3.Error, ValueError):
        return dict(state='error')
    if not rows:
        return None
    cur, n = stats['currency'], stats['copies']
    out = dict(currency=cur, copies=n, comparable=stats['comparable_copies'], unpaid=stats['without_price_paid'], insurance_url=url_for('web.bw_insurance_report'),
               rates=url_for('web.bw_admin', page='settings'), notes=[], paid=None, worth=None, gain=None, title='', sub='', themes=[], years=[], foot='', state='filled')
    if stats['without_rate']:
        out['notes'].append(f"{plural(stats['without_rate'], 'copy', 'copies')} {'needs' if stats['without_rate'] == 1 else 'need'} a rate · left out of the totals")
    if stats['converted']:
        paid_in = {}
        for r in rows:
            if r['paid'] and r['paid']['converted']:
                paid_in[r['paid']['original']['currency']] = paid_in.get(r['paid']['original']['currency'], 0) + 1
        note = f"Converted to {cur} at the rates of {short_age(stats['rates_as_of'])}"
        if paid_in:
            parts = sorted(paid_in.items())
            note += ' · ' + ', '.join((f'{plural(count, "copy", "copies")} paid in {name}' if i == 0 else f'{count} in {name}') for i, (name, count) in enumerate(parts))
        out['notes'].insert(0, note)
    if stats['without_quote'] == n:
        out['state'] = 'no_quotes'
        out['title'] = f'No worth yet for {n} {"copy" if n == 1 else "copies"}'
        out['sub'] = 'No sold prices are stored, so gain is hidden'
        paid_all = sum((r['paid']['amount'] for r in rows if r['paid']), Decimal(0))
        out['paid'] = text(paid_all, cur) if any(r['paid'] for r in rows) else None
        out['update_url'] = url_for('web.bw_admin', page='refresh')
        return out
    worth_only = [r for r in rows if r['worth'] is not None and r['paid_reason'] == 'no_price_paid']
    if stats['without_price_paid'] == n and worth_only:
        out['state'] = 'no_price'
        total = sum((r['worth']['amount'] for r in worth_only), Decimal(0))
        out['worth'] = text(total, cur)
        out['title'] = f'Worth {out["worth"]} across {n} {"copy" if n == 1 else "copies"}'
        out['sub'] = 'No copy has a price paid, so there is no gain · used and new sold averages'
        by_theme = {}
        for r in worth_only:
            by_theme[r['theme'] or valuation.NOT_RECORDED] = by_theme.get(r['theme'] or valuation.NOT_RECORDED, Decimal(0)) + r['worth']['amount']
        groups = [dict(label=k, worth=format(v, 'f')) for k, v in sorted(by_theme.items(), key=lambda kv: (-kv[1], kv[0]))]
        out['themes'] = _bars(groups, cur)
        out['foot'] = "Add a price paid in a copy's Edit sheet to compare."
        return out
    if not stats['enough']:
        out['state'] = 'few'
        out['few'] = f"Paid against value needs {valuation.MIN_COMPARABLE} copies with a price paid and a quote. You have {stats['comparable_copies']}."
        return out
    out['paid'], out['worth'] = text(stats['paid'], cur), text(stats['worth'], cur)
    word, figure = gain_line(stats['gain'], stats['percent'], cur)
    out['gain'], out['gain_word'], out['gain_figure'] = f'{word} {figure}', word, figure
    out['title'] = f'Worth {out["worth"]} against {out["paid"]} paid'
    out['sub'] = f'{out["gain"]} · used and new sold averages'
    out['themes'] = _bars(stats['by_theme'], cur)
    out['years'] = _bars(stats['by_year'], cur)
    if 0 < stats['without_quote'] < n:
        out['notes'].append(f"{plural(stats['without_quote'], 'copy', 'copies')} {'has' if stats['without_quote'] == 1 else 'have'} no sales · left out of the totals")
    out['foot'] = f"Gain compares the {stats['comparable_copies']} copies with a price paid · amounts in {cur}"
    return out


# ---- C. the insurance report ----------------------------------------------------------------------------------------------------------------------------

def _row(r):
    """One report row as shown (the screen and the print table share it)."""
    paid, worth = r['paid'], r['worth']
    if paid:
        paid_cell = dict(state='value', text=text(paid['amount'], paid['currency']),
                         small=f"paid {money(paid['original']['amount'], paid['original']['currency'], fixed=True)}" if paid['converted'] else '')
    else:
        paid_cell = dict(state='no_rate' if r['paid_reason'] == 'no_rate' else 'none', text='', small='')
    if worth:
        source = 'Your value' if r['worth_source'] == 'override' else valuation.SOURCE_WORDS.get(r['worth_source'], '')
        worth_cell = dict(state='value', text=text(worth['amount'], worth['currency']), mark='' if r['worth_source'] == 'override' else short_age(r['worth_date']),
                          source=source, stale=bool(r['worth_stale']),
                          small=f"{money(worth['original']['amount'], worth['original']['currency'], fixed=True)} converted" if worth['converted'] else '')
    else:
        worth_cell = dict(state='no_rate' if r['worth_reason'] == 'no_rate' else 'no_quote', text='', mark='', source='', stale=False, small='')
    urls = [url_for('web.bw_image', image_id=p) for p in r['photo_ids']]
    return dict(number=r['number'], name=r['name'] or '—', year=r['year'] if r['year'] is not None else '—', condition=(r['condition'] or '').capitalize() or '—',
                completeness=(r['completeness'] or '').capitalize() or '—', purchased=short_date(r['purchase_date']) if r['purchase_date'] else '—',
                paid=paid_cell, worth=worth_cell, photos=urls[:SHOWN_PHOTOS], more=max(0, len(urls) - SHOWN_PHOTOS))


def _header(data, rows):
    h = data['header']
    n, c, wp = h['copies'], h['comparable_copies'], h['without_price_paid']
    rate = h['without_rate']                                           # a figure that needs a missing rate: in no total, whichever side it is on
    unworthy = sum(1 for r in data['rows'] if r['paid'] and not r['worth'] and r['worth_reason'] != 'no_rate')
    foot = f'Totals count the {plural(c, "copy", "copies")} with a price paid'
    if unworthy or rate:
        foot += ' and a worth'
    if wp:
        foot += f' · {plural(wp, "copy", "copies")} {"has" if wp == 1 else "have"} no price paid and {"is" if wp == 1 else "are"} listed without one'
    if unworthy:
        foot += f' · {plural(unworthy, "copy", "copies")} {"has" if unworthy == 1 else "have"} no worth and {"is" if unworthy == 1 else "are"} listed without one'
    if rate:
        foot += f' · {plural(rate, "copy", "copies")} {"needs" if rate == 1 else "need"} a rate and {"is" if rate == 1 else "are"} listed without a total'
    return dict(generated=short_date(h['generated']), copies=n, copies_word=plural(n, 'copy', 'copies'),
                paid=text(h['paid'], h['currency']) if h['paid'] is not None else '—', worth=text(h['worth'], h['currency']) if h['worth'] is not None else '—',
                foot=foot, comparable=c)


def _page_items(page, pages):
    """Page numbers as the shared pager shows them: first, last and the current page with its neighbours; a single skipped page shows as its number."""
    wanted = sorted({n for n in (1, page - 1, page, page + 1, pages) if 1 <= n <= pages})
    items = []
    for i, n in enumerate(wanted):
        if i:
            gap = n - wanted[i - 1]
            if gap == 2:
                items.append(n - 1)
            elif gap > 2:
                items.append(None)
        items.append(n)
    return items


def _report():
    from ..core.admin import database
    from .admin_ops import brickwork_path
    with database(brickwork_path(), read_only=True) as db:
        return valuation.report(db)


@web_page.get('/manage/insurance-report')
@login_required
def bw_insurance_report():
    """The insurance report: the screen (15 rows a page, the shared pager) or, with `?print=1`, the print view with every copy."""
    printing = request.args.get('print') == '1'
    error, data, header, rows, pager = None, None, None, [], None
    try:
        data = _report()
        header, rows = _header(data, data['rows']), [_row(r) for r in data['rows']]
    except (sqlite3.Error, OSError, ValueError) as exc:
        error = public(exc, 'Brick Work database is not available · try again')
    page = 1
    if not printing and rows:
        pages = max(1, -(-len(rows) // PAGE_SIZE))
        try:
            page = min(max(1, int(request.args.get('page', 1))), pages)
        except ValueError:
            page = 1
        first = (page - 1) * PAGE_SIZE
        pager = dict(page=page, pages=pages, first=first + 1, last=min(len(rows), first + PAGE_SIZE), total=len(rows),
                     items=[dict(n=n, url=url_for('web.bw_insurance_report', **({'page': n} if n > 1 else {})) if n else None) for n in _page_items(page, pages)],
                     prev=url_for('web.bw_insurance_report', **({'page': page - 1} if page > 2 else {})) if page > 1 else None,
                     next=url_for('web.bw_insurance_report', page=page + 1) if page < pages else None)
        shown = rows[first:first + PAGE_SIZE]
    else:
        shown = rows
    template = 'web/toni/web/bw_insurance_print.html' if printing else 'web/toni/web/bw_insurance_report.html'
    response = current_app.make_response(render_template(template, title='Insurance report', error=error, header=header, rows=shown, pager=pager,
        total=len(rows), print_url=url_for('web.bw_insurance_report', print=1), csv_url=url_for('web.bw_insurance_csv'),
        back_url=url_for('web.bw_admin', page='statistics'), add_url=url_for('web.bw_add')))
    response.headers['Cache-Control'] = 'no-store'
    return response


@web_page.get('/manage/insurance-report.csv')
@login_required
def bw_insurance_csv():
    """The report's CSV: every copy (the API's `GET /export/insurance.csv`, the same file name)."""
    from ..core.admin import database
    from .admin_ops import brickwork_path
    try:
        with database(brickwork_path(), read_only=True) as db:
            body = valuation.report_csv(db)
    except (sqlite3.Error, OSError, ValueError) as exc:
        return current_app.response_class(public(exc, 'Could not build the report · try again'), status=400, mimetype='text/plain')
    response = Response(body, mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename={CSV_NAME}'})
    response.headers['Cache-Control'] = 'no-store'
    return response
