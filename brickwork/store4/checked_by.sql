ALTER TABLE copy ADD COLUMN checked_by TEXT CHECK(checked_by IS NULL OR checked_by IN ('rebrickable'));
