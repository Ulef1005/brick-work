-- description: Creation of the deduplicated table of Rebrickable sets

BEGIN TRANSACTION;

-- Create a Rebrickable set table: each unique set imported from Rebrickable
CREATE TABLE "rebrickable_sets" (
    "set" TEXT NOT NULL,
    "number" INTEGER NOT NULL,
    "version" INTEGER NOT NULL,
    "name" TEXT NOT NULL,
    "year" INTEGER NOT NULL,
    "theme_id" INTEGER NOT NULL,
    "number_of_parts" INTEGER NOT NULL,
    "image" TEXT,
    "url" TEXT,
    "last_modified" TEXT,
    PRIMARY KEY("set")
);

-- Insert existing sets into the new table
INSERT INTO "rebrickable_sets" (
    "set",
    "number",
    "version",
    "name",
    "year",
    "theme_id",
    "number_of_parts",
    "image",
    "url",
    "last_modified"
)
SELECT
    "sets"."set_num",
    CAST(SUBSTR("sets"."set_num", 1, INSTR("sets"."set_num", '-') - 1) AS INTEGER),
    CAST(SUBSTR("sets"."set_num", INSTR("sets"."set_num", '-') + 1) AS INTEGER),
    "sets"."name",
    "sets"."year",
    "sets"."theme_id",
    "sets"."num_parts",
    "sets"."set_img_url",
    "sets"."set_url",
    "sets"."last_modified_dt"
FROM "sets"
GROUP BY
    "sets"."set_num";

COMMIT;