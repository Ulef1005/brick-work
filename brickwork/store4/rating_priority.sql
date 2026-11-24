-- Your own rating and priority, schema 4.9 (#690): a copy's stars (1 to 5) and a wish's priority (1 highest). NULL: not set; every row older than 4.9 stays NULL.
ALTER TABLE copy ADD COLUMN rating INTEGER CHECK(rating IS NULL OR rating BETWEEN 1 AND 5);
ALTER TABLE wish ADD COLUMN priority INTEGER CHECK(priority IS NULL OR priority BETWEEN 1 AND 5);
