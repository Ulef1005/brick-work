"""Shell composition, login, theme and asset contracts on the standalone app."""
import json
import re

from flask import g, render_template
from jinja2 import meta, nodes
import pytest

from brickwork.web.ui import PREFIX, ROOT
from tests.test_bw_collection import bw
from tests.importer.test_importer import legacy
from tests.web_fixtures import app, apps, logged_in

PAGES = ['web/toni/login.html', 'web/toni/error.html']


def render(app, name, **context):
    with app.test_request_context('/login'):
        app.preprocess_request()
        g.request_time = lambda: '0ms'
        return render_template(name, **context)


@pytest.mark.parametrize('path', ['/workbench/part-picker', '/workbench/matcher'])
def test_workbench_pages_have_shell_helpers(app, bw, path):
    response = logged_in(app).get(path)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'data-web-ui="toni"' in html
    assert '<svg class="icon"' in html
    assert 'aria-current="page"' in html
    assert 'href="/workbench/part-to-inventory"' in html
