-- description: Add performance indexes for individual parts and minifigure parts

BEGIN TRANSACTION;

-- Composite index for lot part listing (common query: list parts in a lot)
CREATE INDEX IF NOT EXISTS idx_individual_parts_lot_id_part_color
ON bricktracker_individual_parts(lot_id, part, color);

-- Problem tracking index for individual parts (common query: find parts with problems)
CREATE INDEX IF NOT EXISTS idx_individual_parts_missing_damaged
ON bricktracker_individual_parts(missing, damaged);

-- Checked state index for individual minifigure parts (common query: find unchecked parts)
CREATE INDEX IF NOT EXISTS idx_individual_minifigure_parts_checked
ON bricktracker_individual_minifigure_parts(id, checked);

COMMIT;
