-- description: Add individual minifigures and individual parts tables

-- Individual minifigures table - tracks individual minifigures not associated with sets
CREATE TABLE IF NOT EXISTS "bricktracker_individual_minifigures" (
    "id" TEXT NOT NULL,
    "figure" TEXT NOT NULL,
    "quantity" INTEGER NOT NULL DEFAULT 1,
    "description" TEXT,
    "storage" TEXT, -- Storage bin location
    "purchase_date" REAL, -- Purchase date
    "purchase_location" TEXT, -- Purchase location
    "purchase_price" REAL, -- Purchase price
    PRIMARY KEY("id"),
    FOREIGN KEY("figure") REFERENCES "rebrickable_minifigures"("figure"),
    FOREIGN KEY("storage") REFERENCES "bricktracker_metadata_storages"("id"),
    FOREIGN KEY("purchase_location") REFERENCES "bricktracker_metadata_purchase_locations"("id")
);

-- Metadata for individual minifigures: use bricktracker_set_owners, bricktracker_set_tags, bricktracker_set_statuses tables

-- Parts table for individual minifigures - tracks constituent parts
CREATE TABLE IF NOT EXISTS "bricktracker_individual_minifigure_parts" (
    "id" TEXT NOT NULL,
    "part" TEXT NOT NULL,
    "color" INTEGER NOT NULL,
    "spare" BOOLEAN NOT NULL,
    "quantity" INTEGER NOT NULL,
    "element" INTEGER,
    "rebrickable_inventory" INTEGER NOT NULL,
    "missing" INTEGER NOT NULL DEFAULT 0,
    "damaged" INTEGER NOT NULL DEFAULT 0,
    "checked" BOOLEAN DEFAULT 0,
    PRIMARY KEY("id", "part", "color", "spare"),
    FOREIGN KEY("id") REFERENCES "bricktracker_individual_minifigures"("id"),
    FOREIGN KEY("part", "color") REFERENCES "rebrickable_parts"("part", "color_id")
);

-- Individual parts table - tracks individual parts not associated with sets
CREATE TABLE IF NOT EXISTS "bricktracker_individual_parts" (
    "id" TEXT NOT NULL,
    "part" TEXT NOT NULL,
    "color" INTEGER NOT NULL,
    "quantity" INTEGER NOT NULL DEFAULT 1,
    "description" TEXT,
    "storage" TEXT, -- Storage bin location
    "purchase_date" REAL, -- Purchase date
    "purchase_location" TEXT, -- Purchase location
    "purchase_price" REAL, -- Purchase price
    PRIMARY KEY("id"),
    FOREIGN KEY("part", "color") REFERENCES "rebrickable_parts"("part", "color_id"),
    FOREIGN KEY("storage") REFERENCES "bricktracker_metadata_storages"("id"),
    FOREIGN KEY("purchase_location") REFERENCES "bricktracker_metadata_purchase_locations"("id")
);

-- Metadata for individual parts: use bricktracker_set_owners, bricktracker_set_tags, bricktracker_set_statuses tables

-- Indexes for individual minifigures
CREATE INDEX IF NOT EXISTS idx_bricktracker_individual_minifigures_figure
ON bricktracker_individual_minifigures(figure);

CREATE INDEX IF NOT EXISTS idx_bricktracker_individual_minifigures_storage
ON bricktracker_individual_minifigures(storage);

CREATE INDEX IF NOT EXISTS idx_bricktracker_individual_minifigures_purchase_location
ON bricktracker_individual_minifigures(purchase_location);

CREATE INDEX IF NOT EXISTS idx_bricktracker_individual_minifigures_purchase_date
ON bricktracker_individual_minifigures(purchase_date);

-- Indexes for individual minifigure parts
CREATE INDEX IF NOT EXISTS idx_bricktracker_individual_minifigure_parts_id_missing_damaged
ON bricktracker_individual_minifigure_parts(id, missing, damaged);

CREATE INDEX IF NOT EXISTS idx_bricktracker_individual_minifigure_parts_part_color
ON bricktracker_individual_minifigure_parts(part, color);

-- Indexes for individual parts
CREATE INDEX IF NOT EXISTS idx_bricktracker_individual_parts_part_color
ON bricktracker_individual_parts(part, color);

CREATE INDEX IF NOT EXISTS idx_bricktracker_individual_parts_storage
ON bricktracker_individual_parts(storage);

CREATE INDEX IF NOT EXISTS idx_bricktracker_individual_parts_purchase_location
ON bricktracker_individual_parts(purchase_location);

CREATE INDEX IF NOT EXISTS idx_bricktracker_individual_parts_purchase_date
ON bricktracker_individual_parts(purchase_date);
