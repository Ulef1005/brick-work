-- =====================================================================
-- FILE 2: brickwork.db
-- The collection, the user's identity decisions, acquired data (API-fetched and BrickLink part
-- lists, local items) and the operational state. PRAGMA journal_mode=WAL; foreign_keys=ON.
-- =====================================================================

CREATE TABLE meta(key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL) STRICT;
-- keys: schema_version='4.0'; install_id; catalogue_id (bound at the first build; connect()
-- refuses a catalogue whose catalogue_id differs); catalogue_item_high_water and
-- catalogue_color_high_water (copied at every activation: a rebuild from scratch mints above
-- them); migrated_from (3.3 file name, sha256, migration report digest) after the migration.

CREATE TABLE catalogue_build(                         -- builds this collection has activated (id = catalogue build.id)
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL, mapping_version TEXT,
 activated_at TEXT NOT NULL, reconciled_at TEXT, counts_json TEXT NOT NULL) STRICT;

-- ---------- Identity ----------

CREATE TABLE item(
 id INTEGER PRIMARY KEY CHECK(id>0),
 origin TEXT NOT NULL CHECK(origin IN ('catalogue','local')),
 kind TEXT NOT NULL CHECK(kind IN ('set','part','minifigure','instructions','box','gear','book','catalog')),
 kind_source TEXT NOT NULL CHECK(kind_source IN ('namespace','theme','bricklink','manual')),
 name TEXT NOT NULL, year INTEGER, num_parts INTEGER,
 theme_name TEXT, category_name TEXT, size_key TEXT,  -- projected for the grid and largest-first order (review 14)
 born_provider TEXT CHECK(born_provider IS NULL OR born_provider IN ('rebrickable','bricklink')),
 born_namespace TEXT,                                 -- 'sets'/'parts'/'minifigs' (Rebrickable) or the BrickLink type
 born_key TEXT,                                       -- NULL only for an unidentified item
 catalogue_build_id INTEGER REFERENCES catalogue_build(id),
 digest TEXT,                                         -- the catalogue row digest when last projected
 catalogue_retired_at TEXT,                           -- mirrored by reconcile
 merged_into INTEGER REFERENCES item(id),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 CHECK(origin='catalogue' OR id>=1000000000),         -- local ids never collide with catalogue running numbers
 CHECK(origin='local' OR (born_provider='rebrickable' AND born_key IS NOT NULL)),
 CHECK((born_provider IS NULL) = (born_key IS NULL) AND (born_key IS NULL) = (born_namespace IS NULL)),
 CHECK(merged_into IS NULL OR merged_into!=id)) STRICT;
CREATE UNIQUE INDEX item_born ON item(born_provider, born_namespace, born_key);   -- NULLs (unidentified) are distinct
CREATE INDEX item_kind ON item(kind);
CREATE INDEX item_merged ON item(merged_into);
CREATE INDEX item_catalogue_build ON item(catalogue_build_id);

CREATE TABLE color(                                   -- every catalogue colour is projected; local colours are BrickLink-only
 id INTEGER PRIMARY KEY CHECK(id>0),
 origin TEXT NOT NULL CHECK(origin IN ('catalogue','local')),
 name TEXT NOT NULL, rgb TEXT, is_trans INTEGER NOT NULL CHECK(is_trans IN (0,1)),
 born_provider TEXT NOT NULL CHECK(born_provider IN ('rebrickable','bricklink')), born_key TEXT NOT NULL,
 digest TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 CHECK(origin='catalogue' OR id>=1000000000),
 CHECK((born_provider='rebrickable' AND born_key='9999') = (id=1)),
 CHECK((born_provider='rebrickable' AND born_key='-1') = (id=2))) STRICT;
CREATE UNIQUE INDEX color_born ON color(born_provider, born_key);
INSERT INTO color(id,origin,name,rgb,is_trans,born_provider,born_key,created_at,updated_at) VALUES
 (1,'catalogue','[No Color/Any Color]','05131D',0,'rebrickable','9999',strftime('%Y-%m-%dT%H:%M:%fZ','now'),strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 (2,'catalogue','[Unknown]','0033B2',0,'rebrickable','-1',strftime('%Y-%m-%dT%H:%M:%fZ','now'),strftime('%Y-%m-%dT%H:%M:%fZ','now'));

-- The collection's own links: seeded from the catalogue at projection, then owned here.
-- manual never changes automatically; matched is never downgraded automatically.
CREATE TABLE item_link(
 id INTEGER PRIMARY KEY,
 item_id INTEGER NOT NULL REFERENCES item(id),
 color_id INTEGER REFERENCES color(id),               -- NULL: every colour; set: this colour only
 color_key INTEGER GENERATED ALWAYS AS (coalesce(color_id,0)) VIRTUAL,
 provider TEXT NOT NULL REFERENCES source(id), provider_kind TEXT NOT NULL, provider_key TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('matched','inferred','manual','to_check')),
 method TEXT NOT NULL,
 origin TEXT NOT NULL CHECK(origin IN ('shipped','local','rule','bricklink_list','api','user','migration')),
 preferred INTEGER NOT NULL DEFAULT 0 CHECK(preferred IN (0,1)),   -- decision E: per item, provider and colour
 evidence_digest TEXT, evidence_json TEXT,
 catalogue_build_id INTEGER REFERENCES catalogue_build(id),
 decided_at TEXT NOT NULL, decided_by TEXT,
 CHECK(status!='manual' OR origin='user')) STRICT;
CREATE UNIQUE INDEX item_link_key ON item_link(provider, provider_kind, provider_key, item_id, color_key);
CREATE UNIQUE INDEX item_link_preferred ON item_link(item_id, provider, color_key) WHERE preferred=1;
CREATE INDEX item_link_item ON item_link(item_id);
CREATE INDEX item_link_number ON item_link(provider, provider_key);              -- Add search by a hand-linked number
CREATE INDEX item_link_to_check ON item_link(status) WHERE status='to_check';
CREATE INDEX item_link_color ON item_link(color_id);
CREATE INDEX item_link_catalogue_build ON item_link(catalogue_build_id);

-- What is known about an item at a provider when there is no key to link (review finding 5):
-- "looked, nothing found", "to check, no candidate", "catalogue and BrickLink disagree on the kind".
CREATE TABLE item_provider_status(
 item_id INTEGER NOT NULL REFERENCES item(id),
 provider TEXT NOT NULL REFERENCES source(id),
 status TEXT NOT NULL CHECK(status IN ('unmatched','to_check')),
 reason TEXT NOT NULL CHECK(reason IN ('no_match','no_candidate','kind_differs','migration')),
 evidence_json TEXT, checked_at TEXT NOT NULL,
 PRIMARY KEY(item_id, provider, reason)) STRICT;
CREATE INDEX item_provider_status_status ON item_provider_status(status);

CREATE TABLE color_link(
 id INTEGER PRIMARY KEY,
 color_id INTEGER NOT NULL REFERENCES color(id),
 provider TEXT NOT NULL REFERENCES source(id), provider_key TEXT NOT NULL, provider_name TEXT,
 status TEXT NOT NULL CHECK(status IN ('matched','inferred','manual','to_check')),
 method TEXT NOT NULL, inverse_preferred INTEGER NOT NULL DEFAULT 0 CHECK(inverse_preferred IN (0,1)),
 catalogue_build_id INTEGER REFERENCES catalogue_build(id), decided_at TEXT NOT NULL, decided_by TEXT) STRICT;
CREATE UNIQUE INDEX color_link_key ON color_link(provider, provider_key, color_id);
CREATE UNIQUE INDEX color_link_inverse ON color_link(provider, provider_key) WHERE inverse_preferred=1;
CREATE INDEX color_link_color ON color_link(color_id);
CREATE INDEX color_link_catalogue_build ON color_link(catalogue_build_id);

-- Audited merge (design § 3.4). Only a local item, or a catalogue item the catalogue has retired,
-- can be the merged one: no live catalogue row ever names a merged id (review finding 4).
CREATE TABLE item_merge(
 id INTEGER PRIMARY KEY,
 survivor_id INTEGER NOT NULL REFERENCES item(id), merged_id INTEGER NOT NULL REFERENCES item(id),
 at TEXT NOT NULL, via TEXT NOT NULL, actor TEXT,
 event_id INTEGER NOT NULL REFERENCES event(id),
 receipt_json TEXT NOT NULL, undone_at TEXT, undo_event_id INTEGER REFERENCES event(id),
 CHECK(survivor_id!=merged_id)) STRICT;
CREATE INDEX item_merge_survivor ON item_merge(survivor_id);
CREATE INDEX item_merge_merged ON item_merge(merged_id);
CREATE INDEX item_merge_event ON item_merge(event_id);
CREATE INDEX item_merge_undo_event ON item_merge(undo_event_id);
CREATE TABLE item_redirect(old_id INTEGER PRIMARY KEY NOT NULL REFERENCES item(id), new_id INTEGER NOT NULL REFERENCES item(id)) STRICT;
CREATE INDEX item_redirect_new ON item_redirect(new_id);

-- Per-set part-list preference (decision 6, Q13, Q23). Absent: the global setting
-- 'prefer_bricklink_inventory' decides, else the latest Rebrickable version.
CREATE TABLE set_preference(
 item_id INTEGER PRIMARY KEY NOT NULL REFERENCES item(id),
 inventory_source TEXT NOT NULL CHECK(inventory_source IN ('rebrickable','bricklink')),
 inventory_version INTEGER,                           -- a pinned Rebrickable version; NULL = the latest
 decided_at TEXT NOT NULL,
 CHECK(inventory_source='rebrickable' OR inventory_version IS NULL)) STRICT;
                                                      -- 'bricklink' needs no fetched list yet (review finding 7)

-- ---------- Acquired part lists (review finding 2: kept out of the rebuildable catalogue) ----------

-- A part list fetched for one set or figure: BrickLink subsets (decision 6) or the Rebrickable API
-- for an item newer than the catalogue (decision 2). Every fetch is a new row with the next seq;
-- older rows stay, because copies were built from them.
CREATE TABLE fetched_inventory(
 id INTEGER PRIMARY KEY,
 item_id INTEGER NOT NULL REFERENCES item(id),
 source TEXT NOT NULL CHECK(source IN ('bricklink','rebrickable_api')),
 seq INTEGER NOT NULL CHECK(seq>0),
 is_latest INTEGER NOT NULL CHECK(is_latest IN (0,1)),
 provider_version INTEGER,                            -- Rebrickable's version when the reply names it
 job_id INTEGER REFERENCES job(id), source_record_id INTEGER REFERENCES source_record(id),
 fetched_at TEXT NOT NULL,
 digest TEXT NOT NULL, part_lines INTEGER NOT NULL, figure_lines INTEGER NOT NULL,
 UNIQUE(item_id, source, seq), UNIQUE(item_id, id)) STRICT;
CREATE UNIQUE INDEX fetched_inventory_latest ON fetched_inventory(item_id, source) WHERE is_latest=1;
CREATE INDEX fetched_inventory_job ON fetched_inventory(job_id);
CREATE INDEX fetched_inventory_record ON fetched_inventory(source_record_id);

CREATE TABLE fetched_inventory_part(
 fetched_inventory_id INTEGER NOT NULL REFERENCES fetched_inventory(id),
 item_id INTEGER NOT NULL REFERENCES item(id),
 color_id INTEGER NOT NULL REFERENCES color(id),
 is_spare INTEGER NOT NULL CHECK(is_spare IN (0,1)),
 quantity INTEGER NOT NULL CHECK(quantity>0),         -- BrickLink: required = quantity - extra_quantity, spare = extra_quantity
 PRIMARY KEY(fetched_inventory_id, item_id, color_id, is_spare)) STRICT, WITHOUT ROWID;
CREATE INDEX fetched_inventory_part_item ON fetched_inventory_part(item_id, color_id);
CREATE INDEX fetched_inventory_part_color ON fetched_inventory_part(color_id);

CREATE TABLE fetched_inventory_figure(
 fetched_inventory_id INTEGER NOT NULL REFERENCES fetched_inventory(id),
 item_id INTEGER NOT NULL REFERENCES item(id),
 quantity INTEGER NOT NULL CHECK(quantity>0),
 PRIMARY KEY(fetched_inventory_id, item_id)) STRICT, WITHOUT ROWID;
CREATE INDEX fetched_inventory_figure_item ON fetched_inventory_figure(item_id);

-- ---------- Reference data per item ----------

CREATE TABLE item_property(                          -- fetched metadata (Brickset, BrickLink names)
 item_id INTEGER NOT NULL REFERENCES item(id), key TEXT NOT NULL, source TEXT NOT NULL REFERENCES source(id),
 value TEXT NOT NULL, unit TEXT, fetched_at TEXT,
 PRIMARY KEY(item_id, key, source)) STRICT;
CREATE INDEX item_property_source ON item_property(source);

CREATE TABLE picture(                                -- cached provider pictures: a cache
 id INTEGER PRIMARY KEY,
 item_id INTEGER NOT NULL REFERENCES item(id), color_id INTEGER REFERENCES color(id),
 color_key INTEGER GENERATED ALWAYS AS (coalesce(color_id,0)) VIRTUAL,
 source TEXT NOT NULL REFERENCES source(id),
 kind TEXT NOT NULL CHECK(kind IN ('photo','render','box','booklet')),
 local_path TEXT NOT NULL CHECK(local_path LIKE 'data/images/%' AND instr(local_path,'..')=0),
 url TEXT, width INTEGER, height INTEGER, fetched_at TEXT NOT NULL) STRICT;
CREATE UNIQUE INDEX picture_key ON picture(item_id, color_key, source, kind);
CREATE INDEX picture_color ON picture(color_id);
CREATE INDEX picture_source ON picture(source);

CREATE TABLE photo(                                  -- the user's own photos: user data
 id TEXT PRIMARY KEY NOT NULL,
 item_id INTEGER NOT NULL REFERENCES item(id), color_id INTEGER REFERENCES color(id),
 copy_id TEXT REFERENCES copy(id), stock_id TEXT REFERENCES stock(id),
 local_path TEXT NOT NULL CHECK(local_path LIKE 'data/images/own/%' AND instr(local_path,'..')=0),
 width INTEGER, height INTEGER, caption TEXT, taken_at TEXT,
 created_at TEXT NOT NULL, archived_at TEXT,
 CHECK(copy_id IS NULL OR stock_id IS NULL)) STRICT;
CREATE INDEX photo_item ON photo(item_id);
CREATE INDEX photo_copy ON photo(copy_id);
CREATE INDEX photo_stock ON photo(stock_id);
CREATE INDEX photo_color ON photo(color_id);

CREATE TABLE instruction_file(
 id INTEGER PRIMARY KEY,
 item_id INTEGER NOT NULL REFERENCES item(id),
 path TEXT NOT NULL CHECK(path LIKE 'data/instructions/%' AND instr(path,'..')=0),
 label TEXT NOT NULL, added_at TEXT NOT NULL, archived_at TEXT) STRICT;
CREATE INDEX instruction_file_item ON instruction_file(item_id);

-- ---------- Collection ----------

CREATE TABLE storage(
 id TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL,
 type TEXT CHECK(type IS NULL OR type IN ('Box','Shelf','Drawer','Bin','Bag','Case','Cabinet','Room','Other')),
 parent_id TEXT REFERENCES storage(id), note TEXT,
 created_at TEXT NOT NULL, archived_at TEXT) STRICT;
CREATE INDEX storage_parent ON storage(parent_id);

CREATE TABLE place(
 id TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL,
 kind TEXT CHECK(kind IS NULL OR kind IN ('BrickLink store','Online shop','Shop','Market','Fair','Private','Other')),
 created_at TEXT NOT NULL, archived_at TEXT) STRICT;

CREATE TABLE lot(
 id TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL, note TEXT,
 storage_id TEXT REFERENCES storage(id), place_id TEXT REFERENCES place(id),
 purchase_date TEXT, purchase_price TEXT, purchase_currency TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived_at TEXT,
 CHECK((purchase_price IS NULL) = (purchase_currency IS NULL))) STRICT;
CREATE INDEX lot_storage ON lot(storage_id);
CREATE INDEX lot_place ON lot(place_id);

-- One physical set. Its part list comes from exactly one inventory (ADR 0011):
--   rebrickable      -> catalogue inventory (item_id, inventory_version)   [cross-file natural key]
--   bricklink        -> fetched_inventory (same item; composite FK)
--   rebrickable_api  -> fetched_inventory (same item; composite FK)
--   migrated         -> the lines the 3.3 copy had; no inventory until the user chooses one
--   none             -> no part list known (an unidentified set)
-- inventory_pending='bricklink': BrickLink's list is wanted and its fetch job is queued; the copy
-- has Rebrickable's list meanwhile and switches when the job succeeds (decision F).
CREATE TABLE copy(
 id TEXT PRIMARY KEY NOT NULL,
 item_id INTEGER NOT NULL REFERENCES item(id),
 inventory_source TEXT NOT NULL CHECK(inventory_source IN ('rebrickable','bricklink','rebrickable_api','migrated','none')),
 inventory_version INTEGER,
 fetched_inventory_id INTEGER,
 inventory_digest TEXT, materialised_at TEXT,
 inventory_pending TEXT CHECK(inventory_pending IS NULL OR inventory_pending='bricklink'),
 pending_job_id INTEGER REFERENCES job(id),
 condition TEXT CHECK(condition IS NULL OR condition IN ('new','used')),
 completeness TEXT CHECK(completeness IS NULL OR completeness IN ('sealed','complete','incomplete')),
 completeness_source TEXT CHECK(completeness_source IS NULL OR completeness_source IN ('manual','derived')),
 storage_id TEXT REFERENCES storage(id), place_id TEXT REFERENCES place(id),
 purchase_date TEXT, purchase_price TEXT, purchase_currency TEXT, note TEXT,
 current_value TEXT, current_value_currency TEXT,
 pinned INTEGER NOT NULL DEFAULT 0 CHECK(pinned IN (0,1)),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived_at TEXT,
 FOREIGN KEY(item_id, fetched_inventory_id) REFERENCES fetched_inventory(item_id, id),
 CHECK((inventory_source='rebrickable') = (inventory_version IS NOT NULL)),
 CHECK((inventory_source IN ('bricklink','rebrickable_api')) = (fetched_inventory_id IS NOT NULL)),
 CHECK(inventory_source='none' OR inventory_digest IS NOT NULL),
 CHECK(inventory_pending IS NULL OR inventory_source='rebrickable'),
 CHECK((inventory_pending IS NULL) = (pending_job_id IS NULL)),
 CHECK((purchase_price IS NULL) = (purchase_currency IS NULL)),
 CHECK((current_value IS NULL) = (current_value_currency IS NULL))) STRICT;
CREATE INDEX copy_item ON copy(item_id, archived_at);
CREATE INDEX copy_fetched ON copy(item_id, fetched_inventory_id);
CREATE INDEX copy_pending ON copy(pending_job_id);
CREATE INDEX copy_storage ON copy(storage_id);
CREATE INDEX copy_place ON copy(place_id);

-- One whole minifigure line of a copy. Its parts always come from the figure's own Rebrickable
-- list (Q15): the catalogue's (item_id, inventory_version), or a fetched Rebrickable list for a
-- figure newer than the catalogue. 'none': no Rebrickable list exists (a BrickLink-only figure).
CREATE TABLE copy_figure(
 id INTEGER PRIMARY KEY,
 copy_id TEXT NOT NULL REFERENCES copy(id),
 item_id INTEGER NOT NULL REFERENCES item(id),
 inventory_source TEXT NOT NULL CHECK(inventory_source IN ('rebrickable','rebrickable_api','migrated','none')),
 inventory_version INTEGER, fetched_inventory_id INTEGER, inventory_digest TEXT,
 quantity INTEGER NOT NULL CHECK(quantity>=0),
 missing INTEGER NOT NULL DEFAULT 0 CHECK(missing>=0 AND missing<=quantity),
 retired_at TEXT,                                     -- the line left the copy's list on a switch; kept for references
 updated_at TEXT NOT NULL,
 UNIQUE(copy_id, id),
 FOREIGN KEY(item_id, fetched_inventory_id) REFERENCES fetched_inventory(item_id, id),
 CHECK((inventory_source='rebrickable') = (inventory_version IS NOT NULL)),
 CHECK((inventory_source='rebrickable_api') = (fetched_inventory_id IS NOT NULL)),
 CHECK(inventory_source='none' OR inventory_digest IS NOT NULL)) STRICT;
CREATE UNIQUE INDEX copy_figure_key ON copy_figure(copy_id, item_id);
CREATE INDEX copy_figure_item ON copy_figure(item_id);
CREATE INDEX copy_figure_fetched ON copy_figure(item_id, fetched_inventory_id);

-- One materialised part line; it belongs to the copy. No reference to a catalogue line: the
-- provenance is the copy's (or figure's) inventory plus this row's line key (review finding 2).
-- A switch updates rows in place by line key, inserts new ones and retires vanished ones, so
-- stock_transfer, allocation and part_check references never dangle.
CREATE TABLE copy_part(
 id INTEGER PRIMARY KEY,
 copy_id TEXT NOT NULL REFERENCES copy(id),
 copy_figure_id INTEGER,                              -- NULL: a set line; set: a component of that figure of THIS copy
 figure_key INTEGER GENERATED ALWAYS AS (coalesce(copy_figure_id,0)) VIRTUAL,
 item_id INTEGER NOT NULL REFERENCES item(id),
 color_id INTEGER NOT NULL REFERENCES color(id),      -- 1 ("no colour") where the source has none
 is_spare INTEGER NOT NULL DEFAULT 0 CHECK(is_spare IN (0,1)),
 quantity INTEGER NOT NULL CHECK(quantity>=0),
 missing INTEGER NOT NULL DEFAULT 0 CHECK(missing>=0 AND missing<=quantity),
 damaged INTEGER NOT NULL DEFAULT 0 CHECK(damaged>=0 AND damaged<=quantity),
                                                      -- each bounded on its own, as checker.mark_row today (checker.py:454-468)
 checked INTEGER NOT NULL DEFAULT 0 CHECK(checked IN (0,1)),
 retired_at TEXT,
 FOREIGN KEY(copy_id, copy_figure_id) REFERENCES copy_figure(copy_id, id)) STRICT;
CREATE UNIQUE INDEX copy_part_key ON copy_part(copy_id, figure_key, item_id, color_id, is_spare);
CREATE INDEX copy_part_item ON copy_part(item_id, color_id, copy_id) WHERE retired_at IS NULL;   -- where-used, gaps
CREATE INDEX copy_part_figure ON copy_part(copy_figure_id);
CREATE INDEX copy_part_color ON copy_part(color_id);

-- Loose things. Identical non-figure lines merge (stock.add_loose, stock.py:87-115, compares with
-- IS); the merge key uses generated coalesce columns because a unique index treats NULLs as distinct.
CREATE TABLE stock(
 id TEXT PRIMARY KEY NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('part','minifigure','instructions','box','gear','book','catalog')),
 item_id INTEGER NOT NULL REFERENCES item(id),
 color_id INTEGER REFERENCES color(id),
 quantity INTEGER NOT NULL CHECK(quantity>=0),
 condition TEXT CHECK(condition IS NULL OR condition IN ('new','used','damaged')),
 storage_id TEXT REFERENCES storage(id), lot_id TEXT REFERENCES lot(id), place_id TEXT REFERENCES place(id),
 purchase_date TEXT, purchase_price TEXT, purchase_currency TEXT, note TEXT,
 missing INTEGER, damaged INTEGER, checked INTEGER,   -- figure state summary (NULL = never recorded)
 inventory_source TEXT CHECK(inventory_source IS NULL OR inventory_source IN ('rebrickable','rebrickable_api','migrated','none')),
 inventory_version INTEGER, fetched_inventory_id INTEGER, inventory_digest TEXT,   -- G6: a loose figure's part list
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived_at TEXT,
 color_key INTEGER GENERATED ALWAYS AS (coalesce(color_id,0)) VIRTUAL,
 condition_key TEXT GENERATED ALWAYS AS (coalesce(condition,'')) VIRTUAL,
 lot_key TEXT GENERATED ALWAYS AS (coalesce(lot_id,'')) VIRTUAL,
 storage_key TEXT GENERATED ALWAYS AS (coalesce(storage_id,'')) VIRTUAL,
 FOREIGN KEY(item_id, fetched_inventory_id) REFERENCES fetched_inventory(item_id, id),
 CHECK((kind='part') = (color_id IS NOT NULL)),
 CHECK((kind='minifigure') = (inventory_source IS NOT NULL)),
 CHECK((inventory_source IS 'rebrickable') = (inventory_version IS NOT NULL)),
 CHECK((inventory_source IS 'rebrickable_api') = (fetched_inventory_id IS NOT NULL)),
 CHECK((purchase_price IS NULL) = (purchase_currency IS NULL))) STRICT;
CREATE UNIQUE INDEX stock_merge_key ON stock(item_id, color_key, condition_key, lot_key, storage_key)
 WHERE archived_at IS NULL AND kind!='minifigure';
CREATE INDEX stock_item ON stock(item_id, color_id, archived_at);
CREATE INDEX stock_fetched ON stock(item_id, fetched_inventory_id);
CREATE INDEX stock_color ON stock(color_id);
CREATE INDEX stock_storage ON stock(storage_id);
CREATE INDEX stock_lot ON stock(lot_id);
CREATE INDEX stock_place ON stock(place_id);

CREATE TABLE stock_part(                             -- the parts of one loose minifigure
 id INTEGER PRIMARY KEY,
 stock_id TEXT NOT NULL REFERENCES stock(id),
 item_id INTEGER NOT NULL REFERENCES item(id),
 color_id INTEGER NOT NULL REFERENCES color(id),
 is_spare INTEGER NOT NULL DEFAULT 0 CHECK(is_spare IN (0,1)),
 quantity INTEGER NOT NULL CHECK(quantity>=0),
 missing INTEGER NOT NULL DEFAULT 0 CHECK(missing>=0 AND missing<=quantity),
 damaged INTEGER NOT NULL DEFAULT 0 CHECK(damaged>=0 AND damaged<=quantity),
 checked INTEGER NOT NULL DEFAULT 0 CHECK(checked IN (0,1)),
 retired_at TEXT) STRICT;
CREATE UNIQUE INDEX stock_part_key ON stock_part(stock_id, item_id, color_id, is_spare);
CREATE INDEX stock_part_item ON stock_part(item_id, color_id);
CREATE INDEX stock_part_color ON stock_part(color_id);

CREATE TABLE flag(
 id TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('status','tag','owner')),
 shown_on_grid INTEGER NOT NULL DEFAULT 1 CHECK(shown_on_grid IN (0,1)),
 system INTEGER NOT NULL DEFAULT 0 CHECK(system IN (0,1)),
 created_at TEXT NOT NULL, archived_at TEXT,
 CHECK(system=0 OR archived_at IS NULL)) STRICT;
CREATE TABLE copy_flag(copy_id TEXT NOT NULL REFERENCES copy(id), flag_id TEXT NOT NULL REFERENCES flag(id), PRIMARY KEY(copy_id, flag_id)) STRICT;
CREATE INDEX copy_flag_flag ON copy_flag(flag_id);
CREATE TABLE stock_flag(stock_id TEXT NOT NULL REFERENCES stock(id), flag_id TEXT NOT NULL REFERENCES flag(id), PRIMARY KEY(stock_id, flag_id)) STRICT;
CREATE INDEX stock_flag_flag ON stock_flag(flag_id);
CREATE TABLE wish_flag(wish_id TEXT NOT NULL REFERENCES wish(id), flag_id TEXT NOT NULL REFERENCES flag(id), PRIMARY KEY(wish_id, flag_id)) STRICT;
CREATE INDEX wish_flag_flag ON wish_flag(flag_id);

CREATE TABLE wishlist(
 id TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL, note TEXT, sort INTEGER NOT NULL DEFAULT 0,
 bricklink_id TEXT, created_at TEXT NOT NULL, archived_at TEXT) STRICT;
INSERT INTO wishlist(id,name,created_at) VALUES('default','Wishlist',strftime('%Y-%m-%dT%H:%M:%fZ','now'));

CREATE TABLE wish(
 id TEXT PRIMARY KEY NOT NULL,                        -- uuid (Q6)
 wishlist_id TEXT NOT NULL DEFAULT 'default' REFERENCES wishlist(id),
 kind TEXT NOT NULL CHECK(kind IN ('set','part','minifigure','instructions','box','gear','book','catalog')),
 item_id INTEGER NOT NULL REFERENCES item(id),
 color_id INTEGER REFERENCES color(id),
 color_key INTEGER GENERATED ALWAYS AS (coalesce(color_id,0)) VIRTUAL,
 quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity>=1),
 condition TEXT CHECK(condition IS NULL OR condition IN ('new','used','any')),
 max_price TEXT, max_price_currency TEXT,
 qty_filled_manual INTEGER CHECK(qty_filled_manual IS NULL OR qty_filled_manual>=0),
 note TEXT, added_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived_at TEXT,
 CHECK((kind='part') = (color_id IS NOT NULL)),
 CHECK((max_price IS NULL) = (max_price_currency IS NULL))) STRICT;
CREATE UNIQUE INDEX wish_live_key ON wish(wishlist_id, item_id, color_key) WHERE archived_at IS NULL;
CREATE INDEX wish_item ON wish(item_id);
CREATE INDEX wish_color ON wish(color_id);

CREATE TABLE part_check(                             -- a Check Set Parts session (today settings 'checker:*')
 copy_id TEXT NOT NULL REFERENCES copy(id),
 copy_figure_id INTEGER,
 figure_key INTEGER GENERATED ALWAYS AS (coalesce(copy_figure_id,0)) VIRTUAL,
 session_id TEXT NOT NULL,
 order_mode TEXT NOT NULL CHECK(order_mode IN ('inventory','largest','colour')),
 spares TEXT CHECK(spares IS NULL OR spares IN ('yes','no')),
 session_json TEXT NOT NULL,                          -- order and answers by copy_part.id, which a switch keeps (in-place update)
 finished INTEGER NOT NULL DEFAULT 0 CHECK(finished IN (0,1)),
 started_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(copy_id, copy_figure_id) REFERENCES copy_figure(copy_id, id)) STRICT;
CREATE UNIQUE INDEX part_check_key ON part_check(copy_id, figure_key);
CREATE INDEX part_check_figure ON part_check(copy_figure_id);

CREATE TABLE stock_transfer(                         -- Take / Give history (today match_history)
 id INTEGER PRIMARY KEY, at TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('part','figure','stock-part','instructions','box')),
 stock_id TEXT NOT NULL REFERENCES stock(id),
 copy_id TEXT REFERENCES copy(id), copy_part_id INTEGER REFERENCES copy_part(id),
 copy_figure_id INTEGER REFERENCES copy_figure(id), stock_part_id INTEGER REFERENCES stock_part(id),
 item_id INTEGER NOT NULL REFERENCES item(id), color_id INTEGER REFERENCES color(id),
 quantity INTEGER NOT NULL CHECK(quantity>0), source_snapshot TEXT NOT NULL,
 event_id INTEGER NOT NULL REFERENCES event(id)) STRICT;
CREATE INDEX stock_transfer_stock ON stock_transfer(stock_id);
CREATE INDEX stock_transfer_copy ON stock_transfer(copy_id);
CREATE INDEX stock_transfer_copy_part ON stock_transfer(copy_part_id);
CREATE INDEX stock_transfer_copy_figure ON stock_transfer(copy_figure_id);
CREATE INDEX stock_transfer_stock_part ON stock_transfer(stock_part_id);
CREATE INDEX stock_transfer_item ON stock_transfer(item_id);
CREATE INDEX stock_transfer_color ON stock_transfer(color_id);
CREATE INDEX stock_transfer_event ON stock_transfer(event_id);

-- ---------- Orders (not migrated, decision B; the tables start empty) ----------

CREATE TABLE purchase_order(
 id INTEGER PRIMARY KEY, bricklink_order_id TEXT UNIQUE, store TEXT, seller TEXT, date_ordered TEXT,
 status TEXT, cost TEXT, currency TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 CHECK((cost IS NULL) = (currency IS NULL))) STRICT;

CREATE TABLE order_document(
 id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES purchase_order(id),
 source TEXT NOT NULL CHECK(source IN ('email','xml','api')), digest TEXT NOT NULL, label TEXT,
 phase TEXT NOT NULL CHECK(phase IN ('draft','reviewed','saved','undone')),
 raw_record_id INTEGER REFERENCES source_record(id),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(order_id, source, digest)) STRICT;
CREATE INDEX order_document_order ON order_document(order_id);
CREATE INDEX order_document_record ON order_document(raw_record_id);

CREATE TABLE order_line(
 id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES purchase_order(id),
 document_id INTEGER NOT NULL REFERENCES order_document(id), line_no INTEGER NOT NULL,
 -- The provider's own words, verbatim (an unplaceable BrickLink key stays here, not in item_link).
 raw_item_type TEXT, raw_item_no TEXT, raw_color_id INTEGER, raw_color_name TEXT, raw_name TEXT, raw_text TEXT, remark TEXT,
 item_id INTEGER REFERENCES item(id), color_id INTEGER REFERENCES color(id),
 sticker_set_item_id INTEGER REFERENCES item(id),
 condition TEXT CHECK(condition IS NULL OR condition IN ('new','used')),
 state TEXT NOT NULL CHECK(state IN ('matched','by_hand','confirmed','held')), confirmed_via TEXT,
 qty INTEGER NOT NULL CHECK(qty>0), unit_price TEXT, line_total TEXT,
 batch INTEGER, submitted TEXT, suggestions_json TEXT,
 paired_line_id INTEGER REFERENCES order_line(id), updated_at TEXT NOT NULL,
 UNIQUE(document_id, line_no)) STRICT;
CREATE INDEX order_line_order ON order_line(order_id);
CREATE INDEX order_line_item ON order_line(item_id);
CREATE INDEX order_line_color ON order_line(color_id);
CREATE INDEX order_line_sticker ON order_line(sticker_set_item_id);
CREATE INDEX order_line_paired ON order_line(paired_line_id);

CREATE TABLE line_receipt(line_id INTEGER PRIMARY KEY NOT NULL REFERENCES order_line(id), received INTEGER NOT NULL CHECK(received>=0), updated_at TEXT NOT NULL) STRICT;
CREATE TABLE line_receipt_log(id INTEGER PRIMARY KEY, line_id INTEGER NOT NULL REFERENCES order_line(id), at TEXT NOT NULL, old INTEGER, new INTEGER NOT NULL) STRICT;
CREATE INDEX line_receipt_log_line ON line_receipt_log(line_id);

CREATE TABLE allocation(
 id INTEGER PRIMARY KEY, confirm_id TEXT NOT NULL,
 order_id INTEGER NOT NULL REFERENCES purchase_order(id), line_id INTEGER NOT NULL REFERENCES order_line(id),
 qty INTEGER NOT NULL CHECK(qty>0),
 state TEXT NOT NULL CHECK(state IN ('applied','pending','conflict','undoing','undone')),
 target_kind TEXT NOT NULL CHECK(target_kind IN ('copy','stock')),
 kind TEXT NOT NULL CHECK(kind IN ('missing_part','missing_figure','instructions','box','loose_part','loose_figure','loose_other')),
 copy_id TEXT REFERENCES copy(id), copy_part_id INTEGER REFERENCES copy_part(id), copy_figure_id INTEGER REFERENCES copy_figure(id),
 stock_id TEXT REFERENCES stock(id),
 item_id INTEGER NOT NULL REFERENCES item(id), color_id INTEGER REFERENCES color(id),
 intent_before INTEGER, intent_after INTEGER,
 created_at TEXT NOT NULL, applied_at TEXT, undone_at TEXT,
 CHECK((target_kind='copy') = (copy_id IS NOT NULL)), CHECK((target_kind='stock') = (stock_id IS NOT NULL))) STRICT;
CREATE INDEX allocation_order ON allocation(order_id);
CREATE INDEX allocation_line ON allocation(line_id, state);
CREATE INDEX allocation_copy ON allocation(copy_id);
CREATE INDEX allocation_copy_part ON allocation(copy_part_id);
CREATE INDEX allocation_copy_figure ON allocation(copy_figure_id);
CREATE INDEX allocation_stock ON allocation(stock_id);
CREATE INDEX allocation_item ON allocation(item_id, color_id);
CREATE INDEX allocation_color ON allocation(color_id);

-- ---------- Prices ----------

CREATE TABLE price_observation(
 id INTEGER PRIMARY KEY,
 item_id INTEGER NOT NULL REFERENCES item(id), color_id INTEGER REFERENCES color(id),
 condition TEXT CHECK(condition IS NULL OR condition IN ('new','used')),
 guide TEXT NOT NULL CHECK(guide IN ('sold','stock','retail','manual','valuation')),
 slot TEXT, region TEXT, currency TEXT, price TEXT, qty INTEGER, sold INTEGER, min TEXT, max TEXT,
 source TEXT NOT NULL REFERENCES source(id),
 provider_key TEXT,                                   -- the BrickLink key priced, e.g. 'P:970c00/11' (the 3.3 key on migrated rows)
 observed_at TEXT NOT NULL, error TEXT, voided_at TEXT,
 job_id INTEGER REFERENCES job(id)) STRICT;
-- 931 migrated rows have a price without a currency, so no money-pair CHECK on this table.
CREATE INDEX price_observation_item ON price_observation(item_id, color_id, condition, guide, observed_at);
CREATE INDEX price_observation_source ON price_observation(source);
CREATE INDEX price_observation_color ON price_observation(color_id);
CREATE INDEX price_observation_job ON price_observation(job_id);

CREATE TABLE price_current(
 item_id INTEGER NOT NULL REFERENCES item(id), color_id INTEGER REFERENCES color(id),
 condition TEXT, guide TEXT NOT NULL, slot TEXT, region TEXT, currency TEXT,
 observation_id INTEGER NOT NULL REFERENCES price_observation(id),
 color_key INTEGER GENERATED ALWAYS AS (coalesce(color_id,0)) VIRTUAL,
 condition_key TEXT GENERATED ALWAYS AS (coalesce(condition,'')) VIRTUAL,
 slot_key TEXT GENERATED ALWAYS AS (coalesce(slot,'')) VIRTUAL,
 region_key TEXT GENERATED ALWAYS AS (coalesce(region,'')) VIRTUAL,
 currency_key TEXT GENERATED ALWAYS AS (coalesce(currency,'')) VIRTUAL) STRICT;
CREATE UNIQUE INDEX price_current_key ON price_current(item_id, color_key, condition_key, guide, slot_key, region_key, currency_key);
CREATE INDEX price_current_observation ON price_current(observation_id);
CREATE INDEX price_current_color ON price_current(color_id);

CREATE TABLE price_watch(
 item_id INTEGER NOT NULL REFERENCES item(id), color_id INTEGER REFERENCES color(id), condition TEXT,
 color_key INTEGER GENERATED ALWAYS AS (coalesce(color_id,0)) VIRTUAL,
 condition_key TEXT GENERATED ALWAYS AS (coalesce(condition,'')) VIRTUAL,
 origin TEXT, first_seen TEXT, last_fetch_at TEXT, last_error TEXT, last_error_at TEXT, last_attempt_at TEXT) STRICT;
CREATE UNIQUE INDEX price_watch_key ON price_watch(item_id, color_key, condition_key);
CREATE INDEX price_watch_color ON price_watch(color_id);

CREATE TABLE exchange_rate(currency TEXT PRIMARY KEY NOT NULL CHECK(length(currency)=3), per_eur TEXT NOT NULL, as_of TEXT NOT NULL, source TEXT NOT NULL CHECK(source IN ('manual','ecb'))) STRICT;

-- ---------- Operational ----------

CREATE TABLE source(
 id TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('api','file','manual')),
 enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1))) STRICT;
INSERT INTO source VALUES('rebrickable','Rebrickable','api',1),('bricklink','BrickLink','api',1),('brickset','Brickset','api',1),
 ('brickognize','Brickognize','api',1),('rebrickable_dump','Rebrickable dump','file',1),('bricklink_list','BrickLink item lists','file',1),
 ('mapping','Mappings','file',1),('manual','Manual','manual',1),('own','Own photos','manual',1),('migration','Migration','manual',1),
 ('import','Import pipeline','manual',1),('lego','LEGO colour numbers','file',1);   -- 'import': the pipeline's job source (pipeline.py:106, review finding 8)

CREATE TABLE source_freshness(source TEXT NOT NULL REFERENCES source(id), kind TEXT NOT NULL, max_age_days INTEGER CHECK(max_age_days IS NULL OR max_age_days>=0), PRIMARY KEY(source, kind)) STRICT;

CREATE TABLE source_budget(                          -- API call counters (not the dump download: Q14, tell, don't block)
 source TEXT NOT NULL REFERENCES source(id), day TEXT NOT NULL,
 used INTEGER NOT NULL DEFAULT 0 CHECK(used>=0), blocked INTEGER NOT NULL DEFAULT 0 CHECK(blocked IN (0,1)),
 blocked_until TEXT, last_attempt_at TEXT,
 PRIMARY KEY(source, day)) STRICT;

CREATE TABLE source_key(source TEXT PRIMARY KEY NOT NULL, ciphertext TEXT NOT NULL, saved_at TEXT NOT NULL, archived_at TEXT) STRICT;
CREATE TABLE source_key_previous(source TEXT PRIMARY KEY NOT NULL, ciphertext TEXT NOT NULL, saved_at TEXT NOT NULL, archived_at TEXT) STRICT;
-- source ids here include the credential slots 'rebrickable_user' and 'brickset_user'; deliberately no FK.

CREATE TABLE api_token(
 id TEXT PRIMARY KEY NOT NULL, name TEXT UNIQUE NOT NULL, hash TEXT NOT NULL, scopes TEXT NOT NULL,
 created_at TEXT NOT NULL, expires_at TEXT, last_used_at TEXT, revoked_at TEXT) STRICT;

CREATE TABLE setting(key TEXT PRIMARY KEY NOT NULL, value TEXT) STRICT;
-- Preferences only (design § 5.2): bricklink_region, bricklink_currency, incomplete_discount_pct,
-- repair_shipping, repair_fees, repair_min_order, repair_use_loose_stock, retail_country,
-- display_currency, source_priority (incl. the picture source order, Q17), import_order:<kind>,
-- prefer_bricklink_inventory ('true'/'false', Q13). Also maintenance:database_check, the stored result of
-- the last database check (not a preference, not migrated).

CREATE TABLE job(
 id INTEGER PRIMARY KEY, source TEXT NOT NULL REFERENCES source(id), kind TEXT NOT NULL,
 item_id INTEGER REFERENCES item(id),
 state TEXT NOT NULL CHECK(state IN ('queued','running','waiting_for_budget','failed','done')),
 payload TEXT, attempts INTEGER NOT NULL DEFAULT 0, budget_day TEXT, budget_used INTEGER NOT NULL DEFAULT 0,
 retry_at TEXT, error TEXT,
 error_code TEXT CHECK(error_code IS NULL OR error_code IN ('source_not_configured','unidentified','source_error','budget','not_found','invalid_reply')),
                                                      -- 'unidentified' (G9, Q21): no provider id for this item, beside a missing key
 via TEXT NOT NULL CHECK(via IN ('app','cli','api','import','migration')), actor TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL) STRICT;
CREATE INDEX job_item ON job(item_id);
CREATE INDEX job_source ON job(source);
CREATE INDEX job_state_retry ON job(state, retry_at);

CREATE TABLE job_step(
 job_id INTEGER NOT NULL REFERENCES job(id), name TEXT NOT NULL, position INTEGER NOT NULL,
 sources TEXT NOT NULL, source_index INTEGER NOT NULL DEFAULT 0, source TEXT,
 state TEXT NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','running','waiting_for_budget','failed','done')),
 error TEXT,
 error_code TEXT CHECK(error_code IS NULL OR error_code IN ('source_not_configured','unidentified','source_error','budget','not_found','invalid_reply')),
 retry_at TEXT, count INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 1,
 updated_at TEXT NOT NULL, PRIMARY KEY(job_id, name)) STRICT;

CREATE TABLE job_call(
 job_id INTEGER NOT NULL, step TEXT NOT NULL, operation TEXT NOT NULL,
 request_job INTEGER REFERENCES job(id), result TEXT,
 PRIMARY KEY(job_id, step, operation), FOREIGN KEY(job_id, step) REFERENCES job_step(job_id, name)) STRICT;
CREATE INDEX job_call_request ON job_call(request_job);

CREATE TABLE job_owner(job_id INTEGER PRIMARY KEY NOT NULL REFERENCES job(id), pid INTEGER NOT NULL, claimed_at TEXT NOT NULL) STRICT;

CREATE TABLE source_record(                          -- raw API replies (decision 9: API responses stay raw)
 id INTEGER PRIMARY KEY,
 source TEXT NOT NULL REFERENCES source(id), kind TEXT NOT NULL, key TEXT NOT NULL,
 payload TEXT NOT NULL, digest TEXT NOT NULL, bytes INTEGER NOT NULL,
 job_id INTEGER REFERENCES job(id), fetched_at TEXT NOT NULL, status TEXT NOT NULL) STRICT;
CREATE UNIQUE INDEX source_record_key ON source_record(source, kind, key, digest);
CREATE INDEX source_record_job ON source_record(job_id);

CREATE TABLE plan(
 id TEXT PRIMARY KEY NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('import','sync_pull','sync_send')),
 source TEXT, created_at TEXT NOT NULL, applied_at TEXT, event_id INTEGER REFERENCES event(id), counts_json TEXT) STRICT;
CREATE INDEX plan_event ON plan(event_id);

CREATE TABLE sync_state(
 source TEXT PRIMARY KEY NOT NULL REFERENCES source(id),
 link_json TEXT,                                      -- migrated from settings 'sync:<source>:link' (decision D)
 baseline_json TEXT, last_pull_json TEXT, last_send_json TEXT, updated_at TEXT NOT NULL) STRICT;

CREATE TABLE identification(
 id TEXT PRIMARY KEY NOT NULL, created_at TEXT NOT NULL, has_thumb INTEGER NOT NULL CHECK(has_thumb IN (0,1)),
 candidates TEXT NOT NULL, missing_count INTEGER NOT NULL DEFAULT 0, archived_at TEXT) STRICT;
CREATE TABLE identification_action(
 id INTEGER PRIMARY KEY, identification_id TEXT NOT NULL REFERENCES identification(id),
 kind TEXT NOT NULL, at TEXT NOT NULL,
 item_id INTEGER NOT NULL REFERENCES item(id), color_id INTEGER REFERENCES color(id), quantity INTEGER,
 copy_id TEXT REFERENCES copy(id), stock_id TEXT REFERENCES stock(id), storage_id TEXT REFERENCES storage(id)) STRICT;
CREATE INDEX identification_action_identification ON identification_action(identification_id);
CREATE INDEX identification_action_item ON identification_action(item_id);
CREATE INDEX identification_action_color ON identification_action(color_id);
CREATE INDEX identification_action_copy ON identification_action(copy_id);
CREATE INDEX identification_action_stock ON identification_action(stock_id);
CREATE INDEX identification_action_storage ON identification_action(storage_id);

-- ---------- Audit ----------

CREATE TABLE event(                                  -- append-only; 4.0 starts a fresh log (pre-4.0 events stay in the 3.3 file)
 id INTEGER PRIMARY KEY,
 at TEXT NOT NULL, via TEXT NOT NULL CHECK(via IN ('app','cli','api','import','migration')), actor TEXT,
 entity_kind TEXT NOT NULL, entity_id TEXT,
 field TEXT NOT NULL, old_value TEXT, new_value TEXT,
 operation_key TEXT) STRICT;
CREATE INDEX event_entity ON event(entity_kind, entity_id, id);
CREATE INDEX event_actor_operation ON event(actor, operation_key) WHERE operation_key IS NOT NULL;
CREATE INDEX event_at ON event(at);
CREATE TRIGGER event_no_update BEFORE UPDATE ON event BEGIN SELECT RAISE(ABORT,'events are append-only'); END;
CREATE TRIGGER event_no_delete BEFORE DELETE ON event BEGIN SELECT RAISE(ABORT,'events are append-only'); END;
CREATE TRIGGER event_no_replace BEFORE INSERT ON event WHEN EXISTS(SELECT 1 FROM event WHERE id=new.id)
 BEGIN SELECT RAISE(ABORT,'events are append-only'); END;

CREATE TABLE event_undo(
 event_id INTEGER PRIMARY KEY NOT NULL REFERENCES event(id),
 undo_event_id INTEGER NOT NULL REFERENCES event(id)) STRICT;
CREATE INDEX event_undo_undo ON event_undo(undo_event_id);
CREATE TRIGGER event_undo_no_update BEFORE UPDATE ON event_undo BEGIN SELECT RAISE(ABORT,'undo records are append-only'); END;
CREATE TRIGGER event_undo_no_delete BEFORE DELETE ON event_undo BEGIN SELECT RAISE(ABORT,'undo records are append-only'); END;

-- ---------- Guards (invariants 1 and 3; review finding 8) ----------
-- Generated: one INSERT and one UPDATE trigger per column that references item(id). Each refuses
-- a merged item and, where the table needs one kind, an item of another kind. UPDATE triggers
-- also fire when a row's own kind column changes (stock, wish).
CREATE TRIGGER copy_item_guard_insert BEFORE INSERT ON copy WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT 'set')
 BEGIN SELECT RAISE(ABORT,'copy.item_id: unmerged item of the right kind needed'); END;
CREATE TRIGGER copy_item_guard_update BEFORE UPDATE OF item_id ON copy WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT 'set')
 BEGIN SELECT RAISE(ABORT,'copy.item_id: unmerged item of the right kind needed'); END;
CREATE TRIGGER copy_figure_item_guard_insert BEFORE INSERT ON copy_figure WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT 'minifigure')
 BEGIN SELECT RAISE(ABORT,'copy_figure.item_id: unmerged item of the right kind needed'); END;
CREATE TRIGGER copy_figure_item_guard_update BEFORE UPDATE OF item_id ON copy_figure WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT 'minifigure')
 BEGIN SELECT RAISE(ABORT,'copy_figure.item_id: unmerged item of the right kind needed'); END;
CREATE TRIGGER copy_part_item_guard_insert BEFORE INSERT ON copy_part WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT 'part')
 BEGIN SELECT RAISE(ABORT,'copy_part.item_id: unmerged item of the right kind needed'); END;
CREATE TRIGGER copy_part_item_guard_update BEFORE UPDATE OF item_id ON copy_part WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT 'part')
 BEGIN SELECT RAISE(ABORT,'copy_part.item_id: unmerged item of the right kind needed'); END;
CREATE TRIGGER stock_item_guard_insert BEFORE INSERT ON stock WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT new.kind)
 BEGIN SELECT RAISE(ABORT,'stock.item_id: unmerged item of the right kind needed'); END;
CREATE TRIGGER stock_item_guard_update BEFORE UPDATE OF item_id, kind ON stock WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT new.kind)
 BEGIN SELECT RAISE(ABORT,'stock.item_id: unmerged item of the right kind needed'); END;
CREATE TRIGGER stock_part_item_guard_insert BEFORE INSERT ON stock_part WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT 'part')
 BEGIN SELECT RAISE(ABORT,'stock_part.item_id: unmerged item of the right kind needed'); END;
CREATE TRIGGER stock_part_item_guard_update BEFORE UPDATE OF item_id ON stock_part WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT 'part')
 BEGIN SELECT RAISE(ABORT,'stock_part.item_id: unmerged item of the right kind needed'); END;
CREATE TRIGGER wish_item_guard_insert BEFORE INSERT ON wish WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT new.kind)
 BEGIN SELECT RAISE(ABORT,'wish.item_id: unmerged item of the right kind needed'); END;
CREATE TRIGGER wish_item_guard_update BEFORE UPDATE OF item_id, kind ON wish WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT new.kind)
 BEGIN SELECT RAISE(ABORT,'wish.item_id: unmerged item of the right kind needed'); END;
CREATE TRIGGER fetched_inventory_item_guard_insert BEFORE INSERT ON fetched_inventory WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) NOT IN ('set','minifigure'))
 BEGIN SELECT RAISE(ABORT,'fetched_inventory.item_id: unmerged item of the right kind needed'); END;
CREATE TRIGGER fetched_inventory_item_guard_update BEFORE UPDATE OF item_id ON fetched_inventory WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) NOT IN ('set','minifigure'))
 BEGIN SELECT RAISE(ABORT,'fetched_inventory.item_id: unmerged item of the right kind needed'); END;
CREATE TRIGGER fetched_inventory_part_item_guard_insert BEFORE INSERT ON fetched_inventory_part WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT 'part')
 BEGIN SELECT RAISE(ABORT,'fetched_inventory_part.item_id: unmerged item of the right kind needed'); END;
CREATE TRIGGER fetched_inventory_part_item_guard_update BEFORE UPDATE OF item_id ON fetched_inventory_part WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT 'part')
 BEGIN SELECT RAISE(ABORT,'fetched_inventory_part.item_id: unmerged item of the right kind needed'); END;
CREATE TRIGGER fetched_inventory_figure_item_guard_insert BEFORE INSERT ON fetched_inventory_figure WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT 'minifigure')
 BEGIN SELECT RAISE(ABORT,'fetched_inventory_figure.item_id: unmerged item of the right kind needed'); END;
CREATE TRIGGER fetched_inventory_figure_item_guard_update BEFORE UPDATE OF item_id ON fetched_inventory_figure WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT 'minifigure')
 BEGIN SELECT RAISE(ABORT,'fetched_inventory_figure.item_id: unmerged item of the right kind needed'); END;
CREATE TRIGGER instruction_file_item_guard_insert BEFORE INSERT ON instruction_file WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT 'set')
 BEGIN SELECT RAISE(ABORT,'instruction_file.item_id: unmerged item of the right kind needed'); END;
CREATE TRIGGER instruction_file_item_guard_update BEFORE UPDATE OF item_id ON instruction_file WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT 'set')
 BEGIN SELECT RAISE(ABORT,'instruction_file.item_id: unmerged item of the right kind needed'); END;
CREATE TRIGGER set_preference_item_guard_insert BEFORE INSERT ON set_preference WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT 'set')
 BEGIN SELECT RAISE(ABORT,'set_preference.item_id: unmerged item of the right kind needed'); END;
CREATE TRIGGER set_preference_item_guard_update BEFORE UPDATE OF item_id ON set_preference WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT 'set')
 BEGIN SELECT RAISE(ABORT,'set_preference.item_id: unmerged item of the right kind needed'); END;
CREATE TRIGGER order_line_item_guard_insert BEFORE INSERT ON order_line WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'order_line.item_id: unmerged item needed'); END;
CREATE TRIGGER order_line_item_guard_update BEFORE UPDATE OF item_id ON order_line WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'order_line.item_id: unmerged item needed'); END;
CREATE TRIGGER order_line_sticker_set_guard_insert BEFORE INSERT ON order_line WHEN new.sticker_set_item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.sticker_set_item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'order_line.sticker_set_item_id: unmerged item needed'); END;
CREATE TRIGGER order_line_sticker_set_guard_update BEFORE UPDATE OF sticker_set_item_id ON order_line WHEN new.sticker_set_item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.sticker_set_item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'order_line.sticker_set_item_id: unmerged item needed'); END;
CREATE TRIGGER allocation_item_guard_insert BEFORE INSERT ON allocation WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'allocation.item_id: unmerged item needed'); END;
CREATE TRIGGER allocation_item_guard_update BEFORE UPDATE OF item_id ON allocation WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'allocation.item_id: unmerged item needed'); END;
CREATE TRIGGER price_observation_item_guard_insert BEFORE INSERT ON price_observation WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'price_observation.item_id: unmerged item needed'); END;
CREATE TRIGGER price_observation_item_guard_update BEFORE UPDATE OF item_id ON price_observation WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'price_observation.item_id: unmerged item needed'); END;
CREATE TRIGGER price_current_item_guard_insert BEFORE INSERT ON price_current WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'price_current.item_id: unmerged item needed'); END;
CREATE TRIGGER price_current_item_guard_update BEFORE UPDATE OF item_id ON price_current WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'price_current.item_id: unmerged item needed'); END;
CREATE TRIGGER price_watch_item_guard_insert BEFORE INSERT ON price_watch WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'price_watch.item_id: unmerged item needed'); END;
CREATE TRIGGER price_watch_item_guard_update BEFORE UPDATE OF item_id ON price_watch WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'price_watch.item_id: unmerged item needed'); END;
CREATE TRIGGER item_property_item_guard_insert BEFORE INSERT ON item_property WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'item_property.item_id: unmerged item needed'); END;
CREATE TRIGGER item_property_item_guard_update BEFORE UPDATE OF item_id ON item_property WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'item_property.item_id: unmerged item needed'); END;
CREATE TRIGGER picture_item_guard_insert BEFORE INSERT ON picture WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'picture.item_id: unmerged item needed'); END;
CREATE TRIGGER picture_item_guard_update BEFORE UPDATE OF item_id ON picture WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'picture.item_id: unmerged item needed'); END;
CREATE TRIGGER photo_item_guard_insert BEFORE INSERT ON photo WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'photo.item_id: unmerged item needed'); END;
CREATE TRIGGER photo_item_guard_update BEFORE UPDATE OF item_id ON photo WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'photo.item_id: unmerged item needed'); END;
CREATE TRIGGER identification_action_item_guard_insert BEFORE INSERT ON identification_action WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'identification_action.item_id: unmerged item needed'); END;
CREATE TRIGGER identification_action_item_guard_update BEFORE UPDATE OF item_id ON identification_action WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'identification_action.item_id: unmerged item needed'); END;
CREATE TRIGGER stock_transfer_item_guard_insert BEFORE INSERT ON stock_transfer WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'stock_transfer.item_id: unmerged item needed'); END;
CREATE TRIGGER stock_transfer_item_guard_update BEFORE UPDATE OF item_id ON stock_transfer WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'stock_transfer.item_id: unmerged item needed'); END;
CREATE TRIGGER item_link_item_guard_insert BEFORE INSERT ON item_link WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'item_link.item_id: unmerged item needed'); END;
CREATE TRIGGER item_link_item_guard_update BEFORE UPDATE OF item_id ON item_link WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'item_link.item_id: unmerged item needed'); END;
CREATE TRIGGER item_provider_status_item_guard_insert BEFORE INSERT ON item_provider_status WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'item_provider_status.item_id: unmerged item needed'); END;
CREATE TRIGGER item_provider_status_item_guard_update BEFORE UPDATE OF item_id ON item_provider_status WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'item_provider_status.item_id: unmerged item needed'); END;
CREATE TRIGGER job_item_guard_insert BEFORE INSERT ON job WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'job.item_id: unmerged item needed'); END;
CREATE TRIGGER job_item_guard_update BEFORE UPDATE OF item_id ON job WHEN new.item_id IS NOT NULL AND ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'job.item_id: unmerged item needed'); END;
-- A merge marks the item merged only after every reference moved, only into an unmerged item of
-- the same kind, and only when the merged item is local or retired by the catalogue (finding 4).
CREATE TRIGGER item_merge_guard BEFORE UPDATE OF merged_into ON item WHEN new.merged_into IS NOT NULL AND (
 (old.origin='catalogue' AND old.catalogue_retired_at IS NULL)
 OR (SELECT merged_into FROM item WHERE id=new.merged_into) IS NOT NULL
 OR (SELECT kind FROM item WHERE id=new.merged_into) IS NOT old.kind
 OR EXISTS(SELECT 1 FROM copy WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM copy_figure WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM copy_part WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM stock WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM stock_part WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM wish WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM fetched_inventory WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM fetched_inventory_part WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM fetched_inventory_figure WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM instruction_file WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM set_preference WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM order_line WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM order_line WHERE sticker_set_item_id=old.id)
 OR EXISTS(SELECT 1 FROM allocation WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM price_observation WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM price_current WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM price_watch WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM item_property WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM picture WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM photo WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM identification_action WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM stock_transfer WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM item_link WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM item_provider_status WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM job WHERE item_id=old.id))
 BEGIN SELECT RAISE(ABORT,'merge: only a local or retired item, of the same kind, after every reference moved'); END;
-- A kind change (Q10: a BrickLink type correcting a theme guess) keeps the id. It is refused while
-- a row that needs the old kind references the item; reconcile then records
-- item_provider_status(reason='kind_differs') instead of changing the kind.
CREATE TRIGGER item_kind_guard BEFORE UPDATE OF kind ON item WHEN new.kind IS NOT old.kind AND (
 EXISTS(SELECT 1 FROM copy AS t WHERE t.item_id=old.id AND new.kind != 'set')
 OR EXISTS(SELECT 1 FROM copy_figure AS t WHERE t.item_id=old.id AND new.kind != 'minifigure')
 OR EXISTS(SELECT 1 FROM copy_part AS t WHERE t.item_id=old.id AND new.kind != 'part')
 OR EXISTS(SELECT 1 FROM stock AS t WHERE t.item_id=old.id AND new.kind != t.kind)
 OR EXISTS(SELECT 1 FROM stock_part AS t WHERE t.item_id=old.id AND new.kind != 'part')
 OR EXISTS(SELECT 1 FROM wish AS t WHERE t.item_id=old.id AND new.kind != t.kind)
 OR EXISTS(SELECT 1 FROM fetched_inventory AS t WHERE t.item_id=old.id AND new.kind NOT IN ('set','minifigure'))
 OR EXISTS(SELECT 1 FROM fetched_inventory_part AS t WHERE t.item_id=old.id AND new.kind != 'part')
 OR EXISTS(SELECT 1 FROM fetched_inventory_figure AS t WHERE t.item_id=old.id AND new.kind != 'minifigure')
 OR EXISTS(SELECT 1 FROM instruction_file AS t WHERE t.item_id=old.id AND new.kind != 'set')
 OR EXISTS(SELECT 1 FROM set_preference AS t WHERE t.item_id=old.id AND new.kind != 'set'))
 BEGIN SELECT RAISE(ABORT,'kind change refused: the item is referenced as its current kind'); END;
CREATE TRIGGER item_redirect_guard BEFORE INSERT ON item_redirect
 WHEN (SELECT merged_into FROM item WHERE id=new.old_id) IS NOT new.new_id
 BEGIN SELECT RAISE(ABORT,'a redirect needs the merge it records'); END;

-- Not in this file, on purpose: no FTS in the collection file (catalogue search uses
-- catalogue.item_fts, numbers the user linked by hand are found through item_link_number);
-- no cross-file foreign keys (brickwork check verifies them); no runtime DDL.
