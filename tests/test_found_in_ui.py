from bs4 import BeautifulSoup
from tests.app4 import app4, client, coll, pair, world  # noqa: F401


def test_part_module_and_fragment(client, coll, world):
    part, color = coll.item('parts', '970c03'), coll.colour('0')
    page = client.get(f'/collection/item/{part}?colour={color}')
    assert page.status_code == 200
    soup = BeautifulSoup(page.data, 'html.parser')
    module = soup.select_one('[data-found-in]')
    assert module and f'color={color}' in module['data-url']
    assert 'this colour only' in module.text
    response = client.get(module['data-url'] + '&type=minifigures')
    assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
    assert client.get(module['data-url'] + '&offset=bad').status_code == 400
    assert not BeautifulSoup(client.get(f'/collection/item/{part}').data, 'html.parser').select_one('[data-found-in]')


def test_figure_links_follow_index(client, coll, world):
    figure = coll.item('minifigs', 'fig-000004')
    page = client.get(f'/collection/item/{figure}')
    assert page.status_code == 200
    soup = BeautifulSoup(page.data, 'html.parser')
    assert soup.select('.bc-found-link')
    for link in soup.select('.bc-found-link'):
        assert '#found-in' in link.parent['href']
        assert 'Found in ' in link.text


def test_node_runtime():
    import shutil
    import subprocess
    import pytest
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is not installed')
    subprocess.run([node, 'tests/toni_bw_found_in_runtime.cjs'], check=True)


def test_found_identity_controls_and_singular_counts(client, coll, world):
    part, color = coll.item('parts', '970c03'), coll.colour('0')
    soup = BeautifulSoup(client.get(f'/collection/item/{part}?colour={color}').data, 'html.parser')
    module = soup.select_one('[data-found-in]')
    assert module.select_one('[data-found-filters][aria-controls="found-type"]')
    assert module.select_one('#found-type[hidden] select[name="type"]')
    assert not module.select('[data-found-form] button:not([type="button"])')
    for row in module.select('.bc-found-row'):
        identity = row.select_one('.bc-found-identity')
        assert identity.select_one('.bc-found-number')
        assert identity.select_one('p.bc-found-quantity')
        assert len(row.select(':scope > *')) == 2
    # A search that isolates a single catalogue identity exercises the actual fragment.
    found = module.select_one('.bc-found-number').text.strip()
    fragment = BeautifulSoup(client.get(module['data-url'] + '&q=' + found).data, 'html.parser')
    rows = fragment.select('.bc-found-row')
    sets = sum(r['data-found-kind'] == 'set' for r in rows)
    figures = sum(r['data-found-kind'] == 'minifigure' for r in rows)
    one = lambda n, word: f"{n} {word}" if n == 1 else f"{n} {word}s"
    lines = [p.text.strip() for p in fragment.select('p')[:2]]
    assert lines[0] == f"In {one(sets, 'set')} and {one(figures, 'minifigure')}"
    assert lines[1].startswith(one(len(rows), 'item') + ', of which')
    assert rows and 'In 1 sets' not in fragment.text and '1 items' not in fragment.text
