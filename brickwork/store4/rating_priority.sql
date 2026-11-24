-- Your own rating and priority, schema 4.9 (#690): a copy's stars (1 to 5) and a wish's priority (1 or more, 1 highest). NULL: not set; every row older than 4.9 stays NULL.
ALTER TABLE copy ADD COLUMN rating INTEGER;
ALTER TABLE wish ADD COLUMN priority INTEGER;
-- Brick Owl is a source like the other three sites, so its calls count against a daily budget (#522). Idempotent; a user's enabled=0 stays.
INSERT OR IGNORE INTO source(id,name,kind,enabled) VALUES('brickowl','Brick Owl','api',1);
