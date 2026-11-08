"""#220 the Statistics charts: titles that state the point, the fold after six rows, one scale for every chart. Invented data."""
from bs4 import BeautifulSoup

from brickwork.web import stats_charts
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401  (the fixtures)


def rows(*pairs):
    return [{'label': a, 'count': b} for a, b in pairs]


def data(**kw):
    base = dict(completeness=rows(('Incomplete', 9), ('Not checked', 8), ('Complete', 5), ('Sealed', 3)),
                theme=rows(*[(f'T{i}', 20 - i) for i in range(8)]), storage=rows(('Shelf', 7), ('Box', 1)),
                **{'purchase place': rows(('Flea Market', 11), ('Gift', 7))})
    return {**base, **kw}


def by_kind(result):
    return {c['kind']: c for c in result}


def test_the_headline_and_titles_state_the_point():
    d = data()
    assert stats_charts.headline(d['completeness']) == '9 of 25 copies are incomplete'
    c = by_kind(stats_charts.charts(d))
    assert c['completeness']['title'] == 'Only 5 copies are complete'
    assert c['theme']['title'] == 'T0 is the biggest theme, 20 copies'
    assert c['storage']['title'] == 'Shelf holds the most, 7 copies'
    assert c['purchase place']['title'] == 'Flea Market holds the most, 11 copies'
    assert c['theme']['subtitle'] == 'Copies by theme'


def test_titles_use_the_singular_and_the_edge_cases():
    one = data(completeness=rows(('Complete', 1)), theme=rows(('Harbour', 1)))
    assert stats_charts.headline(one['completeness']) == '0 of 1 copy is incomplete'
    c = by_kind(stats_charts.charts(one))
    assert c['completeness']['title'] == 'All 1 copy is complete'
    assert c['theme']['title'] == 'Harbour is the biggest theme, 1 copy'
    none = data(completeness=rows(('Incomplete', 2)))
    assert by_kind(stats_charts.charts(none))['completeness']['title'] == 'No copy is complete'
    assert stats_charts.headline([]) == 'No copies yet'


def test_completeness_is_in_status_order():
    c = by_kind(stats_charts.charts(data()))
    assert [r['label'] for r in c['completeness']['rows']] == ['Complete', 'Incomplete', 'Not checked', 'Sealed']


def test_a_long_tail_folds_into_one_row_after_six():
    c = by_kind(stats_charts.charts(data()))
    theme = c['theme']['rows']
    assert len(theme) == 7 and [r['folded'] for r in theme] == [False] * 6 + [True]
    assert theme[-1]['label'] == '2 more themes' and theme[-1]['count'] == (14 + 13)
    assert by_kind(stats_charts.charts(data(storage=rows(*[(f'S{i}', 1) for i in range(7)]))))['storage']['rows'][-1]['label'] == '1 more place'
    assert len(by_kind(stats_charts.charts(data(storage=rows(*[(f'S{i}', 1) for i in range(6)]))))['storage']['rows']) == 6


def test_every_chart_shares_one_scale():
    c = by_kind(stats_charts.charts(data()))
    widths = {(k, r['label']): r['width'] for k, v in c.items() for r in v['rows']}
    biggest = max(r['count'] for v in c.values() for r in v['rows'])               # the folded row counts too: 27
    assert biggest == 27 and widths[('theme', '2 more themes')] == 100
    assert widths[('completeness', 'Complete')] == round(100 * 5 / 27, 2)
    assert widths[('storage', 'Box')] == round(100 / 27, 2)
    assert widths[('storage', 'Shelf')] == round(100 * 7 / 27, 2)


def test_the_page_renders_the_charts(coll, world, client):
    html = BeautifulSoup(client.get('/manage/statistics').data, 'html.parser')
    assert html.select_one('h2').get_text() == '1 of 3 copies are incomplete'
    assert len(html.select('.bw-chart')) == 4 and not html.select('.bw-card.bw-chart')
    assert [h.get_text() for h in html.select('.bw-chart h3')][0] == 'Only 1 copy is complete'
    assert len(html.select('.bw-chart-note')) == 1
