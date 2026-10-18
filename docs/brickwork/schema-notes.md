# Brick Work v3.2 schema and migration definitions

Retired screens continue using their existing stores. Add and Tools & Admin
use the new store. The CLI migration runs without a Flask application
context, network access, source schema initialization or legacy writers.

Schema 3.1 (Ulf, 2026-10-13) extends the single `wishlist` table because
v3's `(item_type,item_no)` key could express neither colour nor quantity.
`schema_meta.version` records the latest exact text `3.2`. Re-run the read-only
legacy migration into a new output to build this schema; existing v3 outputs
are not automatically upgraded by opening a connection.

Wishlist rows have an integer `id`, a colour FK and `quantity >= 1` (default 1).
Parts require a colour; S/M/I/O/G/B/C require NULL. The partial unique index
on `(item_type,item_no,color_id IS NULL,coalesce(color_id,0))` covers live rows
only. Archived keys are reusable, and restoring a conflicting archive fails.
Wishlist flags refer to the decimal row id as text. Triggers reject orphan
flags, deletes and changes to id/item/colour while flagged; quantity edits
remain allowed. Admin identity correction temporarily removes and restores
flags for each stable row id in the same audited transaction.

Migration ids are original wishlist rowids, ordered by rowid. The measured
legacy mapping has 182 S wishes and no `[part,color]` wishes: colour is NULL,
quantity is 1, metadata joins precede manual corrections, and true wishlist
owner flags map through source key → row id. JSON `[part,color]` wishes use
part and colour matching, fail if the colour is unresolved, and retain quantity
1. Proof counts and full row checksums include id, colour and quantity and
report the number of coloured wish keys. Synthetic tests cover both forms
and byte-identical migration outputs; the private snapshots are not present
in this worktree.

Add matches live wishes by item and colour. An explicit “Add to the wished
quantity” choice increments the same row. A different colour creates a new
row. Archived matching rows may be restored with the requested quantity;
Undo restores their previous quantity and metadata exactly. New rows are
archived on Undo. Notes contain only user text. XML COLOR/MINQTY reach the
columns unchanged for parts. Price refresh and pipeline colour discovery
include live wishes; Toni's Wishlist navigation count counts live wish rows.
Retired legacy screens continue using their separate old stores.

1. **Typed placeholder parents and children.** Every item reference is a pair
   pointing at `items(item_type,item_no)`. `?` is an ordinary supported type.
   `copy_parts.parent_minifig_type` accompanies `parent_minifig`; both are NULL
   for a direct part. Set-only references also have a type column, allowing an
   unresolved set without copying a source id into a canonical `S` key.
   Recognition and receipt references receive the same typing. Historical
   display strings, opaque import keys and raw source evidence remain intact.

2. **Evidence-only matches.** `id_match` has a real nullable composite FK.
   Unreferenced targets have both target columns NULL; the proposed typed target
   stays in `evidence_json` with all forward/reverse/cache/decision evidence.
   The status and method describe that evidence. Only the referenced item union
   creates catalogue rows. Part-colour evidence is grouped under the source
   part identity; a colour is projected only where the accumulated evidence
   agrees. Ambiguous template children use parent source identity plus JSON
   ordinal, retain every candidate, and reference distinct placeholder rows.
   Decisions are an external input, never a repository fixture or committed
   collection record. Inventory matching calls `web.idmatch.match`; canonical
   cache projections preserve existing bridges, rather than rematching them.

3. **Local pictures and own photos.** `item_images` retains rows only for
   referenced cache images whose local files exist, including repeated URLs backed by the same file. `local_path`
   is NOT NULL and must satisfy the managed-path CHECK. Managed paths are
   relative `data/images/…` paths; traversal outside that tree is rejected.
   Migration checks the image/image_id fields for explicitly named existing
   files beneath the input database directory's `data/images/` tree, including
   the old `<set/figure/image_id>.jpg` cache naming in its typed subfolders. It neither
   moves files nor guesses local files from URLs. Absent bytes produce no
   image row; the original URL and cache fields stay in raw source records. Dimensions remain NULL for legacy files.
   A photo may carry `kind='own'`, copy_id or stock_id, caption and taken_at.
   The supplied snapshots contain no measured own photos or managed files;
   recognition thumbnail flags are retained, without claiming to verify bytes.

4. **Source and freshness defaults.** The six sources are seeded enabled, with
   priority_settings NULL. Each has prices=30 days, metadata=365 days and
   pictures=NULL (never stale). These **18 new rules** implement the explicit
   task instruction and supersede the mapping's zero historical TTL rows.
   The proof documents that amendment; historical fetch dates are never
   invented. All six import steps and their per-type fallbacks live in
   `settings.source_priority`; an absent fallback stays absent.

5. **Audit, search and future DDL.** Events are record-level migration baselines
   in the insertion transaction, with the full mapped tuple, typed table/key,
   NULL old value and via=migration. The one reproducible baseline timestamp is
   the decisions' date at UTC midnight, not a manufactured historical edit or
   a wall-clock value that would break byte determinism. UPDATE, DELETE and
   INSERT OR REPLACE on an existing event id are rejected. FTS5 uses unicode61
   and exactly one item document, containing number, name and properties sorted
   by key/source. Item/property insert/update/delete triggers rebuild affected
   documents, including old keys after re-keying. Archives are nullable dates
   on copies, stock, wishes and lots. Jobs have source, item, state, retry,
   attempts, payload and budget fields. instruction_files and match_history
   retain the Phase 12 fields and typed references. The empty ledger keeps all
   mapped columns, adds composite item FKs and explicit allocation target type
   plus copy/stock FKs. Every FK has an index; nullable stock/price composite
   keys use expression indexes that distinguish NULL from empty text.

## Migration and proof contract

`brickwork migrate --app APP --web WEB --decisions FILE
--catalogue /path/to/bricklink-catalog.db --catalogue-src /path/to/xml
--out DB --report DIR [--replace]` accepts the app catalogue database and a
separate BrickLink XML source directory. Gear decisions are validated against
`items` when the database contains any `G` items (the 4.2b loader loads all
eight types); an absent decided Gear item then fails validation. Only a database
without `G` items falls back to `Gear.xml` in `--catalogue-src`. Every other
manual/confirmed canonical decision is validated against the database. The old
`--catalogue DIR` form with `blcat.db` and adjacent `Gear.xml`, and the direct
`blcat.db` form, remain supported with a deprecation warning; without
`--catalogue-src`, XML fallback uses the database directory. Legacy databases use SQLite URI
mode=ro and query_only. Input hashes are compared before publication. Money uses
Decimal(str(value)), without rounding; existing decimal text is validated and
retained. Unix dates become UTC ISO-8601; existing text dates and NULLs stay.

Schema and data run in one transaction in an exclusively created candidate
file. Deferred FKs permit dependency-independent insertion but must pass the
final FK check. Failed proof rolls back and removes only that candidate;
existing output remains untouched. --replace refuses inputs, symlinks and
outputs with SQLite sidecars. Passed output is checkpointed and atomically
published. Stable source rowid/history id/JSON ordinal ordering fixes surrogate
ids, duplicate multiplicity, price ties, raw envelopes and event order.

The proof rebuilds the mapping from freshly opened read-only inputs and compares
all target columns to database read-back, including every raw cache envelope.
It reports table and per-row content hashes, non-NULL fills, state sums, every
review, transformed lineage and approved drops. Recognizable snapshot source
counts select the fixed approved target counts, amended only by the number
of omitted image cells without local files and carried cache evidence/records;
small synthetic fixtures use input-derived counts. All target columns still
undergo checksum verification. This is an offline transformation proof, not
a claim that absent original API bodies or picture files were recovered. The migration
also verifies the approved copy_check_state drop against source flags and
sorted non-spare missing-part/whole-figure tuples. Populated Phase 12/ledger
inputs outside this gate's empty-source contract are rejected.

The mapping's empty cache `part_image_mappings` may acquire rows before
migration. Its rows are carried under source `rebrickable`, kind `part-image`:
rows with `part_num` become grouped `id_match` evidence, preserving every
original `part_num`, `bricklink_part`, `checked_at` and `error` field and duplicate
row multiplicity. Unreferenced BrickLink targets stay evidence-only; cache
rows do not create collection items. Rows without a source identity become
`source_records` with stable source-rowid keys. Every input cache row is listed
under **Cache rows carried** in both proof formats. Non-cache approved empty
drops, including `legacy_transfer_receipts`, still stop migration if populated.
This and the local-image rule amend the historical 4.2 mapping's empty-cache
and URL-only image counts.

## First-run snapshot blocker and approved Run 2 resolution (2026-10-12)

The supplied `bricklink_colors` contains 214 rows, with ids 1 through 255 and
**no row for BrickLink 0 or 117**. `color_map` refers to both. The approved
mapping requires retaining all 214 colour rows and also explicitly requires
colour 0 to exist. Its migrated references therefore cannot satisfy real
foreign keys: 115 copy_parts, 112 id_match and 82 item_images references fail
(309 total). All projected table counts and content hashes match otherwise.
The first run added no rows and rolled back its output. Run 2 explicitly
approves adding these two referenced BrickLink colours from existing evidence:

- **0:** name `(Not Applicable)`, stated by all 115 matching
  `rebrickable_parts.bricklink_color_name` fields, with `color_map` pairing
  BrickLink 0 with Rebrickable 9999.
- **117:** name NULL, with `color_map` pairing it with Rebrickable 76;
  no collection rows reference it. The 4.2b colour refresh supplies its name.

Both retain NULL type/rgb rather than invented catalogue metadata. Their full
table-labelled evidence is stored in `source_records` with source `rebrickable`,
kind `migration`, source_id `colors:0` / `colors:117`, status `evidence` and NULL
fetched_at. `migration` is the evidence kind; the six-source registry remains
unchanged. This adds two colours (216 total) and two records (14,089 total).
The proof lists both under **Colours added from evidence**. These approved
definitions apply only when the colours are referenced and absent; existing
catalogue rows are preserved. A missing bridge or conflicting colour-0 name
fails visibly; unrelated absent colours still fail the final FK proof.
Run 2 passes all table counts/checksums, integrity and foreign-key checks and
publishes the new database.

## 4.2c additive import runtime DDL

`brickwork/core/import.sql` adds `import_steps`, `import_calls` and
`import_owners` when the pipeline is initialized. The first tracks the six steps,
the second checkpoints successful calls and waiting source jobs, and the third
prevents simultaneous local workers while allowing dead-process recovery. Every
foreign key has an index. `jobs.source='import'` is the parent job. No migrated
table definition, mapping or proof expectation changes. Priority continues to
live in `settings.source_priority`; `import_order:TYPE` adds per-type step order.
See the [pipeline contract](pipeline.md) for states, events and worker operation.

## 4.3d Orders and Storage

The existing ledger tables support document review, line receipts and explicit
copy/stock allocation without DDL changes. New app allocations are atomic and
store reversible row snapshots in `events`, leaving historical ledger records
as provenance. See [Orders and Storage](../web-ui/orders-storage-4.3d.md).

Schema 3.2 (Ulf, 2026-10-13) adds nullable `storages.archived_at TEXT`.
The approved archive-not-erase rule now covers storage locations, enabling
location deletion and Undo of location creation without losing UUIDs or
historical references. This is the only new column; no new table is needed.
`schema_meta` uses the same exact-version CHECK and initial row as 3.1, now
`3.2`. As with 3.1, existing outputs are not upgraded on connect: build a new
output with the read-only legacy migration. All migrated locations explicitly
receive `archived_at=NULL`; mapping and read-back proof include this column
with zero non-null values and unchanged source UUID/name pairs.

Active lists, counts, pickers and destination validation use
`archived_at IS NULL`. Archive refuses live copies, loose stock or lots unless
the user explicitly chooses to move everything to Not stored. That action
moves live storage references and timestamps (lots have no update timestamp)
and archives the location in one transaction with app events and one receipt.
Archived stock/copies/lots and historical identification context keep their
original storage reference. Undo restores exact old rows, guarded against
later edits; creation Undo archives an empty location. A move Undo cannot
restore a live destination that is still archived.

## 4.8b Wish maximum currency

Decided by Ulf (2026-10-15): "add a currency". `wishlist` gains one nullable
column, `max_price_currency TEXT` (a currency code of 3 to 8 letters, upper case, the
same shape as `purchase_currency` and `current_value_currency`). It is the only change:
no table, index or other column moves, and `schema_meta` stays `3.2` (its CHECK is an
exact-version constraint; this is an additive column, not a new schema generation).

- **Fresh outputs.** `schema.sql` declares the column. The legacy projection fills it
  for every migrated wish that has a `max_price` with the configured BrickLink currency
  (`bricklink_currency` from the legacy price settings, default `EUR`) and leaves it
  NULL for wishes without a max, so the read-back proof covers it and byte
  determinism holds.
- **Existing outputs.** `brickwork/core/upgrade.py` (`upgrade_wish_currency`)
  adds the column and applies the backfill rule below. `connect()` runs it
  automatically when a file opened for writing lacks the column or holds a limit without
  a currency; a read-only open performs the same upgrade once on a short writable
  handle and reopens; if that write fails (read-only file or deployment, locked
  database) the failure is remembered per path for 300 seconds or until the file
  changes, readers keep working without the column, and **a read-only deployment must
  run the command below once**. The column check happens inside the write lock and a
  concurrent upgrader's "duplicate column" is treated as already added. It can also be
  run by hand:
  `python -m brickwork.core.upgrade data/brickwork.db`.
- **Backfill rule.** Every wish with a `max_price` and no currency receives the
  `bricklink_currency` setting of that database (`EUR` when the setting is absent or
  empty). Wishes without a max stay NULL. The step is re-runnable: the column is added
  once, only wishes with a max and no currency are touched, a second run changes
  nothing, and no other column is written. It writes no `events` row, because it is a
  migration and not a user edit; the count and currency it applied are returned by the
  function (`column_added`, `backfilled`, `currency`) and recorded in the
  [migration report](migration-report.md#48b-wish-limit-currency).
- **Writes.** `collection.save(entity='wish')` takes `max_price_currency` with
  `max_price`. A max without a currency keeps the currency the wish already has, else the
  configured one; a currency without a max is rejected; clearing the max clears the
  currency. The audited `events` row snapshots both columns; Undo restores both.
- **Reads.** A wish limit is displayed with its currency; a limit without one (only
  possible in a read-only file that could not be upgraded) shows the bare number.

See [design diff 4.8b](design-diff-48b.md) for the Wishlist and Under max behaviour.
