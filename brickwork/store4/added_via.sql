-- Where a row came from, schema 4.8 (#551). `origin` names every way a copy, a loose-stock row or a wish can arrive; a later way is one
-- INSERT in a later step (a lookup table, so no CHECK has to be rebuilt). NULL added_via: the row is older than 4.8 ("Before this release").
CREATE TABLE origin(id TEXT PRIMARY KEY NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('hand','site','file','import'))) STRICT;
INSERT INTO origin(id, kind) VALUES('hand','hand'),
 ('rebrickable','site'),('brickset','site'),('bricklink','site'),('brickowl','site'),
 ('bricklink_xml','file'),('rebrickable_csv','file'),('brickset_csv','file'),('brickowl_xml','file'),('brickwork_export','file'),
 ('bricktracker','import');
ALTER TABLE copy ADD COLUMN added_via TEXT REFERENCES origin(id);
ALTER TABLE stock ADD COLUMN added_via TEXT REFERENCES origin(id);
ALTER TABLE wish ADD COLUMN added_via TEXT REFERENCES origin(id);
CREATE INDEX copy_added_via ON copy(added_via);
CREATE INDEX stock_added_via ON stock(added_via);
CREATE INDEX wish_added_via ON wish(added_via);
CREATE TRIGGER copy_added_via_fixed BEFORE UPDATE OF added_via ON copy WHEN old.added_via IS NOT new.added_via
 BEGIN SELECT RAISE(ABORT,'added_via never changes'); END;
CREATE TRIGGER stock_added_via_fixed BEFORE UPDATE OF added_via ON stock WHEN old.added_via IS NOT new.added_via
 BEGIN SELECT RAISE(ABORT,'added_via never changes'); END;
CREATE TRIGGER wish_added_via_fixed BEFORE UPDATE OF added_via ON wish WHEN old.added_via IS NOT new.added_via
 BEGIN SELECT RAISE(ABORT,'added_via never changes'); END;
-- Last synced from: one row per site and list a row was matched to at a sync (a set in two lists has two). list_key '' is the site's
-- collection as a whole (no list); list_name is the site's name for the list as last read (#531). A run's receipt keeps the rows it changed.
CREATE TABLE synced_from(
 id INTEGER PRIMARY KEY,
 copy_id TEXT REFERENCES copy(id), stock_id TEXT REFERENCES stock(id), wish_id TEXT REFERENCES wish(id),
 site TEXT NOT NULL REFERENCES origin(id),
 list_key TEXT NOT NULL DEFAULT '', list_name TEXT,
 synced_at TEXT NOT NULL,
 CHECK((copy_id IS NOT NULL) + (stock_id IS NOT NULL) + (wish_id IS NOT NULL) = 1)) STRICT;
CREATE UNIQUE INDEX synced_from_key ON synced_from(coalesce(copy_id,''), coalesce(stock_id,''), coalesce(wish_id,''), site, list_key);
CREATE INDEX synced_from_copy ON synced_from(copy_id);
CREATE INDEX synced_from_stock ON synced_from(stock_id);
CREATE INDEX synced_from_wish ON synced_from(wish_id);
CREATE INDEX synced_from_site ON synced_from(site, list_key);
