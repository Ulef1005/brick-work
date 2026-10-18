-- description: Create rebrickable_colors translation table for BrickLink color ID mapping
-- This table caches color information from Rebrickable API to avoid repeated API calls
-- and provides mapping between Rebrickable and BrickLink color IDs

CREATE TABLE IF NOT EXISTS "rebrickable_colors" (
    "color_id" INTEGER PRIMARY KEY,
    "name" TEXT NOT NULL,
    "rgb" TEXT,
    "is_trans" BOOLEAN,
    "bricklink_color_id" INTEGER,
    "bricklink_color_name" TEXT
);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS "idx_rebrickable_colors_bricklink"
ON "rebrickable_colors"("bricklink_color_id");
