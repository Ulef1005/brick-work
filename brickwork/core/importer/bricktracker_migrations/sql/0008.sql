-- description: Creation of the deduplicated table of Rebrickable minifigures

BEGIN TRANSACTION;

-- Create a Rebrickable minifigures table: each unique minifigure imported from Rebrickable
CREATE TABLE "rebrickable_minifigures" (
    "figure" TEXT NOT NULL,
    "number" INTEGER NOT NULL,
    "name" TEXT NOT NULL,
    "image" TEXT,
    PRIMARY KEY("figure")
);

-- Insert existing sets into the new table
INSERT INTO "rebrickable_minifigures" (
    "figure",
    "number",
    "name",
    "image"
)
SELECT
    "minifigures"."fig_num",
    CAST(SUBSTR("minifigures"."fig_num", 5) AS INTEGER),
    "minifigures"."name",
    "minifigures"."set_img_url"
FROM "minifigures"
GROUP BY
    "minifigures"."fig_num";

COMMIT;