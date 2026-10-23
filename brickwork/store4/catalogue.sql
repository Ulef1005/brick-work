-- Brick Work schema 4.0, revision 2: DDL for both files (design, not shipped code).
-- See v2/data-model-design.md. Requirements: SQLite >= 3.37 (STRICT), >= 3.31 (generated
-- columns), FTS5. Tested on SQLite 3.54.1 (python3 sqlite3); the test log is in the design's § 12.
--
-- Conventions: singular table names; stored words, not codes; timestamps ISO-8601 UTC text;
-- money is decimal text with a currency; user-owned rows are archived, never deleted;
-- catalogue rows are retired, never deleted; copy and figure lines are retired, never deleted.
--
-- Ids (design § 3.1): running numbers. Catalogue items and colours are numbered from 1 by the
-- catalogue builder, seeded by born key so a re-download keeps every id. Items and colours born
-- in the collection file ("local": BrickLink-born, fetched through the Rebrickable API,
-- unidentified) are numbered from LOCAL_BASE = 1000000000, so the two sources never collide.
-- Collection rows that people own (copy, stock, wish, ...) keep uuid text ids.
--
-- The two halves below are loaded into two separate databases. Nothing in one half has an
-- SQLite foreign key into the other; cross-file references are item ids, colour ids and the
-- natural key (item_id, version) of a catalogue inventory. `brickwork check` verifies them.

-- =====================================================================
-- FILE 1: catalogue.db
-- Reference data, rebuildable from the Rebrickable dump, the shipped mappings, an optional
-- local mapping under data/mappings/ and the optional BrickLink item lists. Written only by
-- the catalogue builder, which builds a new file beside the old one and swaps it in.
-- PRAGMA journal_mode=DELETE (one self-contained file for Borg, read-only attach needs no -shm);
-- PRAGMA foreign_keys=ON. The app opens it read-only.
-- =====================================================================

CREATE TABLE meta(key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL) STRICT;
-- keys: schema_version='catalogue-4.0'; catalogue_id (uuid of the id space: kept by every
-- seeded build, minted new only by an unseeded first build); item_high_water and
-- color_high_water (the highest running number ever minted here: never reused); created_at.

CREATE TABLE build(                                   -- one row per build step; carried into every rebuilt file
 id INTEGER PRIMARY KEY,
 kind TEXT NOT NULL CHECK(kind IN ('rebrickable_dump','mapping','bricklink_list','bricklink_colors')),
 seeded_from TEXT CHECK(seeded_from IS NULL OR seeded_from IN ('catalogue','collection','none')),
 started_at TEXT NOT NULL, finished_at TEXT,
 app_version TEXT NOT NULL, mapping_version TEXT,
 files_json TEXT NOT NULL,                            -- [{name, bytes, sha256, rows}] of every input (decision 9)
 counts_json TEXT NOT NULL,
 job_id INTEGER,                                      -- the collection job that ran it (cross-file, no FK)
 note TEXT) STRICT;

-- Themes and part categories keep Rebrickable's own ids: nothing outside this file references
-- them (the collection projects their names), so they need no Brick Work id.
CREATE TABLE theme(
 id INTEGER PRIMARY KEY,                              -- themes.csv id
 name TEXT NOT NULL, parent_id INTEGER REFERENCES theme(id),
 item_kind TEXT CHECK(item_kind IS NULL OR item_kind IN ('set','instructions','gear','book','catalog')),
                                                      -- Q10: from mappings/theme_kinds.csv; applied to zero-part sets only
 build_id INTEGER NOT NULL REFERENCES build(id), retired_at TEXT) STRICT;

CREATE TABLE part_category(
 id INTEGER PRIMARY KEY,                              -- part_categories.csv id
 name TEXT NOT NULL,
 build_id INTEGER NOT NULL REFERENCES build(id), retired_at TEXT) STRICT;

CREATE TABLE color(
 id INTEGER PRIMARY KEY CHECK(id>0 AND id<1000000000),
 name TEXT NOT NULL, rgb TEXT CHECK(rgb IS NULL OR length(rgb)=6), is_trans INTEGER NOT NULL CHECK(is_trans IN (0,1)),
 born_provider TEXT NOT NULL CHECK(born_provider='rebrickable'), born_key TEXT NOT NULL,
 build_id INTEGER NOT NULL REFERENCES build(id), retired_at TEXT,
 -- Two fixed ids, known before any catalogue exists: 1 = "no colour" (Rebrickable 9999),
 -- 2 = "unknown" (Rebrickable -1).
 CHECK((born_key='9999') = (id=1)), CHECK((born_key='-1') = (id=2))) STRICT;
CREATE UNIQUE INDEX color_born ON color(born_provider, born_key);

CREATE TABLE item(
 id INTEGER PRIMARY KEY CHECK(id>0),
 kind TEXT NOT NULL CHECK(kind IN ('set','part','minifigure','instructions','box','gear','book','catalog')),
 kind_source TEXT NOT NULL CHECK(kind_source IN ('namespace','theme','bricklink')),
                                                      -- Q10: 'namespace' = the Rebrickable table says it (sets with parts,
                                                      -- parts, figures); 'theme' = a zero-part set classified by its theme
                                                      -- (a guess); 'bricklink' = a BrickLink type corrected it.
                                                      -- The kind is not part of the id: a correction is an UPDATE.
 name TEXT NOT NULL, name_key TEXT NOT NULL, size_key TEXT,
 year INTEGER, num_parts INTEGER,
 theme_id INTEGER REFERENCES theme(id), category_id INTEGER REFERENCES part_category(id),
 material TEXT, img_url TEXT,
 born_provider TEXT NOT NULL CHECK(born_provider='rebrickable'),
 born_namespace TEXT NOT NULL CHECK(born_namespace IN ('sets','parts','minifigs')),
 born_key TEXT NOT NULL,                              -- set_num / part_num / fig_num
 adopted INTEGER NOT NULL DEFAULT 0 CHECK(adopted IN (0,1)),
                                                      -- 1: the id was first minted in the collection file (a set fetched
                                                      -- through the Rebrickable API before the dump had it) and adopted here
 build_id INTEGER NOT NULL REFERENCES build(id),
 digest TEXT NOT NULL,                                -- sha256 of the provider row (decision 9)
 retired_at TEXT,
 CHECK(id<1000000000 OR adopted=1),
 CHECK(born_namespace='sets' OR kind_source='namespace'),      -- parts and figures never change kind
 CHECK(kind_source!='namespace' OR kind=CASE born_namespace WHEN 'sets' THEN 'set' WHEN 'parts' THEN 'part' ELSE 'minifigure' END)) STRICT;
CREATE UNIQUE INDEX item_born ON item(born_provider, born_namespace, born_key);
CREATE INDEX item_kind_name ON item(kind, name_key);
CREATE INDEX item_size ON item(kind, size_key);
CREATE INDEX item_theme ON item(theme_id);
CREATE INDEX item_category ON item(category_id);

-- A Rebrickable part list of one set or figure at one version. The id is internal to this file
-- and may change between builds: the collection names an inventory by (item_id, version).
CREATE TABLE inventory(
 id INTEGER PRIMARY KEY,
 item_id INTEGER NOT NULL REFERENCES item(id),        -- the set or minifigure
 version INTEGER NOT NULL CHECK(version>0),            -- Rebrickable's version (gaps exist: 11 parents)
 ordinal INTEGER NOT NULL CHECK(ordinal>0),            -- "version n of m"
 is_latest INTEGER NOT NULL CHECK(is_latest IN (0,1)),
 rb_inventory_id INTEGER,                             -- inventories.csv id, kept as evidence only
 build_id INTEGER NOT NULL REFERENCES build(id),
 digest TEXT NOT NULL,                                -- sha256 over the sorted lines in Brick Work ids
 bl_digest TEXT,                                      -- the same lines projected to BrickLink keys (migration, Q12)
 part_lines INTEGER NOT NULL, figure_lines INTEGER NOT NULL, set_lines INTEGER NOT NULL,
 retired_at TEXT,
 UNIQUE(item_id, version)) STRICT;
CREATE UNIQUE INDEX inventory_one_latest ON inventory(item_id) WHERE is_latest=1;

-- Line tables have no surrogate id (Rebrickable's dump has none, so one could never be stable):
-- the line key is the primary key, and WITHOUT ROWID stores the table as that index.
CREATE TABLE inventory_part(
 inventory_id INTEGER NOT NULL REFERENCES inventory(id),
 item_id INTEGER NOT NULL REFERENCES item(id),
 color_id INTEGER NOT NULL REFERENCES color(id),
 is_spare INTEGER NOT NULL CHECK(is_spare IN (0,1)),
 quantity INTEGER NOT NULL CHECK(quantity>0),
 PRIMARY KEY(inventory_id, item_id, color_id, is_spare)) STRICT, WITHOUT ROWID;
CREATE INDEX inventory_part_item ON inventory_part(item_id, color_id);   -- where-used, Matcher, Part Picker

CREATE TABLE inventory_figure(
 inventory_id INTEGER NOT NULL REFERENCES inventory(id),
 item_id INTEGER NOT NULL REFERENCES item(id),
 quantity INTEGER NOT NULL CHECK(quantity>0),
 PRIMARY KEY(inventory_id, item_id)) STRICT, WITHOUT ROWID;
CREATE INDEX inventory_figure_item ON inventory_figure(item_id);

CREATE TABLE inventory_set(                            -- bundles and series (#30); stored, unused by 4.0 screens
 inventory_id INTEGER NOT NULL REFERENCES inventory(id),
 item_id INTEGER NOT NULL REFERENCES item(id),
 quantity INTEGER NOT NULL CHECK(quantity>0),
 PRIMARY KEY(inventory_id, item_id)) STRICT, WITHOUT ROWID;
CREATE INDEX inventory_set_item ON inventory_set(item_id);

CREATE TABLE element(
 element_id TEXT PRIMARY KEY NOT NULL,
 item_id INTEGER NOT NULL REFERENCES item(id), color_id INTEGER NOT NULL REFERENCES color(id),
 design_id TEXT) STRICT, WITHOUT ROWID;
CREATE INDEX element_part ON element(item_id, color_id);

CREATE TABLE part_relationship(
 rel_type TEXT NOT NULL CHECK(rel_type IN ('A','B','M','P','R','T')),
 child_item_id INTEGER NOT NULL REFERENCES item(id),
 parent_item_id INTEGER NOT NULL REFERENCES item(id),
 PRIMARY KEY(rel_type, child_item_id, parent_item_id)) STRICT, WITHOUT ROWID;
CREATE INDEX part_relationship_parent ON part_relationship(parent_item_id);
CREATE INDEX part_relationship_child ON part_relationship(child_item_id);

CREATE TABLE picture_url(
 item_id INTEGER NOT NULL REFERENCES item(id), color_id INTEGER NOT NULL REFERENCES color(id),
 url TEXT NOT NULL,
 PRIMARY KEY(item_id, color_id)) STRICT, WITHOUT ROWID;

-- Links that the mappings and the BrickLink list establish. Only links with a provider key live
-- here; "no match known" is the absence of a row (the collection records it per item).
CREATE TABLE item_link(
 id INTEGER PRIMARY KEY,
 item_id INTEGER NOT NULL REFERENCES item(id),
 color_id INTEGER REFERENCES color(id),               -- NULL: every colour; set: this colour only (decision E, leg rule)
 color_key INTEGER GENERATED ALWAYS AS (coalesce(color_id,0)) VIRTUAL,
 provider TEXT NOT NULL CHECK(provider IN ('bricklink','brickset')),
 provider_kind TEXT NOT NULL,                         -- BrickLink S/P/M/G/B/C/I/O, raw
 provider_key TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('matched','inferred','to_check')),
 method TEXT NOT NULL CHECK(method IN ('external_ids','element','set_number','set_exception','leg_rule',
                                        'composition','composition_leg_rule','bricklink_list','same_number')),
 origin TEXT NOT NULL CHECK(origin IN ('shipped','local','rule','bricklink_list')),
                                                      -- shipped: repo CSV; local: data/mappings/ (e.g. the BrickStore test)
 preferred INTEGER NOT NULL DEFAULT 0 CHECK(preferred IN (0,1)),
 evidence_digest TEXT NOT NULL,
 build_id INTEGER NOT NULL REFERENCES build(id)) STRICT;
CREATE UNIQUE INDEX item_link_key ON item_link(provider, provider_kind, provider_key, item_id, color_key);
CREATE UNIQUE INDEX item_link_preferred ON item_link(item_id, provider, color_key) WHERE preferred=1;
CREATE INDEX item_link_item ON item_link(item_id);

CREATE TABLE color_link(
 id INTEGER PRIMARY KEY,
 color_id INTEGER NOT NULL REFERENCES color(id),
 provider TEXT NOT NULL CHECK(provider IN ('bricklink','lego')),
 provider_key TEXT NOT NULL, provider_name TEXT,      -- BrickLink colour name, from Rebrickable's colour external_ids
 status TEXT NOT NULL CHECK(status IN ('matched','inferred','to_check')),
 method TEXT NOT NULL, origin TEXT NOT NULL CHECK(origin IN ('shipped','bricklink_list','bricklink_api')),
 inverse_preferred INTEGER NOT NULL DEFAULT 0 CHECK(inverse_preferred IN (0,1)),
                                                      -- BrickLink 72 and 77 each come from two Rebrickable colours: this
                                                      -- marks the one a BrickLink colour id resolves to (the migration mint)
 build_id INTEGER NOT NULL REFERENCES build(id)) STRICT;
CREATE UNIQUE INDEX color_link_key ON color_link(provider, provider_key, color_id);
CREATE UNIQUE INDEX color_link_inverse ON color_link(provider, provider_key) WHERE inverse_preferred=1;
CREATE INDEX color_link_color ON color_link(color_id);

-- The optional BrickLink item lists (decision 3), provider-native, reached through item_link or
-- by number in Add. Loading them never creates an item: an item is created (locally) only when
-- the collection references a BrickLink-only number.
CREATE TABLE bricklink_item(
 item_type TEXT NOT NULL CHECK(item_type IN ('S','P','M','G','B','C','I','O')),
 item_no TEXT NOT NULL, name TEXT NOT NULL, name_key TEXT NOT NULL,
 category TEXT, year INTEGER, weight TEXT, dim_x TEXT, dim_y TEXT, dim_z TEXT, alt_item_ids TEXT, size_key TEXT,
 build_id INTEGER NOT NULL REFERENCES build(id),
 PRIMARY KEY(item_type, item_no)) STRICT, WITHOUT ROWID;
CREATE INDEX bricklink_item_name ON bricklink_item(item_type, name_key);

CREATE TABLE bricklink_color(
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, rgb TEXT, type TEXT,
 build_id INTEGER NOT NULL REFERENCES build(id)) STRICT;

CREATE VIRTUAL TABLE item_fts USING fts5(item_id UNINDEXED, kind UNINDEXED, name, keys, tokenize="unicode61");
-- keys = born_key plus every linked provider key. Manual links live in the collection file;
-- Add searches the collection's item_link by number as well (design § 6.3).

-- No indexes on build_id, inventory_part.color_id, element.color_id, picture_url.color_id:
-- their parents are never deleted, so the "every FK has an index" rule protects nothing here.

