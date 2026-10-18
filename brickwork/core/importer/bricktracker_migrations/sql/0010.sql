-- description: Creation of the deduplicated table of Rebrickable parts, and add a bunch of extra fields for later

BEGIN TRANSACTION;

-- Create a Rebrickable parts table: each unique part imported from Rebrickable
CREATE TABLE "rebrickable_parts" (
    "part" TEXT NOT NULL,
    "color_id" INTEGER NOT NULL,
    "color_name" TEXT NOT NULL,
    "color_rgb" TEXT, -- can be NULL because it was not saved before
    "color_transparent" BOOLEAN, -- can be NULL because it was not saved before
    "name" TEXT NOT NULL,
    "category" INTEGER, -- can be NULL because it was not saved before
    "image" TEXT,
    "image_id" TEXT,
    "url" TEXT, -- can be NULL because it was not saved before
    "print" INTEGER, -- can be NULL, was not saved before
    PRIMARY KEY("part", "color_id")
);

-- Insert existing parts into the new table
INSERT INTO "rebrickable_parts" (
    "part",
    "color_id",
    "color_name",
    "name",
    "image",
    "image_id"
)
SELECT
    "inventory"."part_num",
    "inventory"."color_id",
    "inventory"."color_name",
    "inventory"."name",
    "inventory"."part_img_url",
    "inventory"."part_img_url_id"
FROM "inventory"
GROUP BY
    "inventory"."part_num",
    "inventory"."color_id";

COMMIT;