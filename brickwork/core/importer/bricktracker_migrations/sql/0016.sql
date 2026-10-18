-- description: Add BrickLink color fields to rebrickable_parts table

BEGIN TRANSACTION;

-- Add BrickLink color fields to the rebrickable_parts table
ALTER TABLE "rebrickable_parts" ADD COLUMN "bricklink_color_id" INTEGER;
ALTER TABLE "rebrickable_parts" ADD COLUMN "bricklink_color_name" TEXT;

COMMIT;