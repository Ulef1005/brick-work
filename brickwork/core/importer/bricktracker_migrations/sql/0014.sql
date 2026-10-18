-- description: Add set tags

BEGIN TRANSACTION;

-- Create a table to define each set tags: an id and a name
CREATE TABLE "bricktracker_metadata_tags" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    PRIMARY KEY("id")
);

-- Create a table for the set tags
CREATE TABLE "bricktracker_set_tags" (
    "id" TEXT NOT NULL,
    PRIMARY KEY("id"),
    FOREIGN KEY("id") REFERENCES "bricktracker_sets"("id")
);

COMMIT;
