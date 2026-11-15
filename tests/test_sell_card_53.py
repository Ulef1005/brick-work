"""Sell this copy (#53): `core/selling.py` (the asking price, the listing text), `core/deductions.py` (what missing lines take off) and the Worth now change
in `core/valuation.py`, then the card on the set detail. Invented data on the rich fixture catalogue.

Set `1000-1` "Syn Castle Keep" (1990): 3001 red x4, 3023 white x2, a spare, and the figure fig-000004 (twice). Quotes are made fresh (now, region eu) because
Complete sets' rule wants a week-old quote at most."""
from decimal import Decimal
import re
import subprocess
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from brickwork.core import collection, deductions, selling, valuation
from brickwork.core.sources.base import now
from tests import rendered
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401  (the fixtures)

ROOT = Path(__file__).resolve().parents[1]
FRESH = now().isoformat()
NUMBER_AFTER_DASH = re.compile(r'(?<![\w])[-−–—]\s*[€$£]?\d')


def setup(coll, average='58.00', brick='0.35', plate='0.10', figure='5.30', new=None):
    """The set's used average and the used quotes of its parts and figure (a value of None leaves that line unpriced)."""
    coll.setting('bricklink_region', 'eu')
    coll.setting('bricklink_currency', 'EUR')
    keep = coll.item('sets', '1000-1')
    if average:
        coll.price(keep, average, condition='used', sold=14, observed=FRESH, region='eu')
    if new:
        coll.price(keep, new, condition='new', sold=1, observed=FRESH, region='eu')
    for item, colour, value in ((coll.item('parts', '3001'), coll.colour('4'), brick), (coll.item('parts', '3023'), coll.colour('15'), plate),
                                (coll.item('minifigs', 'fig-000004'), None, figure)):
        if value:
            coll.price(item, value, colour=colour, condition='used', region='eu', observed=FRESH)


def checked_copy(coll, brick=2, plate=1, figure=1, **fields):
    """A used, incomplete copy with the part check done: 3001 red `brick` missing, 3023 white `plate` missing, the figure `figure` missing."""
    copy = coll.add_copy('1000-1', condition=fields.pop('condition', 'used'), completeness=fields.pop('completeness', 'incomplete'), **fields)
    if brick:
        coll.mark(copy, '3001', '4', missing=brick)
    if plate:
        coll.mark(copy, '3023', '15', missing=plate)
    if figure:
        coll.mark_figure(copy, 'fig-000004', missing=figure)
    coll.tag('copy', copy, coll.flag('Set is checked', 'status'))
    return copy


def card(coll, copy):
    return selling.card(coll.db, copy)


def row(v, label):
    return next(r for r in v['rows'] if r['label'].startswith(label))


# ---- the arithmetic ----

def test_the_asking_price_is_the_used_average_less_the_priced_missing_lines(coll):
    setup(coll)
    v = card(coll, checked_copy(coll))
    assert v['state'] == 'filled' and v['ask']['text'] == '€51.90' and v['ask']['title'] == 'Asking price'
    assert [(r['kind'], r['label'], r['amount']) for r in v['rows']] == [
        ('plain', 'Used average for this condition', '€58.00'), ('deduction', 'Missing parts', 'less €0.80'),
        ('deduction', 'Missing figures', 'less €5.30'), ('sum', 'Asking price', '€51.90')]
    parts = row(v, 'Missing parts')
    assert (parts['count'], parts['noun']) == (3, 'pieces') and [(l['colour'], l['amount'], l['count']) for l in parts['lines']] == [('Red', '€0.70', 2), ('White', '€0.10', None)]
    assert (row(v, 'Missing figures')['count'], v['basis']) == (1, 'Used sold average · 14 sold · 6 months')
    assert v['coverage'] == dict(priced=3, total=3, needs=0, names='') and v['floor']['amount'] == '€6.10' and v['note'] is None
    assert [p['text'] for p in v['pills']] == ['Used', 'Incomplete']


def test_a_line_with_no_quote_needs_evidence_and_stays_out_of_the_sum(coll):
    setup(coll, plate=None)
    v = card(coll, checked_copy(coll))
    assert v['ask']['text'] == '€52.00' and row(v, 'Missing parts')['amount'] == 'less €0.70'
    assert [l['amount'] for l in row(v, 'Missing parts')['lines']] == ['€0.70', None]
    assert v['coverage'] == dict(priced=2, total=3, needs=1, names='White ' + next(l for l in row(v, 'Missing parts')['lines'] if l['amount'] is None)['name'] + ' 3023')
    assert v['floor'] == dict(label='Part-out value of what is present', amount=None, known=False)    # 2 of 3 lines priced: under 90 %


def test_a_stale_quote_is_no_evidence(coll):
    setup(coll, plate=None)
    coll.price(coll.item('parts', '3023'), '0.10', colour=coll.colour('15'), condition='used', region='eu', observed='2026-01-01T00:00:00.000Z')
    v = card(coll, checked_copy(coll))
    assert v['coverage']['needs'] == 1 and v['ask']['text'] == '€52.00'


def test_a_set_with_only_unpriced_missing_lines_takes_nothing_off(coll):
    setup(coll, brick=None, plate=None, figure=None)
    v = card(coll, checked_copy(coll))
    assert v['ask']['text'] == '€58.00' and row(v, 'Missing parts')['amount'] == 'not priced' and v['coverage']['needs'] == 3


def test_the_part_out_value_is_the_floor(coll):
    setup(coll, average='4.00')
    v = card(coll, checked_copy(coll))
    assert v['ask']['text'] == '€6.10' and v['floor'] is None
    assert v['note'] == 'Set to the part-out value: the deductions would take it to €0.00.'
    assert [(r['label'], r['amount']) for r in v['rows'][-2:]] == [('After deductions', '€0.00'), ('Asking price · part-out value', '€6.10')]
    setup_text = v['text']
    assert setup_text.splitlines()[-1] == 'Asking price: €6.10'


def test_a_copy_with_nothing_missing_asks_the_average(coll):
    setup(coll)
    v = card(coll, checked_copy(coll, brick=0, plate=0, figure=0, completeness='complete'))
    assert v['ask']['text'] == '€58.00' and [r['label'] for r in v['rows']] == ['Used average for this condition', 'Nothing missing', 'Asking price']
    assert v['coverage'] is None and v['floor'] is None and [p['text'] for p in v['pills']] == ['Used', 'Complete']


def test_a_new_or_sealed_copy_is_based_on_the_new_average(coll):
    setup(coll, new='214.00')
    sealed = coll.add_copy('1000-1', condition='new', completeness='sealed')
    v = card(coll, sealed)
    assert v['ask']['text'] == '€214.00' and v['basis'] == 'New sold average · 1 sold · single price point' and v['state'] == 'filled'
    assert [r['label'] for r in v['rows']] == ['New average for this condition', 'Nothing missing', 'Asking price'] and [p['text'] for p in v['pills']] == ['New', 'Sealed']
    new = checked_copy(coll, brick=1, plate=0, figure=0, condition='new', completeness='incomplete')
    assert card(coll, new)['ask']['text'] == '€213.65'


def test_no_used_quote_means_no_price_and_no_copy_button(coll):
    setup(coll, average=None)
    v = card(coll, checked_copy(coll))
    assert (v['state'], v['ask']['text'], v['ask']['none'], v['copy_enabled'], v['rows']) == ('no_quote', None, 'no sales', False, [])
    assert 'Asking price' not in v['text']


def test_a_copy_with_no_part_check_shows_the_average_not_adjusted(coll):
    setup(coll)
    copy = coll.add_copy('1000-1', condition='used', completeness='incomplete')
    coll.mark(copy, '3001', '4', missing=2)
    v = card(coll, copy)
    assert (v['state'], v['ask']['text'], v['ask']['title'], v['copy_enabled']) == ('unchecked', '€58.00', 'Used average · not adjusted', True)
    assert [r['kind'] for r in v['rows']] == ['plain'] and v['coverage'] is None and [p['text'] for p in v['pills']] == ['Used', 'Not checked']
    assert 'Completeness: not checked' in v['text'] and 'Missing parts' not in v['text'] and 'Asking price' not in v['text']


def test_the_card_ignores_the_copys_own_estimate(coll):
    setup(coll)
    v = card(coll, checked_copy(coll, current_value='142.00', current_value_currency='EUR'))
    assert v['ask']['text'] == '€51.90'


def test_a_missing_rate_gives_no_price(coll):
    setup(coll)
    coll.sql("UPDATE price_observation SET currency='USD' WHERE guide='sold' AND item_id=?", (coll.item('sets', '1000-1'),))
    v = card(coll, checked_copy(coll))
    assert (v['state'], v['ask']['text'], v['ask']['none'], v['copy_enabled']) == ('no_rate', None, 'needs a rate', False)


def test_a_damaged_line_is_not_deducted(coll):
    setup(coll)
    copy = checked_copy(coll, brick=0, plate=0, figure=0, completeness='complete')
    coll.mark(copy, '3001', '4', damaged=2)
    assert card(coll, copy)['ask']['text'] == '€58.00'


# ---- Worth now ----

def worth(coll, copy):
    return next(r for r in valuation.copies(coll.db) if r['id'] == copy)


def test_worth_now_of_a_checked_copy_is_the_cards_price(coll):
    setup(coll)
    copy = checked_copy(coll)
    r = worth(coll, copy)
    assert str(r['worth']['amount']) == card(coll, copy)['ask']['text'][1:] == '51.90' and r['worth_discount_pct'] is None
    assert '_deduction' not in valuation.valuation(coll.db)['copies'][0] and all(not k.startswith('_') for k in valuation.report(coll.db)['rows'][0])


def test_worth_now_of_an_unchecked_copy_keeps_the_flat_discount(coll):
    setup(coll)
    coll.setting('incomplete_discount_pct', '25')
    copy = coll.add_copy('1000-1', condition='used', completeness='incomplete')
    coll.mark(copy, '3001', '4', missing=2)
    r = worth(coll, copy)
    assert str(r['worth']['amount']) == '43.50' and r['worth_discount_pct'] == 25


def test_the_copys_own_estimate_still_wins_worth_now(coll):
    setup(coll)
    r = worth(coll, checked_copy(coll, current_value='142.00', current_value_currency='EUR'))
    assert (str(r['worth']['amount']), r['worth_source']) == ('142.00', 'override')


def test_a_checked_copy_with_nothing_missing_is_not_discounted_for_a_damaged_line(coll):
    setup(coll)
    copy = checked_copy(coll, brick=0, plate=0, figure=0, completeness='complete')
    coll.mark(copy, '3001', '4', damaged=1)
    r = worth(coll, copy)
    assert str(r['worth']['amount']) == '58.00' and r['worth_discount_pct'] is None


def test_the_value_card_says_what_was_taken_off_and_what_was_not_priced(coll, client):
    setup(coll, plate=None)
    copy = checked_copy(coll)
    page = BeautifulSoup(client.get(f"/collection/item/{coll.item('sets', '1000-1')}?copy={copy}").data, 'html.parser')
    text = re.sub(r'\s+', ' ', page.select_one('[data-module=value]').get_text(' ', strip=True))
    assert 'Worth now €52.00' in text and 'missing parts and figures less €6.00' in text and '1 missing line without a price, not taken off' in text


# ---- the listing text ----

def test_the_listing_text_says_what_the_copy_is_and_lacks(coll):
    setup(coll)
    copy = checked_copy(coll)
    coll.tag('copy', copy, coll.flag('Instructions present', 'status'))
    text = card(coll, copy)['text']
    lines = text.splitlines()
    assert lines[0] == '1000-1 Syn Castle Keep · 1990' and lines[1] == 'Condition: used'
    assert re.fullmatch(r'Completeness: \d\d% complete, \d+ of \d+ pieces', lines[2])
    assert 'Missing parts' in lines and any(l.startswith('  ') and '2 Red ' in l and '(3001)' in l for l in lines) and any('White' in l and '(3023)' in l for l in lines)
    assert 'Figures: 1 of 2 present' in lines and lines[lines.index('Figures: 1 of 2 present') + 1].startswith('  Missing: ')
    assert lines[-3:] == ['Box: no', 'Instructions: yes', 'Asking price: €51.90']


def test_the_text_never_says_complete_for_100_percent_when_a_piece_is_missing(coll):
    setup(coll)
    copy = checked_copy(coll, brick=1, plate=0, figure=0)
    assert 'Completeness: 83% complete, 5 of 6 pieces' in card(coll, copy)['text']
    big = selling.listing(dict(number='1', name='X', year=None, condition='used', completeness='incomplete', checked=True, total=1000, short=1, figures=0, figures_short=0,
                               lines=[], flags=set(), price=None))
    assert 'Completeness: 99% complete, 999 of 1000 pieces' in big


def test_condition_wording_and_sealed(coll):
    setup(coll, new='214.00')
    assert 'Condition: new, sealed' in card(coll, coll.add_copy('1000-1', condition='new', completeness='sealed'))['text']
    assert 'Condition: new\n' in card(coll, checked_copy(coll, condition='new', brick=0, plate=0, figure=0, completeness='complete'))['text']
    assert 'Condition: not stated' in card(coll, coll.add_copy('1000-1'))['text']


def test_the_text_has_no_trademark_word_and_no_dash_before_a_number():
    assert selling.plain('LEGO® Castle - 12 Keep') == 'Castle 12 Keep' and selling.plain('LEGO Technic') == 'Technic' and selling.plain('Legoland') == 'Legoland'
    assert selling.plain('1592-1 fig-008732 Brick - 3') == '1592-1 fig-008732 Brick 3'
    text = selling.listing(dict(number='1592-1', name=selling.plain('LEGO® Town Square - Castle Scene'), year=1980, condition='used', completeness='incomplete', checked=True,
                                total=484, short=5, figures=0, figures_short=0, lines=[], flags=set(), price='€48.60'))
    assert 'LEGO' not in text and not NUMBER_AFTER_DASH.search(text) and text.startswith('1592-1 Town Square - Castle Scene · 1980')


def test_every_number_in_the_card_has_no_dash_in_front(coll):
    setup(coll)
    v = card(coll, checked_copy(coll))
    shown = ' '.join([v['ask']['text'], v['basis']] + [f"{r['label']} {r['amount']}" for r in v['rows']] + [v['text']])
    assert not NUMBER_AFTER_DASH.search(shown)


# ---- the card on the page ----

def sell_node(client, coll, copy):
    response = client.get(f"/collection/item/{coll.item('sets', '1000-1')}?copy={copy}")
    assert response.status_code == 200
    page = BeautifulSoup(response.data, 'html.parser')
    return page, page.select_one('[data-module=sell]')


def test_the_card_sits_between_prices_and_value_with_the_arithmetic_and_the_preview(coll, client):
    setup(coll, plate=None)
    copy = checked_copy(coll)
    page, node = sell_node(client, coll, copy)
    modules = [m['data-module'] for m in page.select('aside [data-module]')]
    assert modules.index('sell') == modules.index('prices') + 1 and modules.index('value') == modules.index('sell') + 1
    text = re.sub(r'\s+', ' ', node.get_text(' ', strip=True))
    assert text.startswith('Sell this copy · Set 1 Preview Used Incomplete Asking price €52.00')
    assert 'Used sold average · 14 sold · 6 months' in text and 'Missing parts · 3 pieces less €0.70' in text and 'Missing figures · 1 less €5.30' in text
    assert 'Priced 2 of 3 missing lines · 1 needs evidence: White' in text and ', not counted' in text and 'needs evidence' in text
    assert node.select('.bc-sell-unpriced') and len(node.select('details.bc-sell-dis')) == 2 and not node.select('details[open]')
    sheet = node.select_one('dialog#bc-sell-preview.bc-sheet')
    assert sheet and node.select_one('[data-bw-open=bc-sell-preview]') and sheet.select_one('textarea').get_text().startswith('1000-1 Syn Castle Keep')
    outline = node.select_one('button.bc-sell-copy')
    assert 'bc-outline' in outline['class'] and 'primary' not in outline['class'] and sheet.select_one('button.primary')
    assert any('bw-sell.js' in s['src'] for s in page.select('script[src]')) and any('bw-sell.css' in l['href'] for l in page.select('link[href]'))


def test_a_read_only_viewer_sees_the_card_and_the_text(coll, client, app4):
    setup(coll)
    copy = checked_copy(coll)
    app4.config['BW_READ_ONLY'] = True
    page, node = sell_node(client, coll, copy)
    assert node and node.select_one('textarea') and '€51.90' in node.get_text()
    unchecked = coll.add_copy('1000-1', condition='used', completeness='incomplete')
    page, node = sell_node(client, coll, unchecked)
    assert 'Check this copy to price what is missing.' in node.get_text() and not node.select('a[href*="check-parts"]')


def test_the_card_states_on_the_page(coll, client):
    setup(coll)
    unchecked = coll.add_copy('1000-1', condition='used', completeness='incomplete')
    page, node = sell_node(client, coll, unchecked)
    assert node.select_one('a[href*="check-parts"]').get_text() == 'Check this copy' and 'Used average · not adjusted' in node.get_text()
    assert [p.get_text(strip=True) for p in node.select('.bc-sell-pill')] == ['Used', 'Not checked']
    coll.sql("UPDATE price_observation SET voided_at='2026-10-26T12:00:00.000Z' WHERE item_id=? AND condition='used'", (coll.item('sets', '1000-1'),))
    page, node = sell_node(client, coll, unchecked)
    assert node['data-state'] == 'no_quote' and node.select_one('button.bc-sell-copy')['disabled'] is not None and 'no sales' in node.get_text()
    assert node.select_one('a[href*="refresh"]').get_text() == 'Update price'


def test_a_loose_item_and_a_part_have_no_card(coll, client, world):
    page = BeautifulSoup(client.get(f"/collection/item/{world.brick}?colour={world.red}").data, 'html.parser')
    assert not page.select('[data-module=sell]')


def test_the_floor_unknown_and_floor_applied_texts_on_the_page(coll, client):
    setup(coll, average='4.00')
    page, node = sell_node(client, coll, checked_copy(coll))
    text = re.sub(r'\s+', ' ', node.get_text(' ', strip=True))
    assert 'Set to the part-out value: the deductions would take it to €0.00.' in text and 'Asking price · part-out value €6.10' in text and 'Part-out value of what is present' not in text


# ---- the preview script ----

def test_the_preview_script_runs():
    rendered.need_node()
    result = subprocess.run(['node', 'tests/toni_bw_sell_runtime.cjs'], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'sell runtime ok' in result.stdout


def test_a_failed_read_is_an_error_state_with_retry(coll, client, monkeypatch):
    import sqlite3
    setup(coll)
    copy = checked_copy(coll)
    def broken(db, copy_id, stamp=None):
        raise sqlite3.OperationalError('boom')
    monkeypatch.setattr(selling, 'card', broken)
    page, node = sell_node(client, coll, copy)
    assert node['data-state'] == 'error' and 'The asking price did not load.' in node.get_text() and node.select_one('a.bc-outline').get_text() == 'Retry'
    assert not node.select('dialog')


def test_the_assets_are_precached():
    worker = (ROOT / 'static/web/toni/sw.js').read_text()
    assert '/static/web/toni/bw-sell.js' in worker and '/static/web/toni/bw-sell.css' in worker

@pytest.mark.parametrize('state', ['no_quote', 'no_rate', 'deduction_rate'])
def test_price_free_preview_names_known_missing_lines(coll, monkeypatch, state):
    setup(coll, average=None if state == 'no_quote' else '58.00')
    copy = checked_copy(coll)
    if state == 'no_rate':
        coll.sql("UPDATE price_observation SET currency='USD' WHERE item_id=?", (coll.item('sets', '1000-1'),))
    elif state == 'deduction_rate':
        monkeypatch.setattr(deductions, 'shown', lambda *args: None)
    v = card(coll, copy)
    assert v['state'] == ('no_quote' if state == 'no_quote' else 'no_rate')
    assert 'Missing parts' in v['text'] and '(3001)' in v['text'] and '(3023)' in v['text']
    assert '  Missing:' in v['text'] and 'Asking price' not in v['text'] and '€' not in v['text']


@pytest.mark.parametrize('rate_missing', [False, True])
def test_unchecked_pill_survives_unavailable_average(coll, rate_missing):
    setup(coll, average='58.00' if rate_missing else None)
    if rate_missing:
        coll.sql("UPDATE price_observation SET currency='USD' WHERE item_id=?", (coll.item('sets', '1000-1'),))
    v = card(coll, coll.add_copy('1000-1', condition='used'))
    assert 'Not checked' in [p['text'] for p in v['pills']]


def test_missing_floor_conversion_is_no_rate(coll, monkeypatch):
    setup(coll)
    copy = checked_copy(coll)
    monkeypatch.setattr(selling.partout, 'values', lambda *args: {copy: dict(value=Decimal('6.10'), currency='USD')})
    v = card(coll, copy)
    assert v['state'] == 'no_rate' and v['ask']['text'] is None and not v['copy_enabled']
    assert 'Asking price' not in v['text'] and 'Missing parts' in v['text']


@pytest.mark.parametrize('group', ['part', 'figure'])
def test_damage_is_named_without_claiming_complete(coll, group):
    setup(coll)
    copy = checked_copy(coll, brick=0, plate=0, figure=0, completeness='complete')
    if group == 'part':
        coll.mark(copy, '3001', '4', damaged=1)
    else:
        coll.sql('UPDATE copy_part SET damaged=1 WHERE id=(SELECT min(id) FROM copy_part WHERE copy_id=? AND copy_figure_id IS NOT NULL)', (copy,))
    v = card(coll, copy)
    assert dict(text='Complete, 1 damaged', tone='warning') in v['pills']
    assert 'Completeness: complete, 6 pieces, 1 damaged' in v['text']
    assert 'Damaged: 1 ' in v['text'] and v['ask']['text'] == '€58.00'
