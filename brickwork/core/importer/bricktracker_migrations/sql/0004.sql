-- description: Migrate the Bricktracker sets

PRAGMA foreign_keys = ON;

BEGIN TRANSACTION;

-- Create a Bricktracker set table: with their unique IDs, and a reference to the Rebrickable set
CREATE TABLE "bricktracker_sets" (
    "id" TEXT NOT NULL,
    "rebrickable_set" TEXT NOT NULL,
    PRIMARY KEY("id"),
    FOREIGN KEY("rebrickable_set") REFERENCES "rebrickable_sets"("set")
);

-- Insert existing sets into the new table
INSERT INTO "bricktracker_sets" (
    "id",
    "rebrickable_set"
)
SELECT
    "sets"."u_id",
    "sets"."set_num"
FROM "sets";

COMMIT;