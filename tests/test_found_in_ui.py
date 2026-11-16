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
