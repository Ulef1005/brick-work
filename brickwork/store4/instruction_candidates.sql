CREATE TABLE IF NOT EXISTS instruction_search(
 job_id INTEGER PRIMARY KEY REFERENCES job(id), item_id INTEGER NOT NULL REFERENCES item(id),
 sources_tried TEXT NOT NULL DEFAULT '[]', error TEXT, updated_at TEXT NOT NULL) STRICT;
CREATE TABLE IF NOT EXISTS instruction_candidate(
 id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL REFERENCES item(id),
 search_job INTEGER NOT NULL REFERENCES job(id), source TEXT NOT NULL REFERENCES source(id),
 title TEXT NOT NULL, booklet INTEGER NOT NULL CHECK(booklet>0), booklets INTEGER NOT NULL CHECK(booklets>=booklet),
 language TEXT, region TEXT, size INTEGER CHECK(size IS NULL OR size>=0), url TEXT NOT NULL,
 file_id INTEGER REFERENCES instruction_file(id), UNIQUE(item_id,source,url)) STRICT;
CREATE INDEX IF NOT EXISTS instruction_candidate_search ON instruction_candidate(search_job,booklet,id);
CREATE INDEX IF NOT EXISTS instruction_search_item ON instruction_search(item_id);
CREATE INDEX IF NOT EXISTS instruction_candidate_source ON instruction_candidate(source);
CREATE INDEX IF NOT EXISTS instruction_candidate_file ON instruction_candidate(file_id);
CREATE TRIGGER IF NOT EXISTS instruction_search_item_guard_insert BEFORE INSERT ON instruction_search WHEN ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT 'set')
 BEGIN SELECT RAISE(ABORT,'instruction_search.item_id: unmerged set needed'); END;
CREATE TRIGGER IF NOT EXISTS instruction_search_item_guard_update BEFORE UPDATE OF item_id ON instruction_search WHEN ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT 'set')
 BEGIN SELECT RAISE(ABORT,'instruction_search.item_id: unmerged set needed'); END;
CREATE TRIGGER IF NOT EXISTS instruction_candidate_item_guard_insert BEFORE INSERT ON instruction_candidate WHEN ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT 'set')
 BEGIN SELECT RAISE(ABORT,'instruction_candidate.item_id: unmerged set needed'); END;
CREATE TRIGGER IF NOT EXISTS instruction_candidate_item_guard_update BEFORE UPDATE OF item_id ON instruction_candidate WHEN ((SELECT merged_into FROM item WHERE id=new.item_id) IS NOT NULL OR (SELECT kind FROM item WHERE id=new.item_id) IS NOT 'set')
 BEGIN SELECT RAISE(ABORT,'instruction_candidate.item_id: unmerged set needed'); END;
