-- description: Migrate the Bricktracker parts (and missing parts), and add a bunch of extra fields for later

PRAGMA foreign_keys = ON;

BEGIN TRANSACTION;

-- Fix: somehow a deletion bug was introduced in an older release?
DELETE FROM "inventory"
WHERE "inventory"."u_id" NOT IN (
    SELECT "bricktracker_sets"."id"
    FROM "bricktracker_sets"
);

DELETE FROM "missing"
WHERE "missing"."u_id" NOT IN (
    SELECT "bricktracker_sets"."id"
    FROM "bricktracker_sets"
);

-- Create a Bricktracker parts table: an amount of parts linked to a Bricktracker set
CREATE TABLE "bricktracker_parts" (
    "id" TEXT NOT NULL,
    "figure" TEXT,
    "part" TEXT NOT NULL,
    "color" INTEGER NOT NULL,
    "spare" BOOLEAN NOT NULL,
    "quantity" INTEGER NOT NULL,
    "element" INTEGER,
    "rebrickable_inventory" INTEGER NOT NULL,
    "missing" INTEGER NOT NULL DEFAULT 0,
    "damaged" INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY("id", "figure", "part", "color", "spare"),
    FOREIGN KEY("id") REFERENCES "bricktracker_sets"("id"),
    FOREIGN KEY("figure") REFERENCES "rebrickable_minifigures"("figure"),
    FOREIGN KEY("part", "color") REFERENCES "rebrickable_parts"("part", "color_id")
);

-- Insert existing parts into the new table
INSERT INTO "bricktracker_parts" (
    "id",
    "figure",
    "part",
    "color",
    "spare",
    "quantity",
    "element",
    "rebrickable_inventory",
    "missing"
)
SELECT
    "inventory"."u_id",
    CASE WHEN SUBSTR("inventory"."set_num", 0, 5) = 'fig-' THEN "inventory"."set_num" ELSE NULL END,
    "inventory"."part_num",
    "inventory"."color_id",
    "inventory"."is_spare",
    "inventory"."quantity",
    "inventory"."element_id",
    "inventory"."id",
    IFNULL("missing"."quantity", 0)
FROM "inventory"
LEFT JOIN "missing"
ON "inventory"."set_num" IS NOT DISTINCT FROM "missing"."set_num"
AND "inventory"."id" IS NOT DISTINCT FROM "missing"."id"
AND "inventory"."part_num" IS NOT DISTINCT FROM "missing"."part_num"
AND "inventory"."color_id" IS NOT DISTINCT FROM "missing"."color_id"
AND "inventory"."element_id" IS NOT DISTINCT FROM "missing"."element_id"
AND "inventory"."u_id" IS NOT DISTINCT FROM "missing"."u_id";

-- Rename the original table (don't delete it yet?)
ALTER TABLE "inventory" RENAME TO "inventory_old";
ALTER TABLE "missing" RENAME TO "missing_old";

COMMIT;