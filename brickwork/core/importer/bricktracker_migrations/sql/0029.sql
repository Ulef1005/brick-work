-- description: Add typed custom fields (admin-defined per-set fields)

BEGIN TRANSACTION;

-- Defines each custom field: an id, a name and a type (text / number / date).
-- The type only drives the input widget + light validation; the per-set value
-- is always stored as TEXT in a dynamic column on bricktracker_set_custom_fields.
CREATE TABLE "bricktracker_metadata_custom_fields" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "type" TEXT NOT NULL DEFAULT 'text',
    PRIMARY KEY("id")
);

-- Holds the per-set value of each custom field. A "custom_field_{id}" TEXT
-- column is added for every field created (mirroring the tag/status pattern).
CREATE TABLE "bricktracker_set_custom_fields" (
    "id" TEXT NOT NULL,
    PRIMARY KEY("id"),
    FOREIGN KEY("id") REFERENCES "bricktracker_sets"("id")
);

COMMIT;
