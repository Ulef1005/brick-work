-- description: Add checked field to bricktracker_parts table for part walkthrough tracking

BEGIN TRANSACTION;

-- Add checked field to the bricktracker_parts table
-- This allows users to track which parts they have checked during walkthroughs
ALTER TABLE "bricktracker_parts" ADD COLUMN "checked" BOOLEAN DEFAULT 0;

COMMIT;