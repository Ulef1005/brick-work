"""#152: small CLI, MCP and order messages found in B.7 and B.4. Invented data, no network."""
import json

import pytest

from brickwork.core import orders
from brickwork.core.mcp import client as mcp_client
from brickwork.store4 import cli as store4_cli
from brickwork.web import admin_ops, cli
from brickwork.web.cli import main
from tests.app4 import app4, coll, pair, world  # noqa: F401 (fixtures)


def test_an_item_job_names_its_item_not_none():
    lines = []
    store4_cli.show_job(dict(id=1, kind='item', number=None, item_id=10, state='done', attempts=1, step={'count': 2}), lines.append)
    assert lines[0].startswith('job 1 item 10: done')


def test_the_mcp_default_api_url_is_the_installs_port():
    import inspect
    from brickwork.core.mcp import server
    assert inspect.signature(server.run).parameters['api_url'].default == 'http://127.0.0.1:3333/api/v2'
    assert cli.build_parser().parse_args(['mcp']).api_url == 'http://127.0.0.1:3333/api/v2'


def test_a_web_page_instead_of_the_api_says_so(monkeypatch):
    class Page:
        status_code = 200
        headers = {'Content-Type': 'text/html; charset=utf-8'}
        text = '<!doctype html><title>Brick Work</title>'

        def json(self):
            raise ValueError('not json')
    monkeypatch.setattr(mcp_client.requests, 'request', lambda *a, **k: Page())
    status, body = mcp_client.HTTPClient('http://127.0.0.1:3333', 'token').request('GET', '/me')
    assert status == 502 and body['code'] == 'not_the_api' and '/api/v2' in body['detail']


def test_a_word_for_the_incomplete_discount_is_the_range_message(app4, world):
    with pytest.raises(ValueError, match='incomplete_discount_pct must be an integer from 0 to 95'):
        admin_ops.settings_set('incomplete_discount_pct', 'abc')


def test_a_second_wishlist_undo_says_already_undone(app4, world, capsys):
    assert main(['wishlist', 'create', 'Twice', '--json']) == 0
    target = json.loads(capsys.readouterr().out)['id']
    assert main(['wishlist', 'copy', target, world.wish_part, '--json']) == 0
    event = json.loads(capsys.readouterr().out)['event_id']
    assert main(['wishlist', 'undo', str(event), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['message'] == 'Undone'
    assert main(['wishlist', 'undo', str(event), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['message'] == 'Already undone'


def test_a_purged_bricklink_order_says_so(monkeypatch):
    class Purged:
        def __init__(self, db):
            pass

        def list_orders(self, filed=False):
            return [dict(order_id=30028491, status='PURGED')]

        def order_items(self, number):
            raise AssertionError('a purged order is not fetched')
    monkeypatch.setattr(orders, 'BrickLink', Purged)
    with pytest.raises(ValueError, match="BrickLink has purged this order's items · paste the order e-mail instead"):
        orders.api_data(None, '30028491')
