-- description: Renaming various complicated field names to something simpler, and add a bunch of extra fields for later

PRAGMA foreign_keys = ON;

BEGIN TRANSACTION;

-- Rename sets table
ALTER TABLE "bricktracker_sets" RENAME TO "bricktracker_sets_old";

-- Create a Bricktracker metadata storage table for later
CREATE TABLE "bricktracker_metadata_storages" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    PRIMARY KEY("id")
);

-- Create a Bricktracker metadata purchase location table for later
CREATE TABLE "bricktracker_metadata_purchase_locations" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    PRIMARY KEY("id")
);

-- Re-Create a Bricktracker set table with the simplified name
CREATE TABLE "bricktracker_sets" (
    "id" TEXT NOT NULL,
    "set" TEXT NOT NULL,
    "description" TEXT,
    "storage" TEXT, -- Storage bin location
    "purchase_date" REAL, -- Purchase data
    "purchase_location" TEXT, -- Purchase location
    "purchase_price" REAL, -- Purchase price
    PRIMARY KEY("id"),
    FOREIGN KEY("set") REFERENCES "rebrickable_sets"("set"),
    FOREIGN KEY("storage") REFERENCES "bricktracker_metadata_storages"("id"),
    FOREIGN KEY("purchase_location") REFERENCES "bricktracker_metadata_purchase_locations"("id")
);

-- Insert existing sets into the new table
INSERT INTO "bricktracker_sets" (
    "id",
    "set"
)
SELECT
    "bricktracker_sets_old"."id",
    "bricktracker_sets_old"."rebrickable_set"
FROM "bricktracker_sets_old";

-- Rename status table
ALTER TABLE "bricktracker_set_statuses" RENAME TO "bricktracker_set_statuses_old";

-- Re-create a table for the status of each checkbox
CREATE TABLE "bricktracker_set_statuses" (
    "id" TEXT NOT NULL,
    {% if structure %}{{ structure }},{% endif %}
    PRIMARY KEY("id"),
    FOREIGN KEY("id") REFERENCES "bricktracker_sets"("id")
);

-- Insert existing status into the new table
INSERT INTO "bricktracker_set_statuses" (
    {% if targets %}{{ targets }},{% endif %}
    "id"
)
SELECT
    {% if sources %}{{ sources }},{% endif %}
    "bricktracker_set_statuses_old"."bricktracker_set_id"
FROM "bricktracker_set_statuses_old";

-- Delete the original tables
DROP TABLE "bricktracker_set_statuses_old";
DROP TABLE "bricktracker_sets_old";

COMMIT;