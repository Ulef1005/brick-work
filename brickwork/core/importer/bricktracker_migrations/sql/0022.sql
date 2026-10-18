-- description: Add individual part lots system for bulk/cart adding of parts

BEGIN TRANSACTION;

-- Create individual part lots table
CREATE TABLE IF NOT EXISTS "bricktracker_individual_part_lots" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "name" TEXT,
    "description" TEXT,
    "created_date" REAL NOT NULL,
    "storage" TEXT,
    "purchase_location" TEXT,
    "purchase_date" REAL,
    "purchase_price" REAL,
    FOREIGN KEY("storage") REFERENCES "bricktracker_metadata_storages"("id") ON DELETE SET NULL,
    FOREIGN KEY("purchase_location") REFERENCES "bricktracker_metadata_purchase_locations"("id") ON DELETE SET NULL
);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS "idx_individual_part_lots_created_date"
ON "bricktracker_individual_part_lots"("created_date");

-- Add missing/damaged/checked fields to individual parts table
ALTER TABLE "bricktracker_individual_parts"
ADD COLUMN "missing" INTEGER NOT NULL DEFAULT 0;

ALTER TABLE "bricktracker_individual_parts"
ADD COLUMN "damaged" INTEGER NOT NULL DEFAULT 0;

ALTER TABLE "bricktracker_individual_parts"
ADD COLUMN "checked" BOOLEAN NOT NULL DEFAULT 0;

-- Add lot_id column to individual parts table with foreign key constraint
-- Note: SQLite doesn't support ALTER TABLE ADD CONSTRAINT for FK, so we need to recreate the table

-- Create new table with FK constraint
CREATE TABLE "bricktracker_individual_parts_new" (
    "id" TEXT NOT NULL,
    "part" TEXT NOT NULL,
    "color" INTEGER NOT NULL,
    "quantity" INTEGER NOT NULL DEFAULT 1,
    "description" TEXT,
    "storage" TEXT,
    "purchase_date" REAL,
    "purchase_location" TEXT,
    "purchase_price" REAL,
    "missing" INTEGER NOT NULL DEFAULT 0,
    "damaged" INTEGER NOT NULL DEFAULT 0,
    "checked" BOOLEAN NOT NULL DEFAULT 0,
    "lot_id" TEXT,
    PRIMARY KEY("id"),
    FOREIGN KEY("part", "color") REFERENCES "rebrickable_parts"("part", "color_id"),
    FOREIGN KEY("storage") REFERENCES "bricktracker_metadata_storages"("id"),
    FOREIGN KEY("purchase_location") REFERENCES "bricktracker_metadata_purchase_locations"("id"),
    FOREIGN KEY("lot_id") REFERENCES "bricktracker_individual_part_lots"("id") ON DELETE SET NULL
);

-- Copy existing data (set lot_id to NULL for all existing parts)
INSERT INTO "bricktracker_individual_parts_new"
    (id, part, color, quantity, description, storage, purchase_date, purchase_location, purchase_price, missing, damaged, checked, lot_id)
SELECT
    id, part, color, quantity, description, storage, purchase_date, purchase_location, purchase_price, missing, damaged, checked, NULL
FROM "bricktracker_individual_parts";

-- Drop old table
DROP TABLE "bricktracker_individual_parts";

-- Rename new table
ALTER TABLE "bricktracker_individual_parts_new" RENAME TO "bricktracker_individual_parts";

-- Recreate existing indexes
CREATE INDEX IF NOT EXISTS idx_bricktracker_individual_parts_part_color
ON bricktracker_individual_parts(part, color);

CREATE INDEX IF NOT EXISTS idx_bricktracker_individual_parts_storage
ON bricktracker_individual_parts(storage);

CREATE INDEX IF NOT EXISTS idx_bricktracker_individual_parts_purchase_location
ON bricktracker_individual_parts(purchase_location);

CREATE INDEX IF NOT EXISTS idx_bricktracker_individual_parts_purchase_date
ON bricktracker_individual_parts(purchase_date);

-- Create lot_id index
CREATE INDEX IF NOT EXISTS "idx_individual_parts_lot_id"
ON "bricktracker_individual_parts"("lot_id");

-- Metadata for individual part lots: use bricktracker_set_owners and bricktracker_set_tags tables
-- Note: Part lots don't have statuses, only owners and tags

COMMIT;
