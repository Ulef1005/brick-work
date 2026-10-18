-- description: Migrate the whislist to have a Rebrickable sets structure

BEGIN TRANSACTION;

-- Create a Rebrickable wish table: each unique (light) set imported from Rebrickable
CREATE TABLE "bricktracker_wishes" (
    "set" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "year" INTEGER NOT NULL,
    "theme_id" INTEGER NOT NULL,
    "number_of_parts" INTEGER NOT NULL,
    "image" TEXT,
    "url" TEXT,
    PRIMARY KEY("set")
);

-- Insert existing wishes into the new table
INSERT INTO "bricktracker_wishes" (
    "set",
    "name",
    "year",
    "theme_id",
    "number_of_parts",
    "image",
    "url"
)
SELECT
    "wishlist"."set_num",
    "wishlist"."name",
    "wishlist"."year",
    "wishlist"."theme_id",
    "wishlist"."num_parts",
    "wishlist"."set_img_url",
    "wishlist"."set_url"
FROM "wishlist"
GROUP BY
    "wishlist"."set_num";

-- Rename the original table (don't delete it yet?)
ALTER TABLE "wishlist" RENAME TO "wishlist_old";

COMMIT;