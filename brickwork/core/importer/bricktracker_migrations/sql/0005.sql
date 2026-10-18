-- description: Creation of the configurable set checkboxes

PRAGMA foreign_keys = ON;

BEGIN TRANSACTION;

-- Create a table to define each set checkbox: with an ID, a name and if they should be displayed on the grid cards
CREATE TABLE "bricktracker_set_checkboxes" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "displayed_on_grid" BOOLEAN NOT NULL DEFAULT 0,
    PRIMARY KEY("id")
);

-- Seed our checkbox with the 3 original ones
INSERT INTO "bricktracker_set_checkboxes" (
    "id",
    "name",
    "displayed_on_grid"
) VALUES (
    "minifigures_collected",
    "Minifigures are collected",
    1
);

INSERT INTO "bricktracker_set_checkboxes" (
    "id",
    "name",
    "displayed_on_grid"
) VALUES (
    "set_checked",
    "Set is checked",
    1
);

INSERT INTO "bricktracker_set_checkboxes" (
    "id",
    "name",
    "displayed_on_grid"
) VALUES (
    "set_collected",
    "Set is collected and boxed",
    1
);

-- Create a table for the status of each checkbox: with the 3 first status
CREATE TABLE "bricktracker_set_statuses" (
    "bricktracker_set_id" TEXT NOT NULL,
    "status_minifigures_collected" BOOLEAN NOT NULL DEFAULT 0,
    "status_set_checked" BOOLEAN NOT NULL DEFAULT 0,
    "status_set_collected" BOOLEAN NOT NULL DEFAULT 0,
    PRIMARY KEY("bricktracker_set_id"),
    FOREIGN KEY("bricktracker_set_id") REFERENCES "bricktracker_sets"("id")
);

INSERT INTO "bricktracker_set_statuses" (
    "bricktracker_set_id",
    "status_minifigures_collected",
    "status_set_checked",
    "status_set_collected"
)
SELECT
    "sets"."u_id",
    "sets"."mini_col",
    "sets"."set_check",
    "sets"."set_col"
FROM "sets";

-- Rename the original table (don't delete it yet?)
ALTER TABLE "sets" RENAME TO "sets_old";

COMMIT;
