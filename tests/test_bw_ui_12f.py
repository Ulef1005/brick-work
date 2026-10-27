"""v1.3 figure detail states and shared item-detail regressions on the 4.0 store (M.8d, issue #110): what is left writes through the collection save.

An unidentified figure has no number to add by, so its page offers a button that puts the item itself (by id) on the wishlist, with a receipt
that Undo takes back; the wanted link into Add for an identified item is in `test_bw_add.py` (M.8c)."""
import sqlite3

from bs4 import BeautifulSoup
import pytest

from brickwork.core import collection
from tests.app4 import app4, client, coll, csrf, pair, post, read  # noqa: F401 (fixtures)


def wanted(client, item):
    response = client.get(f'/collection/item/{item}')
    assert response.status_code == 200
    return BeautifulSoup(response.data, 'html.parser').select_one('[data-module=wanted]')


def test_unresolved_wanted_receipt_undo_and_rollback(coll, client):
    token = csrf(client)
    figure = coll.local('minifigure', 'Review figure')
    module = wanted(client, figure)
    assert module.select_one('form[data-bc-action=wish] button').get_text() == 'Add to wishlist'
    assert 'Not on the wishlist' in module.get_text()
    saved = post(client, token, 'wish', item_id=figure)
    assert saved.status_code == 200, saved.json
    assert 'On the wishlist' in wanted(client, figure).get_text()
    assert post(client, token, 'wish', item_id=figure).status_code == 400
    event = saved.json['event_id']
    assert tuple(coll.db.execute('SELECT entity_kind, field, via FROM event WHERE id=?', (event,)).fetchone()) == ('collection', 'save', 'app')
    undone = post(client, token, 'undo', event_id=event)
    assert undone.status_code == 200
    assert 'Not on the wishlist' in wanted(client, figure).get_text()
    coll.db.execute("CREATE TRIGGER reject_wish BEFORE INSERT ON event WHEN new.entity_kind='collection' BEGIN SELECT RAISE(ABORT,'receipt failed'); END")
    with pytest.raises(sqlite3.IntegrityError):
        collection.want(coll.db, figure)
    assert coll.db.execute('SELECT count(*) FROM wish WHERE item_id=? AND archived_at IS NULL', (figure,)).fetchone()[0] == 0


def test_an_identified_figure_is_added_through_add_not_by_this_button(coll, client):
    figure = coll.item('minifigs', 'fig-000004')
    coll.add_stock('minifigure', figure, quantity=1)
    module = wanted(client, figure)
    assert not module.select_one('form[data-bc-action=wish]')
    assert module.find('a', string='Add to wishlist')['href'].startswith('/manage/add?')
