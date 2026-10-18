"""4.8b: a wish maximum carries a currency; Under max compares only equal currencies."""
import json
import shutil
import sqlite3

from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin, collection, planning, upgrade
from brickwork.core.connect import connect
from brickwork.core.sources.base import now
from tests.importer.test_importer import legacy
from tests.test_bw_collection import bw, post, token
from tests.web_fixtures import app, logged_in
from tests.web_fixtures import apps
from tests.test_bw_admin import reset_shell_metadata_after_test


def old_file(bw, tmp_path, setting=None, name='old.db'):
    """A copy of the migrated file as it was before 4.8b: no currency column."""
    path = tmp_path / name
    shutil.copy(bw, path)
    db = sqlite3.connect(path)
    db.execute('PRAGMA foreign_keys=OFF')
    db.execute('DROP INDEX wishlist_live_key'); db.execute('DROP INDEX wishlist_color_fk')
    db.execute('ALTER TABLE wishlist DROP COLUMN max_price_currency')
    db.execute('CREATE UNIQUE INDEX wishlist_live_key ON wishlist(item_type,item_no,color_id IS NULL,coalesce(color_id,0)) WHERE archived_at IS NULL')
    db.execute('CREATE INDEX wishlist_color_fk ON wishlist(color_id)')
    db.execute("INSERT INTO items(item_type,item_no,name) VALUES('S','no-max','No max'),('S','with-max','With max')")
    db.execute("INSERT INTO wishlist(item_type,item_no,max_price) VALUES('S','no-max',NULL),('S','with-max','12.5')")
    if setting is not None:
        db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('bricklink_currency',?)", (setting,))
    db.commit(); db.close()
    return path


def wishes(path):
    db = sqlite3.connect(path)
    try: return db.execute('SELECT item_no,max_price,max_price_currency FROM wishlist ORDER BY id').fetchall()
    finally: db.close()


def test_fresh_ddl_has_column(tmp_path):
    db = connect(tmp_path / 'fresh.db')
    try: assert 'max_price_currency' in [r[1] for r in db.execute('PRAGMA table_info(wishlist)')]
    finally: db.close()


@pytest.mark.parametrize('setting,expected', [(None, 'EUR'), ('USD', 'USD')])
def test_upgrade_backfills_configured_currency_and_reruns_as_noop(bw, tmp_path, setting, expected):
    path = old_file(bw, tmp_path, setting)
    if setting is None:
        db = sqlite3.connect(path); db.execute("DELETE FROM settings WHERE key='bricklink_currency'"); db.commit(); db.close()
    before_other = sqlite3.connect(path).execute('SELECT id,item_type,item_no,quantity,condition,note,updated_at FROM wishlist ORDER BY id').fetchall()
    events_before = sqlite3.connect(path).execute('SELECT count(*) FROM events').fetchone()[0]
    first = upgrade.upgrade(path)['wish_currency']
    assert first['column_added'] and first['backfilled'] == 2 and first['currency'] == expected
    rows = dict((r[0], r[1:]) for r in wishes(path))
    assert rows['with-max'] == ('12.5', expected) and rows['new-set'] == ('0.125', expected)
    assert rows['no-max'] == (None, None)
    after_other = sqlite3.connect(path).execute('SELECT id,item_type,item_no,quantity,condition,note,updated_at FROM wishlist ORDER BY id').fetchall()
    assert after_other == before_other
    assert sqlite3.connect(path).execute('SELECT count(*) FROM events').fetchone()[0] == events_before
    snapshot = wishes(path)
    again = upgrade.upgrade(path)['wish_currency']
    assert again == dict(column_added=False, backfilled=0, currency=None) and wishes(path) == snapshot


def test_connect_upgrades_old_files_read_only_and_writable(bw, tmp_path):
    for read_only in (True, False):
        path = old_file(bw, tmp_path, name=f'old-{read_only}.db')
        db = connect(path, read_only=read_only)
        try: assert db.execute("SELECT max_price_currency FROM wishlist WHERE item_no='with-max'").fetchone()[0] == 'EUR'
        finally: db.close()


def only_wish(db, number='new-set'):
    return db.execute('SELECT id FROM wishlist WHERE item_no=?', (number,)).fetchone()[0]


def test_save_both_fields_undo_and_audit(bw):
    with admin.database(bw) as db:
        wish = only_wish(db)
        event = collection.save(db, 'wish', [wish], dict(max_price='20', max_price_currency=' usd '))
        row = db.execute('SELECT max_price,max_price_currency FROM wishlist WHERE id=?', (wish,)).fetchone()
        assert tuple(row) == ('20', 'USD')
        ev = db.execute('SELECT * FROM events WHERE id=?', (event,)).fetchone()
        old, new = json.loads(ev['old_value'])[0]['rows'][0], json.loads(ev['new_value'])[0]['rows'][0]
        assert (old['max_price'], old['max_price_currency']) == ('0.125', 'EUR')
        assert (new['max_price'], new['max_price_currency']) == ('20', 'USD') and ev['via'] == 'app'
        collection.undo(db, event)
        assert tuple(db.execute('SELECT max_price,max_price_currency FROM wishlist WHERE id=?', (wish,)).fetchone()) == ('0.125', 'EUR')


def test_max_without_currency_keeps_existing_or_configured(bw):
    with admin.database(bw) as db:
        wish = only_wish(db)
        collection.save(db, 'wish', [wish], dict(max_price='9'))
        assert db.execute('SELECT max_price_currency FROM wishlist WHERE id=?', (wish,)).fetchone()[0] == 'EUR'
        with db: db.execute("UPDATE wishlist SET max_price=NULL,max_price_currency=NULL"); db.execute("INSERT OR REPLACE INTO settings VALUES('bricklink_currency','GBP')")
        collection.save(db, 'wish', [wish], dict(max_price='9'))
        assert db.execute('SELECT max_price_currency FROM wishlist WHERE id=?', (wish,)).fetchone()[0] == 'GBP'
        collection.save(db, 'wish', [wish], dict(max_price='10', max_price_currency='usd'))
        collection.save(db, 'wish', [wish], dict(max_price='11'))
        assert db.execute('SELECT max_price_currency FROM wishlist WHERE id=?', (wish,)).fetchone()[0] == 'USD'


def test_clearing_max_clears_currency_and_undo_restores(bw):
    with admin.database(bw) as db:
        wish = only_wish(db)
        event = collection.save(db, 'wish', [wish], dict(max_price='', max_price_currency=''))
        assert tuple(db.execute('SELECT max_price,max_price_currency FROM wishlist WHERE id=?', (wish,)).fetchone()) == (None, None)
        collection.undo(db, event)
        assert tuple(db.execute('SELECT max_price,max_price_currency FROM wishlist WHERE id=?', (wish,)).fetchone()) == ('0.125', 'EUR')


@pytest.mark.parametrize('values,message', [
    (dict(max_price='5', max_price_currency='E'), '3 to 8 letters'),
    (dict(max_price='5', max_price_currency='EU1'), '3 to 8 letters'),
    (dict(max_price='5', max_price_currency='EUROPEANS'), '3 to 8 letters'),
    (dict(max_price='', max_price_currency='EUR'), 'clear the currency'),
])
def test_currency_validation(bw, values, message):
    with admin.database(bw) as db:
        wish = only_wish(db)
        before = tuple(db.execute('SELECT max_price,max_price_currency FROM wishlist WHERE id=?', (wish,)).fetchone())
        with pytest.raises(ValueError, match=message): collection.save(db, 'wish', [wish], values)
        assert tuple(db.execute('SELECT max_price,max_price_currency FROM wishlist WHERE id=?', (wish,)).fetchone()) == before


def test_currency_alone_needs_a_max(bw):
    with admin.database(bw) as db:
        wish = only_wish(db)
        collection.save(db, 'wish', [wish], dict(max_price='', max_price_currency=''))
        with pytest.raises(ValueError, match='max price before'): collection.save(db, 'wish', [wish], dict(max_price_currency='USD'))
        collection.save(db, 'wish', [wish], dict(max_price='4'))
        collection.save(db, 'wish', [wish], dict(max_price_currency='chf'))
        assert db.execute('SELECT max_price_currency FROM wishlist WHERE id=?', (wish,)).fetchone()[0] == 'CHF'


def priced(db, currency, price, wish_currency, maximum='100'):
    wish = only_wish(db)
    with db:
        db.execute('UPDATE wishlist SET max_price=?,max_price_currency=?,condition=? WHERE id=?', (maximum, wish_currency, 'used', wish))
        oid = db.execute("""INSERT INTO price_observations(item_type,item_no,condition,guide,currency,region,source,price,observed_at)
            VALUES('S','new-set','U','sold',?,'eu','bricklink',?,?)""", (currency, price, now().isoformat())).lastrowid
        db.execute("DELETE FROM price_current WHERE item_no='new-set' AND guide='sold'")
        db.execute("INSERT INTO price_current(item_type,item_no,condition,guide,observation_id) VALUES('S','new-set','U','sold',?)", (oid,))
    return wish


@pytest.mark.parametrize('price,state,margin', [('80', 'under', '20'), ('100', 'under', '0'), ('130', 'over', '-30')])
def test_under_max_equal_currency(bw, price, state, margin):
    with admin.database(bw) as db:
        priced(db, 'EUR', price, 'EUR')
        row = planning.wishes(db)[0]
        assert row['max_state'] == state and row['max_margin'] == __import__('decimal').Decimal(margin)


@pytest.mark.parametrize('price_currency,max_currency', [('EUR', 'USD'), ('usd', 'EUR')])
def test_under_max_not_compared_across_currencies(bw, price_currency, max_currency):
    with admin.database(bw) as db:
        priced(db, price_currency, '5', max_currency)
        row = planning.wishes(db)[0]
        assert row['max_state'] == 'differs' and row['max_margin'] is None


def test_under_max_none_without_max_price_or_currency(bw):
    with admin.database(bw) as db:
        priced(db, 'EUR', '5', None)
        assert planning.wishes(db)[0]['max_state'] is None
        priced(db, 'EUR', '5', 'EUR', maximum=None)
        assert planning.wishes(db)[0]['max_state'] is None


def wish_page(app, screen='wishlist'):
    return BeautifulSoup(logged_in(app).get('/planning/' + screen).data, 'html.parser')


def test_wishlist_card_shows_currency_and_under_max(app, bw):
    with admin.database(bw) as db: priced(db, 'EUR', '80', 'EUR')
    soup = wish_page(app)
    row = soup.select_one('[data-bp-row]')
    assert row.select_one('.bp-max strong').text == '€100.00'
    assert '€20.00 under max' in row.select_one('.bp-max-diff').text
    record = json.loads(row['data-record'])
    assert record['under'] == 'under' and record['undermax'] == '-20' and record['max'] == '100'
    assert not row.select('.bp-max-note')
    text = soup.get_text()
    assert 'no recorded currency' not in text
    assert [o['value'] for o in soup.select('[data-bp-filter=under] option')] == ['', 'under', 'over', 'nomax', 'differs']
    assert [(b['data-value'], b.text) for b in soup.select('.bp-price-filter [data-bp-pick=under]')] == [('under','Under max'),('over','Over max'),('nomax','No max set'),('differs','Not comparable')]
    assert soup.select_one('.bp-price-filter-label').text == 'Price filter'
    assert not soup.select('.bp-price-note')
    assert row.select_one('.bp-verdict').text == 'Under max'
    assert ('undermax', 'Under max') in [(o['value'], o.text) for o in soup.select('[data-bp-sort] option')]


def test_wishlist_card_over_and_differing_currency(app, bw):
    with admin.database(bw) as db: priced(db, 'EUR', '130', 'EUR')
    row = wish_page(app).select_one('[data-bp-row]')
    assert '€30.00 over max' in row.select_one('.bp-max-diff').text
    assert row.select_one('.bp-verdict.over').text == 'Over max'
    assert json.loads(row['data-record'])['under'] == 'over'
    with admin.database(bw) as db: priced(db, 'EUR', '130', 'USD')
    row = wish_page(app).select_one('[data-bp-row]')
    assert row.select_one('.bp-max strong').text == '$100.00'
    assert row.select_one('.bp-max-note').text == 'Max in USD, price in EUR'
    assert not row.select('.bp-max-diff')
    record = json.loads(row['data-record'])
    assert record['under'] == 'differs' and record['undermax'] is None
    assert row.select_one('.bp-verdict.differs').text == 'Not comparable'
    assert 'No verdict is given' in wish_page(app).select_one('.bp-price-note').text


def test_wishlist_no_max_has_no_verdict(app, bw):
    with admin.database(bw) as db: priced(db, 'EUR', '80', 'EUR', maximum=None)
    row = wish_page(app).select_one('[data-bp-row]')
    assert not row.select('.bp-verdict')
    assert json.loads(row['data-record'])['under'] == 'nomax'


def test_wishlist_max_without_comparable_price_has_no_verdict(app, bw):
    with admin.database(bw) as db:
        wish = only_wish(db)
        with db:
            db.execute('DELETE FROM price_current')
            db.execute('UPDATE wishlist SET max_price=?,max_price_currency=?,condition=? WHERE id=?', ('100', 'EUR', 'used', wish))
    soup = wish_page(app)
    row = soup.select_one('[data-bp-row]')
    assert not row.select('.bp-verdict')
    assert not row.select('.bp-max-note')
    assert json.loads(row['data-record'])['under'] == 'noprice'
    assert 'noprice' not in [b['data-value'] for b in soup.select('.bp-price-filter [data-bp-pick=under]')]
    assert not soup.select('.bp-price-note')


def test_wanted_card_and_edit_form_carry_currency(app, bw):
    with admin.database(bw) as db: wish = priced(db, 'EUR', '80', 'USD')
    client = logged_in(app)
    soup = BeautifulSoup(client.get(f'/collection/wishes/{wish}').data, 'html.parser')
    assert soup.select_one('.bc-wanted-max strong').text == '$100.00'
    assert soup.select_one('input[name=max_price_currency]')['value'] == 'USD'
    assert soup.select_one('input[name=max_price_currency]')['maxlength'] == '8'
    assert 'Currency is not stored' not in soup.get_text()
    assert 'Max in USD' in soup.select_one('.bc-wish-facts').text
    response = post(client, token(client), 'save', entity='wish', ids=[wish], values=dict(max_price='101', max_price_currency='gbp'))
    assert response.status_code == 200
    soup = BeautifulSoup(client.get(f'/collection/wishes/{wish}').data, 'html.parser')
    assert soup.select_one('.bc-wanted-max strong').text == '£101.00'
    bad = post(client, token(client), 'save', entity='wish', ids=[wish], values=dict(max_price='5', max_price_currency='1'))
    assert bad.status_code == 400 and '3 to 8 letters' in bad.json['message']
    assert post(client, token(client), 'undo', event_id=response.json['event_id']).status_code == 200
    with admin.database(bw) as db:
        assert tuple(db.execute('SELECT max_price,max_price_currency FROM wishlist WHERE id=?', (wish,)).fetchone()) == ('100', 'USD')


def test_limit_without_currency_is_filled_on_next_open(app, bw):
    with admin.database(bw) as db: wish = priced(db, 'EUR', '80', None)
    soup = BeautifulSoup(logged_in(app).get(f'/collection/wishes/{wish}').data, 'html.parser')
    assert soup.select_one('.bc-wanted-max strong').text == '€100.00'


def test_wishlist_queries_constant(app, bw, monkeypatch):
    client = logged_in(app)
    with admin.database(bw) as db: priced(db, 'EUR', '80', 'EUR')
    original = admin.connect
    statements = []
    def traced(*args, **kwargs):
        db = original(*args, **kwargs); db.set_trace_callback(statements.append); return db
    monkeypatch.setattr(admin, 'connect', traced)
    def count():
        statements.clear()
        assert client.get('/planning/wishlist').status_code == 200
        return len([s for s in statements if s.lstrip().upper().startswith('SELECT')])
    small = count()
    with admin.database(bw) as db, db:
        for i in range(300):
            number = 'cur-bulk-' + str(i)
            db.execute("INSERT INTO items(item_type,item_no,name) VALUES('S',?,'Bulk')", (number,))
            db.execute("INSERT INTO wishlist(item_type,item_no,max_price,max_price_currency) VALUES('S',?,'50',?)", (number, 'USD' if i % 2 else 'EUR'))
            oid = db.execute("""INSERT INTO price_observations(item_type,item_no,condition,guide,currency,region,source,price,observed_at)
                VALUES('S',?,'U','sold','EUR','eu','bricklink','40',?)""", (number, now().isoformat())).lastrowid
            db.execute("INSERT INTO price_current(item_type,item_no,condition,guide,observation_id) VALUES('S',?,'U','sold',?)", (number, oid))
    assert count() <= small + 2
    assert len(client.get('/planning/wishlist').data) > 0


def test_concurrent_upgrader_adding_the_column_first_is_not_an_error(bw, tmp_path):
    path = old_file(bw, tmp_path, name='race.db')
    db = sqlite3.connect(path); db.isolation_level = None
    other = sqlite3.connect(path)
    other.execute('ALTER TABLE wishlist ADD COLUMN max_price_currency TEXT'); other.commit(); other.close()
    # stale view: the check said "missing", the ALTER now meets a duplicate
    class Wrap:
        def __init__(self, inner): self.inner = inner; self.first = True
        def execute(self, sql, *a):
            if sql.startswith('PRAGMA table_info') and self.first:
                self.first = False
                cur = self.inner.execute(sql, *a)
                return iter([r for r in cur.fetchall() if r[1] != 'max_price_currency'])
            return self.inner.execute(sql, *a)
        def __enter__(self): return self.inner.__enter__()
        def __exit__(self, *a): return self.inner.__exit__(*a)
    result = upgrade.upgrade_wish_currency(Wrap(db))
    assert result['column_added'] is False and result['backfilled'] == 2
    db.close()


def test_failed_read_only_upgrade_is_not_retried_per_request(bw, tmp_path, monkeypatch):
    from brickwork.core import connect as connect_module
    path = old_file(bw, tmp_path, name='ro.db')
    connect_module._FAILED.clear()
    calls = []
    def failing(p): calls.append(p); raise sqlite3.OperationalError('attempt to write a readonly database')
    monkeypatch.setattr(upgrade, 'upgrade', failing)
    for _ in range(3):
        db = connect(path, read_only=True)
        assert db.execute('SELECT count(*) FROM wishlist').fetchone()[0] >= 1
        db.close()
    assert len(calls) == 1
    monkeypatch.setattr(connect_module, 'RETRY_SECONDS', 0)
    connect(path, read_only=True).close()
    assert len(calls) == 2
    connect_module._FAILED.clear()


def test_clearing_only_the_currency_is_rejected_before_any_write(bw):
    with admin.database(bw) as db:
        wish = only_wish(db)
        before = tuple(db.execute('SELECT max_price,max_price_currency,updated_at FROM wishlist WHERE id=?', (wish,)).fetchone())
        events = db.execute('SELECT count(*) FROM events').fetchone()[0]
        with pytest.raises(ValueError, match='max price before its currency'):
            collection.save(db, 'wish', [wish], {'max_price_currency': ''})
        assert tuple(db.execute('SELECT max_price,max_price_currency,updated_at FROM wishlist WHERE id=?', (wish,)).fetchone()) == before
        assert db.execute('SELECT count(*) FROM events').fetchone()[0] == events


def test_upgrade_without_settings_table_uses_default(bw, tmp_path):
    path = old_file(bw, tmp_path, name='nosettings.db')
    db = sqlite3.connect(path)
    db.execute('PRAGMA foreign_keys=OFF'); db.execute('DROP TABLE settings'); db.commit(); db.close()
    result = upgrade.upgrade(path)['wish_currency']
    assert result['currency'] == 'EUR' and result['backfilled'] == 2
