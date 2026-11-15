-- Storage label identities survive deletion and Undo; the counter is outside receipts.
ALTER TABLE storage ADD COLUMN short_id TEXT;
CREATE UNIQUE INDEX storage_short_id ON storage(short_id);
CREATE TABLE storage_label_sequence(singleton INTEGER PRIMARY KEY CHECK(singleton=1), value INTEGER NOT NULL) STRICT;
INSERT INTO storage_label_sequence VALUES(1, (SELECT count(*) FROM storage));
WITH ranked AS (SELECT id,row_number() OVER (ORDER BY created_at,id) AS n FROM storage)
UPDATE storage SET short_id=(SELECT printf('S-%04d',n) FROM ranked WHERE ranked.id=storage.id);
CREATE TRIGGER storage_label_identity AFTER INSERT ON storage WHEN NEW.short_id IS NULL BEGIN
 UPDATE storage_label_sequence SET value=value+1 WHERE singleton=1;
 UPDATE storage SET short_id=(SELECT printf('S-%04d',value) FROM storage_label_sequence WHERE singleton=1) WHERE id=NEW.id;
END;
