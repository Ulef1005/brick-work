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


@pytest.mark.parametrize('name', PAGES)
def test_pages_use_the_local_shell_and_assets(app, name):
    html = render(app, name, error='Example', message='Saved', next='/collection/sets')
    assert 'data-web-ui="toni"' in html
    assert '<title>Brick Work' in html and '<span>Brick Work</span></a>' in html
    assert 'Brick Work (' in html
    assert 'Frederik' + 'Baerentsen' not in html  # the upstream credit lives in the README
    assert 'bootstrap' not in html.lower() and 'remixicon' not in html.lower()
    assert not re.search(r'''<(?:link|script)\b[^>]*\b(?:href|src)=[\"'](?:https?:)?//''', html, re.I)  # nothing loaded from outside
    assert html.index('web/toni/theme.js') < html.index('rel="stylesheet"') < html.index('</head>')
    assert 'defer' not in html.split('web/toni/theme.js')[0].split('<script')[-1]
    for group in ('Collection', 'Workbench', 'Planning', 'Manage'):
        assert f'>{group}</p>' in html


def test_unknown_route_renders_the_shell(app):
    response = app.test_client().get('/no-such-route')
    assert response.status_code == 404
    assert 'data-web-ui="toni"' in response.get_data(as_text=True)


def test_every_template_reference_resolves(app):
    for file in (ROOT / 'templates').rglob('*.html'):
        tree = app.jinja_env.parse(file.read_text())
        for name in meta.find_referenced_templates(tree):
            if name is not None:
                assert (ROOT / 'templates' / name).is_file(), (file, name)
                app.jinja_env.get_template(name)
        for include in tree.find_all(nodes.Include):
            if not isinstance(include.template, nodes.Const):
                assert isinstance(include.template, nodes.Call)
                assert include.template.node.name == 'toni_template'
    assert app.jinja_env.globals['toni_template']('macro/card.html') == PREFIX + 'macro/card.html'


def test_login_post_and_failure(app):
    client = app.test_client()
    html = client.get('/login?next=/collection/sets').get_data(as_text=True)
    assert 'id="password" name="password"' in html
    assert 'action="/login?next=/collection/sets"' in html
    failed = client.post('/login?next=/collection/sets', data={'password': 'wrong'})
    assert failed.status_code == 302
    assert 'Wrong password' in client.get(failed.location).get_data(as_text=True)
    success = client.post('/login?next=/collection/sets', data={'password': 'synthetic-password'})
    assert success.status_code == 302 and success.location == '/collection/sets'
    with client.session_transaction() as session:
        assert session['_user_id'] == 'admin'
    for target in ('//example.test/', 'https://example.test/'):
        again = client.post('/login?next=' + target, data={'password': 'synthetic-password'})
        assert again.location == '/'
    assert client.get('/logout').status_code == 302


def test_visibility_links_and_auth(app):
    app.config.update(HIDE_ALL_SETS=True, HIDE_ADD_SET=True)
    html = render(app, 'web/toni/error.html', error='Example')
    assert '>Sets</a>' not in html and '>Check Set Parts</a>' not in html
    assert 'href="/workbench/orders"' in html
    app.config['LOGIN_DISABLED'] = True


def test_assets_have_no_remote_references():
    assets = ROOT / 'static/web/toni'
    tokens = (assets / 'tokens-v2.css').read_text()
    assert '@import' not in tokens and 'fonts.googleapis' not in tokens
    css = (assets / 'toni.css').read_text()
    for filename in re.findall(r"url\('([^']+)'\)", css):
        assert (assets / filename).is_file()
    for file in assets.glob('*'):
        if file.suffix in ('.css', '.js'):
            assert not re.search(r'https?://|url\(["\']?//', file.read_text().replace('http://www.w3.org/2000/svg', 'SVG_NAMESPACE'))


def test_theme_runtime_precedence_storage_and_system():
    """Execute the actual pre-paint script with DOM/storage/media test doubles."""
    import shutil
    import subprocess
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is needed to execute the JavaScript theme contract')
    source = (ROOT / 'static/web/toni/theme.js').read_text()
    harness = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const source = SOURCE;
for (const [stored, initial, denied, expected] of [
 ['light','dark',false,'light'], ['dark','light',false,'dark'],
 ['system','dark',false,'system'], [null,'dark',false,'dark'],
 [null,'light',false,'light'], ['invalid','dark',false,'dark'],
 [null,'invalid',false,'system'], [null,'invalid',true,'system'],
 [null,'light',true,'light']
]) {
 const classes=new Set(), saved=[], events=[];let osChange;
 const sandbox={window:{},document:{documentElement:{dataset:{themeDefault:initial},classList:{remove(...names){names.forEach(n=>classes.delete(n))},add(n){classes.add(n)}}},dispatchEvent(e){events.push(e)}},localStorage:{getItem(){if(denied)throw Error('denied');return stored},setItem(k,v){if(denied)throw Error('denied');saved.push([k,v])}},matchMedia(){return {addEventListener(type,fn){assert.equal(type,'change');osChange=fn}}},CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail}}};
 vm.runInNewContext(source,sandbox);
 assert.equal(sandbox.window.adminTheme.mode,expected);
 assert.deepEqual([...classes],expected==='system'?[]:['tw-'+expected]);
 assert.equal(saved.length,0); // Do not persist server default or resolved OS choice.
 sandbox.window.adminTheme.apply('system',true);
 assert.equal(classes.size,0);
 if(!denied)assert.deepEqual(saved,[['tw-admin-theme','system']]);
 const count=events.length;osChange();assert.equal(events.length,count+1);
 assert.equal(events.at(-1).detail,'system');
 sandbox.window.adminTheme.apply('dark');const explicit=events.length;
 osChange();assert.equal(events.length,explicit);
 sandbox.window.adminTheme.apply('invalid',true);assert.equal(sandbox.window.adminTheme.mode,'system');
}
'''.replace('SOURCE', json.dumps(source))
    subprocess.run([node, '-e', harness], check=True, capture_output=True, text=True)


def test_theme_default_follows_the_device_unless_server_forces_dark(app):
    # Decision 2026-10-05: per-device System/Light/Dark; DARK_MODE only seeds "dark".
    for value, expected in [(False, 'system'), ('false', 'system'), (None, 'system'), (True, 'dark')]:
        app.config['DARK_MODE'] = value
        html = app.test_client().get('/login').get_data(as_text=True)
        assert f'data-theme-default="{expected}"' in html, (value, expected)


@pytest.mark.parametrize('path', ['/workbench/part-picker', '/workbench/matcher'])
def test_workbench_pages_have_shell_helpers(app, bw, path):
    response = logged_in(app).get(path)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'data-web-ui="toni"' in html
    assert '<svg class="icon"' in html
    assert 'aria-current="page"' in html
    assert 'href="/workbench/part-to-inventory"' in html
