-- description: Remove foreign key constraints from consolidated metadata tables

-- This migration is implemented entirely in Python (see migrations/0027.py)
-- The Python code dynamically recreates bricktracker_set_owners, bricktracker_set_tags,
-- and bricktracker_set_statuses without foreign key constraints so they can accept
-- UUIDs from any entity type (sets, individual parts, individual minifigures, part lots)
