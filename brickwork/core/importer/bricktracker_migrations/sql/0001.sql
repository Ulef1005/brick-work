-- description: Original database initialization
-- FROM sqlite3 app.db .schema > init.sql with extra IF NOT EXISTS, transaction and quotes
BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS "wishlist" (
    "set_num" TEXT,
    "name" TEXT,
    "year" INTEGER,
    "theme_id" INTEGER,
    "num_parts" INTEGER,
    "set_img_url" TEXT,
    "set_url" TEXT,
    "last_modified_dt" TEXT
);

CREATE TABLE IF NOT EXISTS "sets" (
    "set_num" TEXT,
    "name" TEXT,
    "year" INTEGER,
    "theme_id" INTEGER,
    "num_parts" INTEGER,
    "set_img_url" TEXT,
    "set_url" TEXT,
    "last_modified_dt" TEXT,
    "mini_col" BOOLEAN,
    "set_check" BOOLEAN,
    "set_col" BOOLEAN,
    "u_id" TEXT
);

CREATE TABLE IF NOT EXISTS "inventory" (
    "set_num" TEXT,
    "id" INTEGER,
    "part_num" TEXT,
    "name" TEXT,
    "part_img_url" TEXT,
    "part_img_url_id" TEXT,
    "color_id" INTEGER,
    "color_name" TEXT,
    "quantity" INTEGER,
    "is_spare" BOOLEAN,
    "element_id" INTEGER,
    "u_id" TEXT
);

CREATE TABLE IF NOT EXISTS "minifigures" (
    "fig_num" TEXT,
    "set_num" TEXT,
    "name" TEXT,
    "quantity" INTEGER,
    "set_img_url" TEXT,
    "u_id" TEXT
);

CREATE TABLE IF NOT EXISTS "missing" (
    "set_num" TEXT,
    "id" INTEGER,
    "part_num" TEXT,
    "part_img_url_id" TEXT,
    "color_id" INTEGER,
    "quantity" INTEGER,
    "element_id" INTEGER,
    "u_id" TEXT
);

COMMIT;