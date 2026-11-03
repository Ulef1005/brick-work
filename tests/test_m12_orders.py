"""M.12 (issue #114): an order keeps its currency without a total. `purchase_order` allows a currency without a cost (a cost still needs its
currency); an e-mail has a currency and no total, so its order stores EUR; stored orders get theirs from the raw document."""
import json
import sqlite3

import pytest

from brickwork.core import orders
from tests.app4 import app4, client, coll, csrf, pair, read, world  # noqa: F401 (fixtures)
from tests.test_bw_orders_storage import XML, inventory, line_of

NOW = '2026-10-26T12:00:00.000Z'


def email(world, coll):
    name = coll.db.execute('SELECT name FROM item WHERE id=?', (world.brick,)).fetchone()[0]
    return f'* Batch #1 (submitted Oct 12, 2026)\n[Used] Red {name} (x3) ... EUR 0.12 each = EUR 0.36'


def test_the_table_allows_a_currency_without_a_cost_and_refuses_a_cost_without_a_currency(coll):
    coll.sql("INSERT INTO purchase_order(id,currency,created_at,updated_at) VALUES(1,'EUR',?,?)", (NOW, NOW))
    coll.sql("INSERT INTO purchase_order(id,cost,currency,created_at,updated_at) VALUES(2,'4.00','EUR',?,?)", (NOW, NOW))
    coll.sql("INSERT INTO purchase_order(id,created_at,updated_at) VALUES(3,?,?)", (NOW, NOW))
    with pytest.raises(sqlite3.IntegrityError):
        coll.sql("INSERT INTO purchase_order(id,cost,created_at,updated_at) VALUES(4,'4.00',?,?)", (NOW, NOW))


def test_an_email_without_a_total_stores_its_currency_and_line_prices_show_it(world, coll, client):
    result = orders.import_document(coll.db, 'email', email(world, coll))
    order = orders.get(coll.db, result['order_id'])
    assert (order['cost'], order['currency']) == (None, 'EUR')
    oid = result['order_id']
    orders.phase(coll.db, oid, result['document_id'], 'review')
    orders.phase(coll.db, oid, result['document_id'], 'save')
    page = client.get(f'/workbench/orders/{oid}').text
    assert 'Currency not recorded' not in page and 'EUR' in page


def test_an_order_with_a_total_keeps_both_and_an_xml_without_a_currency_stores_neither(coll):
    with_total = XML.replace('</INVENTORY>', '<ORDERID>5</ORDERID><CURRENCY>USD</CURRENCY><COST>9.50</COST></INVENTORY>')
    order = orders.get(coll.db, orders.import_document(coll.db, 'xml', with_total)['order_id'])
    assert (order['cost'], order['currency']) == ('9.50', 'USD')
    plain = XML.replace('0.12', '0.13')
    order = orders.get(coll.db, orders.import_document(coll.db, 'xml', plain)['order_id'])
    assert (order['cost'], order['currency']) == (None, None)


def test_an_xml_with_a_currency_and_no_total_stores_the_currency(coll):
    xml = XML.replace('</INVENTORY>', '<CURRENCY>GBP</CURRENCY></INVENTORY>')
    order = orders.get(coll.db, orders.import_document(coll.db, 'xml', xml)['order_id'])
    assert (order['cost'], order['currency']) == (None, 'GBP')


def test_linking_a_document_with_a_currency_fills_the_orders_missing_one_and_a_clash_is_refused(world, coll):
    first = orders.import_document(coll.db, 'xml', XML)
    assert orders.get(coll.db, first['order_id'])['currency'] is None
    second = orders.import_document(coll.db, 'email', email(world, coll), choice=first['order_id'])
    assert orders.get(coll.db, first['order_id'])['currency'] == 'EUR'
    usd = XML.replace('0.12', '0.15').replace('</INVENTORY>', '<CURRENCY>USD</CURRENCY></INVENTORY>')
    with pytest.raises(ValueError, match='currencies differ'):
        orders.import_document(coll.db, 'xml', usd, choice=first['order_id'])
    orders.undo(coll.db, second['event_id'])
    assert orders.get(coll.db, first['order_id'])['currency'] is None                      # Undo puts the order back as it was


def old_order(coll, world, *, text=None):
    """An order as the stored files hold it from before: its e-mail document is there, its currency is not."""
    result = orders.import_document(coll.db, 'email', text or email(world, coll))
    coll.sql('UPDATE purchase_order SET currency=NULL WHERE id=?', (result['order_id'],))
    return result['order_id']


def test_stored_orders_get_their_currency_from_the_raw_document(world, coll):
    oid = old_order(coll, world)
    assert orders.get(coll.db, oid)['currency'] is None
    assert orders.fill_currencies(coll.db) == [oid]
    assert orders.get(coll.db, oid)['currency'] == 'EUR'
    event = coll.db.execute("SELECT field, entity_kind FROM event ORDER BY id DESC LIMIT 1").fetchone()
    assert event['field'] == 'currency'
    assert orders.fill_currencies(coll.db) == []                                           # nothing more to do the second time


def test_filling_leaves_alone_an_order_with_no_document_or_two_currencies(world, coll):
    coll.sql("INSERT INTO purchase_order(id,created_at,updated_at) VALUES(901,?,?)", (NOW, NOW))
    mixed = old_order(coll, world)
    usd = XML.replace('0.12', '0.15').replace('</INVENTORY>', '<CURRENCY>USD</CURRENCY></INVENTORY>')
    other = orders.import_document(coll.db, 'xml', usd)                                    # its own order; move its document under the e-mail's order
    coll.sql('UPDATE order_document SET order_id=? WHERE id=?', (mixed, other['document_id']))
    coll.sql('UPDATE order_line SET order_id=? WHERE document_id=?', (mixed, other['document_id']))
    coll.sql('DELETE FROM purchase_order WHERE id=?', (other['order_id'],))
    assert orders.fill_currencies(coll.db) == []
    assert orders.get(coll.db, 901)['currency'] is None and orders.get(coll.db, mixed)['currency'] is None


def test_the_app_fills_stored_currencies_when_it_starts(world, coll, app4):
    oid = old_order(coll, world)
    from brickwork.web.views import bw_resume_imports
    bw_resume_imports(app4)
    assert orders.get(coll.db, oid)['currency'] == 'EUR'


def named_later(coll):
    """An order imported with no currency whose stored document names one (the import is as an earlier version left it)."""
    result = orders.import_document(coll.db, 'xml', XML)
    payload = json.dumps(dict(text=XML.replace('</INVENTORY>', '<CURRENCY>GBP</CURRENCY></INVENTORY>')))
    coll.sql("UPDATE source_record SET payload=? WHERE kind='order_document:xml'", (payload,))
    return result


def test_a_filled_currency_can_be_undone_and_then_the_import_too(world, coll):
    result = named_later(coll)
    oid = result['order_id']
    assert orders.fill_currencies(coll.db) == [oid] and orders.get(coll.db, oid)['currency'] == 'GBP'
    filled = coll.db.execute("SELECT id FROM event WHERE field='currency' ORDER BY id DESC LIMIT 1").fetchone()[0]
    orders.undo(coll.db, filled)
    assert orders.get(coll.db, oid)['currency'] is None
    orders.undo(coll.db, result['event_id'])


def test_a_filled_currency_does_not_block_the_imports_undo_until_it_is_undone_first(world, coll):
    result = named_later(coll)
    orders.fill_currencies(coll.db)
    with pytest.raises(ValueError):
        orders.undo(coll.db, result['event_id'])


def test_the_binding_check_requires_the_binding_to_exist(coll):
    from brickwork.store4 import crosscheck
    assert crosscheck.binding(coll.db)['ok']
    coll.sql("DELETE FROM main.meta WHERE key='catalogue_id'")
    found = crosscheck.run(coll.db)
    assert not found[0]['ok'] and found[0]['name'] == 'binding' and 'not bound' in found[0]['message'] and 'reconcile' in found[0]['message']


def test_a_collection_with_the_old_check_still_starts(world, coll, app4, caplog):
    import logging
    oid = old_order(coll, world)
    coll.db.execute('PRAGMA foreign_keys=OFF')
    sql = coll.db.execute("SELECT sql FROM sqlite_master WHERE name='purchase_order'").fetchone()[0]
    coll.db.execute('PRAGMA writable_schema=ON')
    coll.db.execute("UPDATE sqlite_master SET sql=? WHERE name='purchase_order'", (sql.replace('CHECK(cost IS NULL OR currency IS NOT NULL)', 'CHECK((cost IS NULL) = (currency IS NULL))'),))
    coll.db.commit()
    coll.db.close()
    from brickwork.web.views import bw_resume_imports
    with caplog.at_level(logging.WARNING):
        bw_resume_imports(app4)
    assert 'currency' in caplog.text
