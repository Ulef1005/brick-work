-- description: WAL journal, 'None' fix for missing table

-- Set the journal mode to WAL
PRAGMA journal_mode = WAL;

BEGIN TRANSACTION;

-- Fix a bug where 'None' was inserted in missing instead of NULL
UPDATE "missing"
SET "element_id" = NULL
WHERE "missing"."element_id" = 'None';

COMMIT;