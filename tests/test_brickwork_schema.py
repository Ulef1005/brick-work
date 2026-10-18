"""New-store constraints and search maintenance, using invented records."""
from contextlib import closing
import sqlite3

import pytest

from brickwork.core.connect import connect


def test_connections_events_and_search(tmp_path):
    with closing(connect(tmp_path/'new.db')) as db:
        assert db.execute('PRAGMA foreign_keys').fetchone()[0]==1
        assert db.execute('PRAGMA journal_mode').fetchone()[0]=='wal'
        assert db.execute('SELECT version FROM schema_meta').fetchone()[0]=='3.3'
        assert db.execute('SELECT count(*) FROM sources').fetchone()[0]==6
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('P','invented-123','Blue spaceship')")
        db.execute("INSERT INTO item_properties VALUES('P','invented-123','theme','manual','Moonbase',NULL,NULL)")
        assert db.execute("SELECT item_no FROM search_index WHERE search_index MATCH 'Moonbase'").fetchone()[0]=='invented-123'
        db.execute("UPDATE item_properties SET value='Forest' WHERE key='theme'")
        assert db.execute("SELECT count(*) FROM search_index WHERE search_index MATCH 'Moonbase'").fetchone()[0]==0
        db.execute("UPDATE items SET name='Rocket' WHERE item_no='invented-123'")
        assert db.execute("SELECT count(*) FROM search_index WHERE search_index MATCH 'Rocket'").fetchone()[0]==1
        db.execute("INSERT INTO item_properties VALUES('P','invented-123','size','manual','Large',NULL,NULL)")
        assert db.execute('SELECT count(*) FROM search_index').fetchone()[0]==1
        db.execute("DELETE FROM item_properties WHERE key='theme'")
        assert db.execute("SELECT count(*) FROM search_index WHERE search_index MATCH 'Forest'").fetchone()[0]==0
        db.execute('DELETE FROM item_properties');db.execute('DELETE FROM items')
        assert db.execute('SELECT count(*) FROM search_index').fetchone()[0]==0
        db.execute("INSERT INTO events(id,entity,field,old_value,new_value,at,via) VALUES(1,'copies:invented','note',NULL,'hello','2022-01-01','cli')")
        for statement in ('UPDATE events SET new_value=NULL','DELETE FROM events',
                          "INSERT OR REPLACE INTO events(id,entity,field,old_value,new_value,at,via) VALUES(1,'copies:invented','note',NULL,'bad','2022-01-01','cli')"):
            with pytest.raises(sqlite3.IntegrityError,match='append-only'):db.execute(statement)
        with pytest.raises(sqlite3.IntegrityError):db.execute("INSERT INTO copies(id,set_no) VALUES('orphan','absent')")
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert list(db.execute('PRAGMA foreign_key_check'))==[]


def test_all_item_types_and_own_photos(tmp_path):
    with closing(connect(tmp_path/'new.db')) as db:
        db.execute("INSERT INTO colors(color_id,name) VALUES(11,'Blue')")
        for kind in 'SMPIOGBC?':
            db.execute('INSERT INTO items(item_type,item_no) VALUES(?,?)',(kind,'invented-'+kind))
            db.execute('INSERT INTO loose_stock(id,item_type,item_no) VALUES(?,?,?)',(kind,kind,'invented-'+kind))
            db.execute('INSERT INTO wishlist(item_type,item_no,color_id) VALUES(?,?,?)',(kind,'invented-'+kind,11 if kind=='P' else None))
        db.execute("INSERT INTO copies(id,item_type,set_no) VALUES('copy','?','invented-?')")
        db.execute("INSERT INTO item_images(item_type,item_no,source,kind,local_path,copy_id,caption,taken_at) VALUES('?','invented-?','manual','own','data/images/own.jpg','copy','Own caption','2022-01-01')")
        assert db.execute('SELECT caption FROM item_images').fetchone()[0]=='Own caption'
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO item_images(item_type,item_no,source,kind,local_path) VALUES('P','invented-P','manual','own','data/images/../outside.jpg')")
        db.execute("UPDATE copies SET archived_at='2022-01-01'")
        assert db.execute('SELECT count(*) FROM copies').fetchone()[0]==1
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO id_match VALUES('manual','part','source',NULL,'incomplete',NULL,NULL,'unmatched',NULL,'[]',NULL)")
        db.execute("INSERT INTO id_match VALUES('manual','part','source',NULL,NULL,NULL,NULL,'unmatched',NULL,'[]',NULL)")


def test_every_foreign_key_has_an_index(tmp_path):
    with closing(connect(tmp_path/'new.db')) as db:
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'search_index%' AND name NOT LIKE 'sqlite_%'"):
            groups={}
            for r in db.execute(f'PRAGMA foreign_key_list({table})'):
                groups.setdefault(r['id'],[]).append(r['from'])
            indexes=[tuple(r['name'] for r in db.execute(f'PRAGMA index_info({i["name"]})'))
                     for i in db.execute(f'PRAGMA index_list({table})')]
            for columns in groups.values():
                assert any(index[:len(columns)]==tuple(columns) for index in indexes),(table,columns)


def test_null_safe_current_price_uniqueness(tmp_path):
    with closing(connect(tmp_path/'new.db')) as db:
        db.execute("INSERT INTO items(item_type,item_no) VALUES('P','invented')")
        db.execute("INSERT INTO price_observations(id,item_type,item_no,guide,source) VALUES(1,'P','invented','manual','manual')")
        sql="INSERT INTO price_current(item_type,item_no,guide,currency,observation_id) VALUES('P','invented','manual',?,1)"
        db.execute(sql,(None,))
        with pytest.raises(sqlite3.IntegrityError):db.execute(sql,(None,))
        db.execute(sql,('',))  # NULL and empty legacy text remain different keys.
        assert db.execute('SELECT count(*) FROM price_current').fetchone()[0]==2


def test_wishlist_live_keys_and_row_flags(tmp_path):
    with closing(connect(tmp_path/'wishes.db')) as db:
        db.execute("INSERT INTO items(item_type,item_no) VALUES('P','part'),('S','set')")
        db.execute("INSERT INTO colors(color_id) VALUES(0),(11)")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO wishlist(item_type,item_no) VALUES('P','part')")
        for color in (0,11):
            db.execute("INSERT INTO wishlist(item_type,item_no,color_id,quantity) VALUES('P','part',?,3)", (color,))
        for statement in (
            "INSERT INTO wishlist(item_type,item_no,color_id) VALUES('P','part',11)",
            "INSERT INTO wishlist(item_type,item_no,color_id,quantity) VALUES('P','part',11,0)",
            "INSERT INTO wishlist(item_type,item_no,color_id) VALUES('S','set',11)"):
            with pytest.raises(sqlite3.IntegrityError): db.execute(statement)
        db.execute("INSERT INTO wishlist(item_type,item_no) VALUES('S','set')")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO wishlist(item_type,item_no) VALUES('S','set')")
        db.execute("UPDATE wishlist SET archived_at='old' WHERE id=2")
        db.execute("INSERT INTO wishlist(item_type,item_no,color_id) VALUES('P','part',11)")
        with pytest.raises(sqlite3.IntegrityError): db.execute('UPDATE wishlist SET archived_at=NULL WHERE id=2')
        db.execute("INSERT INTO flags(id,name,kind,shown_on_grid) VALUES('tag','Tag','tag',1)")
        db.execute("INSERT INTO item_flags VALUES('wishlist','1','tag')")
        for statement in (
            "INSERT INTO item_flags VALUES('wishlist','999','tag')",
            "UPDATE item_flags SET entity_id='999'",
            'DELETE FROM wishlist WHERE id=1',
            'UPDATE wishlist SET id=99 WHERE id=1',
            "UPDATE wishlist SET item_no='set' WHERE id=1",
            'UPDATE wishlist SET color_id=11 WHERE id=1'):
            with pytest.raises(sqlite3.IntegrityError): db.execute(statement)
        db.execute('UPDATE wishlist SET quantity=4 WHERE id=1')
        assert db.execute('SELECT quantity FROM wishlist WHERE id=1').fetchone()[0] == 4
