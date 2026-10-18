-- description: Performance optimization indexes

-- High-impact composite index for problem parts aggregation
-- Used in set listings, statistics, and problem reports
CREATE INDEX IF NOT EXISTS idx_bricktracker_parts_id_missing_damaged
ON bricktracker_parts(id, missing, damaged);

-- Composite index for parts lookup by part and color
-- Used in part listings and filtering operations
CREATE INDEX IF NOT EXISTS idx_bricktracker_parts_part_color_spare
ON bricktracker_parts(part, color, spare);

-- Composite index for set storage filtering
-- Used in set listings filtered by storage location
CREATE INDEX IF NOT EXISTS idx_bricktracker_sets_set_storage
ON bricktracker_sets("set", storage);

-- Search optimization index for set names
-- Improves text search performance on set listings
CREATE INDEX IF NOT EXISTS idx_rebrickable_sets_name_lower
ON rebrickable_sets(LOWER(name));

-- Search optimization index for part names
-- Improves text search performance on part listings
CREATE INDEX IF NOT EXISTS idx_rebrickable_parts_name_lower
ON rebrickable_parts(LOWER(name));

-- Additional indexes for common join patterns

-- Set purchase filtering
CREATE INDEX IF NOT EXISTS idx_bricktracker_sets_purchase_location
ON bricktracker_sets(purchase_location);

-- Parts quantity filtering
CREATE INDEX IF NOT EXISTS idx_bricktracker_parts_quantity
ON bricktracker_parts(quantity);

-- Year-based filtering optimization
CREATE INDEX IF NOT EXISTS idx_rebrickable_sets_year
ON rebrickable_sets(year);

-- Theme-based filtering optimization
CREATE INDEX IF NOT EXISTS idx_rebrickable_sets_theme_id
ON rebrickable_sets(theme_id);

-- Rebrickable sets number and version for sorting
CREATE INDEX IF NOT EXISTS idx_rebrickable_sets_number_version
ON rebrickable_sets(number, version);

-- Purchase date filtering and sorting
CREATE INDEX IF NOT EXISTS idx_bricktracker_sets_purchase_date
ON bricktracker_sets(purchase_date);

-- Minifigures aggregation optimization
CREATE INDEX IF NOT EXISTS idx_bricktracker_minifigures_id_quantity
ON bricktracker_minifigures(id, quantity);