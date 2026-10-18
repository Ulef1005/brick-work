-- description: Change set number column from INTEGER to TEXT to support alphanumeric set numbers

-- Temporarily disable foreign key constraints for this migration
-- This is necessary because we're recreating a table that other tables reference
-- We verify integrity at the end to ensure safety
PRAGMA foreign_keys=OFF;

BEGIN TRANSACTION;

-- Create new table with TEXT number column
CREATE TABLE "rebrickable_sets_new" (
    "set" TEXT NOT NULL,
    "number" TEXT NOT NULL,
    "version" INTEGER NOT NULL,
    "name" TEXT NOT NULL,
    "year" INTEGER NOT NULL,
    "theme_id" INTEGER NOT NULL,
    "number_of_parts" INTEGER NOT NULL,
    "image" TEXT,
    "url" TEXT,
    "last_modified" TEXT,
    PRIMARY KEY("set")
);

-- Copy all data from old table to new table
-- Cast INTEGER number to TEXT explicitly
INSERT INTO "rebrickable_sets_new"
SELECT
    "set",
    CAST("number" AS TEXT),
    "version",
    "name",
    "year",
    "theme_id",
    "number_of_parts",
    "image",
    "url",
    "last_modified"
FROM "rebrickable_sets";

-- Drop old table
DROP TABLE "rebrickable_sets";

-- Rename new table to original name
ALTER TABLE "rebrickable_sets_new" RENAME TO "rebrickable_sets";

-- Recreate the index
CREATE INDEX IF NOT EXISTS idx_rebrickable_sets_number_version
ON rebrickable_sets(number, version);

-- Verify foreign key integrity before committing
-- This ensures we haven't broken any references
PRAGMA foreign_key_check;

COMMIT;

-- Re-enable foreign key constraints
PRAGMA foreign_keys=ON;
