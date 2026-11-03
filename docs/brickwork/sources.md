# Brick Work source layer (4.0)

The source clients write the 4.0 collection file (`brickwork.db`). A source is one provider's client: `BrickLink`, `Rebrickable`,
`Brickset` (and `Brickognize` for photos, with the Identify screen). The pipeline's `pictures`, `metadata` and `market_price` steps call
them through handlers ([pipeline](pipeline.md)); the part lists are `store4.jobs`' (`bricklink_subsets`, `rebrickable_set`). The
design is in the [4.0 design](../data-model-4.0/data-model-design.md) (§ 3.2, § 3.8, § 5.2, § 6.8).

## Credentials and limits

Keys come from the environment first (all of a source's variables), then from the encrypted `source_key` table (Fernet, secret
`BW_SECRET_KEY`; `core.keys`, installed at start as the provider `store4.keys` reads):

- BrickLink: `BW_BRICKLINK_CONSUMER_KEY`, `BW_BRICKLINK_CONSUMER_SECRET`, `BW_BRICKLINK_TOKEN_VALUE`, `BW_BRICKLINK_TOKEN_SECRET`
- Rebrickable: `BW_REBRICKABLE_API_KEY`; Brickset: `BW_BRICKSET_API_KEY`

Daily budgets: BrickLink `BW_BRICKLINK_DAILY_BUDGET` (default 4,400, a margin under the account's 5,000), Rebrickable
`BW_REBRICKABLE_DAILY_BUDGET` (1,000), Brickset 100 (only `getSets` is charged; `checkKey` and `getKeyUsageStats` are not). BrickLink and
Rebrickable calls are at least one second apart. The counters are the rows of `source_budget` (source, UTC day, `used`, `blocked_until`,
`last_attempt_at`), shared with `store4.jobs`, which counts its own calls on the same rows. The Rebrickable catalogue pictures are plain
downloads and count against nothing.

No key is written to a template, a log or an error text: replies are stored redacted, transport failures have fixed texts.
Redirects are refused.

## One call

`Source.request` (core/sources/base.py): refuse a disabled source (`source.enabled`) or a missing key before anything is built or counted;
count the call (`reserve`: the daily budget, a provider's pause, the spacing) or raise `WaitingForBudget(retry_at)`; make the HTTP request
outside any write transaction; keep the reply in `source_record` under the pipeline job (unique over source, kind, key and digest, so the
same reply twice is one record); normalise in one savepoint. A savepoint that fails rolls its writes back and keeps the reply with
`status='failed'`. A provider's own rate pause (HTTP 429 or "throttled", Brickset's "API limit exceeded") is written as
`blocked_until` and honoured by every client and job of the source. A 401 or 403 carrying the provider's own JSON error is `KeyRejected`;
an HTML or empty answer says nothing about the key.

## What each source writes

| Source / operation | Local data |
| --- | --- |
| BrickLink price guide | `price_observation` (decimal strings, words for the condition, slot `bricklink_new`/`bricklink_used`, the region and currency settings, `provider_key` like `P:3023/1` or `S:6081-1`) and `price_current`; an empty sold guide is stored and followed by the stock guide. An `inferred` BrickLink link the reply proves right becomes `matched` (`method='bricklink_api'`, `origin='api'`). |
| BrickLink orders | the full reply in `source_record`; the order ledger is the orders piece's |
| Brickset `getSets` | `item_property(source='brickset')` (setID, theme, subtheme, year, pieces, minifigs, name, category, availability, the first and last date at LEGO) and the retail `price_observation` (`guide='retail'`, slot `retail`, the `retail_country` setting: DE/EUR, US/USD, UK/GBP, CA/CAD). A set Brickset does not know gets `item_provider_status(brickset, unmatched, no_match)`. |
| Rebrickable part record | the BrickLink evidence in `external_ids`: exactly one id is a `matched/external_ids` link, none or several `item_provider_status(bricklink, unmatched, no_match)`; a `manual` link is never replaced and a confirmed one never downgraded. |
| Pictures | `picture` rows and files under `data/images/<source>/<kind>/<sha256>.<ext>`; see below. |

BrickLink prices are for the item's resolved BrickLink key and colour (`items.bricklink_key`, design 3.2). An item without one is
unidentified: the step ends `done` with the code `unidentified` and nothing is called (design 3.8). Brickset is asked by a confirmed
`brickset` link, else the Rebrickable number of a Rebrickable-born set (`6081-1`), else the BrickLink number of a BrickLink-born set
(`6081` is read as `6081-1`); up to 500 numbers go in one call.

## Pictures

Three sources (`rebrickable_dump`, `bricklink`, `rebrickable_api`), in the order of `source_priority.pictures` per kind (design 6.8; the
defaults are in [the pipeline](pipeline.md)). `core.pictures` has the handler of each source, `picture_known(db, item_id, color_id)` (the
Add review's warning: a stored picture, a catalogue `picture_url`, a resolvable BrickLink number, or a Rebrickable key and number) and the
bulk refresh (`state`, `selection`, `queue`). A download is a plain GET of an https URL on a host of the source, no redirects, at most 20 MB,
verified as an image before anything is written; the file is written first, then the row (a `picture:stored` event). Thumbnails are
`core.thumbnails`, generated on first request and cached under `data/thumbs`.

## Stored keys and the embedded worker

Keys can be entered in Manage > Catalogues & keys (`core.keys.save`, `archive`; each is an event with Undo, and an export copy loses
every key, `keys.strip`). `drainer.start` (the embedded worker) and `brickwork worker` register the source handlers and run the queue
until nothing is pending; `BW_EMBEDDED_WORKER=0` leaves draining to `brickwork worker`.
