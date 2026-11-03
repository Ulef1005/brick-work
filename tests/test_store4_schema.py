"""4.0 schema: constraint checks C1-C9 (catalogue) and L0-L15 (collection) ported from the design's test run (design 12),
the guard coverage of every item reference, and the two halves equal to the design DDL. Invented records only."""
from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

STORE = Path(__file__).parent.parent / 'brickwork' / 'store4'
DESIGN = Path(__file__).parent.parent / 'docs' / 'data-model-4.0' / 'schema-4.0.sql'
NOW = '2026-10-23T12:00:00Z'


def load(name):
    db = sqlite3.connect(':memory:', isolation_level=None)
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript((STORE / name).read_text())
    return db


def ok(db, label, sql, args=()):
    try:
        db.execute(sql, args)
    except sqlite3.Error as e:
        pytest.fail(f'{label}: unexpectedly refused: {e}')


def refused(db, label, sql, args=(), expect=None):
    try:
        db.execute(sql, args)
    except sqlite3.IntegrityError as e:
        assert expect is None or expect in str(e), f'{label}: refused for another reason: {e}'
        return
    pytest.fail(f'{label}: unexpectedly accepted')


def check(label, cond, detail=''):
    assert cond, f'{label} {detail}'


def test_halves_equal_the_design_ddl():
    assert (STORE / 'catalogue.sql').read_text() + (STORE / 'brickwork.sql').read_text() == DESIGN.read_text()


def test_catalogue_constraints():
    with closing(load('catalogue.sql')) as c:
        c.execute("INSERT INTO build(id,kind,started_at,app_version,files_json,counts_json) VALUES(1,'rebrickable_dump',?,'4.0','[]','{}')", (NOW,))
        c.execute("INSERT INTO build(id,kind,started_at,app_version,files_json,counts_json) VALUES(2,'mapping',?,'4.0','[]','{}')", (NOW,))
        ok(c, 'C1 colour 1 = Rebrickable 9999', "INSERT INTO color VALUES(1,'[No Color/Any Color]','05131D',0,'rebrickable','9999',1,NULL)")
        ok(c, 'C1 colour 2 = Rebrickable -1', "INSERT INTO color VALUES(2,'[Unknown]','0033B2',0,'rebrickable','-1',1,NULL)")
        refused(c, 'C1 fixed id 1 cannot hold another colour', "INSERT INTO color VALUES(1,'Red','C91A09',0,'rebrickable','4',1,NULL)")
        refused(c, 'C1 Rebrickable 9999 cannot take another id', "INSERT INTO color VALUES(9,'x',NULL,0,'rebrickable','9999',1,NULL)")
        for cid, name, key in ((3, 'Red', '4'), (4, 'Black', '0'), (5, 'White', '15'), (6, 'Pastel Blue', '1051'), (7, 'Maersk Blue', '313')):
            c.execute("INSERT INTO color VALUES(?,?,NULL,0,'rebrickable',?,1,NULL)", (cid, name, key))
        c.execute("INSERT INTO theme(id,name,build_id) VALUES(186,'Castle',1),(501,'Gear',1)")
        c.execute("UPDATE theme SET item_kind='gear' WHERE id=501")
        items = [(10, 'set', 'namespace', "King's Mountain Fortress", 'sets', '6081-1', 186),
                 (11, 'part', 'namespace', 'Plate 1 x 2', 'parts', '3023', None),
                 (12, 'part', 'namespace', 'Hips and Black Legs', 'parts', '970c03', None),
                 (13, 'minifigure', 'namespace', 'Knight', 'minifigs', 'fig-004576', None),
                 (14, 'part', 'namespace', 'Brick Arch 1 x 5 x 4', 'parts', '2339', None),
                 (15, 'gear', 'theme', 'Key Chain', 'sets', '853176-1', 501),
                 (16, 'part', 'namespace', 'Sticker Sheet', 'parts', '003402', None)]
        for i, k, ks, n, ns, key, th in items:
            c.execute("INSERT INTO item(id,kind,kind_source,name,name_key,born_provider,born_namespace,born_key,theme_id,build_id,digest) VALUES(?,?,?,?,?,'rebrickable',?,?,?,1,'d')",
                      (i, k, ks, n, n.lower(), ns, key, th))
        refused(c, 'C2 a part cannot be classified by theme', "INSERT INTO item(id,kind,kind_source,name,name_key,born_provider,born_namespace,born_key,build_id,digest) VALUES(20,'gear','theme','x','x','rebrickable','parts','p20',1,'d')")
        refused(c, 'C2 namespace kind must match the namespace', "INSERT INTO item(id,kind,kind_source,name,name_key,born_provider,born_namespace,born_key,build_id,digest) VALUES(21,'gear','namespace','x','x','rebrickable','sets','s21',1,'d')")
        refused(c, 'C2 born key unique (provider, namespace, key)', "INSERT INTO item(id,kind,kind_source,name,name_key,born_provider,born_namespace,born_key,build_id,digest) VALUES(22,'set','namespace','x','x','rebrickable','sets','6081-1',1,'d')")
        ok(c, 'C2 same key in another namespace is another item', "INSERT INTO item(id,kind,kind_source,name,name_key,born_provider,born_namespace,born_key,build_id,digest) VALUES(23,'part','namespace','x','x','rebrickable','parts','6081-1',1,'d')")
        ok(c, 'C3 kind change keeps the id (theme guess corrected by BrickLink)', "UPDATE item SET kind='set', kind_source='bricklink' WHERE id=15")
        check('C3 id 15 still the same born key', c.execute("SELECT id,kind FROM item WHERE born_key='853176-1'").fetchone() == (15, 'set'))
        refused(c, 'C3 a part cannot change kind', "UPDATE item SET kind='gear', kind_source='bricklink' WHERE id=11")
        refused(c, 'C4 catalogue cannot mint into the local range', "INSERT INTO item(id,kind,kind_source,name,name_key,born_provider,born_namespace,born_key,build_id,digest) VALUES(1000000005,'set','namespace','x','x','rebrickable','sets','2026-1',1,'d')")
        ok(c, 'C4 catalogue adopts a local id (set fetched via API before the dump)', "INSERT INTO item(id,kind,kind_source,name,name_key,born_provider,born_namespace,born_key,adopted,build_id,digest) VALUES(1000000005,'set','namespace','x','x','rebrickable','sets','2026-1',1,1,'d')")
        c.execute("INSERT INTO inventory(id,item_id,version,ordinal,is_latest,build_id,digest,part_lines,figure_lines,set_lines) VALUES(1,10,1,1,1,1,'a',2,1,0)")
        refused(c, 'C5 one inventory per (item, version)', "INSERT INTO inventory(id,item_id,version,ordinal,is_latest,build_id,digest,part_lines,figure_lines,set_lines) VALUES(2,10,1,1,0,1,'b',0,0,0)")
        refused(c, 'C5 one latest inventory per item', "INSERT INTO inventory(id,item_id,version,ordinal,is_latest,build_id,digest,part_lines,figure_lines,set_lines) VALUES(3,10,2,2,1,1,'b',0,0,0)")
        c.execute("INSERT INTO inventory_part VALUES(1,14,4,0,2),(1,11,5,0,4),(1,11,5,1,1)")
        refused(c, 'C6 inventory line key is the primary key (no surrogate id)', "INSERT INTO inventory_part VALUES(1,14,4,0,9)")
        check('C6 inventory_part is WITHOUT ROWID', 'WITHOUT ROWID' in c.execute("SELECT sql FROM sqlite_master WHERE name='inventory_part'").fetchone()[0])
        ok(c, 'C7 leg rule: 970c03 in Black -> BrickLink 970c00 (colour-scoped)', "INSERT INTO item_link(item_id,color_id,provider,provider_kind,provider_key,status,method,origin,preferred,evidence_digest,build_id) VALUES(12,4,'bricklink','P','970c00','matched','leg_rule','rule',1,'e',2)")
        ok(c, 'C7 leg rule: 970c03 in other colours -> 970c11 (unscoped)', "INSERT INTO item_link(item_id,color_id,provider,provider_kind,provider_key,status,method,origin,preferred,evidence_digest,build_id) VALUES(12,NULL,'bricklink','P','970c11','matched','leg_rule','rule',1,'e',2)")
        refused(c, 'C7 duplicate unscoped link refused (NULL colour coalesced)', "INSERT INTO item_link(item_id,color_id,provider,provider_kind,provider_key,status,method,origin,evidence_digest,build_id) VALUES(12,NULL,'bricklink','P','970c11','matched','external_ids','shipped','e',2)")
        refused(c, 'C7 two preferred links for one (item, provider, colour)', "INSERT INTO item_link(item_id,color_id,provider,provider_kind,provider_key,status,method,origin,preferred,evidence_digest,build_id) VALUES(12,4,'bricklink','P','970c99','matched','external_ids','shipped',1,'e',2)")
        refused(c, 'C7 a catalogue link needs an item', "INSERT INTO item_link(item_id,provider,provider_kind,provider_key,status,method,origin,evidence_digest,build_id) VALUES(NULL,'bricklink','P','x','matched','external_ids','shipped','e',2)")
        refused(c, "C7 status 'unmatched' no longer exists on links", "INSERT INTO item_link(item_id,provider,provider_kind,provider_key,status,method,origin,evidence_digest,build_id) VALUES(14,'bricklink','P','2339','unmatched','external_ids','shipped','e',2)")
        for k in ('310.3stk01', '311.1stk01', '312.3stk01'):
            c.execute("INSERT INTO item_link(item_id,provider,provider_kind,provider_key,status,method,origin,evidence_digest,build_id) VALUES(16,'bricklink','P',?,'matched','external_ids','shipped','e',2)", (k,))
        ok(c, 'C8 BrickLink 72 <- Rebrickable 1051 (inverse preferred)', "INSERT INTO color_link(color_id,provider,provider_key,status,method,origin,inverse_preferred,build_id) VALUES(6,'bricklink','72','matched','external_ids','shipped',1,2)")
        ok(c, 'C8 BrickLink 72 <- Rebrickable 313 too', "INSERT INTO color_link(color_id,provider,provider_key,status,method,origin,inverse_preferred,build_id) VALUES(7,'bricklink','72','matched','external_ids','shipped',0,2)")
        refused(c, 'C8 only one inverse per BrickLink colour', "UPDATE color_link SET inverse_preferred=1 WHERE color_id=7")
        check('C9 catalogue foreign_key_check clean', c.execute('PRAGMA foreign_key_check').fetchall() == [])


def test_collection_constraints():
    with closing(load('brickwork.sql')) as d:
        d.execute("INSERT INTO catalogue_build VALUES(1,'rebrickable_dump',NULL,?,NULL,'{}')", (NOW,))
        check('L0 setup seeds colours 1 and 2', d.execute('SELECT id,born_key FROM color ORDER BY id').fetchall() == [(1, '9999'), (2, '-1')])
        for cid, name, key in ((3, 'Red', '4'), (4, 'Black', '0'), (5, 'White', '15')):
            d.execute("INSERT INTO color(id,origin,name,is_trans,born_provider,born_key,created_at,updated_at) VALUES(?,'catalogue',?,0,'rebrickable',?,?,?)", (cid, name, key, NOW, NOW))
        refused(d, 'L0 a second Rebrickable 9999 colour', "INSERT INTO color(id,origin,name,is_trans,born_provider,born_key,created_at,updated_at) VALUES(9,'catalogue','x',0,'rebrickable','9999',?,?)", (NOW, NOW))
        ok(d, 'L0 a BrickLink-only colour is local, above the base', "INSERT INTO color(id,origin,name,is_trans,born_provider,born_key,created_at,updated_at) VALUES(1000000001,'local','BL only',0,'bricklink','999',?,?)", (NOW, NOW))


        def proj(i, kind, ns, key, ks='namespace', origin='catalogue', prov='rebrickable'):
            d.execute("INSERT INTO item(id,origin,kind,kind_source,name,born_provider,born_namespace,born_key,catalogue_build_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (i, origin, kind, ks, f'item {i}', prov, ns, key, 1 if origin == 'catalogue' else None, NOW, NOW))


        proj(10, 'set', 'sets', '6081-1'); proj(11, 'part', 'parts', '3023'); proj(12, 'part', 'parts', '970c03')
        proj(13, 'minifigure', 'minifigs', 'fig-004576'); proj(14, 'part', 'parts', '2339'); proj(15, 'gear', 'sets', '853176-1', 'theme')
        proj(16, 'gear', 'sets', '5004932-1', 'theme'); proj(17, 'set', 'sets', '6285-1'); proj(18, 'part', 'parts', '4624')
        refused(d, 'L1 a local item below the base', "INSERT INTO item(id,origin,kind,kind_source,name,created_at,updated_at) VALUES(99,'local','part','manual','x',?,?)", (NOW, NOW))
        proj(1000000001, 'part', 'P', '970c00', 'namespace', 'local', 'bricklink')
        ok(d, 'L1 an unidentified item: local, no born key', "INSERT INTO item(id,origin,kind,kind_source,name,created_at,updated_at) VALUES(1000000002,'local','part','manual','unknown part',?,?)", (NOW, NOW))
        refused(d, 'L1 a catalogue item needs a Rebrickable born key', "INSERT INTO item(id,origin,kind,kind_source,name,created_at,updated_at) VALUES(50,'catalogue','part','manual','x',?,?)", (NOW, NOW))

        # --- copy and pending state (finding 7, decision F)
        d.execute("INSERT INTO job(id,source,kind,item_id,state,via,created_at,updated_at) VALUES(1,'import','item',10,'queued','app',?,?)", (NOW, NOW))
        d.execute("INSERT INTO job(id,source,kind,item_id,state,via,created_at,updated_at) VALUES(2,'bricklink','subsets',10,'queued','app',?,?)", (NOW, NOW))
        ok(d, "L2 job source 'import' (pipeline) is a seeded source", "SELECT 1")
        ok(d, 'L2 copy on Rebrickable v1 with BrickLink list pending', "INSERT INTO copy(id,item_id,inventory_source,inventory_version,inventory_digest,materialised_at,inventory_pending,pending_job_id,created_at,updated_at) VALUES('c1',10,'rebrickable',1,'dg',?,'bricklink',2,?,?)", (NOW, NOW, NOW))
        refused(d, 'L2 pending without its job', "INSERT INTO copy(id,item_id,inventory_source,inventory_version,inventory_digest,inventory_pending,created_at,updated_at) VALUES('c2',10,'rebrickable',1,'dg','bricklink',?,?)", (NOW, NOW))
        refused(d, "L2 source 'bricklink' needs a fetched list", "INSERT INTO copy(id,item_id,inventory_source,inventory_digest,created_at,updated_at) VALUES('c3',10,'bricklink','dg',?,?)", (NOW, NOW))
        ok(d, "L2 set_preference 'bricklink' before any list was fetched", "INSERT INTO set_preference VALUES(10,'bricklink',NULL,?)", (NOW,))
        d.execute("INSERT INTO fetched_inventory(id,item_id,source,seq,is_latest,fetched_at,digest,part_lines,figure_lines) VALUES(1,17,'bricklink',1,1,?,'x',1,0)", (NOW,))
        refused(d, 'L2 a copy cannot use another set\'s fetched list (composite FK)', "INSERT INTO copy(id,item_id,inventory_source,fetched_inventory_id,inventory_digest,created_at,updated_at) VALUES('c4',10,'bricklink',1,'dg',?,?)", (NOW, NOW))
        refused(d, 'L2 two latest fetched lists per (item, source)', "INSERT INTO fetched_inventory(id,item_id,source,seq,is_latest,fetched_at,digest,part_lines,figure_lines) VALUES(2,17,'bricklink',2,1,?,'y',1,0)", (NOW,))
        d.execute("UPDATE fetched_inventory SET is_latest=0 WHERE id=1")
        ok(d, 'L2 a second fetch is seq 2, latest; seq 1 stays for copies built from it', "INSERT INTO fetched_inventory(id,item_id,source,seq,is_latest,fetched_at,digest,part_lines,figure_lines) VALUES(2,17,'bricklink',2,1,?,'y',1,0)", (NOW,))
        d.execute("INSERT INTO fetched_inventory(id,item_id,source,seq,is_latest,fetched_at,digest,part_lines,figure_lines) VALUES(3,10,'bricklink',1,1,?,'z',2,0)", (NOW,))
        d.execute("INSERT INTO fetched_inventory_part VALUES(3,11,5,0,4),(3,18,4,0,1)")
        refused(d, 'L2 fetched line key is the primary key', "INSERT INTO fetched_inventory_part VALUES(3,11,5,0,1)")

        # --- figure lines and part lines
        d.execute("INSERT INTO copy_figure(id,copy_id,item_id,inventory_source,inventory_version,inventory_digest,quantity,updated_at) VALUES(1,'c1',13,'rebrickable',1,'f',2,?)", (NOW,))
        d.execute("INSERT INTO copy(id,item_id,inventory_source,inventory_version,inventory_digest,created_at,updated_at) VALUES('c5',10,'rebrickable',1,'dg',?,?)", (NOW, NOW))
        refused(d, "L3 copy_part cannot name another copy's figure (composite FK)", "INSERT INTO copy_part(copy_id,copy_figure_id,item_id,color_id,quantity) VALUES('c5',1,12,3,2)")
        ok(d, 'L3 copy_part of its own figure', "INSERT INTO copy_part(id,copy_id,copy_figure_id,item_id,color_id,quantity) VALUES(100,'c1',1,12,3,2)")
        d.execute("INSERT INTO copy_part(id,copy_id,item_id,color_id,is_spare,quantity) VALUES(101,'c1',14,4,0,2),(102,'c1',11,5,0,4),(103,'c1',11,5,1,1),(104,'c1',18,4,0,1)")
        refused(d, 'L3 one row per line key in a copy', "INSERT INTO copy_part(copy_id,item_id,color_id,is_spare,quantity) VALUES('c1',14,4,0,1)")
        ok(d, "L4 missing=2, damaged=1 of 2 (today's per-field bounds, checker.py:454-468)", "UPDATE copy_part SET missing=2, damaged=1 WHERE id=101")
        refused(d, 'L4 missing above quantity', "UPDATE copy_part SET missing=3 WHERE id=101")

        # --- re-materialisation with references (finding 2)
        d.execute("INSERT INTO stock(id,kind,item_id,color_id,quantity,condition,created_at,updated_at) VALUES('s1','part',18,4,3,'used',?,?)", (NOW, NOW))
        d.execute("INSERT INTO event(id,at,via,entity_kind,field) VALUES(1,?,'app','stock','take')", (NOW,))
        d.execute("INSERT INTO stock_transfer(at,kind,stock_id,copy_id,copy_part_id,item_id,color_id,quantity,source_snapshot,event_id) VALUES(?,'part','s1','c1',104,18,4,1,'{}',1)", (NOW,))
        d.execute("INSERT INTO purchase_order(id,created_at,updated_at) VALUES(1,?,?)", (NOW, NOW))
        d.execute("INSERT INTO order_document(id,order_id,source,digest,phase,created_at,updated_at) VALUES(1,1,'xml','x','saved',?,?)", (NOW, NOW))
        d.execute("INSERT INTO order_line(id,order_id,document_id,line_no,state,qty,updated_at) VALUES(1,1,1,1,'matched',1,?)", (NOW,))
        d.execute("INSERT INTO allocation(confirm_id,order_id,line_id,qty,state,target_kind,kind,copy_id,copy_part_id,item_id,color_id,created_at) VALUES('a',1,1,1,'applied','copy','missing_part','c1',104,18,4,?)", (NOW,))
        d.execute("INSERT INTO part_check(copy_id,copy_figure_id,session_id,order_mode,session_json,started_at,updated_at) VALUES('c1',1,'s','inventory','{}',?,?)", (NOW, NOW))
        refused(d, "L5 the initial design's 'replace the rows' fails once a Take/allocation exists", "DELETE FROM copy_part WHERE copy_id='c1'", expect='FOREIGN KEY')
        # Switch c1 to BrickLink list (fetched_inventory 3: 3023 White x4, 4624 Black x1): update in place by line key,
        # insert new, retire vanished. Then a switch where 4624 vanishes (BrickLink 4624c02 granularity).
        d.execute('BEGIN')
        new_lines = {(None, 11, 5, 0): 4, (None, 1000000002, 4, 0): 1}       # e.g. a list where 4624 is replaced
        old = {(r[1], r[2], r[3], r[4]): r[0] for r in d.execute("SELECT id,copy_figure_id,item_id,color_id,is_spare FROM copy_part WHERE copy_id='c1' AND copy_figure_id IS NULL")}
        for key, qty in new_lines.items():
            if key in old:
                d.execute("UPDATE copy_part SET quantity=?, missing=min(missing,?), damaged=min(damaged,?), retired_at=NULL WHERE id=?", (qty, qty, qty, old[key]))
            else:
                d.execute("INSERT INTO copy_part(copy_id,copy_figure_id,item_id,color_id,is_spare,quantity) VALUES('c1',?,?,?,?,?)", (key[0], key[1], key[2], key[3], qty))
        for key, pid in old.items():
            if key not in new_lines:
                d.execute("UPDATE copy_part SET retired_at=? WHERE id=?", (NOW, pid))
        d.execute("UPDATE copy SET inventory_source='bricklink', inventory_version=NULL, fetched_inventory_id=3, inventory_digest='z', inventory_pending=NULL, pending_job_id=NULL WHERE id='c1'")
        d.execute('COMMIT')
        check('L5 switch by in-place update + retire commits with Take, allocation and check session in place',
              d.execute('PRAGMA foreign_key_check').fetchall() == [] and d.execute("SELECT retired_at IS NOT NULL FROM copy_part WHERE id=104").fetchone() == (1,),
              'copy_part 104 retired, stock_transfer and allocation still reference it')
        ok(d, 'L5 switching back re-activates the same row id', "UPDATE copy_part SET retired_at=NULL, quantity=1 WHERE id=104")
        check('L5 stock_transfer still points at row 104', d.execute('SELECT copy_part_id FROM stock_transfer').fetchone() == (104,))

        # --- merge rules (finding 4)
        d.execute("INSERT INTO stock(id,kind,item_id,quantity,inventory_source,created_at,updated_at) VALUES('f1','minifigure',13,1,'migrated',?,?)", (NOW, NOW))
        d.execute("INSERT INTO stock_part(id,stock_id,item_id,color_id,quantity) VALUES(1,'f1',1000000001,4,1)")
        d.execute("INSERT INTO item_link(item_id,provider,provider_kind,provider_key,status,method,origin,decided_at) VALUES(1000000001,'bricklink','P','970c00','matched','migration','migration',?)", (NOW,))
        refused(d, 'L6 a live catalogue item cannot be merged away', "UPDATE item SET merged_into=12 WHERE id=11")
        refused(d, 'L6 a local item cannot be merged while referenced', "UPDATE item SET merged_into=12 WHERE id=1000000001")
        d.execute('BEGIN')
        d.execute("UPDATE stock_part SET item_id=12 WHERE item_id=1000000001")
        d.execute("UPDATE item_link SET item_id=12, color_id=4 WHERE item_id=1000000001")
        d.execute("UPDATE item SET merged_into=12 WHERE id=1000000001")
        d.execute("INSERT INTO item_redirect VALUES(1000000001,12)")
        d.execute('COMMIT')
        check('L6 local BrickLink-born 970c00 merged into catalogue 970c03 after moving references', d.execute('SELECT merged_into FROM item WHERE id=1000000001').fetchone() == (12,))
        refused(d, 'L6 a redirect must match its merge', "INSERT INTO item_redirect VALUES(1000000002,12)")
        refused(d, 'L6 INSERT naming a merged item (copy_part)', "INSERT INTO copy_part(copy_id,item_id,color_id,quantity) VALUES('c5',1000000001,4,1)")
        refused(d, 'L6 UPDATE to a merged item (copy_part)', "UPDATE copy_part SET item_id=1000000001 WHERE id=102")
        refused(d, 'L6 INSERT naming a merged item (stock_part, not guarded before)', "INSERT INTO stock_part(stock_id,item_id,color_id,quantity) VALUES('f1',1000000001,3,1)")
        refused(d, 'L6 INSERT naming a merged item (price_observation, not guarded before)', "INSERT INTO price_observation(item_id,guide,source,observed_at) VALUES(1000000001,'sold','bricklink',?)", (NOW,))
        ok(d, 'L6 materialising a catalogue line still works (no catalogue row names a merged id)', "INSERT INTO copy_part(copy_id,item_id,color_id,quantity) VALUES('c5',12,4,1)")
        d.execute("UPDATE item SET catalogue_retired_at=? WHERE id=18", (NOW,))
        refused(d, 'L6 a retired catalogue item can be merged only after its references move', "UPDATE item SET merged_into=11 WHERE id=18")
        proj(19, 'part', 'parts', '3001old'); d.execute("UPDATE item SET catalogue_retired_at=? WHERE id=19", (NOW,))
        ok(d, 'L6 a retired, unreferenced catalogue item (a Rebrickable rename) can be merged', "UPDATE item SET merged_into=11 WHERE id=19")
        refused(d, 'L6 merge into an item of another kind', "UPDATE item SET merged_into=10 WHERE id=1000000002")

        # --- stock merge key with NULLs (finding 8)
        ok(d, 'L7 3023 White used, no lot, no storage', "INSERT INTO stock(id,kind,item_id,color_id,quantity,condition,created_at,updated_at) VALUES('s2','part',11,5,10,'used',?,?)", (NOW, NOW))
        refused(d, 'L7 the identical line again (NULL lot and storage)', "INSERT INTO stock(id,kind,item_id,color_id,quantity,condition,created_at,updated_at) VALUES('s3','part',11,5,1,'used',?,?)", (NOW, NOW))
        ok(d, 'L7 3023 White with condition NULL', "INSERT INTO stock(id,kind,item_id,color_id,quantity,created_at,updated_at) VALUES('s4','part',11,5,1,?,?)", (NOW, NOW))
        refused(d, 'L7 the same with condition NULL again', "INSERT INTO stock(id,kind,item_id,color_id,quantity,created_at,updated_at) VALUES('s5','part',11,5,1,?,?)", (NOW, NOW))
        d.execute("UPDATE stock SET archived_at=? WHERE id='s2'", (NOW,))
        ok(d, 'L7 a new live line after the old one was archived', "INSERT INTO stock(id,kind,item_id,color_id,quantity,condition,created_at,updated_at) VALUES('s6','part',11,5,1,'used',?,?)", (NOW, NOW))
        ok(d, 'L7 two identical loose figures stay two rows', "INSERT INTO stock(id,kind,item_id,quantity,inventory_source,created_at,updated_at) VALUES('f2','minifigure',13,1,'migrated',?,?)", (NOW, NOW))
        refused(d, 'L7 a loose figure needs a part-list source (G6)', "INSERT INTO stock(id,kind,item_id,quantity,created_at,updated_at) VALUES('f3','minifigure',13,1,?,?)", (NOW, NOW))
        refused(d, 'L7 a loose part has no part-list source', "INSERT INTO stock(id,kind,item_id,color_id,quantity,inventory_source,created_at,updated_at) VALUES('s7','part',14,4,1,'rebrickable',?,?)", (NOW, NOW))

        # --- "no match at provider" with an item (finding 5)
        ok(d, 'L8 item 2339 has no BrickLink id: item_provider_status', "INSERT INTO item_provider_status VALUES(14,'bricklink','unmatched','no_match','{\"rebrickable\":\"2339\"}',?)", (NOW,))
        ok(d, 'L8 a migrated figure with no candidate: to_check without a key', "INSERT INTO item_provider_status VALUES(13,'bricklink','to_check','no_candidate',NULL,?)", (NOW,))
        refused(d, 'L8 item_link without an item', "INSERT INTO item_link(item_id,provider,provider_kind,provider_key,status,method,origin,decided_at) VALUES(NULL,'bricklink','P','2339','to_check','same_number','rule',?)", (NOW,))
        refused(d, "L8 item_link status 'unmatched'", "INSERT INTO item_link(item_id,provider,provider_kind,provider_key,status,method,origin,decided_at) VALUES(14,'bricklink','P','2339','unmatched','x','rule',?)", (NOW,))
        ok(d, 'L8 same_number candidate as to_check link', "INSERT INTO item_link(item_id,provider,provider_kind,provider_key,status,method,origin,decided_at) VALUES(14,'bricklink','P','2339','to_check','same_number','rule',?)", (NOW,))
        refused(d, 'L8 the same link twice (NULL colour scope coalesced)', "INSERT INTO item_link(item_id,provider,provider_kind,provider_key,status,method,origin,decided_at) VALUES(14,'bricklink','P','2339','to_check','same_number','rule',?)", (NOW,))
        refused(d, "L8 'manual' only from the user", "INSERT INTO item_link(item_id,provider,provider_kind,provider_key,status,method,origin,decided_at) VALUES(14,'bricklink','P','2339x','manual','manual','rule',?)", (NOW,))

        # --- kind changes (finding 6, Q10)
        ok(d, 'L9 an unreferenced theme-guessed item changes kind, same id', "UPDATE item SET kind='set', kind_source='bricklink' WHERE id=15")
        refused(d, 'L9 a set referenced by a copy cannot become gear', "UPDATE item SET kind='gear', kind_source='bricklink' WHERE id=10")
        d.execute("INSERT INTO stock(id,kind,item_id,quantity,created_at,updated_at) VALUES('g1','gear',16,1,?,?)", (NOW, NOW))
        refused(d, 'L9 gear held as stock cannot silently become a set', "UPDATE item SET kind='set', kind_source='bricklink' WHERE id=16")
        ok(d, "L9 ... reconcile records it instead (reason 'kind_differs')", "INSERT INTO item_provider_status VALUES(16,'bricklink','to_check','kind_differs','{\"bricklink_type\":\"S\"}',?)", (NOW,))
        refused(d, 'L9 UPDATE copy.item_id to a part', "UPDATE copy SET item_id=11 WHERE id='c5'")
        refused(d, 'L9 INSERT copy of a gear item', "INSERT INTO copy(id,item_id,inventory_source,inventory_version,inventory_digest,created_at,updated_at) VALUES('c9',16,'rebrickable',1,'d',?,?)", (NOW, NOW))
        refused(d, 'L9 UPDATE stock.kind away from the item kind', "UPDATE stock SET kind='book' WHERE id='g1'")
        refused(d, 'L9 INSERT wish with a kind that is not the item kind', "INSERT INTO wish(id,kind,item_id,added_at,updated_at) VALUES('w0','set',16,?,?)", (NOW, NOW))

        # --- preferred link per part and colour (decision E)
        ok(d, 'L10 preferred 970c11 for 970c03 in Red (colour-scoped row)', "INSERT INTO item_link(item_id,color_id,provider,provider_kind,provider_key,status,method,origin,preferred,decided_at) VALUES(12,3,'bricklink','P','970c11','matched','leg_rule','rule',1,?)", (NOW,))
        ok(d, 'L10 preferred 970c11 for 970c03 in any other colour', "INSERT INTO item_link(item_id,color_id,provider,provider_kind,provider_key,status,method,origin,preferred,decided_at) VALUES(12,NULL,'bricklink','P','970c11','matched','leg_rule','rule',1,?)", (NOW,))
        d.execute("UPDATE item_link SET preferred=1 WHERE item_id=12 AND color_id=4")
        refused(d, 'L10 a second preferred link for (970c03, bricklink, Black)', "INSERT INTO item_link(item_id,color_id,provider,provider_kind,provider_key,status,method,origin,preferred,decided_at) VALUES(12,4,'bricklink','P','970c88','manual','manual','user',1,?)", (NOW,))

        # --- wishes, events, jobs
        ok(d, 'L11 wish for a set (colour NULL)', "INSERT INTO wish(id,kind,item_id,added_at,updated_at) VALUES('w1','set',17,?,?)", (NOW, NOW))
        refused(d, 'L11 the same live wish again (NULL colour coalesced)', "INSERT INTO wish(id,kind,item_id,added_at,updated_at) VALUES('w2','set',17,?,?)", (NOW, NOW))
        refused(d, 'L12 events are append-only', "UPDATE event SET field='x' WHERE id=1")
        ok(d, "L13 step error 'unidentified' (G9)", "UPDATE job SET error_code='unidentified' WHERE id=1")
        refused(d, 'L13 unknown step error code', "UPDATE job SET error_code='bogus' WHERE id=1")
        refused(d, 'L14 a system flag cannot be archived', "INSERT INTO flag(id,name,kind,system,created_at,archived_at) VALUES('f','Set is checked','status',1,?,?)", (NOW, NOW))
        check('L15 collection foreign_key_check clean', d.execute('PRAGMA foreign_key_check').fetchall() == [])
        check('L15 collection integrity_check ok', d.execute('PRAGMA integrity_check').fetchone() == ('ok',))


def test_every_item_reference_has_both_guards():
    """A column that references item(id) needs its insert and update guard, so a merged item can never be named again."""
    exempt = {('item', 'merged_into')}
    with closing(load('brickwork.sql')) as db:
        db.row_factory = sqlite3.Row
        refs = []
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND sql NOT LIKE 'CREATE VIRTUAL%'"):
            for fk in db.execute(f'PRAGMA foreign_key_list({table})'):
                if fk['table'] == 'item' and fk['to'] == 'id' and (table, fk['from']) not in exempt \
                        and not table.startswith(('item_merge', 'item_redirect')):
                    refs.append((table, fk['from']))
        assert len(refs) >= 20, refs
        triggers = db.execute("SELECT name, tbl_name, sql FROM sqlite_master WHERE type='trigger'").fetchall()
        for table, column in refs:
            mine = [t for t in triggers if t['tbl_name'] == table]
            insert = [t for t in mine if t['name'].endswith('_guard_insert') and f'new.{column}' in t['sql']]
            update = [t for t in mine if t['name'].endswith('_guard_update') and f'new.{column}' in t['sql']
                      and column in t['sql'].split(' ON ')[0].split('UPDATE OF')[-1]]
            assert insert, f'{table}.{column} has no _guard_insert trigger'
            assert update, f'{table}.{column} has no _guard_update trigger'


# Foreign keys with no index that starts with their columns (M.8c, issue #110: the 3.3 test "every foreign key has an index" ported to the
# 4.0 collection file). Three are known gaps of the M.1 schema, listed so a fourth cannot appear unnoticed; reported to the schema's owner,
# not changed here.
UNINDEXED_FOREIGN_KEYS = {('item_provider_status', ('provider',)), ('copy_part', ('copy_id', 'copy_figure_id')), ('part_check', ('copy_id', 'copy_figure_id'))}


def test_every_collection_foreign_key_has_an_index_but_three_recorded(tmp_path):
    from contextlib import closing as closing_
    from brickwork.core.connect import connect
    found = set()
    with closing_(connect(tmp_path / 'new.db', require_catalogue=False)) as db:
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
            groups = {}
            for r in db.execute(f'PRAGMA foreign_key_list({table})'):
                groups.setdefault(r['id'], []).append(r['from'])
            indexes = [tuple(r['name'] for r in db.execute(f'PRAGMA index_info({i["name"]})')) for i in db.execute(f'PRAGMA index_list({table})')]
            primary = tuple(r['name'] for r in db.execute(f'PRAGMA table_info({table})') if r['pk'])
            for columns in groups.values():
                if not any(index[:len(columns)] == tuple(columns) for index in indexes + [primary]):
                    found.add((table, tuple(columns)))
    assert found == UNINDEXED_FOREIGN_KEYS
