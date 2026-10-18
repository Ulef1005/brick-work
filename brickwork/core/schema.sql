-- Version 3.2. Every connection must enable foreign_keys.
CREATE TABLE schema_meta(version TEXT PRIMARY KEY CHECK(version='3.2'));
INSERT INTO schema_meta VALUES('3.2');
CREATE TABLE sources(source TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('api','file','manual')), enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)), priority_settings TEXT);
CREATE TABLE source_freshness(source TEXT NOT NULL REFERENCES sources(source), kind TEXT NOT NULL,
 max_age_days INTEGER CHECK(max_age_days>=0), PRIMARY KEY(source,kind));
CREATE TABLE colors(color_id INTEGER PRIMARY KEY, name TEXT, type TEXT, rgb TEXT);
CREATE TABLE items(item_type TEXT NOT NULL CHECK(item_type IN ('S','M','P','I','O','G','B','C','?')),
 item_no TEXT NOT NULL, name TEXT, category TEXT, year INTEGER, updated_at TEXT, PRIMARY KEY(item_type,item_no));
CREATE TABLE storages(id TEXT PRIMARY KEY NOT NULL, name TEXT, archived_at TEXT);
CREATE TABLE purchase_locations(id TEXT PRIMARY KEY NOT NULL, name TEXT);
CREATE TABLE lots(id TEXT PRIMARY KEY NOT NULL, name TEXT, note TEXT, created_date TEXT,
 storage_id TEXT REFERENCES storages(id), purchase_location_id TEXT REFERENCES purchase_locations(id),
 purchase_date TEXT, purchase_price TEXT, purchase_currency TEXT, archived_at TEXT);
CREATE TABLE copies(id TEXT PRIMARY KEY NOT NULL, item_type TEXT NOT NULL DEFAULT 'S' CHECK(item_type IN ('S','?')),
 set_no TEXT NOT NULL, condition TEXT CHECK(condition IN ('N','U')),
 completeness TEXT CHECK(completeness IN ('S','C','I')), completeness_source TEXT CHECK(completeness_source IN ('manual','derived')),
 storage_id TEXT REFERENCES storages(id), purchase_location_id TEXT REFERENCES purchase_locations(id),
 purchase_date TEXT, purchase_price TEXT, purchase_currency TEXT, note TEXT,
 current_value TEXT, current_value_currency TEXT, pinned INTEGER NOT NULL DEFAULT 0 CHECK(pinned IN (0,1)),
 updated_at TEXT, archived_at TEXT, FOREIGN KEY(item_type,set_no) REFERENCES items(item_type,item_no));
CREATE TABLE copy_parts(id INTEGER PRIMARY KEY, copy_id TEXT NOT NULL REFERENCES copies(id),
 parent_minifig_type TEXT, parent_minifig TEXT, item_type TEXT NOT NULL, item_no TEXT NOT NULL,
 color_id INTEGER REFERENCES colors(color_id), spare INTEGER, quantity INTEGER, missing INTEGER, damaged INTEGER, checked INTEGER,
 element_id INTEGER, source_ref INTEGER,
 CHECK((parent_minifig_type IS NULL)=(parent_minifig IS NULL)),
 FOREIGN KEY(parent_minifig_type,parent_minifig) REFERENCES items(item_type,item_no),
 FOREIGN KEY(item_type,item_no) REFERENCES items(item_type,item_no));
CREATE TABLE copy_minifigs(copy_id TEXT NOT NULL REFERENCES copies(id), item_type TEXT NOT NULL, minifig_no TEXT NOT NULL,
 quantity INTEGER, missing INTEGER, updated_at TEXT, PRIMARY KEY(copy_id,item_type,minifig_no),
 FOREIGN KEY(item_type,minifig_no) REFERENCES items(item_type,item_no));
CREATE TABLE loose_stock(id TEXT PRIMARY KEY NOT NULL, item_type TEXT NOT NULL, item_no TEXT NOT NULL,
 color_id INTEGER REFERENCES colors(color_id), quantity INTEGER, condition TEXT CHECK(condition IN ('N','U','D')),
 storage_id TEXT REFERENCES storages(id), lot_id TEXT REFERENCES lots(id), purchase_location_id TEXT REFERENCES purchase_locations(id),
 purchase_date TEXT, purchase_price TEXT, purchase_currency TEXT, note TEXT, created_at TEXT, updated_at TEXT, archived_at TEXT,
 missing INTEGER, damaged INTEGER, checked INTEGER, FOREIGN KEY(item_type,item_no) REFERENCES items(item_type,item_no));
CREATE TABLE loose_minifig_parts(stock_id TEXT NOT NULL REFERENCES loose_stock(id), item_type TEXT NOT NULL, item_no TEXT NOT NULL,
 color_id INTEGER REFERENCES colors(color_id), spare INTEGER, quantity INTEGER, missing INTEGER, damaged INTEGER, checked INTEGER,
 element_id INTEGER, source_ref INTEGER, FOREIGN KEY(item_type,item_no) REFERENCES items(item_type,item_no));
CREATE UNIQUE INDEX loose_minifig_parts_key ON loose_minifig_parts(stock_id,item_type,item_no,color_id IS NULL,coalesce(color_id,0),spare IS NULL,coalesce(spare,0));
CREATE TABLE flags(id TEXT PRIMARY KEY NOT NULL, name TEXT, kind TEXT NOT NULL CHECK(kind IN ('status','tag','owner')),
 shown_on_grid INTEGER NOT NULL CHECK(shown_on_grid IN (0,1)));
CREATE TABLE item_flags(entity_type TEXT NOT NULL CHECK(entity_type IN ('copy','stock','wishlist')), entity_id TEXT NOT NULL,
 flag_id TEXT NOT NULL REFERENCES flags(id), PRIMARY KEY(entity_type,entity_id,flag_id));
CREATE TABLE wishlists(id TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL, note TEXT, sort INTEGER NOT NULL DEFAULT 0,
 archived_at TEXT, created_at TEXT, bricklink_id TEXT);
INSERT INTO wishlists(id,name,created_at) VALUES('default','Wishlist',strftime('%Y-%m-%dT%H:%M:%fZ','now'));
CREATE TABLE wishlist(id INTEGER PRIMARY KEY, item_type TEXT NOT NULL, item_no TEXT NOT NULL,
 color_id INTEGER REFERENCES colors(color_id), quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity >= 1), max_price TEXT,
 condition TEXT CHECK(condition IN ('new','used','any')), note TEXT, added_at TEXT, updated_at TEXT, archived_at TEXT,
 max_price_currency TEXT, list_id TEXT NOT NULL DEFAULT 'default' REFERENCES wishlists(id),
 CHECK(item_type!='P' OR color_id IS NOT NULL),
 CHECK(item_type NOT IN ('S','M','I','O','G','B','C') OR color_id IS NULL),
 FOREIGN KEY(item_type,item_no) REFERENCES items(item_type,item_no));
CREATE UNIQUE INDEX wishlist_live_key ON wishlist(list_id,item_type,item_no,color_id IS NULL,coalesce(color_id,0)) WHERE archived_at IS NULL;
CREATE INDEX wishlist_color_fk ON wishlist(color_id);
CREATE TABLE inventory_lines(id INTEGER PRIMARY KEY, parent_item_type TEXT NOT NULL, parent_item_no TEXT NOT NULL,
 child_item_type TEXT NOT NULL, child_item_no TEXT NOT NULL, color_id INTEGER REFERENCES colors(color_id),
 quantity INTEGER, extra_quantity INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL, fetched_at TEXT,
 FOREIGN KEY(parent_item_type,parent_item_no) REFERENCES items(item_type,item_no),
 FOREIGN KEY(child_item_type,child_item_no) REFERENCES items(item_type,item_no));
CREATE TABLE id_match(source TEXT NOT NULL REFERENCES sources(source), kind TEXT NOT NULL, source_id TEXT NOT NULL,
 item_type TEXT, item_no TEXT, color_id INTEGER REFERENCES colors(color_id), method TEXT, status TEXT NOT NULL
 CHECK(status IN ('matched','inferred','manual','to_check','unmatched')), context TEXT, evidence_json TEXT NOT NULL, decided_at TEXT,
 CHECK((item_type IS NULL)=(item_no IS NULL)), PRIMARY KEY(source,kind,source_id),
 FOREIGN KEY(item_type,item_no) REFERENCES items(item_type,item_no));
CREATE TABLE source_records(source TEXT NOT NULL REFERENCES sources(source), kind TEXT NOT NULL, source_id TEXT NOT NULL,
 payload TEXT NOT NULL, fetched_at TEXT, status TEXT NOT NULL, PRIMARY KEY(source,kind,source_id));
CREATE TABLE item_properties(item_type TEXT NOT NULL, item_no TEXT NOT NULL, key TEXT NOT NULL, source TEXT NOT NULL REFERENCES sources(source),
 value TEXT NOT NULL, unit TEXT, fetched_at TEXT, PRIMARY KEY(item_type,item_no,key,source),
 FOREIGN KEY(item_type,item_no) REFERENCES items(item_type,item_no));
CREATE TABLE item_images(id INTEGER PRIMARY KEY, item_type TEXT NOT NULL, item_no TEXT NOT NULL,
 color_id INTEGER REFERENCES colors(color_id), source TEXT NOT NULL REFERENCES sources(source),
 kind TEXT NOT NULL CHECK(kind IN ('photo','render','box','booklet','own')), local_path TEXT NOT NULL CHECK(
 (local_path LIKE 'data/images/%' AND instr(local_path,'..')=0)), url TEXT, width INTEGER, height INTEGER, fetched_at TEXT,
 copy_id TEXT REFERENCES copies(id), stock_id TEXT REFERENCES loose_stock(id), caption TEXT, taken_at TEXT,
 FOREIGN KEY(item_type,item_no) REFERENCES items(item_type,item_no));
CREATE TABLE price_observations(id INTEGER PRIMARY KEY, item_type TEXT NOT NULL, item_no TEXT NOT NULL,
 color_id INTEGER REFERENCES colors(color_id), condition TEXT CHECK(condition IN ('N','U')), guide TEXT NOT NULL
 CHECK(guide IN ('sold','stock','retail','manual','valuation')), slot TEXT, region TEXT, currency TEXT, price TEXT, qty INTEGER,
 sold INTEGER, min TEXT, max TEXT, source TEXT NOT NULL REFERENCES sources(source), observed_at TEXT, error TEXT,
 FOREIGN KEY(item_type,item_no) REFERENCES items(item_type,item_no));
CREATE TABLE price_current(item_type TEXT NOT NULL, item_no TEXT NOT NULL, color_id INTEGER REFERENCES colors(color_id),
 condition TEXT, guide TEXT NOT NULL, slot TEXT, region TEXT, currency TEXT,
 observation_id INTEGER NOT NULL REFERENCES price_observations(id), FOREIGN KEY(item_type,item_no) REFERENCES items(item_type,item_no));
CREATE UNIQUE INDEX price_current_key ON price_current(item_type,item_no,color_id IS NULL,coalesce(color_id,0),condition IS NULL,coalesce(condition,''),guide,slot IS NULL,coalesce(slot,''),region IS NULL,coalesce(region,''),currency IS NULL,coalesce(currency,''));
CREATE TABLE price_watch(item_type TEXT NOT NULL, item_no TEXT NOT NULL, color_id INTEGER REFERENCES colors(color_id), condition TEXT,
 origin TEXT, first_seen TEXT, last_fetch_at TEXT, last_error TEXT, last_error_at TEXT, last_attempt_at TEXT,
 FOREIGN KEY(item_type,item_no) REFERENCES items(item_type,item_no));
CREATE UNIQUE INDEX price_watch_key ON price_watch(item_type,item_no,color_id IS NULL,coalesce(color_id,0),condition IS NULL,coalesce(condition,''));
CREATE TABLE fetch_log(id INTEGER PRIMARY KEY, item_type TEXT, item_no TEXT, source TEXT, at TEXT, ok INTEGER, detail TEXT,
 FOREIGN KEY(item_type,item_no) REFERENCES items(item_type,item_no));
CREATE TABLE settings(key TEXT PRIMARY KEY NOT NULL, value TEXT);
CREATE TABLE identifications(id TEXT PRIMARY KEY NOT NULL, created_at TEXT, has_thumb INTEGER, candidates TEXT, missing_count INTEGER);
CREATE TABLE identification_actions(id INTEGER PRIMARY KEY, identification_id TEXT NOT NULL REFERENCES identifications(id),
 kind TEXT, at TEXT, item_type TEXT NOT NULL, part_num TEXT, color_id INTEGER REFERENCES colors(color_id), color_name TEXT,
 quantity INTEGER, set_type TEXT, set_num TEXT, copy_id TEXT REFERENCES copies(id), storage TEXT REFERENCES storages(id),
 FOREIGN KEY(item_type,part_num) REFERENCES items(item_type,item_no), FOREIGN KEY(set_type,set_num) REFERENCES items(item_type,item_no));
CREATE TABLE import_receipts(import_key TEXT PRIMARY KEY NOT NULL, individual_id TEXT NOT NULL REFERENCES loose_stock(id),
 item_type TEXT NOT NULL, figure TEXT, quantity INTEGER, created_at TEXT,
 FOREIGN KEY(item_type,figure) REFERENCES items(item_type,item_no));
CREATE TABLE events(id INTEGER PRIMARY KEY, entity TEXT NOT NULL, field TEXT NOT NULL, old_value TEXT, new_value TEXT,
 at TEXT NOT NULL, via TEXT NOT NULL CHECK(via IN ('app','cli','house-api','import','migration')));
CREATE TRIGGER events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'events are append-only'); END;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'events are append-only'); END;
CREATE TABLE jobs(id INTEGER PRIMARY KEY, source TEXT NOT NULL REFERENCES sources(source), kind TEXT NOT NULL,
 item_type TEXT, item_no TEXT, state TEXT NOT NULL CHECK(state IN ('queued','running','waiting_for_budget','failed','done')),
 payload TEXT, attempts INTEGER NOT NULL DEFAULT 0, budget_day TEXT, budget_used INTEGER NOT NULL DEFAULT 0,
 retry_at TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(item_type,item_no) REFERENCES items(item_type,item_no));
CREATE TABLE instruction_files(id INTEGER PRIMARY KEY, item_type TEXT NOT NULL DEFAULT 'S', set_no TEXT NOT NULL,
 path TEXT NOT NULL, label TEXT, added_at TEXT, FOREIGN KEY(item_type,set_no) REFERENCES items(item_type,item_no));
CREATE TABLE match_history(id INTEGER PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL,
 source_stock_id TEXT REFERENCES loose_stock(id), copy_id TEXT REFERENCES copies(id), quantity INTEGER,
 item_type TEXT, item_no TEXT, item_key TEXT, source_snapshot TEXT,
 FOREIGN KEY(item_type,item_no) REFERENCES items(item_type,item_no));
CREATE TABLE orders(id INTEGER PRIMARY KEY, bricklink_order_id TEXT UNIQUE, store TEXT, seller TEXT, date_ordered TEXT,
 status TEXT, cost TEXT, currency TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE order_documents(id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id), source TEXT,
 digest TEXT, label TEXT, phase TEXT, created_at TEXT, updated_at TEXT, UNIQUE(order_id,source,digest));
CREATE TABLE order_lines(id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
 document_id INTEGER NOT NULL REFERENCES order_documents(id), line_no INTEGER, source TEXT, condition TEXT,
 item_type TEXT, item_no TEXT, color_id INTEGER REFERENCES colors(color_id), colour_name TEXT, name TEXT, raw_text TEXT,
 remark TEXT, state TEXT, confirmed_via TEXT, qty INTEGER, unit_price TEXT, line_total TEXT,
 sticker_set_type TEXT, sticker_set_no TEXT, set_type TEXT, set_no TEXT, batch INTEGER, submitted TEXT, suggestions_json TEXT,
 paired_line_id INTEGER REFERENCES order_lines(id), updated_at TEXT, UNIQUE(document_id,line_no),
 FOREIGN KEY(item_type,item_no) REFERENCES items(item_type,item_no),
 FOREIGN KEY(sticker_set_type,sticker_set_no) REFERENCES items(item_type,item_no), FOREIGN KEY(set_type,set_no) REFERENCES items(item_type,item_no));
CREATE TABLE line_receipts(line_id INTEGER PRIMARY KEY REFERENCES order_lines(id), received INTEGER, updated_at TEXT);
CREATE TABLE line_receipt_log(id INTEGER PRIMARY KEY, line_id INTEGER NOT NULL REFERENCES order_lines(id), at TEXT, old INTEGER, new INTEGER);
CREATE TABLE allocations(id INTEGER PRIMARY KEY, confirm_id TEXT, order_id INTEGER REFERENCES orders(id),
 line_id INTEGER REFERENCES order_lines(id), kind TEXT, copy_id TEXT REFERENCES copies(id), part_type TEXT, part TEXT,
 color INTEGER REFERENCES colors(color_id), figure_type TEXT, figure TEXT, spare INTEGER, qty INTEGER, state TEXT,
 intent_before INTEGER, intent_after INTEGER, ref TEXT, snapshot TEXT, hold_reason TEXT, error TEXT, created_at TEXT,
 applied_at TEXT, undone_at TEXT, target_type TEXT CHECK(target_type IN ('copy','stock')), target_copy_id TEXT REFERENCES copies(id),
 target_stock_id TEXT REFERENCES loose_stock(id), FOREIGN KEY(part_type,part) REFERENCES items(item_type,item_no),
 FOREIGN KEY(figure_type,figure) REFERENCES items(item_type,item_no));
CREATE INDEX source_freshness_fk0 ON source_freshness(source);
CREATE INDEX lots_fk0 ON lots(purchase_location_id);
CREATE INDEX lots_fk1 ON lots(storage_id);
CREATE INDEX copies_fk0 ON copies(item_type,set_no);
CREATE INDEX copies_fk1 ON copies(purchase_location_id);
CREATE INDEX copies_fk2 ON copies(storage_id);
CREATE INDEX copy_parts_fk0 ON copy_parts(item_type,item_no);
CREATE INDEX copy_parts_fk1 ON copy_parts(parent_minifig_type,parent_minifig);
CREATE INDEX copy_parts_fk2 ON copy_parts(color_id);
CREATE INDEX copy_parts_fk3 ON copy_parts(copy_id);
CREATE INDEX copy_minifigs_fk0 ON copy_minifigs(item_type,minifig_no);
CREATE INDEX copy_minifigs_fk1 ON copy_minifigs(copy_id);
CREATE INDEX loose_stock_fk0 ON loose_stock(item_type,item_no);
CREATE INDEX loose_stock_fk1 ON loose_stock(purchase_location_id);
CREATE INDEX loose_stock_fk2 ON loose_stock(lot_id);
CREATE INDEX loose_stock_fk3 ON loose_stock(storage_id);
CREATE INDEX loose_stock_fk4 ON loose_stock(color_id);
CREATE INDEX loose_minifig_parts_fk0 ON loose_minifig_parts(item_type,item_no);
CREATE INDEX loose_minifig_parts_fk1 ON loose_minifig_parts(color_id);
CREATE INDEX loose_minifig_parts_fk2 ON loose_minifig_parts(stock_id);
CREATE INDEX item_flags_fk0 ON item_flags(flag_id);
CREATE INDEX wishlist_fk0 ON wishlist(item_type,item_no);
CREATE INDEX inventory_lines_fk0 ON inventory_lines(child_item_type,child_item_no);
CREATE INDEX inventory_lines_fk1 ON inventory_lines(parent_item_type,parent_item_no);
CREATE INDEX inventory_lines_fk2 ON inventory_lines(color_id);
CREATE INDEX id_match_fk0 ON id_match(item_type,item_no);
CREATE INDEX id_match_fk1 ON id_match(color_id);
CREATE INDEX id_match_fk2 ON id_match(source);
CREATE INDEX source_records_fk0 ON source_records(source);
CREATE INDEX item_properties_fk0 ON item_properties(item_type,item_no);
CREATE INDEX item_properties_fk1 ON item_properties(source);
CREATE INDEX item_images_fk0 ON item_images(item_type,item_no);
CREATE INDEX item_images_fk1 ON item_images(stock_id);
CREATE INDEX item_images_fk2 ON item_images(copy_id);
CREATE INDEX item_images_fk3 ON item_images(source);
CREATE INDEX item_images_fk4 ON item_images(color_id);
CREATE INDEX price_observations_fk0 ON price_observations(item_type,item_no);
CREATE INDEX price_observations_fk1 ON price_observations(source);
CREATE INDEX price_observations_fk2 ON price_observations(color_id);
CREATE INDEX price_current_fk0 ON price_current(item_type,item_no);
CREATE INDEX price_current_fk1 ON price_current(observation_id);
CREATE INDEX price_current_fk2 ON price_current(color_id);
CREATE INDEX price_watch_fk0 ON price_watch(item_type,item_no);
CREATE INDEX price_watch_fk1 ON price_watch(color_id);
CREATE INDEX fetch_log_fk0 ON fetch_log(item_type,item_no);
CREATE INDEX identification_actions_fk0 ON identification_actions(set_type,set_num);
CREATE INDEX identification_actions_fk1 ON identification_actions(item_type,part_num);
CREATE INDEX identification_actions_fk2 ON identification_actions(storage);
CREATE INDEX identification_actions_fk3 ON identification_actions(copy_id);
CREATE INDEX identification_actions_fk4 ON identification_actions(color_id);
CREATE INDEX identification_actions_fk5 ON identification_actions(identification_id);
CREATE INDEX import_receipts_fk0 ON import_receipts(item_type,figure);
CREATE INDEX import_receipts_fk1 ON import_receipts(individual_id);
CREATE INDEX jobs_fk0 ON jobs(item_type,item_no);
CREATE INDEX jobs_fk1 ON jobs(source);
CREATE INDEX instruction_files_fk0 ON instruction_files(item_type,set_no);
CREATE INDEX match_history_fk0 ON match_history(item_type,item_no);
CREATE INDEX match_history_fk1 ON match_history(copy_id);
CREATE INDEX match_history_fk2 ON match_history(source_stock_id);
CREATE INDEX order_documents_fk0 ON order_documents(order_id);
CREATE INDEX order_lines_fk0 ON order_lines(set_type,set_no);
CREATE INDEX order_lines_fk1 ON order_lines(sticker_set_type,sticker_set_no);
CREATE INDEX order_lines_fk2 ON order_lines(item_type,item_no);
CREATE INDEX order_lines_fk3 ON order_lines(paired_line_id);
CREATE INDEX order_lines_fk4 ON order_lines(color_id);
CREATE INDEX order_lines_fk5 ON order_lines(document_id);
CREATE INDEX order_lines_fk6 ON order_lines(order_id);
CREATE INDEX line_receipts_fk0 ON line_receipts(line_id);
CREATE INDEX line_receipt_log_fk0 ON line_receipt_log(line_id);
CREATE INDEX allocations_fk0 ON allocations(figure_type,figure);
CREATE INDEX allocations_fk1 ON allocations(part_type,part);
CREATE INDEX allocations_fk2 ON allocations(target_stock_id);
CREATE INDEX allocations_fk3 ON allocations(target_copy_id);
CREATE INDEX allocations_fk4 ON allocations(color);
CREATE INDEX allocations_fk5 ON allocations(copy_id);
CREATE INDEX allocations_fk6 ON allocations(line_id);
CREATE INDEX allocations_fk7 ON allocations(order_id);
CREATE INDEX events_entity_at ON events(entity,at);
CREATE INDEX jobs_state_retry ON jobs(state,retry_at);
CREATE VIRTUAL TABLE search_index USING fts5(item_type UNINDEXED,item_no,name,properties, tokenize="unicode61");
CREATE TRIGGER search_items_insert AFTER INSERT ON items BEGIN
DELETE FROM search_index WHERE item_type=new.item_type AND item_no=new.item_no;
INSERT INTO search_index(item_type,item_no,name,properties)
SELECT i.item_type,i.item_no,i.name,(SELECT group_concat(value,' ') FROM
 (SELECT value FROM item_properties WHERE item_type=i.item_type AND item_no=i.item_no ORDER BY key,source))
FROM items i WHERE i.item_type=new.item_type AND item_no=new.item_no;
END;
CREATE TRIGGER search_items_update AFTER UPDATE ON items BEGIN
DELETE FROM search_index WHERE item_type=old.item_type AND item_no=old.item_no;
INSERT INTO search_index(item_type,item_no,name,properties)
SELECT i.item_type,i.item_no,i.name,(SELECT group_concat(value,' ') FROM
 (SELECT value FROM item_properties WHERE item_type=i.item_type AND item_no=i.item_no ORDER BY key,source))
FROM items i WHERE i.item_type=old.item_type AND item_no=old.item_no;
DELETE FROM search_index WHERE item_type=new.item_type AND item_no=new.item_no;
INSERT INTO search_index(item_type,item_no,name,properties)
SELECT i.item_type,i.item_no,i.name,(SELECT group_concat(value,' ') FROM
 (SELECT value FROM item_properties WHERE item_type=i.item_type AND item_no=i.item_no ORDER BY key,source))
FROM items i WHERE i.item_type=new.item_type AND item_no=new.item_no;
END;
CREATE TRIGGER search_items_delete AFTER DELETE ON items BEGIN
DELETE FROM search_index WHERE item_type=old.item_type AND item_no=old.item_no;
INSERT INTO search_index(item_type,item_no,name,properties)
SELECT i.item_type,i.item_no,i.name,(SELECT group_concat(value,' ') FROM
 (SELECT value FROM item_properties WHERE item_type=i.item_type AND item_no=i.item_no ORDER BY key,source))
FROM items i WHERE i.item_type=old.item_type AND item_no=old.item_no;
END;
CREATE TRIGGER search_item_properties_insert AFTER INSERT ON item_properties BEGIN
DELETE FROM search_index WHERE item_type=new.item_type AND item_no=new.item_no;
INSERT INTO search_index(item_type,item_no,name,properties)
SELECT i.item_type,i.item_no,i.name,(SELECT group_concat(value,' ') FROM
 (SELECT value FROM item_properties WHERE item_type=i.item_type AND item_no=i.item_no ORDER BY key,source))
FROM items i WHERE i.item_type=new.item_type AND item_no=new.item_no;
END;
CREATE TRIGGER search_item_properties_update AFTER UPDATE ON item_properties BEGIN
DELETE FROM search_index WHERE item_type=old.item_type AND item_no=old.item_no;
INSERT INTO search_index(item_type,item_no,name,properties)
SELECT i.item_type,i.item_no,i.name,(SELECT group_concat(value,' ') FROM
 (SELECT value FROM item_properties WHERE item_type=i.item_type AND item_no=i.item_no ORDER BY key,source))
FROM items i WHERE i.item_type=old.item_type AND item_no=old.item_no;
DELETE FROM search_index WHERE item_type=new.item_type AND item_no=new.item_no;
INSERT INTO search_index(item_type,item_no,name,properties)
SELECT i.item_type,i.item_no,i.name,(SELECT group_concat(value,' ') FROM
 (SELECT value FROM item_properties WHERE item_type=i.item_type AND item_no=i.item_no ORDER BY key,source))
FROM items i WHERE i.item_type=new.item_type AND item_no=new.item_no;
END;
CREATE TRIGGER search_item_properties_delete AFTER DELETE ON item_properties BEGIN
DELETE FROM search_index WHERE item_type=old.item_type AND item_no=old.item_no;
INSERT INTO search_index(item_type,item_no,name,properties)
SELECT i.item_type,i.item_no,i.name,(SELECT group_concat(value,' ') FROM
 (SELECT value FROM item_properties WHERE item_type=i.item_type AND item_no=i.item_no ORDER BY key,source))
FROM items i WHERE i.item_type=old.item_type AND item_no=old.item_no;
END;

-- Even INSERT OR REPLACE cannot rewrite an audit id when recursive_triggers
-- is off (SQLite normally suppresses its implicit DELETE trigger).
CREATE TRIGGER events_no_replace BEFORE INSERT ON events
WHEN EXISTS(SELECT 1 FROM events WHERE id=new.id)
BEGIN SELECT RAISE(ABORT,'events are append-only'); END;
INSERT INTO sources(source,name,kind,enabled,priority_settings) VALUES('bricklink','BrickLink','api',1,NULL);
INSERT INTO source_freshness VALUES('bricklink','prices',30);
INSERT INTO source_freshness VALUES('bricklink','metadata',365);
INSERT INTO source_freshness VALUES('bricklink','pictures',NULL);
INSERT INTO sources(source,name,kind,enabled,priority_settings) VALUES('rebrickable','Rebrickable','api',1,NULL);
INSERT INTO source_freshness VALUES('rebrickable','prices',30);
INSERT INTO source_freshness VALUES('rebrickable','metadata',365);
INSERT INTO source_freshness VALUES('rebrickable','pictures',NULL);
INSERT INTO sources(source,name,kind,enabled,priority_settings) VALUES('brickset','Brickset','api',1,NULL);
INSERT INTO source_freshness VALUES('brickset','prices',30);
INSERT INTO source_freshness VALUES('brickset','metadata',365);
INSERT INTO source_freshness VALUES('brickset','pictures',NULL);
INSERT INTO sources(source,name,kind,enabled,priority_settings) VALUES('brickognize','Brickognize','api',1,NULL);
INSERT INTO source_freshness VALUES('brickognize','prices',30);
INSERT INTO source_freshness VALUES('brickognize','metadata',365);
INSERT INTO source_freshness VALUES('brickognize','pictures',NULL);
INSERT INTO sources(source,name,kind,enabled,priority_settings) VALUES('peeron','Peeron','file',1,NULL);
INSERT INTO source_freshness VALUES('peeron','prices',30);
INSERT INTO source_freshness VALUES('peeron','metadata',365);
INSERT INTO source_freshness VALUES('peeron','pictures',NULL);
INSERT INTO sources(source,name,kind,enabled,priority_settings) VALUES('manual','Manual','manual',1,NULL);
INSERT INTO source_freshness VALUES('manual','prices',30);
INSERT INTO source_freshness VALUES('manual','metadata',365);
INSERT INTO source_freshness VALUES('manual','pictures',NULL);
-- Polymorphic flag assertions use explicit entity types. Validate each branch
-- without interpreting a copy/stock UUID as a wishlist row id.
CREATE TRIGGER item_flags_copy_insert BEFORE INSERT ON item_flags
WHEN new.entity_type='copy' AND NOT EXISTS(SELECT 1 FROM copies WHERE id=new.entity_id)
BEGIN SELECT RAISE(ABORT,'orphan copy flag'); END;
CREATE TRIGGER item_flags_copy_update BEFORE UPDATE ON item_flags
WHEN new.entity_type='copy' AND NOT EXISTS(SELECT 1 FROM copies WHERE id=new.entity_id)
BEGIN SELECT RAISE(ABORT,'orphan copy flag'); END;
CREATE TRIGGER item_flags_stock_insert BEFORE INSERT ON item_flags
WHEN new.entity_type='stock' AND NOT EXISTS(SELECT 1 FROM loose_stock WHERE id=new.entity_id)
BEGIN SELECT RAISE(ABORT,'orphan stock flag'); END;
CREATE TRIGGER item_flags_stock_update BEFORE UPDATE ON item_flags
WHEN new.entity_type='stock' AND NOT EXISTS(SELECT 1 FROM loose_stock WHERE id=new.entity_id)
BEGIN SELECT RAISE(ABORT,'orphan stock flag'); END;
CREATE TRIGGER item_flags_wishlist_insert BEFORE INSERT ON item_flags
WHEN new.entity_type='wishlist' AND NOT EXISTS(SELECT 1 FROM wishlist WHERE CAST(id AS TEXT)=new.entity_id)
BEGIN SELECT RAISE(ABORT,'orphan wishlist flag'); END;
CREATE TRIGGER item_flags_wishlist_update BEFORE UPDATE ON item_flags
WHEN new.entity_type='wishlist' AND NOT EXISTS(SELECT 1 FROM wishlist WHERE CAST(id AS TEXT)=new.entity_id)
BEGIN SELECT RAISE(ABORT,'orphan wishlist flag'); END;
CREATE TRIGGER copies_flags_restrict BEFORE DELETE ON copies
WHEN EXISTS(SELECT 1 FROM item_flags WHERE entity_type='copy' AND entity_id=old.id)
BEGIN SELECT RAISE(ABORT,'copy still has flags'); END;
CREATE TRIGGER stocks_flags_restrict BEFORE DELETE ON loose_stock
WHEN EXISTS(SELECT 1 FROM item_flags WHERE entity_type='stock' AND entity_id=old.id)
BEGIN SELECT RAISE(ABORT,'stock still has flags'); END;
CREATE TRIGGER wishes_flags_restrict BEFORE DELETE ON wishlist
WHEN EXISTS(SELECT 1 FROM item_flags WHERE entity_type='wishlist' AND entity_id=CAST(old.id AS TEXT))
BEGIN SELECT RAISE(ABORT,'wishlist item still has flags'); END;
CREATE TRIGGER copies_flags_key_restrict BEFORE UPDATE OF id ON copies
WHEN new.id IS NOT old.id AND EXISTS(SELECT 1 FROM item_flags WHERE entity_type='copy' AND entity_id=old.id)
BEGIN SELECT RAISE(ABORT,'copy still has flags'); END;
CREATE TRIGGER stocks_flags_key_restrict BEFORE UPDATE OF id ON loose_stock
WHEN new.id IS NOT old.id AND EXISTS(SELECT 1 FROM item_flags WHERE entity_type='stock' AND entity_id=old.id)
BEGIN SELECT RAISE(ABORT,'stock still has flags'); END;
CREATE TRIGGER wishes_flags_key_restrict BEFORE UPDATE OF id,item_type,item_no,color_id ON wishlist
WHEN (new.id IS NOT old.id OR new.item_type IS NOT old.item_type OR new.item_no IS NOT old.item_no OR new.color_id IS NOT old.color_id)
AND EXISTS(SELECT 1 FROM item_flags WHERE entity_type='wishlist' AND entity_id=CAST(old.id AS TEXT))
BEGIN SELECT RAISE(ABORT,'wishlist item still has flags'); END;
