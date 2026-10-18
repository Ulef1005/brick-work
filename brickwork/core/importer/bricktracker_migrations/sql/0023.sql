-- description: Add missing indexes for individual part lots optimization

BEGIN TRANSACTION;

-- Add storage index for lots table (for filtering by storage)
CREATE INDEX IF NOT EXISTS "idx_individual_part_lots_storage"
ON "bricktracker_individual_part_lots"("storage");

-- Add purchase location index for lots table (for filtering by purchase location)
CREATE INDEX IF NOT EXISTS "idx_individual_part_lots_purchase_location"
ON "bricktracker_individual_part_lots"("purchase_location");

COMMIT;
