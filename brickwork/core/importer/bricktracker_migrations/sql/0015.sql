-- description: Add number of parts for minifigures

BEGIN TRANSACTION;

-- Add the number_of_parts column to the minifigures
ALTER TABLE "rebrickable_minifigures"
ADD COLUMN "number_of_parts" INTEGER NOT NULL DEFAULT 0;

-- Update the number of parts for each minifigure
UPDATE "rebrickable_minifigures"
SET "number_of_parts" = "parts_sum"."number_of_parts"
FROM (
    SELECT
        "parts"."figure",
        SUM("parts"."quantity") as "number_of_parts"
    FROM (
        SELECT
            "bricktracker_parts"."figure",
            "bricktracker_parts"."quantity"
        FROM "bricktracker_parts"
        WHERE "bricktracker_parts"."figure" IS NOT NULL
        GROUP BY
            "bricktracker_parts"."figure",
            "bricktracker_parts"."part",
            "bricktracker_parts"."color",
            "bricktracker_parts"."spare"
    ) "parts"
    GROUP BY "parts"."figure"
) "parts_sum"
WHERE "rebrickable_minifigures"."figure" = "parts_sum"."figure";

COMMIT;
