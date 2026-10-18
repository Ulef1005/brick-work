-- description: Add sidecar_set_cache table for brickset-sidecar metadata and price caching

BEGIN TRANSACTION;

-- Caches responses from the optional brickset-sidecar so we never hammer it.
-- payload        : JSON of GET /sets/{ref} (effectively permanent, refresh on demand)
-- price_payload  : JSON of GET /sets/{ref}/price (honours SIDECAR_PRICE_CACHE_HOURS TTL)
-- *_fetched_at   : epoch seconds (REAL) of when each payload was stored
CREATE TABLE IF NOT EXISTS "sidecar_set_cache" (
    "set_ref" TEXT NOT NULL PRIMARY KEY,
    "payload" TEXT,
    "price_payload" TEXT,
    "fetched_at" REAL,
    "price_fetched_at" REAL
);

COMMIT;
