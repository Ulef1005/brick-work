-- Instruction discovery references must remain unmerged sets, including direct SQL changes.
CREATE TRIGGER IF NOT EXISTS item_instruction_merge_guard BEFORE UPDATE OF merged_into ON item
 WHEN new.merged_into IS NOT NULL AND (
 EXISTS(SELECT 1 FROM instruction_search WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM instruction_candidate WHERE item_id=old.id))
 BEGIN SELECT RAISE(ABORT,'merge: instruction references must move first'); END;
CREATE TRIGGER IF NOT EXISTS item_instruction_kind_guard BEFORE UPDATE OF kind ON item
 WHEN new.kind IS NOT old.kind AND new.kind != 'set' AND (
 EXISTS(SELECT 1 FROM instruction_search WHERE item_id=old.id)
 OR EXISTS(SELECT 1 FROM instruction_candidate WHERE item_id=old.id))
 BEGIN SELECT RAISE(ABORT,'kind change refused: instruction references require a set'); END;
