"""Paging of the lot page's lists past 100 rows (#200, #201): every candidate set and every sticker candidate is reachable through the links."""
import re
from contextlib import closing

from bs4 import BeautifulSoup
import pytest

from brickwork.core.connect import connect
from tests.app4 import Coll, app4, client, make_pair  # noqa: F401 (fixtures)
from tests.stickers_world import DUMP, World

MANY = 130
EXTRA = [f'96{n:03d}-1' for n in range(MANY)]


@pytest.fixture
def pair(tmp_path):
    dump = {k: list(v) for k, v in DUMP.items()}
    dump['sets'] += [[n, f'Stk Many {n[:5]}', 2020, 700, 40, ''] for n in EXTRA]
    dump['inventories'] += [[9700 + i, 1, n] for i, n in enumerate(EXTRA)]
    dump['inventory_parts'] += ([[9700 + i, 'stk-tile', 4, 4, 'False', ''] for i in range(MANY)] + [[9700 + i, 'stk-sheet-b', 0, 1, 'False', ''] for i in range(MANY)]
                                + [[9700 + i, 'stk-r1', 4, 1, 'False', ''] for i in range(MANY)])
    return make_pair(tmp_path, extra_dump=dump)


@pytest.fixture
def world(pair):
    with closing(connect(pair)) as db:
        yield World(Coll(db), flag=True)


def get(client, url):
    response = client.get(url)
    assert response.status_code == 200
    return BeautifulSoup(response.text, 'html.parser')


def follow(client, url, link_text, rows, scope=''):
    """Visit every page by its 'more' link; the numbers of all rows seen."""
    seen = []
    for _ in range(20):
        soup = get(client, url)
        seen += [r.select_one('.bd-number').text for r in soup.select(rows)]
        link = next((a for a in soup.select(scope + ' .bd-more-link a') if a.text == link_text), None)
        if link is None:
            return seen
        url = url.split('?')[0] + link['href'].split('#')[0]
    raise AssertionError('the links never end')


def test_set_detection_reaches_every_candidate_past_100(client, world):
    url = f'/collection/lots/{world.lot}?detect=1&min_score=0&ignore_common=0&show=100'
    seen = follow(client, url, 'Show more candidates', '.bd-cand', '#set-detection')
    assert len(seen) == len(set(seen)) and len(seen) > 130 and set(f'{n}' for n in EXTRA) <= set(seen)
    second = get(client, url + '&offset=100')
    assert second.select_one('#set-detection .bd-more-link').text.startswith('Previous candidates') and len(second.select('.bd-cand')) == 69 and len(get(client, url).select('.bd-cand')) == 100


def test_the_sticker_chooser_reaches_every_set_past_100(client, world):
    url = f'/collection/lots/{world.lot}/sticker/{world.line}?all=1'
    seen = follow(client, url, 'Show more', '.bd-set', '#sticker-chooser')
    assert len(seen) == len(set(seen)) and set(EXTRA) <= set(seen)
    page = get(client, url)
    assert len(page.select('.bd-set')) == 100
    assert get(client, url + '&offset=100').select_one('#sticker-chooser .bd-more-link').text.startswith('Previous sets')
    first = get(client, f'/collection/lots/{world.lot}/sticker/{world.line}')
    assert first.select_one('#sticker-chooser .bd-more-link a')['href'].startswith('?all=1#'), 'Show all starts at the top of the list'
