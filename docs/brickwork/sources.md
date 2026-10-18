# Brick Work source layer (4.2b)

The source clients write schema v3 `brickwork.db`. The existing screens and
legacy `python -m brickwork.web` commands retain their previous adapters.
The `brickwork` commands below use the new source layer.

```sh
brickwork catalogue import bricklink --from data/bricklink-catalog-src
brickwork catalogue status
brickwork prices refresh 6081-1
brickwork brickset refresh 6081-1 6876-1
brickwork brickset refresh
brickwork sources status
brickwork settings set retail_country DE
```

An empty Brickset set list selects all canonical sets already in `items`.
`BW_DB_PATH` overrides the new store's path; otherwise it uses the explicit `BRICKWORK_DB_PATH` Flask setting or
`data/brickwork.db`.
The rebuildable catalogue lives beside it as `bricklink-catalog.db`.

## Credentials and limits

Credentials are read exclusively from the process environment:

- `BW_BRICKLINK_CONSUMER_KEY`
- `BW_BRICKLINK_CONSUMER_SECRET`
- `BW_BRICKLINK_TOKEN_VALUE`
- `BW_BRICKLINK_TOKEN_SECRET`
- `BW_BRICKSET_API_KEY`

`BW_BRICKLINK_DAILY_BUDGET` is a positive integer, default **4,400**. This
provides a safety margin for other tools sharing the same key within the
account's 5,000-call limit. BrickLink attempts have at least one second of spacing.
Brickset permits 100 charged calls per UTC day; only `getSets` is charged.
`check_key()` and `key_usage_stats()` expose the API's status checks without
charging the local `getSets` budget. `sources status` reads local state and
reports key presence, budget, usage today and last successful job without
making network calls or creating an absent database.

No credentials are written to `.env`, templates or error messages. HTTP
redirects are disabled. Replies are stored verbatim as text except for redaction
of any echoed environment credentials. Transport failures use fixed public
errors; unsuccessful API bodies remain available locally for diagnosis.

## Common interface and transactions

`Source` declares `source`, `source_kind`, `daily_budget`, `minimum_spacing`,
`credentials` and `freshness` (kind to maximum age in days). A new implementation
adds a row to `sources` and its freshness rows without changing the schema.
Freshness is declared here; scheduling and screen rewiring are later work.

Each network attempt first reserves its UTC budget in a separate, immediate
transaction. `settings` holds `source:used:<source>:<UTC-day>` counters,
`source:last_attempt:<source>` pacing timestamps and, if the provider reports
exhaustion, `source:blocked_day:<source>`. `jobs` tracks payload, attempts,
state and next UTC midnight retry time. Reservations commit before HTTP I/O,
so failures and process restarts cannot recover spent calls. Corrupt counters
fail closed. Process locks serialize requests; SQLite serializes reservations
and pacing across processes.

Exhaustion raises `WaitingForBudget(job_id)` and persists
`state='waiting_for_budget'`, rather than failing the job. CLI commands report
this state with a successful exit code. API clients can resume a waiting call
with the same `job_id` and payload after budget becomes available. BrickLink
`price(..., job_id=...)` resumes even a waiting stock fallback; Brickset
`refresh(numbers, job_id=...)` resumes one batch. This layer does not run a
background job scheduler.

The reply, normalized tables, audit events and job completion are written in
one transaction. A savepoint rolls back partial normalization on invalid data
while preserving the raw reply and failure status. `source_records.source_id`
contains `<job-id>:<attempt>` to retain every reply, including resumed attempts.
Every mutation appends an `events` row with `via='import'` in the same transaction.
Large audit values use a SHA-256 digest and length rather than duplicating the
raw catalogue payload in the event log.

## Table mappings

| Source / operation | Local data |
| --- | --- |
| BrickLink catalogue | Separate indexed `items` table and metadata in `bricklink-catalog.db`; raw XML and successful import job in `brickwork.db` |
| BrickLink item information | Canonical `items` name/category/year, all returned fields in `item_properties` |
| BrickLink subsets | Canonical parent/child `items`, placeholder `colors`, replaced source-owned `inventory_lines` |
| BrickLink colours | `colors` name/type, preserving existing RGB |
| BrickLink price guide | Decimal strings in `price_observations`, latest guide/condition/region/currency in `price_current` |
| BrickLink orders and order items | Full reply in `source_records`; order-ledger ingestion remains a later step |
| Brickset `getSets` | `item_properties` metadata, `id_match` set numbers, retail `price_observations` and `price_current` |
| All API operations | Every raw reply in `source_records`, budget/job state and import events |

Subset `quantity` already includes `extra_quantity`: both are retained, and
extras are never added to the quantity. Duplicate child/colour lines are
summed. Counterparts and alternates are excluded. Sets retain both parts and
whole minifigures, while minifigure inventories retain parts.

BrickLink prices use the configured `bricklink_region` (default `eu`) and
`bricklink_currency` (default `EUR`). Worldwide (`all`) omits the API region
parameter. An empty sold guide is stored and followed by a stock guide. New
and used prices are separate; all monetary values remain decimal strings.

Brickset sends a comma list of at most 500 set numbers with `pageSize=500`.
Existing `id_match` aliases are used; a bare numeric canonical number maps to
`<number>-1`. Returned unmatched numbers stay in `id_match` as `unmatched`
without creating a purported canonical item. Brickset's `setID`, theme,
subtheme, year, pieces, minifigs, name and availability are source properties.
Retail price and availability dates come only from `LEGOCom.<retail_country>`.
The default is `DE`; supported documented countries are DE/EUR, US/USD,
UK/GBP and CA/CAD. No market prices are fetched from Brickset.

The catalogue importer streams every XML file in the input directory, identifies
items by `ITEMTYPE`, and requires all eight types S/P/M/G/B/C/I/O before installation.
Filenames can be `catalog-Sets.xml`, `Books.xml` or any other `.xml` name.
Names are HTML-unescaped and whitespace-normalized. Duplicate keys or malformed
files reject the rebuild. The lock, temporary build, fsync, atomic replace and
previous-version rollback protocol are reused from `web/bl_catalog.py`.
Raw XML is retained for each import. File installation and the store transaction
are separate because they span two databases; the catalogue is rebuildable.

Brickset request and fixture shapes follow its [API v3 documentation](https://brickset.com/article/52664/api-version-3-documentation).
The synthetic fixtures and mocked transport tests do not make network calls.

## Import pipeline and Rebrickable (4.2c)

The [pipeline](pipeline.md) composes these source operations into independent,
retryable steps and supplies the reusable Add progress component. Rebrickable's
API client uses `BW_REBRICKABLE_API_KEY`, a configurable
`BW_REBRICKABLE_DAILY_BUDGET` (default 1,000), at least one second of durable
spacing, and persisted short waits for remote throttling. Its part, colour and
minifigure identifiers remain in `id_match`. Images are downloaded and indexed
in `item_images`; URLs are provenance and must never be used as hot-links.

## Stored keys and the embedded worker (4.11g)

Source keys can come from the environment (`BW_BRICKLINK_CONSUMER_KEY`,
`BW_BRICKLINK_CONSUMER_SECRET`, `BW_BRICKLINK_TOKEN_VALUE`,
`BW_BRICKLINK_TOKEN_SECRET`, `BW_REBRICKABLE_API_KEY`, `BW_BRICKSET_API_KEY`) or be
entered in Manage > Catalogues & keys, or through `PUT /api/v1/sources/{source}/key`.
Entered keys are stored encrypted (Fernet) in `source_keys`; the encryption secret is
`BW_SECRET_KEY`, a Fernet key (generate one with
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).
Without it key entry is disabled and environment keys keep working. A complete
environment key set wins over a stored one. Keys are write-only: no page, API response,
log line, error, event or database export contains a key, a fragment or the ciphertext.

Queued jobs are drained by an embedded worker started with the web app or the first
queued API request. Catalogue XML files are read from `bricklink-catalog-src/` beside the database. Set `BW_EMBEDDED_WORKER=0` on headless installs and run
`brickwork worker` instead; `POST /api/v1/jobs/drain` runs one drain on demand.
