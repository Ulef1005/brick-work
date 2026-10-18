-- description: Rename checkboxes to status metadata

BEGIN TRANSACTION;

ALTER TABLE "bricktracker_set_checkboxes" RENAME TO "bricktracker_metadata_statuses";

COMMIT;