-- description: Add per-bag part state (checked/missing) for sidecar bag inventories

BEGIN TRANSACTION;

-- Per-bag progress for sets with a sidecar bag inventory. The bag composition
-- itself is never persisted (joined from the sidecar at render time); this
-- only stores what the user ticked/typed per bag. The main parts row's
-- missing count is kept as the sum of these per-bag values client-side.
CREATE TABLE "bricktracker_bag_parts" (
    "id" TEXT NOT NULL,
    "bag" TEXT NOT NULL,
    "part" TEXT NOT NULL,
    "color" INTEGER NOT NULL,
    "spare" INTEGER NOT NULL DEFAULT 0,
    "checked" INTEGER NOT NULL DEFAULT 0,
    "missing" INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY("id", "bag", "part", "color", "spare"),
    FOREIGN KEY("id") REFERENCES "bricktracker_sets"("id")
);

COMMIT;
