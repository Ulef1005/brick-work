-- description: Standardize ON DELETE behavior for foreign keys (use RESTRICT everywhere)

BEGIN TRANSACTION;

-- Recreate bricktracker_individual_part_lots without ON DELETE SET NULL
-- This makes FK behavior consistent: prevent deletion of metadata if referenced

CREATE TABLE "bricktracker_individual_part_lots_new" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "name" TEXT,
    "description" TEXT,
    "created_date" REAL NOT NULL,
    "storage" TEXT,
    "purchase_location" TEXT,
    "purchase_date" REAL,
    "purchase_price" REAL,
    FOREIGN KEY("storage") REFERENCES "bricktracker_metadata_storages"("id"),
    FOREIGN KEY("purchase_location") REFERENCES "bricktracker_metadata_purchase_locations"("id")
);

-- Copy existing data
INSERT INTO "bricktracker_individual_part_lots_new"
SELECT * FROM "bricktracker_individual_part_lots";

-- Drop old table
DROP TABLE "bricktracker_individual_part_lots";

-- Rename new table
ALTER TABLE "bricktracker_individual_part_lots_new" RENAME TO "bricktracker_individual_part_lots";

-- Recreate indexes
CREATE INDEX IF NOT EXISTS "idx_individual_part_lots_created_date"
ON "bricktracker_individual_part_lots"("created_date");

CREATE INDEX IF NOT EXISTS "idx_individual_part_lots_storage"
ON "bricktracker_individual_part_lots"("storage");

CREATE INDEX IF NOT EXISTS "idx_individual_part_lots_purchase_location"
ON "bricktracker_individual_part_lots"("purchase_location");

COMMIT;
