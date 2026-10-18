-- description: Add set owners

BEGIN TRANSACTION;

-- Create a table to define each set owners: an id and a name
CREATE TABLE "bricktracker_metadata_owners" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    PRIMARY KEY("id")
);

-- Create a table for the set owners
CREATE TABLE "bricktracker_set_owners" (
    "id" TEXT NOT NULL,
    PRIMARY KEY("id"),
    FOREIGN KEY("id") REFERENCES "bricktracker_sets"("id")
);

-- Create a table for the wish owners
CREATE TABLE "bricktracker_wish_owners" (
    "set" TEXT NOT NULL,
    PRIMARY KEY("set"),
    FOREIGN KEY("set") REFERENCES "bricktracker_wishes"("set")
);

COMMIT;
