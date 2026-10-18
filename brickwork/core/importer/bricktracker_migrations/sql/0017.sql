-- description: Add BrickLink part number field to rebrickable_parts table

BEGIN TRANSACTION;

-- Add BrickLink part number field to the rebrickable_parts table
ALTER TABLE "rebrickable_parts" ADD COLUMN "bricklink_part_num" TEXT;

COMMIT;