ALTER TABLE instruction_file ADD COLUMN thumbnail_path TEXT CHECK(thumbnail_path IS NULL OR (thumbnail_path LIKE 'data/instructions/%.thumb.png' AND instr(thumbnail_path,'..')=0));
ALTER TABLE instruction_file ADD COLUMN thumbnail_state TEXT CHECK(thumbnail_state IS NULL OR thumbnail_state IN ('pending','ready','failed'));
