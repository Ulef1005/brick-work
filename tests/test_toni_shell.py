"""Shell composition on the standalone app, on the ported Workbench screens (M.8e, issue #110).

The 3.3 file imported a login/error rendering helper that no test used; the one test it had is the Workbench pages' shell helpers."""
import pytest

from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401 (fixtures)


@pytest.mark.parametrize('path', ['/workbench/part-picker', '/workbench/matcher'])
def test_workbench_pages_have_shell_helpers(world, client, path):
    response = client.get(path)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'data-web-ui="toni"' in html
    assert '<svg class="icon"' in html
    assert 'aria-current="page"' in html
    assert 'href="/workbench/part-to-inventory"' in html
